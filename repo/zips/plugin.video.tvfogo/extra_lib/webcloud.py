import requests
import re
import base64
from six.moves.urllib.parse import quote, unquote_plus
import six
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

def find_hash(magnet):
    hash_match1 = re.search(r"urn:btih:(.*?)&", magnet)
    hash_match2 = re.search(r"urn:btih:([0-9a-fA-F]+)", magnet)
    if hash_match1: 
        h = hash_match1.group(1)
        return h.lower()
    if hash_match2:
        h = hash_match2.group(1)
        return h.lower()       
    return None

def find_dn(magnet):
    dn = ''
    try:
        dn = magnet.split('dn=')[1]
    except IndexError:
        pass
    try:
        dn = dn.split('&')[0]
    except IndexError:
        pass
    return dn

def torrent_cloud(magnet):
    DNSOverride()
    if not 'magnet:?xt=urn:btih:' in magnet and '&dn' in magnet:
        magnet = 'magnet:?xt=urn:btih:' + magnet
    ### webtor.io test scraper
    hash_ = find_hash(magnet)
    dn = find_dn(magnet)
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Encoding': 'gzip, deflate',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'sec-ch-ua': '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"wingows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
    }    
    url_webtor = 'https://webtor.io/{}'.format(hash_)

    # primeira parte:
    r = requests.get(url_webtor, headers=headers)
    api_cookies = r.cookies.get_dict()
    src = r.text
    try:
        CRF = re.findall(r'window._CSRF = "(.*?)";', src)[0]
        sessionid = re.findall(r'window._sessionID = "(.*?)";', src)[0]
    except IndexError:
        CRF = sessionid = ''
    try:
        file_name = re.findall(r'<li class="py-1 text-accent-focus">> (.*?)</li>', src)[0]
    except IndexError:
        file_name = ''
    pattern = r'<input type="hidden" name="(resource-id|item-id)" value="([a-f0-9]+)"'
    try:
        title_page = re.findall(r'<title>(.*?)</title>', src)[0]
    except IndexError:
        title_page = ''
    try:
        websiteid = re.findall(r'window._umami = {"website_id":"(.*?)",', src)[0]
        web_host = re.findall(r'window._umami = {"website_id":.+?,"host_url":"(.*?)"};', src)[0]
    except IndexError:
        websiteid = web_host = ''
    
    # check form        
    try:
        matches = re.findall(pattern, src)
        data = {key: value for key, value in matches}
        data['item-id'] = matches[1][1]
    except (IndexError, KeyError):
        # sending signal to webtor.io
        headers_signal = headers.copy()
        headers_signal.pop('Content-Type', None)
        headers_signal.pop('x-umami-cache', None)
        headers_signal.update({
            'rid': 'anti-csrf',
            'st-auth-mode': 'cookie',
            'x-csrf-token': CRF,
            'x-layout': '{{ template "main" . }}',
            'x-requested-with': 'XMLHttpRequest',
            'x-session-id': sessionid
        })        
        webtor_ = 'https://webtor.io/'
        data_signal = {'resource': magnet, 'instruction': ''}
        r_signal = requests.post(webtor_, headers=headers_signal, data=data_signal)
        r = requests.get(url_webtor, headers=headers)
        api_cookies = r.cookies.get_dict()
        src = r.text
        try:
            CRF = re.findall(r'window._CSRF = "(.*?)";', src)[0]
        except IndexError:
            CRF = ''
        try:
            sessionid = re.findall(r'window._sessionID = "(.*?)";', src)[0]
        except IndexError:
            sessionid = ''
        try:
            file_name = re.findall(r'<li class="py-1 text-accent-focus">> (.*?)</li>', src)[0]
        except IndexError:
            file_name = ''
        try:
            title_page = re.findall(r'<title>(.*?)</title>', src)[0]
        except IndexError:
            title_page = ''
        try:
            websiteid = re.findall(r'window._umami = {"website_id":"(.*?)",', src)[0]
        except IndexError:
            websiteid = ''
        try:
            web_host = re.findall(r'window._umami = {"website_id":.+?,"host_url":"(.*?)"};', src)[0]
        except IndexError:
            web_host = ''
        try:
            matches = re.findall(pattern, src)
            data = {key: value for key, value in matches}
            data['item-id'] = matches[1][1]
        except (IndexError, KeyError):
            return None

    api_host = web_host + '/api/send'
    if dn and file_name:
        title = '/' + quote(dn) + '/' + quote(file_name) + quote(' | ') + quote(dn) + quote(' | ') + 'Webtor.io'
    else:
        title = '/' + quote(title_page)

    headers.pop('Upgrade-Insecure-Requests', None)
    headers.update({
        'Content-Type': 'application/json',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site'
    })

    params = {
        "type": "event",
        "payload": {
            "website": websiteid,
            "hostname": "webtor.io",
            "screen": "1920x1080",
            "language": "pt-BR",
            "title": title,
            "url": "/{}".format(hash_),
            "name": "download",
            "data": {}
        }
    }

    r = requests.post(api_host, headers=headers, json=params)
    key = r.text

    headers.pop('Content-Type', None)
    headers.pop('x-umami-cache', None)
    headers.update({
        'rid': 'anti-csrf',
        'st-auth-mode': 'cookie',
        'x-csrf-token': CRF,
        'x-layout': '{{ template "main" . }}',
        'x-requested-with': 'XMLHttpRequest',
        'x-session-id': sessionid
    })
    r = requests.post('https://webtor.io/download-file', headers=headers, cookies=api_cookies, data=data)
    src = r.text
    try:
        queue = re.findall(r'data-async-progress-log="(.*?)"', src)[0]
    except IndexError:
        return None
    log_url = 'https://webtor.io' + queue

    r = requests.get(log_url, headers=headers, cookies=api_cookies)
    src = r.text
    try:
        stream = re.findall('var url = .\"(.*?).\"', src)[0].replace('\\\\u0026', '&')
    except IndexError:
        return None
    return stream

def teste_magnet():
    magnet = 'magnet:?xt=urn:btih:bfadd755f395508693a8b10f5ce09955e26371e6&dn=Um.Filme.Minecraft.2025.1080p.FULL.HD.WEB-DL.DUAL.5.1&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce'
    stream = torrent_cloud(magnet)


