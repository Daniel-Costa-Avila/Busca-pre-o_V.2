import sys
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Adiciona raiz ao path para importar modulos do App
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from App.config import get_server_settings
except ImportError:
    print("Erro: Nao foi possivel importar App.config. Execute na raiz do projeto.")
    sys.exit(1)

def main():
    print("========================================")
    print("  DIAGNOSTICO DE E-MAIL (SMTP)")
    print("========================================")

    try:
        settings = get_server_settings()
    except Exception as e:
        print(f"[ERRO] Falha ao carregar configuracoes: {e}")
        return

    # Logica de fallback para Gmail (similar ao ui/server.py)
    smtp_host = settings.smtp_host
    smtp_port = settings.smtp_port
    smtp_user = settings.smtp_user
    smtp_password = settings.smtp_password
    smtp_sender = settings.smtp_sender
    use_tls = settings.smtp_use_tls
    use_ssl = settings.smtp_use_ssl

    # Se configurado Gmail App Password, sobrescreve padroes
    if settings.gmail_user and settings.gmail_app_password:
        print("[INFO] Detectada configuracao simplificada de GMAIL.")
        smtp_host = "smtp.gmail.com"
        smtp_port = 587
        smtp_user = settings.gmail_user
        smtp_password = settings.gmail_app_password
        smtp_sender = settings.gmail_sender or settings.gmail_user
        use_tls = True
        use_ssl = False

    print(f"Host:       {smtp_host}")
    print(f"Porta:      {smtp_port}")
    print(f"Usuario:    {smtp_user}")
    print(f"Remetente:  {smtp_sender}")
    print(f"TLS: {use_tls} | SSL: {use_ssl}")
    print(f"Modos Envio: {settings.email_send_on}")
    print("-" * 40)

    if not smtp_host:
        print("[ERRO] SMTP_HOST nao configurado (nem Gmail fallback).")
        print("Verifique seu arquivo .env")
        return

    recipients = settings.email_recipients
    if not recipients:
        print("[AVISO] EMAIL_RECIPIENTS nao configurado no .env")
        recipients = input("Digite um e-mail de destino para teste: ").strip()
    
    if not recipients:
        print("Operacao cancelada.")
        return

    to_list = [r.strip() for r in recipients.split(",") if r.strip()]
    print(f"Enviando teste para: {to_list}")

    # Monta mensagem
    msg = MIMEMultipart()
    msg['From'] = smtp_sender
    msg['To'] = ", ".join(to_list)
    msg['Subject'] = f"{settings.email_subject_prefix} Teste de Diagnostico"
    body = "Ola,\n\nEste e um e-mail de teste enviado pelo script de diagnostico do Agente de Precos.\nSe voce recebeu isso, suas credenciais SMTP estao corretas."
    msg.attach(MIMEText(body, 'plain'))

    try:
        print("\nTentando conectar ao servidor SMTP...")
        server = None
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
        
        # Debug da conexao
        server.set_debuglevel(1)

        if use_tls and not use_ssl:
            print("Iniciando STARTTLS...")
            server.starttls()
        
        if smtp_user and smtp_password:
            print("Autenticando...")
            server.login(smtp_user, smtp_password)
        
        print("Enviando dados...")
        server.sendmail(smtp_sender, to_list, msg.as_string())
        server.quit()
        
        print("\n" + "="*40)
        print(" [SUCESSO] E-mail enviado com sucesso!")
        print("="*40)
        
    except Exception as e:
        print("\n" + "="*40)
        print(f" [FALHA] Erro ao enviar e-mail: {e}")
        print("="*40)
        print("Dicas:")
        print("1. Se usa Gmail, gerou a 'Senha de App'? (Senha normal nao funciona)")
        print("2. Verifique firewall/antivirus bloqueando porta 587.")
        print("3. Verifique se o remetente e valido.")

if __name__ == "__main__":
    main()