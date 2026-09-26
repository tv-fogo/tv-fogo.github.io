# -*- coding: utf-8 -*-
import socket
import threading
import urllib.parse
import urllib.request
import select
import json
import xbmc
import logging
import os
import ipaddress


LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 11489
DOH_URL = "https://cloudflare-dns.com/dns-query"
TIMEOUT = 15

os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def is_private_host(host):
    if not host:
        return True

    if host in ("localhost",):
        return True

    try:
        ip = ipaddress.ip_address(host)
        return (
            ip.is_private or
            ip.is_loopback or
            ip.is_link_local
        )
    except ValueError:
        # não é IP → é domínio público
        return False


# =====================================================
# DNS over HTTPS (urllib)
# =====================================================

def doh_resolve(host):
    if not host or host.replace(".", "").isdigit():
        return None

    try:
        url = f"{DOH_URL}?name={host}&type=A"
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/dns-json"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())

        return [a["data"] for a in data.get("Answer", []) if a["type"] == 1]
    except:
        return None

def connect_doh(host, port):
    # NÃO interferir em proxies locais (Brazuca, Kodi, etc)
    if is_private_host(host):
        logging.info(f"[DIRECT CONNECT] {host}:{port}")
        return socket.create_connection((host, port), timeout=TIMEOUT)

    # Host público → DoH
    ips = doh_resolve(host)
    if ips:
        for ip in ips:
            try:
                logging.info(f"[DoH CONNECT] {host} → {ip}:{port}")
                return socket.create_connection((ip, port), timeout=TIMEOUT)
            except:
                pass

    # fallback
    logging.info(f"[FALLBACK CONNECT] {host}:{port}")
    return socket.create_connection((host, port), timeout=TIMEOUT)       

# =====================================================
# HTTPS CONNECT (túnel puro)
# =====================================================

def tunnel(a, b):
    sockets = [a, b]
    while True:
        r, _, _ = select.select(sockets, [], [], TIMEOUT)
        if not r:
            return
        for s in r:
            data = s.recv(65536)
            if not data:
                return
            (b if s is a else a).sendall(data)

def handle_connect(client, host, port):
    try:
        remote = connect_doh(host, port)
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        tunnel(client, remote)
    except Exception as e:
        logging.error(e)

# =====================================================
# HTTP
# =====================================================

def handle_http(client, request):
    try:
        first = request.decode(errors="ignore").split("\r\n")[0]
        req_text = request.decode(errors="ignore")
        ua_requests = "python-requests" in req_text.lower()
        method, url, _ = first.split(" ", 2)                   

        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname
        port = parsed.port or 80

        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query


        # SE FOR HOST LOCAL → TÚNEL PURO (SEM TOCAR EM NADA)
        if is_private_host(host):
            logging.info(f"[BYPASS LOCAL PROXY] {host}:{port}")
            remote = socket.create_connection((host, port), timeout=TIMEOUT)
            remote.sendall(request)
            tunnel(client, remote)            
            return        

        logging.info(f"[HTTP TUNNEL] {host}:{port}")

        remote = connect_doh(host, port)

        if not is_private_host(host):
            req = request.decode(errors="ignore")
            lines = req.split("\r\n")

            method, url, proto = lines[0].split(" ", 2)            
            # REESCREVE APENAS A PRIMEIRA LINHA
            lines[0] = f"{method} {path} {proto}"

            new_headers = []
            has_host = False
            for line in lines[1:]:
                if not line:
                    break
                if line.lower().startswith("host:"):
                    has_host = True
                    new_headers.append(f"Host: {host}")
                elif line.lower().startswith("connection:"):
                    new_headers.append("Connection: close")
                elif line.lower().startswith("proxy-connection:"):
                    continue
                else:
                    new_headers.append(line)

            if not has_host:
                new_headers.insert(0, f"Host: {host}")

            new_headers.append("Connection: close")

            new_req = (
                lines[0] + "\r\n" +
                "\r\n".join(new_headers) +
                "\r\n\r\n"
            )
            logging.info(f"[HTTP TUNNEL request ip publico]: {new_req.encode()}")
            remote.sendall(new_req.encode())
        else:
            logging.info(f"[HTTP TUNNEL request ip local]: {new_req.encode()}")      
            remote.sendall(request)


        # 🔥 STREAM CONTÍNUO (m3u8 precisa disso)
        while True:
            data = remote.recv(65536)
            if not data:
                break
            client.sendall(data)

        remote.close()        

    except Exception as e:
        logging.error(e)






# =====================================================
# Client handler
# =====================================================

def handle_client(client):
    try:
        data = client.recv(65536)
        if not data:
            return

        first = data.decode(errors="ignore").split("\r\n")[0]

        if first.startswith("CONNECT"):
            _, target, _ = first.split()
            host, port = target.split(":")
            handle_connect(client, host, int(port))
        else:
            handle_http(client, data)

    except Exception as e:
        logging.error(e)
    finally:
        client.close()

# =====================================================
# Server (Kodi service)
# =====================================================

def server(monitor=None):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((LISTEN_HOST, LISTEN_PORT))
    sock.listen(50)
    sock.settimeout(1.0)

    logging.info(f"[PROXY] ativo em {LISTEN_HOST}:{LISTEN_PORT}")

    if monitor is None:
        monitor = xbmc.Monitor()
    while not monitor.abortRequested():
        try:
            client, addr = sock.accept()
            logging.info(f"[CLOUDLFARE DNS - CLIENT] {addr}")
            threading.Thread(
                target=handle_client,
                args=(client,),
                daemon=True
            ).start()

        except socket.timeout:
            # timeout normal → volta pro while e checa abortRequested
            continue
        except Exception as e:
            logging.error(f"[SERVER ERROR] {e}")
            break

    logging.info("[PROXY] encerrando...")
    sock.close()