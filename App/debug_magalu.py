import sys
import os
import requests

# Adiciona raiz ao path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def main():
    print("=== DIAGNOSTICO DE AUTENTICACAO MAGALU ===")
    
    client_id = (os.getenv("MAGALU_API_CLIENT_ID") or os.getenv("MAGALU_API_KEY_ID") or "").strip()
    client_secret = (os.getenv("MAGALU_API_CLIENT_SECRET") or os.getenv("MAGALU_API_KEY_SECRET") or "").strip()
    token_url = (os.getenv("MAGALU_API_TOKEN_URL") or "https://id.magalu.com/oauth/token").strip()

    if not client_id or not client_secret:
        print("[ERRO] Credenciais nao encontradas no .env")
        print("Verifique MAGALU_API_CLIENT_ID e MAGALU_API_CLIENT_SECRET")
        return

    print(f"URL: {token_url}")
    print(f"Client ID: {client_id}")
    print(f"Client Secret: {'*' * 4}...{'*' * 4} (len={len(client_secret)})")

    # Teste 1: Basic Auth (Padrao OAuth2)
    print("\n--- Tentativa 1: Basic Auth (Padrao) ---")
    try:
        resp = requests.post(
            token_url,
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=10
        )
        print(f"Status: {resp.status_code}")
        print(f"Resposta: {resp.text}")
    except Exception as e:
        print(f"Erro: {e}")

    # Teste 2: Body Auth (Fallback)
    print("\n--- Tentativa 2: Body Auth (Credenciais no corpo) ---")
    try:
        resp = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret
            },
            timeout=10
        )
        print(f"Status: {resp.status_code}")
        print(f"Resposta: {resp.text}")
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    main()