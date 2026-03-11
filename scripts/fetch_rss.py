#!/usr/bin/env python3
"""Fetch configured RSS sources, summarize, and render an HTML digest."""

import argparse
import datetime
import json
import shutil
import subprocess
import time
from pathlib import Path
from string import Template

import feedparser


TEMPLATE = Template("""
<!-- Generated: $ts -->
<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <title>RSS Digest</title>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <style>
    :root {
      color-scheme: light dark;
    }
    body {
      font-family: 'Noto Sans SC', 'PingFang SC', system-ui, sans-serif;
      margin: 0;
      padding: 32px;
      background: #f5f5f5;
      color: #111;
    }
    main {
      max-width: 1024px;
      margin: 0 auto;
    }
    header {
      margin-bottom: 24px;
    }
    h1 {
      margin-bottom: 6px;
      font-size: 2em;
    }
    .subtitle {
      color: #666;
      margin-bottom: 20px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 20px;
    }
    section {
      background: #fff;
      border-radius: 16px;
      padding: 18px 20px;
      box-shadow: 0 6px 20px rgba(3, 10, 18, 0.08);
      border: 1px solid #e7e7e7;
    }
    section h2 {
      margin: 0 0 6px;
      font-size: 1.2em;
    }
    .section-meta {
      font-size: 0.9em;
      color: #777;
      margin-bottom: 12px;
    }
    ul {
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .item {
      padding-bottom: 10px;
      border-bottom: 1px solid #f0f0f0;
    }
    .item:last-child {
      border-bottom: none;
    }
    .item strong {
      font-size: 1em;
      display: block;
      margin-bottom: 6px;
    }
    .item .meta {
      font-size: 0.85em;
      color: #999;
    }
    .item p {
      margin: 8px 0 10px;
      color: #333;
      line-height: 1.5;
    }
    .item img {
      max-width: 100%;
      border-radius: 12px;
      margin-top: 6px;
      border: 1px solid #eee;
    }
    .external {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.9em;
      color: #0b73ff;
      text-decoration: none;
      font-weight: 600;
    }
    .external:after {
      content: '↗';
      font-size: 0.8em;
    }
    @media (max-width: 640px) {
      body {
        padding: 18px;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>$title</h1>
      <p class=\"subtitle\">$subtitle</p>
    </header>
    <div class=\"grid\">
      $sections
    </div>
  </main>
</body>
</html>
""")

ENTRY_TEMPLATE = Template("""<section>
  <h2>$source_name</h2>
  <p class=\"section-meta\">$notes · $count 条 · 最后更新：$feed_updated</p>
  <ul>
    $items
  </ul>
</section>""")

ITEM_TEMPLATE = Template("""<li class=\"item\">
  <strong>$title</strong>
  <span class=\"meta\">$published</span>
  <p>$summary</p>
  <a class=\"external\" href=\"$link\" target=\"_blank\" rel=\"noopener\">阅读原文</a>
</li>""")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_RETENTION_DAYS = 30


def safe_excerpt(text: str, length: int = 180) -> str:
    if not text:
        return ""
    stripped = ' '.join(text.strip().split())
    if len(stripped) <= length:
        return stripped
    return stripped[:length].rstrip() + "…"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=PROJECT_ROOT / "rss_sources.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "output" / "latest.html")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--summary-json", type=Path, default=PROJECT_ROOT / "output" / "latest.json")
    parser.add_argument("--git", action="store_true", help="Stage, commit, and push the generated artifacts")
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
            ITEM_TEMPLATE.substitute(
                title=entry["title"],
                published=entry["published"],
                link=entry["link"],
                summary=entry["summary"],
            )
            for entry in section["entries"]
        )
        section_fragments.append(
            ENTRY_TEMPLATE.substitute(
                source_name=section["source_name"],
                notes=section["notes"],
                count=section["count"],
                feed_updated=section["feed_updated"],
                items=items,
            )
        )
    sections_html = "\n  ".join(section_fragments) if section_fragments else "<p>没有抓到任何条目。</p>"
    return TEMPLATE.substitute(
        ts=subtitle,
        title=title,
        subtitle=subtitle,
        sections=sections_html,
    )


def archive_previous(output_path: Path, summary_path: Path, timestamp: str) -> None:
    archive_dir = output_path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    def copy_if_exists(src: Path, suffix: str) -> None:
        if not src.exists():
            return
        dest = archive_dir / f"rss-{timestamp}{suffix}"
        shutil.copy2(src, dest)

    copy_if_exists(output_path, ".html")
    copy_if_exists(summary_path, ".json")
    cleanup_archive(archive_dir, ARCHIVE_RETENTION_DAYS)


def cleanup_archive(directory: Path, retention_days: int) -> None:
    cutoff = time.time() - retention_days * 86400
    for child in sorted(directory.iterdir()):
        if child.is_file() and child.stat().st_mtime < cutoff:
            child.unlink()


def git_commit_push(date: datetime.datetime) -> None:
    message = f"chore: update rss digest {date.strftime('%Y-%m-%d')}"
    subprocess.run(
        ["git", "add", "output/latest.html", "output/latest.json", "output/archive"],
        check=True,
    )
    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)


def main() -> None:
    args = parse_args()
    sources = json.loads(args.sources.read_text())
    results = []
    for source in sources:
        results.append(summarize_feed(source, args.limit))
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H%M%S")
    archive_previous(args.output, args.summary_json, timestamp)
    html = render_html(
        title="RSS 情报摘要",
        subtitle=now.strftime("%Y-%m-%d %H:%M:%S"),
        sections=results,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    args.summary_json.write_text(json.dumps({"generated": now.isoformat(), "feeds": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    index_path = PROJECT_ROOT / "index.html"
    index_path.write_text(html, encoding="utf-8")
    counts = [f"{r['source_name']}({r['count']})" for r in results]
    print(" | ".join(counts))
    if args.git:
        git_commit_push(now)


if __name__ == "__main__":
    main()
