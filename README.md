# Stanley RSS Reader

已升级为：**抓取写入 SQLite**，Web 服务从 SQLite 读取并渲染页面，同时提供 RSS 订阅。

## 核心结构

- `scripts/fetch_rss.py`：抓取 RSS，写入 SQLite（`data/rss.db`），并导出 `output/latest.json` / `output/feed.xml`（兼容用途）
- `app/storage.py`：SQLite 读写（建表、写快照、读 payload）
- `app/server.py`：FastAPI 服务（页面/API/RSS）
- `app/templates/index.html`：页面模板
- `data/rss.db`：主数据源（运行时生成）

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 抓取并写入 sqlite
python scripts/fetch_rss.py --limit 20

# 启动服务
uvicorn app.server:app --host 0.0.0.0 --port 8090
```

访问：
- `http://localhost:8090/`
- `http://localhost:8090/api/news`
- `http://localhost:8090/feed.xml`

## Docker 部署（推荐云端）

```bash
docker compose up -d --build
```

访问：
- `http://<host>:8090/`
- `http://<host>:8090/api/news`
- `http://<host>:8090/feed.xml`

## 定时任务（云端建议）

推荐用宿主机 cron 调用容器内抓取：

```bash
0 7 * * * cd /opt/stanley-rss-reader && docker compose run --rm rss-web python scripts/fetch_rss.py --limit 20 >> /var/log/stanley-rss-cron.log 2>&1
```

页面/API/RSS 都由服务从 SQLite 实时读取，不再依赖静态 HTML 生成。
