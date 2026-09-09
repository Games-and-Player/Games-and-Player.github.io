#!/usr/bin/env python3
"""每周：同步站主直播回放合集（3428508）进 data/lives.json。
不变量：source=='early'（辰默呵的 10 条早期录像种子）的内容字段永不改动；
唯一例外是 dead_at——辰默呵的号不在我们控制下，录像若被下架也要能在页面上显示已失效，
所以巡检对 early 和 owner 一视同仁，只是从不改动 early 的 date/topic/part/aid/bvid/
title/duration/uploaded_at/views/cover/cover_local/author 这些内容字段。
用法：
  python scripts/update_lives.py            登录 + 抓合集 + upsert + 巡检存活 + 镜像封面 + 写回
  python scripts/update_lives.py --dry-run  照常抓取/巡检，只是不写 lives.json、不下载封面
  python scripts/update_lives.py --offline  不联网，改读 data/lives_archives.json 上次抓到的合集缓存
需要 data/cookie.json（風二中账号）或环境变量 BILIBILI_COOKIE：合集接口要 wbi 签名，
签名密钥取自已登录的 nav 响应，所以登录失败就没法往下走。
巡检未知状态过多（B站风控/网络）时放弃写回，退出码 2，与 recheck.py 的 UNKNOWN_LIMIT 一致。"""
import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.enrich import TZ, now_iso, write_db  # noqa: E402
from scripts.mirror_covers import fetch, to_webp  # noqa: E402
from scripts.recheck import GONE, UNKNOWN_LIMIT  # noqa: E402
from scripts.update_reupload import fetch_season_archives  # noqa: E402
from utils.bilibili_api import BilibiliAPI  # noqa: E402

LIVES = Path("data/lives.json")
CACHE = Path("data/lives_archives.json")
COVER_DIR = Path("covers/live")
MID = "509617361"        # 站主账号 風二中
SEASON_ID = "3428508"    # 直播回放合集
OWNER = {"name": "風二中", "mid": 509617361}
API_INTERVAL = 0.5

DATE_SEG = re.compile(r"^\d{8}$")
DATE_ANY = re.compile(r"20\d{6}")


def _fmt_date(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def parse_live_title(title: str) -> tuple[str | None, str]:
    """按 | 切分并 strip()；第 2 段是 YYYYMMDD 则用它做日期、第 3 段做主题；
    切不出时退回正则在整个标题里找 20\\d{6}，主题留空。"""
    parts = [p.strip() for p in title.split("|")]
    if len(parts) >= 2 and DATE_SEG.match(parts[1]):
        topic = parts[2] if len(parts) >= 3 else ""
        return _fmt_date(parts[1]), topic
    m = DATE_ANY.search(title)
    if m:
        return _fmt_date(m.group(0)), ""
    return None, ""


def upsert_owner(lives: list[dict], archives: list[dict]) -> tuple[list[dict], int]:
    """合集里的条目按 aid upsert 进 source=='owner' 的记录（更新 title/topic/duration/views/cover）；
    early 记录不碰。合集成员不是存活信号——一条视频可能只是从合集里移出但仍能看，
    合集里没有的 owner 记录也不动 dead_at；dead_at 唯一由紧随其后的 recheck_lives 判定。"""
    by_aid = {r["aid"]: r for r in lives if r["source"] == "owner"}
    new_count = 0
    for a in archives:
        aid = a["aid"]
        date, topic = parse_live_title(a["title"])
        if date is None:
            print(f"无法解析：{a['title']}")
            continue
        fields = {
            "date": date, "topic": topic, "title": a["title"],
            "duration": a.get("duration"),
            "uploaded_at": datetime.fromtimestamp(a["pubdate"], TZ).strftime("%Y-%m-%d"),
            "views": a.get("stat", {}).get("view", 0),
            "cover": a["pic"].replace("http://", "https://", 1),
        }
        if aid in by_aid:
            by_aid[aid].update(fields)
        else:
            record = {"source": "owner", "aid": aid, "bvid": a.get("bvid", ""),
                      "cover_local": None, "author": dict(OWNER), "dead_at": None, **fields}
            lives.append(record)
            by_aid[aid] = record
            new_count += 1
    return lives, new_count


def _classify(resp: dict) -> str | None:
    """alive / dead / None（未知，不改）——与 recheck.py 的 GONE 判定一致。"""
    code = resp.get("code", -1)
    if code == 0:
        return "alive"
    if code in GONE:
        return "dead"
    return None


def recheck_lives(lives: list[dict], api, today: str, sleep: float = API_INTERVAL) -> dict:
    """逐条调用 get_view，对 owner 和 early 一视同仁（辰默呵的号不受我们控制，下架也要能显示已失效）：
    不可见的标 dead_at（已标过的不覆盖），重新可见的清空。这是巡检唯一会碰的字段——
    早期录像的 date/topic/title/duration/... 等内容字段永不改动。
    先算好每条的判定，等未知状态没超过 UNKNOWN_LIMIT 再统一落到记录上，
    与 recheck.py 的 run() 同一顺序：避免部分应用后半路因风控放弃写回却已经改了内存。"""
    pending: list[tuple[dict, str]] = []
    unknown = 0
    for r in lives:
        verdict = _classify(api.get_view(r["aid"]))
        time.sleep(sleep)
        if verdict is None:
            unknown += 1
        else:
            pending.append((r, verdict))
    checked = len(lives)
    if checked >= 50 and unknown / checked > UNKNOWN_LIMIT:
        print(f"巡检未知状态 {unknown}/{checked} 超过 {UNKNOWN_LIMIT:.0%}，放弃写回")
        raise SystemExit(2)
    changed = {"dead": 0, "revived": 0}
    for r, verdict in pending:
        if verdict == "dead" and r["dead_at"] is None:
            r["dead_at"] = today
            changed["dead"] += 1
        elif verdict == "alive" and r["dead_at"] is not None:
            r["dead_at"] = None
            changed["revived"] += 1
    return changed


def mirror_live_covers(lives: list[dict], session, cover_dir: Path = COVER_DIR) -> int:
    """没有 cover_local 或文件缺失的记录，镜像封面到 covers/live/{aid}.webp；失败留 cover_local=None。"""
    cover_dir.mkdir(parents=True, exist_ok=True)
    added = 0
    for r in lives:
        target = cover_dir / f"{r['aid']}.webp"
        if r.get("cover_local") and target.exists():
            continue
        data = fetch(r["cover"], session)
        if data is None:
            r["cover_local"] = None
            continue
        try:
            target.write_bytes(to_webp(data))
        except (OSError, ValueError):
            r["cover_local"] = None
            continue
        r["cover_local"] = f"covers/live/{r['aid']}.webp"
        added += 1
    return added


def sort_and_number(lives: list[dict]) -> list[dict]:
    """按 date 升序、同日按 aid 升序编号 part；返回按 date 降序、同日 part 升序排列的列表。"""
    ordered = sorted(lives, key=lambda r: (r["date"], r["aid"]))
    counters: dict[str, int] = defaultdict(int)
    for r in ordered:
        counters[r["date"]] += 1
        r["part"] = counters[r["date"]]
    return sorted(ordered, key=lambda r: r["date"], reverse=True)


def build_output(lives: list[dict], generated_at: str) -> dict:
    ordered = sort_and_number(lives)
    return {"schema_version": 1, "generated_at": generated_at, "count": len(ordered), "lives": ordered}


def unchanged(old: dict, new: dict) -> bool:
    """比较两份 build_output() 产物，忽略 generated_at——内容没变就不用落盘，
    workflow 的「无变化不提交」才有机会走到。"""
    return {k: v for k, v in old.items() if k != "generated_at"} == \
           {k: v for k, v in new.items() if k != "generated_at"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args(argv)

    if args.offline:
        if not CACHE.exists():
            print(f"缺少缓存 {CACHE}：先联网跑一次，或把合集列表放到这里", file=sys.stderr)
            return 1
        archives = json.loads(CACHE.read_text(encoding="utf-8"))
        api = None
    else:
        api = BilibiliAPI()
        if not api.login_with_cookie():
            print("登录失败：cookie 可能已过期", file=sys.stderr)
            return 1
        archives = fetch_season_archives(api, MID, SEASON_ID)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(archives, ensure_ascii=False, indent=2), encoding="utf-8")

    lives: list[dict] = []
    if LIVES.exists():
        lives = json.loads(LIVES.read_text(encoding="utf-8"))["lives"]

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    lives, new_count = upsert_owner(lives, archives)

    if api is not None:
        recheck_lives(lives, api, today)

    covers_new = 0
    if api is not None and not args.dry_run:
        covers_new = mirror_live_covers(lives, requests.Session())

    if not args.dry_run:
        output = build_output(lives, now_iso())
        if LIVES.exists() and unchanged(json.loads(LIVES.read_text(encoding="utf-8")), output):
            print("lives: unchanged")
            return 0
        write_db(output, LIVES)

    owner_total = sum(1 for r in lives if r["source"] == "owner")
    early_total = sum(1 for r in lives if r["source"] == "early")
    dead_total = sum(1 for r in lives if r["dead_at"] is not None)
    print(f"lives: owner={owner_total} early={early_total} total={len(lives)} "
          f"+new={new_count} dead={dead_total} covers=+{covers_new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
