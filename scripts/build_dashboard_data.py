#!/usr/bin/env python3
"""Build JSON data for the SecurityIncidentArchive dashboard.

This script intentionally uses only Python's standard library. It reads the
archive Markdown files from year/month directories and emits a static JSON file
for GitHub Pages. Optional listed-company data is loaded from
`data/jpx_listed_companies.json`, which is generated separately from JPX data.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data" / "incidents.json"
LISTED_COMPANIES = ROOT / "data" / "jpx_listed_companies.json"
LISTED_OVERRIDES = ROOT / "data" / "listed_company_overrides.json"
DATE_RE = re.compile(r"^(20\d{2})/(\d{2})/(\d{2})_.*\.md$")
HEADING_RE = re.compile(r"^#\s+")

TAG_RULES: list[tuple[str, list[str]]] = [
    ("不正アクセス", ["不正アクセス", "第三者によるアクセス", "権限のないアクセス", "Unauthorized access", "unauthorized access"]),
    ("ランサムウェア", ["ランサムウェア", "身代金", "暗号化", "ransomware", "Ransomware"]),
    ("情報漏えい", ["情報漏えい", "情報漏洩", "漏えい", "漏洩", "流出", "外部に公開", "個人情報"]),
    ("フィッシング・不審画面", ["フィッシング", "不審な認証画面", "不審な画面", "偽サイト", "なりすまし"]),
    ("マルウェア", ["マルウェア", "ウイルス", "Emotet", "感染"]),
    ("Web改ざん", ["改ざん", "改竄", "不正なスクリプト", "不審なスクリプト", "polyfill.io"]),
    ("メール誤送信", ["誤送信", "宛先", "CC", "BCC"]),
    ("設定不備", ["設定不備", "設定ミス", "閲覧可能", "アクセス制限", "公開状態"]),
    ("委託先・外部サービス", ["委託先", "再委託", "外部サービス", "クラウドサービス", "取引先"]),
    ("システム障害", ["システム障害", "障害", "停止", "利用できない", "復旧"]),
]

ORG_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("自治体・公的機関", ["県", "市", "区", "町", "村", "庁", "省", "機構", "協会", "大学", "病院"]),
    ("株式会社", ["株式会社", "有限会社", "合同会社"]),
    ("学校・教育", ["大学", "高校", "学校", "学院", "教育"]),
    ("医療・福祉", ["病院", "クリニック", "医療", "福祉", "介護"]),
]

NON_COMPANY_ORG_TYPES = {"自治体・公的機関", "学校・教育", "医療・福祉"}


def safe_text(value: str, limit: int) -> str:
    """Normalize text and cap length to keep JSON small and UI predictable."""
    value = re.sub(r"\s+", " ", str(value)).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def normalize_name(value: str) -> str:
    value = str(value or "").strip()
    replacements = {
        "（株）": "株式会社",
        "(株)": "株式会社",
        "㈱": "株式会社",
        "　": " ",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"\s+", "", value)
    value = value.replace("・", "").replace("－", "-")
    return value


def bullet_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def section_lines(lines: list[str], heading: str) -> list[str]:
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        return []
    end = len(lines)
    for j in range(start, len(lines)):
        if HEADING_RE.match(lines[j]):
            end = j
            break
    return lines[start:end]


def infer_tags(title: str, body: str) -> list[str]:
    haystack = f"{title}\n{body}"
    tags = [label for label, words in TAG_RULES if any(word in haystack for word in words)]
    return tags or ["未分類"]


def infer_org_type(org: str) -> str:
    for label, words in ORG_TYPE_RULES:
        if any(word in org for word in words):
            return label
    return "その他"


def load_listed_companies() -> dict[str, Any]:
    if not LISTED_COMPANIES.exists():
        return {
            "source": "JPX 東証上場銘柄一覧",
            "sourceUrl": "",
            "generatedAt": "",
            "companyCount": 0,
            "byNormalizedName": {},
        }
    raw = json.loads(LISTED_COMPANIES.read_text(encoding="utf-8"))
    by_name = raw.get("byNormalizedName", {})
    if not isinstance(by_name, dict):
        by_name = {}
    return {
        "source": str(raw.get("source", "JPX 東証上場銘柄一覧")),
        "sourceUrl": str(raw.get("sourceUrl", "")),
        "sourcePageUrl": str(raw.get("sourcePageUrl", "")),
        "generatedAt": str(raw.get("generatedAt", "")),
        "companyCount": int(raw.get("companyCount", 0) or 0),
        "byNormalizedName": by_name,
    }


def load_listed_overrides() -> dict[str, dict[str, str]]:
    if not LISTED_OVERRIDES.exists():
        return {}
    raw = json.loads(LISTED_OVERRIDES.read_text(encoding="utf-8"))
    organizations = raw.get("organizations", {})
    if not isinstance(organizations, dict):
        raise ValueError("data/listed_company_overrides.json: organizations must be an object")
    normalized: dict[str, dict[str, str]] = {}
    for org, value in organizations.items():
        if isinstance(org, str) and isinstance(value, dict):
            normalized[org] = {key: safe_text(str(val), 120) for key, val in value.items()}
    return normalized


def listed_status(org: str, org_type: str, listed_data: dict[str, Any], overrides: dict[str, dict[str, str]]) -> dict[str, str]:
    if org in overrides:
        override = overrides[org]
        return {
            "listedStatus": override.get("listedStatus", "手動確認"),
            "listedMarket": override.get("listedMarket", ""),
            "securitiesCode": override.get("securitiesCode", ""),
            "listedName": override.get("listedName", ""),
            "listedSource": override.get("listedSource", "手動補正"),
            "listedConfidence": override.get("listedConfidence", "manual"),
            "listedNote": override.get("listedNote", "data/listed_company_overrides.json による手動補正"),
        }

    if org_type in NON_COMPANY_ORG_TYPES:
        return {
            "listedStatus": "対象外",
            "listedMarket": "",
            "securitiesCode": "",
            "listedName": "",
            "listedSource": "組織種別による判定",
            "listedConfidence": "rule",
            "listedNote": "自治体・学校・医療機関等として扱い、上場判定の対象外にしています。",
        }

    normalized = normalize_name(org)
    match = listed_data.get("byNormalizedName", {}).get(normalized)
    if isinstance(match, dict):
        return {
            "listedStatus": "上場",
            "listedMarket": safe_text(str(match.get("market", "")), 80),
            "securitiesCode": safe_text(str(match.get("code", "")), 20),
            "listedName": safe_text(str(match.get("name", "")), 120),
            "listedSource": "JPX 東証上場銘柄一覧",
            "listedConfidence": "normalized-exact",
            "listedNote": "JPX上場銘柄一覧の銘柄名と正規化一致しました。",
        }

    return {
        "listedStatus": "未確認",
        "listedMarket": "",
        "securitiesCode": "",
        "listedName": "",
        "listedSource": "JPX 東証上場銘柄一覧",
        "listedConfidence": "none",
        "listedNote": "JPX銘柄名との完全一致・正規化一致はありませんでした。非上場とは断定しません。",
    }


def public_url(path: Path) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "piyokango/SecurityIncidentArchive")
    ref = os.environ.get("GITHUB_REF_NAME", "main")
    encoded = "/".join(quote(part) for part in path.as_posix().split("/"))
    return f"https://github.com/{repo}/blob/{quote(ref)}/{encoded}"


def parse_file(path: Path, listed_data: dict[str, Any], listed_overrides: dict[str, dict[str, str]]) -> dict[str, Any] | None:
    rel = path.relative_to(ROOT)
    match = DATE_RE.match(rel.as_posix())
    if not match:
        return None

    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    overview = bullet_items(section_lines(lines, "# 公表概要"))
    body_lines = section_lines(lines, "# 本文")
    body = "\n".join(body_lines).strip()

    year, month, day = match.groups()
    fallback_date = f"{year}-{month}-{day}"
    title = overview[0] if len(overview) >= 1 else path.stem.split("_", 1)[-1]
    published = overview[1] if len(overview) >= 2 else fallback_date
    org = overview[2] if len(overview) >= 3 else path.stem.split("_", 1)[-1]
    source = overview[3] if len(overview) >= 4 else ""

    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        source = ""

    normalized = published.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").strip()
    parts = normalized.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        normalized = f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    try:
        date_obj = datetime.strptime(normalized, "%Y-%m-%d")
        date = date_obj.strftime("%Y-%m-%d")
    except ValueError:
        date = fallback_date

    tags = infer_tags(title, body)
    org_type = infer_org_type(org)
    listed = listed_status(org, org_type, listed_data, listed_overrides)
    return {
        "id": rel.as_posix(),
        "date": date,
        "year": date[:4],
        "month": date[:7],
        "title": safe_text(title, 240),
        "organization": safe_text(org, 120),
        "organizationType": org_type,
        **listed,
        "sourceUrl": source,
        "archivePath": rel.as_posix(),
        "archiveUrl": public_url(rel),
        "tags": tags,
        "summary": safe_text(body, 360),
    }


def counter_to_rows(counter: Counter[str], key_name: str, value_name: str = "count") -> list[dict[str, Any]]:
    return [{key_name: key, value_name: value} for key, value in sorted(counter.items())]


def sorted_counter_rows(counter: Counter[str], key_name: str) -> list[dict[str, Any]]:
    return sorted(counter_to_rows(counter, key_name), key=lambda row: (-row["count"], row[key_name]))


def main() -> None:
    listed_data = load_listed_companies()
    listed_overrides = load_listed_overrides()
    incidents = [item for path in sorted(ROOT.glob("20[0-9][0-9]/[0-1][0-9]/*.md")) if (item := parse_file(path, listed_data, listed_overrides))]
    incidents.sort(key=lambda item: (item["date"], item["organization"], item["title"]), reverse=True)

    by_month: Counter[str] = Counter(item["month"] for item in incidents)
    by_year: Counter[str] = Counter(item["year"] for item in incidents)
    by_tag: Counter[str] = Counter(tag for item in incidents for tag in item["tags"])
    by_org_type: Counter[str] = Counter(item["organizationType"] for item in incidents)
    by_listed_status: Counter[str] = Counter(item["listedStatus"] for item in incidents)
    by_listed_market: Counter[str] = Counter(item["listedMarket"] or "未確認・対象外" for item in incidents)

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "SecurityIncidentArchive",
        "total": len(incidents),
        "listedCompanyData": {
            "mode": "jpx-normalized-name-match",
            "source": listed_data.get("source", "JPX 東証上場銘柄一覧"),
            "sourceUrl": listed_data.get("sourceUrl", ""),
            "sourcePageUrl": listed_data.get("sourcePageUrl", ""),
            "generatedAt": listed_data.get("generatedAt", ""),
            "listedCompanyCount": listed_data.get("companyCount", 0),
            "overrideFile": "data/listed_company_overrides.json",
            "overrideCount": len(listed_overrides),
            "note": "JPX銘柄名と正規化一致した場合のみ上場とします。一致しない場合は未確認であり、非上場とは断定しません。",
        },
        "stats": {
            "byMonth": counter_to_rows(by_month, "month"),
            "byYear": counter_to_rows(by_year, "year"),
            "byTag": sorted_counter_rows(by_tag, "tag"),
            "byOrganizationType": sorted_counter_rows(by_org_type, "organizationType"),
            "byListedStatus": sorted_counter_rows(by_listed_status, "listedStatus"),
            "byListedMarket": sorted_counter_rows(by_listed_market, "listedMarket"),
        },
        "incidents": incidents,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} with {len(incidents)} incidents")


if __name__ == "__main__":
    main()
