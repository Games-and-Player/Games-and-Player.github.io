# 运维手册

## 一、脚本一览

| 脚本 | 何时运行 | 作用 |
| --- | --- | --- |
| `scripts/update.py` | 每日（Daily Update） | 抓 UP 主新投稿追加进 `db.json`，顺带镜像封面 |
| `scripts/recheck.py` | 每周（Weekly Recheck） | 逐条 view 现存视频判断删除/仅自见；再巡检补档视频是否还活着 |
| `scripts/update_reupload.py` | 每周（Sync Reuploads）或手动 | 从补档合集抓列表并匹配 `reupload_aid`；`--dry-run` 只报告，`--verify` 复核已有匹配，`--offline` 读上次缓存不联网 |
| `scripts/enrich.py` | 迁移与补数据时手动 | 升级到 schema v2 并补 `bvid`/https 封面/`cover_local`；加 `--durations` 用 view 接口补 `duration`/`stat` |
| `scripts/mirror_covers.py` | 有新记录时手动 | 把封面下载成 `covers/{aid}.webp`，已存在的跳过 |
| `scripts/validate.py` | 每次改完 `db.json` | 字段、类型、唯一性、状态一致性校验，出错退出码 1 |
| `scripts/report_unmatched.py` | 整理栏目规则时 | 列出未识别栏目的视频，供填 `data/overrides.json` |

`enrich.py`、`mirror_covers.py`、`update_reupload.py` 都是幂等的，可以放心重跑。

## 二、把 `redesign/phase-1` 合并到 `main`

```bash
git checkout redesign/phase-1
git merge main                      # 冲突只会在 db.json
git checkout --ours db.json         # 保留分支的 v2 文件，不要整体取 main 的
git show main:db.json > /tmp/main_db.json
python - <<'PY'
import json, pathlib
cur  = json.loads(pathlib.Path("db.json").read_text(encoding="utf-8"))
main = json.loads(pathlib.Path("/tmp/main_db.json").read_text(encoding="utf-8"))
known = {v["aid"] for v in cur["videos"]}
added = [v for v in main["videos"] if v["aid"] not in known]
print("main 新增", len(added), [v["aid"] for v in added])
cur["videos"].extend(added)
pathlib.Path("db.json").write_text(json.dumps(cur, ensure_ascii=False, indent=4), encoding="utf-8")
PY
python scripts/mirror_covers.py          # 只下载新记录的封面
python scripts/enrich.py --durations     # 幂等；只给新记录补 bvid/https/cover_local/duration
python scripts/validate.py               # 必须输出 OK
git add db.json covers && git commit -m "data: merge main's daily additions into schema v2"
git checkout main && git merge redesign/phase-1
```

**警告：** 合并后的推送必须包含这一步，否则每日任务会把 v1 文件标成 schema 2 并触发严格校验，四个 workflow 全部变红。

## 三、合并后的检查清单

1. 在 Actions 里手动运行 CI / Daily Update / Weekly Recheck / Sync Reuploads 各一次。
2. 本地用風二中账号刷新 cookie 后跑 `python scripts/update_reupload.py --verify`。
3. 确认线上首页仍显示 2,030 / 481 / 944（旧页面按 `reupload_aid` 计数，尚不区分失效补档）。

## 四、刷新 cookie

```bash
python -c "from utils import BilibiliAPI; BilibiliAPI().login_with_qrcode()"
```

扫码后写入 `data/cookie.json`（已 gitignore）。Actions 用的是 `BILIBILI_COOKIE` secret，过期时 Daily Update 会变红，把新 cookie 更新进 secret 即可。

## 五、已知限制

- 每周巡检约 1567 次接口调用，跑 20–40 分钟。
- 若 Actions 被风控，可改成在本机 cron 运行再 push，workflow 都保留了手动触发。
- `62004 审核中` 视为未知状态，不改动记录，等下一轮巡检。
- `reupload_dead_at` 只由巡检写入；合集同步遇到不同 aid 的新补档会替换 `reupload_aid` 并清除它。
