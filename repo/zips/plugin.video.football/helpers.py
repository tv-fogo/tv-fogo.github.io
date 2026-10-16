# -*- coding: utf-8 -*-
try:
    from kodi_six import xbmc as xbmc_, xbmcgui as xbmcgui_, xbmcplugin as xbmcplugin_, xbmcaddon as xbmcaddon_, xbmcvfs as xbmcvfs_
except:
    pass
import six as six_
if six_.PY3:
    from urllib.parse import urlparse as urlparse_, parse_qs as parse_qs_, parse_qsl as parse_qsl_, quote as quote_, unquote as unquote_, quote_plus as quote_plus_, unquote_plus as unquote_plus_, urlencode as urlencode_ #python 3
else:
    from urlparse import urlparse as urlparse_, parse_qs as parse_qs_, parse_qsl as parse_qsl_ #python 2
    from urllib import quote as quote_, unquote as unquote_, quote_plus as quote_plus_, unquote_plus as unquote_plus_, urlencode as urlencode_
import sys
import os as os_
import requests as rq
try:
    import json as json_
except ImportError:
    import simplejson as json_
try:
    from bs4 import BeautifulSoup as bfs
except Exception:
    bfs = None
import base64
import threading
import time
import uuid

six = six_
requests = rq
json = json_
BeautifulSoup = bfs
try:
    xbmc = xbmc_
    xbmcgui = xbmcgui_
    xbmcplugin = xbmcplugin_
    xbmcaddon = xbmcaddon_
    xbmcvfs = xbmcvfs_
except:
    pass
urlparse = urlparse_
parse_qs = parse_qs_
parse_qsl = parse_qsl_
quote = quote_
unquote = unquote_
quote_plus = quote_plus_
unquote_plus = unquote_plus_
urlencode = urlencode_
os = os_

# if six.PY2:
#     reload(sys)
#     sys.setdefaultencoding('utf-8')




try:
    class Progress_six:
        dp = xbmcgui.DialogProgress()
        @classmethod
        def create(cls,heading,msg):
            if six.PY3:
                cls.dp.create(str(heading),str(msg))
            else:
                cls.dp.create(str(heading),str(msg), '','')
        @classmethod
        def update(cls,update,heading):
            if six.PY3:
                cls.dp.update(int(update), str(heading))
            else:
                cls.dp.update(int(update), str(heading),'', '')

    class ProgressBG_six:
        dp = xbmcgui.DialogProgressBG()
        @classmethod
        def create(cls,heading,msg):
            if six.PY3:
                cls.dp.create(str(heading),str(msg))
            else:
                cls.dp.create(str(heading),str(msg), '','')
        @classmethod
        def update(cls,update,heading):
            if six.PY3:
                cls.dp.update(int(update), str(heading))
            else:
                cls.dp.update(int(update), str(heading),'', '')
except:
    pass

try:
    addon = xbmcaddon.Addon()
    addonID = addon.getAddonInfo('id')
    addonName = addon.getAddonInfo('name')
    addonVersion = addon.getAddonInfo('version')
    localLang = addon.getLocalizedString
    homeDir = addon.getAddonInfo('path')
    translate = xbmcvfs.translatePath if six.PY3 else xbmc.translatePath
    addonIcon = translate(os.path.join(homeDir, 'icon.jpg'))
    addonFanart = translate(os.path.join(homeDir, 'fanart.jpeg'))
    profile = translate(addon.getAddonInfo('profile'))
    kversion = int(xbmc.getInfoLabel('System.BuildVersion').split(".")[0])
    plugin = sys.argv[0]
    handle = int(sys.argv[1])
    dialog_ = xbmcgui.Dialog()
    executebuiltin = xbmc.executebuiltin
except:
    pass

def yesno(heading="",message="",nolabel="Nao",yeslabel="Sim"):
    if not heading:
        heading = addonName
    if six.PY2:
        q = dialog_.yesno(heading=heading, line1=message, nolabel=nolabel, yeslabel=yeslabel)
    else:
        q = dialog_.yesno(heading=heading, message=message, nolabel=nolabel, yeslabel=yeslabel)
    return q        

def opensettings():
    addon.openSettings()

def getsetting(text):
    return addon.getSetting(text)

def setsetting(key,value):
    return addon.setSetting(key, value)

def exists(path):
    return xbmcvfs.exists(path)

def mkdir(path):
    try:
        xbmcvfs.mkdir(path)
    except:
        pass

def dialog(msg):
    dialog = xbmcgui.Dialog()
    dialog.ok(addonName, msg)

def dialog2(title, msg):
    dialog = xbmcgui.Dialog()
    dialog.ok(title, msg)    

def dialog_text(msg):
    dialog = xbmcgui.Dialog()
    dialog.textviewer(addonName, msg)

def progress_six():
    dp = Progress_six()
    return dp 

def progressBG_six():
    pDialog = ProgressBG_six()
    return pDialog

def select(name,items):
    op = dialog_.select(name, items)
    return op 

def log(txt):
    try:
        message = ''.join([addonName, ' : ', txt])
        xbmc.log(msg=message, level=xbmc.LOGDEBUG)
    except:
        pass


# Estado por execucao do plugin. O proxy persistente e mantido pelo service.py;
# este start() apenas garante compatibilidade quando o addon acabou de ser instalado
# e o Kodi ainda nao reiniciou o servico.
_artwork_proxy_checked = False
_artwork_proxy_available = False


def _is_remote_http_url(value):
    try:
        text = to_utf8(value).strip().lower()
        return text.startswith('http://') or text.startswith('https://')
    except Exception:
        return False


def proxy_artwork_url(value, fallback=''):
    """Entrega artes remotas pelo proxy local do addon.

    O Kodi baixa thumbs/fanarts fora do processo do plugin. Sem essa reescrita,
    ele voltaria a consultar o DNS padrao da rede. Quando o proxy nao estiver
    disponivel, usa somente arte local de fallback — nunca devolve a URL remota
    direta para evitar uma saida fora do fluxo Cloudflare.
    """
    global _artwork_proxy_checked, _artwork_proxy_available
    if not value or not _is_remote_http_url(value):
        return value or fallback
    try:
        import localproxy
        if not _artwork_proxy_checked:
            _artwork_proxy_checked = True
            _artwork_proxy_available = bool(localproxy.start())
        if _artwork_proxy_available:
            return localproxy.proxy_url(value)
        log('Proxy de artes indisponivel; usando arte local.')
    except Exception as exc:
        try:
            log('Falha ao preparar arte pelo proxy: {0}'.format(str(exc)))
        except Exception:
            pass
    return fallback

def to_utf8(text):
    if isinstance(text, bytes):
        return text.decode('utf-8', errors='ignore')
    try:
        return str(text)
    except:
        return u''    

def string_utf8(string):
    if isinstance(string, bytes):
        return string

    return string.encode("utf-8", errors="ignore")

def normalize_text(text):
    if not text:
        return u''

    if six.PY3:
        return text

    # Python 2
    if isinstance(text, unicode):
        try:
            # corrige double-encoding comum (GÃªnio, GÃºnio, etc)
            return text.encode('latin-1').decode('utf-8')
        except:
            return text

    try:
        return text.decode('utf-8')
    except:
        try:
            return text.decode('latin-1')
        except:
            return unicode(text, errors='ignore')

def to_unicode(text, encoding='utf-8', errors='strict'):
    """Force text to unicode"""
    if isinstance(text, bytes):
        return text.decode(encoding, errors=errors)
    return text

def get_search_string(heading='', message=''):
    """Ask the user for a search string"""
    search_string = None
    keyboard = xbmc.Keyboard(message, heading)
    keyboard.doModal()
    if keyboard.isConfirmed():
        search_string = to_unicode(keyboard.getText())
    return search_string 

def input_text(heading='Put text'):
    vq = get_search_string(heading=heading, message="")        
    if ( not vq ): return False
    return vq

# UI de abertura do player. Mantemos o dialogo em background para nao bloquear
# o invoker do plugin e fechamos assim que o Kodi confirma audio/video real.
_playback_wait_lock = threading.RLock()
_playback_wait_current = None


class _PlaybackWaitUI(object):
    def __init__(self, title=''):
        self.title = to_utf8(title or '')
        self.dialog = None
        self.closed = False
        self.opened_at = 0.0
        self.adopted_bootstrap = False
        self._lock = threading.RLock()

    def open(self):
        with self._lock:
            if self.closed:
                return False
            try:
                dlg = xbmcgui.DialogProgressBG()
                dlg.create('AGUARDE...', self.title or 'Preparando transmissao...')
                self.dialog = dlg
                self.opened_at = time.monotonic()
                try:
                    log('AGUARDE de abertura exibido imediatamente.')
                except Exception:
                    pass
                return True
            except Exception as exc:
                try:
                    log('DialogProgressBG indisponivel; usando notificacao de espera: {0}'.format(str(exc)))
                except Exception:
                    pass
                try:
                    dialog_.notification(addonName, 'AGUARDE...', xbmcgui.NOTIFICATION_INFO, 10000, sound=False)
                except Exception:
                    pass
                return False

    def close(self):
        with self._lock:
            if self.closed:
                return
            self.closed = True
            dlg = self.dialog
            self.dialog = None
        if dlg is not None:
            try:
                dlg.close()
            except Exception:
                pass
        try:
            log('AGUARDE de abertura encerrado em A/V ou término da tentativa.')
        except Exception:
            pass


def begin_playback_wait(title=''):
    """Obtém a UI de espera mais cedo possível.

    addon.py cria um DialogProgressBG mínimo antes de desempacotar o payload da
    rota /play_canal. Aqui adotamos exatamente essa instância, evitando fechar e
    reabrir o diálogo depois de 1-2 s de import/decodificação. Se o bootstrap não
    estiver disponível (chamada interna/teste), criamos a UI normalmente.
    """
    global _playback_wait_current
    previous = None
    with _playback_wait_lock:
        previous = _playback_wait_current
        _playback_wait_current = None
    if previous is not None:
        try:
            previous.close()
        except Exception:
            pass

    wait_ui = None
    try:
        import builtins
        marker = getattr(builtins, '_football_early_wait', None)
        if marker:
            try:
                dlg, opened_at = marker
            except Exception:
                dlg, opened_at = marker, 0.0
            try:
                delattr(builtins, '_football_early_wait')
            except Exception:
                pass
            if dlg is not None:
                wait_ui = _PlaybackWaitUI(title)
                wait_ui.dialog = dlg
                wait_ui.opened_at = float(opened_at or time.monotonic())
                wait_ui.adopted_bootstrap = True
                try:
                    dlg.update(0, 'AGUARDE...', title or 'Preparando transmissao...')
                except Exception:
                    pass
                try:
                    log('AGUARDE bootstrap imediato adotado pelo resolvedor.')
                except Exception:
                    pass
    except Exception:
        wait_ui = None

    if wait_ui is None:
        wait_ui = _PlaybackWaitUI(title)
        wait_ui.open()

    with _playback_wait_lock:
        _playback_wait_current = wait_ui
    return wait_ui


def close_playback_wait(wait_ui=None):
    global _playback_wait_current
    target = wait_ui
    with _playback_wait_lock:
        if target is None:
            target = _playback_wait_current
        if target is _playback_wait_current:
            _playback_wait_current = None
    if target is not None:
        try:
            target.close()
        except Exception:
            pass


def playback_wait_active():
    with _playback_wait_lock:
        current = _playback_wait_current
    return bool(current is not None and not getattr(current, 'closed', True))


def infoDialog(message, iconimage='', time=3000, sound=False):
    # O resolvedor legado chamava AGUARDE somente depois de iniciar a primeira
    # requisicao HTTP. Quando a UI imediata de playback ja esta ativa, suprima
    # essa notificacao tardia para nao criar dois avisos sobrepostos.
    try:
        if to_utf8(message).strip().upper().rstrip('.') == 'AGUARDE' and playback_wait_active():
            return
    except Exception:
        pass
    heading = addonName

    if iconimage == '':
        iconimage = addonIcon
    elif iconimage == 'INFO':
        iconimage = xbmcgui.NOTIFICATION_INFO
    elif iconimage == 'WARNING':
        iconimage = xbmcgui.NOTIFICATION_WARNING
    elif iconimage == 'ERROR':
        iconimage = xbmcgui.NOTIFICATION_ERROR

    message = to_utf8(message)
    heading = to_utf8(heading)

    dialog_.notification(heading, message, iconimage, time, sound=sound)


def notify(msg):
    try:
        infoDialog(msg,iconimage='INFO') 
    except:
        pass

def addMenuItem(params={}, destiny='', context=[], folder=True):
    name = params.get('name', '')
    description = params.get("description", "")
    originaltitle = params.get("originaltitle", "")        
    try:
        params.update({'name': string_utf8(name)})
    except:
        pass
    try:
        params.update({'description': string_utf8(description)})
    except:
        pass
    try:
        params.update({'originaltitle': string_utf8(originaltitle)})
    except:
        pass
    if 'plugin://' in destiny:
        u = destiny
    else: 
        try:
            destiny = destiny.split('/')[1]
        except:
            pass                     
        u = 'plugin://%s/%s/%s'%(plugin.split("/")[2],destiny,quote_plus(urlencode(params)))
    iconimage = params.get("iconimage", "")
    fanart = params.get("fanart", "")
    codec = params.get("codec", "")
    playable = params.get("playable", "")
    duration = params.get("duration", "")
    imdbnumber = params.get("imdbnumber", "")
    if not imdbnumber:
        imdbnumber = params.get("imdb", "")
    aired = params.get("aired", "")
    genre = params.get("genre", "")
    season = params.get("season", "")
    episode = params.get("episode", "")
    year = params.get("year", "")
    mediatype = params.get("mediatype", "video")
    li=xbmcgui.ListItem(name)
    iconimage = proxy_artwork_url(iconimage, addonIcon)
    li.setArt({"icon": "DefaultVideo.png", "thumb": iconimage})
    if kversion > 19:
        info = li.getVideoInfoTag()
        info.setTitle(name)
        info.setPlot(description)
        infotag = True
    else:
        li.setInfo(type="Video", infoLabels={"Title": name, "Plot": description})
        infotag = False
    if year:
        if infotag:
            info.setYear(int(year))
        else:
            li.setInfo('video', {'year': int(year)})
    if codec:
        if infotag:
            info.addVideoStream(xbmc.VideoStreamDetail(codec=str(codec)))
        else:
            li.addStreamInfo('video', {'codec': codec})
    if duration:
        if infotag:
            info.setDuration(int(duration))
        else:
            li.setInfo('video', {'duration': int(duration)})
    if originaltitle:
        if infotag:
            info.setOriginalTitle(str(originaltitle))
        else:
            li.setInfo('video', {'originaltitle': str(originaltitle) })
    if imdbnumber:
        if infotag:
            info.setIMDBNumber(str(imdbnumber))
        else:
            li.setInfo('video', {'imdbnumber': str(imdbnumber)})
    if aired:
        if infotag:
            info.setFirstAired(str(aired))
        else:
            li.setInfo('video', {'aired': str(aired)})
    if genre:
        if infotag:
            info.setGenres([str(genre)])
        else:
            li.setInfo('video', {'genre': str(genre)})
    if season:
        if infotag:
            info.setSeason(int(season))
        else:
            li.setInfo('video', {'season': int(season)})
    if episode:
        if infotag:
            info.setEpisode(int(episode))
        else:
            li.setInfo('video', {'episode': int(episode)})
    if mediatype:
        if infotag:
            info.setMediaType(str(mediatype))
        else:
            li.setInfo('video', {'mediatype': str(mediatype)})       
    if playable and folder == False and not playable == 'false':
        li.setProperty('IsPlayable', 'true')        
    fanart = proxy_artwork_url(fanart, addonFanart)
    li.setProperty('fanart_image', fanart)
    if context:
        li.addContextMenuItems(context)        
    xbmcplugin.addDirectoryItem(handle=handle, url=u, listitem=li, isFolder=folder)


# Vigia somente a abertura e o encerramento do player.
# Após o início da reprodução não existe reconexão automática: Stop manual,
# término do player ou falha da origem sempre devolvem o controle ao usuário.
_PLAYBACK_STARTUP_TIMEOUT = 105.0
_PLAYBACK_POLL_INTERVAL = 0.35
_PLAYBACK_RUNTIME_POLL_INTERVAL = 0.60
_PLAYBACK_SILENT_END_GRACE = 2.20
_playback_watch_lock = threading.RLock()
_playback_watches = []


def _sanitize_failure_reason(reason):
    try:
        value = to_utf8(reason).replace('\r', ' ').replace('\n', ' ').strip()
        return value[:180]
    except Exception:
        return ''


def _offline_content_message(reason=''):
    message = 'Conteúdo indisponível no momento.'
    reason = _sanitize_failure_reason(reason)
    if reason:
        message += '\nErro: {0}.'.format(reason)
    message += '\nTente novamente mais tarde.'
    try:
        xbmcgui.Dialog().ok(addonName, message)
        return
    except Exception:
        pass
    try:
        infoDialog(message.replace('\n', ' '), iconimage='WARNING', time=7000)
    except Exception:
        pass


def _clear_proxy_failure(watch):
    try:
        watch_id = getattr(watch, 'watch_id', '')
        if not watch_id:
            return
        import localproxy
        localproxy.clear_playback_failure(watch_id)
    except Exception:
        pass


def _get_proxy_failure(watch):
    try:
        watch_id = getattr(watch, 'watch_id', '')
        if not watch_id:
            return None
        import localproxy
        state = localproxy.get_playback_failure(watch_id)
        return state if isinstance(state, dict) else None
    except Exception as exc:
        try:
            log('Falha ao consultar estado da origem: {0}'.format(str(exc)))
        except Exception:
            pass
        return None


def _discard_playback_watch(watch):
    try:
        with _playback_watch_lock:
            if watch in _playback_watches:
                _playback_watches.remove(watch)
    except Exception:
        pass
    _clear_proxy_failure(watch)


def _is_hls_stream_url(value):
    try:
        text = to_utf8(value).lower()
        return '.m3u8' in text or 'mf_hls=1' in text
    except Exception:
        return False


class _PlaybackStartupWatch(xbmc.Player):
    def __init__(self, title='', wait_ui=None):
        xbmc.Player.__init__(self)
        self.title = title or ''
        self.wait_ui = wait_ui
        self.player_core_started = threading.Event()
        self.watch_id = uuid.uuid4().hex
        self.started = threading.Event()
        self.failed = threading.Event()
        self.stopped = threading.Event()      # Stop manual/externo
        self.ended = threading.Event()        # EOF/fim comunicado pelo Kodi
        self.reported = threading.Event()
        self.proxy_tracking = False
        self.proxy_failure = None
        self.watch_url = ''
        self.listitem = None
        self.is_hls = False
        self.attempt_started_at = time.time()
        self.playback_started_at = 0.0
        self.not_playing_since = 0.0
        self._state_lock = threading.RLock()

    def _mark_started(self):
        with self._state_lock:
            if not self.started.is_set():
                self.playback_started_at = time.time()
            self.started.set()
        # onAVStarted (ou isPlayingVideo como fallback) significa que o Kodi ja
        # possui fluxo A/V real; este e o ponto correto para remover AGUARDE.
        close_playback_wait(self.wait_ui)

    def begin_attempt(self):
        with self._state_lock:
            self.started.clear()
            self.player_core_started.clear()
            self.failed.clear()
            self.stopped.clear()
            self.ended.clear()
            self.proxy_failure = None
            self.attempt_started_at = time.time()
            self.playback_started_at = 0.0
            self.not_playing_since = 0.0

    def playback_age(self):
        try:
            base = self.playback_started_at or self.attempt_started_at
            return max(0.0, time.time() - float(base or time.time()))
        except Exception:
            return 0.0

    def onAVStarted(self):
        self._mark_started()

    def onPlayBackStarted(self):
        # A documentacao do Kodi 21 deixa claro que este callback pode ocorrer
        # antes de existir audio/video. Mantemos apenas a marca do player core;
        # AGUARDE fecha em onAVStarted/isPlayingVideo.
        self.player_core_started.set()

    def onPlayBackError(self):
        self.failed.set()
        close_playback_wait(self.wait_ui)

    def onPlayBackStopped(self):
        # É a trilha do Stop explícito; jamais reiniciamos por ela.
        self.stopped.set()
        close_playback_wait(self.wait_ui)

    def onPlayBackEnded(self):
        # Nos logs do Kodi, EOF de live HLS chega por Ended, não Stopped.
        self.ended.set()
        close_playback_wait(self.wait_ui)

    def is_actually_playing(self):
        try:
            if self.isPlayingVideo():
                return True
        except Exception:
            pass
        try:
            return bool(self.isPlaying())
        except Exception:
            return False


def _stop_unstarted_player(watch):
    """Encerra apenas uma abertura que já foi classificada como falha."""
    try:
        if not watch.is_actually_playing():
            watch.stop()
    except Exception:
        pass


def _report_playback_failure(watch, reason, stop_player=False):
    try:
        if watch.reported.is_set():
            return
        watch.reported.set()
        close_playback_wait(getattr(watch, 'wait_ui', None))
        if stop_player:
            _stop_unstarted_player(watch)
        _offline_content_message(reason)
    except Exception as exc:
        try:
            log('Falha ao informar indisponibilidade: {0}'.format(str(exc)))
        except Exception:
            pass


def _monitor_player_lifecycle(watch):
    """Monitora a abertura e encerra o vigia sem reabrir uma live.

    O callback de Stop do Kodi não é entregue de modo confiável ao objeto
    xbmc.Player criado pelo addon em todas as builds. Portanto, depois que a
    reprodução já começou, qualquer término é tratado como final da sessão;
    o addon não tenta tocar a URL novamente nem exibe "Transmissão oscilou".
    """
    startup_mode = True
    startup_deadline = time.time() + float(_PLAYBACK_STARTUP_TIMEOUT)
    try:
        while True:
            if startup_mode:
                # Reprodução válida ganha sempre: uma tentativa transitória que
                # se recuperou não deve gerar popup nem interromper o canal.
                if watch.started.is_set() or watch.is_actually_playing():
                    watch._mark_started()
                    # A partir daqui o Kodi ja assumiu o player. Nao mantemos uma
                    # thread Python viva ate o Stop; isso evita que a rota de plugin
                    # seja reavaliada ao retornar para o container anterior.
                    return

                proxy_failure = _get_proxy_failure(watch)
                if proxy_failure:
                    watch.proxy_failure = proxy_failure
                    reason = proxy_failure.get('message', '')
                    attempts = int(proxy_failure.get('count', 1) or 1)
                    immediate = bool(proxy_failure.get('immediate', False))
                    # 401/403/404/410 são terminais; falhas transitórias precisam
                    # de uma nova tentativa confirmada antes de exibir o aviso.
                    if immediate or attempts >= 2:
                        _report_playback_failure(watch, reason, stop_player=True)
                        return

                if watch.failed.is_set():
                    reason = ''
                    if watch.proxy_failure:
                        reason = watch.proxy_failure.get('message', '')
                    if not reason:
                        reason = 'o player do Kodi não conseguiu abrir a fonte'
                    _report_playback_failure(watch, reason, stop_player=False)
                    return

                if watch.stopped.is_set():
                    # Stop manual sempre vence qualquer falha que tenha sido
                    # registrada em paralelo pela origem: não há popup nem retry.
                    return

                if watch.ended.is_set():
                    reason = watch.proxy_failure.get('message', '') if watch.proxy_failure else ''
                    _report_playback_failure(watch, reason or 'a fonte encerrou antes de iniciar a transmissão', stop_player=False)
                    return

                if time.time() >= startup_deadline:
                    reason = watch.proxy_failure.get('message', '') if watch.proxy_failure else ''
                    if not reason:
                        reason = 'o servidor não respondeu dentro do tempo esperado'
                    _report_playback_failure(watch, reason, stop_player=True)
                    return

                time.sleep(_PLAYBACK_POLL_INTERVAL)
                continue

            # Após a abertura, este addon não reabre automaticamente uma live.
            # Isso cobre Stop manual mesmo quando o callback não chega ao objeto
            # Python que iniciou o player. O diagnóstico técnico permanece no
            # log do proxy, mas a próxima reprodução é sempre decisão do usuário.
            if watch.stopped.is_set() or watch.ended.is_set() or watch.failed.is_set():
                return

            proxy_failure = _get_proxy_failure(watch)
            if proxy_failure:
                watch.proxy_failure = proxy_failure

            # Algumas builds registram o fim de HLS somente no player interno,
            # sem callback Python. Após uma pequena graça, liberamos o vigia em
            # silêncio; não há popup, retry nem nova abertura da URL.
            if watch.is_actually_playing():
                watch.not_playing_since = 0.0
            else:
                if not watch.not_playing_since:
                    watch.not_playing_since = time.time()
                silent_age = time.time() - float(watch.not_playing_since or time.time())
                if (watch.is_hls and watch.playback_age() >= 3.0 and
                        silent_age >= float(_PLAYBACK_SILENT_END_GRACE)):
                    try:
                        log('Live HLS finalizada; vigia encerrado sem reconexão automática.')
                    except Exception:
                        pass
                    return

            time.sleep(_PLAYBACK_RUNTIME_POLL_INTERVAL)
    except Exception as exc:
        try:
            log('Monitor de reprodução do player falhou: {0}'.format(str(exc)))
        except Exception:
            pass
    finally:
        if not watch.started.is_set():
            close_playback_wait(getattr(watch, 'wait_ui', None))
        _discard_playback_watch(watch)


def _inputstream_ffmpegdirect_available():
    """Confirma que o motor binário existe e está habilitado no Kodi.

    System.HasAddon() informa apenas instalação. Em Android é comum o binário
    permanecer instalado, porém desabilitado após atualização ou por build do
    fabricante. Como esta origem depende de FFmpegDirect para o HLS fMP4 muxado,
    indisponibilidade é tratada explicitamente como falha, sem fallback silencioso.
    """
    addon_id = 'inputstream.ffmpegdirect'
    try:
        if not bool(xbmc.getCondVisibility('System.HasAddon({})'.format(addon_id))):
            return False
    except Exception:
        return False
    try:
        if not bool(xbmc.getCondVisibility('System.AddonIsEnabled({})'.format(addon_id))):
            return False
    except Exception:
        # Kodi 19+ expõe a condição acima. Caso uma build compatível não a
        # disponibilize, a presença do binário ainda permite o comportamento
        # legado sem bloquear a reprodução.
        pass
    try:
        xbmcaddon.Addon(addon_id).getAddonInfo('version')
    except Exception:
        return False
    return True


def _configure_hls_inputstream(listitem, url):
    """Usa FFmpegDirect para HLS fMP4 muxado quando disponível.

    Esta origem publica vídeo H.264 e áudio AAC no mesmo init/segmento fMP4.
    O InputStream Adaptive separa os fluxos lógicos, mas não recebe a trilha
    AAC desta representação muxada e deixa a imagem sem som. O FFmpegDirect
    usa libavformat para demuxar o mesmo objeto, preservando vídeo e áudio.

    O proxy local permanece responsável por DNS Cloudflare interno, sessão,
    redirects, Referer/Origin, Range/206 e validação HTTP. A marca local
    existente apenas desliga a fila HLS própria do proxy porque o inputstream
    externo administra a playlist; ela não é enviada ao CDN.
    """
    if not listitem or not _is_hls_stream_url(url):
        return url
    if not _inputstream_ffmpegdirect_available():
        return ''

    # A marca mf_isa=1 desliga a fila HLS do proxy porque FFmpegDirect passa a
    # administrar a playlist. Ela só pode ser aplicada depois que todas as
    # propriedades do ListItem foram aceitas. Nesta versão, falha de configuração
    # é terminal para HLS e nunca libera fallback silencioso ao player padrão.
    try:
        listitem.setMimeType('application/vnd.apple.mpegurl')
        listitem.setContentLookup(False)
        listitem.setProperty('inputstream', 'inputstream.ffmpegdirect')
        listitem.setProperty('inputstream.ffmpegdirect.manifest_type', 'hls')
        listitem.setProperty('inputstream.ffmpegdirect.open_mode', 'ffmpeg')
        listitem.setProperty('inputstream.ffmpegdirect.is_realtime_stream', 'true')
    except Exception as exc:
        try:
            log('InputStream FFmpegDirect não pôde ser configurado; reprodução HLS bloqueada: {0}'.format(str(exc)))
        except Exception:
            pass
        return ''

    try:
        import localproxy
        # Reutiliza a marca local de inputstream externo, sem alterar a origem.
        marked_url = localproxy.attach_adaptive_playback(url)
        if marked_url:
            url = marked_url
    except Exception as exc:
        # Sem a marca local, o player ainda pode usar FFmpegDirect; o proxy
        # mantém o fallback HLS próprio, que é mais seguro do que desativar a
        # proteção da playlist sem confirmação.
        try:
            log('Marca local do InputStream indisponível; mantendo proteção HLS do proxy: {0}'.format(str(exc)))
        except Exception:
            pass
    try:
        log('HLS fMP4 muxado usando InputStream FFmpegDirect; áudio AAC preservado.')
    except Exception:
        pass
    return url


def play_with_startup_watch(url, listitem, title='', wait_ui=None):
    watch = None
    try:
        watch = _PlaybackStartupWatch(title, wait_ui=wait_ui)
        watch_url = url
        try:
            import localproxy
            watch_url = localproxy.attach_playback_watch(url, watch.watch_id)
            watch.proxy_tracking = (watch_url != url)
        except Exception as exc:
            try:
                log('Rastreamento de falha da origem indisponível: {0}'.format(str(exc)))
            except Exception:
                pass

        watch.is_hls = _is_hls_stream_url(watch_url)
        if watch.is_hls:
            # Nesta versão o FFmpegDirect é dependência obrigatória. Não permita
            # fallback silencioso ao VideoPlayer padrão, pois ele não preserva de
            # forma confiável o áudio AAC desta origem fMP4 em todas as plataformas.
            if not _inputstream_ffmpegdirect_available():
                _offline_content_message('o componente InputStream FFmpegDirect não está disponível ou está desativado')
                return False
            configured_url = _configure_hls_inputstream(listitem, watch_url)
            if not configured_url:
                _offline_content_message('o InputStream FFmpegDirect não pôde ser configurado para esta transmissão')
                return False
            watch_url = configured_url
        watch.watch_url = watch_url
        watch.listitem = listitem
        watch.is_hls = _is_hls_stream_url(watch_url)
        watch.begin_attempt()
        with _playback_watch_lock:
            _playback_watches.append(watch)

        try:
            listitem.setPath(watch_url)
        except Exception:
            pass
        watch.play(item=watch_url, listitem=listitem)
        worker = threading.Thread(target=_monitor_player_lifecycle, args=(watch,))
        worker.daemon = True
        worker.start()
        return True
    except Exception as exc:
        _discard_playback_watch(watch)
        try:
            log('Falha ao iniciar player: {0}'.format(str(exc)))
        except Exception:
            pass
        _offline_content_message('o player não pôde ser iniciado')
        return False

def resolve_with_startup_watch(url, listitem, title='', wait_ui=None):
    """Entrega um item reproduzivel pelo contrato nativo de plugins do Kodi.

    A URL continua carregando mf_watch para o proxy diagnosticar apenas a abertura.
    O vigia termina assim que A/V real inicia, portanto nao permanece associado ao
    Stop e nao transforma o retorno ao container em uma nova execucao da raiz.
    """
    watch = None
    try:
        watch = _PlaybackStartupWatch(title, wait_ui=wait_ui)
        watch_url = url
        try:
            import localproxy
            watch_url = localproxy.attach_playback_watch(url, watch.watch_id)
            watch.proxy_tracking = (watch_url != url)
        except Exception as exc:
            try:
                log('Rastreamento de falha da origem indisponível: {0}'.format(str(exc)))
            except Exception:
                pass

        watch.is_hls = _is_hls_stream_url(watch_url)
        if watch.is_hls:
            if not _inputstream_ffmpegdirect_available():
                close_playback_wait(wait_ui)
                _offline_content_message('o componente InputStream FFmpegDirect não está disponível ou está desativado')
                try:
                    xbmcplugin.setResolvedUrl(int(sys.argv[1]), False, listitem)
                except Exception:
                    pass
                return False
            configured_url = _configure_hls_inputstream(listitem, watch_url)
            if not configured_url:
                close_playback_wait(wait_ui)
                _offline_content_message('o InputStream FFmpegDirect não pôde ser configurado para esta transmissão')
                try:
                    xbmcplugin.setResolvedUrl(int(sys.argv[1]), False, listitem)
                except Exception:
                    pass
                return False
            watch_url = configured_url

        watch.watch_url = watch_url
        watch.listitem = listitem
        watch.is_hls = _is_hls_stream_url(watch_url)
        watch.begin_attempt()
        with _playback_watch_lock:
            _playback_watches.append(watch)
        listitem.setPath(watch_url)

        # IsPlayable + setResolvedUrl e o contrato nativo de video plugins Kodi.
        # O monitor existe apenas durante o startup; onAVStarted fecha AGUARDE.
        xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, listitem)
        worker = threading.Thread(target=_monitor_player_lifecycle, args=(watch,))
        worker.daemon = True
        worker.start()
        return True
    except Exception as exc:
        _discard_playback_watch(watch)
        close_playback_wait(wait_ui)
        try:
            xbmcplugin.setResolvedUrl(int(sys.argv[1]), False, listitem)
        except Exception:
            pass
        try:
            log('Falha ao resolver player: {0}'.format(str(exc)))
        except Exception:
            pass
        _offline_content_message('o player não pôde ser iniciado')
        return False


def play_video(params):
    name = params.get('name', '')
    url = params.get('url', '')
    sub = params.get('sub', [])
    description = params.get("description", "")
    originaltitle = params.get("originaltitle", "") 
    iconimage = params.get("iconimage", "")
    fanart = params.get("fanart", "")
    codec = params.get("codec", "")
    playable = params.get("playable", "")
    wait_ui = params.get("_wait_ui")
    duration = params.get("duration", "")
    imdbnumber = params.get("imdbnumber", "")
    if not imdbnumber:
        imdbnumber = params.get("imdb", "")
    aired = params.get("aired", "")
    genre = params.get("genre", "")
    season = params.get("season", "")
    episode = params.get("episode", "")
    year = params.get("year", "")
    mediatype = params.get("mediatype", "video")
    li=xbmcgui.ListItem(name)
    iconimage = proxy_artwork_url(iconimage, addonIcon)
    li.setArt({"icon": "DefaultVideo.png", "thumb": iconimage})
    if kversion > 19:
        info = li.getVideoInfoTag()
        info.setTitle(name)
        info.setPlot(description)
        infotag = True
    else:
        li.setInfo(type="Video", infoLabels={"Title": name, "Plot": description})
        infotag = False
    if year:
        if infotag:
            info.setYear(int(year))
        else:
            li.setInfo('video', {'year': int(year)})
    if codec:
        if infotag:
            info.addVideoStream(xbmc.VideoStreamDetail(codec=str(codec)))
        else:
            li.addStreamInfo('video', {'codec': codec})
    if duration:
        if infotag:
            info.setDuration(int(duration))
        else:
            li.setInfo('video', {'duration': int(duration)})
    if originaltitle:
        if infotag:
            info.setOriginalTitle(str(originaltitle))
        else:
            li.setInfo('video', {'originaltitle': str(originaltitle) })
    if imdbnumber:
        if infotag:
            info.setIMDBNumber(str(imdbnumber))
        else:
            li.setInfo('video', {'imdbnumber': str(imdbnumber)})
    if aired:
        if infotag:
            info.setFirstAired(str(aired))
        else:
            li.setInfo('video', {'aired': str(aired)})
    if genre:
        if infotag:
            info.setGenres([str(genre)])
        else:
            li.setInfo('video', {'genre': str(genre)})
    if season:
        if infotag:
            info.setSeason(int(season))
        else:
            li.setInfo('video', {'season': int(season)})
    if episode:
        if infotag:
            info.setEpisode(int(episode))
        else:
            li.setInfo('video', {'episode': int(episode)})
    if mediatype:
        if infotag:
            info.setMediaType(str(mediatype))
        else:
            li.setInfo('video', {'mediatype': str(mediatype)})
    fanart = proxy_artwork_url(fanart, addonFanart)
    try:
        li.setArt({'fanart': fanart})
    except Exception:
        li.setProperty('fanart_image', fanart)
    else:
        # Mantém a propriedade legada para skins antigas sem sacrificar a API
        # moderna do Kodi 20/21.
        li.setProperty('fanart_image', fanart)
    if sub:
        li.setSubtitles(sub)

    if playable and playable != 'false':
        return resolve_with_startup_watch(url, li, name, wait_ui=wait_ui)

    # Fluxo legado preservado para chamadas internas que nao sejam itens
    # IsPlayable. O vigia tambem termina no startup, nunca no Stop.
    li.setPath(url)
    return play_with_startup_watch(url, li, name, wait_ui=wait_ui)

def setcontent(name):
    xbmcplugin.setContent(handle, name)  

def end(cache=True):
    # O container pode ser reutilizado ao voltar do player. A porta do proxy e
    # dinamica, mas persistente por preferencia e revalidada no service; portanto
    # nao precisamos invalidar a listagem a cada Stop.
    xbmcplugin.endOfDirectory(handle, cacheToDisc=cache)

def setview(name):
    mode = {'Wall': '500',
            'List': '50',
            'Poster': '51',
            'Shift': '53',
            'InfoWall': '54',
            'WideList': '55',
            'Fanart': '502'
            }.get(name, '50')
    view = 'Container.SetViewMode(%s)'%mode
    xbmc.executebuiltin(view)  

def extract_params():
    try:
        plugin_route = sys.argv[0].split('/')[3:]
        route_sys = plugin_route[0] if plugin_route else ''
        params = {}
        try:
            param_root = plugin_route[1] # params from sys
            param_root = unquote_plus(param_root).split('&')
            for command in param_root:
                if '=' in command:
                    split_command = command.split('=', 1)
                    key = unquote_plus(split_command[0])
                    value = unquote_plus(split_command[1])
                    params[key] = value
                else:
                    params[command] = ''
        except:
            pass
        #params = dict(parse_qsl(unquote_plus(plugin_route[1]))) if len(plugin_route) > 1 else {}
        return route_sys, params
    except Exception as e:
        log('Failed to extract parameters: {0}'.format(str(e)))
        return '', {} 
    
def route(route_path):
    def decorator(func):
        route_sys, params = extract_params()
        if route_sys == route_path.strip('/'):
            try:
                if params:
                    func(params)
                else:
                    func()
            except Exception as e:
                log('Route execution error: {0}'.format(str(e)))
        return func
    return decorator


