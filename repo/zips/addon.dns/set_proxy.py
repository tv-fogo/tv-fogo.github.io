import json
import xbmc
import xbmcgui
# https://kodi.wiki/view/JSON-RPC_API/v12

def get_setting(setting_name):
    """Obtém o valor de uma configuração"""
    command = {
        "jsonrpc": "2.0",
        "method": "Settings.GetSettingValue",
        "params": {
            "setting": setting_name
        },
        "id": 1
    }
    response = xbmc.executeJSONRPC(json.dumps(command))
    result = json.loads(response)
    if "error" in result:
        xbmc.log(f"Erro ao obter configuração {setting_name}: {result['error']}", xbmc.LOGERROR)
        return None
    return result.get("result", {}).get("value")

def set_setting(setting_name, value):
    """Define o valor de uma configuração"""
    command = {
        "jsonrpc": "2.0",
        "method": "Settings.SetSettingValue",
        "params": {
            "setting": setting_name,
            "value": value
        },
        "id": 1
    }
    response = xbmc.executeJSONRPC(json.dumps(command))
    result = json.loads(response)
    if "error" in result:
        xbmc.log(f"Erro ao definir {setting_name}: {result['error']}", xbmc.LOGERROR)
        return False
    return True

def is_valid_ip(ip):
    """Valida um endereço IP"""
    try:
        parts = ip.split('.')
        return len(parts) == 4 and all(0 <= int(part) <= 255 for part in parts)
    except (ValueError, AttributeError):
        return False

def is_valid_port(port):
    """Valida uma porta"""
    try:
        return 0 < int(port) <= 65535
    except (ValueError, TypeError):
        return False

def set_kodi_proxy(ip, port, proxy_type=0, username=None, password=None):
    """
    Configura o proxy do Kodi
    
    :param ip: Endereço IP do proxy
    :param port: Porta do proxy
    :param proxy_type: Tipo de proxy (0-5, padrão 1 para HTTP)
    :param username: Nome de usuário (opcional)
    :param password: Senha (opcional)
    """
    # Validações iniciais
    if not is_valid_ip(ip):
        xbmcgui.Dialog().ok("Erro", "Endereço IP inválido.")
        return False
        
    if not is_valid_port(port):
        xbmcgui.Dialog().ok("Erro", "Porta inválida.")
        return False
    
    if proxy_type not in [0, 1, 2, 3, 4, 5]:
        xbmcgui.Dialog().ok("Erro", "Tipo de proxy inválido.")
        return False
    
    # Log das configurações atuais
    current_settings = {
        'type': get_setting("network.httpproxytype"),
        'server': get_setting("network.httpproxyserver"),
        'port': get_setting("network.httpproxyport"),
        'enabled': get_setting("network.usehttpproxy"),
        'username': get_setting("network.httpproxyusername"),
        'password': get_setting("network.httpproxypassword")
    }
    xbmc.log(f"Configurações atuais do proxy: {current_settings}", xbmc.LOGINFO)
    
    needs_restart = False
    success = True
    
    # Configurar tipo de proxy
    if current_settings['type'] != proxy_type:
        if not set_setting("network.httpproxytype", proxy_type):
            xbmcgui.Dialog().ok("Erro", "Falha ao configurar o tipo de proxy.")
            success = False
        else:
            needs_restart = True
    
    # Configurar servidor
    if success and current_settings['server'] != ip:
        if not set_setting("network.httpproxyserver", ip):
            xbmcgui.Dialog().ok("Erro", "Falha ao configurar o servidor proxy.")
            success = False
        else:
            needs_restart = True
    
    # Configurar porta
    if success and current_settings['port'] != port:
        if not set_setting("network.httpproxyport", int(port)):
            xbmcgui.Dialog().ok("Erro", "Falha ao configurar a porta do proxy.")
            success = False
        else:
            needs_restart = True
    
    # Configurar credenciais (se fornecidas)
    if success and username and password:
        if not set_setting("network.httpproxyusername", username):
            xbmc.log("Aviso: Falha ao configurar nome de usuário", xbmc.LOGWARNING)
        
        if not set_setting("network.httpproxypassword", password):
            xbmc.log("Aviso: Falha ao configurar senha", xbmc.LOGWARNING)
    
    # Ativar proxy
    if success and not current_settings['enabled']:
        if not set_setting("network.usehttpproxy", True):
            xbmcgui.Dialog().ok("Erro", "Falha ao ativar o proxy.")
            success = False
        else:
            needs_restart = True
    
    # Feedback para o usuário
    if not success:
        xbmcgui.Dialog().ok("Erro", "Não foi possível configurar completamente o proxy dns.")
        return False
    elif needs_restart:
        xbmcgui.Dialog().ok("CLOUDFLARE DNS", f"Proxy dns configurado para {ip}:{port}.\nReinicie o Kodi para aplicar as alterações.")
    
    return True


def _same_proxy_value(value, expected):
    try:
        return str(value).strip() == str(expected).strip()
    except Exception:
        return False

def disable_addon_proxy_if_active(ip, port):
    """
    Desativa o proxy do Kodi somente se ele ainda estiver apontado para o
    proxy local deste addon.

    Uso: desativação/desinstalação do addon.
    Não deve ser chamado no fechamento/reinício normal do Kodi, para preservar
    o comportamento estável da versão 1.0.0.
    """
    try:
        enabled = get_setting("network.usehttpproxy")
        server = get_setting("network.httpproxyserver")
        current_port = get_setting("network.httpproxyport")

        if enabled and _same_proxy_value(server, ip) and _same_proxy_value(current_port, int(port)):
            xbmc.log("[CLOUDFLARE DNS] Desativando proxy do addon no Kodi.", xbmc.LOGINFO)
            ok = set_setting("network.usehttpproxy", False)

            # Limpeza leve: deixa claro que o proxy deste addon não ficou preso.
            # Se algum Kodi rejeitar string vazia/porta 0, o principal já foi feito: usehttpproxy=False.
            try:
                set_setting("network.httpproxyserver", "")
            except Exception:
                pass
            try:
                set_setting("network.httpproxyport", 0)
            except Exception:
                pass

            return bool(ok)

        xbmc.log("[CLOUDFLARE DNS] Proxy atual não pertence ao addon; nada a restaurar.", xbmc.LOGINFO)
        return True
    except Exception as e:
        xbmc.log(f"[CLOUDFLARE DNS] Erro ao desativar proxy do addon: {e}", xbmc.LOGERROR)
        return False