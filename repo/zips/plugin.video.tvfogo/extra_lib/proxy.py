# -*- coding: utf-8 -*-
#
# proxy.py - Proxy HTTP/HTTPS local (127.0.0.1) que usa o customdns.py como
# resolvedor DNS-over-HTTPS (DoH).
#
# Comportamento (inspirado no Cloudflare WARP, em escala de addon):
#   * Escuta apenas em 127.0.0.1: nada fica exposto na rede.
#   * Todo nome de host é resolvido via customdns.resolve_via_doh (DoH),
#     nunca pelo DNS local do aparelho.
#   * Somente IPv4 (A records), como o customdns.py já exige.
#   * Cache DNS com TTL e deduplicação de consultas simultâneas para o
#     mesmo host (evita rajadas de DoH em streams HLS/IPTV).
#   * Túnel bidirecional (CONNECT e HTTP) com select() e timeout de inatividade.
#
# Este módulo NÃO altera o customdns.py: só o importa e chama resolve_via_doh.
# Não é uma VPN: não cria interface TUN nem cifra tráfego. Ele faz DNS
# seguro + proxy local, que é o que um addon Kodi consegue fazer.

import errno
import ipaddress
import select
import socket
import threading
import time
from urllib.parse import urlsplit

try:
    from extra_lib import customdns  # layout dentro do addon
except ImportError:
    try:
        import customdns  # execução a partir da própria pasta extra_lib
    except ImportError:
        customdns = None

# --- Configurações ---------------------------------------------------------
HOST = '127.0.0.1'
PORT = 1080
BUFFER_SIZE = 65536
HEADER_LIMIT = 65536          # tamanho máximo do cabeçalho HTTP aceito
CLIENT_TIMEOUT = 10           # leitura inicial do cliente
CONNECT_TIMEOUT = 15          # conexão com o destino
IDLE_TIMEOUT = 300            # inatividade do túnel
MAX_CLIENTS = 128             # conexões simultâneas (cada uma usa 2 fds)
DOH_WAIT = 10                 # tempo máximo que um pedido espera outro DoH
DNS_TTL = 300                 # cache de sucesso (customdns não devolve TTL)
DNS_NEG_TTL = 20              # cache de falha, para não martelar o DoH
VERBOSE = False               # True = loga cada requisição (use só para debug)

_slots = threading.BoundedSemaphore(MAX_CLIENTS)
_dns_lock = threading.Lock()
_dns_cache = {}               # host -> (ip ou None, expira em monotonic)
_dns_inflight = {}            # host -> threading.Event


def _log(message, debug=False):
    if debug and not VERBOSE:
        return
    line = f"[proxy] {message}"
    try:
        import xbmc
        xbmc.log(line, getattr(xbmc, 'LOGINFO', 1))
    except Exception:
        print(line)


# --- Resolução DNS ---------------------------------------------------------

def _is_ipv4(value):
    try:
        return ipaddress.ip_address(value).version == 4
    except ValueError:
        return False


def _doh_lookup(host):
    """Chama o DoH do customdns.py. Retorna IPv4 ou None."""
    if customdns is None:
        _log("customdns.py não encontrado; impossível resolver via DoH.")
        return None
    try:
        ip = customdns.resolve_via_doh(host)
    except Exception as e:
        _log(f"Erro no DoH para {host}: {e}")
        return None
    return ip if ip and _is_ipv4(ip) else None


def resolve(host):
    """Resolve host -> IPv4 usando cache, deduplicação e customdns (DoH)."""
    host = (host or '').strip().rstrip('.').lower()
    if not host:
        return None

    # IP literal: IPv4 passa direto, IPv6 é recusado (addon é IPv4-only).
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return str(literal) if literal.version == 4 else None
    if host == 'localhost':
        return '127.0.0.1'

    now = time.monotonic()
    with _dns_lock:
        hit = _dns_cache.get(host)
        if hit and hit[1] > now:
            return hit[0]
        waiter = _dns_inflight.get(host)
        owner = waiter is None
        if owner:
            waiter = threading.Event()
            _dns_inflight[host] = waiter

    if not owner:
        # Outro thread já está consultando o DoH para este host.
        waiter.wait(DOH_WAIT)
        with _dns_lock:
            hit = _dns_cache.get(host)
        return hit[0] if hit else None

    ip = None
    try:
        ip = _doh_lookup(host)
        _log(f"DoH {host} -> {ip}", debug=True)
    finally:
        with _dns_lock:
            ttl = DNS_TTL if ip else DNS_NEG_TTL
            _dns_cache[host] = (ip, time.monotonic() + ttl)
            _dns_inflight.pop(host, None)
        waiter.set()
    return ip


# --- Parsing HTTP ----------------------------------------------------------

def _read_head(sock):
    """Lê cabeçalhos até \\r\\n\\r\\n. Retorna (cabeçalho, bytes extras)."""
    data = b''
    while b'\r\n\r\n' not in data:
        chunk = sock.recv(BUFFER_SIZE)
        if not chunk:
            break
        data += chunk
        if len(data) > HEADER_LIMIT:
            raise ValueError('cabeçalho HTTP grande demais')
    head, _, rest = data.partition(b'\r\n\r\n')
    return head, rest


def _parse_head(head):
    lines = head.decode('latin-1').split('\r\n')
    parts = lines[0].split(' ', 2)
    if len(parts) < 2:
        raise ValueError('linha de requisição inválida')
    method = parts[0].upper()
    target = parts[1]
    version = parts[2] if len(parts) > 2 else 'HTTP/1.1'
    headers = lines[1:]
    return method, target, version, headers


def _get_header(headers, name):
    name = name.lower() + ':'
    for line in headers:
        if line.lower().startswith(name):
            return line.split(':', 1)[1].strip()
    return None


def _split_host_port(hostport, default_port):
    hostport = hostport.strip()
    if hostport.startswith('['):                       # [IPv6]:porta
        end = hostport.find(']')
        if end == -1:
            raise ValueError('IPv6 mal formado')
        host = hostport[1:end]
        rest = hostport[end + 1:]
        port = int(rest[1:]) if rest.startswith(':') else default_port
    elif ':' in hostport:
        host, _, p = hostport.rpartition(':')
        port = int(p)
    else:
        host, port = hostport, default_port
    if not 0 < port < 65536:
        raise ValueError(f'porta inválida: {port}')
    return host, port


# --- Conexão e túnel -------------------------------------------------------

def _connect(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass
    sock.settimeout(CONNECT_TIMEOUT)
    try:
        sock.connect((ip, port))
    except Exception:
        sock.close()
        raise
    sock.settimeout(IDLE_TIMEOUT)
    return sock


def _tunnel(a, b):
    """Copia dados nos dois sentidos até um dos lados fechar ou ficar ocioso."""
    socks = [a, b]
    while True:
        try:
            readable, _, exceptional = select.select(socks, [], socks, IDLE_TIMEOUT)
        except (OSError, ValueError):
            return
        if exceptional or not readable:
            return
        for s in readable:
            try:
                data = s.recv(BUFFER_SIZE)
            except OSError:
                return
            if not data:
                return
            other = b if s is a else a
            try:
                other.sendall(data)
            except OSError:
                return


def _send_status(sock, code, reason):
    try:
        sock.sendall(
            f'HTTP/1.1 {code} {reason}\r\nConnection: close\r\n'
            f'Content-Length: 0\r\n\r\n'.encode('ascii')
        )
    except OSError:
        pass


def _handle_client(client, addr):
    upstream = None
    try:
        client.settimeout(CLIENT_TIMEOUT)
        head, rest = _read_head(client)
        if not head:
            return
        method, target, version, headers = _parse_head(head)

        if method == 'CONNECT':
            host, port = _split_host_port(target, 443)
            ip = resolve(host)
            if not ip:
                _log(f"Falha DNS para {host} (CONNECT de {addr[0]})")
                _send_status(client, 502, 'Bad Gateway')
                return
            upstream = _connect(ip, port)
            client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            if rest:
                upstream.sendall(rest)

        else:
            if target.lower().startswith('http://'):
                parts = urlsplit(target)
                host, port = _split_host_port(parts.netloc, 80)
                path = (parts.path or '/') + (('?' + parts.query) if parts.query else '')
            else:
                hostheader = _get_header(headers, 'host')
                if not hostheader:
                    _send_status(client, 400, 'Bad Request')
                    return
                host, port = _split_host_port(hostheader, 80)
                path = target

            ip = resolve(host)
            if not ip:
                _log(f"Falha DNS para {host} ({method} de {addr[0]})")
                _send_status(client, 502, 'Bad Gateway')
                return
            upstream = _connect(ip, port)

            # Reescreve a linha de requisição (URL absoluta -> caminho) e
            # remove Proxy-Connection, que não deve chegar ao destino.
            lines = [f'{method} {path} {version}']
            lines += [h for h in headers if not h.lower().startswith('proxy-connection:')]
            request = ('\r\n'.join(lines) + '\r\n\r\n').encode('latin-1') + rest
            upstream.sendall(request)

        _tunnel(client, upstream)

    except socket.timeout:
        _log(f"Timeout com {addr[0]}")
        _send_status(client, 504, 'Gateway Timeout')
    except ValueError as e:
        _log(f"Requisição inválida de {addr[0]}: {e}")
        _send_status(client, 400, 'Bad Request')
    except OSError as e:
        _log(f"Erro de conexão ({addr[0]}): {e}", debug=True)
        _send_status(client, 502, 'Bad Gateway')
    except Exception as e:
        _log(f"Erro inesperado ({addr[0]}): {e}")
    finally:
        for s in (upstream, client):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


def _worker(client, addr):
    try:
        _handle_client(client, addr)
    finally:
        _slots.release()


# --- Servidor --------------------------------------------------------------

def _should_stop(monitor, stop_event):
    if stop_event is not None and stop_event.is_set():
        return True
    if monitor is not None:
        try:
            return bool(monitor.abortRequested())
        except Exception:
            return False
    return False


def main(monitor=None, stop_event=None):
    """Sobe o proxy. Retorna quando o Kodi pedir encerramento (monitor)
    ou quando stop_event for setado. Feito para ser chamado pelo service.py."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, PORT))
    except OSError as e:
        # Porta já ocupada = outro processo do addon já é o proxy. Não é erro.
        if e.errno == errno.EADDRINUSE:
            _log(f"Proxy já ativo em {HOST}:{PORT} (outro processo).", debug=True)
        else:
            _log(f"Não foi possível escutar em {HOST}:{PORT}: {e}")
        server.close()
        return
    server.listen(64)
    server.settimeout(1.0)
    _log(f"Proxy DoH ativo em {HOST}:{PORT}")

    try:
        while not _should_stop(monitor, stop_event):
            try:
                client, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not _slots.acquire(blocking=False):
                _send_status(client, 503, 'Service Unavailable')
                client.close()
                continue
            threading.Thread(target=_worker, args=(client, addr), daemon=True).start()
    finally:
        server.close()
        _log("Proxy encerrado.")


_bg_lock = threading.Lock()
_bg_started = False


# --- Ajuste global do requests: manda as saídas dos players pelo proxy ---
# Fallback: se o proxy falhar, a requisição vai direto e o proxy fica de
# fora por SHIM_RETRY_SECONDS, para o canal não travar.
SHIM_RETRY_SECONDS = 30
_PROXY_URL = f'http://{HOST}:{PORT}'
_NO_PROXY_HOSTS = ('localhost', 'cloudflare-dns.com', 'dns.google')
_shim_down_until = 0.0
_shim_lock = threading.Lock()


def _shim_should_proxy(url):
    try:
        from urllib.parse import urlsplit
        host = (urlsplit(url).hostname or '').lower()
    except Exception:
        return False
    if not host or host in _NO_PROXY_HOSTS:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
    except ValueError:
        pass
    return True


def _install_requests_shim():
    try:
        import requests
        from requests import exceptions as rexc
    except ImportError:
        return
    if getattr(requests.Session, '_tvfogo_proxy_shim', False):
        return
    original = requests.Session.request

    def request(self, method, url, *args, **kwargs):
        global _shim_down_until
        use_proxy = (
            'proxies' not in kwargs
            and _shim_should_proxy(url)
            and time.monotonic() >= _shim_down_until
        )
        if not use_proxy:
            return original(self, method, url, *args, **kwargs)
        kwargs['proxies'] = {'http': _PROXY_URL, 'https': _PROXY_URL}
        try:
            return original(self, method, url, *args, **kwargs)
        except rexc.ReadTimeout:
            raise
        except (rexc.ProxyError, rexc.ConnectionError) as e:
            with _shim_lock:
                _shim_down_until = time.monotonic() + SHIM_RETRY_SECONDS
            _log(f"Proxy indisponível ({e}); usando conexão direta por {SHIM_RETRY_SECONDS}s.")
            kwargs['proxies'] = {}
            return original(self, method, url, *args, **kwargs)

    request._tvfogo_proxy_shim = True
    requests.Session.request = request
    requests.Session._tvfogo_proxy_shim = True


def start_background(monitor=None):
    """Sobe o proxy em uma thread daemon e instala o ajuste do requests.
    Idempotente: só inicia uma vez por processo, mesmo que service.py e
    customdns.py chamem."""
    global _bg_started
    with _bg_lock:
        if _bg_started:
            return
        _bg_started = True
    _install_requests_shim()
    threading.Thread(target=main, kwargs={'monitor': monitor}, name='proxy-doh', daemon=True).start()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
