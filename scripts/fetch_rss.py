#!/usr/bin/env python3
"""Fetch configured RSS sources and publish normalized JSON/RSS artifacts."""

from __future__ import annotations

import argparse
import datetime
import email.utils
import html
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import feedparser
from paho.mqtt import publish

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = PROJECT_ROOT / "archive"
ARCHIVE_RETENTION_DAYS = 30
MAX_PER_SOURCE = 20
REST_WINDOW_HOURS = 24
MQTT_TOPIC_STATE = "homeassistant/sensor/it_rss_brief_mqtt/state"
MQTT_TOPIC_CONFIG = "homeassistant/sensor/it_rss_brief_mqtt/config"


def safe_excerpt(text: str, length: int = 220) -> str:
    if not text:
        return ""
    stripped = " ".join(text.strip().split())
    if len(stripped) <= length:
        return stripped
    return stripped[:length].rstrip() + "…"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=PROJECT_ROOT / "rss_sources.json")
    parser.add_argument("--summary-json", type=Path, default=PROJECT_ROOT / "output" / "latest.json")
    parser.add_argument("--rss-output", type=Path, default=PROJECT_ROOT / "output" / "latest.xml")
    parser.add_argument("--public-rss", type=Path, default=PROJECT_ROOT / "feed.xml")
    parser.add_argument("--limit", type=int, default=MAX_PER_SOURCE)
    parser.add_argument("--git", action="store_true", help="Stage, commit, and push generated artifacts")
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
                return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
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
                "published_ts": ts.isoformat(),
                "summary": safe_excerpt(entry.get("summary", entry.get("description", "")), 220),
            }
        )

    if not section_entries:
        return None, 0

    section = {
        "source_name": feed_cfg["name"],
        "notes": feed_cfg.get("notes", ""),
        "feed_url": feed_cfg["url"],
        "feed_updated": parsed.feed.get("updated", "未知"),
        "count": len(section_entries),
        "entries": section_entries,
    }
    return section, len(section_entries)


def cleanup_archive(directory: Path, retention_days: int) -> None:
    cutoff = time.time() - retention_days * 86400
    directory.mkdir(parents=True, exist_ok=True)
    for child in directory.iterdir():
        if child.is_file() and child.stat().st_mtime < cutoff:
            child.unlink()


def archive_previous(json_path: Path, xml_path: Path, timestamp: str) -> None:
    cleanup_archive(ARCHIVE_DIR, ARCHIVE_RETENTION_DAYS)
    if json_path.exists():
        shutil.copy2(json_path, ARCHIVE_DIR / f"rss-{timestamp}.json")
    if xml_path.exists():
        shutil.copy2(xml_path, ARCHIVE_DIR / f"rss-{timestamp}.xml")


def flatten_entries(results: list[dict]) -> list[dict]:
    items: list[dict] = []
    for section in results:
        for entry in section.get("entries", []):
            items.append(
                {
                    "source_name": section.get("source_name", "未知来源"),
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "published_ts": entry.get("published_ts", ""),
                    "summary": entry.get("summary", ""),
                }
            )
    items.sort(key=lambda x: x.get("published_ts", ""), reverse=True)
    return items


def build_rss_xml(title: str, link: str, description: str, generated: datetime.datetime, items: list[dict]) -> str:
    pub_date = email.utils.format_datetime(generated.astimezone(datetime.timezone.utc))
    rss_items = []
    for item in items:
        item_title = html.escape(f"[{item['source_name']}] {item['title']}")
        item_link = html.escape(item["link"])
        item_desc = html.escape(item.get("summary", ""))
        source = html.escape(item["source_name"])

        try:
            item_dt = datetime.datetime.fromisoformat(item.get("published_ts", "")).astimezone(datetime.timezone.utc)
            item_pub_date = email.utils.format_datetime(item_dt)
        except Exception:
            item_pub_date = pub_date

        guid = item_link or html.escape(f"{item['source_name']}::{item['title']}::{item.get('published_ts', '')}")
        rss_items.append(
            f"""
    <item>
      <title>{item_title}</title>
      <link>{item_link}</link>
      <guid isPermaLink=\"false\">{guid}</guid>
      <pubDate>{item_pub_date}</pubDate>
      <category>{source}</category>
      <description><![CDATA[{item_desc}]]></description>
    </item>""".rstrip()
        )

    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<rss version=\"2.0\">
  <channel>
    <title>{html.escape(title)}</title>
    <link>{html.escape(link)}</link>
    <description>{html.escape(description)}</description>
    <language>zh-CN</language>
    <lastBuildDate>{pub_date}</lastBuildDate>
{''.join(rss_items)}
  </channel>
</rss>
"""


def build_dashboard_summary(results: list[dict], max_chars: int = 12000) -> tuple[str, int]:
    lines: list[str] = []
    total = 0

    for section in results:
        source_name = section.get("source_name", "未知来源")
        entries = section.get("entries", [])
        if not entries:
            continue

        section_header = f"---\n## 栏目｜{source_name}\n"
        if len("\n".join(lines)) + len(section_header) > max_chars:
            break
        lines.append(section_header)

        for entry in entries:
            title = entry.get("title", "")
            published = entry.get("published", "")
            summary = entry.get("summary", "")
            link = entry.get("link", "")

            block_lines = [f"### **{title}**"]
            if published:
                block_lines.append(f"*{published}*")
            if summary:
                block_lines.append(f"> {summary}")
            block_lines.append(f"[查看原文]({link})")
            block_lines.append("")
            block = "\n".join(block_lines)

            if len("\n".join(lines)) + len(block) > max_chars:
                return "\n".join(lines).strip(), total

            lines.append(block)
            total += 1

    return "\n".join(lines).strip(), total


def publish_to_mqtt(generated: str, summary: str, count: int) -> None:
    host = os.getenv("MQTT_HOST", "127.0.0.1")
    port = int(os.getenv("MQTT_PORT", "1883"))
    username = os.getenv("MQTT_USERNAME")
    password = os.getenv("MQTT_PASSWORD")
    if not username or not password:
        print("MQTT credentials missing; skip MQTT publish")
        return

    auth = {"username": username, "password": password}
    config_payload = json.dumps(
        {
            "name": "IT资讯简报(MQTT)",
            "unique_id": "it_rss_brief_mqtt",
            "state_topic": MQTT_TOPIC_STATE,
            "value_template": "{{ value_json.generated }}",
            "json_attributes_topic": MQTT_TOPIC_STATE,
            "icon": "mdi:newspaper-variant-multiple",
        },
        ensure_ascii=False,
    )
    publish.single(MQTT_TOPIC_CONFIG, payload=config_payload, qos=1, retain=True, hostname=host, port=port, auth=auth)

    payload = json.dumps(
        {
            "generated": generated,
            "count": count,
            "summary": summary,
            "source": "rss-script/mqtt-direct",
        },
        ensure_ascii=False,
    )
    publish.single(MQTT_TOPIC_STATE, payload=payload, qos=1, retain=False, hostname=host, port=port, auth=auth)
    print(f"MQTT published: {MQTT_TOPIC_STATE}")


def git_commit_push(date: datetime.datetime) -> None:
    message = f"chore: update rss digest {date.strftime('%Y-%m-%d')}"
    subprocess.run(["git", "add", "output/latest.json", "output/latest.xml", "feed.xml", "archive"], check=True)
    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)


def main() -> None:
    args = parse_args()
    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    threshold = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=REST_WINDOW_HOURS)

    results: list[dict] = []
    counts: list[str] = []
    for source in sources:
        section, count = gather_new_entries(source, args.limit, threshold)
        counts.append(f"{source['name']}({count})")
        if section:
            results.append(section)

    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now.strftime("%Y-%m-%d_%H%M%S")

    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.rss_output.parent.mkdir(parents=True, exist_ok=True)

    archive_previous(args.summary_json, args.rss_output, timestamp)

    json_payload = {
        "generated": now.isoformat(),
        "feeds": results,
        "total_count": sum(x.get("count", 0) for x in results),
    }
    args.summary_json.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    items = flatten_entries(results)
    rss_xml = build_rss_xml(
        title="Stanley RSS Digest",
        link="https://stanley-rss-reader.vercel.app/",
        description="聚合科技 / AI / 影视资讯的订阅源",
        generated=now,
        items=items,
    )
    args.rss_output.write_text(rss_xml, encoding="utf-8")
    args.public_rss.write_text(rss_xml, encoding="utf-8")

    dashboard_summary, item_count = build_dashboard_summary(results)
    payload_summary = f"**RSS更新时间：** {now.isoformat()}\n\n{dashboard_summary}" if dashboard_summary else f"**RSS更新时间：** {now.isoformat()}\n\n暂无资讯"
    publish_to_mqtt(now.isoformat(), payload_summary, item_count)

    print(" | ".join(counts))
    if args.git:
        git_commit_push(now)


if __name__ == "__main__":
    main()
