#!/usr/bin/env python3
"""Build candidate issue content for grouping related releases into incidents.

This script does not modify archive files. It scans releases that do not already
have a manual incident ID and suggests possible groups based on organization,
date proximity, and title similarity. The output is intended for human review in
an Issue.
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
DATE_RE = re.compile(r"^(20\d{2})/(\d{2})/(\d{2})_.*\.md$")
HEADING_RE = re.compile(r"^#\s+")
INCIDENT_ID_KEYS = {"事案ID", "事案Id", "incidentId", "IncidentId", "incidentID", "IncidentID", "incident id", "Incident ID"}
TITLE_STOPWORDS = {"について", "お知らせ", "お詫び", "ご報告", "に関する", "の件", "第", "報", "続報", "調査", "結果", "最終", "公表"}


def safe_text(value: str, limit: int = 160) -> str:
    value = re.sub(r"\s+", " ", str(value)).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


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


def bullet_items(lines: list[str]) -> list[str]:
    return [line.strip()[2:].strip() for line in lines if line.strip().startswith("- ")]


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


def normalize_date(published: str, fallback: str) -> str:
    normalized = published.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").strip()
    parts = normalized.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        normalized = f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return fallback


def title_tokens(title: str) -> set[str]:
    normalized = re.sub(r"[\s　・、。，．（）()【】\[\]「」『』:：/／\\-]+", " ", title)
    chunks = set()
    for chunk in normalized.split():
        chunk = chunk.strip()
        if not chunk or chunk in TITLE_STOPWORDS:
            continue
        if len(chunk) >= 2:
            chunks.add(chunk)
    # Character bigrams help Japanese titles where spaces are rare.
    compact = re.sub(r"\s+", "", normalized)
    for index in range(max(0, len(compact) - 1)):
        token = compact[index : index + 2]
        if token not in TITLE_STOPWORDS:
            chunks.add(token)
    return chunks


def similarity(a: str, b: str) -> float:
    tokens_a = title_tokens(a)
    tokens_b = title_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def parse_release(path: Path) -> dict[str, Any] | None:
    rel = path.relative_to(ROOT)
    match = DATE_RE.match(rel.as_posix())
    if not match:
        return None
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    overview = bullet_items(section_lines(lines, "# 公表概要"))
    year, month, day = match.groups()
    fallback = f"{year}-{month}-{day}"
    title = overview[0] if len(overview) >= 1 else path.stem.split("_", 1)[-1]
    published = overview[1] if len(overview) >= 2 else fallback
    organization = overview[2] if len(overview) >= 3 else path.stem.split("_", 1)[-1]
    source_url = overview[3] if len(overview) >= 4 else ""
    metadata = overview_metadata(overview)
    incident_id = metadata_value(metadata, INCIDENT_ID_KEYS)
    date = normalize_date(published, fallback)
    return {
        "date": date,
        "dateObject": datetime.strptime(date, "%Y-%m-%d"),
        "title": safe_text(title, 240),
        "organization": safe_text(organization, 120),
        "sourceUrl": source_url,
        "archivePath": rel.as_posix(),
        "hasIncidentId": bool(incident_id),
        "incidentId": incident_id,
    }


def candidate_groups(releases: list[dict[str, Any]], max_days: int, min_similarity: float) -> list[dict[str, Any]]:
    by_org: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for release in releases:
        if not release["hasIncidentId"]:
            by_org[release["organization"]].append(release)
    candidates: list[dict[str, Any]] = []
    for organization, items in by_org.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda item: (item["date"], item["archivePath"]))
        used: set[str] = set()
        for index, base in enumerate(items):
            if base["archivePath"] in used:
                continue
            group = [base]
            reasons: list[str] = []
            for other in items[index + 1 :]:
                delta = (other["dateObject"] - base["dateObject"]).days
                if delta < 0 or delta > max_days:
                    continue
                score = similarity(base["title"], other["title"])
                same_source_host = bool(base["sourceUrl"] and other["sourceUrl"] and base["sourceUrl"].split("/")[2:3] == other["sourceUrl"].split("/")[2:3])
                if score >= min_similarity or (same_source_host and score >= min_similarity * 0.7):
                    group.append(other)
                    reasons.append(f"{other['archivePath']}: title similarity {score:.2f}, {delta} days apart")
            if len(group) >= 2:
                for item in group:
                    used.add(item["archivePath"])
                candidate_id = f"{group[0]['date']}-{re.sub(r'[^0-9A-Za-zぁ-んァ-ヶ一-龥]+', '-', organization).strip('-')[:40]}"
                candidates.append({
                    "candidateIncidentId": candidate_id,
                    "organization": organization,
                    "releaseCount": len(group),
                    "firstDate": group[0]["date"],
                    "latestDate": group[-1]["date"],
                    "reasons": reasons,
                    "releases": [{key: item[key] for key in ["date", "title", "archivePath", "sourceUrl"]} for item in group],
                })
    candidates.sort(key=lambda item: (item["latestDate"], item["organization"]), reverse=True)
    return candidates


def markdown_report(candidates: list[dict[str, Any]]) -> str:
    lines = [
        "# [dashboard] 事案グルーピング候補",
        "",
        "同一事案の可能性がある未グループの公表リリース候補です。自動確定ではありません。内容を確認し、同一事案と判断できる場合だけ、各Markdownの `# 公表概要` に同じ `事案ID` を追加してください。",
        "",
        f"生成日時: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"候補数: {len(candidates)}",
        "",
    ]
    if not candidates:
        lines.append("候補はありませんでした。")
        return "\n".join(lines) + "\n"
    for number, candidate in enumerate(candidates[:50], 1):
        lines.extend([
            f"## {number}. {candidate['organization']} / {candidate['firstDate']} - {candidate['latestDate']}",
            "",
            f"候補事案ID: `{candidate['candidateIncidentId']}`",
            f"公表数: {candidate['releaseCount']}",
            "",
            "| 日付 | タイトル | Archive | 原典 |",
            "| --- | --- | --- | --- |",
        ])
        for release in candidate["releases"]:
            lines.append(f"| {release['date']} | {release['title']} | `{release['archivePath']}` | {release['sourceUrl']} |")
        lines.extend(["", "判定理由:"])
        for reason in candidate["reasons"][:5]:
            lines.append(f"- {reason}")
        lines.extend(["", "追記例:", "", "```markdown", f"- 事案ID: {candidate['candidateIncidentId']}", "- 公表種別: 初報 / 続報 / 調査結果 など", "```", ""])
    if len(candidates) > 50:
        lines.append(f"ほか {len(candidates) - 50} 件の候補があります。")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-json", default="data/incident_group_candidates.json")
    parser.add_argument("--output-md", default="data/incident_group_candidates.md")
    parser.add_argument("--max-days", type=int, default=45)
    parser.add_argument("--min-similarity", type=float, default=0.32)
    args = parser.parse_args()
    releases = [item for path in sorted(ROOT.glob("20[0-9][0-9]/[0-1][0-9]/*.md")) if (item := parse_release(path))]
    candidates = candidate_groups(releases, args.max_days, args.min_similarity)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidateCount": len(candidates),
        "maxDays": args.max_days,
        "minSimilarity": args.min_similarity,
        "candidates": candidates,
    }
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(markdown_report(candidates), encoding="utf-8")
    print(f"candidate_count={len(candidates)}")


if __name__ == "__main__":
    main()
