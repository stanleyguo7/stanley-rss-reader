#!/usr/bin/env python3
from __future__ import annotations

import datetime
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_JSON = PROJECT_ROOT / "output" / "latest.json"
FEED_XML = PROJECT_ROOT / "feed.xml"

app = FastAPI(title="Stanley RSS Reader")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def load_payload() -> dict:
    if not DATA_JSON.exists():
        raise HTTPException(status_code=404, detail="latest.json not found, run fetch_rss.py first")
    return json.loads(DATA_JSON.read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    payload = load_payload()
    generated = payload.get("generated")
    generated_local = generated
    try:
        dt = datetime.datetime.fromisoformat(generated)
        generated_local = dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "generated": generated_local,
            "feeds": payload.get("feeds", []),
            "total": payload.get("total_count", 0),
        },
    )


@app.get("/feed.xml")
def feed():
    if not FEED_XML.exists():
        raise HTTPException(status_code=404, detail="feed.xml not found, run fetch_rss.py first")
    return Response(content=FEED_XML.read_text(encoding="utf-8"), media_type="application/rss+xml; charset=utf-8")


@app.get("/api/news")
def api_news():
    return load_payload()
