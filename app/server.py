#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_JSON = PROJECT_ROOT / "output" / "latest.json"
FEED_XML = PROJECT_ROOT / "output" / "feed.xml"

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
app = FastAPI(title="Stanley RSS Reader")


def load_payload() -> dict:
    if not DATA_JSON.exists():
        return {"generated": None, "feeds": [], "items": []}
    return json.loads(DATA_JSON.read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    payload = load_payload()
    return templates.TemplateResponse("index.html", {"request": request, "data": payload})


@app.get("/feed.xml")
def feed_xml():
    if not FEED_XML.exists():
        raise HTTPException(status_code=404, detail="feed.xml not found")
    return Response(FEED_XML.read_text(encoding="utf-8"), media_type="application/rss+xml; charset=utf-8")


@app.get("/api/news")
def api_news():
    return load_payload()
