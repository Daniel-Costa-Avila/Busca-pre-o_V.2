from __future__ import annotations

import json
import sys

from App.collectors.magalu import coletar


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"status": "MAGALU - ERRO NO WORKER: URL AUSENTE"}, ensure_ascii=False))
        return 2

    url = str(sys.argv[1] or "").strip()
    headless_arg = str(sys.argv[2] or "0").strip().lower() if len(sys.argv) >= 3 else "0"
    headless = headless_arg in {"1", "true", "yes", "on"}

    try:
        result = coletar(url, headless=headless)
        if not isinstance(result, dict):
            result = {"status": "MAGALU - RETORNO INVALIDO"}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": f"MAGALU - ERRO NO WORKER: {type(exc).__name__} | {exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
