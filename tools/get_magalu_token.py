import os
import sys

try:
    import requests
except ImportError:
    print("A biblioteca 'requests' nao foi encontrada.")
    print("Instale com: pip install requests")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def main():
    print("\n========================================")
    print("  GERADOR DE REFRESH TOKEN - MAGALU API")
    print("========================================\n")
    
    # 1. Obter credenciais
    client_id = (os.getenv("MAGALU_API_CLIENT_ID") or os.getenv("MAGALU_API_KEY_ID") or "").strip()
    client_secret = (os.getenv("MAGALU_API_CLIENT_SECRET") or os.getenv("MAGALU_API_KEY_SECRET") or "").strip()

    if not client_id:
        client_id = input("Digite seu Client ID (Key ID): ").strip()
    if not client_secret:
        client_secret = input("Digite seu Client Secret (Key Secret): ").strip()
    
    if not client_id or not client_secret:
        print("\n[Erro] Client ID e Client Secret sao obrigatorios.")
        return

    # 2. Redirect URI
    print("\n--- CONFIGURACAO DE REDIRECT URI ---")
    print("A Redirect URI deve ser EXATAMENTE a mesma configurada no seu App no painel da Magalu.")
    print("Exemplos comuns: https://www.google.com.br ou http://localhost:8000/callback")
    redirect_uri = input("Digite a Redirect URI: ").strip()
    if not redirect_uri:
        print("\n[Erro] Redirect URI e obrigatoria.")
        return

    # 3. Gerar URL de autorizacao
    auth_url = (
        f"https://id.magalu.com/authorize"
        f"?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}"
    )

    print("\n--- PASSO 1: AUTORIZACAO ---")
    print(f"1. Acesse este link no navegador:\n\n{auth_url}\n")
    print("2. Faca login na sua conta Magalu Marketplace e clique em 'Autorizar'.")
    print(f"3. Voce sera redirecionado para {redirect_uri}?code=...")
    
    # 4. Receber o code
    code_input = input("\nCole a URL completa de redirecionamento ou apenas o codigo: ").strip()
    
    code = code_input
    if "error=" in code_input:
        print("\n[Erro] A URL colada indica um erro de autorizacao (ex: acesso negado ou cancelado).")
        return

    if "code=" in code_input:
        try:
            code = code_input.split("code=")[1].split("&")[0]
        except IndexError:
            pass
            
    if not code:
        print("\n[Erro] Codigo nao fornecido.")
        return

    print(f"\nUsando codigo: {code}")

    # 5. Trocar code por tokens
    print("\n--- PASSO 2: OBTENDO TOKENS ---")
    token_url = "https://id.magalu.com/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    try:
        print("Trocando codigo por token...")
        response = requests.post(token_url, data=payload, auth=(client_id, client_secret))
        
        # Se falhar com 400/401, tenta enviar credenciais no corpo (fallback para alguns tipos de app)
        if response.status_code >= 400:
            payload_body = payload.copy()
            payload_body["client_id"] = client_id
            payload_body["client_secret"] = client_secret
            response = requests.post(token_url, data=payload_body)

        data = response.json()

        if response.status_code == 200:
            refresh_token = data.get("refresh_token")
            print("\n>>> SUCESSO! Adicione esta linha ao seu arquivo .env: <<<\n")
            print(f'MAGALU_API_REFRESH_TOKEN="{refresh_token}"')
            print("\n(Com isso, o sistema gerara os tokens de acesso automaticamente)")
        else:
            print(f"\n[Erro] Falha ao obter token: {response.status_code}")
            print(f"Detalhe: {data}")
            
    except Exception as e:
        print(f"\n[Erro] Falha de conexao: {e}")

if __name__ == "__main__":
    main()