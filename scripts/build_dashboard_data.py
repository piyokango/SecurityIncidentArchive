#!/usr/bin/env python3
"""Build JSON data for the SecurityIncidentArchive dashboard.

This script intentionally uses only Python's standard library. It reads the
archive Markdown files from year/month directories and emits a static JSON file
for GitHub Pages. No network access is performed.
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
ORG_OVERRIDES = ROOT / "data" / "organization_overrides.json"
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

DEFAULT_ORG_META = {
    "industry": "未登録",
    "businessType": "未登録",
    "companySize": "未登録",
    "source": "未登録",
    "confidence": "none",
    "note": "data/organization_overrides.json に手動登録すると表示されます。",
}


def safe_text(value: str, limit: int) -> str:
    """Normalize text and cap length to keep JSON small and UI predictable."""
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


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


def load_org_overrides() -> dict[str, dict[str, str]]:
    if not ORG_OVERRIDES.exists():
        return {}
    raw = json.loads(ORG_OVERRIDES.read_text(encoding="utf-8"))
    organizations = raw.get("organizations", {})
    if not isinstance(organizations, dict):
        raise ValueError("data/organization_overrides.json: organizations must be an object")

    normalized: dict[str, dict[str, str]] = {}
    for org, value in organizations.items():
        if not isinstance(org, str) or not isinstance(value, dict):
            continue
        normalized[org] = {
            "industry": safe_text(str(value.get("industry", "未登録")), 80),
            "businessType": safe_text(str(value.get("businessType", "未登録")), 120),
            "companySize": safe_text(str(value.get("companySize", "未登録")), 40),
            "source": safe_text(str(value.get("source", "手動登録")), 120),
            "confidence": safe_text(str(value.get("confidence", "manual")), 40),
            "note": safe_text(str(value.get("note", "")), 180),
        }
    return normalized


def organization_metadata(org: str, overrides: dict[str, dict[str, str]]) -> dict[str, str]:
    metadata = dict(DEFAULT_ORG_META)
    if org in overrides:
        metadata.update(overrides[org])
    return metadata


def public_url(path: Path) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "piyokango/SecurityIncidentArchive")
    ref = os.environ.get("GITHUB_REF_NAME", "main")
    encoded = "/".join(quote(part) for part in path.as_posix().split("/"))
    return f"https://github.com/{repo}/blob/{quote(ref)}/{encoded}"


def parse_file(path: Path, org_overrides: dict[str, dict[str, str]]) -> dict[str, Any] | None:
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
    org_meta = organization_metadata(org, org_overrides)
    return {
        "id": rel.as_posix(),
        "date": date,
        "year": date[:4],
        "month": date[:7],
        "title": safe_text(title, 240),
        "organization": safe_text(org, 120),
        "organizationType": infer_org_type(org),
        "industry": org_meta["industry"],
        "businessType": org_meta["businessType"],
        "companySize": org_meta["companySize"],
        "organizationMetadataSource": org_meta["source"],
        "organizationMetadataConfidence": org_meta["confidence"],
        "organizationMetadataNote": org_meta["note"],
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
    org_overrides = load_org_overrides()
    incidents = [item for path in sorted(ROOT.glob("20[0-9][0-9]/[0-1][0-9]/*.md")) if (item := parse_file(path, org_overrides))]
    incidents.sort(key=lambda item: (item["date"], item["organization"], item["title"]), reverse=True)

    by_month: Counter[str] = Counter(item["month"] for item in incidents)
    by_year: Counter[str] = Counter(item["year"] for item in incidents)
    by_tag: Counter[str] = Counter(tag for item in incidents for tag in item["tags"])
    by_org_type: Counter[str] = Counter(item["organizationType"] for item in incidents)
    by_industry: Counter[str] = Counter(item["industry"] for item in incidents)
    by_business_type: Counter[str] = Counter(item["businessType"] for item in incidents)
    by_company_size: Counter[str] = Counter(item["companySize"] for item in incidents)

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "SecurityIncidentArchive",
        "total": len(incidents),
        "organizationMetadata": {
            "mode": "manual-overrides",
            "sourceFile": "data/organization_overrides.json",
            "registeredOrganizations": len(org_overrides),
            "note": "業種・業態・規模は手動補正ファイルに登録された情報のみを反映します。未登録の組織は未登録として表示します。",
        },
        "stats": {
            "byMonth": counter_to_rows(by_month, "month"),
            "byYear": counter_to_rows(by_year, "year"),
            "byTag": sorted_counter_rows(by_tag, "tag"),
            "byOrganizationType": sorted_counter_rows(by_org_type, "organizationType"),
            "byIndustry": sorted_counter_rows(by_industry, "industry"),
            "byBusinessType": sorted_counter_rows(by_business_type, "businessType"),
            "byCompanySize": sorted_counter_rows(by_company_size, "companySize"),
        },
        "incidents": incidents,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} with {len(incidents)} incidents")


if __name__ == "__main__":
    main()
