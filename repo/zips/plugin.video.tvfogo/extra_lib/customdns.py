# -*- coding: utf-8 -*-
#
# Servidor Proxy HTTP/HTTPS com Resolução DNS-over-HTTPS (DoH) via Cloudflare
#
# Este script usa o protocolo HTTP/HTTPS e resolve nomes de domínio através do
# serviço DoH da Cloudflare (https://cloudflare-dns.com/dns-query), que é
# altamente confiável e rápido, resolvendo problemas de timeout.
#
# Compatível com Kodi 19 (Python 3.8), 20 e 21.3.
# Dependência: requests (script.module.requests, já declarado no addon.xml).
# Execução: python3 proxy.py
#
# DEBUG HABILITADO PARA RASTREAR QUEDAS DE CONEXÃO.

import socket
import threading
import sys
import os
try:
    import requests # Disponível no Kodi via script.module.requests
except ImportError:
    requests = None
import json
import struct
import select # Para controle de timeout no socket
import ipaddress
from datetime import datetime

# --- Configurações do Proxy HTTP/HTTPS (Estritamente IPv4) ---
HOST = '127.0.0.1'
PORT = 1080  # Porta padrão para o proxy
BUFFER_SIZE = 65536 # Aumentado para 64KB para otimizar streams contínuos (como IPTV)
CUSTOM_DNS_CLOUDFLARE = 'https://cloudflare-dns.com/dns-query'
CUSTOM_DNS_GOOGLE = 'https://dns.google/resolve'

# Timeout de 3.5 segundos para o DoH (evita travamentos na reprodução de canais)
DOH_TIMEOUT = 3.5

def _is_ipv4(ip_str):
    try:
        val = str(ip_str).strip()
        if ':' in val:
            return False
        parts = val.split('.')
        return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
    except Exception:
        return False

def is_private_host(host):
    """Verificação refinada de hosts locais/privados para evitar gargalos em requisições internas."""
    if not host:
        return True
    if host in ("localhost", "127.0.0.1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return (
            ip.is_private or
            ip.is_loopback or
            ip.is_link_local
        )
    except ValueError:
        return False

def log(message):
    """Log com timestamp. Dentro do Kodi vai para o kodi.log com o
    prefixo [customdns]; fora do Kodi cai no print normal."""
    line = f"[customdns] [{datetime.now().strftime('%H:%M:%S')}] {message}"
    try:
        import xbmc
        level = getattr(xbmc, 'LOGINFO', 1) # 1 = LOGINFO
        xbmc.log(line, level)
    except Exception:
        print(line)

def _query_doh_endpoint(url, domain):
    headers = {'Accept': 'application/dns-json'}
    params = {'name': domain, 'type': 'A'}
    if requests is not None:
        response = requests.get(url, headers=headers, params=params, timeout=DOH_TIMEOUT)
        if response.status_code == 200:
            return response.json()
    else:
        from urllib.parse import urlencode
        try:
            from urllib.request import Request, urlopen
        except ImportError:
            from urllib2 import Request, urlopen
        full_url = url + '?' + urlencode(params)
        req = Request(full_url, headers=headers)
        response = urlopen(req, timeout=DOH_TIMEOUT)
        return json.loads(response.read().decode('utf-8'))
    return None

def resolve_via_doh(domain):
    """Resolve o nome de domínio usando DNS-over-HTTPS (Cloudflare com fallback Google).
    Retorna estritamente endereço IPv4.
    """
    if is_private_host(domain):
        return domain

    log(f"[DOH INÍCIO] Tentando resolver: {domain}")
    # 1. Provedor Primário: Cloudflare
    try:
        data = _query_doh_endpoint(CUSTOM_DNS_CLOUDFLARE, domain)
        if data and data.get('Status') == 0 and 'Answer' in data:
            for record in data['Answer']:
                if record.get('type') == 1: # Tipo 1 é registro A (IPv4)
                    ip = str(record.get('data', '')).strip()
                    if _is_ipv4(ip):
                        log(f"[DOH OK (Cloudflare)] {domain} -> {ip}")
                        return ip
    except Exception as e:
        log(f"[DOH AVISO] Falha na Cloudflare para {domain}: {e}")

    # 2. Provedor Secundário (Fallback): Google
    try:
        data = _query_doh_endpoint(CUSTOM_DNS_GOOGLE, domain)
        if data and data.get('Status') == 0 and 'Answer' in data:
            for record in data['Answer']:
                if record.get('type') == 1: # Tipo 1 é registro A (IPv4)
                    ip = str(record.get('data', '')).strip()
                    if _is_ipv4(ip):
                        log(f"[DOH OK (Google)] {domain} -> {ip}")
                        return ip
    except Exception as e:
        log(f"[ERRO DOH] Falha no Google DoH para {domain}: {e}")

    log(f"[DOH FALHA] Resposta sem registro IPv4 (A) para {domain}.")
    return None

def handle_socks5_connection(client_socket, client_addr):
    """Lida com a requisição HTTP/HTTPS (CONNECT ou Proxy comum) e roteamento de dados."""
    dest_socket = None
    log(f"[HANDLER INÍCIO] Conexão de: {client_addr}")
    try:
        client_socket.settimeout(5) # Timeout curto para a leitura inicial
        
        # Leitura da requisição HTTP inicial
        request_data = client_socket.recv(BUFFER_SIZE)
        if not request_data:
            raise Exception("Requisição vazia.")
        
        request_str = request_data.decode('utf-8', errors='ignore')
        lines = request_str.split('\r\n')
        if not lines:
            raise Exception("Requisição HTTP malformada.")
        
        request_line = lines[0]
        log(f"[HTTP INICIAL] {request_line}")
        
        parts = request_line.split(' ')
        if len(parts) < 2:
            raise Exception("Linha de requisição HTTP inválida.")
        
        method = parts[0].upper()
        url = parts[1]
        
        dest_addr = None
        dest_port = 80

        if method == 'CONNECT':
            # Formato CONNECT host:port HTTP/1.1
            if ':' in url:
                host_port = url.split(':')
                domain = host_port[0]
                dest_port = int(host_port[1])
            else:
                domain = url
                dest_port = 443

            log(f"[DESTINO CONNECT] Domínio: {domain}:{dest_port}. Iniciando DoH.")
            dest_addr = resolve_via_doh(domain)
            
            if not dest_addr:
                log(f"[HTTP FALHA] Falha na resolução DOH para {domain}.")
                client_socket.sendall(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
                raise Exception(f"Falha na resolução DOH para {domain}.")

            # Conectar ao Destino HTTPS
            dest_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                dest_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                dest_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except Exception:
                pass

            dest_socket.settimeout(20)
            log(f"[CONECTANDO] Tentando conexão com {dest_addr}:{dest_port}")
            dest_socket.connect((dest_addr, dest_port))
            log(f"[CONECTADO SUCESSO] Conexão estabelecida com {dest_addr}:{dest_port}.")
            
            # Responde ao cliente informando que o túnel CONNECT foi estabelecido
            client_socket.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            log("[HANDSHAKE COMPLETO] Resposta HTTP 200 enviada ao cliente. Iniciando túnel.")

        else:
            # Requisição HTTP comum (GET, POST, etc.) com URL absoluta ou relativa
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            
            if parsed_url.netloc:
                host_port = parsed_url.netloc.split(':')
                domain = host_port[0]
                dest_port = int(host_port[1]) if len(host_port) > 1 else 80
                
                # Reconstrói o caminho relativo para enviar ao servidor de destino
                path = parsed_url.path or '/'
                if parsed_url.query:
                    path += '?' + parsed_url.query
                
                # Substitui a URL absoluta na linha de requisição por relativa
                lines[0] = f"{method} {path} {parts[2] if len(parts) > 2 else 'HTTP/1.1'}"
                new_request_data = ('\r\n'.join(lines)).encode('utf-8', errors='ignore') + (request_data[request_data.find(b'\r\n\r\n'):] if b'\r\n\r\n' in request_data else b'')
            else:
                # Caso venha cabeçalho Host separadamente
                domain = None
                for line in lines:
                    if line.lower().startswith('host:'):
                        domain = line.split(':', 1)[1].strip()
                        break
                if not domain:
                    raise Exception("Host não encontrado na requisição HTTP.")
                
                if ':' in domain:
                    host_port = domain.split(':')
                    domain = host_port[0]
                    dest_port = int(host_port[1])
                
                new_request_data = request_data

            log(f"[DESTINO HTTP] Domínio: {domain}:{dest_port}. Iniciando DoH.")
            dest_addr = resolve_via_doh(domain)
            
            if not dest_addr:
                log(f"[HTTP FALHA] Falha na resolução DOH para {domain}.")
                client_socket.sendall(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
                raise Exception(f"Falha na resolução DOH para {domain}.")

            dest_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                dest_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                dest_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except Exception:
                pass

            dest_socket.settimeout(20)
            log(f"[CONECTANDO] Tentando conexão com {dest_addr}:{dest_port}")
            dest_socket.connect((dest_addr, dest_port))
            log(f"[CONECTADO SUCESSO] Conexão estabelecida com {dest_addr}:{dest_port}.")
            
            # Envia a requisição modificada para o destino
            dest_socket.sendall(new_request_data)

        # 4. Inicia o Túnel de Dados
        tunnel_data_transfer(client_socket, dest_socket, client_addr)

    except socket.timeout:
        log(f"[ERRO HANDLER] Timeout de socket durante a conexão com destino para {client_addr}.")
        try:
             client_socket.sendall(b'HTTP/1.1 504 Gateway Timeout\r\n\r\n')
        except:
             pass
    except ConnectionResetError:
        log(f"[ERRO HANDLER] Cliente {client_addr} resetou a conexão.")
    except Exception as e:
        log(f"[ERRO GERAL NO HANDLER] Falha para {client_addr}: {e}")
        try:
            client_socket.sendall(b'HTTP/1.1 500 Internal Server Error\r\n\r\n') 
        except:
            pass
    finally:
        client_socket.close()
        if dest_socket: dest_socket.close()
        log(f"[HANDLER FIM] Conexão encerrada para {client_addr}.")

def tunnel_data_transfer(source_socket, destination_socket, client_addr):
    """Transfere dados bidirecionalmente usando select com timeout."""
    TIMEOUT = 300 
    inputs = [source_socket, destination_socket]
    
    log(f"[TÚNEL INICIADO] Transferência de dados iniciada para {client_addr}. Timeout de inatividade: {TIMEOUT}s.") 
    
    while inputs:
        try:
            readable, _, exceptional = select.select(inputs, [], inputs, TIMEOUT)
        except Exception as e:
            log(f"[ERRO SELECT] Falha no select para {client_addr}: {e}") 
            break 
        
        if exceptional:
             log(f"[ERRO EXCEPCIONAL] Exceção em um socket para {client_addr}. Encerrando.")
             break

        if not readable:
            log(f"[TÚNEL TIMEOUT] Inatividade de {TIMEOUT}s atingida para {client_addr}. Encerrando o túnel.") 
            break

        for sock in readable:
            try:
                data = sock.recv(BUFFER_SIZE)
                
                if not data:
                    log(f"[TÚNEL FECHADO] Conexão encerrada pelo lado {'CLIENTE' if sock == source_socket else 'DESTINO'} para {client_addr}.") 
                    if sock in inputs: inputs.remove(sock)
                else:
                    if sock == source_socket:
                        destination_socket.sendall(data)
                    else:
                        source_socket.sendall(data)
            
            except ConnectionResetError:
                log(f"[ERRO DE DADOS] Conexão resetada pelo lado {'CLIENTE' if sock == source_socket else 'DESTINO'} para {client_addr}.") 
                inputs.clear()
                break
            
            except Exception as e:
                log(f"[ERRO DE DADOS GERAL] Falha na leitura/escrita de dados para {client_addr}: {e}") 
                inputs.clear()
                break
    
    log(f"[TÚNEL ENCERRADO] Fim da transferência de dados para {client_addr}.")


def main(monitor=None):
    """Inicializa e executa o servidor proxy HTTP/HTTPS principal."""
    server_socket = None
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, PORT))
        server_socket.listen(50) # Aumentado o backlog de conexões pendentes para estabilidade
        server_socket.settimeout(1.0)
        log(f"Servidor Proxy HTTP/HTTPS + DNS-over-HTTPS (DoH) Ativo em {HOST}:{PORT}")
        
        while True:
            if monitor is not None and monitor.abortRequested():
                log("Kodi esta encerrando. Finalizando o proxy HTTP/HTTPS.")
                break
            try:
                client_socket, addr = server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            log(f"[NOVA CONEXÃO] Aceita de {addr[0]}:{addr[1]}")
            client_handler = threading.Thread(target=handle_socks5_connection, args=(client_socket, addr))
            client_handler.daemon = True
            client_handler.start()

    except KeyboardInterrupt:
        log("Servidor encerrado por comando do usuário.")
    except Exception as e:
        log(f"Erro Fatal no Servidor Principal: {e}")
    finally:
        if server_socket is not None:
            try:
                server_socket.close()
            except Exception:
                pass
        log("Servidor Proxy HTTP/HTTPS encerrado.")

if __name__ == '__main__':
    main()