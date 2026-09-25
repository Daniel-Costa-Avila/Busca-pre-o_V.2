"""Gera uma cópia da interface com a integração, sem editar a UI em operação."""
from pathlib import Path
import difflib
import shutil

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".tmp" / "brasilapi-test"


def prepare():
    original = (ROOT / "ui_streamlit" / "app.py").read_text(encoding="utf-8")
    replacements = [
        ('import requests\n', 'import requests\nfrom integrations.brasilapi_panel import render as render_brasilapi\n'),
        ('        _nav_button("?  Ajuda", "help")', '        _nav_button("?  Ajuda", "help")\n        _nav_button("◎  BrasilAPI", "brasilapi")'),
        ('        view_titles = {', '        view_titles = {\n            "brasilapi": ("Painel / BrasilAPI", "Consultas de dados públicos"),'),
        ('        if view == "overview":', '        if view == "brasilapi":\n            render_brasilapi()\n        elif view == "overview":'),
    ]
    updated = original
    for before, after in replacements:
        if updated.count(before) != 1:
            raise RuntimeError(f"Ponto de integração mudou: {before!r}")
        updated = updated.replace(before, after, 1)
    (TARGET / "ui_streamlit").mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "integrations", TARGET / "ui_streamlit" / "integrations", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "Modelo.xlsx", TARGET / "Modelo.xlsx")
    (TARGET / "ui_streamlit" / "app.py").write_text(updated, encoding="utf-8")
    (TARGET / "integration.patch").write_text("".join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True), fromfile="a/ui_streamlit/app.py", tofile="b/ui_streamlit/app.py")), encoding="utf-8")
    print(TARGET / "ui_streamlit" / "app.py")


if __name__ == "__main__":
    prepare()
