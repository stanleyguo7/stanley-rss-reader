#!/usr/bin/env python3
"""Fetch configured RSS sources, summarize, and render an HTML digest."""

import argparse
import datetime
import json
from pathlib import Path

import feedparser


TEMPLATE = """<!-- Generated: {ts} -->
<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <title>RSS Digest</title>
  <style>
    body {{ font-family: 'Noto Sans SC', sans-serif; margin: 32px; max-width: 980px; }}
    header {{ margin-bottom: 24px; }}
    section {{ margin-bottom: 28px; border-bottom: 1px solid #e5e5e5; padding-bottom: 18px; }}
    h2 {{ margin-bottom: 4px; }}
    ul {{ margin-top: 6px; }}
    li {{ margin-bottom: 10px; }}
    .meta {{ color: #666; font-size: 0.9em; }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <p>{subtitle}</p>
  </header>
  {sections}
</body>
</html>
"""

ENTRY_TEMPLATE = """<section>
  <h2>{source_name}</h2>
  <p class=\"meta\">{notes} · {count} 条 · 最后更新：{feed_updated}</p>
  <ul>
    {items}
  </ul>
</section>"""

ITEM_TEMPLATE = """<li><strong>{title}</strong><br /><span class=\"meta\">{published}</span><br /><a href=\"{link}\">{link}</a><p>{summary}</p></li>"""


def safe_excerpt(text: str, length: int = 180) -> str:
    if not text:
        return ""
    stripped = ' '.join(text.strip().split())
    if len(stripped) <= length:
        return stripped
    return stripped[:length].rstrip() + "…"


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=PROJECT_ROOT / "rss_sources.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "output" / "latest.html")
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--summary-json", type=Path, default=PROJECT_ROOT / "output" / "latest.json")
    return parser.parse_args()


def summarize_feed(feed_cfg: dict, limit: int) -> dict:
    parsed = feedparser.parse(feed_cfg["url"])
    entries = []
    for entry in parsed.entries[:limit]:
        entries.append(
            {
                "title": entry.get("title", "(no title)"),
                "link": entry.get("link", ""),
                "published": entry.get("published", entry.get("updated", "")),
                "summary": safe_excerpt(entry.get("summary", entry.get("description", "")), 200),
            }
        )
    return {
        "source_name": feed_cfg["name"],
        "notes": feed_cfg.get("notes", ""),
        "feed_updated": parsed.feed.get("updated", "未知"),
        "count": len(entries),
        "entries": entries,
    }


def render_html(title: str, subtitle: str, sections: list[dict]) -> str:
    section_fragments = []
    for section in sections:
        items = "\n    ".join(
            ITEM_TEMPLATE.format(
                title=entry["title"],
                published=entry["published"],
                link=entry["link"],
                summary=entry["summary"],
            )
            for entry in section["entries"]
        )
        section_fragments.append(
            ENTRY_TEMPLATE.format(
                source_name=section["source_name"],
                notes=section["notes"],
                count=section["count"],
                feed_updated=section["feed_updated"],
                items=items,
            )
        )
    return TEMPLATE.format(
        ts=subtitle,
        title=title,
        subtitle=subtitle,
        sections="\n  ".join(section_fragments) if section_fragments else "<p>没有抓到任何条目。</p>",
    )


def main() -> None:
    args = parse_args()
    sources = json.loads(args.sources.read_text())
    results = []
    for source in sources:
        results.append(summarize_feed(source, args.limit))
    now = datetime.datetime.now()
    html = render_html(
        title="RSS 情报摘要",
        subtitle=now.strftime("%Y-%m-%d %H:%M:%S"),
        sections=results,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    args.summary_json.write_text(json.dumps({"generated": now.isoformat(), "feeds": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = [f"{r['source_name']}({r['count']})" for r in results]
    print(" | ".join(counts))


if __name__ == "__main__":
    main()
