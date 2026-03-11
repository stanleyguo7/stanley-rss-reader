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
    .footer {
      grid-column: 1 / -1;
      text-align: right;
      margin-top: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
      align-items: center;
      font-size: 0.95em;
    }
    .footer a {
      color: #0b73ff;
      font-weight: 600;
      text-decoration: none;
    }
    .footer .separator {
      color: #999;
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
MAX_PER_SOURCE = 20
HISTORY_WINDOW_DAYS = 7
REST_WINDOW_HOURS = 24


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
    parser.add_argument("--limit", type=int, default=MAX_PER_SOURCE)
    parser.add_argument("--summary-json", type=Path, default=PROJECT_ROOT / "output" / "latest.json")
    parser.add_argument("--git", action="store_true", help="Stage, commit, and push the generated artifacts")
    return parser.parse_args()


def entry_timestamp(entry: dict) -> datetime.datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        struct = entry.get(key)
        if struct:
            return datetime.datetime.fromtimestamp(time.mktime(struct), datetime.timezone.utc)
    for key in ("published", "updated"):
        text = entry.get(key)
        if text:
            try:
                dt = datetime.datetime.fromisoformat(text)
                if dt.tzinfo:
                    return dt.astimezone(datetime.timezone.utc)
                return dt.replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                continue
    return None


def gather_new_entries(feed_cfg: dict, limit: int, threshold: datetime.datetime) -> tuple[dict | None, int]:
    parsed = feedparser.parse(feed_cfg["url"])
    entries = []
    for entry in parsed.entries:
        ts = entry_timestamp(entry)
        if ts and ts >= threshold:
            entries.append((ts, entry))
    entries.sort(key=lambda item: item[0])
    limited = entries[-limit:] if entries else []
    section_entries = []
    for ts, entry in limited:
        section_entries.append(
            {
                "title": entry.get("title", "(no title)"),
                "link": entry.get("link", ""),
                "published": entry.get("published", entry.get("updated", "")),
                "summary": safe_excerpt(entry.get("summary", entry.get("description", "")), 220),
            }
        )
    if not section_entries:
        return None, 0
    section = {
        "source_name": feed_cfg["name"],
        "notes": feed_cfg.get("notes", ""),
        "feed_updated": parsed.feed.get("updated", "未知"),
        "count": len(section_entries),
        "entries": section_entries,
    }
    return section, len(section_entries)


def render_html(title: str, subtitle: str, sections: list[dict], recent_links: list[tuple[str, str]]) -> str:
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
    if recent_links:
        recent_part = ' | '.join(f'<a href="{link}">{label}</a>' for link, label in recent_links)
    else:
        recent_part = '<span>暂无更新</span>'
    footer = f"<footer class=\"footer\"><span>最近更新：</span>{recent_part}<span class=\"separator\">·</span><a href=\"archive/index.html\">查看过去 7 天的资讯</a></footer>"
    return TEMPLATE.substitute(
        ts=subtitle,
        title=title,
        subtitle=subtitle,
        sections=sections_html + "\n  " + footer,
    )


def archive_previous(output_path: Path, summary_path: Path, timestamp: str) -> Path:
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
    return archive_dir


def cleanup_archive(directory: Path, retention_days: int) -> None:
    cutoff = time.time() - retention_days * 86400
    for child in sorted(directory.iterdir()):
        if child.is_file() and child.stat().st_mtime < cutoff:
            child.unlink()


def get_recent_links(archive_dir: Path, limit: int) -> list[tuple[str, str]]:
    files = sorted(archive_dir.glob("rss-*.html"), reverse=True)
    links = []
    for f in files[:limit]:
        ts = f.name.replace("rss-", "")[:-5]
        display = ts.replace("_", " ")
        links.append((f"archive/{f.name}", display))
    return links


def generate_history_index(archive_dir: Path, window_days: int) -> None:
    files = sorted(archive_dir.glob("rss-*.html"), reverse=True)
    recent = files[:window_days]
    items = "\n".join(
        f"  <li><a href=\"./{f.name}\">{f.name.replace('rss-', '')[:-5].replace('_', ' ')}</a></li>"
        for f in recent
    )
    content = f"""
<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <title>历史快报</title>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <style>
    body {{ font-family: 'Noto Sans SC', 'PingFang SC', sans-serif; padding: 32px; background: #141414; color: #fff; }}
    h1 {{ margin-bottom: 12px; }}
    ul {{ padding-left: 16px; }}
    li {{ margin-bottom: 8px; }}
    a {{ color: #4ea5ff; }}
  </style>
</head>
<body>
  <header>
    <h1>过去 7 天的快报</h1>
    <p>点击条目即可查看对应日报。</p>
  </header>
  <ul>
{items}
  </ul>
</body>
</html>
"""
    (archive_dir / "index.html").write_text(content, encoding="utf-8")


def git_commit_push(date: datetime.datetime) -> None:
    message = f"chore: update rss digest {date.strftime('%Y-%m-%d')}"
    subprocess.run(
        ["git", "add", "output/latest.html", "output/latest.json", "index.html", "output/archive"],
        check=True,
    )
    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)


def main() -> None:
    args = parse_args()
    sources = json.loads(args.sources.read_text())
    results = []
    counts = []
    threshold = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=REST_WINDOW_HOURS)
    for source in sources:
        section, count = gather_new_entries(source, args.limit, threshold)
        counts.append(f"{source['name']}({count})")
        if section:
            results.append(section)
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H%M%S")
    archive_dir = archive_previous(args.output, args.summary_json, timestamp)
    generate_history_index(archive_dir, HISTORY_WINDOW_DAYS)
    recent_links = get_recent_links(archive_dir, 3)
    html = render_html(
        title="RSS 情报摘要",
        subtitle=now.strftime("%Y-%m-%d %H:%M:%S"),
        sections=results,
        recent_links=recent_links,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    args.summary_json.write_text(json.dumps({"generated": now.isoformat(), "feeds": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    index_path = PROJECT_ROOT / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(" | ".join(counts))
    if args.git:
        git_commit_push(now)


if __name__ == "__main__":
    main()
