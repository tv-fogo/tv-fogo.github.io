# -*- coding: utf-8 -*-
"""Opportunistically upgrade public HTTP URLs to HTTPS when TLS works.

Unlike the tvfogo implementation, this module does not monkeypatch requests
and does not issue a direct-HTTP retry from here. Requests use localproxy, so
the configured HTTPS upstream and strict DNS policy are respected.
"""

import ipaddress
import threading
import time

try:
    from urllib.parse import urljoin, urlsplit, urlunsplit
except ImportError:
    from urlparse import urljoin, urlsplit, urlunsplit

_LOCK = threading.Lock()
_HOST_CACHE = {}
_SUCCESS_TTL = 6 * 60 * 60
_FAILURE_TTL = 30 * 60
_DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36'
_SETTING_CACHE_TTL = 30.0
_enabled = None
_enabled_checked_at = 0.0


def is_enabled():
    """Read the HTTPS preference from this addon's settings."""
    global _enabled, _enabled_checked_at
    now = time.time()
    if _enabled is None or (now - _enabled_checked_at) > _SETTING_CACHE_TTL:
        try:
            import xbmcaddon
            value = xbmcaddon.Addon('plugin.video.football').getSetting('force_https')
            _enabled = str(value or '').strip().lower() != 'false'
        except Exception:
            _enabled = True
        _enabled_checked_at = now
    return _enabled


def _is_local_or_private(host):
    host = str(host or '').strip('[]').lower().rstrip('.')
    if not host or host == 'localhost' or host.endswith('.localhost') or host.endswith('.local'):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return '.' not in host
    except Exception:
        return True


def to_https(url):
    """Build an HTTPS candidate for a public HTTP URL on a standard port."""
    if not isinstance(url, str) or '|' in url:
        base = str(url or '').split('|', 1)[0]
    else:
        base = url
    try:
        parsed = urlsplit(base)
        if parsed.scheme.lower() != 'http' or _is_local_or_private(parsed.hostname):
            return url
        port = parsed.port
        if port not in (None, 80, 443):
            return url
        netloc = parsed.netloc
        if port == 80:
            # Remove only the explicit :80 suffix, keeping any userinfo intact.
            host_part = netloc.rsplit('@', 1)[-1]
            netloc = netloc[:-len(host_part)] + host_part[:-3]
        return urlunsplit(('https', netloc, parsed.path, parsed.query, parsed.fragment)) + (
            ('|' + url.split('|', 1)[1]) if '|' in str(url) else ''
        )
    except Exception:
        return url


def _probe_https(candidate, headers=None):
    """Verify TLS and a usable response through the addon's network path."""
    response = None
    try:
        import localproxy
        probe_headers = {'User-Agent': _DEFAULT_UA, 'Range': 'bytes=0-0'}
        probe_headers.update(headers or {})
        response = localproxy.cloudflare_get(
            candidate,
            headers=probe_headers,
            timeout=(2, 4),
            verify=True,
            allow_redirects=False,
            stream=True,
        )
        status = int(getattr(response, 'status_code', 0) or 0)
        if status >= 400 or status < 100:
            return False
        location = (getattr(response, 'headers', {}) or {}).get('Location', '')
        if location and urlsplit(urljoin(candidate, location)).scheme.lower() != 'https':
            return False
        return True
    except Exception:
        return False
    finally:
        try:
            if response is not None:
                response.close()
        except Exception:
            pass


def play_url(url, headers=None):
    """Upgrade a URL only after the HTTPS endpoint has passed a probe.

    If the host does not provide a usable HTTPS response, preserve the original
    URL for playback compatibility. privacy_mode still blocks direct access
    without a configured HTTPS upstream proxy.
    """
    if not is_enabled():
        return url
    candidate = to_https(url)
    if candidate == url:
        return url
    try:
        host = urlsplit(candidate.split('|', 1)[0]).netloc.lower()
        now = time.time()
        with _LOCK:
            cached = _HOST_CACHE.get(host)
            if cached and cached[1] > now:
                supported = cached[0]
            else:
                supported = None
        if supported is None:
            supported = _probe_https(candidate.split('|', 1)[0], headers=headers)
            ttl = _SUCCESS_TTL if supported else _FAILURE_TTL
            with _LOCK:
                _HOST_CACHE[host] = (supported, now + ttl)
        return candidate if supported else url
    except Exception:
        return url


def patch_requests():
    """Compatibility no-op: request conversion is integrated in localproxy."""
    return None
