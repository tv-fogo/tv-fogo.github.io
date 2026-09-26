# -*- coding: utf-8 -*-
try:
    from .helper import *
    from . import hlsretry, tsdownloader, server
except ImportError:
    from helper import *
    import hlsretry
    import tsdownloader
    import server
import threading
import time
from six.moves import urllib_parse


def m3u8_to_ts(url):
    if '.m3u8' in url and '/live/' in url and int(url.count("/")) > 5:
        url = url.replace('/live', '').replace('.m3u8', '')
    return url


def basename(p):
    """Returns the final component of a pathname"""
    i = p.rfind('/') + 1
    return p[i:]
    
def convert_to_m3u8(url):
    if '|' in url:
        url = url.split('|')[0]
    elif '%7C' in url:
        url = url.split('%7C')[0]
    
    if not '.m3u8' in url and not '/hl' in url and int(url.count("/")) > 4 and not '.mp4' in url and not '.avi' in url:
        parsed_url = urlparse(url)
        try:
            # Captura o esquema (http) e o host (domínio:porta) automaticamente
            host_part1 = '%s://%s'%(parsed_url.scheme, parsed_url.netloc)
            host_part2 = url.split(host_part1)[1]
            
            # Se a URL não tiver /live (padrão Xtream), nós adicionamos
            # Se já tiver, mantemos a estrutura original
            if not '/live' in host_part2:
                url = host_part1 + '/live' + host_part2
            else:
                url = host_part1 + host_part2
                
            file = basename(url)
            if '.ts' in file:
                file_new = file.replace('.ts', '.m3u8')
                url = url.replace(file, file_new)
            else:
                # Adiciona o .m3u8 no final para que o HLSRETRY funcione
                url = url + '.m3u8'
        except:
            pass
    return url 

def player_hlsretry(name,url,iconimage,description):
    if name:
        name = 'GLORIOSO TV - HLSRETRY - ' + name
    else:
        name = 'GLORIOSO TV - HLSRETRY'
    url = unquote_plus(url)
    url = convert_to_m3u8(url)
    url = 'http://%s:%s/?url=%s'%(str(hlsretry.HOST_NAME),str(hlsretry.PORT_NUMBER),quote(url))
    hlsretry.XtreamProxy().start()
    li=xbmcgui.ListItem(name)
    iconimage = iconimage if iconimage else ''
    li.setArt({"icon": "DefaultVideo.png", "thumb": iconimage})
    set_video_info(li, title=name, plot=description)
    xbmc.Player().play(item=url, listitem=li)
    _monitor_local_player(hlsretry.HOST_NAME, hlsretry.PORT_NUMBER)

def player_tsdownloader(name,url,iconimage,description):
    if name:
        name = 'GLORIOSO TV - TSDOWNLOADER - ' + name
    else:
        name = 'GLORIOSO TV - TSDOWNLOADER'
    url = unquote_plus(url)
    url = url.replace('.m3u8', '')
    url = 'http://%s:%s/?url=%s'%(str(tsdownloader.HOST_NAME),str(tsdownloader.PORT_NUMBER),quote(url))
    tsdownloader.XtreamProxy().start() 
    li=xbmcgui.ListItem(name)
    iconimage = iconimage if iconimage else ''
    li.setArt({"icon": "DefaultVideo.png", "thumb": iconimage})
    set_video_info(li, title=name, plot=description)
    xbmc.Player().play(item=url, listitem=li)           
    _monitor_local_player(tsdownloader.HOST_NAME, tsdownloader.PORT_NUMBER)

def player_input(name, url, iconimage, description):
    try:
        from extra_lib.dnscompat import DNSOverride
    except Exception:
        from dnscompat import DNSOverride
    try:
        from extra_lib.secureurl import play_url as secure_play_url
    except Exception:
        from secureurl import play_url as secure_play_url
    
    url = secure_play_url(url)  # criptografa o stream (http -> https)
    dns_resolver = DNSOverride()

    if name:
        name = "GLORIOSO TV - INPUTSTREAM FFMPEGDIRECT - " + name
    else:
        name = "GLORIOSO TV - INPUTSTREAM FFMPEGDIRECT"

    exts = (".mp4", ".mp3", ".mkv", ".avi", ".rmvb")
    if not any(ext in url.lower() for ext in exts):
        url = convert_to_m3u8(url)
        if ".m3u8" in url or ".ts" in url or "format=ts" in url or ".ism" in url:
            plugin = xbmcvfs.translatePath(
                "special://home/addons/inputstream.ffmpegdirect"
            )
            if not os.path.exists(plugin):
                try:
                    xbmc.executebuiltin(
                        "InstallAddon(inputstream.ffmpegdirect)", wait=True
                    )
                except Exception:
                    pass

            url = unquote_plus(url)
            
            # Montagem do User-Agent / Headers na própria URL
            if "|" in url:
                base_url, headers = url.split("|", 1)
                if "Connection" not in headers:
                    headers += "&Connection=keep-alive"
                url = f"{base_url}|{headers}"
            else:
                user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
                url = f"{url}|User-Agent={user_agent}&Connection=keep-alive"

            play_item = xbmcgui.ListItem(path=url)
            item = play_item
            play_item.setArt({"icon": "DefaultVideo.png", "thumb": iconimage or ""})

            if kversion > 19:
                info = play_item.getVideoInfoTag()
                info.setTitle(name)
                info.setPlot(description)
            else:
                play_item.setInfo(
                    type="Video", infoLabels={"Title": name, "Plot": description}
                )

            play_item.setContentLookup(False)
            play_item.setProperty("IsPlayable", "true")

            # --- RESOLUÇÃO DOH INJETADA NO LIBCURL SEM REMOVER PROPRIEDADES ---
            try:
                raw_stream_url = url.split('|')[0]
                parsed_url = urlparse(raw_stream_url)
                domain = parsed_url.hostname
                port = parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)

                if domain and not dns_resolver.is_valid_ipv4(domain):
                    resolved_ip = dns_resolver.resolve(domain)
                    if resolved_ip:
                        dns_mapping = f"{domain}:{port}:{resolved_ip}"
                        play_item.setProperty('inputstream.ffmpegdirect.curl_option.resolve', dns_mapping)

                # Força IPv4 explicitamente no libcurl do Kodi (CURL_IPRESOLVE_V4 = 1)
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.ipresolve', '1')
                # Configurações de reconexão automática para o stream não cair com oscilações
                play_item.setProperty('inputstream.ffmpegdirect.reconnect_on_error', 'true')
                play_item.setProperty('inputstream.ffmpegdirect.reconnect_delay_max', '5')
                play_item.setProperty('inputstream.ffmpegdirect.reconnect_on_http_error', '4xx,5xx')

                # Segue o redirect via DoH: alguns servidores redirecionam para
                # hosts que o DNS do sistema so devolve em IPv6 (ou nem devolve),
                # o que quebra o curl do Kodi. Resolvemos o destino final aqui
                # (via requests + DoH) e tocamos direto na URL final, ja com o
                # IP correto injetado no curl. Funciona para m3u8 e ts.
                try:
                    import requests as _rq
                    hdrs = {}
                    try:
                        if '|' in url:
                            extra = url.split('|', 1)[1]
                            if 'User-Agent=' in extra:
                                hdrs['User-Agent'] = extra.split('User-Agent=')[1].split('&')[0]
                    except Exception:
                        hdrs = {}
                    _r = _rq.get(raw_stream_url, headers=hdrs, stream=True, timeout=(3, 5), allow_redirects=True, verify=False)
                    _final = _r.url
                    try:
                        _r.close()
                    except Exception:
                        pass
                    if (_final and _final.startswith('http')
                            and _final.split('|')[0] != raw_stream_url):
                        url = _final + ('|' + url.split('|', 1)[1] if '|' in url else '')
                        _p2 = urlparse(_final.split('|')[0])
                        _dom2 = _p2.hostname
                        _port2 = _p2.port or (443 if _p2.scheme == 'https' else 80)
                        if _dom2 and not dns_resolver.is_valid_ipv4(_dom2):
                            _ip2 = dns_resolver.resolve(_dom2)
                            if _ip2:
                                play_item.setProperty(
                                    'inputstream.ffmpegdirect.curl_option.resolve',
                                    f"{_dom2}:{_port2}:{_ip2}")
                except Exception:
                    pass
            except Exception:
                pass
            # -----------------------------------------------------------------

            if '$$lic' in url:
                url, lic = url.split('$$lic=')
                lic = urllib_parse.unquote_plus(lic)
                if '{SSM}' not in lic:
                    lic += '||R{SSM}|'
                play_item.setProperty('inputstream.ffmpegdirect.license_type', 'com.widevine.alpha')
                play_item.setProperty('inputstream.ffmpegdirect.license_key', lic)
            if '|' in url:
                url, strhdr = url.split('|')
                play_item.setProperty('inputstream.ffmpegdirect.stream_headers', strhdr)
                item.setPath(url)
            if '.m3u8' in url:
                if six.PY2:
                    play_item.setProperty('inputstreamaddon', 'inputstream.ffmpegdirect')
                else:
                    play_item.setProperty('inputstream', 'inputstream.ffmpegdirect')
                play_item.setProperty('inputstream.ffmpegdirect.manifest_type', 'hls')
                play_item.setProperty('inputstream.ffmpegdirect.open_mode', 'curl')
                play_item.setProperty('inputstream.ffmpegdirect.stream_mode', 'timeshift')
                play_item.setProperty('inputstream.ffmpegdirect.chunk_size', '67108864')
                play_item.setProperty('inputstream.ffmpegdirect.buffer_mode', 'adaptive')
                play_item.setProperty('inputstream.ffmpegdirect.cache', 'true')
                play_item.setProperty('inputstream.ffmpegdirect.codec_whitelist', 'h264,hevc,aac,mp3,ac3,eac3')
                play_item.setProperty('inputstream.ffmpegdirect.protocol_whitelist', 'http,https,tcp,udp')
                play_item.setProperty('inputstream.ffmpegdirect.max_bandwidth', '0')
                play_item.setProperty('inputstream.ffmpegdirect.seekable', 'true')
                play_item.setProperty('inputstream.ffmpegdirect.scalevideo', 'true')
                play_item.setProperty('inputstream.ffmpegdirect.codec_whitelist', 'ALL')
                play_item.setProperty('inputstream.ffmpegdirect.protocol_whitelist', 'ALL')
                play_item.setProperty('inputstream.ffmpegdirect.max_bandwidth', '0')
                play_item.setProperty('inputstream.ffmpegdirect.ignore_ts', 'false')
                play_item.setProperty('inputstream.ffmpegdirect.user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.connecttimeout', '15')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.timeout', '30')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.followlocation', '1')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.ssl_verifypeer', '0')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.ssl_verifyhost', '0')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.low_speed_limit', '1000')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.low_speed_time', '20')
                play_item.setProperty('inputstream.ffmpegdirect.manifest_update_parameter', 'full')
                play_item.setProperty('inputstream.ffmpegdirect.read_full_manifest', 'true')
                play_item.setProperty('inputstream.ffmpegdirect.min_buffer_time', '10')
                play_item.setProperty('inputstream.ffmpegdirect.max_buffer_time', '30')
                item.setContentLookup(False)

            elif '.ts' in url or 'format=ts' in url:
                if six.PY2:
                    play_item.setProperty('inputstreamaddon', 'inputstream.ffmpegdirect')
                else:
                    play_item.setProperty('inputstream', 'inputstream.ffmpegdirect')
                item.setMimeType('video/mp2t')
                play_item.setProperty('inputstream.ffmpegdirect.open_mode', 'curl')
                play_item.setProperty('inputstream.ffmpegdirect.stream_mode', 'ffmpeg')
                play_item.setProperty('inputstream.ffmpegdirect.is_realtime_stream', 'true')
                play_item.setProperty('inputstream.ffmpegdirect.cache', 'true')
                play_item.setProperty('inputstream.ffmpegdirect.seekable', 'true')
                play_item.setProperty('inputstream.ffmpegdirect.ignore_ts', 'false')
                play_item.setProperty('inputstream.ffmpegdirect.user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.connecttimeout', '15')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.timeout', '30')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.followlocation', '1')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.ssl_verifypeer', '0')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.ssl_verifyhost', '0')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.low_speed_limit', '1000')
                play_item.setProperty('inputstream.ffmpegdirect.curl_option.low_speed_time', '20')
                item.setContentLookup(False)

            elif '.ism' in url:
                if six.PY2:
                    play_item.setProperty('inputstreamaddon', 'inputstream.ffmpegdirect')
                else:
                    play_item.setProperty('inputstream', 'inputstream.ffmpegdirect')
                play_item.setProperty('inputstream.ffmpegdirect.manifest_type', 'ism')
                item.setMimeType('application/vnd.ms-sstr+xml')
                item.setContentLookup(False)
            item.setPath(url)

            xbmc.Player().play(item=url, listitem=play_item)
        else:
            notify("O link não é M3U8")
    else:
        notify("Formato inválido!")
	
class MyPlayer(xbmc.Player):
    def __init__(self):
        xbmc.Player.__init__(self)

def _monitor_local_player(host, port):
    def monitor_player():
        monitor = xbmc.Monitor()
        # Aguarda o player iniciar a reprodução por até 30 segundos
        wait_count = 0
        while not monitor.abortRequested() and not xbmc.Player().isPlaying():
            if monitor.waitForAbort(0.25):
                return
            wait_count += 1
            if wait_count > 120:  # 30 segundos
                break

        # Monitora com tolerância contra falsos desligamentos durante buffering
        stopped_count = 0
        while not monitor.abortRequested():
            if monitor.waitForAbort(1.0):
                break
            if not xbmc.Player().isPlaying():
                stopped_count += 1
                if stopped_count >= 6:  # Confirma 6 segundos sem tocar antes de parar
                    break
            else:
                stopped_count = 0

        try:
            requests.get('http://%s:%s/stop' % (host, port), timeout=2)
        except Exception:
            pass

    thread = threading.Thread(target=monitor_player)
    thread.daemon = True
    thread.start()

def monitor():
    monitor = xbmc.Monitor()
    # Aguarda o player iniciar por até 30 segundos
    wait_count = 0
    while not monitor.abortRequested() and not xbmc.Player().isPlaying():
        if monitor.waitForAbort(0.25):
            return
        wait_count += 1
        if wait_count > 120:
            break

    stopped_count = 0
    while not monitor.abortRequested():
        if monitor.waitForAbort(1.0):
            break
        if not xbmc.Player().isPlaying():
            stopped_count += 1
            if stopped_count >= 6:
                break
        else:
            stopped_count = 0
    server.req_shutdown()

def proxy2_thread(name,iconImage,url_to_play):
    if not name:
        name = 'GLORIOSO TV'
    name = name + ' - Proxy 2'
    try:
        media_url = server.extract_media_url(url_to_play)
        liz = xbmcgui.ListItem(name)
        liz.setPath(url_to_play)
        if iconImage:
            liz.setArt({"icon": iconImage, "thumb": iconImage})
        else:
            liz.setArt({"icon": addonIcon, "thumb": addonIcon})
        set_video_info(liz, title=name)
        if media_url.lower().split('?')[0].endswith('.m3u8'):
            liz.setMimeType("application/vnd.apple.mpegurl")
        elif media_url.lower().split('?')[0].endswith('.ts'):
            liz.setMimeType("video/mp2t")
        liz.setContentLookup(False) 
        mplayer = MyPlayer()
        mplayer.play(url_to_play,liz)
    except:
        pass

def proxy2_player(url,name,iconImage):
    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
    url_to_play = server.prepare_url(url)
    infoDialog('ABRINDO PROXY...',iconimage='INFO', time=6000)
    server.mediaserver().start()
    t1 = threading.Thread(target=proxy2_thread, args=(name,iconImage,url_to_play))
    t1.daemon = True
    t1.start()
    t2 = threading.Thread(target=monitor)
    t2.daemon = True
    t2.start()


#### run addon ####
def run(params):
    stream_type = params.get("streamtype", None)
    iconimage = params.get(
        "iconImage", params.get("thumbnailImage", addonIcon)
    )
    name = params.get("name", "GLORIOSO TV")
    url = params.get("url", "")
    description = params.get("description", "")
    if not url:
        dialog("GLORIOSO TV PLAYER")
        return

    stream_type = (stream_type or "").upper()
    if stream_type == "HLSRETRY":
        player_hlsretry(name, url, iconimage, description)
        return
    if stream_type == "TSDOWNLOADER":
        player_tsdownloader(name, url, iconimage, description)
        return
    if stream_type == "FFMPEGDIRECT":
        # CORRIGIDO: Agora chama o player_input correto
        player_input(name, url, iconimage, description)
        return
    if stream_type in ("SERVER2", "SERVER_2", "PROXY2"):
        proxy2_player(url, name, iconimage)
        return

    op = select(
        "SELECT PLAYER",
        [
            "PROXY - HLSRETRY",
            "PROXY - TSDOWNLOADER",
            "PROXY - SERVER 2",
            "INPUTSTREAM FFMPEGDIRECT",
        ],
    )
    if op == 0:
        player_hlsretry(name, url, iconimage, description)
    elif op == 1:
        player_tsdownloader(name, url, iconimage, description)
    elif op == 2:
        proxy2_player(url, name, iconimage)
    elif op == 3:
        # CORRIGIDO: Ordem dos parâmetros alinhada com def player_input(name, url, iconimage, description)
        player_input(name, url, iconimage, description)