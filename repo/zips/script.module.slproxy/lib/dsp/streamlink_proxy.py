"""
StreamLinkProxy
based on XBMCLocalProxy by
Copyright 2011 Torben Gerkensmeyer

Modified for Livestreamer by your mom 2k15

Modified for StreamLink by jairoxyz 2k18/19

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
MA 02110-1301, USA.
"""

import xbmc
import xbmcgui
import xbmcvfs
import sys
import traceback  # noQA
import os

# Fix LibreELEC/CoreELEC: Force use of addon libraries
for lib in ['script.module.streamlink', 'script.module.requests', 'script.module.six']:
    path = xbmcvfs.translatePath('special://home/addons/%s/lib' % lib)
    sys.path.insert(0, path)

import errno
import re
import time
import json
import base64
import threading
import socket
import struct
import requests
import six
import binascii

if six.PY3:
    from urllib.parse import urlparse
    from urllib.parse import urljoin
    from urllib.parse import unquote
    from urllib.parse import quote
    from urllib.parse import quote_plus
    from urllib.parse import parse_qsl
    from urllib.parse import urlencode

    # from typing import List, NamedTuple, Optional, Union

elif six.PY2:
    # Python 2.7
    from urlparse import urlparse
    from urlparse import urljoin
    from urlparse import parse_qsl
    from urlparse import urlencode
    from urllib import quote
    from urllib import quote_plus
    # from .typing2 import List, NamedTuple, Optional, Union

if six.PY3:
    from http.server import BaseHTTPRequestHandler
    from http.server import HTTPServer
elif six.PY2:
    # Python 2.7
    from BaseHTTPServer import BaseHTTPRequestHandler
    from BaseHTTPServer import HTTPServer

if six.PY3:
    from socketserver import ThreadingMixIn
elif six.PY2:
    # Python 2.7
    from SocketServer import ThreadingMixIn

import ssl
from urllib3.poolmanager import PoolManager
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except Exception:
    from requests.packages.urllib3.util.retry import Retry


# HTTPServer errors
ACCEPTABLE_ERRNO = (
    errno.ECONNABORTED,
    errno.ECONNRESET,
    errno.EINVAL,
    errno.EPIPE,
)
try:
    ACCEPTABLE_ERRNO += (errno.WSAECONNABORTED,)
except AttributeError:
    pass  # Not windows


# aes stuff - custom crypto implementation
_dec = False
_crypto = 'None'

try:
    import Cryptodome
    sys.modules['Crypto'] = Cryptodome
    from Cryptodome.Cipher import AES
    _dec = True
    _crypto = 'pyCryptodome'
except ImportError:
    try:
        from Crypto.Cipher import AES
        _dec = True
        _crypto = 'pyCrypto'
    except ImportError:
        xbmc.log('[StreamLink_Proxy] no Crypto lib found. Encrypted streams won\'t play')
        _dec = False


# streamlink imports
from streamlink import Streamlink
from streamlink.stream import hls, HLSStream, HTTPStream
from streamlink.exceptions import StreamError, PluginError, NoPluginError
from streamlink.plugin.api import useragents
from streamlink.utils import LazyFormatter
# from streamlink.stream.hls_playlist import Key, M3U8, Map, Segment


# TLS 1.2 adapter for older nginx behind CF
class TLS12HttpAdapter(HTTPAdapter):
    """"Transport adapter that forces the use of TLS v1.2."""
    def init_poolmanager(self, connections, maxsize, block=False):
        tls = ssl.PROTOCOL_TLSv1_2 if six.PY3 else ssl.PROTOCOL_TLSv1
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize,
            block=block, ssl_version=tls)


# SLProxy SL method implementations #
#####################################

# Sequence class used in type declarations, throws error in Py2
# class Sequence(NamedTuple):
#     num = None  # type: int
#     segment = None  # type: Segment

# !!! TODO: https://mypy.readthedocs.io/en/stable/cheat_sheet.html !!! #
########################################################################

# num to IV
def num_to_iv(n):
    return struct.pack(">8xq", n)


def event_is_set(evt):
    """Py2/Py3 compatible threading.Event checker."""
    if hasattr(evt, "is_set"):
        return evt.is_set()
    return evt.isSet()


try:
    BrokenPipeError
except NameError:
    BrokenPipeError = socket.error

try:
    ConnectionResetError
except NameError:
    ConnectionResetError = socket.error


STOP_EXCEPTIONS = (BrokenPipeError, ConnectionResetError, socket.error)


def is_client_disconnect(exc):
    if isinstance(exc, STOP_EXCEPTIONS):
        err_no = getattr(exc, "errno", None)
        if err_no is None:
            return True
        return err_no in ACCEPTABLE_ERRNO
    return False


class TTLCache(object):
    def __init__(self, max_entries=256):
        self._max_entries = max_entries
        self._data = {}
        self._lock = threading.Lock()

    def get(self, key):
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key, value, ttl):
        now = time.time()
        expires_at = now + max(1, int(ttl))
        with self._lock:
            if len(self._data) >= self._max_entries:
                # Remove oldest entry first to keep memory bounded.
                oldest = min(self._data.items(), key=lambda kv: kv[1][0])[0]
                self._data.pop(oldest, None)
            self._data[key] = (expires_at, value)


HTTP_CACHE = TTLCache(max_entries=512)
LOW_LATENCY_CHUNK = 16 * 1024
STEADY_CHUNK = 64 * 1024


def build_retry():
    kwargs = {
        "total": 4,
        "connect": 4,
        "read": 4,
        "backoff_factor": 0.2,
        "status_forcelist": [429, 500, 502, 503, 504],
        "raise_on_status": False,
    }
    try:
        return Retry(allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]), **kwargs)
    except TypeError:
        return Retry(method_whitelist=frozenset(["GET", "HEAD", "OPTIONS"]), **kwargs)


def build_http_session(headers=None, verify=True):
    ses = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=64,
        pool_maxsize=64,
        max_retries=build_retry()
    )
    ses.mount("http://", adapter)
    ses.mount("https://", adapter)
    ses.verify = verify
    if headers:
        ses.headers.update(headers)
    return ses


def iter_low_latency_chunks(response, stop_event=None, initial_chunk=LOW_LATENCY_CHUNK, max_chunk=STEADY_CHUNK):
    chunk_size = max(4 * 1024, int(initial_chunk))
    max_chunk = max(chunk_size, int(max_chunk))
    raw = response.raw

    while True:
        if stop_event is not None and event_is_set(stop_event):
            break
        chunk = raw.read(chunk_size, decode_content=True)
        if not chunk:
            break
        yield chunk
        if chunk_size < max_chunk:
            chunk_size = min(chunk_size * 2, max_chunk)


def build_xtream_stream_candidates(parsed_url, params):
    username = params.get("username")
    password = params.get("password")
    if not username or not password:
        return []

    stream_id = params.get("stream") or params.get("stream_id") or params.get("live_id") or params.get("vod_id")
    if not stream_id:
        return []

    output = params.get("output") or params.get("container_extension") or params.get("extension") or "ts"
    output = six.ensure_str(output).lower()
    if output not in ("ts", "m3u8", "mp4", "mkv", "aac", "mp3"):
        output = "ts"

    action = six.ensure_str(params.get("action", "")).lower()
    content_type = six.ensure_str(params.get("type", "")).lower()

    base = "{0}://{1}".format(parsed_url.scheme, parsed_url.netloc)
    ordered = []

    if "vod" in action or content_type in ("vod", "movie"):
        ordered = ["movie", "series", "live"]
    elif "series" in action or content_type == "series":
        ordered = ["series", "movie", "live"]
    else:
        ordered = ["live", "movie", "series"]

    candidates = []
    for segment in ordered:
        candidates.append("{0}/{1}/{2}/{3}/{4}.{5}".format(base, segment, username, password, stream_id, output))
    return candidates


def maybe_resolve_xtream_player_api(url, headers=None):
    try:
        parsed = urlparse(url)
        if "/player_api.php" not in parsed.path:
            return url
        params = dict(parse_qsl(parsed.query))
        if not params.get("username") or not params.get("password"):
            return url
    except Exception:
        return url

    cache_key = "xtream::{0}".format(url)
    cached = HTTP_CACHE.get(cache_key)
    if cached:
        return cached

    ses = build_http_session(headers=headers, verify=False)
    try:
        probe = None
        # Some panels redirect player_api directly to a playable URL.
        try:
            probe = ses.get(url, headers=headers, allow_redirects=True, stream=True, timeout=(4, 12))
            ctype = six.ensure_str(probe.headers.get("Content-Type", "")).lower()
            if probe.status_code < 400 and (
                "video/" in ctype or "mpegurl" in ctype or ".m3u8" in six.ensure_str(probe.url)
            ):
                resolved = probe.url
                HTTP_CACHE.set(cache_key, resolved, 300)
                return resolved
        except Exception:
            pass
        finally:
            try:
                probe.close()
            except Exception:
                pass

        for candidate in build_xtream_stream_candidates(parsed, params):
            resp = None
            try:
                resp = ses.get(candidate, headers=headers, allow_redirects=True, stream=True, timeout=(4, 12))
                if resp.status_code < 400:
                    resolved = resp.url
                    HTTP_CACHE.set(cache_key, resolved, 300)
                    return resolved
            except Exception:
                continue
            finally:
                if resp is not None:
                    try:
                        resp.close()
                    except Exception:
                        pass
    finally:
        ses.close()

    return url


# override SL decryptor function
def create_decryptor(self, key, sequence):
    # ##### type: (hls.HLSStreamWriter, Key, int) -> AES
    if key.method != "AES-128":
        raise StreamError("Unable to decrypt cipher {0}", key.method)

    if not self.key_uri_override and not key.uri:
        raise StreamError("Missing URI to decryption key")

    if self.key_uri_override:
        p = urlparse(key.uri)
        key_uri = LazyFormatter.format(
            self.key_uri_override,
            url=key.uri,
            scheme=p.scheme,
            netloc=p.netloc,
            path=p.path,
            query=p.query,
        )
    else:
        key_uri = key.uri

    if self.key_uri != key_uri:
        # zoom_key = self.reader.stream.session.options.get("zoom-key")
        # zuom_key = self.reader.stream.session.options.get("zuom-key")
        ply_key = self.reader.stream.session.options.get("ply-key")
        livecam_key = self.reader.stream.session.options.get("livecam-key")
        saw_key = self.reader.stream.session.options.get("saw-key")
        your_key = self.reader.stream.session.options.get("your-key")
        mama_key = self.reader.stream.session.options.get("mama-key")
        tele_key = self.reader.stream.session.options.get("tele-key")
        tinyurl_key = self.reader.stream.session.options.get("tinyurl-key")
        sports24_key = self.reader.stream.session.options.get("sports24-key")
        flowcable_key = self.reader.stream.session.options.get("flowcable-key")
        hls_aes_key = self.reader.stream.session.options.get("hls-aes-key")
        # custom_uri = self.reader.stream.session.options.get("custom-uri")

        # if zoom_key:
        #     zoom_key = zoom_key.encode() if six.PY3 else zoom_key
        #     _tmp = (base64.urlsafe_b64encode(zoom_key + base64.urlsafe_b64encode(key_uri.encode() if six.PY3 else key_uri)))
        #     _tmp = _tmp.decode() if six.PY3 else _tmp
        #     uri = 'http://www.zoomtv.me/k.php?q=' + _tmp
        # elif zuom_key:
        #     zuom_key = zuom_key.encode() if six.PY3 else zuom_key
        #     _tmp = (base64.urlsafe_b64encode(zuom_key + base64.urlsafe_b64encode(key_uri.encode() if six.PY3 else key_uri)))
        #     _tmp = _tmp.decode() if six.PY3 else _tmp
        #     uri = 'http://www.zuom.xyz/k.php?q=' + _tmp
        if ply_key:
            uri = base64.urlsafe_b64decode(ply_key.encode() if six.PY3 else ply_key) + base64.urlsafe_b64encode(key_uri.encode() if six.PY3 else key_uri)
            uri = "https://www.plylive.me" + (uri.decode() if six.PY3 else uri)
        elif livecam_key:
            h = urlparse(unquote(livecam_key)).netloc
            h = h.encode() if six.PY3 else h
            q = urlparse(unquote(livecam_key)).query
            q = q.encode() if six.PY3 else q
            uri = 'https://%s/kaesv2?sqa=' % (h + base64.urlsafe_b64encode(q + base64.b64encode(key_uri.encode() if six.PY3 else key_uri)))
            uri = uri.decode() if six.PY3 else uri
        elif saw_key:
            if 'foxsportsgo' in key_uri:
                _tmp = key_uri.split('/')
                uri = urljoin(saw_key, '/m/fream?p=' + _tmp[-4] + '&k=' + _tmp[-1])
            elif 'nlsk.neulion' in key_uri:
                _tmp = key_uri.split('?')
                uri = urljoin(saw_key, '/m/stream?' + _tmp[-1])
            elif 'nlsk' in key_uri:
                _tmp = key_uri.split('?')
                uri = 'http://bile.level303.club/m/stream?' + _tmp[-1]
            elif 'nhl.com' in key_uri:
                _tmp = key_uri.split('/')
                uri = urljoin(saw_key, '/m/streams?vaa=' + _tmp[-3] + '&va=' + _tmp[-1])
            else:
                uri = key_uri
        elif mama_key:
            if 'nlsk' in key_uri:
                _tmp = key_uri.split('&url=')
                uri = 'http://mamahd.in/nba?url=' + _tmp[-1]
        elif your_key:
            if re.search(r'playback\.svcs\.mlb\.com|mlb-ws-mf\.media\.mlb\.com|mf\.svc\.nhl\.com', key_uri, re.IGNORECASE) is not None:
                try:
                    _ip = your_key.split('?')[1]
                    uri = re.sub(r'playback\.svcs\.mlb\.com|mlb-ws-mf\.media\.mlb\.com|mf\.svc\.nhl\.com', _ip, key_uri, re.IGNORECASE)
                except:
                    pass
            elif 'mlb.com' in key_uri:
                _tmp = key_uri.split('?')
                uri = urljoin(your_key, '/mlb/get_key/' + _tmp[-1])
            elif 'espn3/auth' in key_uri:
                _tmp = key_uri.split('?')
                uri = urljoin(your_key, '/ncaa/get_key/' + _tmp[-1])
            elif 'nhl.com' in key_uri:
                _tmp = key_uri.split('nhl.com/')
                uri = urljoin(your_key, '/nhl/get_key/' + _tmp[-1])
            else:
                uri = key_uri
        elif tele_key:
            if 'nhl.com' in key_uri:
                _tmp = key_uri.split('nhl.com/')
                uri = '%s/%s' % (tele_key, _tmp[-1])
        elif tinyurl_key:
            ses = build_http_session(headers=self.session.get_option("http-headers"), verify=False)
            tiny = None
            try:
                tiny = ses.get(key_uri, headers=self.session.get_option("http-headers"), timeout=15, allow_redirects=True)
                uri = tiny.url
            finally:
                try:
                    if tiny is not None:
                        tiny.close()
                except:
                    pass
                ses.close()
        elif sports24_key:
            if "cbsi.live.ott.irdeto.com" in key_uri:
                _tmp = base64.b64encode(key_uri.encode() if six.PY3 else key_uri)
                _tmp = _tmp.decode() if six.PY3 else _tmp
                uri = urljoin(sports24_key, 'pp/key.php?id=' + _tmp)
            elif "playback.svcs.plus.espn" in key_uri:
                _tmp = urljoin(sports24_key, "/espn/espnpkey.php?url=")
                uri = key_uri.replace("https://playback.svcs.plus.espn.com/events/", _tmp)
        elif flowcable_key:
            ses = None
            try:
                ses = build_http_session(headers=self.session.get_option("http-headers"), verify=False)
                res = ses.get(key_uri, headers=self.session.get_option("http-headers"), verify=False, timeout=15, allow_redirects=True)
                auth = res.headers["xauth"]
                hdrs = self.session.get_option("http-headers")
                hdrs["Xauth"] = auth
                self.session.set_option("http-headers", hdrs)
                try:
                    res.close()
                except:
                    pass
            except:
                pass
            finally:
                try:
                    if ses is not None:
                        ses.close()
                except:
                    pass
            uri = key_uri
        else:
            uri = key_uri

        # get key from key data from key uri
        if not hls_aes_key:
            try:
                xbmc.log('[StreamLink_Proxy] using key uri %s' % str(uri))
                res = self.session.http.get(uri, exception=StreamError,
                                            retries=self.retries,
                                            **self.reader.request_params)
            except Exception as rerr:
                # check if nginx behind cloudflare doesn't accept TLS1.3
                if isinstance(rerr.err, requests.exceptions.HTTPError):
                    status_code = rerr.err.response.status_code
                    try:
                        srv = rerr.err.response.headers.get('Server').lower()
                    except:
                        srv = ""
                    if status_code > 400 and "cloudflare" in srv:
                        # rtxt = rerr.err.response.text
                        # if "This website is using a security service to protect itself from online attacks" in rtxt:
                        self.session.http.mount("https://", TLS12HttpAdapter())  # force TLS1.2

                res = self.session.http.get(
                    uri,
                    exception=StreamError,
                    retries=self.retries,
                    **self.reader.request_params
                )

            res.encoding = "binary/octet-stream"
            self.key_data = res.content[:16]  # strip any potential LF or other extra chars from key data

        # or passed via custom headers
        else:
            xbmc.log('[StreamLink_Proxy] using direct AES key')
            self.key_data = binascii.unhexlify(hls_aes_key)[:16]

        self.key_uri = uri

    iv = key.iv or num_to_iv(sequence)

    # Pad IV to 16 bytes if needed
    iv = b"\x00" * (16 - len(iv)) + iv

    return AES.new(self.key_data, AES.MODE_CBC, iv)


# override sequence processing
def process_sequences(self, playlist, sequences):
    # ##### playlist: M3U8, sequences: List[Sequence]) -> None
    first_sequence, last_sequence = sequences[0], sequences[-1]
    # xbmc.log("[StreamLink_Proxy] process_sequences: %s"%len(sequences))
    # xbmc.log("[StreamLink_Proxy] process_sequences: %s"%str(first_sequence))

    if first_sequence.segment.key and first_sequence.segment.key.method != "NONE":
        xbmc.log('[StreamLink_Proxy] Segments in this playlist are encrypted.')

    self.playlist_changed = ([s.num for s in self.playlist_sequences] != [s.num for s in sequences])
    self.playlist_sequences = sequences

    if not self.playlist_changed:
        self.playlist_reload_time = max(self.playlist_reload_time / 2, 1)

    if playlist.is_endlist:
        self.playlist_end = last_sequence.num

    if self.playlist_sequence < 0:
        if self.playlist_end is None and not self.hls_live_restart:
            edge_index = -(min(len(sequences), max(int(self.live_edge), 1)))
            edge_sequence = sequences[edge_index]
            self.playlist_sequence = edge_sequence.num
        else:
            self.playlist_sequence = first_sequence.num


# override fetch for segment uri rewrite
# fetch2 for py2 and SL <= 1.7.2
def fetch2(self, sequence, retries=None):
    if self.closed or not retries:
        return

    try:
        request_params = self.create_request_params(sequence)

        # skip ignored segment names - until 1.7.0
        if six.PY2 and self.ignore_names and self.ignore_names_re.search(sequence.segment.uri):
            xbmc.log("[StreamLink_Proxy] Skipping segment {0}".format(sequence.num))
            return

        urimod = ''
        uri = sequence.segment.uri
        # print('segment-uri ' + uri)
        if self.session.options.get('hls-segment-uri-mod') is not None:
            xbmc.log('[StreamLink_Proxy] Rewriting segment uri ...')
            urimod = self.session.options.get('hls-segment-uri-mod')
            try:
                urimod = base64.b64decode(urimod).decode('utf-8')
                urimod = json.loads(urimod)
            except:
                # traceback.print_exc()
                pass

            if not isinstance(urimod, dict):
                uri = uri + urimod
            elif 'regex' in urimod:
                repl = urimod['repl']
                uri = re.sub(urimod['regex'], repl, uri, 1)

        return self.session.http.get(
            uri,
            stream=(self.stream_data and not sequence.segment.key),
            timeout=self.timeout,
            exception=StreamError,
            retries=self.retries,
            **request_params
        )

    except StreamError as err:
        print("Failed to open segment {0}: {1}", sequence.num, err)
        return


# fetch3 for py3 and SL >= 2.0
def fetch3(self, segment, stream):
    if self.closed or not self.retries:  # pragma: no cover
        return

    request_params = self.create_request_params(segment)

    urimod = ''
    uri = segment.uri
    # print('segment-uri ' + uri)
    if self.session.options.get('hls-segment-uri-mod') is not None:
        xbmc.log('[StreamLink_Proxy] Rewriting segment uri ...')
        urimod = self.session.options.get('hls-segment-uri-mod')
        # print('uri-mod ' + urimod)
        try:
            urimod = base64.b64decode(urimod).decode('utf-8')
            urimod = json.loads(urimod)
        except:
            # traceback.print_exc()
            pass

        if not isinstance(urimod, dict):
            if "stairwayexplains.top" in urimod:
                sg = uri.split("/")[-1].replace(".ts", "")
                sgm = ""
                for char in sg:
                    sgm += format(ord(char), "x")
                uri = urimod + "/" + sgm + "/feed.xml"
            else:
                uri = uri + urimod
        elif 'regex' in urimod:
            repl = urimod['repl']
            uri = re.sub(urimod['regex'], repl, uri, 1)

        # print('new segment-uri ' + uri)

    return self.session.http.get(
        uri,
        stream=stream,
        timeout=self.timeout,
        exception=StreamError,
        retries=self.retries,
        **request_params
    )


def load_custom_plugins(session):
    # get SL custom plugins dir

    try:
        streamlink_plugins = os.path.join('script.module.streamlink.plugins', 'plugins')
        path_streamlink_service = os.path.join('script.module.slproxy', 'lib', 'dsp')
        kodi_folder = os.path.dirname(os.path.realpath(__file__))
        custom_plugins = kodi_folder.replace(path_streamlink_service, streamlink_plugins)
        custom_plugins_new = xbmc.translatePath('special://home/addons/script.module.streamlink-plugins/lib/data/').encode('utf-8') \
            if six.PY2 else xbmcvfs.translatePath('special://home/addons/script.module.streamlink-plugins/lib/data/')
    except:
        # traceback.print_exc()
        pass

    try:
        session.load_plugins(custom_plugins)
        session.load_plugins(custom_plugins_new)
    except:
        # traceback.print_exc()
        pass


class MyHandler(BaseHTTPRequestHandler):
    handlerStop = threading.Event()
    handlerStop.clear()

    def log_message(self, format, *args):
        pass

    """
    Serves a HEAD request
    """
    def do_HEAD(self):
        self.answer_request(0)

    """
    Serves a GET request.
    """
    def do_GET(self):
        self.answer_request(1)

    def answer_request(self, sendData):
        try:
            request_path = self.path[1:]
            parsed_path = urlparse(self.path)
            path = parsed_path.path[1:]

            try:
                params = dict(parse_qsl(parsed_path.query))
            except:
                self.send_response(404)
                self.end_headers()
                self.wfile.write('URL malformed or stream not found!')
                return

            if request_path == "version":
                self.send_response(200)
                self.end_headers()
                self.wfile.write("StreamLink Proxy: Running\r\n")
                self.wfile.write("Version: 0.1.1\r\n")

            elif path == "streamlink/":
                fURL = params.get('url')
                # fURL = unquote(fURL)
                q = params.get('q', None)
                p = params.get('p', None)
                if not q:
                    q = 'best'
                # print('fURL, q, p ', fURL,q,p)
                self.serveFile(fURL, q, p, sendData)

            elif path == "vodrewrite/":
                pUrl = params.get('url')
                pUrl = unquote(pUrl)
                try:
                    pUrl = re.findall(r'(http.*$)', pUrl)[0]
                except:
                    pass
                m3u8mod = params.get('m3u8mod', None)
                m3u8mod = unquote(m3u8mod)
                self.rewriteVOD(pUrl, m3u8mod)

            elif path == "wtvrestream/":
                fURL = params.get('url')
                q = params.get('q', '720')
                q = re.search(r'(\d+)', q).group(1)
                hdrs = params.get('hdrs', None)
                try:
                    hdrs = base64.b64decode(hdrs.encode("Utf-8")).decode("Utf-8")
                except:
                    pass
                # print('fURL  ', fURL)
                # print('Quality  ', repr(q))
                self.restreamWTV(fURL, q, hdrs)

            else:
                self.send_response(404)
                self.end_headers()
        except:
            # traceback.print_exc()
            self.send_response(500)
            self.end_headers()
        finally:
            return

    """
    Sends the requested file and add additional headers.
    """
    def serveFile(self, fURL, quality, proxy, sendData):

        session = Streamlink()
        load_custom_plugins(session)

        if _dec:
            xbmc.log('[StreamLink_Proxy] using %s encryption library' % _crypto)
            hls.HLSStreamWriter.create_decryptor = create_decryptor
            hls.HLSStreamWorker.process_sequences = process_sequences

        if '|' in fURL:
            sp = fURL.split('|')
            fURL = sp[0]
            headers = quote_plus(sp[1]).replace('%3D', '=').replace('%26', '&') if ' ' in sp[1] else sp[1]
            headers = dict(parse_qsl(headers))

            session.set_option("hls-timeout", 60)
            session.set_option("hls-segment-threads", 2)
            session.set_option("hls-segment-timeout", 30)
            session.set_option("http-stream-timeout", 3600)
            session.set_option("ringbuffer-size", 32 * 1024 * 1024)

            try:
                if 'Referer' in headers:
                    # if 'zoomtv' in headers['Referer']:
                    #     session.set_option("zoom-key", headers['Referer'].split('?')[1])
                    # elif 'zuom' in headers['Referer']:
                    #     session.set_option("zuom-key", headers['Referer'].split('?')[1])
                    if (
                        ('livecamtv' in headers['Referer']
                         or 'realtimetv' in headers['Referer']
                         or 'seelive.me' in headers['Referer'])
                        and ('vw%253D' in headers['Referer']
                             or 'vw=' in headers['Referer'])
                    ):
                        session.set_option("livecam-key", headers['Referer'])
                        headers.pop('Referer')
                    elif 'sawlive' in headers['Referer']:
                        session.set_option("saw-key", headers['Referer'])
                    elif 'yoursportsinhd' in headers['Referer']:
                        session.set_option("your-key", headers['Referer'])
                        headers.pop('Referer')
                    elif 'mamahd' in headers['Referer']:
                        session.set_option("mama-key", headers['Referer'].split('&')[1])
                    elif '@@@zoomtv' in headers['Referer']:
                        _r, _k, _s, _a, _z = headers['Referer'].split('@@@')
                        session.set_option("zoomtv-ksrv", _k)
                        session.set_option("zoomtv-stream", _s)
                        session.set_option("zoomtv-auth", _a)
                        headers['Referer'] = _r
                    elif 'tvply.me' in headers['Referer'] or 'plylive.me' in headers['Referer'] and '@@@' in headers['Referer']:
                        session.set_option("ply-key", headers['Referer'].split('@@@')[1])
                        headers['Referer'] = headers['Referer'].split('@@@')[0]
                        headers['Cookie'] = '_pshflg=~; tamedy=2'
                        headers['Origin'] = 'https://www.plylive.me'
                    elif 'julinewr.xyz' in headers['Referer'] or 'lowend.xyz' in headers['Referer']:
                        session.set_option("tele-key", headers['Referer'].split('@@@')[1])
                        headers['Referer'] = headers['Referer'].split('@@@')[0]
                    elif 'wmsxx.com' in headers['Referer'] or 'eplayer.to' in headers['Referer']:
                        session.set_option("tinyurl-key", True)
                        session.set_option("http-ssl-verify", False)
                    elif 'sports24' in headers['Referer']:
                        session.set_option("sports24-key", headers['Referer'])
                    elif 'flowcablevision' in headers['Referer']:
                        session.set_option("http-ssl-verify", False)
                        session.set_option("flowcable-key", True)

                if 'CustomKeyUri' in headers:
                    session.set_option("hls-segment-key-uri", unquote(headers['CustomKeyUri']))
                    headers.pop('CustomKeyUri')
                elif 'AESKey' in headers:
                    session.set_option("hls-aes-key", headers['AESKey'])
                    headers.pop('AESKey')
                if 'CustomSegmentUri' in headers:
                    if six.PY2:
                        hls.HLSStreamWriter.fetch = fetch2  # for rewriting segment uris
                    elif six.PY3:
                        hls.HLSStreamWriter._fetch = fetch3
                    session.set_option("hls-segment-uri-mod", unquote(headers['CustomSegmentUri']))
                    headers.pop('CustomSegmentUri')

            except:
                # traceback.print_exc()
                pass

            session.set_option("http-headers", headers)
        else:
            # session.set_option('http-headers', {"User-Agent": useragents.CHROME})
            session.set_option('http-headers', {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"})

        if proxy and len(proxy) > 0 and 'http' in proxy:
            if 'https' in proxy:
                session.set_option('https-proxy', proxy)
            else:
                session.set_option('http-proxy', proxy)
            xbmc.log('[StreamLink_Proxy] using http-proxy: {0}'.format(proxy))

        xbmc.log('[StreamLink_Proxy] http-headers added: %s' % str(session.get_option("http-headers")))

        try:
            fURL = maybe_resolve_xtream_player_api(fURL, headers=session.get_option("http-headers"))

            # handle zoomtv redirects
            if session.options.get("zoomtv-auth") is not None:
                res_ = session.http.get(fURL.replace("hls://", ""), allow_redirects=False)
                if res_.status_code in (302, 303):
                    fURL = "hls://" + urljoin(res_.url, res_.headers["Location"])

            # xbmc.log('[StreamLink_Proxy] %s'%fURL)
            plugin = session.resolve_url(fURL)
            xbmc.log('[StreamLink_Proxy] Found matching plugin %s for URL %s' % (plugin.module, fURL))
            # streams = session.streams(fURL)
            streams = plugin.streams()

        except NoPluginError:
            xbmc.log('[StreamLink_Proxy] Error: no plugin found to handle this stream.')
            self.send_response(404)
            self.end_headers()
            return

        except PluginError as err:
            xbmc.log('[StreamLink_Proxy] a plugin error occured: %s' % str(err))
            self.send_response(500)
            self.end_headers()
            return

        except Exception as err:
            # traceback.print_exc(file=sys.stdout)
            xbmc.log('[StreamLink_Proxy] an error occured: %s' % str(err))
            self.send_response(500)
            self.end_headers()
            return

        if not streams:
            xbmc.log('[StreamLink_Proxy] Error: no playable streams found on this URL: %s' % fURL)
            self.send_response(404)
            self.end_headers()
            return

        if (sendData):

            if not streams.get(quality, None):
                quality = "best"

            # Fix OSD Freeze: Send headers immediately
            isHLS = (isinstance(streams[quality], HLSStream))
            isHTTP = (isinstance(streams[quality], HTTPStream))
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp2t' if isHLS or isHTTP else 'video/unknown')
            self.end_headers()

            try:
                with streams[quality].open() as stream:
                    # xbmc.log('[StreamLink_Proxy] Playing stream %s with quality \'%s\''%(streams[quality],quality))
                    cache = STEADY_CHUNK  # Pre-fill Buffer: Start with 64KB

                    # init zoomtv auth refresh
                    zoomtv_auth = None
                    tdelta = None
                    try:
                        zoomtv_ksrv = stream.session.options.get("zoomtv-ksrv").replace("ksrv=", "")
                        zoomtv_stream = stream.session.options.get("zoomtv-stream").replace("stream=", "")
                        zoomtv_auth = stream.session.options.get("zoomtv-auth").replace("auth=", "")
                        zoomtv_auth = six.ensure_str(base64.b64decode(zoomtv_auth))
                        zoomtv_auth = json.loads(zoomtv_auth)
                        tdelta = (int(zoomtv_auth["ts"]) - int(time.time())) / 2
                    except:
                        pass

                    # t0 = time.time()
                    buf = 'INIT'
                    while buf and (len(buf) > 0 and not event_is_set(self.handlerStop)):
                        # print('buf ' + repr(buf[:200]))
                        buf = stream.read(cache)

                        # delete fake PNG header and img in hls
                        if isHLS and buf[:8] == b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A':
                            off = re.search(b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A.*?\x47', buf)  # 0x47 (G) is ts header sync byte
                            if off:
                                off = off.end() - 1
                            else:
                                off = 8
                            buf = buf[off:]

                        # call zoomtv auth page before expire ts
                        if zoomtv_auth is not None and tdelta is not None:
                            if time.time() >= int(zoomtv_auth["ts"]) - tdelta:
                                try:
                                    zoomtv_securl = "{}/?stream={}&scode={}&expires={}".format(zoomtv_ksrv, zoomtv_stream, zoomtv_auth['scode'], zoomtv_auth['ts'])
                                    xbmc.log('[StreamLink_Proxy] calling ZoomTV auth page: %s' % str(zoomtv_securl))
                                    # session is closed after with block
                                    with requests.Session() as ses:
                                        ses.mount("https://", TLS12HttpAdapter())
                                        ses.headers = stream.session.get_option("http-headers")
                                        # ses.verify = False
                                        zoomtv_auth = ses.get(zoomtv_securl, timeout=10).json()

                                except:
                                    traceback.print_exc(file=sys.stdout)
                                    pass

                        # print(repr(buf[:13]))
                        if not buf:
                            xbmc.log("[StreamLink_Proxy] Error: no data returned from stream!")
                            break

                        try:
                            self.wfile.write(buf)
                            self.wfile.flush()
                        except STOP_EXCEPTIONS as e:
                            if is_client_disconnect(e):
                                break
                            raise

                        if cache < STEADY_CHUNK:
                            cache = min(cache * 2, STEADY_CHUNK)

                    # self.wfile.close()
                    # self.handlerStop.set()

            except STOP_EXCEPTIONS:
                # Silent Exit: Don't log errors on stop to avoid "Playback Failed" messages
                pass

            except Exception as err:
                # traceback.print_exc(file=sys.stdout)
                xbmc.log('[StreamLink_Proxy] could not open stream: {0}'.format(err))
                self.handlerStop.set()

            try:
                stream.close()
            except:
                pass
            stream = None

    def rewriteVOD(self, pUrl, m3u8mod):
        try:
            if '|' in pUrl:
                sp = pUrl.split('|')
                pUrl = sp[0]
                headers = quote_plus(sp[1]).replace('%3D', '=').replace('%26', '&') if ' ' in sp[1] else sp[1]
                headers = dict(parse_qsl(headers))
            else:
                headers = {"User-Agent": useragents.CHROME}

            cache_key = "vod::{0}::{1}::{2}".format(pUrl, six.ensure_str(m3u8mod), six.ensure_str(sorted(headers.items())))
            cached = HTTP_CACHE.get(cache_key)
            if cached:
                ct, m3u8 = cached
            else:
                ses = build_http_session(headers=headers, verify=False)
                r = ses.get(pUrl, headers=headers, verify=False, timeout=15, allow_redirects=True)

                try:
                    ct = r.headers['content-type']
                except:
                    ct = 'application/vnd.apple.mpegurl'
                m3u8 = r.text
                HTTP_CACHE.set(cache_key, (ct, m3u8), 15)
                try:
                    r.close()
                except:
                    pass
                ses.close()

            try:
                m3u8mod = base64.b64decode(m3u8mod).decode('utf-8')
                m3u8mod = json.loads(m3u8mod)
            except:
                # traceback.print_exc()
                m3u8mod = None

            if m3u8mod and 'regex' in m3u8mod:
                repl = m3u8mod['repl']
                regex = m3u8mod['regex']
                m3u8 = re.sub(regex, repl, m3u8, 0)
                m3u8 = m3u8.encode('utf-8') if six.PY2 else m3u8

            cl = str(len(m3u8.encode('utf-8') if six.PY3 and isinstance(m3u8, six.text_type) else m3u8))

            self.send_response(200)
            self.send_header('Content-type', ct)  # m3u8
            self.send_header("Content-Length", cl)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(m3u8.encode('utf-8') if six.PY3 and isinstance(m3u8, six.text_type) else m3u8)
            # self.wfile.close()

        except STOP_EXCEPTIONS as err:
            if not is_client_disconnect(err):
                xbmc.log('[StreamLink_Proxy] Socket Error: {0}'.format(err))

        except Exception as err:
            # traceback.print_exc()
            self.handlerStop.set()
            xbmc.log('[StreamLink_Proxy] could not rewrite or open playlist: {0}'.format(err))

    def restreamWTV(self, link, quality, headers):
        r = None
        s = None
        try:
            prx = 'http://%s:%s/wtvrestream/?url=' % (SLProxy.HOST_NAME, SLProxy.PORT_NUMBER)
            scode = 0
            s = build_http_session(verify=False)
            # s = Streamlink().http

            if headers is None:
                headers = {"User-Agent": useragents.CHROME}
            else:
                try:
                    headers__ = {}
                    headers_ = headers.split("&")
                    for header_ in headers_:
                        headers__.update({header_.split("=")[0].strip(): header_.split("=")[1].strip()})
                    headers = headers__
                except:
                    pass

            isTS = False
            isTS = re.search(r'^.*\.ts.*$', link) or re.search(r'^.*\.mp4a.*$', link) or re.search(r'^.*\.aac.*$', link)

            r = s.get(
                link,
                stream=True,
                headers=headers,
                allow_redirects=True,
                timeout=15
            )
            scode = r.status_code

            # print("[VODPROXY]    " + repr(headers))
            if scode >= 400:
                self.send_response(scode)
                self.end_headers()
                self.wfile.flush()
            else:
                base = re.findall(r'(^.*\/)', r.url)[0]
                # if ('content-type' in headers and headers['content-type'] == 'application/vnd.apple.mpegurl') or b"#EXT" in r.content:
                if (not isTS) and ('.m3u8' in link or '/m3u8/' in link):
                    hls7 = r.text

                    # filter resolution and language in master pl
                    if "#EXT-X-STREAM-INF" in hls7:
                        try:
                            hls7 = re.sub(r'#EXT-X-STREAM-INF:.*RESOLUTION=\d+x(?!{0}).*\s+.*'.format(quality), r"", hls7)
                            bw = re.findall(r'BANDWIDTH=(\d+)', hls7)
                            bw.sort(reverse=True, key=lambda x: int(x))
                            bw = bw[0]
                            hls7 = re.sub(r'#EXT-X-STREAM-INF:.*BANDWIDTH=(?!{0}).*\s+.*'.format(bw), r"", hls7)
                            hls7 = re.sub(r'#EXT-X-MEDIA:TYPE=AUDIO.*DEFAULT=NO.*', r"", hls7)
                        except:
                            # traceback.print_exc()
                            pass

                    data = hls7.splitlines()

                    ct = "application/vnd.apple.mpegurl"
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    # self.send_header("Content-Length", cl)
                    # self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()

                    hdrs_ = base64.b64encode(urlencode(headers).encode("Utf-8")).decode("Utf-8")
                    lines = ""

                    for line in data:
                        if re.search(r'^#EXT-X-MEDIA.*?URI="(.*?)"', line):
                            uri = re.search(r'^#EXT-X-MEDIA.*?URI="(.*?)"', line).group(1)
                            line = re.sub(r'URI=".*?(".*$)', r'URI="{0}{1}\1'.format(prx, quote(urljoin(base, uri))), line)
                            pass
                        elif re.search(r'(?:#EXTM3U|#EXT-X-|EXTINF)', line):
                            # print(line)
                            pass
                        elif re.search(r'^\w+.*(?:\.m3u8|\.ts|\.aac|\.mp4a)*$', line):
                            line = '{0}{1}'.format(prx, quote(urljoin(base, line)))
                            line += "&hdrs=%s" % hdrs_ if "#EXTINF:" in hls7 else ""
                            pass
                        elif line == '':
                            continue
                        else:
                            pass

                        line += "\n"
                        lines += line

                    self.wfile.write(lines.encode() if six.PY3 else lines)
                    self.wfile.flush()

                elif isTS:
                    if re.search(r'^https?://.*\.ts', link):
                        ct = 'video/mp2t'
                    elif re.search(r'^https?://.*\.aac', link):
                        ct = 'audio/aac'
                    elif re.search(r'^https?://.*\.mp4a', link):
                        ct = 'audio/mp4'
                    headers = {header.lower(): r.headers[header] for header in r.headers}
                    self.send_response(200)
                    self.send_header('Content-Type', ct)
                    try:
                        self.send_header("Content-Length", headers['content-length'])
                    except:
                        pass

                    self.end_headers()
                    # print("[SLPROXY TS]    " + repr(link))
                    # rmhead = 1

                    # for chunk in r.iter_content(chunk_size=1000000):
                    #    print("[SLPROXY]    " + repr(chunk[:50]))
                    #     if rmhead == 1:
                    #    self.wfile.write(chunk.lstrip(b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A'))
                    #         rmhead = 0
                    #     else:
                    for chunk in iter_low_latency_chunks(r, stop_event=self.handlerStop):
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except STOP_EXCEPTIONS as err:
                            if is_client_disconnect(err):
                                break
                            raise

        except STOP_EXCEPTIONS as err:
            if not is_client_disconnect(err):
                xbmc.log('[SLProxy] socket error: {0}'.format(err))

        except Exception as err:
            # traceback.print_exc()
            self.handlerStop.set()
            xbmc.log('[SLProxy] could not open playlist: {0}'.format(err))
        finally:
            try:
                r.close()
            except:
                pass
            try:
                s.close()
            except:
                pass

        pass


class Server(HTTPServer):
    """HTTPServer class with timeout."""
    timeout = 5

    def finish_request(self, request, client_address):
        """Finish one request by instantiating RequestHandlerClass."""
        try:
            self.RequestHandlerClass(request, client_address, self)
        except socket.error as err:
            if err.errno not in ACCEPTABLE_ERRNO:
                raise


class ThreadedHTTPServer(ThreadingMixIn, Server):
    """Handle requests in a separate thread."""
    allow_reuse_address = True
    daemon_threads = True


class SLProxy():
    HOST_NAME = '127.0.0.1'
    PORT_NUMBER = 45678
    ready = threading.Event()

    def start(self, stopEvent):
        self.ready.clear()
        sys.stderr = sys.stdout
        server_class = ThreadedHTTPServer
        MyHandler.handlerStop = stopEvent
        httpd = server_class((self.HOST_NAME, self.PORT_NUMBER), MyHandler)
        xbmc.log("[StreamLink_Proxy] Service started - %s:%s." % (self.HOST_NAME, self.PORT_NUMBER))

        while(True and not event_is_set(stopEvent)):  # and not xbmc.abortRequested
            httpd.handle_request()
            self.ready.set()

        httpd.server_close()
        self.ready.clear()
        xbmc.log('[StreamLink_Proxy] Service stopped.')

    def stop(self):
        pass

    def status(self):
        pass


class SLProxy_Helper():

    def getKodiVersion(self):
        return xbmc.getInfoLabel("System.BuildVersion").split(".")[0]

    def startProxy(self):
        pass

    def playSLink(self, url, listitem):
        # print('SLurl {0}'.format(url))
        stopPlaying = threading.Event()
        stopPlaying.clear()
        progress = xbmcgui.DialogProgress()
        progress.create('Starting StreamLink Proxy')
        progress.update(10, 'Loading StreamLink Proxy')

        sl_Proxy = SLProxy()
        url = url.replace('slplugin://', '')  # plugin flag from SD
        if 'm3u8mod=' in url:
            action = 'vodrewrite'
        # elif 'streams.wilmaa.com' in url: # todo: update for yallo
        #     action = 'wtvrestream'
        else:
            action = 'streamlink'
        # action = 'vodrewrite' if 'm3u8mod=' in url else 'streamlink'
        url_to_play = 'http://%s:%s/%s/?url=%s' % (sl_Proxy.HOST_NAME, sl_Proxy.PORT_NUMBER, action, url)
        proxy_thread = threading.Thread(target=sl_Proxy.start, args=(stopPlaying,))
        proxy_thread.daemon = True
        proxy_thread.start()
        proxyReady = sl_Proxy.ready
        monitor = xbmc.Monitor()

        progress.update(20)
        xbmc.sleep(200)
        p = 30
        while True and p < 100:
            if event_is_set(proxyReady):
                progress.update(90)
                break
            if monitor.abortRequested():
                stopPlaying.set()
                progress.close()
                return False
            progress.update(p)
            xbmc.sleep(200)
            p += 10

        mplayer = MyPlayer()
        mplayer.stopPlaying = stopPlaying
        mplayer.play(url_to_play, listitem)
        xbmc.executebuiltin("Dialog.Close(busydialog)")
        xbmc.executebuiltin("Dialog.Close(busydialognocancel)")
        progress.update(100)
        progress.close()
        played = False
        start_wait = time.time()

        while True:
            if event_is_set(stopPlaying):
                break
            if monitor.abortRequested():
                stopPlaying.set()
                break
            if mplayer.isPlaying():
                played = True
            elif played:
                # If playback had started and now stopped, exit cleanly
                # even when Kodi callback is not fired in some builds.
                stopPlaying.set()
                break
            elif not played and (time.time() - start_wait) > 30:
                # Avoid endless waiting when stream/proxy never starts.
                xbmc.log('[StreamLink_Proxy] playback did not start within timeout, stopping proxy loop.')
                stopPlaying.set()
                break
            xbmc.log('[StreamLink_Proxy] idle running ...')
            xbmc.sleep(500)

        return played

    def resolve_url(self, url):
        xbmc.log('[StreamLink_Proxy] trying to resolve url ...')
        session = Streamlink()
        # get custom plugins
        load_custom_plugins(session)

        try:
            params = dict(parse_qsl('url=%s' % url))
            fURL = params.get('url')
            fURL = unquote(fURL)
            q = params.get('q', False) or 'pick'
            proxy = params.get('p', None)

            if '|' in fURL:
                sp = fURL.split('|')
                fURL = sp[0]
                headers = dict(parse_qsl(sp[1]))
                session.set_option("http-headers", headers)

            if proxy and len(proxy) > 0 and 'http' in proxy:
                if 'https' in proxy:
                    session.set_option('https-proxy', proxy)
                else:
                    session.set_option('http-proxy', proxy)
                xbmc.log('[StreamLink_Proxy] using http-proxy: {0}'.format(proxy))

            plugin = session.resolve_url(fURL)
            session.set_plugin_option("rtve", "mux-subtitles", True)
            streams = plugin.streams()
            # print streams
            if "streams.wilmaa.com" in fURL:
                ql = [q for q in streams.keys() if re.search(r'^[\d]{3}p$', q)]
                q = xbmcgui.Dialog().select('Choose the stream quality', ql)
                if q == -1:
                    return None
                else:
                    q = ql[q]

                uri = quote(fURL) + '&q={0}'.format(q)
                return uri
            else:
                if len(streams) > 2 and q == 'pick':
                    q = xbmcgui.Dialog().select('Choose the stream quality', [q for q in streams.keys()])
                    if q == -1:
                        return None
                    else:
                        q = list(streams.keys())[q]
                elif q == 'pick':
                    q = 'best'

                stream = streams.get(q, False) or streams.get('best')
                return stream.url

        except Exception as err:
            # traceback.print_exc(file=sys.stdout)
            xbmc.log('[StreamLink_Proxy] resolve error: {0}'.format(err))
            return None


class MyPlayer (xbmc.Player):
    def __init__(self):
        xbmc.Player.__init__(self)

    def play(self, url, listitem):
        # print 'Now im playing... %s' % url
        self.stopPlaying.clear()
        xbmc.Player.play(self, url, listitem)

    def onPlayBackEnded(self):
        # Will be called when xbmc stops playing a file
        # print "seting event in onPlayBackEnded "
        self.stopPlaying.set()
        # print "stop Event is SET"

    def onPlayBackStopped(self):
        # Will be called when user stops xbmc playing a file
        # print "seting event in onPlayBackStopped "
        self.stopPlaying.set()
        # print "stop Event is SET"

    def onPlayBackError(self):
        self.stopPlaying.set()

    def onPlayBackStarted(self):
        xbmc.executebuiltin("Dialog.Close(busydialog)")
        xbmc.executebuiltin("Dialog.Close(busydialognocancel)")
