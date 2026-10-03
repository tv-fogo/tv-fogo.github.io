# -*- coding: utf-8 -*-
import socket
import threading
import time
import six
if six.PY3:
    from urllib.parse import urlparse, urljoin, parse_qs, quote, unquote, unquote_plus, quote_plus
else:
    from urlparse import urlparse, urljoin, parse_qs
    from urllib import quote, unquote, unquote_plus, quote_plus, quote
try:
    from .helper import os, notify, log as log2
except ImportError:
    try:
        from helper import os, notify, log as log2
    except ImportError:
        import os
        def notify(*args, **kwargs):
            return None
        def log2(msg):
            return None
# try:
#     from resources.modules.helper import monitor_acesso
# except:
#     def monitor_acesso():
#         return True
import re
import requests
import logging
import base64
import random
try:
    from extra_lib.dnscompat import DNSOverride
except:
    from dnscompat import DNSOverride
try:
    from extra_lib.secureurl import patch_requests as _patch_requests_https
except:
    from secureurl import patch_requests as _patch_requests_https
_patch_requests_https()
DNSOverride()
logger = logging.getLogger(__name__)

# Session criada DEPOIS do patch do secureurl, para herdar o que ele alterar
SESSION = requests.Session()

def reset_session():
    """Descarta cookies/conexoes da sessao anterior e cria uma nova."""
    global SESSION
    try:
        SESSION.close()
    except:
        pass
    SESSION = requests.Session()

def http_get(url, **kwargs):
    """GET usando a Session. Se der erro de SSL, tenta o requests.get normal
    (que passa pelo patch do secureurl)."""
    try:
        return SESSION.get(url, **kwargs)
    except requests.exceptions.SSLError:
        return requests.get(url, **kwargs)

def http_head(url, **kwargs):
    """HEAD usando a Session, com a mesma protecao de SSL."""
    try:
        return SESSION.head(url, **kwargs)
    except requests.exceptions.SSLError:
        return requests.head(url, **kwargs)

# habilita ou desabilita o uso de IP falso
# (desligado: IP falso diferente a cada requisicao quebra servidores com token)
USE_FAKE_IP = True

def get_local_ip():
    try:
        # Cria um socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        local_ip = s.getsockname()[0]
    except Exception as e:
        local_ip = '127.0.0.1'
    finally:
        try:
            s.close()
        except:
            pass
    return local_ip

def log(msg):
    try:
        log2('F4MTESTER: %s'%msg)
    except:    
        logger.info(msg)    

#HOST_NAME será alterado de acordo com o modo fake
if USE_FAKE_IP:
    # dentro do addon o proxy escuta apenas localhost, sem expor IP real
    HOST_NAME = '127.0.0.1'
else:
    HOST_NAME = get_local_ip()
PORT_NUMBER = 58500

url_proxy = 'http://'+HOST_NAME+':'+str(PORT_NUMBER)+'/?url='

global MAX_RETRY
global URL_BASE
global LAST_URL
global HEADERS_BASE
global STOP_SERVER
global CACHE_CHUNKS
global CACHE_M3U8
global DELAY_MODE
global RESOLUTION
global LAST_M3U8
global PARAMS
global URL_BASE_PARAMS
global CHECK_URL_PARAMS
global URL_BASE_STALKER
global TOKEN_STALKER
global FAKE_IP_SESSION
global LAST_CHANNEL
MAX_RETRY = 28
DELAY_MODE = True
URL_BASE = ''
URL_BASE_PARAMS = ''
LAST_URL = ''
HEADERS_BASE = {}
STOP_SERVER = False
CACHE_CHUNKS = []
CACHE_M3U8 = ''
RESOLUTION = True
LAST_M3U8 = ''
PARAMS = ''
CHECK_URL_PARAMS = True
URL_BASE_STALKER = ''
TOKEN_STALKER = ''
NSPLAYER = False
FAKE_IP_SESSION = ''
LAST_CHANNEL = ''

# permite ativar/desativar sistema de IP falso
USE_FAKE_IP = True


def normalize_url(url):
    """Remove sufixos usados para forçar canal/segmento e deixa a URL limpo."""
    if not url:
        return url
    for sep in ('|', '%7C'):
        if sep in url:
            url = url.split(sep)[0]
    return url


def reset_channel_state():
    """Limpa o estado do canal atual sem afetar o restante do proxy."""
    global URL_BASE, LAST_URL, HEADERS_BASE, CACHE_CHUNKS, CACHE_M3U8, DELAY_MODE
    global RESOLUTION, LAST_M3U8, PARAMS, URL_BASE_PARAMS, CHECK_URL_PARAMS
    global URL_BASE_STALKER, TOKEN_STALKER, FAKE_IP_SESSION, LAST_CHANNEL

    URL_BASE = ''
    LAST_URL = ''
    HEADERS_BASE = {}
    CACHE_CHUNKS = []
    CACHE_M3U8 = ''
    DELAY_MODE = True
    RESOLUTION = True
    LAST_M3U8 = ''
    PARAMS = ''
    URL_BASE_PARAMS = ''
    CHECK_URL_PARAMS = True
    URL_BASE_STALKER = ''
    TOKEN_STALKER = ''
    FAKE_IP_SESSION = ''
    LAST_CHANNEL = ''


# função para gerar IP aleatório (rede privada, imitando brasileira)
# já existia gerar_ip_brasileiro, mas expomos para facilitar uso

def get_fake_ip():
    """Retorna um IP aleatório da faixa privada (padrão usado como fake).
    O mesmo IP é mantido durante toda a sessão (até o /reset)."""
    global FAKE_IP_SESSION
    if not FAKE_IP_SESSION:
        FAKE_IP_SESSION = gerar_ip_brasileiro()  # mantém compatibilidade
    return FAKE_IP_SESSION


def gerar_ip_brasileiro():
    ranges = [
        (167772160, 184549375),   # 10.0.0.0 – 10.255.255.255
        (1879048192, 1884162559), # 112.0.0.0 – 112.63.255.255
        (2896692480, 2896702975), # 172.16.0.0 – 172.31.255.255
        (3232235520, 3232301055)  # 192.168.0.0 – 192.168.255.255
    ]

    faixa = random.choice(ranges)
    ip_numerico = random.randint(faixa[0], faixa[1])

    ip = ".".join([str((ip_numerico >> (i * 8)) & 0xFF) for i in range(4)[::-1]])
    return ip

class XtreamCodes:
    def update_headers(self):
        global HEADERS_BASE
        global NSPLAYER
        global USE_FAKE_IP
        # cópia do dicionário global: antes alterava HEADERS_BASE direto,
        # que é compartilhado entre as threads do proxy
        header = dict(HEADERS_BASE)
        # User-Agent fixo da sessão: o que veio na URL (se houver) ou o padrão.
        # Antes era sobrescrito a cada requisição.
        header.setdefault('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36')
        # cabeçalhos padrão básicos
        header.update({'Accept-Encoding': 'gzip, deflate', 'Accept': '*/*', 'Connection': 'keep-alive'})
        # se habilitado, adiciona IP falso em vários campos comuns
        if USE_FAKE_IP:
            fake_ip = get_fake_ip()
            header.update({'X-Forwarded-For': fake_ip, 'Client-IP': fake_ip, 'X-Real-IP': fake_ip})
        if NSPLAYER == True:
            # antes: User-Agent aleatório (binascii.b2a_hex(os.urandom(20))[:32])
            # a cada falha, o que fazia o servidor ver aparelhos diferentes.
            # Agora mantém o mesmo User-Agent da sessão.
            pass
        return header


    def basename(self,p):
        """Returns the final component of a pathname"""
        i = p.rfind('/') + 1
        return p[i:]
    
    def convert_to_m3u8(self,url):
        url = normalize_url(url)
        if urlparse(url).path.lower().endswith('.ts'):
            return url
        if not '.m3u8' in url and not '/hl' in url and int(url.count("/")) > 4 and not '.mp4' in url and not '.avi' in url:
            parsed_url = urlparse(url)
            try:
                host_part1 = '%s://%s'%(parsed_url.scheme,parsed_url.netloc)
                host_part2 = url.split(host_part1)[1]
                if not host_part2.startswith('/live/'):
                    host_part2 = '/live' + host_part2
                url = host_part1 + host_part2
                url = url + '.m3u8'
            except:
                pass
        return url 

    def set_headers(self,url):
        global URL_BASE
        global HEADERS_BASE        
        headers_default = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36', 'Accept-Encoding': 'gzip, deflate','Connection': 'keep-alive'}
        headers = {}
        if 'User-Agent' in url:
            try:
                user_agent = url.split('User-Agent=')[1]
                try:
                    user_agent = user_agent.split('&')[0]
                except:
                    pass
                try:
                    user_agent = unquote_plus(user_agent)
                except:
                    pass
                try:
                    user_agent = unquote(user_agent)
                except:
                    pass
                if 'Mozilla' in user_agent:
                    headers['User-Agent'] = user_agent
            except:
                pass
        if 'Referer' in url:
            try:
                referer = url.split('Referer=')[1]
                try:
                    referer = referer.split('&')[0]
                except:
                    pass
                try:
                    referer = unquote_plus(referer)
                except:
                    pass
                try:
                    referer = unquote(referer)
                except:
                    pass                
                headers['Referer'] = referer
            except:
                pass
        if 'Origin' in url:
            try:
                origin = url.split('Origin=')[1]
                try:
                    origin = origin.split('&')[0]
                except:
                    pass
                try:
                    origin = unquote_plus(origin)
                except:
                    pass
                try:
                    origin = unquote(origin)
                except:
                    pass                
                headers['Origin'] = origin
            except:
                pass
        #HEADERS_ = headers if headers else headers_default
        if headers != {}:
            headers.update({'Connection': 'keep-alive'})
            HEADERS_ = headers
        else:
            HEADERS_ = headers_default
        if HEADERS_BASE == {}:
            HEADERS_BASE = HEADERS_

    def base_url(self,url):
        global HEADERS_BASE
        global PARAMS
        header_ = self.update_headers()
        try:
            if not PARAMS:
                for i in range(7):
                    DNSOverride()
                    r = http_get(url,headers=header_, timeout=3, verify=True)
                    if r.status_code == 200:
                        url = r.url
                        # antes não parava aqui e repetia o mesmo GET 7 vezes
                        # (gastando conexões do login)
                        break
                    else:
                        break
        except:
            pass
        filename = url.split('/')[-1]
        if not '.m3u8' in filename:
            url = url.split('?')[0]
            filename = url.split('/')[-1]
            url = url.split(filename)[0]
        else:
            url = url.replace(filename, '')
        return url

    def base_url_params(self,url):
        global HEADERS_BASE
        header_ = self.update_headers()
        try:
            for i in range(7):
                DNSOverride()
                r = http_get(url,headers=header_, timeout=3, verify=True)
                if r.status_code == 200:
                    url = r.url
                    break
        except:
            pass
        filename = url.split('/')[-1]
        if not '.m3u8' in filename:
            url = url.split('?')[0]
            filename = url.split('/')[-1]
            url = url.split(filename)[0]
        else:
            url = url.replace(filename, '')
        return url

    def get_filename_params(self,url):
        if '.m3u8' in url:
            try:
                filename = url.split('.m3u8')[0].split('/')[-1] + '.m3u8'
                url = filename + url.split(filename)[1]
            except:
                pass
        return url

    def check_url_params(self,url):
        global URL_BASE_PARAMS
        global HEADERS_BASE
        global CHECK_URL_PARAMS
        baseurl = url
        if URL_BASE_PARAMS:
            url = URL_BASE_PARAMS + self.get_filename_params(url)
            if '.m3u8' in url and CHECK_URL_PARAMS:
                try:
                    header_ = self.update_headers()
                    DNSOverride()
                    r = http_get(url,headers=header_,timeout=3,verify=True)
                    if r.status_code == 200:
                        CHECK_URL_PARAMS = False
                        return url
                except:
                    pass
        return baseurl

    def make_m3u8(self,m3u):
        padrao = r'#EXTINF:\d+\.\d+,\n/hl.+?/[^/]+\d+\.ts\?[^#]+'
        padrao2 = r'#EXTINF:\d+\.\d+,\n/hl.+?/[^/]+\d+\.ts'
        resultados = re.findall(padrao, m3u)
        if not resultados:
            resultados = re.findall(padrao2, m3u)
        if resultados:
            base_m3u = m3u.split('#EXTINF')[0]
            duas_ultimas_linhas = resultados[-1:]
            for linha in duas_ultimas_linhas:
                base_m3u += linha
            m3u = base_m3u
        return m3u

    def magical_hls(self,url):
        global DELAY_MODE
        if '/hl' in url and not 'https' in url:
            segment = re.findall('ls/(.*?).ts', url)
            segment2 = re.findall('/(.*?).ts',url)
            if segment and DELAY_MODE:
                try:
                    s = segment[0]
                    file, part = s.split('_')
                    part = int(part) - 1
                    new_s = file + '_' + str(part)
                    url = url.replace(s, new_s)
                except:
                    pass
            elif segment2 and DELAY_MODE:
                try:
                    s = segment2[0]
                    file, part = s.split('_')
                    part = int(part) - 1
                    new_s = file + '_' + str(part)
                    url = url.replace(s, new_s)
                except:
                    pass            
                
        return url

    def get_max_m3u8(self,src):
        return self.get_max_m3u8_url(src, URL_BASE)

    def get_max_m3u8_url(self,src,base_url):
        variants = []
        lines = src.splitlines()
        for index, line in enumerate(lines[:-1]):
            match = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
            if not match:
                continue
            variant_uri = lines[index + 1].strip()
            if not variant_uri or variant_uri.startswith('#'):
                continue
            resolution = (int(match.group(1)), int(match.group(2)))
            variants.append((resolution, variant_uri))
        if not variants:
            return ''
        _, variant_uri = max(variants, key=lambda variant: variant[0])
        return urljoin(base_url, variant_uri)

    def proxy_m3u8(self,src,playlist_url):
        proxy_prefix = 'http://%s:%s/?url=' % (HOST_NAME, PORT_NUMBER)

        def proxied_url(uri):
            uri = uri.strip()
            if not uri:
                return uri
            resolved = urljoin(playlist_url, uri)
            if urlparse(resolved).scheme not in ('http', 'https'):
                return uri
            return proxy_prefix + quote(resolved, safe='') + '&hls=1'

        rewritten = []
        uri_attribute = re.compile(r"URI=(['\"])(.*?)\1", re.IGNORECASE)
        for line in src.splitlines(True):
            content = line.rstrip('\\r\\n')
            ending = line[len(content):]
            stripped = content.strip()
            if stripped.startswith('#'):
                content = uri_attribute.sub(
                    lambda match: 'URI=%s%s%s' % (
                        match.group(1), proxied_url(match.group(2)), match.group(1)
                    ),
                    content
                )
            elif stripped:
                leading = content[:len(content) - len(content.lstrip())]
                trailing = content[len(content.rstrip()):]
                content = leading + proxied_url(stripped) + trailing
            rewritten.append(content + ending)
        return ''.join(rewritten)

    # funcao m3u8 principal
    def send_m3u8(self,self_server,url):
        global MAX_RETRY
        global URL_BASE
        global LAST_URL
        global HEADERS_BASE
        global STOP_SERVER
        global CACHE_CHUNKS
        global CACHE_M3U8
        global DELAY_MODE
        global RESOLUTION
        global LAST_M3U8
        global PARAMS
        global URL_BASE_PARAMS
        global CHECK_URL_PARAMS
        global NSPLAYER
        url = normalize_url(url)
        if '.m3u8' in url or '.php' in url:
            self_server.send_header('Content-Type', 'application/x-mpegURL')
            self_server.end_headers() 
            URL_PLAY = url            
            if not URL_BASE:
                URL_BASE = self.base_url(url)
                LAST_URL = url
            elif URL_BASE:
                if 'http' in url:
                    last_parse = urlparse(LAST_URL)
                    last_host = '%s://%s'%(last_parse.scheme,last_parse.netloc)
                    url_parse = urlparse(url)
                    url_host = '%s://%s'%(url_parse.scheme,url_parse.netloc)
                    if last_host != url_host:
                        URL_BASE = self.base_url(url)
            if not 'http' in url:
                if url.startswith('/'):
                    url = url[1:]
                log('URL DO NO HTTP: %s'%url)
                # verificar param             
                #url = URL_BASE + url
            if PARAMS and not '?' in url:
                url = url + PARAMS
                log('URL DO PARAMS: %s'%url)
            if not URL_BASE_PARAMS and '?' in url:
                URL_BASE_PARAMS = self.base_url_params(url)
            if URL_BASE_PARAMS:
                url = self.check_url_params(url)
                log('URL DO BASE PARAMS: %s'%url)
            for i in range(MAX_RETRY):
                count = i + 1
                if STOP_SERVER:
                    break
                # if count == MAX_RETRY - 4:
                #     notify('Canal ruim, tente outro canal ou lista')
                header_ = self.update_headers()
                if RESOLUTION and not self_server.is_hls_resource:
                    try:                         
                        DNSOverride()
                        r = http_get(url,headers=header_, allow_redirects=True, timeout=4, verify=True)
                        code = r.status_code
                        log('Status Code: %s'%str(code))
                        if code == 200:
                            src = r.text
                            if '.m3u8' in src and 'RESOLUTION' in src:
                                url = self.get_max_m3u8_url(src, r.url)
                                LAST_M3U8 = url
                    except:
                        pass
                    RESOLUTION = False
                if LAST_M3U8 and not self_server.is_hls_resource:
                    url = LAST_M3U8
                if PARAMS and not '?' in url:
                    url = url + PARAMS
                try:
                    DNSOverride()
                    r = http_get(url,headers=header_, allow_redirects=True, timeout=6, verify=True)
                    code = r.status_code
                    log('Status Code: %s'%str(code))
                    
                    if code == 200:
                        NSPLAYER = False
                        src = r.text
                        if not src.lstrip('\ufeff \r\n').startswith('#EXTM3U'):
                            logger.warning(
                                'Resposta HTTP 200 nao contem uma playlist HLS valida'
                            )
                        src = self.proxy_m3u8(src, r.url)
                        if '/live/' in url and url.count('/') == 6:
                            try:
                                CACHE_M3U8 = self.make_m3u8(src)
                            except:
                                pass
                        src = src.encode('utf-8') #if six.PY3 else src
                        self_server.conn.sendall(src)
                        break
                    else:
                        NSPLAYER = True
                        if count == 1:
                            logger.warning(
                                'Servidor da playlist HLS respondeu HTTP %s', code
                            )
                        if '/live/' in url and url.count('/') == 6 and CACHE_M3U8:
                            src = CACHE_M3U8
                            src = src.encode('utf-8') #if six.PY3 else src
                            self_server.conn.sendall(src)
                            break
                        # pausa antes de tentar de novo (não martela o servidor)
                        time.sleep(0.5)
                except requests.exceptions.RequestException as exc:
                    if count in (1, MAX_RETRY):
                        logger.warning(
                            'Falha na requisicao da playlist HLS, tentativa %s/%s (%s)',
                            count, MAX_RETRY, type(exc).__name__
                        )
                    time.sleep(0.5)

    def send_ts(self,self_server,url):
        global MAX_RETRY
        global URL_BASE
        global LAST_URL
        global HEADERS_BASE
        global STOP_SERVER
        global CACHE_CHUNKS
        global CACHE_M3U8
        global DELAY_MODE
        global RESOLUTION
        global LAST_M3U8
        global PARAMS
        global URL_BASE_PARAMS
        global CHECK_URL_PARAMS
        if '.ts' in url or ('/hl' in url and '.ts' not in url):
            self_server.send_header('Content-type','video/mp2t')
            self_server.end_headers()            
            if url.startswith('/') and not '/hl' in url:
                url = url[1:]
                ts = URL_BASE + url
            elif url.startswith('/'):
                url = url[1:]
                if 'https' in URL_BASE:
                    ts = 'https://' + URL_BASE.split('/')[2] + '/' + url
                else:
                    ts = 'http://' + URL_BASE.split('/')[2] + '/' + url
            else:
                ts = url
            sent_any = False
            for i in range(MAX_RETRY):
                count = i + 1
                if STOP_SERVER:
                    break              
                # if count == MAX_RETRY - 4:
                #     notify('Canal ruim, tente outro canal ou lista')
                client_gone = False
                r = None
                try:
                    header_ = self.update_headers()
                    DNSOverride()
                    r = http_get(ts, headers=header_, allow_redirects=True, stream=True, verify=True, timeout=(5, 15))
                    code = r.status_code
                    log('Status Code: %s'%str(code))
                    if code == 200:
                        CACHE_CHUNKS = []
                        for chunk in r.iter_content(50*1024):                      
                            try:
                                self_server.conn.sendall(chunk)
                                sent_any = True
                                CACHE_CHUNKS.append(chunk)
                            except:
                                # o player fechou a conexão: para de baixar
                                client_gone = True
                                break
                        break
                    else:
                        if i == 0:
                            DELAY_MODE = False
                        # antes reenviava CACHE_CHUNKS[-1] aqui, o que repetia
                        # dados no meio do video e corrompia a imagem.
                        # Agora apenas espera um pouco e tenta o segmento de novo.
                        time.sleep(0.5)

                except requests.exceptions.RequestException as exc:
                    # se já enviou parte do segmento, repetir duplicaria dados
                    if sent_any:
                        break
                    if count == MAX_RETRY:
                        log('Falha ao carregar segmento (%s)' % type(exc).__name__)
                    time.sleep(0.5)
                finally:
                    if r is not None:
                        try:
                            r.close()
                        except:
                            pass
                if client_gone:
                    break

    def parse_url(self,url):
        parsed_url = urlparse(url)
        scheme = parsed_url.scheme
        host = parsed_url.hostname
        port = parsed_url.port
    
        return scheme, host, port    

    def send_m3u8_stalker(self,self_server,url):
        global URL_BASE_STALKER
        global TOKEN_STALKER
        global NSPLAYER
        global CACHE_M3U8
        if 'm3u8' in url:
            self_server.send_header('Content-Type', 'application/x-mpegURL')
            self_server.end_headers()                       
            if not URL_BASE_STALKER:
                header_ = self.update_headers()
                try:
                    header_ = self.update_headers()
                    DNSOverride()
                    r = http_get(url,headers=header_, allow_redirects=True, timeout=4, verify=True)
                    url = r.url
                except:
                    pass
                scheme, host, port = self.parse_url(url)
                if port:
                    URL_BASE_STALKER = scheme + '://' + host + ':' + str(port)
                else:
                    URL_BASE_STALKER = scheme + '://' + host
        if not TOKEN_STALKER:
            if '?' in url:
                try:
                    TOKEN_STALKER = url.split('?')[1]
                except:
                    pass
        if 'm3u8' in url:
            for i in range(MAX_RETRY):
                count = i + 1
                if STOP_SERVER:
                    break
                if count == MAX_RETRY - 4:
                    notify('Canal ruim, tente outro canal ou lista')
                try:
                    header_ = self.update_headers()
                    DNSOverride()
                    r = http_get(url,headers=header_, allow_redirects=True, timeout=4, verify=True)
                    code = r.status_code
                    log('Status Code: %s'%str(code))
                    if code == 200:
                        NSPLAYER = False
                        src = r.text
                        try:
                            CACHE_M3U8 = self.make_m3u8(src)
                        except:
                            pass
                        src = src.encode('utf-8') #if six.PY3 else src
                        self_server.conn.sendall(src)
                        break
                    else:
                        NSPLAYER = True
                        if CACHE_M3U8:
                            src = CACHE_M3U8
                            #src = response_headers + src
                            src = src.encode('utf-8') #if six.PY3 else src
                            self_server.conn.sendall(src)
                            break
                        time.sleep(0.5)
                        
                except requests.exceptions.RequestException as exc:
                    if count == MAX_RETRY:
                        log('Falha ao carregar playlist Stalker (%s)' % type(exc).__name__)
                    time.sleep(0.5)
                    
    
    def send_ts_stalker(self,self_server,url): 
        global MAX_RETRY
        global URL_BASE
        global LAST_URL
        global HEADERS_BASE
        global STOP_SERVER
        global CACHE_CHUNKS
        global CACHE_M3U8
        global DELAY_MODE
        global RESOLUTION
        global LAST_M3U8
        global PARAMS
        global URL_BASE_PARAMS
        global CHECK_URL_PARAMS 
        global URL_BASE_STALKER
        global TOKEN_STALKER
        if '.ts' in url and URL_BASE_STALKER:
            # if TOKEN_STALKER:
            #     ts = URL_BASE_STALKER + url + '?' + TOKEN_STALKER
            self_server.send_header('Content-Type', 'video/mp2t')
            self_server.end_headers()            
            ts = URL_BASE_STALKER + url
            sent_any = False
            for i in range(MAX_RETRY):
                count = i + 1
                if STOP_SERVER:
                    break        
                client_gone = False
                r = None
                try:
                    header_ = self.update_headers()
                    DNSOverride()
                    r = http_get(ts,headers=header_, allow_redirects=True, stream=True, verify=True, timeout=(5, 15))
                    code = r.status_code
                    log('Status Code: %s'%str(code))
                    if code == 200:
                        CACHE_CHUNKS = []
                        for chunk in r.iter_content(50*1024):                      
                            try:
                                self_server.conn.sendall(chunk)
                                sent_any = True
                                CACHE_CHUNKS.append(chunk)
                            except:
                                client_gone = True
                                break
                        break
                    else:
                        if i == 0:
                            DELAY_MODE = False
                        # não reenvia mais o último chunk (corrompia o video)
                        time.sleep(0.5)

                except requests.exceptions.RequestException as exc:
                    if sent_any:
                        break
                    if count == MAX_RETRY:
                        log('Falha ao carregar segmento Stalker (%s)' % type(exc).__name__)
                    time.sleep(0.5)
                finally:
                    if r is not None:
                        try:
                            r.close()
                        except:
                            pass
                if client_gone:
                    break


class ProxyHandler(XtreamCodes):
    def __init__(self, conn, addr, server):
        self.conn = conn
        self.addr = addr
        self.server = server
        self.path = ""
        self.request_method = ""
        self.is_hls_resource = False

    def parse_request(self, request):
        parts = request.split(b' ')
        if len(parts) >= 1:
            self.request_method = parts[0].decode()

    def parse_request2(self, request):
        parts = request.split(b' ')
        if len(parts) >= 2:
            self.path = parts[1].decode()

    def send_response(self, code, message=None):
        response = "HTTP/1.1 {} {}\r\n".format(code, message if message else "")
        self.conn.sendall(response.encode())

    def send_header(self, keyword, value):
        header = "{}: {}\r\n".format(keyword, value)
        self.conn.sendall(header.encode())

    def end_headers(self):
        self.conn.sendall(b"\r\n")

    def extract_header(self, request_data, header_name):
        header_lines = request_data.split(b'\r\n')
        for line in header_lines:
            if header_name in line:
                return line
        return None        

    def get_range(self, request_data, content_length):
        range_header = self.extract_header(request_data, b'Range:')
        if range_header:
            parts = range_header.split(b"-")
            start = int(parts[0].split(b'=')[-1])
            end = int(parts[1]) if parts[1] else content_length - 1
            return start, end
        else:
            return 0, content_length - 1       

    def stream_video(self, video_url, request_data):
        video_url = normalize_url(video_url)
        global HEADERS_BASE
        # cópia: antes o 'Range' era gravado direto em HEADERS_BASE e depois
        # vazava para as requisições de m3u8/ts
        headers = dict(HEADERS_BASE)
        try:
            DNSOverride()
            response = http_head(video_url, headers=headers, timeout=(5, 10))
            if response.status_code == 200:
                content_length = int(response.headers.get('Content-Length', 0))
                start, end = self.get_range(request_data, content_length)
                headers['Range'] = 'bytes=%s-%s'%(str(start),str(end))
                DNSOverride()
                response = http_get(video_url, headers=headers, stream=True, timeout=(5, 15))
                if response.status_code == 206 or response.status_code == 200:
                    self.send_partial_response(206, response.headers, content_length, response.iter_content(chunk_size=1024), start, end)
                else:
                    self.send_response(404)
            else:
                self.send_response(404)
        except Exception as e:
            self.send_response(500)

    def send_partial_response(self, status_code, headers, content_length, content_generator, start, end):
        self.send_response(status_code)
        self.send_header("Accept-Ranges", "bytes")
        if start is not None:
            self.send_header("Content-Range", "bytes %s-%s/%s"%(str(start),str(end),str(content_length)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()

        for chunk in content_generator:
            if STOP_SERVER:
                break
            try:
                self.conn.sendall(chunk)
            except:
                pass

    def handle_request(self):
        try:
            self._handle_request()
        except requests.exceptions.RequestException as exc:
            logger.warning(
                'Falha de rede no proxy (%s)', type(exc).__name__
            )
        except OSError as exc:
            logger.debug('Conexao do proxy encerrada (%s)', type(exc).__name__)
        except Exception as exc:
            logger.error(
                'Falha ao processar requisicao do proxy (%s)', type(exc).__name__
            )
        finally:
            try:
                self.conn.close()
            except OSError:
                pass

    def _handle_request(self):
        global URL_BASE, LAST_URL, HEADERS_BASE, STOP_SERVER, CACHE_CHUNKS, CACHE_M3U8, DELAY_MODE
        global RESOLUTION, LAST_M3U8, PARAMS, URL_BASE_PARAMS, CHECK_URL_PARAMS, URL_BASE_STALKER, TOKEN_STALKER       
        global FAKE_IP_SESSION, LAST_CHANNEL
        
        request_data = self.conn.recv(1024)
        if not request_data:
            return
        self.parse_request(request_data)
        self.parse_request2(request_data)
        
        if self.request_method == 'HEAD':
            self.send_response(200)
            self.end_headers()
        elif self.path == "/stop":
            self.send_response(200)
            STOP_SERVER = True
            reset_channel_state()
            reset_session()
            self.server.stop_server()
        elif self.path == "/reset":
            self.send_response(200)
            reset_channel_state()
            reset_session()
        elif self.path == '/check':
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.conn.sendall(b"Hello, world!")
        else:
            request_parts = urlparse(self.path)
            url_path = unquote_plus(request_parts.path)
            query_params = parse_qs(request_parts.query, keep_blank_values=True)
            is_hls_resource = query_params.get('hls') == ['1']

            if 'url' in query_params:
                url = query_params['url'][0]
                if urlparse(url).scheme.lower() not in ('http', 'https'):
                    try:
                        decoded_url = base64.b64decode(url).decode('utf-8')
                        if urlparse(decoded_url).scheme.lower() in ('http', 'https'):
                            url = decoded_url
                    except Exception:
                        pass
                url = normalize_url(url)
                self.set_headers(url)

                # --- NOVO AJUSTE PARA FORMATO DIRETO ---
                if not is_hls_resource and re.search(r'/\w+/\w+/\d+$', url):
                    parsed_url = urlparse(url)
                    host_part = '%s://%s' % (parsed_url.scheme, parsed_url.netloc)
                    url = host_part + '/live' + parsed_url.path + '.m3u8'
                # ----------------------------------------
                if not is_hls_resource:
                    url = self.convert_to_m3u8(url)
            else:
                url = url_path
                self.set_headers(url)

            self.is_hls_resource = is_hls_resource

            # TROCA DE CANAL: se o canal (/live/usuario/senha/id.m3u8) mudou,
            # limpa o estado do canal anterior (sem precisar do /reset).
            # Não mexe nas playlists internas/segmentos do mesmo canal.
            channel_url = url.split('?')[0]
            if (not is_hls_resource and '/live/' in channel_url
                    and '.m3u8' in channel_url and channel_url.count('/') == 6):
                if LAST_CHANNEL and channel_url != LAST_CHANNEL:
                    log('TROCA DE CANAL: limpando estado anterior')
                    reset_channel_state()
                    reset_session()
                LAST_CHANNEL = channel_url
                
            if '.m3u8' in url and '?' in url and not 'extension' in url:
                if not PARAMS:
                    try:
                        PARAMS = '?' + url.split('?')[1]
                    except:
                        pass
            
            # STALKER
            if '/hl' in url and '.ts' in url:
                self.send_response(200)
                self.send_ts(self,url)            
            elif '/hl' in url and not '.ts' in url:
                self.send_response(200)
                self.send_ts(self,url)            
            elif 'm3u8' in url and not 'extension' in url and '/play/' in url and not '.m3u8' in url:
                self.send_response(200)
                self.send_m3u8_stalker(self,url)               
            elif 'm3u8' in url and 'extension' in url:
                self.send_response(200)
            elif '.ts' in url and URL_BASE_STALKER or 'hls' in url and URL_BASE_STALKER:
                self.send_response(200)
                self.send_ts_stalker(self,url)
            
            # XTREAM CODES
            elif '.mp4' in url and not '.m3u8' in url and not '.ts' in url:
                self.stream_video(url, request_data)                    
            elif '.m3u8' in url:
                self.send_response(200)
                self.send_m3u8(self,url)
            elif '.ts' in url:
                self.send_response(200)
                self.send_ts(self,url)
            
            # AJUSTE PARA LINKS SEM EXTENSÃO QUE PASSARAM PELA CONVERSÃO ACIMA
            elif '/live/' in url and not '.ts' in url and not '.m3u8' in url:
                self.send_response(200)
                self.send_m3u8(self, url + '.m3u8')

def monitor():
    try:
        try:
            from kodi_six import xbmc
        except:
            import xbmc
        monitor = xbmc.Monitor()
        while not monitor.waitForAbort(3):
            pass
        log('Ecerrando proxy server')
        url = 'http://'+HOST_NAME+':'+str(PORT_NUMBER)+'/stop'
        try:
            DNSOverride()
            r = requests.get(url,timeout=4)
        except:
            pass
        log('Proxy encerrado')
    except:
        pass

class Server:
    def __init__(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((HOST_NAME, PORT_NUMBER))
        self.server_socket.listen(10)
        self.server_socket.settimeout(1.0)

    def serve_forever(self):
        global STOP_SERVER
        while True:
            if STOP_SERVER:
                break
            try:
                conn, addr = self.server_socket.accept()
                handler = ProxyHandler(conn, addr, self)
                t = threading.Thread(target=handler.handle_request)
                t.daemon = True
                t.start()
            except socket.timeout:
                continue
            except:
                break

    def stop_server(self):
        self.server_socket.close()

def loop_server():
    server = Server()
    server.serve_forever()

class XtreamProxy:
    def reset(self):
        try:
            url = 'http://'+HOST_NAME+':'+str(PORT_NUMBER)+'/reset'
            DNSOverride()
            r = requests.get(url,timeout=3)
        except:
            pass

    def check_service(self):
        try:
            url = 'http://'+HOST_NAME+':'+str(PORT_NUMBER)+'/check'
            DNSOverride()
            r = requests.head(url,timeout=3)
            if r.status_code == 200:
                return True
            return False
        except:
            return False

    def start(self):
        status = self.check_service()
        if status == False:
            proxy_service = threading.Thread(target=loop_server)
            proxy_service.daemon = True
            proxy_service.start()
            monitor_service = threading.Thread(target=monitor)
            monitor_service.daemon = True
            monitor_service.start()
        else:
            self.reset()

# print('url proxy: ',url_proxy)
# XtreamProxy().start()