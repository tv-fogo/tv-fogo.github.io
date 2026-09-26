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

# O entrypoint do customdns e a funcao main(). Ela agora aceita o monitor
# do Kodi e encerra o proxy sozinha quando o Kodi esta fechando.
try:
    from extra_lib.customdns import main as server
except Exception:
    from customdns import main as server


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
    # Bloqueia aqui rodando o proxy; o main() sai em até ~1s quando o
    # Kodi setar abort (fechar/reiniciar), encerrando tudo limpo.
    server(monitor=monitor)
finally:
    log_fim = "[customdns] service.py do Glorioso TV finalizado."
    try:
        xbmc.log(log_fim, getattr(xbmc, 'LOGINFO', 1))
    except Exception:
        pass
