#!/usr/bin/env python3
from urllib.parse import parse_qsl, urlencode
import sys
import os
import shutil
import subprocess
import xbmc
import xbmcplugin
import xbmcgui
import xbmcaddon
import xbmcvfs


addon = xbmcaddon.Addon()
pluginhandle = int(sys.argv[1])
addonID = addon.getAddonInfo('id')
addonPath = addon.getAddonInfo('path')
translation = addon.getLocalizedString
browser = addon.getSetting("browser") or "firefox"
osWin = xbmc.getCondVisibility('system.platform.windows')
osOsx = xbmc.getCondVisibility('system.platform.osx')
osLinux = xbmc.getCondVisibility('system.platform.linux')
useOwnProfile = addon.getSetting("useOwnProfile") == "true"
useCustomPath = addon.getSetting("useCustomPath") == "true"
customPath = xbmcvfs.translatePath(addon.getSetting("customPath"))

userDataFolder = xbmcvfs.translatePath("special://profile/addon_data/" + addonID)
profileFolder = os.path.join(userDataFolder, 'profile')
firefoxProfileFolder = os.path.join(userDataFolder, 'firefox-profile')
siteFolder = os.path.join(userDataFolder, 'sites')

os.makedirs(profileFolder, exist_ok=True)
os.makedirs(siteFolder, exist_ok=True)

youtubeUrl = "http://www.youtube.com/leanback"
vimeoUrl = "http://www.vimeo.com/couchmode"


def index():
    files = os.listdir(siteFolder)
    for file in files:
        if file.endswith(".link"):
            with open(os.path.join(siteFolder, file), 'r', encoding='utf-8') as fh:
                lines = fh.readlines()
            title = ""
            url = ""
            thumb = ""
            kiosk = "yes"
            stopPlayback = "no"
            for line in lines:
                entry = line[:line.find("=")]
                content = line[line.find("=")+1:]
                if entry == "title":
                    title = content.strip()
                elif entry == "url":
                    url = content.strip()
                elif entry == "thumb":
                    thumb = content.strip()
                elif entry == "kiosk":
                    kiosk = content.strip()
                elif entry == "stopPlayback":
                    stopPlayback = content.strip()
            addSiteDir(title, url, 'showSite', thumb, stopPlayback, kiosk)
    addDir("[ Vimeo Couchmode ]", vimeoUrl, 'showSite', os.path.join(addonPath, "vimeo.png"), "yes", "yes")
    addDir("[ Youtube Leanback ]", youtubeUrl, 'showSite', os.path.join(addonPath, "youtube.png"), "yes", "yes")
    addDir("[B]- "+translation(30001)+"[/B]", "", 'addSite', "")
    xbmcplugin.endOfDirectory(pluginhandle)


def addSite(site="", title=""):
    if site:
        filename = getFileName(title)
        content = "title="+title+"\nurl="+site+"\nthumb=DefaultFolder.png\nstopPlayback=no\nkiosk=yes"
        with open(os.path.join(siteFolder, filename + ".link"), 'w', encoding='utf-8') as fh:
            fh.write(content)
    else:
        keyboard = xbmc.Keyboard('', translation(30003))
        keyboard.doModal()
        if keyboard.isConfirmed() and keyboard.getText():
            title = keyboard.getText()
            keyboard = xbmc.Keyboard('http://', translation(30004))
            keyboard.doModal()
            if keyboard.isConfirmed() and keyboard.getText():
                url = keyboard.getText()
                keyboard = xbmc.Keyboard('no', translation(30009))
                keyboard.doModal()
                if keyboard.isConfirmed() and keyboard.getText():
                    stopPlayback = keyboard.getText()
                    keyboard = xbmc.Keyboard('yes', translation(30016))
                    keyboard.doModal()
                    if keyboard.isConfirmed() and keyboard.getText():
                        kiosk = keyboard.getText()
                        content = "title="+title+"\nurl="+url+"\nthumb=DefaultFolder.png\nstopPlayback="+stopPlayback+"\nkiosk="+kiosk
                        with open(os.path.join(siteFolder, getFileName(title) + ".link"), 'w', encoding='utf-8') as fh:
                            fh.write(content)
    xbmc.executebuiltin("Container.Refresh")


def getFileName(title):
    return ''.join(character for character in str(title) if character not in '/\\:?"*|<>').strip()


def getFullPath(path, url, useKiosk, userAgent):
    command = [path]
    if browser == "firefox":
        if useOwnProfile:
            command.extend(['--profile', firefoxProfileFolder])
        if useKiosk == "yes":
            command.append('--kiosk')
        command.append(url)
        return command
    if useOwnProfile:
        command.append('--user-data-dir=' + profileFolder)
    if userAgent:
        command.append('--user-agent=' + userAgent)
    command.extend([
        '--start-maximized',
        '--disable-translate',
        '--disable-new-tab-first-run',
        '--no-default-browser-check',
        '--no-first-run',
    ])
    if useKiosk == "yes":
        command.append('--kiosk')
    command.append(url)
    return command


def getBrowserPath():
    if useCustomPath and os.path.isfile(customPath):
        return customPath

    if browser == "firefox":
        if osWin:
            candidates = [
                shutil.which('firefox.exe'),
                r'C:\Program Files\Mozilla Firefox\firefox.exe',
                r'C:\Program Files (x86)\Mozilla Firefox\firefox.exe',
            ]
        elif osOsx:
            candidates = [
                shutil.which('firefox'),
                '/Applications/Firefox.app/Contents/MacOS/firefox',
            ]
        elif osLinux:
            candidates = [shutil.which('firefox'), '/usr/bin/firefox']
        else:
            candidates = []
    elif browser == "chrome":
        if osWin:
            candidates = [
                shutil.which('chrome.exe'),
                r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
            ]
        elif osOsx:
            candidates = [
                shutil.which('google-chrome'),
                '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            ]
        elif osLinux:
            candidates = [shutil.which('google-chrome'), '/usr/bin/google-chrome']
        else:
            candidates = []
    else:
        candidates = []

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def showSite(url, stopPlayback, kiosk, userAgent):
    if stopPlayback == "yes":
        xbmc.Player().stop()
    path = getBrowserPath()
    if path:
        subprocess.Popen(getFullPath(path, url, kiosk, userAgent))
    else:
        xbmc.executebuiltin('XBMC.Notification(Info:,'+str(translation(30005))+'!,5000)')
        addon.openSettings()


def removeSite(title):
    os.remove(os.path.join(siteFolder, getFileName(title)+".link"))
    xbmc.executebuiltin("Container.Refresh")


def editSite(title):
    filenameOld = getFileName(title)
    file = os.path.join(siteFolder, filenameOld+".link")
    with open(file, 'r', encoding='utf-8') as fh:
        lines = fh.readlines()
    title = ""
    url = ""
    kiosk = "yes"
    thumb = "DefaultFolder.png"
    stopPlayback = "no"
    for line in lines:
        entry = line[:line.find("=")]
        content = line[line.find("=")+1:]
        if entry == "title":
            title = content.strip()
        elif entry == "url":
            url = content.strip()
        elif entry == "kiosk":
            kiosk = content.strip()
        elif entry == "thumb":
            thumb = content.strip()
        elif entry == "stopPlayback":
            stopPlayback = content.strip()
    oldTitle = title
    keyboard = xbmc.Keyboard(title, translation(30003))
    keyboard.doModal()
    if keyboard.isConfirmed() and keyboard.getText():
        title = keyboard.getText()
        keyboard = xbmc.Keyboard(url, translation(30004))
        keyboard.doModal()
        if keyboard.isConfirmed() and keyboard.getText():
            url = keyboard.getText()
            keyboard = xbmc.Keyboard(stopPlayback, translation(30009))
            keyboard.doModal()
            if keyboard.isConfirmed() and keyboard.getText():
                stopPlayback = keyboard.getText()
                keyboard = xbmc.Keyboard(kiosk, translation(30016))
                keyboard.doModal()
                if keyboard.isConfirmed() and keyboard.getText():
                    kiosk = keyboard.getText()
                    content = "title="+title+"\nurl="+url+"\nthumb="+thumb+"\nstopPlayback="+stopPlayback+"\nkiosk="+kiosk
                    with open(os.path.join(siteFolder, getFileName(title) + ".link"), 'w', encoding='utf-8') as fh:
                        fh.write(content)
                    if title != oldTitle:
                        os.remove(os.path.join(siteFolder, filenameOld+".link"))
    xbmc.executebuiltin("Container.Refresh")


def parameters_string_to_dict(parameters):
    return dict(parse_qsl(parameters.lstrip('?'), keep_blank_values=True))


def addDir(name, url, mode, iconimage, stopPlayback="", kiosk=""):
    plugin_url = sys.argv[0] + '?' + urlencode({
        'url': url,
        'mode': mode,
        'stopPlayback': stopPlayback,
        'kiosk': kiosk,
    })
    item = xbmcgui.ListItem(name, path=plugin_url)
    item.setArt({'icon': 'DefaultFolder.png', 'thumb': iconimage})
    item.getVideoInfoTag().setTitle(name)
    return xbmcplugin.addDirectoryItem(
        handle=pluginhandle, url=plugin_url, listitem=item, isFolder=True
    )


def addSiteDir(name, url, mode, iconimage, stopPlayback, kiosk):
    plugin_url = sys.argv[0] + '?' + urlencode({
        'url': url,
        'mode': mode,
        'stopPlayback': stopPlayback,
        'kiosk': kiosk,
    })
    item = xbmcgui.ListItem(name, path=plugin_url)
    item.setArt({'icon': 'DefaultFolder.png', 'thumb': iconimage})
    item.getVideoInfoTag().setTitle(name)
    edit_url = 'plugin://' + addonID + '/?' + urlencode({'mode': 'editSite', 'url': name})
    remove_url = 'plugin://' + addonID + '/?' + urlencode({'mode': 'removeSite', 'url': name})
    item.addContextMenuItems([
        (translation(30006), 'RunPlugin(' + edit_url + ')'),
        (translation(30002), 'RunPlugin(' + remove_url + ')'),
    ])
    return xbmcplugin.addDirectoryItem(
        handle=pluginhandle, url=plugin_url, listitem=item, isFolder=True
    )

params = parameters_string_to_dict(sys.argv[2])
mode = params.get('mode', '')
name = params.get('name', '')
url = params.get('url', '')
stopPlayback = params.get('stopPlayback', 'no')
kiosk = params.get('kiosk', 'yes')
userAgent = params.get('userAgent', '')


if mode == 'addSite':
    addSite()
elif mode == 'showSite':
    showSite(url, stopPlayback, kiosk, userAgent)
elif mode == 'removeSite':
    removeSite(url)
elif mode == 'editSite':
    editSite(url)
else:
    index()
