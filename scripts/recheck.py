"""每周巡检：对现存视频调用 view 接口，发现删除/仅自见即标记；再逐条巡检补档视频是否还活着。
合集列表接口仍会列出已删除的补档，所以「补档还在不在」只能靠 view 接口一条条问。
用法：python scripts/recheck.py [--include-dead] [--refresh-stats] [--sleep 0.5] [--skip-reuploads|--reuploads-only]
退出码：0 正常；2 未知状态过多（风控/网络），本次不写回（两轮巡检任一放弃都不写）。
最后一行输出摘要，供 workflow 写进提交信息。"""
import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.enrich import now_iso, recompute_metadata, write_db  # noqa: E402
from utils.bilibili_api import BilibiliAPI  # noqa: E402

TZ = pytz.timezone("Asia/Shanghai")
DB = Path("db.json")
GONE = {62002: "稿件不可见（已删除）", 62012: "仅UP主自己可见", -404: "啥都木有", 62004: "稿件审核中"}
UNKNOWN_LIMIT = 0.2
STAT_KEYS = ("view", "like", "coin", "favorite", "danmaku")


def decide(video: dict, resp: dict, now_iso: str, today: str, refresh_stats: bool = False) -> dict | None:
    code = resp.get("code", -1)
    if code == 0:
        changes = {"status_check_time": now_iso}
        if not video["is_available"]:
            changes.update({"is_available": True, "status_code": 0, "status_description": "OK", "restored_at": today})
        if refresh_stats:
            s = resp.get("data", {}).get("stat", {})
            changes["stat"] = {k: int(s.get(k, 0)) for k in STAT_KEYS}
            changes["stat"]["at"] = today
        return changes
    if code in GONE:
        changes = {"is_available": False, "status_code": code, "status_description": GONE[code], "status_check_time": now_iso}
        if not video.get("deleted_found_at"):
            changes["deleted_found_at"] = today
        return changes
    return None


def run(videos: list[dict], api, include_dead: bool = False, sleep: float = 0.5,
        refresh_stats: bool = False, now: tuple[str, str] | None = None) -> dict:
    now_iso, today = now or (datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S"), datetime.now(TZ).strftime("%Y-%m-%d"))
    targets = [v for v in videos if v["is_available"] or include_dead]
    pending: list[tuple[dict, dict]] = []
    unknown = 0
    for v in targets:
        change = decide(v, api.get_view(v["aid"]), now_iso, today, refresh_stats)
        if change is None:
            unknown += 1
        else:
            pending.append((v, change))
        time.sleep(sleep + random.random() * sleep)
    checked = len(targets)
    if checked >= 50 and unknown / checked > UNKNOWN_LIMIT:
        print(f"未知状态 {unknown}/{checked} 超过 {UNKNOWN_LIMIT:.0%}，放弃写回")
        raise SystemExit(2)
    summary = {"checked": checked, "changed": 0, "new_deleted": [], "restored": [], "unknown": unknown}
    for v, change in pending:
        if change.get("is_available") is False and v["is_available"]:
            summary["new_deleted"].append(v["aid"])
        if change.get("restored_at"):
            summary["restored"].append(v["aid"])
        if any(k != "status_check_time" for k in change):
            summary["changed"] += 1
        v.update(change)
    return summary


def decide_reupload(video: dict, resp: dict) -> str | None:
    """补档视频存活判定：alive / dead / None（未知，不改）。"""
    code = resp.get("code", -1)
    if code == 0:
        return "alive"
    if code in GONE:
        return "dead"
    return None


def check_reuploads(videos: list[dict], api, sleep: float = 0.5, now: tuple[str, str] | None = None) -> dict:
    _, today = now or (datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S"), datetime.now(TZ).strftime("%Y-%m-%d"))
    targets = [v for v in videos if v.get("reupload_aid")]
    verdicts: list[tuple[dict, str]] = []
    unknown = 0
    for v in targets:
        verdict = decide_reupload(v, api.get_view(v["reupload_aid"]))
        if verdict is None:
            unknown += 1
        else:
            verdicts.append((v, verdict))
        time.sleep(sleep + random.random() * sleep)
    checked = len(targets)
    if checked >= 50 and unknown / checked > UNKNOWN_LIMIT:
        print(f"补档巡检未知状态 {unknown}/{checked} 超过 {UNKNOWN_LIMIT:.0%}，放弃写回")
        raise SystemExit(2)
    summary = {"checked": checked, "new_dead": [], "revived": [], "unknown": unknown}
    for v, verdict in verdicts:
        if verdict == "dead" and not v.get("reupload_dead_at"):
            v["reupload_dead_at"] = today
            summary["new_dead"].append(v["aid"])
        elif verdict == "alive" and v.get("reupload_dead_at"):
            v.pop("reupload_dead_at")
            summary["revived"].append(v["aid"])
    return summary


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-dead", action="store_true")
    ap.add_argument("--refresh-stats", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.5)
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--skip-reuploads", action="store_true", help="只巡检原视频")
    which.add_argument("--reuploads-only", action="store_true", help="只巡检补档视频")
    args = ap.parse_args(argv[1:])
    db = json.loads(DB.read_text(encoding="utf-8"))
    api = BilibiliAPI()
    api.login_with_cookie()
    summary = {"checked": 0, "new_deleted": [], "restored": [], "unknown": 0}
    if not args.reuploads_only:
        summary = run(db["videos"], api, include_dead=args.include_dead, sleep=args.sleep,
                      refresh_stats=args.refresh_stats)
    reups = {"checked": 0, "new_dead": [], "revived": [], "unknown": 0}
    if not args.skip_reuploads:
        reups = check_reuploads(db["videos"], api, sleep=args.sleep)
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    db["metadata"] = recompute_metadata(db["videos"], last_recheck=today)
    db["generated_at"] = now_iso()
    write_db(db)
    by_aid = {v["aid"]: v for v in db["videos"]}
    for aid in summary["new_deleted"]:
        print(f"新发现删除：av{aid} {by_aid[aid]['title']}")
    for aid in reups["new_dead"]:
        print(f"补档失效：av{by_aid[aid]['reupload_aid']} ← {by_aid[aid]['title']}")
    print(f"recheck {today}: checked={summary['checked']} +deleted={len(summary['new_deleted'])} "
          f"+restored={len(summary['restored'])} unknown={summary['unknown']} "
          f"reuploads={reups['checked']} +dead={len(reups['new_dead'])} +revived={len(reups['revived'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
