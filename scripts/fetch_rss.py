#!/usr/bin/env python3
"""Fetch RSS sources and publish normalized JSON + RSS feed + MQTT summary."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from email.utils import format_datetime
from pathlib import Path

import feedparser
from paho.mqtt import publish

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_PER_SOURCE = 20
REST_WINDOW_HOURS = 24

MQTT_TOPIC_STATE = "homeassistant/sensor/it_rss_brief_mqtt/state"
MQTT_TOPIC_CONFIG = "homeassistant/sensor/it_rss_brief_mqtt/config"


def safe_excerpt(text: str, length: int = 220) -> str:
    if not text:
        return ""
    # strip basic html tags and collapse spaces
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = " ".join(html.unescape(clean).split())
    if len(clean) <= length:
        return clean
    return clean[:length].rstrip() + "…"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sources", type=Path, default=PROJECT_ROOT / "rss_sources.json")
    p.add_argument("--summary-json", type=Path, default=PROJECT_ROOT / "output" / "latest.json")
    p.add_argument("--rss-xml", type=Path, default=PROJECT_ROOT / "output" / "feed.xml")
    p.add_argument("--limit", type=int, default=MAX_PER_SOURCE)
    p.add_argument("--git", action="store_true")
    return p.parse_args()


def parse_entry_ts(entry: dict) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        st = entry.get(key)
        if st:
            return dt.datetime.fromtimestamp(time.mktime(st), dt.timezone.utc)
    for key in ("published", "updated"):
        text = entry.get(key)
        if not text:
            continue
        try:
            parsed = dt.datetime.fromisoformat(text)
            if parsed.tzinfo:
                return parsed.astimezone(dt.timezone.utc)
            return parsed.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def gather_source(feed_cfg: dict, threshold: dt.datetime, limit: int) -> tuple[dict | None, list[dict]]:
    parsed = feedparser.parse(feed_cfg["url"])
    picked: list[tuple[dt.datetime, dict]] = []
    for entry in parsed.entries:
        ts = parse_entry_ts(entry)
        if ts and ts >= threshold:
            picked.append((ts, entry))
    picked.sort(key=lambda x: x[0])
    picked = picked[-limit:]

    entries: list[dict] = []
    flat: list[dict] = []
    for ts, e in picked:
        item = {
            "title": e.get("title", "(no title)"),
            "link": e.get("link", ""),
            "published": e.get("published", e.get("updated", "")),
            "published_ts": ts.isoformat(),
            "summary": safe_excerpt(e.get("summary", e.get("description", ""))),
        }
        entries.append(item)
        flat.append({"source_name": feed_cfg["name"], **item})

    if not entries:
        return None, []

    section = {
        "source_name": feed_cfg["name"],
        "notes": feed_cfg.get("notes", ""),
        "feed_updated": parsed.feed.get("updated", "未知"),
        "count": len(entries),
        "entries": entries,
    }
    return section, flat


def build_feed_xml(items: list[dict], generated: dt.datetime) -> str:
    rss = ET.Element("rss", attrib={"version": "2.0"})
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = "Stanley RSS Digest"
    ET.SubElement(ch, "link").text = "https://stanley-rss-reader.vercel.app/"
    ET.SubElement(ch, "description").text = "Aggregated latest tech/news items"
    ET.SubElement(ch, "language").text = "zh-CN"
    ET.SubElement(ch, "lastBuildDate").text = format_datetime(generated.astimezone(dt.timezone.utc))

    # latest first
    items_sorted = sorted(items, key=lambda x: x.get("published_ts", ""), reverse=True)
    for it in items_sorted:
        node = ET.SubElement(ch, "item")
        ET.SubElement(node, "title").text = f"[{it['source_name']}] {it['title']}"
        ET.SubElement(node, "link").text = it["link"]
        ET.SubElement(node, "guid").text = it["link"] or f"{it['source_name']}::{it['title']}"
        ET.SubElement(node, "description").text = it.get("summary", "")
        if it.get("published_ts"):
            try:
                pub_dt = dt.datetime.fromisoformat(it["published_ts"])
                ET.SubElement(node, "pubDate").text = format_datetime(pub_dt.astimezone(dt.timezone.utc))
            except Exception:
                pass
        ET.SubElement(node, "category").text = it["source_name"]

    xml_bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")


def build_dashboard_summary(sections: list[dict], max_chars: int = 12000) -> tuple[str, int]:
    lines: list[str] = []
    total = 0
    for sec in sections:
        header = f"---\n## 栏目｜{sec['source_name']}\n"
        if len("\n".join(lines)) + len(header) > max_chars:
            break
        lines.append(header)
        for e in sec["entries"]:
            block = [f"### **{e['title']}**"]
            if e.get("published"):
                block.append(f"*{e['published']}*")
            if e.get("summary"):
                block.append(f"> {e['summary']}")
            block.append(f"[查看原文]({e['link']})")
            block.append("")
            text = "\n".join(block)
            if len("\n".join(lines)) + len(text) > max_chars:
                return "\n".join(lines).strip(), total
            lines.append(text)
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


def git_commit_push(now: dt.datetime) -> None:
    subprocess.run(["git", "add", "output/latest.json", "output/feed.xml"], check=True)
    subprocess.run(["git", "commit", "-m", f"chore: update rss digest {now.strftime('%Y-%m-%d')}"], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)


def main() -> None:
    args = parse_args()
    sources = json.loads(args.sources.read_text())
    threshold = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=REST_WINDOW_HOURS)

    sections: list[dict] = []
    flat_items: list[dict] = []
    counts: list[str] = []

    for src in sources:
        section, flat = gather_source(src, threshold, args.limit)
        counts.append(f"{src['name']}({len(flat)})")
        if section:
            sections.append(section)
            flat_items.extend(flat)

    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "generated": now.isoformat(),
        "feeds": sections,
        "items": sorted(flat_items, key=lambda x: x.get("published_ts", ""), reverse=True),
    }

    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.rss_xml.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.rss_xml.write_text(build_feed_xml(payload["items"], now), encoding="utf-8")

    summary_text, item_count = build_dashboard_summary(sections)
    mqtt_summary = f"**RSS更新时间：** {now.isoformat()}\n\n{summary_text}" if summary_text else f"**RSS更新时间：** {now.isoformat()}\n\n暂无资讯"
    publish_to_mqtt(now.isoformat(), mqtt_summary, item_count)

    print(" | ".join(counts))
    if args.git:
        git_commit_push(now)


if __name__ == "__main__":
    main()
