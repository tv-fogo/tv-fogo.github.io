# -*- coding: utf-8 -*-
import xbmc

from proxyhttp import LISTEN_HOST, LISTEN_PORT, server
from set_proxy import set_kodi_proxy, disable_addon_proxy_if_active


class DnsServiceMonitor(xbmc.Monitor):
    def __init__(self):
        super(DnsServiceMonitor, self).__init__()
        self.kodi_shutdown = False

    def onNotification(self, sender, method, data):
        # Se o Kodi está fechando/reiniciando/suspendendo, NÃO restaurar o proxy.
        # Isso preserva o comportamento estável da versão 1.0.0 no boot/reboot.
        if method in (
            "System.OnQuit",
            "System.OnRestart",
            "System.OnSleep",
            "System.OnPowerdown",
        ):
            self.kodi_shutdown = True


monitor = DnsServiceMonitor()

try:
    set_kodi_proxy(LISTEN_HOST, LISTEN_PORT)
    server(monitor=monitor)
finally:
    # Se o serviço parou sem evento de fechamento/reinício do Kodi, normalmente é
    # desativação/desinstalação do addon. Neste caso, limpar somente o proxy deste addon.
    if not getattr(monitor, "kodi_shutdown", False):
        disable_addon_proxy_if_active(LISTEN_HOST, LISTEN_PORT)