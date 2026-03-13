#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.feed import build_feed_xml
from app.storage import get_conn, load_payload

templates = Jinja2Templates(directory="app/templates")
app = FastAPI(title="Stanley RSS Reader")

BJ_TZ = ZoneInfo("Asia/Shanghai")


def _to_bj(ts: str | None) -> str | None:
    if not ts:
        return None
    s = ts.strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BJ_TZ)
    return dt.astimezone(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _with_bj_display(payload: dict) -> dict:
    data = {
        **payload,
        "generated_display": _to_bj(payload.get("generated")),
    }
    feeds = []
    for feed in payload.get("feeds", []):
        entries = []
        for item in feed.get("entries", []):
            entries.append(
                {
                    **item,
                    "published_display": _to_bj(item.get("published_ts") or item.get("published")),
                }
            )
        feeds.append(
            {
                **feed,
                "feed_updated_display": _to_bj(feed.get("feed_updated")),
                "entries": entries,
            }
        )
    data["feeds"] = feeds
    return data


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with get_conn() as conn:
        payload = load_payload(conn)
    payload = _with_bj_display(payload)
    return templates.TemplateResponse("index.html", {"request": request, "data": payload})


@app.get("/feed.xml")
def feed_xml():
    with get_conn() as conn:
        payload = load_payload(conn)
    xml_text = build_feed_xml(payload.get("items", []), payload.get("generated"))
    return Response(xml_text, media_type="application/rss+xml; charset=utf-8")


@app.get("/api/news")
def api_news():
    with get_conn() as conn:
        payload = load_payload(conn)
    return _with_bj_display(payload)
