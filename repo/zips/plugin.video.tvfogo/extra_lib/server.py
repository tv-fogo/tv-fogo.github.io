import six
try:
    from urllib.parse import urlparse, parse_qs, quote, unquote, quote_plus, unquote_plus, urlencode, urljoin #python 3
except ImportError:    
    from urlparse import urlparse, parse_qs, urljoin #python 2
    from urllib import quote, unquote, quote_plus, unquote_plus, urlencode
if six.PY3:
    from http.server import HTTPServer
    from http.server import BaseHTTPRequestHandler
    from http.server import SimpleHTTPRequestHandler
else:
    from BaseHTTPServer import BaseHTTPRequestHandler
    from SimpleHTTPServer import SimpleHTTPRequestHandler
    from BaseHTTPServer import HTTPServer
import threading
import requests
import time
try:
    from extra_lib.dnscompat import DNSOverride
except:
    from dnscompat import DNSOverride
try:
    from extra_lib.secureurl import patch_requests as _patch_requests_https
except:
    from secureurl import patch_requests as _patch_requests_https
_patch_requests_https()
	
HOST_NAME = '127.0.0.1'
PORT_NUMBER = 55334

global GLOBAL_HEADERS
global GLOBAL_URL
global MAX_CPU
GLOBAL_HEADERS = {}
GLOBAL_URL = ''
M3U8_URL = ''
TS_URL = ''
URL_TOKEN = ''
URL_NORMAL = ''
HTTPS_PORT = False
STOP_SERVER = False
URL_REFERER = ''
MAX_CPU = 98



class handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def send_stream_headers(self, content_type, status=200, content_length=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        if content_length is not None:
            self.send_header('Content-Length', str(content_length))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Connection', 'close')
        self.end_headers()

    def send_empty_response(self, status=200):
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()

    def cpu(self):
        try:
            from kodi_six import xbmc
            cpu_percent = xbmc.getInfoLabel("System.CpuUsage")
            cpu_percent = int(str(cpu_percent).replace('%', ''))
        except:
            cpu_percent = 0
        return int(cpu_percent)
    
    def playing(self):
        try:
            from kodi_six import xbmc
            if not xbmc.Player().isPlaying():
                return False
            return True
        except:
            return True

   
    def basename(self,p):
        """Returns the final component of a pathname"""
        i = p.rfind('/') + 1
        return p[i:] 
    
    def check_stream(self,url,headers):
        r = requests.head(url,headers=headers,timeout=3, verify=False)
        if r.status_code == 200:
            return True
        return False

    def get_origin(url,headers):
        origin = ''
        if int(url.count(':')) == 2:
            r = requests.get(url,headers=headers,verify=False,timeout=1)
            r_parse = urlparse(r.url)
            if 'https' in url or ':443' in url:
                origin = "https://" + r_parse.netloc
            else:
                origin = "http://" + r_parse.netloc
        return origin
    
    def get_headers(self,url):
        global GLOBAL_HEADERS
        try:
            url = url.split('url=')[1]
        except:
            pass
        data = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36', 'Connection': 'keep-alive'}
        if '|' in url or '&' in url or 'h123' in url:
            try:
                referer = url.split('Referer=')[1]
                try:
                    referer = referer.split('&')[0]
                except:
                    pass
            except:
                referer = None
            try:
                origin = url.split('Origin=')[1]
                try:
                    origin = origin.split('&')[0]
                except:
                    pass
            except:
                origin = None
            try:
                cookie = url.split('Cookie=')[1]
                try:
                    cookie = cookie.split('&')[0]
                except:
                    pass
            except:
                cookie = None
            try:
                user_agent = url.split('User-Agent=')[1]
                try:
                    user_agent = user_agent.split('&')[0]
                except:
                    pass
            except:
                user_agent = None
            try:
                referer = unquote_plus(referer)
            except:
                pass
            try:
                origin = unquote_plus(origin)
            except:
                pass
            try:
                cookie = unquote_plus(cookie)
            except:
                pass
            try:
                user_agent = unquote_plus(user_agent)
            except:
                pass                        
            if referer:
                #data.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'})
                data.update({'Referer': referer})
            if cookie:
                data.update({'Cookie': cookie})                
            if origin:
                data.update({'Origin': origin})
            if user_agent:
                data.update({'User-Agent': user_agent})
            # else:
            #     if not 'token' in url:
            #         try:
            #             url_safe = url.split('|')[0]
            #         except:
            #             url_safe = url
            #         try:
            #             url_safe = url_safe.split('&')[0]
            #         except:
            #             pass
            #         origin = self.get_origin(url,data)
            #         if origin:
            #             data.update({'Origin': origin})
            if referer or origin or cookie:
                GLOBAL_HEADERS = data
        if not GLOBAL_HEADERS:
            GLOBAL_HEADERS = data
    
    def append_headers(self,headers):
        return '|%s' % '&'.join(['%s=%s' % (key, headers[key]) for key in headers])    
    
    def convert_to_m3u8(self,url):
        if '|' in url:
            url = url.split('|')[0]
        elif '&h123' in url:
            url = url.split('&h123')[0]
        # if '&' in url:
        #     url = url.split('&')[0]
        if not '.m3u8' in url and not '/hl' in url and int(url.count("/")) > 4 and not '.mp4' in url and not '.avi' in url:
            parsed_url = urlparse(url)
            try:
                host_part1 = '%s://%s'%(parsed_url.scheme,parsed_url.netloc)
                host_part2 = url.split(host_part1, 1)[1]
                if not host_part2.startswith('/live/'):
                    url = host_part1 + '/live' + host_part2
                else:
                    url = host_part1 + host_part2
                query = ''
                if '?' in url:
                    url, query = url.split('?', 1)
                    query = '?' + query
                file = self.basename(url)
                if file.endswith('.ts'):
                    file_new = file[:-3] + '.m3u8'
                    url = url.replace(file, file_new) + query
                else:
                    file_new = file + '.m3u8'
                    url = url.replace(file, file_new) + query
            except:
                pass
        return url
    
    def convert_to_ts(self,url):
        if '|' in url:
            url = url.split('|')[0]
        elif '&h123' in url:
            url = url.split('&h123')[0]        
        if '.m3u8' in url and '/live/' in url and int(url.count("/")) > 5:
            url = url.replace('/live', '').replace('.m3u8', '')
        return url
    
    def detect_xtream_codes(self,url):
        if not '.m3u8' in url and not '/hl' in url and int(url.count(":")) == 2 and int(url.count("/")) > 4 or '.m3u8' in url and '/live/' in url and int(url.count("/")) > 5:
            return True
        else:
            return False

    def make_absolute_uri(self,base_url,uri):
        uri = uri.strip()
        if not uri or uri.startswith('#') or uri.startswith('data:'):
            return uri
        if uri.startswith('http://') or uri.startswith('https://'):
            return uri
        if uri.startswith('//'):
            parsed = urlparse(base_url)
            return parsed.scheme + ':' + uri
        return urljoin(base_url, uri)

    def rewrite_tag_uris(self,line,base_url):
        marker = 'URI="'
        pos = 0
        while True:
            start = line.find(marker, pos)
            if start == -1:
                break
            uri_start = start + len(marker)
            uri_end = line.find('"', uri_start)
            if uri_end == -1:
                break
            uri = line[uri_start:uri_end]
            abs_uri = self.make_absolute_uri(base_url, uri)
            line = line[:uri_start] + abs_uri + line[uri_end:]
            pos = uri_start + len(abs_uri) + 1
        return line

    def absolute_origin_playlist(self,text,base_url):
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                lines.append(line)
            elif stripped.startswith('#'):
                lines.append(self.rewrite_tag_uris(line, base_url))
            else:
                lines.append(self.make_absolute_uri(base_url, stripped))
        if text.endswith('\n') or text.endswith('\r'):
            return '\n'.join(lines) + '\n'
        return '\n'.join(lines)

    
    def ts(self,url,headers,head=False):
        global GLOBAL_URL
        global GLOBAL_HEADERS
        global STOP_SERVER
        if not headers:
            headers = GLOBAL_HEADERS
        if GLOBAL_URL and not 'http' in url:
            url = GLOBAL_URL + url
        # url = url.replace('esportes4/', '')
        if head:
            self.send_stream_headers('video/mp2t')
            return
        def head_ts(url,headers):
            r = requests.head(url,headers=headers,timeout=3,verify=False)
            if r.status_code == 200:
                return True
            return False
        
        def fechar_server():
            def shutdown(server):
                server.shutdown()
            t = threading.Thread(target=shutdown, args=(self.server, ))
            t.start() 


        for i in range(30):
            i = i + 1
            if STOP_SERVER:
                break
            # if self.cpu() >= MAX_CPU:
            #     self.send_response(200)
            #     self.end_headers()
            #     def shutdown(server):
            #         server.shutdown()
            #     t = threading.Thread(target=shutdown, args=(self.server, ))
            #     t.start()
            #     break
            # if i > 6:
            #     if not self.playing():
            #         self.send_response(200)
            #         self.end_headers()
            #         def shutdown(server):
            #             server.shutdown()
            #         t = threading.Thread(target=shutdown, args=(self.server, ))
            #         t.start()
            #         break
            if not STOP_SERVER:  
                try:
                    r = requests.get(url, headers=headers, stream=True, verify=False)
                    if r.status_code == 200:
                        self.send_stream_headers('video/mp2t')
                        for chunk in r.iter_content(300000):                           
                            try:
                                if chunk:
                                    self.wfile.write(chunk)
                                    self.wfile.flush()
                            except:
                                break
                            if STOP_SERVER:
                                break
                    r.close()
                    break
                except:
                    pass
            if STOP_SERVER:
                break                           
            # if head_ts(url,headers):                                    
            #     try:
            #         r = requests.get(url, headers=headers, stream=True, verify=False)
            #         if r.status_code == 200:
            #             self.send_response(200)
            #             self.send_header('Content-type','video/mp2t')
            #             self.end_headers()
            #             for chunk in r.iter_content(300000):                           
            #                 try:
            #                     self.wfile.write(chunk)
            #                 except:
            #                     pass
            #                 if not self.playing():
            #                     fechar_server()
            #                     break
            #         r.close()
            #         break
            #     except:
            #         pass
            if i == 15:
                self.send_empty_response(404)
                # def shutdown(server):
                #     server.shutdown()
                # t = threading.Thread(target=shutdown, args=(self.server, ))
                # t.start()                
                break
    
    def m3u8(self,url,headers,head=False):
        #print('acessando a url: ',url)
        global GLOBAL_URL
        global MAX_CPU
        global HTTPS_PORT
        global URL_TOKEN
        global URL_NORMAL
        global URL_REFERER
        global STOP_SERVER
        # if not URL_REFERER:
        #     URL_REFERER = url
        # if URL_REFERER and 'token' in url:
        #     headers.update({'Referer': URL_REFERER})
        if not 'token' in url:
            URL_NORMAL = url
        if URL_TOKEN:
            url = URL_TOKEN
        elif URL_NORMAL:
            url = URL_NORMAL
        if head:
            self.send_stream_headers('application/vnd.apple.mpegurl')
            return
        
        def head_m3u8(url,headers):
            r = requests.head(url,headers=headers,timeout=3, verify=False)
            if r.status_code == 200:
                return True
            return False
        
        for i in range(20):
            i = i + 1
            if STOP_SERVER:                    
                break

            if i > 5:
                if self.cpu() >= MAX_CPU:
                    self.send_empty_response()
                    STOP_SERVER = True
                    def shutdown(server):
                        server.shutdown()
                        try:
                            server.server_close()
                        except:
                            pass                        
                    t = threading.Thread(target=shutdown, args=(self.server, ))
                    t.start()
                    break
            # if i > 3:
            #     if not self.playing():
            #         self.send_response(200)
            #         self.end_headers()
            #         def shutdown(server):
            #             server.shutdown()
            #         t = threading.Thread(target=shutdown, args=(self.server, ))
            #         t.start()
            #         break
            if not STOP_SERVER:
                try:
                    r = requests.get(url, headers=headers,timeout=4, verify=False)
                    last_url = r.url
                    # if 'token' in url:
                    #     URL_TOKEN = ''                  
                    # elif not URL_TOKEN and 'token' in last_url:
                    #     URL_TOKEN = last_url
                    if r.status_code == 200:
                        text_ = self.absolute_origin_playlist(r.text, last_url)
                        payload = text_.encode("utf-8")
                        self.send_stream_headers('application/vnd.apple.mpegurl', content_length=len(payload))
                        self.wfile.write(payload)
                        r.close()
                        break
                    r.close()
                    time.sleep(0.5)
                    continue
                except:
                    time.sleep(0.5)
                    continue
            if STOP_SERVER:
                break
            time.sleep(3)           
            if i == 8: # 24 segundos
                self.send_empty_response(404)
                STOP_SERVER = True
                def shutdown(server):
                    server.shutdown()
                t = threading.Thread(target=shutdown, args=(self.server, ))
                t.start()      
                break

    def do_HEAD(self):
        global GLOBAL_HEADERS
        global GLOBAL_URL
        global M3U8_URL
        global TS_URL
        global HTTPS_PORT
        global URL_REFERER
        global STOP_SERVER
        if not STOP_SERVER:
            try:
                url = self.path.split('url=')[1]
            except:
                url = ''
            try:
                url = unquote_plus(url)
            except:
                pass
            try:
                url = unquote(url)
            except:
                pass
            if url:
                if not GLOBAL_HEADERS:
                    self.get_headers(url)
                if not url.lower().split('?', 1)[0].endswith('.ts'):
                    url = self.convert_to_m3u8(url)
                # ts_link = self.convert_to_ts(url)
                # url = ts_link
                if ':443' in url or 'https://' in url:
                    HTTPS_PORT = True
                # if self.check_stream(m3u8,GLOBAL_HEADERS):
                #     M3U8_URL = m3u8
                # elif self.check_stream(ts_link,GLOBAL_HEADERS) and not M3U8_URL:
                #     TS_URL = ts_link
                # else:
                #     TS_URL = ts_link
            # if not M3U8_URL and TS_URL:
            #     url = TS_URL
            # else:
            #     url = M3U8_URL
        
            if self.path == '/check':
                self.send_empty_response()
            elif self.path == '/stop':
                self.send_empty_response()
                STOP_SERVER = True
                def shutdown(server):
                    server.shutdown()
                    try:
                        server.server_close()
                    except:
                        pass                    
                t = threading.Thread(target=shutdown, args=(self.server, ))
                t.start()                
            elif url.startswith('http') and '/hl' in url and '.m3u8' in url:
                self.m3u8(url,GLOBAL_HEADERS,head=True)
            elif not url.startswith('http') and '.m3u8' in self.path:
                if self.path.startswith('/'):
                    path_url = self.path[1:]
                else:
                    path_url = self.path
                url = GLOBAL_URL + path_url
                self.m3u8(url,GLOBAL_HEADERS,head=True)
            elif not 'http' in url and not '/hl' in url and '.ts' in self.path:
                print('nao http, nao /hl e .ts')
                self.ts(self.path,GLOBAL_HEADERS,head=True)
            elif url.endswith(".ts") or ('/hl' in url and not url.endswith(".ts") and not url.endswith(".m3u8")):
                self.ts(url,GLOBAL_HEADERS,head=True)
            elif url.endswith(".html"):
                self.ts(url,GLOBAL_HEADERS,head=True)
            elif '.m3u8' in url:
                self.m3u8(url,GLOBAL_HEADERS,head=True)
            elif not '/hl' in url and not '.ts' in url and TS_URL:
                self.ts(url,GLOBAL_HEADERS,head=True)

    
    def do_GET(self):
        global GLOBAL_HEADERS
        global GLOBAL_URL
        global M3U8_URL
        global TS_URL
        global HTTPS_PORT
        global URL_REFERER
        global STOP_SERVER
        if not STOP_SERVER:
            try:
                url = self.path.split('url=')[1]
            except:
                url = ''
            try:
                url = unquote_plus(url)
            except:
                pass
            try:
                url = unquote(url)
            except:
                pass
            if url:
                if not GLOBAL_HEADERS:
                    self.get_headers(url)
                if not url.lower().split('?', 1)[0].endswith('.ts'):
                    url = self.convert_to_m3u8(url)
                # ts_link = self.convert_to_ts(url)
                # url = ts_link
                if ':443' in url or 'https://' in url:
                    HTTPS_PORT = True
                # if self.check_stream(m3u8,GLOBAL_HEADERS):
                #     M3U8_URL = m3u8
                # elif self.check_stream(ts_link,GLOBAL_HEADERS) and not M3U8_URL:
                #     TS_URL = ts_link
                # else:
                #     TS_URL = ts_link
            # if not M3U8_URL and TS_URL:
            #     url = TS_URL
            # else:
            #     url = M3U8_URL
        
            if self.path == '/check':
                self.send_empty_response()
            elif self.path == '/stop':
                self.send_empty_response()
                STOP_SERVER = True
                def shutdown(server):
                    server.shutdown()
                    try:
                        server.server_close()
                    except:
                        pass
                t = threading.Thread(target=shutdown, args=(self.server, ))
                t.start()                
            elif url.startswith('http') and '/hl' in url and '.m3u8' in url:
                self.m3u8(url,GLOBAL_HEADERS)
            elif not url.startswith('http') and '.m3u8' in self.path:
                if self.path.startswith('/'):
                    path_url = self.path[1:]
                else:
                    path_url = self.path
                url = GLOBAL_URL + path_url
                self.m3u8(url,GLOBAL_HEADERS)
            elif not 'http' in url and not '/hl' in url and '.ts' in self.path:
                print('nao http, nao /hl e .ts')
                self.ts(self.path,GLOBAL_HEADERS)
            elif url.endswith(".ts") or ('/hl' in url and not url.endswith(".ts") and not url.endswith(".m3u8")):
                self.ts(url,GLOBAL_HEADERS)
            elif url.endswith(".html"):
                self.ts(url,GLOBAL_HEADERS)
            elif '.m3u8' in url:
                self.m3u8(url,GLOBAL_HEADERS)
            elif not '/hl' in url and not '.ts' in url and TS_URL:
                self.ts(url,GLOBAL_HEADERS)


def serve_forever(httpd):
    with httpd:  # to make sure httpd.server_close is called
        httpd.serve_forever()#


class mediaserver:
    def __init__(self):
        try:
            self.httpd = HTTPServer(('', PORT_NUMBER), handler)
            self.server_instance = True
        except:
            self.server_instance = False
        if self.server_instance:
            try:
                self.server = threading.Thread(target=serve_forever, args=(self.httpd, ))
                self.server.daemon = True
                self.server_thread = True
            except:
                self.server_thread = False
        else:
            self.server_thread = False     

    
    def in_use(self):
        url = 'http://'+HOST_NAME+':'+str(PORT_NUMBER)+'/check'
        use = False
        try:
            r = requests.head(url,timeout=1)
            if r.status_code == 200:
                use = True
        except:
            pass
        return use 

    def start(self):
        global STOP_SERVER
        STOP_SERVER = False
        if not self.in_use():
            if self.server_thread:
                self.server.start()
                time.sleep(4)

    def stop(self):
        if self.server_instance:
            self.httpd.shutdown()
            self.httpd.server_close()

def prepare_url(url):
    try:
        url = unquote_plus(url)
    except:
        pass
    try:
        url = unquote(url)
    except:
        pass
    base_url, separator, stream_headers = url.partition('|')
    path, query_separator, query = base_url.partition('?')
    if path.lower().endswith('.ts'):
        path = path[:-3] + '.m3u8'
        base_url = path + (query_separator + query if query_separator else '')
        url = base_url + (separator + stream_headers if separator else '')
    url = url.replace('|', '&h123=true&')
    url = quote_plus(url)
    url = 'http://'+HOST_NAME+':'+str(PORT_NUMBER)+'/?url=' + url
    return url

def extract_media_url(url):
    try:
        url = url.split('url=', 1)[1]
    except:
        return url
    try:
        url = unquote_plus(url)
    except:
        pass
    try:
        url = unquote(url)
    except:
        pass
    try:
        url = url.split('&h123=true&', 1)[0]
    except:
        pass
    return url

def req_shutdown():
    url = 'http://'+HOST_NAME+':'+str(PORT_NUMBER)+'/stop'
    try:
        r = requests.get(url,timeout=2)
        r.close()
    except:
        pass

def check_server():
    url = 'http://'+HOST_NAME+':'+str(PORT_NUMBER)+'/check'
    status = False
    try:
        r = requests.get(url,timeout=3)
        if r.status_code == 200:
            status = True
    except:
        pass
    return status

def thread_stop():
    t = threading.Thread(target=req_shutdown)
    t.start()


# try:
#     mediaserver().start()
# except KeyboardInterrupt:
#     mediaserver().stop()
