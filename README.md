# Stanley RSS Reader

重构后：**抓取产出数据（JSON + RSS XML）**，由 Web 服务实时渲染 HTML。

## 目录

- `scripts/fetch_rss.py`：抓取 RSS，写入 `output/latest.json` + `output/feed.xml`，并推送 MQTT 摘要给 HA。
- `app/server.py`：FastAPI 服务。
- `app/templates/index.html`：页面模板（杂志风可继续调）。
- `output/latest.json`：结构化聚合结果（给前端/API/自动化）。
- `output/feed.xml`：标准 RSS 2.0，对外可订阅。
- `rss_sources.json`：订阅源配置。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# 先抓数据
python scripts/fetch_rss.py --limit 20

# 起服务
uvicorn app.server:app --host 0.0.0.0 --port 8090
```

打开：
- `http://localhost:8090/` 页面
- `http://localhost:8090/feed.xml` RSS 订阅
- `http://localhost:8090/api/news` JSON API

## 定时任务

`run_rss.sh` + `rss-cron.tab` 每天 07:00 执行：

- 抓取并更新 `output/latest.json` / `output/feed.xml`
- 发布 MQTT 状态给 HA
- `--git` 自动 commit + push

## 说明

不再每次生成静态 HTML 文件（`index.html` / `output/latest.html`）。
页面展示由 Web 服务按最新 JSON 实时渲染。
