# -*- coding: utf-8 -*-
# Author: Lord Grey
# Created : 01.03.2019
# License: GPL v.3 https://www.gnu.org/copyleft/gpl.html

import re
import xbmcgui
import xbmcplugin
import resources.lib.helper as helper


def get_categories(url='https://www.xvideos.com'):
    '''Parses the Xvideos homepage and returns available category links.'''
    hardcoded = 'https://www.xvideos.com'
    categories = []
    soup = helper.get_soup(url)
    cat_list = soup.find('ul', id='main-cats-sub-list')
    if not cat_list:
        return categories

    for a in cat_list.find_all('a', href=True):
        href = a['href']
        title = a.text.strip()
        if not href.startswith('/'):
            continue
        if not (href.startswith('/c/') or href.startswith('/gay') or href.startswith('/shemale')):
            continue

        if href.startswith('/'):
            href = hardcoded + href

        categories.append({'title': title, 'link': href})

    return categories


def get_vids(url, category='none'):
    '''crawls a given url form xvideos.com for videos
    and returns them as a list of dicts
    if a catergory is given it will be added to the dict
    '''
    hardcoded = 'https://www.xvideos.com'
    video_info = []
    videos = []
    soup = helper.get_soup(url)
    
    # Seletores atualizados para os blocos de vídeo
    videos = soup.find_all("div", class_="thumb-block")
    if not videos:
        videos = soup.find_all("article", class_="thumb-block")

    page = '1'
    next_url = None
    pagination = soup.find("div", class_="pagination")
    if pagination:
        page_num = None
        active_tag = pagination.find(class_=["active", "current"])
        if active_tag:
            page_num = active_tag.get_text(strip=True)
        else:
            # fallback to explicit page numbers when the active/current class is not present
            page_numbers = []
            for tag in pagination.find_all(['a', 'span', 'li']):
                text = tag.get_text(strip=True)
                if not text or text.lower() == 'next':
                    continue
                if text.isdigit():
                    page_numbers.append(int(text))
            if page_numbers:
                page_num = str(max(page_numbers))

        if page_num:
            page = page_num

        # Try to get the real next page URL from the pagination links
        next_link_tag = None
        for a in pagination.find_all('a', href=True):
            if a.get_text(strip=True).lower() == 'next':
                next_link_tag = a
                break

        if not next_link_tag:
            next_link_tag = pagination.find('a', class_='next', href=True) or pagination.find('a', attrs={'rel': 'next'}, href=True)

        if next_link_tag:
            href = next_link_tag['href']
            if href.startswith('/'):
                next_url = hardcoded + href
            elif href.startswith('//'):
                next_url = 'https:' + href
            elif not href.startswith(('http://', 'https://')):
                next_url = hardcoded + '/' + href.lstrip('/')
            else:
                next_url = href

    for info in videos:
        # Mantendo a lógica de busca interna ou fallback para o bloco principal
        inside = info.find("div", class_="thumb-inside") or info
        under = info.find("div", class_="thumb-under") or info
        
        # O link e título agora costumam estar no primeiro 'a' dentro do bloco
        title_tag = under.find("a", href=True)
        title = title_tag.get('title') if title_tag and title_tag.get('title') else title_tag.text.strip() if title_tag else 'Untitled'
        
        img = inside.find('img')
        if img:
            # Expandido para capturar atributos de lazy-loading atuais
            thumb = img.get('data-src') or img.get('data-lazy-src') or img.get('data-sdk-src') or img.get('data-original') or img.get('src')
        else:
            thumb = None

        # Seletores de qualidade (HD) e duração
        res_tag = inside.find(class_="video-hd-mark") or inside.find("span", class_="video-hd-mark") or inside.find("span", class_="thumb-info")
        duration_tag = under.find("span", class_="duration")
        duration = helper.convert_duration(duration_tag.text) if duration_tag else 0

        views = None
        views_tag = under.find("span", class_="sprfluous")
        if views_tag:
            # Captura o texto após o ícone/span de visualizações
            views = views_tag.next_sibling
        
        if not views and duration_tag:
            # Fallback caso a estrutura de visualização mude
            next_sibling = duration_tag.next_sibling
            views = next_sibling.strip() if next_sibling and isinstance(next_sibling, str) else None

        if views:
            views = views.strip()
            if views.startswith('•'):
                views = views[1:].strip()
        else:
            views = '0'

        try:
            # Classe 'name' é o padrão para canais/uploaders
            uploader = under.find("span", class_="name").text.strip()
        except AttributeError:
            uploader = "Unknown"

        res = res_tag.text.strip() if res_tag else None

        href = title_tag.get('href') if title_tag and title_tag.get('href') else url
        if href.startswith('/'):
            href = hardcoded + href
        elif href.startswith('//'):
            href = 'https:' + href
        elif not href.startswith(('http://', 'https://')):
            href = hardcoded + '/' + href.lstrip('/')

        video_info.append(
            dict([
                ('title', title),
                ('link', href),
                ('duration', duration),
                ('thumb', thumb),
                ('res', res),
                ('views', views),
                ('uploader', uploader),
                ('category', category),
                ('page', page)
            ]))

    return video_info, next_url


def play_video(_handle, video):
    """
    Play a video by the provided path.

    :param path: Fully-qualified video URL
    :type path: str
    """
    soup = helper.get_soup(video)
    m3u_link = None

    for script in soup.find_all('script'):
        text = script.string or script.text
        if not text:
            continue

        match = re.search(r"setVideoHLS\(\s*['\"]([^'\"]+)['\"]\s*\)", text)
        if match:
            m3u_link = match.group(1)
            break

    if not m3u_link:
        match = re.search(r'"contentUrl"\s*:\s*"([^"]+)"', soup.text)
        if match:
            m3u_link = match.group(1)

    if not m3u_link:
        match = re.search(r"setVideoUrl(?:Low|High)\(\s*['\"]([^'\"]+)['\"]\s*\)", soup.text)
        if match:
            m3u_link = match.group(1)

    if not m3u_link:
        raise RuntimeError('Unable to find playable stream URL on Xvideos page')

    play_item = xbmcgui.ListItem(path=m3u_link)
    xbmcplugin.setResolvedUrl(_handle, True, listitem=play_item)

