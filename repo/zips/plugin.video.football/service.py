# -*- coding: utf-8 -*-
from helpers import xbmc, log
import localproxy


def main():
    monitor = xbmc.Monitor()
    started_once = False
    try:
        privacy_enabled, secure_proxy_ready = localproxy.privacy_status()
        if secure_proxy_ready:
            log('Proxy HTTPS configurado; conexões externas serão encaminhadas por ele.')
        elif privacy_enabled:
            log('Modo de privacidade ativo sem proxy HTTPS válido; conexões externas serão bloqueadas até configurar um.')
        else:
            log('Nenhum proxy HTTPS configurado; conexões externas seguem diretamente.')

        while not monitor.abortRequested():
            try:
                if not localproxy.is_running(require_owned=True):
                    if localproxy.start(owner='service', force_own=True):
                        if not started_once:
                            log('Servico de proxy Cloudflare iniciado em porta dinamica.')
                        else:
                            log('Servico de proxy Cloudflare recuperado em nova porta dinamica.')
                        started_once = True
                    else:
                        log('Servico de proxy Cloudflare nao confirmou listener local dinamico.')
            except Exception as exc:
                try:
                    log('Falha ao supervisionar servico de proxy: {0}'.format(str(exc)))
                except Exception:
                    pass
            # Além de encerrar imediatamente no abort do Kodi, a janela curta
            # permite recuperar um listener que tenha morrido inesperadamente.
            if monitor.waitForAbort(5):
                break
    finally:
        try:
            localproxy.stop()
        except Exception:
            pass


if __name__ == '__main__':
    main()
