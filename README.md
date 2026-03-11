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

反馈点评会打印每个源抓到的数量。你可以把 `--limit` 调整为 6~8 来抓更丰富的故事，也可以把 `.venv` 名字改成你习惯的虚拟环境目录。

想让脚本直接把文件 `git add` / `commit` / `push` 回 GitHub？加上 `--git` 开关，脚本会在当前工作区自动提交当天最新的 `output/latest.html`、`output/latest.json`、根目录 `index.html`，以及新生成的 `output/archive/rss-*.html` / `.json`。

## 归档与历史

执行前会把旧的 `output/latest.html` / `output/latest.json` 复制到 `output/archive/`，文件名里带时间戳，默认只保留最近 30 天的版本。你可以直接在 `output/archive` 里打开历史快报，配合每日分镜会更方便。

## 静态站点（已部署至 Vercel）

我们已经把 `index.html` 设为项目主页，Vercel 会展示最新的 `output/latest.html` 内容（脚本运行后也更新 `index.html`），你可以把这个链接分享给团队成员或直接在飞书里发当前 deploy 网址。

## 通过 OpenClaw 定期运行

我们已经在 Gateway 中注册了定时任务（Job ID `322cca5a-48de-4842-b634-6d0945919f92`），每天 08:00 Asia/Shanghai：

- 执行命令 `python scripts/fetch_rss.py --sources rss_sources.json --output output/latest.html --summary-json output/latest.json --limit 4 --git`
- 脚本会把命令输出（各源抓到的数量）公告到当前通道，自动提交新快报，并提醒你 `output/latest.html` 里有最新内容。

因此只要你在分镜/剧情会议前打开 `output/latest.html`，就能快速抓到最新的资讯灵感。
