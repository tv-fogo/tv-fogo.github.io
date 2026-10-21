# -*- coding: utf-8 -*-
try:
    from lib.ClientScraper import cfscraper
except ImportError:
    try:
        from ClientScraper import cfscraper
    except ImportError:
        import requests as cfscraper
import xml.dom.minidom
import base64
import calendar
import gzip
import hashlib
import io
import json
import os
import time
from xml.etree import ElementTree
try:
    from lib.helper import *
except:
    try:
        from .helper import *
    except ImportError:
        from helper import *
import re
try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

IPTV_PROBLEM_LOG = translate(os.path.join(profile, 'iptv_problems_log.txt'))
XMLTV_CACHE_TTL = 6 * 60 * 60


def _xmltv_key(value):
    return re.sub(r'\s+', ' ', str(value or '').strip().lower())


def _xmltv_timestamp(value):
    try:
        raw = str(value or '').strip()
        timestamp = calendar.timegm(time.strptime(raw[:14], '%Y%m%d%H%M%S'))
        timezone = re.search(r'([+-])(\d{2}):?(\d{2})', raw[14:])
        if timezone:
            offset = (int(timezone.group(2)) * 60 + int(timezone.group(3))) * 60
            timestamp -= offset if timezone.group(1) == '+' else -offset
        return timestamp
    except Exception:
        return 0

def extract_info(url):
    # Parseia a URL
    parsed_url = urlparse(url)
    protocol = parsed_url.scheme
    # Extrai o host e a porta
    host = parsed_url.hostname
    # Define a porta padrão se não estiver especificada
    if parsed_url.port:
        port = parsed_url.port
    else:
        port = 80 if parsed_url.scheme == 'http' else 443
    
    # Extrai o username e o password dos parâmetros da query
    query_params = parse_qs(parsed_url.query)
    username = query_params.get('username', [None])[0]
    password = query_params.get('password', [None])[0]
    dns = '{0}://{1}:{2}'.format(protocol,host,port)
    
    return dns, username, password

def check_iptv(url_iptv):
    cond = True
    if exists(IPTV_PROBLEM_LOG):
        if six.PY2:
            import io
            open_file = lambda filename, mode: io.open(filename, mode, encoding='utf-8')
        else:
            open_file = lambda filename, mode: open(filename, mode, encoding='utf-8')
        with open_file(IPTV_PROBLEM_LOG, "r") as arquivo:
            urls = arquivo.read()
            urls = urls.split('\n')
            for i in urls:
                if 'http' in i:
                    if i in url_iptv:
                        cond = False
                        break
    return cond

def parselist(url):
    iptv = []
    try:
        url = cfscraper.get(url).json()['url']
    except:
        pass
    try:
        if 'paste.kodi.tv' in url and not 'documents' in url and not 'raw' in url:
            try:
                key = url.split('/')[-1]
                url = 'https://paste.kodi.tv/documents/' + key
                src = cfscraper.get(url).json()['data']
                lines = src.split('\n')
                if lines:
                    for i in lines:
                        i = i.replace(' ', '')
                        if 'http' in i:
                            if check_iptv(i):
                                dns, username, password = extract_info(i)
                                iptv.append((dns,username,password))
            except:
                pass
        else:
            src = cfscraper.get(url).text
            lines = src.split('\n')
            if lines:
                for i in lines:
                    i = i.replace(' ', '')
                    if 'http' in i:
                        if check_iptv(i):
                            dns, username, password = extract_info(i)
                            iptv.append((dns,username,password))
    except:
        pass
    return iptv


def replace_desc(desc):
    substituicoes = {
        '[': '[COLOR yellow][',
        '(': '[/COLOR]('
    }

    def substituidor(match):
        return substituicoes[match.group(0)]

    padrao = re.compile('|'.join(map(re.escape, substituicoes.keys())))
    resultado = padrao.sub(substituidor, desc)
    return resultado

def replace_name(name):
    if '-' in name:
        name = name.replace('-', '-[COLOR yellow]')
        name = name + '[/COLOR]'
    return name

def ordenar_resolucao(item):
    name = item[0]
    if 'FHD' in name:
        return 1
    elif 'HD' in name:
        return 2
    elif '4K' in name:
        return 3    
    elif 'SD' in name:
        return 4
    return 5 

    

class API:
    def __init__(self, dns, username, password):
        self.live_url = '{0}/enigma2.php?username={1}&password={2}&type=get_live_categories'.format(dns, username, password)
        self.vod_url = '{0}/enigma2.php?username={1}&password={2}&type=get_vod_categories'.format(dns, username, password)
        self.series_url = '{0}/enigma2.php?username={1}&password={2}&type=get_series_categories'.format(dns, username, password)
        self.player_api = '{0}/player_api.php?username={1}&password={2}'.format(dns, username, password)
        self.xmltv_url = '{0}/xmltv.php?{1}'.format(
            dns.rstrip('/'), urlencode({'username': username, 'password': password}))
        self._epg_data = None
        self._xmltv_status = None
        self._xmltv_error = None
        self.play_url = '{0}/live/{1}/{2}/'.format(dns,username,password)
        self.play_movies = '{0}/movie/{1}/{2}/'.format(dns,username,password)
        self.play_series = '{0}/series/{1}/{2}/'.format(dns,username,password)
        self.adult_tags = ['xxx','xXx','XXX','adult','Adult','ADULT','adults','Adults','ADULTS','porn','Porn','PORN', 'teste', 'TESTE', 'Teste']
        self.hide_adult = 'true'

    def http(self, url='', mode=None):
        if not mode:
            try:
                return cfscraper.get(url).content    
            except:
                pass
        elif mode == 'channels_category':
            try:
                return cfscraper.get(self.live_url).content
            except:
                pass
        elif mode == 'json_url':
            try:
                return cfscraper.get(url).json()
            except:
                pass
        elif mode == 'vod':
            try:
                return cfscraper.get(url).text
            except:
                pass
        return ''


        
        
    def b64(self, obj):
        return base64.b64decode(obj).decode('utf-8')
    
    def check_protocol(self,url):
        parsed = urlparse(self.live_url)
        protocol = parsed.scheme
        if protocol=='https':
            return url.replace('http','https')
        return url
    
    def regex_from_to(self, text, from_string, to_string, excluding=True):
        if excluding:
            try: r = re.search("(?i)" + from_string + "([\S\s]+?)" + to_string, text).group(1)
            except: r = ''
        else:
            try: r = re.search("(?i)(" + from_string + "[\S\s]+?" + to_string + ")", text).group(1)
            except: r = ''
        return r 

    def regex_get_all(self, text, start_with, end_with):
        r = re.findall("(?i)(" + start_with + "[\S\s]+?" + end_with + ")", text)
        return r       

    
    def channels_category(self):
        itens = []
        xml_data = self.http('', 'channels_category')
        if xml_data:
            doc = xml.dom.minidom.parseString(xml_data)
            if doc:
                for i, _ in enumerate(doc.getElementsByTagName('channel')):
                    name = self.b64(doc.getElementsByTagName('title')[i].firstChild.nodeValue)
                    url = self.check_protocol(doc.getElementsByTagName('playlist_url')[i].firstChild.nodeValue).replace('<![CDATA[','').replace(']]>','')
                    if not 'All' in name: 
                        if self.hide_adult == 'false':                      
                            itens.append((name,url))
                        else:
                            if not any(s in name for s in self.adult_tags):
                                itens.append((name,url))
        return itens
    
    def channel_id(self,json_data,n):
        if json_data:
            for i, d in enumerate(json_data):
                if n == i:
                    return d.get('stream_id', '')
        return ''

    def xmltv_epg(self):
        if self._epg_data is not None:
            return self._epg_data

        self._epg_data = {}
        cache_id = hashlib.md5(self.xmltv_url.encode('utf-8', 'ignore')).hexdigest()
        cache_path = os.path.join(profile, 'xtream_xmltv_{0}.json'.format(cache_id))
        try:
            with open(cache_path, 'r') as cache_file:
                cached = json.load(cache_file)
            if (isinstance(cached, dict)
                    and cached.get('expires', 0) > time.time()
                    and isinstance(cached.get('channels'), dict)):
                self._epg_data = cached['channels']
                return self._epg_data
        except Exception:
            pass

        try:
            response = cfscraper.get(
                self.xmltv_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 '
                                      '(KHTML, like Gecko) Chrome/52.0.2743.116 Safari/537.36'},
                timeout=(5, 60))
            self._xmltv_status = getattr(response, 'status_code', 200)
            if self._xmltv_status >= 400:
                return self._epg_data
            content = response.content
            if isinstance(content, str):
                content = content.encode('utf-8')
            if content[:2] == b'\x1f\x8b':
                content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()

            aliases = {}
            programmes = {}
            now = time.time()
            for unused, element in ElementTree.iterparse(io.BytesIO(content), events=('end',)):
                tag = element.tag.rsplit('}', 1)[-1]
                if tag == 'channel':
                    channel_id = _xmltv_key(element.get('id'))
                    if channel_id:
                        for display_name in element.findall('display-name'):
                            alias = _xmltv_key(''.join(display_name.itertext()))
                            if alias:
                                aliases[alias] = channel_id
                    element.clear()
                elif tag == 'programme':
                    channel_id = _xmltv_key(element.get('channel'))
                    title_element = element.find('title')
                    title = ''.join(title_element.itertext()).strip() if title_element is not None else ''
                    start = _xmltv_timestamp(element.get('start'))
                    stop = _xmltv_timestamp(element.get('stop'))
                    if channel_id and title and stop > now:
                        schedule = programmes.setdefault(channel_id, {'current': None, 'next': None})
                        entry = {'title': title, 'start': start, 'stop': stop}
                        if start <= now < stop:
                            schedule['current'] = entry
                        elif start > now and (schedule['next'] is None or start < schedule['next']['start']):
                            schedule['next'] = entry
                    element.clear()

            result = {}
            for channel_id, schedule in programmes.items():
                result[channel_id] = [entry for entry in (schedule['current'], schedule['next']) if entry]
            for alias, channel_id in aliases.items():
                if channel_id in result:
                    result[alias] = result[channel_id]
            self._epg_data = result
            try:
                with open(cache_path, 'w') as cache_file:
                    json.dump({'expires': time.time() + XMLTV_CACHE_TTL, 'channels': result},
                              cache_file, ensure_ascii=True)
            except Exception:
                pass
        except Exception as error:
            self._xmltv_error = type(error).__name__
        return self._epg_data

    def channel_epg(self, epg_data, epg_channel_id, channel_name):
        programs = []
        for value in (epg_channel_id, channel_name):
            key = _xmltv_key(value)
            if key and epg_data.get(key):
                programs = epg_data[key]
                break
        if not programs:
            return ''

        now = time.time()
        current = None
        upcoming = None
        for program in programs:
            if program['start'] <= now < program['stop']:
                current = program
            elif program['start'] > now and (upcoming is None or program['start'] < upcoming['start']):
                upcoming = program
        lines = []
        if current:
            lines.append('[B][COLOR gold]AGORA[/COLOR][/B] ' + current['title'])
        if upcoming:
            lines.append('[B][COLOR gray]PRÓXIMO[/COLOR][/B] ' + upcoming['title'])
        return '\n'.join(lines)

    
    def channels_open(self,url):
        try:
            chan_id = url.split('cat_id=')[1]
        except:
            chan_id = ''
        try:
            chan_id = chan_id.split('&')[0]
        except:
            pass
        if not chan_id:
            try:
                chan_id = url.split('category_id=')[1]
            except:
                chan_id = ''
            try:
                chan_id = chan_id.split('&')[0]
            except:
                pass           

        itens = []
        xml_data = self.http(url)
        if xml_data and chan_id:
            url_json_channels = '{0}&action=get_live_streams&category_id={1}'.format(self.player_api,chan_id)
            json_data = self.http(url_json_channels,'json_url')            
            epg_data = self.xmltv_epg() if json_data else {}
            doc = xml.dom.minidom.parseString(xml_data)
            if doc:
                for i, _ in enumerate(doc.getElementsByTagName('channel')):
                    name = re.sub('\[.*?min ','-',self.b64(doc.getElementsByTagName('title')[i].firstChild.nodeValue))
                    url_ = self.check_protocol(doc.getElementsByTagName('stream_url')[i].firstChild.nodeValue).replace('<![CDATA[','').replace(']]>','')
                    stream_id = self.channel_id(json_data,i)
                    url_ = '{0}{1}.m3u8'.format(self.play_url,stream_id)
                    epg_channel_id = ''
                    try:
                        epg_channel_id = json_data[i].get('epg_channel_id', '')
                    except Exception:
                        pass
                    epg_desc = self.channel_epg(epg_data, epg_channel_id, name)
                    try:
                        name = replace_name(name)
                    except:
                        pass
                    try:
                        thumb = (doc.getElementsByTagName('desc_image')[i].firstChild.nodeValue).replace('<![CDATA[ ','').replace(' ]]>','')
                        desc = self.b64(doc.getElementsByTagName('description')[i].firstChild.nodeValue)
                        try:
                            desc = replace_desc(desc)
                        except:
                            pass
                    except:
                        thumb = ''
                        desc = 'No Info Available'
                    if epg_desc:
                        desc = (desc + '\n\n' + epg_desc).strip()
                    itens.append((name,url_,thumb,desc))
        
        if itens:
            try:
                itens = sorted(itens, key=ordenar_resolucao)
            except:
                pass
        return itens

    def series_cat(self):
        itens = []
        url_series = '{0}&action=get_series_categories'.format(self.player_api)
        vod_cat = self.http(url_series,'json_url')
        if vod_cat:
            for cat in vod_cat:
                name = cat['category_name']
                url = self.player_api + '&action=get_series&category_id='+cat['category_id']                
                if self.hide_adult == 'false':
                    itens.append((name,url))
                else:
                    if not any(s in name for s in self.adult_tags):
                        itens.append((name,url))
        return itens
    
    def series_list(self,url):
        itens = []
        ser_cat = self.http(url,'json_url')
        if ser_cat:
            for ser in ser_cat:	
                name = ser['name']
                url = self.player_api+'&action=get_series_info&series_id='+str(ser['series_id'])
                try:
                    thumb = ser['cover']
                    background = ser['backdrop_path'][0]
                    plot = ser['plot']
                    releaseDate = ser['releaseDate']
                    cast = str(ser['cast']).split()
                    rating_5based = ser['rating_5based']
                    episode_run_time = str(ser['episode_run_time'])
                    genre = ser['genre']
                except:
                    thumb = ''
                    plot = ''
                    releasedate = ''
                    cast = ('', '')
                    rating_5based = ''
                    episode_run_time = ''
                    genre = ''
                itens.append((name,url,thumb,background,plot,releaseDate,cast,rating_5based,episode_run_time,genre)) # series seasons
        return itens
    
    def series_seasons(self,url):
        itens = []
        ser_cat = self.http(url,'json_url')
        if ser_cat:
            for ser in ser_cat['episodes']:
                info = ser_cat['info']
                try:
                    thumb = info['cover']
                except:
                    thumb = ''
                try:
                    background = info['backdrop_path'][0]
                except:
                    background = ''
                name = 'Season - '+ser
                url_ = url+'&season_number='+str(ser)
                itens.append((name,url_,thumb,background)) # season list
        return itens
    
    def season_list(self,url):
        itens = []
        ser_cat = self.http(url,'json_url')
        info = ser_cat['info']
        ser_cat = ser_cat['episodes']
        parsed_url = urlparse(url)
        season_number = str(parse_qs(parsed_url.query)['season_number'][0])
        for ser in ser_cat[season_number]:
            url = self.play_series+str(ser['id'])+'.'+ser['container_extension']
            name = ser['title']
            try:
                thumb = ser['info']['movie_image']
            except:
                thumb = ''
            try:
                background = ser['info']['movie_image']
            except:
                background = ''
            try:
                plot = ser['info']['plot']
            except:
                plot = ''
            try:
                releasedate = ser['info']['releasedate']
            except:
                releasedate = ''
            try:
                cast = str(info['cast']).split()
            except:
                cast = ('', '')
            try:
                rating_5based = info['rating_5based']
            except:
                rating_5based = ''
            try:
                duration = str(ser['info']['duration'])
            except:
                duration = ''
            try:
                genre = info['genre']
            except:
                genre = ''
            itens.append((name,url,thumb,background,plot,releasedate,cast,rating_5based,duration,genre))
        return itens 

    def vod(self,url=''):
        # exemplo no addon
        # tipo = t[0]
        # if tipo == 'dir':
        #     d, name1, name2 = t        
        itens = []
        if not url:
            open = self.http(self.vod_url, mode='vod')
        else:
            open = self.http(url, 'vod')
        if open:
            all_cats = self.regex_get_all(open,'<channel>','</channel>')
            if all_cats:
                for a in all_cats:
                    if '<playlist_url>' in open:
                        name = str(self.b64(self.regex_from_to(a,'<title>','</title>'))).replace('?','')
                        url = self.check_protocol(self.regex_from_to(a,'<playlist_url>','</playlist_url>').replace('<![CDATA[','').replace(']]>',''))
                        if not 'All' in name: 
                            if self.hide_adult == 'false':
                                itens.append(('dir', name,url))
                            else:
                                if not any(s in name for s in self.adult_tags):
                                    itens.append(('dir', name,url))
                    else:
                        try:
                            name = self.b64(self.regex_from_to(a,'<title>','</title>'))
                            thumb= self.regex_from_to(a,'<desc_image>','</desc_image>').replace('<![CDATA[','').replace(']]>','')
                            url = self.check_protocol(self.regex_from_to(a,'<stream_url>','</stream_url>').replace('<![CDATA[','').replace(']]>',''))
                            desc = self.b64(self.regex_from_to(a,'<description>','</description>'))
                            plot = self.regex_from_to(desc,'PLOT:','\n')
                            try:
                                cast = self.regex_from_to(desc,'CAST:','\n')
                            except:
                                cast = ('', '')
                            ratin= self.regex_from_to(desc,'RATING:','\n')
                            year = self.regex_from_to(desc,'RELEASEDATE:','\n').replace(' ','-')
                            year = re.compile('-.*?-.*?-(.*?)-',re.DOTALL).findall(year)
                            runt = self.regex_from_to(desc,'DURATION_SECS:','\n')
                            genre= self.regex_from_to(desc,'GENRE:','\n')
                            background = ''
                            itens.append(('play', name, url, thumb, background,plot,str(year).replace("['","").replace("']",""),str(cast).split(),ratin,genre))
                        except:pass
        return itens                        


