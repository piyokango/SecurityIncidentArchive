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
from collections import Counter, defaultdict
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
CORPORATE_WORDS = ["株式会社", "有限会社", "合同会社", "合資会社", "合名会社"]
INCIDENT_ID_KEYS = {"事案ID", "事案Id", "incidentId", "IncidentId", "incidentID", "IncidentID", "incident id", "Incident ID"}
RELEASE_TYPE_KEYS = {"公表種別", "リリース種別", "releaseType", "ReleaseType", "release type", "Release Type"}

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
    value = re.sub(r"\s+", " ", str(value)).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def normalize_name(value: str) -> str:
    value = str(value or "").strip()
    replacements = {"（株）": "株式会社", "(株)": "株式会社", "㈱": "株式会社", "　": " ", "＆": "&", "－": "-", "―": "-", "ー": "-"}
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


def bullet_items(lines: list[str]) -> list[str]:
    return [line.strip()[2:].strip() for line in lines if line.strip().startswith("- ")]


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


def overview_metadata(items: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for item in items[4:]:
        if ":" in item:
            key, value = item.split(":", 1)
        elif "：" in item:
            key, value = item.split("：", 1)
        else:
            continue
        metadata[key.strip()] = value.strip()
    return metadata


def metadata_value(metadata: dict[str, str], keys: set[str]) -> str:
    lowered = {key.lower(): value for key, value in metadata.items()}
    for key in keys:
        if key in metadata:
            return metadata[key]
        if key.lower() in lowered:
            return lowered[key.lower()]
    return ""


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
        return {"source": "JPX 東証上場銘柄一覧", "sourceUrl": "", "generatedAt": "", "companyCount": 0, "byNormalizedName": {}}
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


def find_listed_match(org: str, listed_data: dict[str, Any]) -> dict[str, str] | None:
    by_name = listed_data.get("byNormalizedName", {})
    if not isinstance(by_name, dict):
        return None
    for alias in company_name_aliases(org):
        match = by_name.get(alias)
        if isinstance(match, dict):
            return {key: str(value) for key, value in match.items()}
    return None


def listed_status(org: str, org_type: str, listed_data: dict[str, Any], overrides: dict[str, dict[str, str]]) -> dict[str, str]:
    if org in overrides:
        override = overrides[org]
        return {
            "listedStatus": override.get("listedStatus", "手動確認"),
            "listedMarket": override.get("listedMarket", ""),
            "listedIndustry33": override.get("listedIndustry33", override.get("listedIndustry", "")),
            "listedIndustry17": override.get("listedIndustry17", ""),
            "securitiesCode": override.get("securitiesCode", ""),
            "listedName": override.get("listedName", ""),
            "listedSource": override.get("listedSource", "手動補正"),
            "listedConfidence": override.get("listedConfidence", "manual"),
            "listedNote": override.get("listedNote", "data/listed_company_overrides.json による手動補正"),
        }
    if org_type in NON_COMPANY_ORG_TYPES:
        return {"listedStatus": "対象外", "listedMarket": "", "listedIndustry33": "", "listedIndustry17": "", "securitiesCode": "", "listedName": "", "listedSource": "組織種別による判定", "listedConfidence": "rule", "listedNote": "自治体・学校・医療機関等として扱い、上場判定の対象外にしています。"}
    match = find_listed_match(org, listed_data)
    if match:
        return {
            "listedStatus": "上場",
            "listedMarket": safe_text(match.get("market", ""), 80),
            "listedIndustry33": safe_text(match.get("industry33", ""), 80),
            "listedIndustry17": safe_text(match.get("industry17", ""), 80),
            "securitiesCode": safe_text(match.get("code", ""), 20),
            "listedName": safe_text(match.get("name", ""), 120),
            "listedSource": "JPX 東証上場銘柄一覧",
            "listedConfidence": "alias-exact",
            "listedNote": "JPX上場銘柄一覧の銘柄名と、法人種別を除いた正規化名で一致しました。",
        }
    return {"listedStatus": "未確認", "listedMarket": "", "listedIndustry33": "", "listedIndustry17": "", "securitiesCode": "", "listedName": "", "listedSource": "JPX 東証上場銘柄一覧", "listedConfidence": "none", "listedNote": "JPX銘柄名との正規化一致はありませんでした。非上場とは断定しません。"}


def public_url(path: Path) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "piyokango/SecurityIncidentArchive")
    ref = os.environ.get("GITHUB_REF_NAME", "main")
    encoded = "/".join(quote(part) for part in path.as_posix().split("/"))
    return f"https://github.com/{repo}/blob/{quote(ref)}/{encoded}"


def normalize_date(published: str, fallback_date: str) -> str:
    normalized = published.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").strip()
    parts = normalized.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        normalized = f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return fallback_date


def parse_file(path: Path, listed_data: dict[str, Any], listed_overrides: dict[str, dict[str, str]]) -> dict[str, Any] | None:
    rel = path.relative_to(ROOT)
    match = DATE_RE.match(rel.as_posix())
    if not match:
        return None
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    overview = bullet_items(section_lines(lines, "# 公表概要"))
    body = "\n".join(section_lines(lines, "# 本文")).strip()
    year, month, day = match.groups()
    fallback_date = f"{year}-{month}-{day}"
    title = overview[0] if len(overview) >= 1 else path.stem.split("_", 1)[-1]
    published = overview[1] if len(overview) >= 2 else fallback_date
    org = overview[2] if len(overview) >= 3 else path.stem.split("_", 1)[-1]
    source = overview[3] if len(overview) >= 4 else ""
    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        source = ""
    date = normalize_date(published, fallback_date)
    metadata = overview_metadata(overview)
    incident_id = safe_text(metadata_value(metadata, INCIDENT_ID_KEYS), 120)
    release_type = safe_text(metadata_value(metadata, RELEASE_TYPE_KEYS) or "公表", 40)
    tags = infer_tags(title, body)
    org_type = infer_org_type(org)
    listed = listed_status(org, org_type, listed_data, listed_overrides)
    archive_path = rel.as_posix()
    return {
        "id": archive_path,
        "releaseId": archive_path,
        "incidentId": incident_id or archive_path,
        "incidentIdSource": "overview" if incident_id else "archivePath",
        "releaseType": release_type,
        "date": date,
        "year": date[:4],
        "month": date[:7],
        "title": safe_text(title, 240),
        "organization": safe_text(org, 120),
        "organizationType": org_type,
        **listed,
        "sourceUrl": source,
        "archivePath": archive_path,
        "archiveUrl": public_url(rel),
        "tags": tags,
        "summary": safe_text(body, 360),
    }


def counter_to_rows(counter: Counter[str], key_name: str, value_name: str = "count") -> list[dict[str, Any]]:
    return [{key_name: key, value_name: value} for key, value in sorted(counter.items())]


def sorted_counter_rows(counter: Counter[str], key_name: str) -> list[dict[str, Any]]:
    return sorted(counter_to_rows(counter, key_name), key=lambda row: (-row["count"], row[key_name]))


def stats_for(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_month: Counter[str] = Counter(item["month"] for item in items)
    by_year: Counter[str] = Counter(item["year"] for item in items)
    by_tag: Counter[str] = Counter(tag for item in items for tag in item["tags"])
    by_org_type: Counter[str] = Counter(item["organizationType"] for item in items)
    by_listed_status: Counter[str] = Counter(item["listedStatus"] for item in items)
    by_listed_market: Counter[str] = Counter(item["listedMarket"] or "未確認・対象外" for item in items)
    by_listed_industry33: Counter[str] = Counter(item["listedIndustry33"] or "未確認・対象外" for item in items)
    return {
        "byMonth": counter_to_rows(by_month, "month"),
        "byYear": counter_to_rows(by_year, "year"),
        "byTag": sorted_counter_rows(by_tag, "tag"),
        "byOrganizationType": sorted_counter_rows(by_org_type, "organizationType"),
        "byListedStatus": sorted_counter_rows(by_listed_status, "listedStatus"),
        "byListedMarket": sorted_counter_rows(by_listed_market, "listedMarket"),
        "byListedIndustry33": sorted_counter_rows(by_listed_industry33, "listedIndustry33"),
    }


def group_incidents(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for release in releases:
        grouped[release["incidentId"]].append(release)
    incidents: list[dict[str, Any]] = []
    for incident_id, items in grouped.items():
        items.sort(key=lambda item: (item["date"], item["archivePath"]))
        first = items[0]
        latest = items[-1]
        tags = sorted({tag for item in items for tag in item["tags"]})
        release_summaries = [
            {
                "releaseId": item["releaseId"],
                "date": item["date"],
                "releaseType": item["releaseType"],
                "title": item["title"],
                "archivePath": item["archivePath"],
                "archiveUrl": item["archiveUrl"],
                "sourceUrl": item["sourceUrl"],
            }
            for item in items
        ]
        incidents.append({
            "id": incident_id,
            "incidentId": incident_id,
            "incidentIdSource": "overview" if any(item["incidentIdSource"] == "overview" for item in items) else "archivePath",
            "date": latest["date"],
            "year": latest["year"],
            "month": latest["month"],
            "firstDate": first["date"],
            "latestDate": latest["date"],
            "title": latest["title"],
            "organization": latest["organization"],
            "organizationType": latest["organizationType"],
            "listedStatus": latest["listedStatus"],
            "listedMarket": latest["listedMarket"],
            "listedIndustry33": latest["listedIndustry33"],
            "listedIndustry17": latest["listedIndustry17"],
            "securitiesCode": latest["securitiesCode"],
            "listedName": latest["listedName"],
            "listedSource": latest["listedSource"],
            "listedConfidence": latest["listedConfidence"],
            "listedNote": latest["listedNote"],
            "sourceUrl": latest["sourceUrl"],
            "archivePath": latest["archivePath"],
            "archiveUrl": latest["archiveUrl"],
            "tags": tags,
            "summary": latest["summary"],
            "releaseCount": len(items),
            "releaseTypes": sorted({item["releaseType"] for item in items}),
            "releases": release_summaries,
        })
    incidents.sort(key=lambda item: (item["latestDate"], item["organization"], item["title"]), reverse=True)
    return incidents


def main() -> None:
    listed_data = load_listed_companies()
    listed_overrides = load_listed_overrides()
    releases = [item for path in sorted(ROOT.glob("20[0-9][0-9]/[0-1][0-9]/*.md")) if (item := parse_file(path, listed_data, listed_overrides))]
    releases.sort(key=lambda item: (item["date"], item["organization"], item["title"]), reverse=True)
    incidents = group_incidents(releases)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "SecurityIncidentArchive",
        "total": len(releases),
        "releaseCount": len(releases),
        "incidentCount": len(incidents),
        "grouping": {
            "mode": "manual-incident-id-with-archive-path-fallback",
            "overviewKeys": {"incidentId": sorted(INCIDENT_ID_KEYS), "releaseType": sorted(RELEASE_TYPE_KEYS)},
            "note": "# 公表概要に事案IDを追加すると複数リリースを同一事案として集計します。未設定の場合は従来どおり1ファイルを1事案として扱います。",
        },
        "listedCompanyData": {
            "mode": "jpx-corporate-suffix-normalized-match",
            "source": listed_data.get("source", "JPX 東証上場銘柄一覧"),
            "sourceUrl": listed_data.get("sourceUrl", ""),
            "sourcePageUrl": listed_data.get("sourcePageUrl", ""),
            "generatedAt": listed_data.get("generatedAt", ""),
            "listedCompanyCount": listed_data.get("companyCount", 0),
            "overrideFile": "data/listed_company_overrides.json",
            "overrideCount": len(listed_overrides),
            "note": "JPX銘柄名と、株式会社などの法人種別を除いた正規化名で一致した場合のみ上場とします。一致しない場合は未確認であり、非上場とは断定しません。",
        },
        "stats": stats_for(releases),
        "releaseStats": stats_for(releases),
        "incidentStats": stats_for(incidents),
        "releases": releases,
        "incidents": incidents,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} with {len(releases)} releases and {len(incidents)} incidents")


if __name__ == "__main__":
    main()
