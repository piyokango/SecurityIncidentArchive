#!/usr/bin/env python3
"""Build a review report for organizations without dashboard metadata.

The script does not access the network. It extracts organization names from the
archive Markdown files, compares them with data/organization_overrides.json, and
writes machine-readable JSON plus a Markdown report suitable for a GitHub issue.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ORG_OVERRIDES = ROOT / "data" / "organization_overrides.json"
DATE_RE = re.compile(r"^(20\d{2})/(\d{2})/(\d{2})_.*\.md$")
HEADING_RE = re.compile(r"^#\s+")


def safe_text(value: str, limit: int = 200) -> str:
    value = re.sub(r"\s+", " ", str(value)).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def bullet_items(lines: list[str]) -> list[str]:
    return [line.strip()[2:].strip() for line in lines if line.strip().startswith("- ")]


def section_lines(lines: list[str], heading: str) -> list[str]:
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            break
    if start is None:
        return []
    end = len(lines)
    for index in range(start, len(lines)):
        if HEADING_RE.match(lines[index]):
            end = index
            break
    return lines[start:end]


def normalized_date(value: str, fallback: str) -> str:
    value = value.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").strip()
    parts = value.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return fallback


def load_registered_orgs() -> set[str]:
    if not ORG_OVERRIDES.exists():
        return set()
    raw = json.loads(ORG_OVERRIDES.read_text(encoding="utf-8"))
    organizations = raw.get("organizations", {})
    if not isinstance(organizations, dict):
        raise ValueError("data/organization_overrides.json: organizations must be an object")
    return {str(name) for name in organizations.keys()}


def extract_archive_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(ROOT.glob("20[0-9][0-9]/[0-1][0-9]/*.md")):
        rel = path.relative_to(ROOT)
        match = DATE_RE.match(rel.as_posix())
        if not match:
            continue
        fallback = "-".join(match.groups())
        raw = path.read_text(encoding="utf-8", errors="replace")
        overview = bullet_items(section_lines(raw.splitlines(), "# 公表概要"))
        title = overview[0] if len(overview) >= 1 else path.stem.split("_", 1)[-1]
        date = normalized_date(overview[1], fallback) if len(overview) >= 2 else fallback
        org = overview[2] if len(overview) >= 3 else path.stem.split("_", 1)[-1]
        rows.append({
            "organization": safe_text(org, 120),
            "date": date,
            "title": safe_text(title, 180),
            "archivePath": rel.as_posix(),
        })
    return rows


def build_candidates(rows: list[dict[str, str]], registered_orgs: set[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        org = row["organization"]
        if org not in registered_orgs:
            grouped[org].append(row)

    candidates: list[dict[str, Any]] = []
    for org, items in grouped.items():
        items.sort(key=lambda row: row["date"], reverse=True)
        candidates.append({
            "organization": org,
            "incidentCount": len(items),
            "latestDate": items[0]["date"],
            "sampleTitle": items[0]["title"],
            "sampleArchivePath": items[0]["archivePath"],
            "suggestedOverride": {
                "industry": "未確認",
                "businessType": "未確認",
                "companySize": "未確認",
                "source": "要確認",
                "confidence": "needs-review",
                "note": f"未登録組織。最新確認対象: {items[0]['archivePath']}",
            },
        })
    candidates.sort(key=lambda item: (-item["incidentCount"], item["organization"]))
    return candidates


def markdown_table(candidates: list[dict[str, Any]], limit: int = 80) -> str:
    if not candidates:
        return "未登録組織はありません。\n"
    lines = [
        "| 組織名 | 件数 | 最新日 | 確認用ファイル |",
        "| --- | ---: | --- | --- |",
    ]
    for item in candidates[:limit]:
        org = str(item["organization"]).replace("|", "\\|")
        path = str(item["sampleArchivePath"]).replace("|", "\\|")
        lines.append(f"| `{org}` | {item['incidentCount']} | {item['latestDate']} | `{path}` |")
    if len(candidates) > limit:
        lines.append(f"\n上位 {limit} 件のみ表示しています。全件は生成JSONを確認してください。")
    return "\n".join(lines) + "\n"


def markdown_json_snippet(candidates: list[dict[str, Any]], limit: int = 20) -> str:
    snippet = {item["organization"]: item["suggestedOverride"] for item in candidates[:limit]}
    return json.dumps(snippet, ensure_ascii=False, indent=2)


def write_outputs(candidates: list[dict[str, Any]], output_json: Path, output_md: Path) -> None:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "generatedAt": generated_at,
        "candidateCount": len(candidates),
        "source": "SecurityIncidentArchive",
        "note": "This file lists organizations missing from data/organization_overrides.json. Values are review candidates only and are not automatically trusted.",
        "candidates": candidates,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    body = [
        "# 未登録組織の企業情報確認",
        "",
        f"生成日時: `{generated_at}`",
        f"未登録組織数: **{len(candidates)}**",
        "",
        "このIssueは `scripts/build_organization_candidates.py` により生成されます。",
        "業種・業態・企業規模は自動断定せず、確認後に `data/organization_overrides.json` へ手動反映してください。",
        "",
        "## 確認対象",
        "",
        markdown_table(candidates),
        "## 追記用テンプレート候補（上位20件）",
        "",
        "```json",
        markdown_json_snippet(candidates),
        "```",
        "",
        "## 確認ルール",
        "",
        "- 同名企業がある場合は `confidence` を `needs-review` のままにする。",
        "- 公式サイト、法人番号、Gビズインフォ等で確認した場合は `source` と `note` に根拠を残す。",
        "- 判断できない場合は `未確認` のまま登録してもよい。",
    ]
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(body) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-json", default="data/organization_candidates.json")
    parser.add_argument("--output-md", default="data/organization_candidates.md")
    args = parser.parse_args()

    registered_orgs = load_registered_orgs()
    rows = extract_archive_rows()
    candidates = build_candidates(rows, registered_orgs)
    write_outputs(candidates, ROOT / args.output_json, ROOT / args.output_md)
    print(f"candidate_count={len(candidates)}")


if __name__ == "__main__":
    main()
