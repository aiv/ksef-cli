#!/usr/bin/env python3
"""Transformacja faktur XML z KSeF do PDF za pomocą XSLT."""

import os
import re
import sys
import glob
import argparse
from lxml import etree
from weasyprint import HTML, CSS

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INVOICES_DIR = "faktury"
OUTPUT_DIR = "faktury_pdf"
XSLT_DIR = "xslt"
FONTS_DIR = os.path.join(SCRIPT_DIR, "fonts")

# Mapowanie namespace XML → plik XSLT
NAMESPACE_XSLT_MAP = {
    "http://crd.gov.pl/wzor/2025/06/25/13775/": os.path.join(XSLT_DIR, "kseffaktura_fa(3).xsl"),
    "http://crd.gov.pl/wzor/2023/06/29/12648/": os.path.join(XSLT_DIR, "kseffaktura.xsl"),
}


def _build_font_css():
    """Buduje CSS @font-face z lokalnych plików TTF."""
    fonts = [
        ("Open Sans", 400, "OpenSans-Regular.ttf"),
        ("Open Sans", 600, "OpenSans-SemiBold.ttf"),
        ("Open Sans", 700, "OpenSans-Bold.ttf"),
        ("Montserrat", 600, "Montserrat-SemiBold.ttf"),
        ("Montserrat", 700, "Montserrat-Bold.ttf"),
    ]
    rules = []
    for family, weight, filename in fonts:
        path = os.path.join(FONTS_DIR, filename)
        if not os.path.exists(path):
            continue
        url = "file://" + path
        rules.append(
            f"@font-face {{\n"
            f"  font-family: '{family}';\n"
            f"  font-style: normal;\n"
            f"  font-weight: {weight};\n"
            f"  src: url('{url}') format('truetype');\n"
            f"}}"
        )
    return "\n".join(rules)


FONT_CSS = _build_font_css()

# Wzorzec do usunięcia linków Google Fonts z HTML
_GOOGLE_FONTS_RE = re.compile(
    r'<link[^>]+href="https://fonts\.googleapis\.com/css[^"]*"[^>]*/?\s*>',
    re.IGNORECASE,
)


def detect_namespace(xml_tree):
    """Wykrywa namespace elementu głównego faktury."""
    root = xml_tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else None
    return ns


def select_xslt(namespace):
    """Wybiera plik XSLT na podstawie namespace."""
    xslt_path = NAMESPACE_XSLT_MAP.get(namespace)
    if not xslt_path:
        raise ValueError(f"Nieznany namespace: {namespace}")
    if not os.path.exists(xslt_path):
        raise FileNotFoundError(f"Brak pliku XSLT: {xslt_path}")
    return xslt_path


def _inject_local_fonts(html_string):
    """Zamienia linki Google Fonts na lokalne @font-face."""
    html_string = _GOOGLE_FONTS_RE.sub("", html_string)
    font_style = f"<style type=\"text/css\">\n{FONT_CSS}\n</style>"
    html_string = html_string.replace("<head>", f"<head>\n{font_style}", 1)
    return html_string


def transform_to_pdf(xml_path, output_dir):
    """Transformuje plik XML faktury do PDF."""
    xml_tree = etree.parse(xml_path)
    namespace = detect_namespace(xml_tree)
    xslt_path = select_xslt(namespace)

    xslt_tree = etree.parse(xslt_path)
    transform = etree.XSLT(xslt_tree)
    html_result = transform(xml_tree)

    html_string = _inject_local_fonts(str(html_result))

    basename = os.path.splitext(os.path.basename(xml_path))[0]
    pdf_path = os.path.join(output_dir, f"{basename}.pdf")

    HTML(string=html_string).write_pdf(pdf_path)
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="Transformacja faktur XML do PDF")
    parser.add_argument("--input", default=INVOICES_DIR, help=f"Folder z fakturami XML (domyślnie: {INVOICES_DIR})")
    parser.add_argument("--output", default=OUTPUT_DIR, help=f"Folder wyjściowy PDF (domyślnie: {OUTPUT_DIR})")
    args = parser.parse_args()

    if not os.path.isdir(args.input):
        print(f"Folder wejściowy nie istnieje: {args.input}")
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)

    xml_files = glob.glob(os.path.join(args.input, "*.xml"))
    if not xml_files:
        print(f"Brak plików XML w folderze: {args.input}")
        sys.exit(0)

    print(f"Znaleziono {len(xml_files)} faktur do transformacji")

    success = 0
    for xml_path in xml_files:
        filename = os.path.basename(xml_path)
        try:
            pdf_path = transform_to_pdf(xml_path, args.output)
            print(f"  OK: {filename} -> {os.path.basename(pdf_path)}")
            success += 1
        except Exception as e:
            print(f"  BŁĄD: {filename} - {e}")

    print(f"\nPrzetransformowano {success}/{len(xml_files)} faktur")


if __name__ == "__main__":
    main()
