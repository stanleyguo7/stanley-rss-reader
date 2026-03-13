# Stanley RSS Reader

重构后：
- 抓取脚本只负责产出**结构化数据**（JSON + RSS XML）
- Web 服务运行时渲染 HTML
- RSS 可对外订阅

## 产物

- `output/latest.json`：聚合后的结构化数据
- `output/latest.xml`：本地 RSS 输出
- `feed.xml`：对外订阅入口（仓库根目录）
- `archive/rss-*.json|xml`：历史快照

## 运行

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# 1) 抓取并生成 JSON + RSS
python scripts/fetch_rss.py --limit 20

# 2) 启动 Web 服务（动态渲染 HTML）
uvicorn app.server:app --host 0.0.0.0 --port 8099
```

访问：
- `http://<host>:8099/` 页面
- `http://<host>:8099/feed.xml` RSS 订阅
- `http://<host>:8099/api/news` JSON API

## 定时任务

`run_rss.sh` + crontab 仍在每天 07:00 执行：
- 抓取数据
- 更新 `output/latest.json` / `feed.xml`
- 发布 MQTT 摘要到 Home Assistant
- 自动 commit + push

## 说明

当前静态 HTML 已不再作为主产物。展示层由 `app/server.py` 运行时渲染，后续改排版只需要改模板 `app/templates/index.html`。
