from openpyxl import Workbook
import os

def create_test_file():
    wb = Workbook()
    ws = wb.active
    # Cabecalhos padrao do sistema
    ws.append(["id_produto", "SKU", "Canal", "titulo", "link"])
    
    # Adiciona um produto Magalu SEM o SKU preenchido.
    # O ID "232997900" esta apenas na URL.
    # Se a correcao funcionar, o sistema vai extrair esse ID e consultar a API com sucesso.
    ws.append([
        "TESTE_MAGALU_01", 
        "",  # <--- SKU VAZIO PROPOSITALMENTE
        "Magalu", 
        "iPhone 13 Teste", 
        "https://www.magazineluiza.com.br/iphone-13-apple-128gb-meia-noite-tela-6-1-12mp/p/232997900/te/ip13/"
    ])
    
    filename = "input_magalu_test.xlsx"
    wb.save(filename)
    print(f"Arquivo de teste criado com sucesso: {filename}")
    print("Agora execute o sistema apontando para este arquivo.")

if __name__ == "__main__":
    create_test_file()
