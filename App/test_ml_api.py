import sys
import os

# Adiciona raiz ao path para importar modulos do App
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Aviso: python-dotenv nao instalado. Variaveis podem falhar se nao estiverem no sistema.")

try:
    from App.collectors.mercadolivre.collector import coletar
    from App.utils.mercadolivre_api import MercadoLivreAPI
except ImportError as e:
    print(f"Erro de importacao: {e}")
    print("Verifique se moveu 'mercadolivre_api.py' para 'App/utils/'.")
    sys.exit(1)

def main():
    print("========================================")
    print("  TESTE DE API - MERCADO LIVRE")
    print("========================================")
    
    link = input("Cole o link do produto ML (ex: https://.../MLB-...): ").strip()
    if not link:
        print("Link vazio.")
        return

    # 1. Verifica credenciais
    api = MercadoLivreAPI()
    if not api.is_configured():
        print("\n[ERRO] Credenciais (Tokens) nao encontradas no .env")
        return

    print(f"\n[INFO] Credenciais carregadas. Testando coleta...")

    # 2. Executa o coletor sem driver (forca teste da API)
    resultado = coletar(driver=None, link=link)
    
    print("\n--- RESULTADO ---")
    print(f"Preco a vista: {resultado.get('avista')}")
    print(f"Status:        {resultado.get('status')}")
    
    if "API" in str(resultado.get('status')):
        print("\n[SUCESSO] A API retornou os dados corretamente!")
    else:
        print("\n[FALHA] A API nao funcionou. Verifique o status acima.")

if __name__ == "__main__":
    main()