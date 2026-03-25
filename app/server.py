#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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


class ImaSavePayload(BaseModel):
    url: HttpUrl


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
@app.get("/rss/", response_class=HTMLResponse)
def home(request: Request):
    with get_conn() as conn:
        payload = load_payload(conn)
    payload = _with_bj_display(payload)
    return templates.TemplateResponse(request, "index.html", {"data": payload})


@app.get("/feed.xml")
@app.get("/rss/feed.xml")
def feed_xml():
    with get_conn() as conn:
        payload = load_payload(conn)
    xml_text = build_feed_xml(payload.get("items", []), payload.get("generated"))
    return Response(xml_text, media_type="application/rss+xml; charset=utf-8")


@app.get("/api/news")
@app.get("/rss/api/news")
def api_news():
    with get_conn() as conn:
        payload = load_payload(conn)
    return _with_bj_display(payload)


def _ima_post(path: str, payload: dict, client_id: str, api_key: str) -> dict:
    req = Request(
        f"https://ima.qq.com/{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "ima-openapi-clientid": client_id,
            "ima-openapi-apikey": api_key,
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"IMA 请求失败: HTTP {e.code} {body[:240]}") from e
    except URLError as e:
        raise HTTPException(status_code=502, detail=f"IMA 网络错误: {e}") from e

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"IMA 返回非 JSON: {raw[:240]}") from e


def _resolve_kb_id(client_id: str, api_key: str) -> str:
    kb_id = os.getenv("IMA_KNOWLEDGE_BASE_ID", "").strip()
    if kb_id:
        return kb_id

    res = _ima_post(
        "openapi/wiki/v1/get_addable_knowledge_base_list",
        {"cursor": "", "limit": 1},
        client_id,
        api_key,
    )
    if "retcode" in res and res.get("retcode") != 0:
        raise HTTPException(status_code=502, detail=f"IMA 获取知识库失败: {res.get('errmsg') or res.get('retcode')}")

    data = res.get("data") or {}
    lst = data.get("knowledge_bases") or res.get("addable_knowledge_base_list") or []
    if not lst:
        raise HTTPException(status_code=503, detail="IMA 未找到可添加知识库，请先在 IMA 中创建或授权知识库")
    return (lst[0].get("id") or "").strip()


def _ima_import_url(url: str) -> dict:
    client_id = os.getenv("IMA_OPENAPI_CLIENTID", "").strip()
    api_key = os.getenv("IMA_OPENAPI_APIKEY", "").strip()

    if not client_id or not api_key:
        missing = [
            name
            for name, value in [
                ("IMA_OPENAPI_CLIENTID", client_id),
                ("IMA_OPENAPI_APIKEY", api_key),
            ]
            if not value
        ]
        raise HTTPException(status_code=503, detail=f"IMA 配置缺失: {', '.join(missing)}")

    knowledge_base_id = _resolve_kb_id(client_id, api_key)
    result = _ima_post(
        "openapi/wiki/v1/import_urls",
        {"knowledge_base_id": knowledge_base_id, "urls": [url]},
        client_id,
        api_key,
    )

    if "retcode" in result and result.get("retcode") != 0:
        raise HTTPException(status_code=502, detail=f"IMA 保存失败: {result.get('errmsg') or result.get('retcode')}")

    return result


@app.post("/api/ima/save-url")
@app.post("/rss/api/ima/save-url")
def api_ima_save_url(payload: ImaSavePayload):
    result = _ima_import_url(str(payload.url))
    return {"ok": True, "result": result.get("data", result)}


@app.get("/admin/sources", response_class=HTMLResponse)
@app.get("/rss/admin/sources", response_class=HTMLResponse)
def admin_sources_page(request: Request):
    sources = _load_sources()
    return templates.TemplateResponse(
        request,
        "admin_sources.html",
        {"sources": sources, "sources_file": str(SOURCES_FILE)},
    )


@app.get("/api/sources")
@app.get("/rss/api/sources")
def get_sources():
    return {"sources": _load_sources()}


@app.post("/api/sources")
@app.post("/rss/api/sources")
def save_sources(payload: SourcesPayload):
    _save_sources([item.model_dump(mode="json") for item in payload.sources])
    return {"ok": True, "count": len(payload.sources), "sources_file": str(SOURCES_FILE)}
