#!/usr/bin/env python3
"""Fetch RSS sources and persist snapshot into SQLite (plus JSON/XML exports)."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import feedparser
from paho.mqtt import publish

from app.feed import build_feed_xml
from app.storage import get_conn, save_snapshot
MAX_PER_SOURCE = 20
REST_WINDOW_HOURS = 24

MQTT_TOPIC_STATE = "homeassistant/sensor/it_rss_brief_mqtt/state"
MQTT_TOPIC_CONFIG = "homeassistant/sensor/it_rss_brief_mqtt/config"
BJ_TZ = ZoneInfo("Asia/Shanghai")


def to_bj_text(ts: str | None) -> str:
    if not ts:
        return ""
    s = ts.strip()
    if not s:
        return ""
    try:
        dt_obj = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
    return dt_obj.astimezone(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")


def safe_excerpt(text: str, length: int = 220) -> str:
    if not text:
        return ""
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
    return None


def gather_source(feed_cfg: dict, threshold: dt.datetime, limit: int) -> tuple[dict | None, int]:
    parsed = feedparser.parse(feed_cfg["url"])
    picked: list[tuple[dt.datetime, dict]] = []
    for entry in parsed.entries:
        ts = parse_entry_ts(entry)
        if ts and ts >= threshold:
            picked.append((ts, entry))
    picked.sort(key=lambda x: x[0])
    picked = picked[-limit:]

    entries: list[dict] = []
    for ts, e in picked:
        entries.append(
            {
                "title": e.get("title", "(no title)"),
                "link": e.get("link", ""),
                "published": e.get("published", e.get("updated", "")),
                "published_ts": ts.isoformat(),
                "summary": safe_excerpt(e.get("summary", e.get("description", ""))),
            }
        )

    if not entries:
        return None, 0

    section = {
        "source_name": feed_cfg["name"],
        "notes": feed_cfg.get("notes", ""),
        "feed_updated": parsed.feed.get("updated", "未知"),
        "count": len(entries),
        "entries": entries,
    }
    return section, len(entries)


def build_dashboard_summary(sections: list[dict], max_bytes: int = 12000) -> tuple[str, int]:
    lines: list[str] = []
    total = 0

    def cur(extra: str = "") -> int:
        return len(("\n".join(lines) + extra).encode("utf-8"))

    for sec in sections:
        header = f"---\n## {sec['source_name']}\n"
        if cur(header) > max_bytes:
            break
        lines.append(header)
        for e in sec["entries"]:
            block = [f"### **{e['title']}**"]
            published_bj = to_bj_text(e.get("published_ts") or e.get("published"))
            if published_bj:
                block.append(f"*{published_bj}*")
            if e.get("summary"):
                block.append(f"> {e['summary']}")
            block.append(f"[查看原文]({e['link']})")
            block.append("")
            text = "\n".join(block)
            if cur("\n" + text) > max_bytes:
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
        {"generated": generated, "count": count, "summary": summary, "source": "rss-script/mqtt-direct"},
        ensure_ascii=False,
    )
    publish.single(MQTT_TOPIC_STATE, payload=payload, qos=1, retain=False, hostname=host, port=port, auth=auth)
    print(f"MQTT published: {MQTT_TOPIC_STATE}")


def git_commit_push(now: dt.datetime) -> None:
    subprocess.run(["git", "add", "output/latest.json", "output/feed.xml"], check=True)
    subprocess.run(["git", "commit", "-m", f"chore: update rss digest {now.strftime('%Y-%m-%d')}"], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)


def ensure_sources_file(path: Path) -> None:
    if path.exists():
        return
    template = path.with_suffix(path.suffix + ".template")
    if template.exists():
        path.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")


def main() -> None:
    args = parse_args()
    ensure_sources_file(args.sources)
    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    threshold = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=REST_WINDOW_HOURS)

    sections: list[dict] = []
    counts: list[str] = []
    for src in sources:
        section, count = gather_source(src, threshold, args.limit)
        counts.append(f"{src['name']}({count})")
        if section:
            sections.append(section)

    generated = dt.datetime.now(dt.timezone.utc).isoformat()
    generated_bj = to_bj_text(generated)
    with get_conn() as conn:
        save_snapshot(conn, generated, sections)

    items = sorted(
        [dict(source_name=f["source_name"], **e) for f in sections for e in f.get("entries", [])],
        key=lambda x: x.get("published_ts", ""),
        reverse=True,
    )
    payload = {"generated": generated, "feeds": sections, "items": items}

    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.rss_xml.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.rss_xml.write_text(build_feed_xml(items, generated), encoding="utf-8")

    summary, cnt = build_dashboard_summary(sections)
    mqtt_summary = (
        f"**RSS更新时间：** {generated_bj}\n\n{summary}" if summary else f"**RSS更新时间：** {generated_bj}\n\n暂无资讯"
    )
    publish_to_mqtt(generated_bj, mqtt_summary, cnt)

    print(" | ".join(counts))
    if args.git:
        git_commit_push(dt.datetime.now(dt.timezone.utc))


if __name__ == "__main__":
    main()
