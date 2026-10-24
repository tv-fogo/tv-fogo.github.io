# -*- coding: utf-8 -*-
import xbmc

# Ativa a camada de DNS compatível com DoH e sem IPv6 globalmente no processo
try:
    from extra_lib.dnscompat import DNSOverride
    DNSOverride()
except Exception:
    try:
        from dnscompat import DNSOverride
        DNSOverride()
    except Exception:
        pass

try:
    from extra_lib.proxy import start_background as start_proxy
except Exception:
    try:
        from proxy import start_background as start_proxy
    except Exception:
        start_proxy = None


class DnsServiceMonitor(xbmc.Monitor):
    def __init__(self):
        super(DnsServiceMonitor, self).__init__()
        self.kodi_shutdown = False

    def onNotification(self, sender, method, data):
        # Se o Kodi está fechando/reiniciando/suspendendo, marca o flag
        if method in (
            "System.OnQuit",
            "System.OnRestart",
            "System.OnSleep",
            "System.OnPowerdown",
        ):
            self.kodi_shutdown = True


monitor = DnsServiceMonitor()

try:
    # Sobe o proxy (idempotente: o customdns também o inicia na primeira
    # consulta DoH) e mantém o serviço vivo até o Kodi pedir encerramento.
    if start_proxy is not None:
        start_proxy()
    while not monitor.waitForAbort(5):
        pass
finally:
    log_fim = "[customdns] service.py do Tv Fogo finalizado."
    try:
        xbmc.log(log_fim, getattr(xbmc, 'LOGINFO', 1))
    except Exception:
        pass