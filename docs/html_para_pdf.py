from __future__ import annotations

import html
import re
import textwrap
from html.parser import HTMLParser
from pathlib import Path


class HtmlToTextParser(HTMLParser):
    BLOCK_TAGS = {"p", "div", "section", "h1", "h2", "h3", "h4", "pre", "ul", "ol", "table", "tr"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.in_pre = False
        self.list_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "br":
            self.parts.append("\n")
            return
        if tag == "pre":
            self.in_pre = True
            self.parts.append("\n")
            return
        if tag in {"ul", "ol"}:
            self.list_stack.append(tag)
            self.parts.append("\n")
            return
        if tag == "li":
            prefix = "• " if (self.list_stack and self.list_stack[-1] == "ul") else "- "
            self.parts.append(prefix)

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self.in_pre = False
            self.parts.append("\n\n")
            return
        if tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self.parts.append("\n")
            return
        if tag in self.BLOCK_TAGS or tag == "li":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        text = html.unescape(data)
        if not text.strip():
            if self.in_pre:
                self.parts.append(text)
            return
        if self.in_pre:
            self.parts.append(text)
        else:
            compact = re.sub(r"\s+", " ", text)
            self.parts.append(compact)

    def get_text(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def wrap_text(raw_text: str, width: int = 96) -> list[str]:
    output: list[str] = []
    for block in raw_text.splitlines():
        stripped = block.rstrip()
        if not stripped:
            output.append("")
            continue
        if stripped.startswith("• ") or stripped.startswith("- "):
            prefix = stripped[:2]
            body = stripped[2:].strip()
            wrapped = textwrap.wrap(body, width=width - len(prefix)) or [""]
            output.append(prefix + wrapped[0])
            for item in wrapped[1:]:
                output.append("  " + item)
            continue
        output.extend(textwrap.wrap(stripped, width=width) or [""])
    return output


def pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(lines: list[str], target: Path) -> None:
    page_width = 595
    page_height = 842
    margin_left = 42
    margin_top = 48
    font_size = 11
    line_height = 15
    usable_height = page_height - margin_top - 48
    lines_per_page = usable_height // line_height

    pages: list[list[str]] = []
    for index in range(0, len(lines), lines_per_page):
        pages.append(lines[index:index + lines_per_page])

    objects: list[bytes] = []

    def add_object(data: bytes) -> int:
        objects.append(data)
        return len(objects)

    font_obj = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_obj_numbers: list[int] = []
    content_obj_numbers: list[int] = []
    pages_obj_placeholder = len(objects) + 1

    for page_lines in pages:
        content_lines = ["BT", f"/F1 {font_size} Tf", f"1 0 0 1 {margin_left} {page_height - margin_top} Tm", f"{line_height} TL"]
        for line in page_lines:
            content_lines.append(f"({pdf_escape(line)}) Tj")
            content_lines.append("T*")
        content_lines.append("ET")
        content_stream = "\n".join(content_lines).encode("latin-1", errors="replace")
        content_obj = add_object(b"<< /Length " + str(len(content_stream)).encode("ascii") + b" >>\nstream\n" + content_stream + b"\nendstream")
        content_obj_numbers.append(content_obj)
        page_obj = add_object(
            (
                f"<< /Type /Page /Parent {pages_obj_placeholder} 0 R /MediaBox [0 0 {page_width} {page_height}] "
                f"/Resources << /Font << /F1 {font_obj} 0 R >> >> /Contents {content_obj} 0 R >>"
            ).encode("ascii")
        )
        page_obj_numbers.append(page_obj)

    kids = " ".join(f"{number} 0 R" for number in page_obj_numbers)
    pages_obj = add_object(f"<< /Type /Pages /Count {len(page_obj_numbers)} /Kids [{kids}] >>".encode("ascii"))
    catalog_obj = add_object(f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode("ascii"))

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_obj} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
    )

    target.write_bytes(pdf)


def main() -> None:
    root = Path(__file__).resolve().parent
    html_path = root / "DOCUMENTACAO_SISTEMA_COMPLETA_2026-03-18.html"
    pdf_path = root / "DOCUMENTACAO_SISTEMA_COMPLETA_2026-03-18.pdf"

    parser = HtmlToTextParser()
    parser.feed(html_path.read_text(encoding="utf-8"))
    text_content = parser.get_text()
    wrapped_lines = wrap_text(text_content)
    build_pdf(wrapped_lines, pdf_path)
    print(f"PDF gerado em: {pdf_path}")


if __name__ == "__main__":
    main()
