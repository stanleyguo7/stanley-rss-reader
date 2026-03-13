from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from email.utils import format_datetime


def build_feed_xml(items: list[dict], generated_iso: str | None) -> str:
    rss = ET.Element("rss", attrib={"version": "2.0"})
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = "Stanley RSS Digest"
    ET.SubElement(ch, "link").text = "https://stanley-rss-reader.vercel.app/"
    ET.SubElement(ch, "description").text = "Aggregated latest tech/news items"
    ET.SubElement(ch, "language").text = "zh-CN"

    now = dt.datetime.now(dt.timezone.utc)
    if generated_iso:
        try:
            now = dt.datetime.fromisoformat(generated_iso).astimezone(dt.timezone.utc)
        except Exception:
            pass
    ET.SubElement(ch, "lastBuildDate").text = format_datetime(now)

    for it in items:
        node = ET.SubElement(ch, "item")
        ET.SubElement(node, "title").text = f"[{it['source_name']}] {it['title']}"
        ET.SubElement(node, "link").text = it.get("link", "")
        ET.SubElement(node, "guid").text = it.get("link", "") or f"{it['source_name']}::{it['title']}"
        ET.SubElement(node, "description").text = it.get("summary", "")
        if it.get("published_ts"):
            try:
                pub_dt = dt.datetime.fromisoformat(it["published_ts"]).astimezone(dt.timezone.utc)
                ET.SubElement(node, "pubDate").text = format_datetime(pub_dt)
            except Exception:
                pass
        ET.SubElement(node, "category").text = it["source_name"]

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")
