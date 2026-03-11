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
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/fetch_rss.py --sources rss_sources.json --output output/latest.html --summary-json output/latest.json
```

默认会抓取每个源自上次成功运行后的所有新内容（单源最多 20 条，合计约 160 条），并以栅格卡片形式展示：标题+摘要+“阅读原文”按钮，原始链接不再直接暴露，更方便阅读。脚本默认就是 `--limit 20`，你可以在命令里加 `--limit 5`（或更大）额外限制单次最多拉多少条更新。

想让脚本直接把文件 `git add` / `commit` / `push` 回 GitHub？加上 `--git` 开关，脚本会在当前工作区自动提交当天最新的 `output/latest.html`、`output/latest.json`、根目录 `index.html`，以及新生成的 `output/archive/rss-*.html` / `.json`。

## 归档与历史

执行前会把旧的 `output/latest.html` / `output/latest.json` 复制到 `output/archive/`，文件名里带时间戳，默认只保留最近 30 天的版本。你可以直接在 `output/archive` 里打开历史快报，配合每日分镜会更方便。

## 追踪更新

脚本会在 `state/rss_state.json` 记录每个 RSS 源上一次成功抓取的时间与条目 ID（该文件已加入 `.gitignore`）。每次运行只会把新内容（基于时间戳或链接）呈现在首页，因此不会重复。你可以直接看这个文件判断什么时候有新条目。首页底部有个“查看过去7天的资讯”链接，点击即可进入 `output/archive/index.html`，查看最近一周的历史快报。

## 静态站点（已部署至 Vercel）

我们已经把 `index.html` 设为项目主页，Vercel 会展示最新的 `output/latest.html` 内容（脚本运行后也更新 `index.html`），你可以把这个链接分享给团队成员或直接在飞书里发当前 deploy 网址。

## 定时运行

本地的 `run_rss.sh` + `rss-cron.tab` 会在每天 07:00（系统 crontab）执行：

- 激活 `.venv` 并运行 `python scripts/fetch_rss.py --limit 20 --git`
- 归档 `output/latest.*` 到 `output/archive/`（保留 30 天）并同步更新 `index.html`
- 自动提交并推送最新快报，便于 Vercel 首页实时呈现

如此一来只要在分镜/剧情会议前打开项目主页（`https://stanley-rss-reader.vercel.app/`），就能看到当日新鲜的资讯。