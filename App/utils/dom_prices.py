from __future__ import annotations

import re


MONEY_RE = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})")
_STRUCK_PRICES_SCRIPT = """
() => {
  const out = [];
  const moneyRe = /R\\$\\s?\\d{1,3}(?:\\.\\d{3})*(?:,\\d{2})/;
  const originalHints = [
    "old-price",
    "oldprice",
    "original-price",
    "originalprice",
    "list-price",
    "listprice",
    "from-price",
    "preco-antigo",
    "precoantigo",
  ];

  for (const el of document.querySelectorAll("body *")) {
    const text = (el.innerText || "").replace(/\\s+/g, " ").trim();
    if (!text || !moneyRe.test(text)) continue;

    const style = window.getComputedStyle(el);
    if (!style) continue;
    if (style.display === "none" || style.visibility === "hidden") continue;

    const decoration = `${style.textDecorationLine || ""} ${style.textDecoration || ""}`.toLowerCase();
    const meta = `${el.className || ""} ${el.id || ""} ${el.getAttribute("data-testid") || ""}`.toLowerCase();
    const markedAsOriginal = originalHints.some((token) => meta.includes(token));

    if (!decoration.includes("line-through") && !markedAsOriginal) continue;
    out.push(text);
  }

  return out;
}
"""


def extract_struck_prices(driver) -> set[str]:
    if driver is None:
        return set()

    try:
        if hasattr(driver, "execute_script"):
            raw_texts = driver.execute_script(f"return ({_STRUCK_PRICES_SCRIPT})();")
        elif hasattr(driver, "evaluate"):
            raw_texts = driver.evaluate(_STRUCK_PRICES_SCRIPT)
        else:
            return set()
    except Exception:
        return set()

    ignored: set[str] = set()
    for text in raw_texts or []:
        for match in MONEY_RE.finditer(str(text or "")):
            ignored.add(match.group(0).strip())
    return ignored
