#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator
from starlette.requests import Request

from app.feed import build_feed_xml
from app.storage import get_conn, load_payload

templates = Jinja2Templates(directory="app/templates")
app = FastAPI(title="Stanley RSS Reader")

BJ_TZ = ZoneInfo("Asia/Shanghai")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = PROJECT_ROOT / "rss_sources.json"


class SourceItem(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: HttpUrl
    category: str = Field(default="custom", min_length=1, max_length=40)
    notes: str = Field(default="", max_length=240)

    @field_validator("name", "category", "notes", mode="before")
    @classmethod
    def trim_text(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class SourcesPayload(BaseModel):
    sources: list[SourceItem]


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


def _load_sources() -> list[dict]:
    if not SOURCES_FILE.exists():
        return []
    try:
        raw = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"rss_sources.json 解析失败: {e}") from e

    try:
        payload = SourcesPayload(sources=raw)
    except ValidationError as e:
        raise HTTPException(status_code=500, detail=f"rss_sources.json 格式不合法: {e}") from e
    return [item.model_dump(mode="json") for item in payload.sources]


def _save_sources(sources: list[dict]) -> None:
    payload = SourcesPayload(sources=sources)
    SOURCES_FILE.write_text(
        json.dumps([item.model_dump(mode="json") for item in payload.sources], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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


@app.get("/admin/sources", response_class=HTMLResponse)
def admin_sources_page(request: Request):
    sources = _load_sources()
    return templates.TemplateResponse(
        "admin_sources.html",
        {"request": request, "sources": sources, "sources_file": str(SOURCES_FILE)},
    )


@app.get("/api/sources")
def get_sources():
    return {"sources": _load_sources()}


@app.post("/api/sources")
def save_sources(payload: SourcesPayload):
    _save_sources([item.model_dump(mode="json") for item in payload.sources])
    return {"ok": True, "count": len(payload.sources), "sources_file": str(SOURCES_FILE)}
