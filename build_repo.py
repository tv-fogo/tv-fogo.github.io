# -*- coding: utf-8 -*-
import os
import hashlib
import zipfile
import re
import shutil
import subprocess

class GeradorDeRepositorio:
    """
    Gera os arquivos addons.xml e addons.xml.md5 para um repositório Kodi.
    """

    def __init__(self):
        # Define o caminho base usando a localização deste script
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.caminho_repo = os.path.join(self.base_dir, "repo")
        self.caminho_zips = os.path.join(self.base_dir, "repo", "zips")
        self.caminho_addons_xml = os.path.join(self.base_dir, "repo", "addons.xml")
        self.caminho_addons_xml_md5 = os.path.join(self.base_dir, "repo", "addons.xml.md5")

        print(f"Diretório base: {self.base_dir}")

        self._garantir_estrutura_repo()
        self._compactar_addons()
        self._gerar_arquivo_addons()
        self._gerar_arquivo_md5()
        self._finalizar_repo()
        
        # Passo extra: Força o Git a reconhecer os arquivos
        self._git_force_add()
        
        print("\nArquivos do repositório gerados com sucesso!")

    def _garantir_estrutura_repo(self):
        """Garante que a estrutura do repositório exista antes da geração."""
        os.makedirs(self.caminho_zips, exist_ok=True)

    def _finalizar_repo(self):
        """Copia o zip do repositório para a pasta raiz e atualiza o index.html."""
        print("\nFinalizando estrutura do repositório...")
        
        zip_name = ""
        try:
            repo_addon_id = "repository.gloriosotv"
            repo_addon_path = os.path.join(self.caminho_zips, repo_addon_id)
            
            with open(os.path.join(repo_addon_path, "addon.xml"), "r", encoding="utf-8") as f:
                xml_content = f.read()
            version_match = re.search(r'version="([^"]+)"', xml_content)
            if not version_match:
                print("  [ERRO] Não foi possível encontrar a versão do repositório.")
                return

            version = version_match.group(1)
            zip_name = f"{repo_addon_id}-{version}.zip"
            
            origem = os.path.join(repo_addon_path, zip_name)
            destino = os.path.join(self.base_dir, zip_name)

            if os.path.exists(origem):
                shutil.copy2(origem, destino)
                print(f"  [OK] '{zip_name}' copiado para a pasta raiz.")
                # Atualiza o index.html com o novo nome do zip
                self._atualizar_index_html(zip_name)
            else:
                print(f"  [AVISO] O arquivo ZIP do repositório '{origem}' não foi encontrado para cópia.")
                return

        except Exception as e:
            print(f"  [ERRO] Falha ao finalizar o repositório: {e}")

    def _atualizar_index_html(self, zip_name):
        try:
            index_path = os.path.join(self.base_dir, "index.html")
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    html = f.read()
                
                # Atualiza o link href e o texto do botão para o nome do arquivo
                html = re.sub(r'href="repository\.gloriosotv-.*?\.zip"', f'href="{zip_name}"', html)
                html = re.sub(r'>repository\.gloriosotv-.*?\.zip<', f'>{zip_name}<', html)
                
                with open(index_path, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"  [OK] index.html atualizado apontando para: {zip_name}")
        except Exception as e:
            print(f"  [ERRO] Não foi possível atualizar o index.html: {e}")

    def _gerar_arquivo_addons(self):
        addons = []
        
        if not os.path.exists(self.caminho_zips):
            print(f"ERRO CRÍTICO: A pasta '{self.caminho_zips}' não existe!")
            return

        print(f"Lendo addons em '{self.caminho_zips}'...")
        for root, _, files in os.walk(self.caminho_zips):
            for file in files:
                if not file.endswith(".zip"):
                    continue
                
                caminho_zip = os.path.join(root, file)
                try:
                    with zipfile.ZipFile(caminho_zip, 'r') as addon_zip:
                        for info_zip in addon_zip.infolist():
                            if info_zip.filename.endswith('addon.xml') and not info_zip.is_dir():
                                partes = info_zip.filename.split('/')
                                if len(partes) == 2 and partes[1] == 'addon.xml':
                                    # Lê o arquivo usando utf-8
                                    conteudo = addon_zip.read(info_zip.filename).decode('utf-8')
                                    
                                    # 2. Limpeza Infalível: Encontra a primeira tag <addon e corta tudo antes dela
                                    pos_addon = conteudo.find('<addon')
                                    if pos_addon >= 0:
                                        conteudo = conteudo[pos_addon:]
                                    else:
                                        # Fallback se não achar <addon (improvável)
                                        conteudo = re.sub(r'<\?xml.*?\?>', '', conteudo, flags=re.DOTALL).strip()

                                    addons.append(conteudo)
                                    print(f"  [OK] Processado: {partes[0]}")
                                    break
                except Exception as e:
                    print(f"  [ERRO] Falha em {file}: {e}")

        if not addons:
            print("AVISO: Nenhum addon foi encontrado nos zips!")
        
        xml_final = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n'
        xml_final += "\n".join(addons)
        xml_final += "\n</addons>"

        with open(self.caminho_addons_xml, "w", encoding="utf-8") as f:
            f.write(xml_final)
        print(f"\nArquivo 'addons.xml' salvo com {len(addons)} addons.")

    def _compactar_addons(self):
        print("\nVerificando pastas para criar novos ZIPs...")
        for nome_addon in os.listdir(self.caminho_zips):
            caminho_addon = os.path.join(self.caminho_zips, nome_addon)
            
            if os.path.isdir(caminho_addon) and "addon.xml" in os.listdir(caminho_addon):
                try:
                    with open(os.path.join(caminho_addon, "addon.xml"), "r", encoding="utf-8") as f:
                        xml_content = f.read()
                    
                    id_match = re.search(r'<addon[^>]+id="([^"]+)"', xml_content)
                    ver_match = re.search(r'<addon[^>]+version="([^"]+)"', xml_content)
                    
                    if id_match and ver_match:
                        addon_id = id_match.group(1)
                        version = ver_match.group(1)
                        zip_name = f"{addon_id}-{version}.zip"
                        zip_path = os.path.join(caminho_addon, zip_name)
                        
                        # Remove zips antigos da pasta para evitar confusão
                        for file in os.listdir(caminho_addon):
                            caminho_arquivo = os.path.join(caminho_addon, file)
                            if (file.endswith(".zip") and file != zip_name
                                    and os.path.isfile(caminho_arquivo)):
                                os.remove(caminho_arquivo)
                                print(f"  - Removido zip antigo: {file}")
                        
                        print(f"  - Compactando {addon_id} v{version}...")
                        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                            for root, dirs, files in os.walk(caminho_addon):
                                for file in files:
                                    if file.endswith(".zip"): continue
                                    file_path = os.path.join(root, file)
                                    rel_path = os.path.relpath(file_path, self.caminho_zips)
                                    zf.write(file_path, rel_path)
                except Exception as e:
                    print(f"ERRO ao compactar {nome_addon}: {e}")

    def _gerar_arquivo_md5(self):
        try:
            with open(self.caminho_addons_xml, 'rb') as f:
                m = hashlib.md5(f.read()).hexdigest()
            
            with open(self.caminho_addons_xml_md5, "w", encoding="utf-8") as f:
                f.write(m)
            print(f"MD5 gerado: {m}")
        except Exception as e:
            print(f"ERRO no MD5: {e}")

    def _git_force_add(self):
        """Força a adição dos arquivos da pasta repo ao Git, ignorando o .gitignore"""
        try:
            print("\nExecutando GIT ADD forçado na pasta repo...")
            # Adiciona a pasta repo inteira, forçando a inclusão de zips ignorados
            subprocess.check_call(['git', 'add', '--force', 'repo'], cwd=self.base_dir)
            print("  [SUCESSO] Arquivos adicionados ao stage do Git.")
        except Exception as e:
            print(f"  [AVISO] Não foi possível executar git add: {e}")

if __name__ == "__main__":
    GeradorDeRepositorio()