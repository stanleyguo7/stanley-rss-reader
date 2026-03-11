# Stanley RSS Reader

这是给短剧团队准备的轻量级资讯采集项目，用来收藏希望持续追踪的 RSS 源，并通过 OpenClaw 定期抓取、生成 HTML 快报。

## 结构说明

- `rss_sources.json`：保存你希望追踪的 RSS 源（名称、链接、简要说明）。
- `scripts/fetch_rss.py`：从 RSS 里提取最新条目，生成 HTML 和 JSON 摘要。
- `output/latest.html`：自动生成的资讯页面（通过 `fetch_rss.py` 产出）。
- `output/latest.json`：结构化摘要，便于内部自动化或分享。
- `requirements.txt`：依赖说明（当前只需要 `feedparser`）。

## 本地运行

```bash
python -m pip install -r requirements.txt
python scripts/fetch_rss.py --sources rss_sources.json --output output/latest.html --summary-json output/latest.json
```

反馈点评会打印每个源抓到的数量。你可以把 `--limit` 调整为 6~8 来抓更丰富的故事。

## 通过 OpenClaw 定期运行

我们已经在 Gateway 中注册了定时任务（每天 08:00 Asia/Shanghai）：

- 运行命令 `python scripts/fetch_rss.py --sources rss_sources.json --output output/latest.html --summary-json output/latest.json`
- 结果会自动 summary 并发布到当前通道

因此只要你在分镜/剧情会议前打开 `output/latest.html`，就能快速抓到最新的资讯灵感。
