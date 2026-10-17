# -*- coding: utf-8 -*-
from helpers import *
import threading
import socket
import time
import os
import requests
import re
import ssl
import json
import sys
from contextlib import contextmanager
try:
    requests.packages.urllib3.disable_warnings()
except Exception:
    pass
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
try:
    from urllib.parse import urljoin
except Exception:
    from urlparse import urljoin

HOST = '127.0.0.1'
# Porta 0 delega ao kernel a escolha de uma porta TCP efêmera livre. A porta
# efetivamente vinculada é publicada em Window(10000) para todos os processos
# Python do addon, eliminando colisões com portas fixas de outros serviços.
DYNAMIC_PORT = 0
HEALTH_PATH = '/_football_health'
HEALTH_TOKEN = 'FOOTBALL_PROXY_V016'

DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'
TLS_VERIFY = True

WINDOW = xbmcgui.Window(10000)
PROPERTY_NAME = 'football.proxy.running'
PORT_PROPERTY_NAME = 'football.proxy.port'
OWNER_PROPERTY_NAME = 'football.proxy.owner'
# A porta continua dinamica (nenhum numero fixo no codigo), mas o ultimo bind
# escolhido pelo kernel vira preferencia para o proximo inicio. Isso mantem URLs
# de artwork em cache validas entre reinicios. Se houver colisao, cai atomicamente
# para porta 0 e grava a nova escolha.
DYNAMIC_PORT_STATE_FILE = os.path.join(profile, 'dynamic_proxy_port.json')

def privacy_mode_enabled():
    """O modo HTTPS estrito fica sempre ligado e não depende de preferências."""
    return True


_TLS_SUCCESS_LOG_LOCK = threading.Lock()
_TLS_SUCCESS_LOG_HOSTS = {}
_TLS_SUCCESS_LOG_INTERVAL = 60.0


def _log_verified_https(response, requested_url):
    """Log TLS success by host only, throttled to avoid URL/token leakage."""
    try:
        final_url = getattr(response, 'url', '') or requested_url
        parsed = urlparse(final_url)
        if parsed.scheme.lower() != 'https' or not parsed.hostname:
            return
        host = parsed.hostname.lower()
        now = time.time()
        with _TLS_SUCCESS_LOG_LOCK:
            previous = _TLS_SUCCESS_LOG_HOSTS.get(host, 0)
            if now - previous < _TLS_SUCCESS_LOG_INTERVAL:
                return
            _TLS_SUCCESS_LOG_HOSTS[host] = now
            for cached_host, timestamp in list(_TLS_SUCCESS_LOG_HOSTS.items()):
                if now - timestamp > 900:
                    _TLS_SUCCESS_LOG_HOSTS.pop(cached_host, None)
        xbmc.log(
            '[FOOTBALL HTTPS] TLS validado para host: {}.'.format(host),
            xbmc.LOGINFO
        )
    except Exception:
        pass

# Canal de diagnóstico entre o proxy de serviço e o processo do plugin.
# Só armazena motivo técnico resumido; nunca URL, token ou cabeçalho remoto.
PLAYBACK_WATCH_QUERY = 'mf_watch'
PLAYBACK_HLS_QUERY = 'mf_hls'
# Marca somente a rota local quando o ListItem escolhe um inputstream externo.
# Nunca é enviado à origem e serve para o proxy não reescrever a janela HLS
# enquanto o demuxador externo administra a própria leitura live.
PLAYBACK_ADAPTIVE_QUERY = 'mf_isa'
PLAYBACK_FAILURE_PREFIX = 'football.playback.failure.'
PLAYBACK_FAILURE_TTL = 180.0
PLAYBACK_WATCH_RE = re.compile(r'^[A-Za-z0-9_-]{8,96}$')

# HLS e segmentos de live são pequenos e precisam chegar íntegros ao Kodi.
# O proxy lê o objeto inteiro antes de responder apenas quando ele pertence a uma
# playlist HLS. Assim, uma conexão que cai no meio do segmento pode ser tentada
# novamente sem expor ao player um arquivo truncado que acabaria em EOF.
# Perfil HLS derivado das partes compatíveis do proxy FOOTBALL: retry curto,
# revalidação sem cache e cabeçalhos alternativos. Ele é aplicado apenas a
# playlists/segmentos live; não altera VOD, imagens ou o DNS privado do addon.
HLS_PLAYLIST_RETRY_ATTEMPTS = 3
HLS_SEGMENT_RETRY_ATTEMPTS = 2
HLS_RETRY_BACKOFF = (0.12, 0.28)
HLS_PLAYLIST_TIMEOUT = (5.0, 8.0)
# O Kodi abandona esta fonte fMP4 em cerca de sete segundos quando o próximo
# segmento não chega. O proxy, portanto, falha cedo o bastante para recuperar
# uma vez antes do EOF local, sem esperar os 12 s antigos por uma origem morta.
HLS_SEGMENT_TIMEOUT = (3.0, 3.0)
HLS_LIVE_JUMP_PLAYLIST_TIMEOUT = (1.4, 1.4)
HLS_LIVE_JUMP_SEGMENT_TIMEOUT = (1.8, 1.8)
HLS_SEGMENT_RETRY_BUDGET = 6.45
HLS_MAX_OBJECT_BYTES = 32 * 1024 * 1024
HLS_PLAYLIST_SUFFIXES = ('.m3u8', '.m3u')
HLS_CONTEXT_TTL = 120.0
HLS_CONTEXT_LIMIT = 48
HLS_INIT_CACHE_TTL = 180.0
HLS_INIT_CACHE_LIMIT = 48
# Uma sessão HTTP fica isolada por reprodução (mf_watch). Ela preserva somente
# cookies legitimamente emitidos pela origem durante aquela execução e permite
# reutilizar a conexão upstream. Nunca é compartilhada entre canais/usuários,
# nunca é persistida em disco e expira junto com o contexto HLS.
HLS_SESSION_TTL = 180.0
HLS_SESSION_LIMIT = 48
# Buffer HLS real: o player recebe uma playlist alguns segmentos atrás da
# borda live e o proxy pré-baixa esses fragmentos completos em RAM. Assim, uma
# oscilação curta do CDN acontece enquanto ainda existe mídia válida para tocar.
# O atraso é deliberadamente limitado a três segmentos e só é usado em lives
# com janela suficiente, preservando VOD e playlists terminadas.
HLS_LIVE_HOLDBACK_SEGMENTS = 3
HLS_LIVE_HOLDBACK_MIN_SEGMENTS = 5
HLS_BUFFER_ENABLED = True
HLS_BUFFER_PREFETCH_SEGMENTS = 8
HLS_BUFFER_PREFETCH_ATTEMPTS = 2
HLS_BUFFER_PREFETCH_TIMEOUT = (2.0, 2.8)
# Antes de devolver a primeira playlist live, aguarda no máximo alguns segundos
# por dois segmentos completos. O Kodi inicia já com uma pequena reserva, sem
# transformar troca de canal em espera longa quando a origem está realmente fora.
HLS_BUFFER_STARTUP_SEGMENTS = 4
HLS_BUFFER_STARTUP_WAIT = 5.5
# Janela liberada ao player e reserva que permanece no proxy. Cada segmento
# desta fonte dura ~6 s; três de reserva equivalem a ~18 s para absorver
# microquedas do CDN sem entregar segmento ainda não confirmado.
HLS_BUFFER_RELEASE_WINDOW = 5
HLS_BUFFER_RELEASE_MIN_SEGMENTS = 4
HLS_BUFFER_RELEASE_RESERVE = 3
HLS_BUFFER_OBJECT_MAX_BYTES = 8 * 1024 * 1024
HLS_BUFFER_MAX_SEGMENTS_PER_WATCH = 10
HLS_BUFFER_MAX_BYTES_PER_WATCH = 64 * 1024 * 1024
HLS_BUFFER_MAX_BYTES_GLOBAL = 96 * 1024 * 1024
HLS_BUFFER_TTL = 120.0
HLS_BUFFER_CONTEXT_TTL = 150.0


def _runtime_is_android():
    """Detecta Android sem depender de paths do sistema operacional."""
    try:
        return bool(xbmc.getCondVisibility('System.Platform.Android'))
    except Exception:
        return False


# Windows é a referência já validada em produção e mantém os valores originais.
# No Android, a mesma rota HTTP/FFmpegDirect é usada, mas o proxy aceita leitura
# um pouco mais lenta e limita mais agressivamente seus caches HLS em RAM. Isso
# evita timeout prematuro e pressão de memória em aparelhos modestos sem alterar
# a sessão validada no Windows.
RUNTIME_PLATFORM = 'android' if _runtime_is_android() else 'standard'
if RUNTIME_PLATFORM == 'android':
    HLS_PLAYLIST_TIMEOUT = (5.0, 10.0)
    HLS_SEGMENT_TIMEOUT = (4.0, 5.0)
    HLS_SEGMENT_RETRY_BUDGET = 10.0
    HLS_BUFFER_PREFETCH_SEGMENTS = 4
    HLS_BUFFER_PREFETCH_TIMEOUT = (2.5, 4.0)
    HLS_BUFFER_STARTUP_SEGMENTS = 2
    HLS_BUFFER_STARTUP_WAIT = 4.5
    HLS_BUFFER_RELEASE_WINDOW = 4
    HLS_BUFFER_RELEASE_MIN_SEGMENTS = 3
    HLS_BUFFER_RELEASE_RESERVE = 2
    HLS_BUFFER_MAX_SEGMENTS_PER_WATCH = 6
    HLS_BUFFER_MAX_BYTES_PER_WATCH = 32 * 1024 * 1024
    HLS_BUFFER_MAX_BYTES_GLOBAL = 48 * 1024 * 1024
    HLS_BUFFER_TTL = 90.0
    HLS_BUFFER_CONTEXT_TTL = 120.0

# O perfil deve ser estável durante toda a sessão; alternar de navegador em
# retries é pior para CDNs que associam a rota ao cabeçalho inicial.
HLS_USER_AGENT_POOL = (DEFAULT_UA,)
# Desativado por padrão: pular um fragmento fMP4 pode introduzir artefatos ou
# descontinuidades. Em falha real, o player retoma a playlist de forma limpa.
HLS_ENABLE_LIVE_SEGMENT_JUMP = False
# Contexto e init segment permanecem estritamente em memória de processo.
_HLS_CONTEXT_LOCK = threading.RLock()
_HLS_PLAYLIST_CONTEXT = {}
_HLS_INIT_CACHE = {}
_HLS_UPSTREAM_SESSIONS = {}
# Buffer somente em RAM e por mf_watch. Cada entrada guarda um segmento completo
# já validado; respostas parciais nunca entram no cache. A fila de prefetch usa
# conexão própria para não bloquear uma leitura urgente do Kodi na sessão ativa.
_HLS_BUFFER_LOCK = threading.RLock()
_HLS_SEGMENT_BUFFER = {}
_HLS_PREFETCH_QUEUE = {}
# Estado de liberação da playlist por reprodução. Ele mantém uma fila
# contínua de segmentos já confirmados, diferente de apenas pré-baixar a
# janela atual e repassá-la ao player sem controle de borda.
_HLS_BUFFER_PLAYLIST_STATE = {}

_proxy_instance = None
_owned_port = None


class CloudflareDNSResolver(object):
    """Resolvedor DNS privado por DoH direto aos IPs 1.1.1.1/1.0.0.1.

    Ele só substitui getaddrinfo enquanto uma requisição HTTP deste addon está em
    andamento. Isso evita mudar o DNS do dispositivo ou deixar uma alteração
    permanente no Kodi. Consultas de nomes usam somente HTTPS; se o DoH não
    responder, a requisição falha sem consultar DNS em texto claro.
    """

    SERVERS = ('1.1.1.1', '1.0.0.1')
    CACHE_TTL_MIN = 60
    CACHE_TTL_MAX = 1800
    DOH_TIMEOUT = (3, 6)

    def __init__(self):
        self._native_getaddrinfo = socket.getaddrinfo
        self._cache = {}
        self._cache_lock = threading.RLock()
        self._patch_lock = threading.RLock()
        self._patch_depth = 0
        self._resolving = threading.local()
        self._logged_active = False

    @staticmethod
    def _host_text(host):
        if isinstance(host, bytes):
            try:
                return host.decode('idna')
            except Exception:
                return host.decode('utf-8', 'ignore')
        return str(host or '')

    @staticmethod
    def _is_ip_literal(host):
        try:
            socket.inet_pton(socket.AF_INET, host)
            return True
        except Exception:
            pass
        try:
            socket.inet_pton(socket.AF_INET6, host)
            return True
        except Exception:
            return False

    def _query_doh(self, host):
        """Consulta DNS exclusivamente via HTTPS, sem DNS de texto claro.

        A conexao TLS vai direto aos IPs publicos da Cloudflare e preserva SNI
        cloudflare-dns.com; portanto nao existe bootstrap pelo DNS da operadora.
        """
        request_path = '/dns-query?{}'.format(urlencode({'name': host, 'type': 'A'}))
        request = (
            'GET {} HTTP/1.1\r\n'
            'Host: cloudflare-dns.com\r\n'
            'Accept: application/dns-json\r\n'
            'Accept-Encoding: identity\r\n'
            'User-Agent: {}\r\n'
            'Connection: close\r\n\r\n'
        ).format(request_path, DEFAULT_UA).encode('ascii', 'ignore')
        for server in self.SERVERS:
            raw_sock = None
            tls_sock = None
            try:
                raw_sock = socket.create_connection((server, 443), self.DOH_TIMEOUT[1])
                context = ssl.create_default_context()
                tls_sock = context.wrap_socket(raw_sock, server_hostname='cloudflare-dns.com')
                raw_sock = None
                tls_sock.settimeout(self.DOH_TIMEOUT[1])
                tls_sock.sendall(request)
                response = b''
                while True:
                    block = tls_sock.recv(65536)
                    if not block:
                        break
                    response += block
                    if len(response) > 1024 * 1024:
                        raise ValueError('Resposta DoH grande demais')
                header, sep, body = response.partition(b'\r\n\r\n')
                if not sep or not header.startswith(b'HTTP/'):
                    continue
                try:
                    status = int(header.split(b'\r\n', 1)[0].split()[1])
                except Exception:
                    status = 0
                if status != 200:
                    continue
                payload = json.loads(body.decode('utf-8', 'replace'))
                ips = []
                ttls = []
                for answer in payload.get('Answer') or []:
                    if answer.get('type') == 1 and answer.get('data'):
                        ip = str(answer.get('data'))
                        if self._is_ip_literal(ip):
                            ips.append(ip)
                            ttls.append(answer.get('TTL') or self.CACHE_TTL_MIN)
                if ips:
                    ttl = min(ttls) if ttls else self.CACHE_TTL_MIN
                    return ips, max(self.CACHE_TTL_MIN, min(int(ttl), self.CACHE_TTL_MAX))
            except Exception as exc:
                try:
                    xbmc.log('[FOOTBALL DNS] DoH direto indisponivel em {}: {}'.format(server, str(exc)), xbmc.LOGDEBUG)
                except Exception:
                    pass
            finally:
                for candidate in (tls_sock, raw_sock):
                    try:
                        if candidate:
                            candidate.close()
                    except Exception:
                        pass
        return [], self.CACHE_TTL_MIN

    def resolve(self, host):
        host = self._host_text(host).strip().rstrip('.').lower()
        if not host or self._is_ip_literal(host) or host in ('localhost', 'localhost.localdomain') or host.endswith('.local'):
            return []
        now = time.time()
        with self._cache_lock:
            cached = self._cache.get(host)
            if cached and cached[0] > now:
                return list(cached[1])

        if getattr(self._resolving, 'active', False):
            return []

        self._resolving.active = True
        try:
            addresses, ttl = self._query_doh(host)
            if addresses:
                self._save_cache(host, addresses, ttl)
                return addresses
        finally:
            self._resolving.active = False
        return []

    def _save_cache(self, host, addresses, ttl):
        with self._cache_lock:
            self._cache[host] = (time.time() + ttl, tuple(addresses))

    def _patched_getaddrinfo(self, host, port, family=0, type=0, proto=0, flags=0):
        # Evita recursão enquanto a consulta DoH já está em andamento.
        if getattr(self._resolving, 'active', False):
            return self._native_getaddrinfo(host, port, family, type, proto, flags)
        host_text = self._host_text(host)
        if not host_text or self._is_ip_literal(host_text) or host_text in ('localhost', 'localhost.localdomain') or host_text.endswith('.local'):
            return self._native_getaddrinfo(host, port, family, type, proto, flags)
        # O addon trabalha somente com A/IPv4 neste fluxo. Nunca cai no DNS nativo
        # para um hostname externo: se Cloudflare falhar, a requisicao falha de forma
        # explicita em vez de escapar para o resolvedor padrao da rede.
        if family == socket.AF_INET6:
            raise socket.gaierror(socket.EAI_NONAME, 'Cloudflare DNS: IPv6 nao disponivel neste fluxo')
        addresses = self.resolve(host_text)
        if not addresses:
            raise socket.gaierror(socket.EAI_NONAME, 'Cloudflare DNS nao respondeu para {}'.format(host_text))
        results = []
        for ip in addresses:
            try:
                results.extend(self._native_getaddrinfo(ip, port, family, type, proto, flags))
            except Exception:
                pass
        if not results:
            raise socket.gaierror(socket.EAI_NONAME, 'Cloudflare DNS nao retornou endereco utilizavel para {}'.format(host_text))
        return results

    @contextmanager
    def scoped(self):
        with self._patch_lock:
            if self._patch_depth == 0:
                socket.getaddrinfo = self._patched_getaddrinfo
            self._patch_depth += 1
        try:
            yield
        finally:
            with self._patch_lock:
                self._patch_depth -= 1
                if self._patch_depth <= 0:
                    self._patch_depth = 0
                    socket.getaddrinfo = self._native_getaddrinfo

    def mark_active(self):
        if self._logged_active:
            return
        self._logged_active = True
        try:
            xbmc.log('[FOOTBALL DNS] Cloudflare interno estrito habilitado (sem DNS padrao da rede).', xbmc.LOGINFO)
        except Exception:
            pass


_cloudflare_dns = CloudflareDNSResolver()


def resolve_cloudflare_addresses(host):
    """Return IPv4 addresses from the resolver already used by this addon."""
    return _cloudflare_dns.resolve(host)


@contextmanager
def cloudflare_dns_scope():
    """Limit the socket resolver override to one outbound request."""
    with _cloudflare_dns.scoped():
        yield


def install_cloudflare_dns():
    """Marca o resolvedor como ativo; não troca o DNS do sistema nem grava configurações."""
    _cloudflare_dns.mark_active()
    return True


def _privacy_request_proxies(proxies=None):
    """Desativa proxies públicos/configurados e exige transporte HTTPS direto."""
    return {'http': '', 'https': ''}


def _https_request_url(url):
    """Upgrade public HTTP URLs and reject every remaining non-HTTPS URL."""
    try:
        import secureurl
        upgraded = secureurl.to_https(str(url or ''))
        if urlparse(upgraded).scheme.lower() != 'https':
            raise requests.exceptions.SSLError(
                'Modo de privacidade exige HTTPS; o destino nao oferece uma URL publica HTTPS.'
            )
        return upgraded
    except requests.RequestException:
        raise
    except Exception as exc:
        raise requests.exceptions.SSLError(
            'Nao foi possivel validar uma URL HTTPS: {0}'.format(type(exc).__name__)
        )


def _https_redirect_guard(response, *args, **kwargs):
    """Keep redirects on TLS by upgrading HTTP Location values before follow."""
    try:
        location = response.headers.get('Location', '')
        if response.is_redirect and location:
            target = urljoin(response.url or '', location)
            response.headers['Location'] = _https_request_url(target)
    except requests.RequestException:
        try:
            response.close()
        except Exception:
            pass
        raise
    return response


def _install_https_redirect_guard(kwargs):
    hooks = kwargs.get('hooks') or {}
    response_hooks = hooks.get('response', [])
    if callable(response_hooks):
        response_hooks = [response_hooks]
    else:
        response_hooks = list(response_hooks or [])
    if _https_redirect_guard not in response_hooks:
        response_hooks.append(_https_redirect_guard)
    hooks['response'] = response_hooks
    kwargs['hooks'] = hooks


def cloudflare_request(method, url, **kwargs):
    """Requisição externa HTTPS sem proxies e com DNS Cloudflare interno."""
    url = _https_request_url(url)
    kwargs['proxies'] = _privacy_request_proxies(kwargs.get('proxies'))
    kwargs['verify'] = TLS_VERIFY
    _install_https_redirect_guard(kwargs)
    install_cloudflare_dns()
    import dnscompat
    with dnscompat.cloudflare_scope():
        url = _https_request_url(url)
        response = requests.request(method, url, **kwargs)
    _log_verified_https(response, url)
    return response


def cloudflare_get(url, **kwargs):
    """GET do requests com resolução Cloudflare limitada a esta requisição."""
    return cloudflare_request('GET', url, **kwargs)


def cloudflare_session_get(session, url, **kwargs):
    """GET por sessão efêmera com o mesmo DNS Cloudflare do addon.

    A sessão existe somente durante uma reprodução HLS identificada por
    mf_watch. Isso preserva Set-Cookie e keep-alive emitidos normalmente pela
    origem, sem criar login, burlar desafio ou compartilhar credenciais.
    """
    url = _https_request_url(url)
    kwargs['proxies'] = _privacy_request_proxies(kwargs.get('proxies'))
    kwargs['verify'] = TLS_VERIFY
    _install_https_redirect_guard(kwargs)
    # Impede que variáveis do ambiente alterem a rota sem o usuário saber.
    session.trust_env = False
    install_cloudflare_dns()
    import dnscompat
    with dnscompat.cloudflare_scope():
        response = session.get(_https_request_url(url), **kwargs)
    _log_verified_https(response, url)
    return response


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # HTTPServer herda backlog muito pequeno. Kodi pode abrir health, artwork,
    # playlist e segmentos quase juntos; uma fila maior evita falso timeout de
    # loopback sem criar workers permanentes ou consumir buffer HLS adicional.
    request_queue_size = 64

    def handle_error(self, request, client_address):
        # Kodi/FFmpeg pode encerrar o socket assim que troca de segmento, dá Stop
        # ou conclui um HEAD. Broken pipe/reset/abort do cliente loopback é ciclo
        # normal e não deve despejar traceback no kodi.log.
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        if isinstance(exc, OSError):
            code = getattr(exc, 'winerror', None) or getattr(exc, 'errno', None)
            if code in (32, 54, 103, 104, 10053, 10054):
                return
        return HTTPServer.handle_error(self, request, client_address)


def is_port_in_use(port, host=HOST):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.8)
            return s.connect_ex((host, int(port))) == 0
    except Exception:
        return False


def _valid_port(value):
    try:
        value = int(value)
        return value if 1 <= value <= 65535 else 0
    except Exception:
        return 0


def _current_proxy_port(prefer_owned=True):
    """Retorna somente uma porta efetivamente publicada/possuída pelo addon."""
    if prefer_owned:
        try:
            value = _valid_port(_owned_port)
            if value:
                return value
        except Exception:
            pass
    try:
        value = _valid_port(WINDOW.getProperty(PORT_PROPERTY_NAME))
        if value:
            return value
    except Exception:
        pass
    return 0


def _proxy_base(port=None):
    port = _valid_port(port) or _current_proxy_port()
    if not port:
        return ''
    return 'http://{}:{}/?url='.format(HOST, port)


def _health_check(port, timeout=0.8):
    """Confirma que uma porta em loopback é realmente deste addon.

    Não basta uma porta estar aberta: outro addon/processo pode ser o listener.
    """
    port = _valid_port(port)
    if not port:
        return False
    sock = None
    try:
        sock = socket.create_connection((HOST, port), timeout)
        request = ('HEAD {} HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n\r\n'
                   .format(HEALTH_PATH, HOST, port)).encode('ascii')
        sock.sendall(request)
        data = b''
        while len(data) < 4096:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk
            if b'\r\n\r\n' in data:
                break
        return (b' 200 ' in data.split(b'\r\n', 1)[0] and
                ('X-football-Proxy: {}'.format(HEALTH_TOKEN)).encode('ascii') in data)
    except Exception:
        return False
    finally:
        try:
            if sock:
                sock.close()
        except Exception:
            pass


def _stable_published_health(port, attempts=3):
    """Confirma uma publicação compartilhada sem reagir a um único timeout.

    Invocações curtas do plugin não possuem a thread do service e precisam usar
    /health. Um único falso-negativo, porém, não pode substituir o listener no
    meio de uma live. Só declaramos a publicação obsoleta após tentativas HEAD
    consecutivas e curtas.
    """
    port = _valid_port(port)
    if not port:
        return False
    attempts = max(1, int(attempts or 1))
    for index in range(attempts):
        # A primeira verificação é rápida; as seguintes dão uma pequena janela
        # para o scheduler/Android acordar a thread do servidor sob carga.
        timeout = 0.45 if index == 0 else 0.65
        if _health_check(port, timeout=timeout):
            return True
        if index + 1 < attempts:
            time.sleep(0.06 * (index + 1))
    return False


def _mark_proxy_running(port, owner=''):
    port = _valid_port(port)
    if not port:
        return False
    try:
        WINDOW.setProperty(PROPERTY_NAME, 'true')
        WINDOW.setProperty(PORT_PROPERTY_NAME, str(port))
        WINDOW.setProperty(OWNER_PROPERTY_NAME, str(owner or 'shared'))
        return True
    except Exception:
        return False


def _clear_proxy_properties(expected_port=None):
    """Limpa publicação apenas se ela ainda pertencer à instância esperada.

    Isso evita que um processo antigo apague a porta publicada por um service
    que assumiu o proxy durante uma corrida de inicialização.
    """
    try:
        if expected_port is not None:
            expected_port = _valid_port(expected_port)
            published = _valid_port(WINDOW.getProperty(PORT_PROPERTY_NAME))
            if expected_port and published and expected_port != published:
                return False
        WINDOW.clearProperty(PROPERTY_NAME)
        WINDOW.clearProperty(PORT_PROPERTY_NAME)
        WINDOW.clearProperty(OWNER_PROPERTY_NAME)
        return True
    except Exception:
        return False


def _published_owner():
    try:
        return str(WINDOW.getProperty(OWNER_PROPERTY_NAME) or '').strip().lower()
    except Exception:
        return ''


def _is_own_proxy_url(raw_url):
    """Valida loopback contra a porta dinâmica publicada ou possuída localmente."""
    try:
        parsed = urlparse(raw_url)
        if parsed.scheme != 'http' or parsed.hostname != HOST:
            return False
        port = _valid_port(parsed.port)
        if not port:
            return False
        allowed = set()
        published = _current_proxy_port(prefer_owned=False)
        owned = _valid_port(_owned_port)
        if published:
            allowed.add(published)
        if owned:
            allowed.add(owned)
        return port in allowed
    except Exception:
        return False



def _normalize_playback_watch(value):
    try:
        watch_id = str(value or '').strip()
        if PLAYBACK_WATCH_RE.match(watch_id):
            return watch_id
    except Exception:
        pass
    return ''


def _playback_failure_key(watch_id):
    return PLAYBACK_FAILURE_PREFIX + watch_id


def clear_playback_failure(watch_id):
    watch_id = _normalize_playback_watch(watch_id)
    if not watch_id:
        return
    try:
        WINDOW.clearProperty(_playback_failure_key(watch_id))
    except Exception:
        pass


def get_playback_failure(watch_id):
    """Lê falha de origem vinculada à tentativa corrente, com TTL curto."""
    watch_id = _normalize_playback_watch(watch_id)
    if not watch_id:
        return None
    try:
        raw = WINDOW.getProperty(_playback_failure_key(watch_id))
        if not raw:
            return None
        state = json.loads(raw)
        when = float(state.get('time', 0) or 0)
        if not when or (time.time() - when) > PLAYBACK_FAILURE_TTL:
            clear_playback_failure(watch_id)
            return None
        return state if isinstance(state, dict) else None
    except Exception:
        clear_playback_failure(watch_id)
        return None


def _classify_upstream_failure(exc):
    """Converte exceções de rede em texto seguro e útil para o usuário."""
    status = None
    try:
        response = getattr(exc, 'response', None)
        status = int(getattr(response, 'status_code', 0) or 0)
    except Exception:
        status = None

    if status:
        labels = {
            401: 'HTTP 401 — servidor exige nova autorização',
            403: 'HTTP 403 — servidor recusou o acesso',
            404: 'HTTP 404 — conteúdo não encontrado no servidor',
            408: 'HTTP 408 — servidor demorou para responder',
            410: 'HTTP 410 — conteúdo removido do servidor',
            429: 'HTTP 429 — servidor temporariamente sobrecarregado',
            500: 'HTTP 500 — servidor de origem indisponível',
            501: 'HTTP 501 — servidor não suporta esta solicitação',
            502: 'HTTP 502 — falha no servidor de origem',
            503: 'HTTP 503 — servidor indisponível',
            504: 'HTTP 504 — tempo de resposta do servidor esgotado'
        }
        if status in labels:
            message = labels[status]
        elif status >= 500:
            message = 'HTTP {0} — servidor de origem indisponível'.format(status)
        else:
            message = 'HTTP {0} — resposta inválida do servidor'.format(status)
        return {
            'message': message,
            'status': status,
            'immediate': status in (401, 403, 404, 410, 429)
        }

    if isinstance(exc, (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.Timeout)):
        return {'message': 'tempo de resposta do servidor esgotado', 'status': 0, 'immediate': False}
    if isinstance(exc, requests.exceptions.SSLError):
        return {'message': 'falha de conexão segura com o servidor', 'status': 0, 'immediate': False}
    if isinstance(exc, (requests.exceptions.ConnectionError, socket.gaierror, OSError)):
        detail = str(exc or '').lower()
        if 'dns' in detail or 'name or service' in detail or 'getaddrinfo' in detail:
            message = 'não foi possível localizar o servidor de origem'
        else:
            message = 'servidor de origem não respondeu'
        return {'message': message, 'status': 0, 'immediate': False}
    return {'message': 'falha de comunicação com o servidor de origem', 'status': 0, 'immediate': False}


class HLSReadError(IOError):
    """Falha recuperável durante a leitura de uma playlist ou segmento HLS."""
    pass


def _is_hls_playlist_url(url):
    try:
        clean = str(url or '').split('?', 1)[0].lower()
        return clean.endswith(HLS_PLAYLIST_SUFFIXES)
    except Exception:
        return False


def _response_status_from_exception(exc):
    try:
        response = getattr(exc, 'response', None)
        return int(getattr(response, 'status_code', 0) or 0)
    except Exception:
        return 0


def _is_retryable_hls_failure(exc):
    status = _response_status_from_exception(exc)
    if status in (401, 403, 404, 410):
        return False
    # 429 pode recuperar, mas não fazemos loop longo: no máximo as tentativas
    # controladas abaixo, com atraso curto.
    if status == 429 or status >= 500:
        return True
    if status:
        return False
    return isinstance(exc, (
        HLSReadError,
        requests.exceptions.RequestException,
        socket.gaierror,
        OSError,
        IOError
    ))


def _close_upstream_response(response):
    try:
        if response is not None:
            response.close()
    except Exception:
        pass


def _hls_clean_path(url):
    try:
        return (urlparse(str(url or '')).path or '').lower()
    except Exception:
        return str(url or '').split('?', 1)[0].lower()


def _is_hls_media_segment(url):
    path = _hls_clean_path(url)
    if _is_hls_playlist_url(url):
        return False
    return path.endswith(('.ts', '.m4s', '.m4v', '.cmfv', '.mp4'))


def _is_hls_init_object(url):
    path = _hls_clean_path(url).rsplit('/', 1)[-1]
    return path.startswith('init.') or path.startswith('init_') or path.startswith('init-')


def _is_hls_jump_candidate(url):
    return _is_hls_media_segment(url) and not _is_hls_init_object(url)


def _hls_context_copy_options(options):
    copied = {}
    try:
        for key in ('User-Agent', 'Referer', 'Origin'):
            value = _opt(options or {}, key, '')
            if value:
                copied[key] = [value]
    except Exception:
        pass
    return copied


def _trim_hls_memory(now=None):
    now = float(now or time.time())
    sessions_to_close = []
    with _HLS_CONTEXT_LOCK:
        for watch_id, item in list(_HLS_PLAYLIST_CONTEXT.items()):
            if (now - float(item.get('time', 0) or 0)) > HLS_CONTEXT_TTL:
                _HLS_PLAYLIST_CONTEXT.pop(watch_id, None)
        for cache_key, item in list(_HLS_INIT_CACHE.items()):
            if (now - float(item.get('time', 0) or 0)) > HLS_INIT_CACHE_TTL:
                _HLS_INIT_CACHE.pop(cache_key, None)
        for watch_id, item in list(_HLS_UPSTREAM_SESSIONS.items()):
            if (now - float(item.get('time', 0) or 0)) > HLS_SESSION_TTL:
                removed = _HLS_UPSTREAM_SESSIONS.pop(watch_id, None)
                if removed:
                    sessions_to_close.append(removed.get('session'))
        if len(_HLS_PLAYLIST_CONTEXT) > HLS_CONTEXT_LIMIT:
            ordered = sorted(_HLS_PLAYLIST_CONTEXT.items(), key=lambda kv: float(kv[1].get('time', 0) or 0))
            for key, _value in ordered[:max(1, len(_HLS_PLAYLIST_CONTEXT) - HLS_CONTEXT_LIMIT)]:
                _HLS_PLAYLIST_CONTEXT.pop(key, None)
        if len(_HLS_INIT_CACHE) > HLS_INIT_CACHE_LIMIT:
            ordered = sorted(_HLS_INIT_CACHE.items(), key=lambda kv: float(kv[1].get('time', 0) or 0))
            for key, _value in ordered[:max(1, len(_HLS_INIT_CACHE) - HLS_INIT_CACHE_LIMIT)]:
                _HLS_INIT_CACHE.pop(key, None)
        if len(_HLS_UPSTREAM_SESSIONS) > HLS_SESSION_LIMIT:
            ordered = sorted(_HLS_UPSTREAM_SESSIONS.items(), key=lambda kv: float(kv[1].get('time', 0) or 0))
            for key, _value in ordered[:max(1, len(_HLS_UPSTREAM_SESSIONS) - HLS_SESSION_LIMIT)]:
                removed = _HLS_UPSTREAM_SESSIONS.pop(key, None)
                if removed:
                    sessions_to_close.append(removed.get('session'))
    for session in sessions_to_close:
        try:
            if session:
                session.close()
        except Exception:
            pass


def _get_hls_session_context(watch_id):
    """Obtém sessão upstream exclusiva desta reprodução HLS."""
    watch_id = _normalize_playback_watch(watch_id)
    if not watch_id:
        return None
    now = time.time()
    _trim_hls_memory(now)
    with _HLS_CONTEXT_LOCK:
        item = _HLS_UPSTREAM_SESSIONS.get(watch_id)
        if item is None:
            item = {
                'session': requests.Session(),
                'lock': threading.RLock(),
                'time': now,
            }
            _HLS_UPSTREAM_SESSIONS[watch_id] = item
        else:
            item['time'] = now
        return item


def _remember_hls_playlist_context(watch_id, playlist_url, options):
    watch_id = _normalize_playback_watch(watch_id)
    if not watch_id or not playlist_url:
        return
    try:
        with _HLS_CONTEXT_LOCK:
            _HLS_PLAYLIST_CONTEXT[watch_id] = {
                'url': str(playlist_url),
                'options': _hls_context_copy_options(options),
                'time': time.time()
            }
        _trim_hls_memory()
    except Exception:
        pass


def _get_hls_playlist_context(watch_id):
    watch_id = _normalize_playback_watch(watch_id)
    if not watch_id:
        return None
    _trim_hls_memory()
    try:
        with _HLS_CONTEXT_LOCK:
            item = _HLS_PLAYLIST_CONTEXT.get(watch_id)
            return dict(item) if item else None
    except Exception:
        return None


def _hls_init_cache_get(url):
    if not _is_hls_init_object(url):
        return None
    _trim_hls_memory()
    try:
        with _HLS_CONTEXT_LOCK:
            item = _HLS_INIT_CACHE.get(str(url))
            return dict(item) if item else None
    except Exception:
        return None


def _hls_init_cache_set(url, result):
    if not _is_hls_init_object(url) or not result:
        return
    try:
        item = dict(result)
        item['time'] = time.time()
        with _HLS_CONTEXT_LOCK:
            _HLS_INIT_CACHE[str(url)] = item
        _trim_hls_memory()
    except Exception:
        pass



def _hls_buffer_watch_id(watch_id):
    return _normalize_playback_watch(watch_id)


def _hls_buffer_entry_key(url):
    try:
        return str(url or '')
    except Exception:
        return ''


def _hls_buffer_total_bytes_locked():
    total = 0
    for entries in _HLS_SEGMENT_BUFFER.values():
        for entry in entries.values():
            try:
                total += int(entry.get('size', 0) or 0)
            except Exception:
                pass
    return total


def _trim_hls_segment_buffer(now=None):
    """Limita cache HLS por sessão e globalmente, sempre em memória."""
    now = float(now or time.time())
    with _HLS_BUFFER_LOCK:
        for watch_id, entries in list(_HLS_SEGMENT_BUFFER.items()):
            for key, entry in list(entries.items()):
                age = now - float(entry.get('time', 0) or 0)
                if age > HLS_BUFFER_TTL:
                    entries.pop(key, None)
            if not entries:
                _HLS_SEGMENT_BUFFER.pop(watch_id, None)
                continue
            ordered = sorted(entries.items(), key=lambda item: float(item[1].get('last_access', 0) or 0))
            while len(entries) > HLS_BUFFER_MAX_SEGMENTS_PER_WATCH and ordered:
                key, _entry = ordered.pop(0)
                entries.pop(key, None)
            watch_bytes = sum(int(item.get('size', 0) or 0) for item in entries.values())
            if watch_bytes > HLS_BUFFER_MAX_BYTES_PER_WATCH:
                ordered = sorted(entries.items(), key=lambda item: float(item[1].get('last_access', 0) or 0))
                while watch_bytes > HLS_BUFFER_MAX_BYTES_PER_WATCH and ordered:
                    key, entry = ordered.pop(0)
                    watch_bytes -= int(entry.get('size', 0) or 0)
                    entries.pop(key, None)

        total = _hls_buffer_total_bytes_locked()
        if total > HLS_BUFFER_MAX_BYTES_GLOBAL:
            all_entries = []
            for watch_id, entries in _HLS_SEGMENT_BUFFER.items():
                for key, entry in entries.items():
                    all_entries.append((float(entry.get('last_access', 0) or 0), watch_id, key, entry))
            all_entries.sort(key=lambda item: item[0])
            for _stamp, watch_id, key, entry in all_entries:
                if total <= HLS_BUFFER_MAX_BYTES_GLOBAL:
                    break
                try:
                    total -= int(entry.get('size', 0) or 0)
                except Exception:
                    pass
                entries = _HLS_SEGMENT_BUFFER.get(watch_id, {})
                entries.pop(key, None)
                if not entries:
                    _HLS_SEGMENT_BUFFER.pop(watch_id, None)

        for watch_id, state in list(_HLS_PREFETCH_QUEUE.items()):
            if not state.get('running') and (now - float(state.get('time', 0) or 0)) > HLS_BUFFER_CONTEXT_TTL:
                _HLS_PREFETCH_QUEUE.pop(watch_id, None)
        for watch_id, state in list(_HLS_BUFFER_PLAYLIST_STATE.items()):
            if (now - float(state.get('time', 0) or 0)) > HLS_BUFFER_CONTEXT_TTL:
                _HLS_BUFFER_PLAYLIST_STATE.pop(watch_id, None)


def _hls_buffer_get(watch_id, url):
    if not HLS_BUFFER_ENABLED:
        return None
    watch_id = _hls_buffer_watch_id(watch_id)
    key = _hls_buffer_entry_key(url)
    if not watch_id or not key:
        return None
    _trim_hls_segment_buffer()
    with _HLS_BUFFER_LOCK:
        entry = _HLS_SEGMENT_BUFFER.get(watch_id, {}).get(key)
        if not entry:
            return None
        entry['last_access'] = time.time()
        copied = dict(entry)
        copied['headers'] = dict(entry.get('headers') or {})
        return copied


def _hls_buffer_store(watch_id, url, result):
    """Armazena apenas segmentos completos (HTTP 200) e validados."""
    if not HLS_BUFFER_ENABLED or not result:
        return
    watch_id = _hls_buffer_watch_id(watch_id)
    key = _hls_buffer_entry_key(url)
    body = result.get('body') if isinstance(result, dict) else None
    status = int(result.get('status', 0) or 0) if isinstance(result, dict) else 0
    if not watch_id or not key or status != 200 or not body:
        return
    if len(body) > HLS_BUFFER_OBJECT_MAX_BYTES:
        return
    if not _looks_like_valid_hls_media(body, url):
        return
    headers = dict(result.get('headers') or {})
    # Content-Length será sempre recalculado ao responder do buffer.
    headers.pop('Content-Length', None)
    headers.pop('Content-Range', None)
    entry = {
        'body': body,
        'headers': headers,
        'status': 200,
        'size': len(body),
        'time': time.time(),
        'last_access': time.time(),
        'url': result.get('url') or key,
    }
    with _HLS_BUFFER_LOCK:
        _HLS_SEGMENT_BUFFER.setdefault(watch_id, {})[key] = entry
    _trim_hls_segment_buffer()


def _hls_if_range_matches(if_range, headers):
    if not if_range:
        return True
    if_range = str(if_range).strip()
    if not if_range:
        return True
    etag = str((headers or {}).get('ETag', '') or '').strip()
    last_modified = str((headers or {}).get('Last-Modified', '') or '').strip()
    return bool(if_range and (if_range == etag or if_range == last_modified))


def _hls_parse_single_range(value, total):
    """Aceita um único Range HTTP bytes=... e retorna (inicio, fim)."""
    try:
        raw = str(value or '').strip().lower()
        if not raw.startswith('bytes=') or ',' in raw:
            return None
        spec = raw[6:].strip()
        start_text, end_text = spec.split('-', 1)
        if not start_text:
            suffix = int(end_text)
            if suffix <= 0:
                return None
            start = max(0, int(total) - suffix)
            end = int(total) - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else int(total) - 1
        if start < 0 or end < start or start >= int(total):
            return None
        return start, min(end, int(total) - 1)
    except Exception:
        return None


def _hls_buffer_response(watch_id, url, request_headers):
    """Monta 200/206 local a partir de um segmento completo em RAM."""
    entry = _hls_buffer_get(watch_id, url)
    if not entry:
        return None
    body = entry.get('body') or b''
    if not body:
        return None
    headers = dict(entry.get('headers') or {})
    total = len(body)
    range_header = (request_headers or {}).get('Range', '')
    if range_header and _hls_if_range_matches((request_headers or {}).get('If-Range', ''), headers):
        selected = _hls_parse_single_range(range_header, total)
        if selected is None:
            headers['Content-Range'] = 'bytes */{}'.format(total)
            headers['Accept-Ranges'] = 'bytes'
            return {'body': b'', 'status': 416, 'headers': headers, 'url': entry.get('url') or url}
        start, end = selected
        headers['Content-Range'] = 'bytes {}-{}/{}'.format(start, end, total)
        headers['Accept-Ranges'] = 'bytes'
        return {'body': body[start:end + 1], 'status': 206, 'headers': headers, 'url': entry.get('url') or url}
    headers['Accept-Ranges'] = headers.get('Accept-Ranges') or 'bytes'
    return {'body': body, 'status': 200, 'headers': headers, 'url': entry.get('url') or url}


def _hls_playlist_segment_urls(content, base_url):
    """Extrai segmentos de uma media playlist; ignora master playlists e chaves."""
    urls = []
    seen = set()
    has_extinf = False
    pending_media = False
    for raw_line in str(content or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('#'):
            if line.upper().startswith('#EXTINF:'):
                has_extinf = True
                pending_media = True
            continue
        absolute = urljoin(base_url, line)
        if _is_hls_playlist_url(absolute):
            pending_media = False
            continue
        if pending_media or _is_hls_media_segment(absolute):
            pending_media = False
            if absolute not in seen and _is_hls_media_segment(absolute) and not _is_hls_init_object(absolute):
                seen.add(absolute)
                urls.append(absolute)
    return urls if has_extinf else []


def _hls_prefetch_headers(headers):
    clean = dict(headers or {})
    clean.pop('Range', None)
    clean.pop('If-Range', None)
    clean.pop('Cache-Control', None)
    clean.pop('Pragma', None)
    return clean


def _hls_prefetch_fetch(url, headers, proxies=None):
    last_error = None
    for attempt in range(max(1, int(HLS_BUFFER_PREFETCH_ATTEMPTS or 1))):
        try:
            result = _hls_fetch_once(
                url, headers, proxies=proxies, expect_playlist=False,
                is_segment=True, attempt=attempt,
                timeout_override=HLS_BUFFER_PREFETCH_TIMEOUT,
                session_context=None
            )
            if int(result.get('status', 0) or 0) == 200:
                return result
            return None
        except Exception as exc:
            last_error = exc
            if not _is_retryable_hls_failure(exc) or attempt + 1 >= int(HLS_BUFFER_PREFETCH_ATTEMPTS or 1):
                break
            time.sleep(HLS_RETRY_BACKOFF[min(attempt, len(HLS_RETRY_BACKOFF) - 1)])
    return None


def _hls_prefetch_worker(watch_id):
    while True:
        with _HLS_BUFFER_LOCK:
            state = _HLS_PREFETCH_QUEUE.get(watch_id)
            if not state:
                return
            state['time'] = time.time()
            pending = state.get('pending') or []
            if not pending:
                state['running'] = False
                return
            item = pending.pop(0)
        url = item.get('url')
        if not url or _hls_buffer_get(watch_id, url):
            continue
        result = _hls_prefetch_fetch(url, item.get('headers') or {}, proxies=item.get('proxies'))
        if result:
            _hls_buffer_store(watch_id, url, result)


def _schedule_hls_prefetch(watch_id, playlist_content, base_url, headers, proxies=None):
    """Agenda pré-carregamento de segmentos entregues ao Kodi, sem bloqueá-lo."""
    if not HLS_BUFFER_ENABLED:
        return
    watch_id = _hls_buffer_watch_id(watch_id)
    if not watch_id:
        return
    candidates = _hls_playlist_segment_urls(playlist_content, base_url)
    if not candidates:
        return
    # Prioriza a borda que o player alcançará primeiro após iniciar na playlist
    # atrasada. O máximo de quatro objetos mantém o uso de RAM previsível.
    candidates = candidates[-max(1, int(HLS_BUFFER_PREFETCH_SEGMENTS or 1)):]
    clean_headers = _hls_prefetch_headers(headers)
    with _HLS_BUFFER_LOCK:
        state = _HLS_PREFETCH_QUEUE.get(watch_id)
        if state is None:
            state = {'pending': [], 'running': False, 'time': time.time()}
            _HLS_PREFETCH_QUEUE[watch_id] = state
        queued = set(item.get('url') for item in state.get('pending') or [])
        for url in candidates:
            if url in queued or _hls_buffer_get(watch_id, url):
                continue
            state['pending'].append({'url': url, 'headers': clean_headers, 'proxies': proxies})
            queued.add(url)
        state['time'] = time.time()
        if state.get('pending') and not state.get('running'):
            state['running'] = True
            worker = threading.Thread(target=_hls_prefetch_worker, args=(watch_id,))
            worker.daemon = True
            worker.start()



def _report_hls_buffer_ready(watch_id, ready, target):
    """Registra estado resumido uma vez por mudança, sem URL ou headers."""
    now = time.time()
    should_log = False
    with _HLS_BUFFER_LOCK:
        state = _HLS_PREFETCH_QUEUE.get(watch_id)
        if state is not None:
            last_ready = int(state.get('last_report_ready', -1) or -1)
            last_time = float(state.get('last_report_time', 0) or 0)
            if ready != last_ready or (now - last_time) >= 45.0:
                state['last_report_ready'] = int(ready)
                state['last_report_time'] = now
                should_log = True
    if should_log:
        try:
            xbmc.log('[FOOTBALL PROXY] Buffer HLS preparado: {}/{} segmentos completos em memória.'.format(int(ready), int(target)), xbmc.LOGINFO)
        except Exception:
            pass


def _prime_hls_buffer(watch_id, playlist_content, base_url, headers, proxies=None):
    """Pré-carrega a primeira fila; depois apenas agenda trabalho em segundo plano."""
    if not HLS_BUFFER_ENABLED:
        return 0
    watch_id = _hls_buffer_watch_id(watch_id)
    if not watch_id:
        return 0
    candidates = _hls_playlist_segment_urls(playlist_content, base_url)
    if not candidates:
        return 0
    candidates = candidates[-max(1, int(HLS_BUFFER_PREFETCH_SEGMENTS or 1)):]
    _schedule_hls_prefetch(watch_id, playlist_content, base_url, headers, proxies=proxies)
    state = _hls_buffer_playlist_state(watch_id, create=True)
    startup_needed = True
    with _HLS_BUFFER_LOCK:
        if state.get('startup_attempted'):
            startup_needed = False
        else:
            state['startup_attempted'] = True
            state['time'] = time.time()
    if not startup_needed:
        ready = sum(1 for url in candidates if _hls_buffer_get(watch_id, url))
        return ready

    target = min(len(candidates), max(1, int(HLS_BUFFER_STARTUP_SEGMENTS or 1)))
    deadline = time.monotonic() + max(0.0, float(HLS_BUFFER_STARTUP_WAIT or 0.0))
    ready = 0
    while True:
        ready = sum(1 for url in candidates if _hls_buffer_get(watch_id, url))
        if ready >= target or time.monotonic() >= deadline:
            _report_hls_buffer_ready(watch_id, ready, target)
            return ready
        time.sleep(0.04)



def _hls_buffer_playlist_state(watch_id, create=False):
    """Obtém estado de playlist local por reprodução, sempre em memória."""
    watch_id = _hls_buffer_watch_id(watch_id)
    if not watch_id:
        return None
    with _HLS_BUFFER_LOCK:
        state = _HLS_BUFFER_PLAYLIST_STATE.get(watch_id)
        if state is None and create:
            state = {'time': time.time(), 'startup_attempted': False}
            _HLS_BUFFER_PLAYLIST_STATE[watch_id] = state
        if state is not None:
            state['time'] = time.time()
        return state


def _hls_buffer_note_source(watch_id, content, base_url):
    """Guarda a última janela HLS válida para sobreviver a uma falha curta da playlist."""
    if not watch_id or not content or not base_url:
        return
    state = _hls_buffer_playlist_state(watch_id, create=True)
    if state is None:
        return
    with _HLS_BUFFER_LOCK:
        state['source_content'] = str(content)
        state['source_base_url'] = str(base_url)
        state['time'] = time.time()


def _hls_media_sequence(lines):
    for raw in lines:
        value = raw.strip()
        if value.upper().startswith('#EXT-X-MEDIA-SEQUENCE:'):
            try:
                return int(value.split(':', 1)[1].strip())
            except Exception:
                return None
    return None


def _hls_replace_media_sequence(lines, sequence):
    if sequence is None:
        return list(lines)
    out = []
    changed = False
    for raw in lines:
        if raw.strip().upper().startswith('#EXT-X-MEDIA-SEQUENCE:'):
            out.append('#EXT-X-MEDIA-SEQUENCE:{}'.format(int(sequence)))
            changed = True
        else:
            out.append(raw)
    if not changed:
        insert_at = 1 if out and out[0].strip().upper() == '#EXTM3U' else 0
        out.insert(insert_at, '#EXT-X-MEDIA-SEQUENCE:{}'.format(int(sequence)))
    return out


def _hls_parse_media_entries(content, base_url):
    """Extrai blocos completos de segmentos de uma media playlist HLS.

    Preserva #EXTINF, #EXT-X-PROGRAM-DATE-TIME, #EXT-X-BYTERANGE e outras
    diretivas que antecedem cada URI. O formato é deliberadamente conservador:
    quando não houver #EXTINF ou ENDLIST não é alterado.
    """
    try:
        lines = str(content or '').splitlines()
        if not lines or any(line.strip().upper() == '#EXT-X-ENDLIST' for line in lines):
            return None
        uri_indexes = []
        pending_extinf = False
        for index, raw in enumerate(lines):
            value = raw.strip()
            if not value:
                continue
            if value.upper().startswith('#EXTINF:'):
                pending_extinf = True
                continue
            if value.startswith('#'):
                continue
            absolute = urljoin(base_url, value)
            if pending_extinf or _is_hls_media_segment(absolute):
                pending_extinf = False
                if _is_hls_media_segment(absolute) and not _is_hls_init_object(absolute):
                    uri_indexes.append(index)
        if not uri_indexes:
            return None

        # O primeiro bloco começa no primeiro marcador que pertence à mídia,
        # sem absorver #EXTM3U, TARGETDURATION, MEDIA-SEQUENCE ou EXT-X-MAP.
        first_uri = uri_indexes[0]
        first_start = first_uri
        for index in range(first_uri - 1, -1, -1):
            value = lines[index].strip().upper()
            if value.startswith(('#EXTINF:', '#EXT-X-PROGRAM-DATE-TIME:', '#EXT-X-BYTERANGE:',
                                 '#EXT-X-DISCONTINUITY', '#EXT-X-GAP', '#EXT-X-DATERANGE:')):
                first_start = index
                continue
            if not value:
                first_start = index
                continue
            break

        header = list(lines[:first_start])
        entries = []
        previous_uri = None
        for position, uri_index in enumerate(uri_indexes):
            start = first_start if position == 0 else previous_uri + 1
            block = list(lines[start:uri_index + 1])
            uri = urljoin(base_url, lines[uri_index].strip())
            entries.append({'url': uri, 'block': block})
            previous_uri = uri_index
        return {
            'header': header,
            'entries': entries,
            'media_sequence': _hls_media_sequence(lines),
        }
    except Exception:
        return None


def _hls_render_buffered_playlist(parsed, start_index, end_index):
    """Renderiza uma janela local e ajusta MEDIA-SEQUENCE para o primeiro URI."""
    try:
        entries = parsed.get('entries') or []
        if not entries or start_index < 0 or end_index < start_index or end_index >= len(entries):
            return ''
        header = list(parsed.get('header') or [])
        media_sequence = parsed.get('media_sequence')
        if media_sequence is not None:
            header = _hls_replace_media_sequence(header, int(media_sequence) + int(start_index))
        out = list(header)
        for entry in entries[start_index:end_index + 1]:
            out.extend(entry.get('block') or [])
        return '\n'.join(out) + '\n'
    except Exception:
        return ''


def _hls_buffered_live_playlist(watch_id, content, base_url):
    """Cria a playlist que o Kodi recebe, usando apenas segmentos confirmados.

    A primeira janela fica três segmentos atrás quando há reserva suficiente.
    Em cada nova leitura de playlist, libera no máximo um segmento. Assim, se
    a origem parar de atualizar por alguns ciclos, a reserva pré-baixada segue
    chegando ao Kodi em vez de o demuxer receber EOF imediatamente.
    """
    parsed = _hls_parse_media_entries(content, base_url)
    if not parsed:
        return '', None
    entries = parsed.get('entries') or []
    if not entries:
        return '', None

    cached = []
    for entry in entries:
        cached.append(bool(_hls_buffer_get(watch_id, entry.get('url'))))

    # Localiza a corrida contígua mais recente de segmentos completos em RAM.
    end = len(entries) - 1
    while end >= 0 and not cached[end]:
        end -= 1
    if end < 0:
        return '', None
    start = end
    while start >= 0 and cached[start]:
        start -= 1
    start += 1
    available = end - start + 1
    minimum = max(1, int(HLS_BUFFER_RELEASE_MIN_SEGMENTS or 1))
    if available < minimum:
        return '', None

    state = _hls_buffer_playlist_state(watch_id, create=True)
    previous_url = ''
    if state is not None:
        with _HLS_BUFFER_LOCK:
            previous_url = str(state.get('released_tail_url', '') or '')

    previous_index = -1
    if previous_url:
        for index, entry in enumerate(entries):
            if entry.get('url') == previous_url:
                previous_index = index
                break

    visible = max(minimum, int(HLS_BUFFER_RELEASE_WINDOW or minimum))
    reserve = max(0, int(HLS_BUFFER_RELEASE_RESERVE or 0))
    min_tail = start + minimum - 1
    if previous_index >= start:
        # Uma atualização da playlist libera só o próximo segmento confirmado.
        # Isso conserva a fila caso a origem congele logo após responder.
        tail = min(end, max(min_tail, previous_index + 1))
    else:
        # Primeira entrega: mantém a reserva completa quando a corrida permite.
        desired = end - reserve
        tail = desired if desired >= min_tail else end
        tail = max(min_tail, min(tail, end))

    window_start = max(start, tail - visible + 1)
    if tail - window_start + 1 < minimum:
        return '', None
    rendered = _hls_render_buffered_playlist(parsed, window_start, tail)
    if not rendered:
        return '', None

    if state is not None:
        with _HLS_BUFFER_LOCK:
            state['released_tail_url'] = entries[tail].get('url') or ''
            state['time'] = time.time()
    return rendered, {
        'visible': tail - window_start + 1,
        'reserve': max(0, end - tail),
        'available': available,
    }


def _hls_stale_buffered_playlist(watch_id):
    """Usa a última playlist válida se a atualização upstream falhar brevemente."""
    state = _hls_buffer_playlist_state(watch_id, create=False)
    if not state:
        return '', None, ''
    with _HLS_BUFFER_LOCK:
        content = state.get('source_content') or ''
        base_url = state.get('source_base_url') or ''
    if not content or not base_url:
        return '', None, ''
    rendered, details = _hls_buffered_live_playlist(watch_id, content, base_url)
    return rendered, details, base_url


def _log_hls_buffer_release(watch_id, details, stale=False):
    if not details:
        return
    state = _hls_buffer_playlist_state(watch_id, create=True)
    if state is None:
        return
    signature = '{}:{}:{}:{}'.format(
        int(details.get('visible', 0) or 0),
        int(details.get('reserve', 0) or 0),
        int(details.get('available', 0) or 0),
        'stale' if stale else 'live'
    )
    should_log = False
    with _HLS_BUFFER_LOCK:
        if state.get('last_release_signature') != signature:
            state['last_release_signature'] = signature
            state['time'] = time.time()
            should_log = True
    if should_log:
        try:
            label = 'em reserva local' if stale else 'confirmados'
            xbmc.log('[FOOTBALL PROXY] Fila HLS: {} visíveis, {} de reserva, {} segmentos {}.'.format(
                int(details.get('visible', 0) or 0),
                int(details.get('reserve', 0) or 0),
                int(details.get('available', 0) or 0),
                label
            ), xbmc.LOGINFO)
        except Exception:
            pass


def _hls_request_headers(headers, attempt=0, is_segment=False):
    request_headers = dict(headers or {})
    # Mídia fMP4 não precisa de compressão HTTP; manter identity evita qualquer
    # ambiguidade de tamanho/corpo no proxy, sem mudar o User-Agent da sessão.
    request_headers['Accept-Encoding'] = 'identity'
    # Não força Connection: close no upstream. A sessão por reprodução pode
    # reutilizar transporte e cookies válidos como um cliente HTTP normal.
    request_headers.pop('Connection', None)
    request_headers.setdefault('User-Agent', DEFAULT_UA)
    if is_segment:
        request_headers.setdefault('Accept', '*/*')
        # Segmentos timestampados são imutáveis no CDN. Forçar no-cache/no-store
        # para cada .m4s cria misses desnecessários e piora uma origem oscilante.
        request_headers.pop('Cache-Control', None)
        request_headers.pop('Pragma', None)
    else:
        request_headers.setdefault('Accept', 'application/vnd.apple.mpegurl, application/x-mpegURL, */*')
        # Manifesto live deve ser atual; somente ele recebe revalidação curta.
        request_headers['Cache-Control'] = 'no-cache'
        request_headers['Pragma'] = 'no-cache'
    # Nunca altera uma seleção explícita de bytes feita pelo player. Em HLS
    # fMP4, Range + If-Range pode ser uma sonda de cache/retomada (inclusive
    # um único byte no fim do segmento). Remover esses cabeçalhos no retry e
    # devolver o arquivo inteiro muda a semântica da requisição e pode fazer
    # o cliente concluir que a continuidade falhou. Se a ETag mudou, o próprio
    # servidor decide corretamente entre 206 e 200 conforme o If-Range.
    return {key: value for key, value in request_headers.items() if value}


def _hls_timeout_for(url, is_segment=False, override=None):
    if override:
        return override
    if is_segment:
        return HLS_SEGMENT_TIMEOUT
    return HLS_PLAYLIST_TIMEOUT


def _looks_like_valid_hls_media(body, url):
    """Recusa fragmentos fMP4 obviamente cortados sem inventar mídia velha."""
    if not body:
        return False
    path = _hls_clean_path(url)
    # Chaves AES não carregam cabeçalho de mídia; 16 bytes válidos são normais.
    if path.endswith(('.key', '.bin')):
        return True
    if path.endswith('.m4s') or path.endswith('.m4v') or path.endswith('.cmfv'):
        # Segmentos AES podem ser opacos até o Kodi aplicar a chave. Quando o
        # fragmento expõe boxes ISO-BMFF, porém, a ausência de mdat denuncia
        # truncamento. Assim protegemos fMP4 aberto sem quebrar HLS criptografado.
        return (b'mdat' in body) if b'moof' in body else True
    if _is_hls_init_object(url) or path.endswith('.mp4'):
        return (b'ftyp' in body and b'moov' in body) if _is_hls_init_object(url) else bool(body)
    if path.endswith('.ts'):
        return len(body) >= 188 and (body[:1] == b'\x47' or body[188:189] == b'\x47')
    return True


def _read_hls_object(response, source_url=''):
    """Lê um objeto HLS por completo e recusa resposta parcial/vazia."""
    expected = 0
    try:
        expected = int(response.headers.get('Content-Length', 0) or 0)
    except Exception:
        expected = 0
    if expected > HLS_MAX_OBJECT_BYTES:
        raise HLSReadError('segmento HLS maior que o limite seguro')

    chunks = []
    total = 0
    try:
        iterator = response.iter_content(chunk_size=64 * 1024)
        for chunk in iterator:
            if not chunk:
                continue
            total += len(chunk)
            if total > HLS_MAX_OBJECT_BYTES:
                raise HLSReadError('segmento HLS maior que o limite seguro')
            chunks.append(chunk)
    except HLSReadError:
        raise
    except Exception as exc:
        raise HLSReadError('leitura interrompida do trecho HLS: {0}'.format(str(exc)))

    body = b''.join(chunks)
    if not body:
        raise HLSReadError('o servidor entregou um trecho HLS vazio')
    if expected and len(body) < expected:
        raise HLSReadError('o servidor interrompeu o trecho HLS antes do fim')
    # Uma resposta 206 para um Range explícito é semanticamente parcial e não
    # contém necessariamente boxes moof/mdat completos. Ela deve seguir até o
    # player exatamente como veio da origem; a camada de cache já recusa 206,
    # portanto nenhuma resposta parcial é reutilizada como segmento inteiro.
    partial_response = False
    try:
        partial_response = int(getattr(response, 'status_code', 0) or 0) == 206 or bool(response.headers.get('Content-Range'))
    except Exception:
        partial_response = False
    if (source_url and _is_hls_media_segment(source_url) and not partial_response and
            not _looks_like_valid_hls_media(body, source_url)):
        raise HLSReadError('o servidor entregou um fragmento HLS incompleto')
    return body


def _hls_fetch_once(url, headers, proxies=None, expect_playlist=False, is_segment=False, attempt=0, timeout_override=None,
                    session_context=None):
    response = None
    session_lock = None
    try:
        request_headers = _hls_request_headers(headers, attempt=attempt, is_segment=is_segment)
        request_kwargs = {
            'headers': request_headers,
            'proxies': proxies,
            'timeout': _hls_timeout_for(url, is_segment=is_segment, override=timeout_override),
            'verify': TLS_VERIFY,
            'allow_redirects': True,
            'stream': True,
        }
        if session_context and session_context.get('session'):
            session_lock = session_context.get('lock')
            if session_lock:
                session_lock.acquire()
            session_context['time'] = time.time()
            response = cloudflare_session_get(session_context.get('session'), url, **request_kwargs)
        else:
            response = cloudflare_get(url, **request_kwargs)
        response.raise_for_status()
        final_url = response.url or url
        body = _read_hls_object(response, final_url)
        if expect_playlist and not body.lstrip().startswith(b'#EXTM3U'):
            raise HLSReadError('o servidor devolveu uma playlist HLS inválida')
        return {
            'body': body,
            'status': response.status_code,
            'headers': dict(response.headers or {}),
            'url': final_url
        }
    finally:
        _close_upstream_response(response)
        if session_lock:
            try:
                session_lock.release()
            except Exception:
                pass


def _segment_number(url):
    try:
        name = _hls_clean_path(url).rsplit('/', 1)[-1]
        values = re.findall(r'(\d+)', name)
        return int(values[-1]) if values else None
    except Exception:
        return None


def _select_fresher_hls_segment(playlist_body, playlist_url, failed_url):
    try:
        text = playlist_body.decode('utf-8', 'replace') if isinstance(playlist_body, bytes) else str(playlist_body or '')
        candidates = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            absolute = urljoin(playlist_url, line)
            if _is_hls_jump_candidate(absolute):
                candidates.append(absolute)
        if not candidates:
            return ''
        failed_path = _hls_clean_path(failed_url)
        for index, candidate in enumerate(candidates):
            if _hls_clean_path(candidate) == failed_path:
                if index + 1 < len(candidates):
                    return candidates[index + 1]
                return ''
        failed_number = _segment_number(failed_url)
        if failed_number is not None:
            for candidate in candidates:
                candidate_number = _segment_number(candidate)
                if candidate_number is not None and candidate_number > failed_number:
                    return candidate
        # Se a janela live já rodou, o último trecho independente é a única
        # retomada segura. Nunca usamos o mesmo URL que acabou de falhar.
        newest = candidates[-1]
        return '' if _hls_clean_path(newest) == failed_path else newest
    except Exception:
        return ''


def _try_live_hls_jump(failed_url, headers, proxies, watch_id, session_context=None):
    """Tenta saltar uma única vez para o próximo segmento independente.

    HLS fMP4 não aceita pacote TS nulo. A alternativa correta é revalidar o
    manifesto sem cache e entregar apenas um próximo fragmento real do mesmo
    canal, quando disponível. Isso troca uma lacuna curta por continuidade,
    sem gerar bytes sintéticos nem loop.
    """
    if not _is_hls_jump_candidate(failed_url):
        return None
    context = _get_hls_playlist_context(watch_id)
    if not context or not context.get('url'):
        return None
    playlist_url = context.get('url')
    context_options = context.get('options') or {}
    merged_headers = dict(headers or {})
    for key in ('User-Agent', 'Referer', 'Origin'):
        value = _opt(context_options, key, '')
        if value:
            merged_headers[key] = value
    try:
        xbmc.log('[FOOTBALL HTTPS] Segmento HLS oscilou; revalidando playlist para continuidade.', xbmc.LOGINFO)
    except Exception:
        pass
    try:
        playlist = _hls_fetch_once(
            playlist_url, merged_headers, proxies=proxies,
            expect_playlist=True, is_segment=False, attempt=1,
            timeout_override=HLS_LIVE_JUMP_PLAYLIST_TIMEOUT,
            session_context=session_context
        )
        _remember_hls_playlist_context(watch_id, playlist.get('url') or playlist_url, context_options)
        replacement = _select_fresher_hls_segment(playlist.get('body', b''), playlist.get('url') or playlist_url, failed_url)
        if not replacement:
            return None
        result = _hls_fetch_once(
            replacement, merged_headers, proxies=proxies,
            expect_playlist=False, is_segment=True, attempt=1,
            timeout_override=HLS_LIVE_JUMP_SEGMENT_TIMEOUT,
            session_context=session_context
        )
        try:
            xbmc.log('[FOOTBALL PROXY] Continuidade HLS recuperada com segmento live atualizado.', xbmc.LOGINFO)
        except Exception:
            pass
        return result
    except Exception:
        return None


def _fetch_hls_object(url, headers, proxies=None, expect_playlist=False, watch_id='', hls_child=False,
                      attempt_limit=None, timeout_override=None, allow_live_jump=True, use_buffer=True):
    """Busca playlist/segmento HLS com recuperação no prazo do Kodi.

    Portado de forma seletiva do proxy FOOTBALL: tentativa curta, revalidação
    sem cache, Range seguro e alternância de cabeçalho apenas após falha. Para
    fMP4 live, uma única revalidação de playlist pode saltar para o próximo
    segmento independente antes que o player receba EOF.
    """
    is_segment = bool(hls_child or _is_hls_media_segment(url)) and not expect_playlist
    # Só usa buffer para segmentos de mídia completos. Keys e init.mp4 continuam
    # no fluxo original para não misturar objetos com semântica diferente.
    bufferable_segment = bool(use_buffer and is_segment and _is_hls_media_segment(url) and not _is_hls_init_object(url))
    if bufferable_segment:
        cached_segment = _hls_buffer_response(watch_id, url, headers)
        if cached_segment:
            return cached_segment
    session_context = _get_hls_session_context(watch_id)
    if _is_hls_init_object(url):
        cached = _hls_init_cache_get(url)
        if cached:
            return cached
    max_attempts = int(attempt_limit or (HLS_SEGMENT_RETRY_ATTEMPTS if is_segment else HLS_PLAYLIST_RETRY_ATTEMPTS))
    max_attempts = max(1, max_attempts)
    deadline = (time.monotonic() + HLS_SEGMENT_RETRY_BUDGET) if is_segment and timeout_override is None else 0.0
    last_error = None
    jump_tried = False

    for attempt in range(max_attempts):
        try:
            result = _hls_fetch_once(
                url, headers, proxies=proxies, expect_playlist=expect_playlist,
                is_segment=is_segment, attempt=attempt, timeout_override=timeout_override,
                session_context=session_context
            )
            if _is_hls_init_object(url):
                _hls_init_cache_set(url, result)
            elif bufferable_segment:
                _hls_buffer_store(watch_id, url, result)
            # Uma resposta HLS válida após falha transitória confirma a recuperação.
            # Não deixe um estado antigo de erro contaminar a telemetria da sessão.
            if watch_id:
                clear_playback_failure(watch_id)
            return result
        except Exception as exc:
            last_error = exc
            retryable = _is_retryable_hls_failure(exc)
            if not retryable:
                raise

            # Após a primeira falha de um fragmento fMP4, tentar o manifest
            # atual é melhor que insistir longamente no mesmo segmento morto.
            if (HLS_ENABLE_LIVE_SEGMENT_JUMP and is_segment and allow_live_jump and not jump_tried and
                    _is_hls_jump_candidate(url) and watch_id):
                jump_tried = True
                replacement = _try_live_hls_jump(url, headers, proxies, watch_id, session_context=session_context)
                if replacement:
                    return replacement

            if (attempt + 1) >= max_attempts:
                break
            if deadline and (time.monotonic() + 0.20) >= deadline:
                break
            delay = HLS_RETRY_BACKOFF[min(attempt, len(HLS_RETRY_BACKOFF) - 1)]
            if deadline:
                delay = min(delay, max(0.0, deadline - time.monotonic()))
            if delay > 0:
                time.sleep(delay)

    if last_error:
        raise last_error
    raise HLSReadError('falha desconhecida ao obter a transmissão HLS')


def _record_playback_failure(watch_id, exc):
    watch_id = _normalize_playback_watch(watch_id)
    if not watch_id:
        return
    try:
        failure = _classify_upstream_failure(exc)
        previous = get_playback_failure(watch_id) or {}
        same_failure = (
            previous.get('message') == failure.get('message') and
            int(previous.get('status', 0) or 0) == int(failure.get('status', 0) or 0)
        )
        count = int(previous.get('count', 0) or 0) + 1 if same_failure else 1
        state = {
            'message': failure.get('message', 'falha de comunicação com o servidor de origem'),
            'status': int(failure.get('status', 0) or 0),
            'immediate': bool(failure.get('immediate', False)),
            'count': count,
            'time': time.time()
        }
        WINDOW.setProperty(_playback_failure_key(watch_id), json.dumps(state, separators=(',', ':')))
    except Exception:
        pass


def attach_adaptive_playback(raw_url):
    """Marca uma URL loopback para uso com InputStream Adaptive.

    A marca é local e só informa ao proxy que a playlist HLS será atualizada
    pelo ISA. Dessa forma o proxy preserva resolução, DNS interno, redirects,
    sessão HTTP e headers de origem, mas não aplica sua fila HLS reescrita
    sobre outro demuxador que já possui buffer/live-delay próprios.
    """
    if not raw_url:
        return raw_url
    try:
        parsed = urlparse(raw_url)
        if not _is_own_proxy_url(raw_url):
            return raw_url
        if PLAYBACK_ADAPTIVE_QUERY + '=' in (parsed.query or ''):
            return raw_url
        separator = '&' if parsed.query else '?'
        return raw_url + separator + PLAYBACK_ADAPTIVE_QUERY + '=1'
    except Exception:
        return raw_url


def attach_playback_watch(raw_url, watch_id):
    """Anexa um identificador apenas à URL loopback do próprio proxy."""
    watch_id = _normalize_playback_watch(watch_id)
    if not watch_id or not raw_url:
        return raw_url
    clear_playback_failure(watch_id)
    try:
        parsed = urlparse(raw_url)
        if not _is_own_proxy_url(raw_url):
            return raw_url
        if 'url=' not in (parsed.query or ''):
            return raw_url
        separator = '&' if parsed.query else '?'
        return raw_url + separator + PLAYBACK_WATCH_QUERY + '=' + quote_plus(watch_id)
    except Exception:
        return raw_url

def _split_kodi_url(raw):
    if '|' in raw:
        url, options = raw.split('|', 1)
    else:
        url, options = raw, ''
    parsed_options = parse_qs(options, keep_blank_values=True)
    return url, parsed_options


def _opt(options, key, default=''):
    value = options.get(key, [default])
    return value[0] if value else default


def _proxy_target_url(proxy_base, target_url):
    raw_target, _ = _split_kodi_url(target_url)
    extension = os.path.splitext(urlparse(raw_target).path)[1].lower()
    if extension not in (
        '.aac', '.ac3', '.eac3', '.m3u', '.m3u8', '.m4a', '.m4b', '.m4p',
        '.m4s', '.m4v', '.mp3', '.mp4', '.mpeg', '.mpg', '.ogg', '.oga',
        '.ogv', '.opus', '.ts', '.vtt', '.wav', '.webvtt'
    ):
        extension = ''

    endpoint = proxy_base.split('?url=', 1)[0].rstrip('/')
    path = '/resource{}'.format(extension) if extension else '/'
    return endpoint + path + '?url=' + quote_plus(target_url)


def proxy_url(raw_url):
    """Encapsula URL HTTP externa no proxy local sem alterar URLs locais."""
    if not raw_url:
        return ''
    try:
        value = str(raw_url)
        if _is_own_proxy_url(value):
            return value
        current_prefix = _proxy_base()
        if not current_prefix:
            return value
        raw_target, _ = _split_kodi_url(value)
        lower = raw_target.lower()
        if not lower.startswith(('http://', 'https://')):
            return value
        return _proxy_target_url(current_prefix, value)
    except Exception:
        return raw_url


def _build_proxy_url(url, options, watch_id='', adaptive_hls=False):
    params = {}
    user_agent = _opt(options, 'User-Agent', DEFAULT_UA)
    referer = _opt(options, 'Referer', '')
    origin = _opt(options, 'Origin', '')
    if user_agent:
        params['User-Agent'] = user_agent
    if referer:
        params['Referer'] = referer
    if origin:
        params['Origin'] = origin
    kodi_url = url + ('|' + urlencode(params) if params else '')
    proxy_base = _proxy_base()
    if not proxy_base:
        return kodi_url
    proxy_target = _proxy_target_url(proxy_base, kodi_url)
    # Tudo que nasce dentro de uma playlist fica marcado como HLS, inclusive
    # URLs de segmento sem extensão. Isso habilita proteção contra respostas
    # parciais sem afetar VODs HTTP diretos ou as imagens do addon.
    proxy_target += '&' + PLAYBACK_HLS_QUERY + '=1'
    watch_id = _normalize_playback_watch(watch_id)
    if watch_id:
        proxy_target += '&' + PLAYBACK_WATCH_QUERY + '=' + quote_plus(watch_id)
    if adaptive_hls:
        proxy_target += '&' + PLAYBACK_ADAPTIVE_QUERY + '=1'
    return proxy_target


def _rewrite_attr_uris(line, base_url, options, watch_id='', adaptive_hls=False):
    def repl(match):
        quote_char = match.group(1)
        uri = match.group(2)
        absolute = urljoin(base_url, uri)
        return 'URI={}{}{}'.format(quote_char, _build_proxy_url(absolute, options, watch_id, adaptive_hls), quote_char)
    return re.sub(r'URI=(["\'])(.*?)\1', repl, line)


def _apply_live_hls_holdback(content):
    """Mantém o player alguns segmentos atrás da borda de uma live ruim.

    Só remove a cauda de manifesto vivo sem ENDLIST e com janela suficiente.
    Não altera VOD, não inventa segmentos e não muda MEDIA-SEQUENCE; portanto
    o cliente continua recebendo uma playlist HLS válida, apenas com margem de
    publicação para o próximo fragmento.
    """
    try:
        lines = str(content or '').splitlines()
        if not lines or any(line.strip().upper() == '#EXT-X-ENDLIST' for line in lines):
            return content, 0
        media_indexes = []
        for index, raw_line in enumerate(lines):
            item = raw_line.strip()
            if item and not item.startswith('#'):
                media_indexes.append(index)
        minimum = max(1, int(HLS_LIVE_HOLDBACK_MIN_SEGMENTS or 1))
        holdback = max(0, int(HLS_LIVE_HOLDBACK_SEGMENTS or 0))
        if holdback <= 0 or len(media_indexes) < minimum or len(media_indexes) <= holdback:
            return content, 0
        first_drop = media_indexes[-holdback]
        previous_media = media_indexes[-holdback - 1]
        # Tudo depois do último URI preservado pertence aos segmentos que
        # serão segurados (EXTINF, PDT, MAP, PART/PRELOAD-HINT etc.).
        trimmed = lines[:previous_media + 1]
        if not trimmed:
            return content, 0
        return '\n'.join(trimmed) + '\n', holdback
    except Exception:
        return content, 0


def _rewrite_playlist(content, base_url, options, watch_id='', adaptive_hls=False):
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        if stripped.startswith('#'):
            if 'URI=' in stripped:
                lines.append(_rewrite_attr_uris(line, base_url, options, watch_id, adaptive_hls))
            else:
                lines.append(line)
            continue
        absolute = urljoin(base_url, stripped)
        lines.append(_build_proxy_url(absolute, options, watch_id, adaptive_hls))
    return '\n'.join(lines) + '\n'


class M3UProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send_headers(self, status, content_type='', content_length=None, upstream_headers=None, cache_images=False, preserve_media_cache=False):
        self.send_response(status)
        self.send_header('Content-Type', content_type or 'application/octet-stream')
        if cache_images and (content_type or '').lower().startswith('image/'):
            self.send_header('Cache-Control', 'public, max-age=21600')
        elif preserve_media_cache and upstream_headers and upstream_headers.get('Cache-Control'):
            # Segmentos .m4s publicados como immutable podem ser reutilizados
            # pelo cliente em reabertura, sem aplicar cache a playlists live.
            self.send_header('Cache-Control', upstream_headers.get('Cache-Control'))
        else:
            self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        if content_length is not None:
            self.send_header('Content-Length', str(content_length))
        if upstream_headers:
            for header in ('Content-Range', 'Accept-Ranges'):
                value = upstream_headers.get(header)
                if value:
                    self.send_header(header, value)
        self.end_headers()

    def _send_playlist(self, body, send_body):
        self._send_headers(
            200,
            'application/vnd.apple.mpegurl',
            len(body),
            upstream_headers=None,
            cache_images=False
        )
        if send_body and body:
            self.wfile.write(body)

    def _handle_health(self, send_body):
        body = (HEALTH_TOKEN + '\n').encode('ascii')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('X-football-Proxy', HEALTH_TOKEN)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if send_body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                # Cliente de health/GUI pode fechar o loopback assim que recebe os
                # headers. Isso é desconexão local normal, não falha do proxy.
                pass

    @staticmethod
    def _looks_like_playlist(chunk):
        try:
            return bool(chunk and chunk.lstrip().startswith(b'#EXTM3U'))
        except Exception:
            return False

    def _handle_request(self, send_body=True):
        parsed_path = urlparse(self.path)
        if parsed_path.path == HEALTH_PATH:
            self._handle_health(send_body)
            return

        query = parse_qs(parsed_path.query)
        # parse_qs já desfaz quote_plus. Decodificar uma segunda vez corrompia
        # tokens assinados com "+" e parâmetros "%2F" de URLs HLS.
        watch_id = _normalize_playback_watch(query.get(PLAYBACK_WATCH_QUERY, [''])[0])
        hls_child = str(query.get(PLAYBACK_HLS_QUERY, [''])[0]).strip() == '1'
        adaptive_hls = str(query.get(PLAYBACK_ADAPTIVE_QUERY, [''])[0]).strip() == '1'
        target_url = query.get('url', [None])[0]
        if not target_url:
            self.send_error(400)
            return

        try:
            url, options = _split_kodi_url(target_url)
            headers = {
                'User-Agent': _opt(options, 'User-Agent', DEFAULT_UA),
                'Referer': _opt(options, 'Referer', ''),
                'Origin': _opt(options, 'Origin', '')
            }
            try:
                import secureurl
                url = secureurl.play_url(url, headers=headers)
            except Exception:
                pass
            # O Kodi/FFmpeg pode usar Range para abrir, validar cache ou
            # retomar objetos fMP4. Preserve a requisição byte a byte para a
            # origem, junto com If-Range quando existir; o CDN então mantém a
            # semântica HTTP correta (206 parcial ou 200 se a ETag mudou).
            client_range = self.headers.get('Range', '')
            client_if_range = self.headers.get('If-Range', '')
            if client_range:
                headers['Range'] = client_range
            if client_if_range:
                headers['If-Range'] = client_if_range
            headers = {k: v for k, v in headers.items() if v}

            proxies = None
            playlist_hint = _is_hls_playlist_url(url)
            hls_request = bool(hls_child or playlist_hint)

            # HEAD continua leve: ele não precisa materializar um segmento para
            # responder ao Kodi. O GET é quem recebe a proteção integral.
            if not send_body:
                response = cloudflare_get(
                    url, headers=headers, proxies=proxies, timeout=(8, 25),
                    verify=TLS_VERIFY, allow_redirects=True, stream=True
                )
                response.raise_for_status()
                status = response.status_code if response.status_code in (200, 206) else 200
                self._send_headers(
                    status, response.headers.get('Content-Type', ''),
                    response.headers.get('Content-Length'),
                    upstream_headers=response.headers, cache_images=True
                )
                return

            if hls_request:
                try:
                    hls_object = _fetch_hls_object(
                        url, headers, proxies=proxies, expect_playlist=playlist_hint,
                        watch_id=watch_id, hls_child=hls_child,
                        allow_live_jump=not adaptive_hls, use_buffer=not adaptive_hls
                    )
                except Exception as upstream_error:
                    try:
                        failure_status = _response_status_from_exception(upstream_error)
                        failure_detail = type(upstream_error).__name__
                        if failure_status:
                            failure_detail += ' HTTP {}'.format(failure_status)
                        xbmc.log(
                            '[FOOTBALL HTTPS] A requisicao HTTPS falhou ({}); sem fallback para HTTP.'.format(failure_detail),
                            xbmc.LOGWARNING
                        )
                    except Exception:
                        pass
                    # Para a playlist principal, uma falha transitória não
                    # descarta de imediato segmentos que já estão íntegros na
                    # RAM. O proxy devolve a próxima janela local e preserva
                    # a continuidade por alguns ciclos de TARGETDURATION.
                    if playlist_hint and watch_id:
                        stale_text, stale_details, stale_base = _hls_stale_buffered_playlist(watch_id)
                        context = _get_hls_playlist_context(watch_id) or {}
                        stale_options = context.get('options') or options
                        if stale_text and stale_base:
                            _log_hls_buffer_release(watch_id, stale_details, stale=True)
                            body = _rewrite_playlist(stale_text, stale_base, stale_options, watch_id).encode('utf-8')
                            self._send_playlist(body, True)
                            return
                    raise upstream_error
                source_body = hls_object['body']
                content_type = hls_object['headers'].get('Content-Type', '')
                final_url = hls_object['url']
                base_url = final_url.rsplit('/', 1)[0] + '/'
                is_playlist = (
                    playlist_hint or
                    'mpegurl' in (content_type or '').lower() or
                    self._looks_like_playlist(source_body)
                )

                if is_playlist:
                    if len(source_body) > 2 * 1024 * 1024:
                        raise HLSReadError('playlist HLS maior que o limite seguro')
                    raw_text = source_body.decode('utf-8', 'replace').replace('\\/', '/')
                    _remember_hls_playlist_context(watch_id, final_url, options)
                    if adaptive_hls:
                        # O InputStream Adaptive possui downloader segmentado e
                        # buffer próprio. Preserve a playlist live original,
                        # reescrevendo apenas os URLs para o loopback seguro.
                        text = raw_text
                        body = _rewrite_playlist(text, base_url, options, watch_id, adaptive_hls=True).encode('utf-8')
                    else:
                        # Pré-carrega a janela original. A playlist publicada ao
                        # Kodi é montada depois somente com segmentos confirmados.
                        _hls_buffer_note_source(watch_id, raw_text, base_url)
                        _prime_hls_buffer(watch_id, raw_text, base_url, headers, proxies=proxies)
                        text, buffer_details = _hls_buffered_live_playlist(watch_id, raw_text, base_url)
                        if text:
                            _log_hls_buffer_release(watch_id, buffer_details, stale=False)
                        else:
                            # Fallback só quando a origem ainda não entregou uma
                            # corrida mínima de segmentos completos na primeira abertura.
                            text, held_segments = _apply_live_hls_holdback(raw_text)
                            if held_segments:
                                xbmc.log('[FOOTBALL PROXY] Live HLS com margem de %d segmentos para evitar queda na borda.' % held_segments, xbmc.LOGINFO)
                        body = _rewrite_playlist(text, base_url, options, watch_id).encode('utf-8')
                    self._send_playlist(body, True)
                    return

                status = hls_object['status'] if hls_object['status'] in (200, 206) else 200
                self._send_headers(
                    status, content_type, len(source_body),
                    upstream_headers=hls_object['headers'], cache_images=False,
                    preserve_media_cache=_is_hls_media_segment(final_url)
                )
                self.wfile.write(source_body)
                return

            response = cloudflare_get(
                url, headers=headers, proxies=proxies, timeout=(8, 25),
                verify=TLS_VERIFY, allow_redirects=True, stream=True
            )
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '')
            final_url = response.url or url
            base_url = final_url.rsplit('/', 1)[0] + '/'
            declared_playlist = (
                '.m3u8' in final_url.lower() or
                'mpegurl' in (content_type or '').lower()
            )

            if declared_playlist:
                source_body = response.content
                raw_text = source_body.decode(response.encoding or 'utf-8', 'replace').replace('\\/', '/')
                _remember_hls_playlist_context(watch_id, final_url, options)
                if adaptive_hls:
                    text = raw_text
                    body = _rewrite_playlist(text, base_url, options, watch_id, adaptive_hls=True).encode('utf-8')
                else:
                    _hls_buffer_note_source(watch_id, raw_text, base_url)
                    _prime_hls_buffer(watch_id, raw_text, base_url, headers, proxies=proxies)
                    text, buffer_details = _hls_buffered_live_playlist(watch_id, raw_text, base_url)
                    if text:
                        _log_hls_buffer_release(watch_id, buffer_details, stale=False)
                    else:
                        text, held_segments = _apply_live_hls_holdback(raw_text)
                        if held_segments:
                            xbmc.log('[FOOTBALL PROXY] Live HLS com margem de %d segmentos para evitar queda na borda.' % held_segments, xbmc.LOGINFO)
                    body = _rewrite_playlist(text, base_url, options, watch_id).encode('utf-8')
                self._send_playlist(body, True)
                return

            # Alguns provedores devolvem HLS sem ".m3u8". Quando isso ocorre
            # fora de uma sessão marcada, mantemos o comportamento conservador
            # anterior, apenas detectando o cabeçalho #EXTM3U.
            iterator = response.iter_content(chunk_size=64 * 1024)
            first_chunk = next(iterator, b'')
            if self._looks_like_playlist(first_chunk):
                chunks = [first_chunk]
                total = len(first_chunk)
                for chunk in iterator:
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > 2 * 1024 * 1024:
                        raise ValueError('Playlist HLS grande demais')
                    chunks.append(chunk)
                source_body = b''.join(chunks)
                raw_text = source_body.decode(response.encoding or 'utf-8', 'replace').replace('\\/', '/')
                _remember_hls_playlist_context(watch_id, final_url, options)
                if adaptive_hls:
                    text = raw_text
                    body = _rewrite_playlist(text, base_url, options, watch_id, adaptive_hls=True).encode('utf-8')
                else:
                    _hls_buffer_note_source(watch_id, raw_text, base_url)
                    _prime_hls_buffer(watch_id, raw_text, base_url, headers, proxies=proxies)
                    text, buffer_details = _hls_buffered_live_playlist(watch_id, raw_text, base_url)
                    if text:
                        _log_hls_buffer_release(watch_id, buffer_details, stale=False)
                    else:
                        text, held_segments = _apply_live_hls_holdback(raw_text)
                        if held_segments:
                            xbmc.log('[FOOTBALL PROXY] Live HLS com margem de %d segmentos para evitar queda na borda.' % held_segments, xbmc.LOGINFO)
                    body = _rewrite_playlist(text, base_url, options, watch_id).encode('utf-8')
                self._send_playlist(body, True)
                return

            status = response.status_code if response.status_code in (200, 206) else 200
            self._send_headers(
                status, content_type, response.headers.get('Content-Length'),
                upstream_headers=response.headers, cache_images=True
            )
            if first_chunk:
                self.wfile.write(first_chunk)
            for chunk in iterator:
                if chunk:
                    self.wfile.write(chunk)

        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            # Erros de origem são salvos por tentativa para que helpers.py só
            # avise após a confirmação do Kodi, sem vazar URL/token ao usuário.
            _record_playback_failure(watch_id if 'watch_id' in locals() else '', exc)
            failure = None
            try:
                failure = _classify_upstream_failure(exc)
                # Falha transitória de HLS pode ser recuperada pelo FFmpegDirect.
                # Em arte estática, 404/410 é ausência do recurso remoto e não uma
                # falha interna do proxy; mantenha como WARNING. Só a trilha de
                # reprodução recebe ERROR para condição terminal.
                hls_request_ = bool(locals().get('hls_request', False))
                playback_request = bool((watch_id if 'watch_id' in locals() else '') or hls_request_)
                transient_hls = hls_request_ and not bool(failure.get('immediate', False))
                quiet_static_4xx = (not playback_request and 400 <= int(failure.get('status', 0) or 0) < 500)
                warning_only = transient_hls or quiet_static_4xx
                level = xbmc.LOGWARNING if warning_only else xbmc.LOGERROR
                label = '[FOOTBALL PROXY AVISO]' if warning_only else '[FOOTBALL PROXY ERROR]'
                xbmc.log('{0} {1}'.format(label, failure.get('message', str(exc))), level)
            except Exception:
                pass
            try:
                # Preserve o status real da origem quando existe. Antes, qualquer
                # 404 remoto virava HTTP 500 local, mascarando o diagnóstico no Kodi.
                status = int((failure or {}).get('status', 0) or 0)
                if not 400 <= status <= 599:
                    status = 502
                self.send_error(status)
            except Exception:
                pass

    def do_GET(self):
        self._handle_request(send_body=True)

    def do_HEAD(self):
        self._handle_request(send_body=False)


def _load_preferred_dynamic_port():
    try:
        with open(DYNAMIC_PORT_STATE_FILE, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return _valid_port(data.get('port')) if isinstance(data, dict) else None
    except Exception:
        return None


def _save_preferred_dynamic_port(port):
    port = _valid_port(port)
    if not port:
        return
    try:
        folder = os.path.dirname(DYNAMIC_PORT_STATE_FILE)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        pass
    tmp = DYNAMIC_PORT_STATE_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'port': int(port)}, fh, separators=(',', ':'))
        try:
            os.replace(tmp, DYNAMIC_PORT_STATE_FILE)
        except AttributeError:
            if os.path.exists(DYNAMIC_PORT_STATE_FILE):
                os.remove(DYNAMIC_PORT_STATE_FILE)
            os.rename(tmp, DYNAMIC_PORT_STATE_FILE)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


class ProxyServer(threading.Thread):
    def __init__(self, port=DYNAMIC_PORT):
        threading.Thread.__init__(self)
        self.daemon = True
        self.requested_port = _valid_port(port) if port else DYNAMIC_PORT
        self.port = 0
        self.server = None
        self.bound = threading.Event()
        self.failed = threading.Event()

    def run(self):
        try:
            # requested_port=0 pede ao SO uma porta efêmera livre de forma atômica.
            # Não há janela TOCTOU entre "testar porta" e "bindar porta".
            self.server = ThreadedHTTPServer((HOST, self.requested_port), M3UProxyHandler)
            self.port = int(self.server.server_address[1])
            self.bound.set()
            xbmc.log('[FOOTBALL PROXY] Rodando em http://{}:{} (porta dinâmica).'.format(HOST, self.port), xbmc.LOGINFO)
            # A própria ProxyServer é a thread do serve_forever; não criamos uma
            # segunda thread/Monitor redundante. service.py controla o lifecycle.
            self.server.serve_forever(poll_interval=0.25)
        except Exception as exc:
            self.failed.set()
            try:
                xbmc.log('[FOOTBALL PROXY] Falha no servidor local dinâmico: {}'.format(str(exc)), xbmc.LOGERROR)
            except Exception:
                pass
        finally:
            server = self.server
            self.server = None
            if server:
                try:
                    server.server_close()
                except Exception:
                    pass

    def stop(self):
        server = self.server
        if server:
            try:
                xbmc.log('[FOOTBALL PROXY] Encerrando porta dinâmica {}...'.format(self.port), xbmc.LOGINFO)
            except Exception:
                pass
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass


def _wait_for_proxy(instance, timeout=2.5):
    deadline = time.monotonic() + float(timeout)
    while time.monotonic() < deadline:
        if instance.failed.is_set():
            return False
        if instance.bound.is_set():
            port = _valid_port(instance.port)
            if port and _health_check(port):
                return True
        time.sleep(0.05)
    port = _valid_port(instance.port)
    return bool(port and _health_check(port))


def _start_owned_dynamic_proxy(owner):
    global _proxy_instance, _owned_port
    preferred = _load_preferred_dynamic_port()
    requested_ports = []
    if preferred:
        requested_ports.append(preferred)
    # Porta 0 continua sendo a autoridade de fallback: o kernel escolhe
    # atomicamente uma porta livre, sem varrer faixa nem criar janela TOCTOU.
    requested_ports.extend([DYNAMIC_PORT, DYNAMIC_PORT, DYNAMIC_PORT])

    for requested in requested_ports[:4]:
        instance = ProxyServer(requested)
        instance.start()
        if _wait_for_proxy(instance):
            port = _valid_port(instance.port)
            if port:
                _proxy_instance = instance
                _owned_port = port
                _mark_proxy_running(port, owner=owner)
                _save_preferred_dynamic_port(port)
                try:
                    if preferred and requested == preferred and port == preferred:
                        xbmc.log('[FOOTBALL PROXY] Porta dinâmica preferida reutilizada: {}.'.format(port), xbmc.LOGINFO)
                    else:
                        xbmc.log('[FOOTBALL PROXY] Porta dinâmica selecionada pelo SO: {}.'.format(port), xbmc.LOGINFO)
                except Exception:
                    pass
                return True
        try:
            instance.stop()
            instance.join(0.8)
        except Exception:
            pass
        # Se a preferida colidiu, nao tente o mesmo numero outra vez nesta rodada.
        if preferred and requested == preferred:
            try:
                xbmc.log('[FOOTBALL PROXY] Porta dinâmica anterior ocupada; solicitando nova porta ao SO.', xbmc.LOGWARNING)
            except Exception:
                pass
            preferred = None

    _proxy_instance = None
    _owned_port = None
    return False


def _owned_instance_alive():
    """Verifica ownership local sem abrir uma segunda conexão HTTP.

    O service possui a própria thread/HTTPServer. Enquanto essa thread, o socket
    e a porta vinculada estiverem vivos, um timeout isolado de /health não deve
    derrubar uma live em reprodução. /health continua sendo usado por outros
    intérpretes para descobrir o service, mas não como gatilho de restart do dono.
    """
    try:
        instance = _proxy_instance
        port = _valid_port(_owned_port)
        if not instance or not port or _valid_port(getattr(instance, 'port', 0)) != port:
            return False
        if not instance.bound.is_set() or not instance.is_alive():
            return False
        server = getattr(instance, 'server', None)
        if server is None:
            return False
        try:
            return int(server.fileno()) >= 0
        except Exception:
            return True
    except Exception:
        return False


def start(owner='plugin', force_own=False):
    global _proxy_instance, _owned_port
    install_cloudflare_dns()
    owner = str(owner or 'plugin').strip().lower()
    if RUNTIME_PLATFORM == 'android':
        try:
            xbmc.log('[FOOTBALL PROXY] Perfil Android: mesma rota FFmpegDirect, I/O HLS tolerante e fallback nativo com memória reduzida.', xbmc.LOGINFO)
        except Exception:
            pass

    # Se esta própria interpretação Python já possui uma instância íntegra,
    # republique-a. A checagem precede propriedades globais para não perder
    # ownership durante uma corrida com outra invocação curta do plugin.
    if _owned_instance_alive():
        _mark_proxy_running(_owned_port, owner=owner)
        return True

    published_port = _current_proxy_port(prefer_owned=False)
    published_owner = _published_owner()
    published_healthy = bool(published_port and _stable_published_health(published_port))

    # Invocações normais do plugin reutilizam o proxy persistente do service.
    # O service, por outro lado, exige ownership próprio: nunca fica dependente
    # de uma thread daemon criada por uma invocação curta do addon.py.
    if published_healthy and not force_own:
        return True
    # force_own é usado pelo service.py: uma publicação de outro intérprete,
    # mesmo com owner='service', não basta. O processo atual precisa possuir a
    # thread que será encerrada/reiniciada com este próprio serviço.

    if WINDOW.getProperty(PROPERTY_NAME) == 'true' and not published_healthy:
        _clear_proxy_properties(expected_port=published_port or None)
        try:
            xbmc.log('[FOOTBALL PROXY] Publicação antiga sem health-check; criando nova porta dinâmica.', xbmc.LOGWARNING)
        except Exception:
            pass

    # Descarte uma instância local que perdeu o health-check antes de criar outra.
    if _proxy_instance:
        stale_instance = _proxy_instance
        _proxy_instance = None
        _owned_port = None
        try:
            stale_instance.stop()
            stale_instance.join(1.0)
        except Exception:
            pass

    if _start_owned_dynamic_proxy(owner):
        return True

    # Não apague uma publicação íntegra feita em paralelo por outro processo.
    published_port = _current_proxy_port(prefer_owned=False)
    if published_port and _stable_published_health(published_port):
        return True
    _clear_proxy_properties(expected_port=published_port or None)
    try:
        xbmc.log('[FOOTBALL PROXY] Não foi possível criar um listener loopback dinâmico.', xbmc.LOGERROR)
    except Exception:
        pass
    return False


def is_running(require_owned=False):
    """Confirma o listener sem matar uma live por falso-negativo de health.

    O service supervisiona a instância que ele próprio possui por estado de
    thread/socket. Processos curtos do plugin continuam usando /health HEAD para
    validar a publicação compartilhada.
    """
    if require_owned:
        return _owned_instance_alive()
    port = _current_proxy_port()
    return bool(port and _health_check(port))


def stop():
    global _proxy_instance, _owned_port
    instance = _proxy_instance
    owned_port = _owned_port
    _proxy_instance = None
    _owned_port = None
    if instance:
        try:
            instance.stop()
        except Exception:
            pass
        try:
            instance.join(2.0)
        except Exception:
            pass
        _clear_proxy_properties(expected_port=owned_port)
        try:
            xbmc.log('[FOOTBALL PROXY] Finalizado.', xbmc.LOGINFO)
        except Exception:
            pass
    elif owned_port:
        _clear_proxy_properties(expected_port=owned_port)
