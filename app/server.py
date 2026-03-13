#!/usr/bin/env python3
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.feed import build_feed_xml
from app.storage import get_conn, load_payload

templates = Jinja2Templates(directory="app/templates")
app = FastAPI(title="Stanley RSS Reader")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with get_conn() as conn:
        payload = load_payload(conn)
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
        return load_payload(conn)
