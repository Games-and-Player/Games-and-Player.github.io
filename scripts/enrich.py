"""把 db.json 升级到 schema v2 并补齐派生字段。可重复运行（幂等）。
用法：
  python scripts/enrich.py              只做本地升级（bvid/https/cover_local/deleted_found_at/metadata）
  python scripts/enrich.py --durations  另外用 view 接口补 duration/stat（约 1600 次请求，每 50 条落盘一次，可中断续跑）"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generator.bvid import av2bv  # noqa: E402
from utils.bilibili_api import BilibiliAPI  # noqa: E402

TZ = pytz.timezone("Asia/Shanghai")
DB = Path("db.json")
COVERS = Path("covers")


def now_iso() -> str:
    """当前时间，ISO 8601 带冒号时区偏移，如 2026-08-26T02:36:46+08:00。"""
    return datetime.now(TZ).isoformat(timespec="seconds")


def write_db(db: dict, path: Path = DB) -> None:
    """原子落盘：先写同目录临时文件，再 os.replace 覆盖，避免中断时留下截断的 db.json。"""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=4), encoding="utf-8")
    os.replace(tmp, path)


def status_key(v: dict) -> str:
    if v["is_available"]:
        return "available"
    if v.get("reupload_aid") and not v.get("reupload_dead_at"):
        return "backup"
    if v["status_code"] == 62012:
        return "hidden"
    return "lost"


def upgrade_record(v: dict, cover_dir: Path) -> dict:
    out = dict(v)
    # main 上有两条记录把 cid/created_timestamp 存成了字符串，严格校验会拒收，排序也会崩
    out["cid"] = int(out["cid"])
    out["created_timestamp"] = int(out["created_timestamp"])
    out["bvid"] = av2bv(out["aid"])
    out["cover"] = out["cover"].replace("http://", "https://", 1)
    if (cover_dir / f"{out['aid']}.webp").exists():
        out["cover_local"] = f"covers/{out['aid']}.webp"
    out.setdefault("duration", None)
    out.setdefault("restored_at", None)
    if out["is_available"]:
        out.setdefault("deleted_found_at", None)
    elif not out.get("deleted_found_at"):
        out["deleted_found_at"] = out["status_check_time"][:10]
    return out


def recompute_metadata(videos: list[dict], last_recheck: str | None) -> dict:
    by_year: dict[str, dict[str, int]] = {}
    counts = {"available": 0, "backup": 0, "hidden": 0, "lost": 0}
    for v in videos:
        key = status_key(v)
        counts[key] += 1
        year = v["created_at"][:4]
        y = by_year.setdefault(year, {"available": 0, "deleted": 0})
        y["available" if key == "available" else "deleted"] += 1
    return {
        "total": len(videos),
        "available": counts["available"],
        "deleted": counts["backup"] + counts["lost"],
        "self_visible": counts["hidden"],
        "reuploaded": counts["backup"],
        "pending_reupload": counts["lost"] + counts["hidden"],
        "reupload_dead": sum(1 for v in videos if v.get("reupload_dead_at")),
        "by_year": dict(sorted(by_year.items())),
        "last_recheck": last_recheck,
    }


def fill_durations(videos: list[dict], api: BilibiliAPI, save, sleep: float = 0.5) -> None:
    """现存视频取本身的 duration/stat；已删除但有补档的取补档视频的 duration。"""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    done = 0
    for v in videos:
        if v.get("duration") is not None:
            continue
        target = v["aid"] if v["is_available"] else v.get("reupload_aid")
        if not target:
            continue
        res = api.get_view(target)
        if res.get("code") != 0:
            print(f"跳过 {v['aid']}: code={res.get('code')} {res.get('message')}")
            time.sleep(sleep)
            continue
        data = res["data"]
        v["duration"] = int(data["duration"])
        if v["is_available"]:
            s = data.get("stat", {})
            v["stat"] = {k: int(s.get(k, 0)) for k in ("view", "like", "coin", "favorite", "danmaku")}
            v["stat"]["at"] = today
        done += 1
        if done % 50 == 0:
            save()
            print(f"已补 {done} 条")
        time.sleep(sleep)
    save()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--durations", action="store_true")
    args = ap.parse_args(argv[1:])
    db = json.loads(DB.read_text(encoding="utf-8"))
    videos = [upgrade_record(v, COVERS) for v in db["videos"]]
    videos.sort(key=lambda v: v["created_timestamp"], reverse=True)
    last_recheck = db.get("metadata", {}).get("last_recheck")

    def save() -> None:
        write_db({
            "schema_version": 2,
            "generated_at": now_iso(),
            "videos": videos,
            "metadata": recompute_metadata(videos, last_recheck),
        })

    if args.durations:
        api = BilibiliAPI()
        api.login_with_cookie()  # 失败也可继续：view 接口无需登录
        fill_durations(videos, api, save)
    else:
        save()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
