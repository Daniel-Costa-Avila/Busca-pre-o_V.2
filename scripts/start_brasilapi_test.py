"""Inicia apenas a UI de teste no loopback, usando a API existente para o painel."""
import os
import socket
import subprocess
import sys

from dotenv import dotenv_values
from prepare_brasilapi_test import ROOT, TARGET, prepare


if __name__ == "__main__":
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8514))
    prepare()
    env = os.environ.copy()
    env.update({key: value for key, value in dotenv_values(ROOT / ".env").items() if value is not None})
    env["UI_API_BASE"] = "http://127.0.0.1:8000"
    env["UI_EMBED_API_IFRAME"] = "false"
    env["UI_BRAND_NAME"] = "Busca Preço — Teste BrasilAPI"
    with (TARGET / "streamlit.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(TARGET / "ui_streamlit" / "app.py"),
             "--server.address", "127.0.0.1", "--server.port", "8514", "--server.headless", "true", "--server.baseUrlPath", ""],
            cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    (TARGET / "streamlit.pid").write_text(str(process.pid), encoding="ascii")
    print(f"UI de teste: http://127.0.0.1:8514 | PID {process.pid}")
