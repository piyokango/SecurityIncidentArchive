#!/usr/bin/env python3
"""Build a JSON dataset of listed companies from the JPX page.

The script downloads the official JPX page for the latest TSE listed-company
file, downloads the linked Excel file, and converts the needed columns to JSON.
It uses only the Python standard library for xlsx files. If JPX serves legacy
xls, install xlrd explicitly in the workflow before running this script.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

JPX_PAGE_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CORPORATE_WORDS = ["株式会社", "有限会社", "合同会社", "合資会社", "合名会社"]


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SecurityIncidentArchive/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def find_excel_url(page_html: str) -> str:
    candidates = re.findall(r"href=[\"']([^\"']+\.(?:xls|xlsx))(?:\?[^\"']*)?[\"']", page_html, flags=re.I)
    if not candidates:
        raise RuntimeError("JPX listed-company Excel link was not found")
    # Prefer the Japanese list if multiple files are present.
    candidates.sort(key=lambda href: ("data_j" not in href.lower(), href))
    return urljoin(JPX_PAGE_URL, html.unescape(candidates[0]))


def normalize_name(value: str) -> str:
    value = str(value or "").strip()
    replacements = {
        "（株）": "株式会社",
        "(株)": "株式会社",
        "㈱": "株式会社",
        "　": " ",
        "＆": "&",
        "－": "-",
        "―": "-",
        "ー": "-",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"\s+", "", value)
    value = value.replace("・", "")
    return value.upper()


def company_name_aliases(value: str) -> set[str]:
    normalized = normalize_name(value)
    aliases = {normalized}
    without_words = normalized
    for word in CORPORATE_WORDS:
        if without_words.startswith(word):
            aliases.add(without_words[len(word) :])
        if without_words.endswith(word):
            aliases.add(without_words[: -len(word)])
        without_words = without_words.replace(word, "")
    aliases.add(without_words)
    return {alias for alias in aliases if alias}


def parse_xlsx(content: bytes) -> list[list[str]]:
    with zipfile.ZipFile(BytesIO(content)) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", NS):
                texts = [node.text or "" for node in si.findall(".//a:t", NS)]
                shared.append("".join(texts))
        sheet_name = "xl/worksheets/sheet1.xml"
        root = ET.fromstring(zf.read(sheet_name))
        rows: list[list[str]] = []
        for row in root.findall(".//a:sheetData/a:row", NS):
            values: list[str] = []
            current_col = 0
            for cell in row.findall("a:c", NS):
                ref = cell.attrib.get("r", "")
                letters = "".join(ch for ch in ref if ch.isalpha())
                col_index = 0
                for ch in letters:
                    col_index = col_index * 26 + (ord(ch.upper()) - ord("A") + 1)
                col_index -= 1
                while current_col < col_index:
                    values.append("")
                    current_col += 1
                value_node = cell.find("a:v", NS)
                value = value_node.text if value_node is not None else ""
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                values.append(value or "")
                current_col += 1
            rows.append(values)
        return rows


def parse_xls_with_xlrd(content: bytes) -> list[list[str]]:
    try:
        import xlrd  # type: ignore
    except ImportError as exc:
        raise RuntimeError("JPX served legacy xls. Please install xlrd==2.0.1 before running this script.") from exc
    book = xlrd.open_workbook(file_contents=content)
    sheet = book.sheet_by_index(0)
    rows: list[list[str]] = []
    for row_index in range(sheet.nrows):
        rows.append([str(sheet.cell_value(row_index, col_index)).strip() for col_index in range(sheet.ncols)])
    return rows


def parse_excel(content: bytes) -> list[list[str]]:
    if content[:2] == b"PK":
        return parse_xlsx(content)
    return parse_xls_with_xlrd(content)


def header_index(header: list[str], patterns: list[str]) -> int:
    normalized = [re.sub(r"\s+", "", cell) for cell in header]
    for pattern in patterns:
        for index, cell in enumerate(normalized):
            if pattern in cell:
                return index
    raise RuntimeError(f"Column not found: {patterns}")


def optional_header_index(header: list[str], patterns: list[str]) -> int | None:
    try:
        return header_index(header, patterns)
    except RuntimeError:
        return None


def cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index]).strip()


def build_listed_companies(rows: list[list[str]], source_url: str) -> dict[str, Any]:
    header_row_index = None
    for index, row in enumerate(rows[:20]):
        joined = " ".join(row)
        if "コード" in joined and ("銘柄名" in joined or "会社名" in joined):
            header_row_index = index
            break
    if header_row_index is None:
        raise RuntimeError("Header row was not found in JPX Excel")

    header = rows[header_row_index]
    code_i = header_index(header, ["コード"])
    name_i = header_index(header, ["銘柄名", "会社名"])
    market_i = header_index(header, ["市場・商品区分", "市場区分", "市場"])
    industry33_i = optional_header_index(header, ["33業種区分", "33業種", "業種区分"])
    industry17_i = optional_header_index(header, ["17業種区分", "17業種"])
    scale_i = optional_header_index(header, ["規模区分"])

    companies: list[dict[str, Any]] = []
    alias_candidates: dict[str, list[dict[str, str]]] = {}
    for row in rows[header_row_index + 1 :]:
        if len(row) <= max(code_i, name_i, market_i):
            continue
        code = re.sub(r"\.0$", "", str(row[code_i]).strip())
        name = str(row[name_i]).strip()
        market = str(row[market_i]).strip()
        if not code or not name:
            continue
        aliases = sorted(company_name_aliases(name))
        item = {
            "code": code,
            "name": name,
            "normalizedName": normalize_name(name),
            "aliases": aliases,
            "market": market,
            "industry33": cell(row, industry33_i),
            "industry17": cell(row, industry17_i),
            "scaleCategory": cell(row, scale_i),
        }
        companies.append(item)
        compact_item = {
            "code": item["code"],
            "name": item["name"],
            "market": item["market"],
            "industry33": item["industry33"],
            "industry17": item["industry17"],
            "scaleCategory": item["scaleCategory"],
        }
        for alias in aliases:
            alias_candidates.setdefault(alias, []).append(compact_item)

    by_normalized_name: dict[str, dict[str, str]] = {}
    ambiguous_aliases: dict[str, int] = {}
    for alias, matches in alias_candidates.items():
        unique_codes = {match["code"] for match in matches}
        if len(unique_codes) == 1:
            by_normalized_name[alias] = matches[0]
        else:
            ambiguous_aliases[alias] = len(unique_codes)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "JPX 東証上場銘柄一覧",
        "sourceUrl": source_url,
        "sourcePageUrl": JPX_PAGE_URL,
        "companyCount": len(companies),
        "aliasCount": len(by_normalized_name),
        "ambiguousAliasCount": len(ambiguous_aliases),
        "companies": companies,
        "byNormalizedName": by_normalized_name,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/jpx_listed_companies.json")
    args = parser.parse_args()

    page_html = fetch_bytes(JPX_PAGE_URL).decode("utf-8", errors="replace")
    excel_url = find_excel_url(page_html)
    excel_content = fetch_bytes(excel_url)
    rows = parse_excel(excel_content)
    payload = build_listed_companies(rows, excel_url)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"listed_company_count={payload['companyCount']}")
    print(f"listed_alias_count={payload['aliasCount']}")
    print(f"source_url={excel_url}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
