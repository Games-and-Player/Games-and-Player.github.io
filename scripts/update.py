#!/usr/bin/python3
"""每日：抓取 UP 主新投稿并追加进 db.json（v2 记录），同时镜像封面。"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytz
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generator.bvid import av2bv  # noqa: E402
from scripts.enrich import now_iso, recompute_metadata, write_db  # noqa: E402
from scripts.mirror_covers import COVER_DIR, fetch, to_webp  # noqa: E402
from utils.bilibili_api import BilibiliAPI  # noqa: E402

TZ = pytz.timezone("Asia/Shanghai")
DB = Path("db.json")
MID = "67390259"
STAT_KEYS = ("view", "like", "coin", "favorite", "danmaku")


def make_record(item: dict, tags: list[str], cid: int, view: dict | None, now: datetime) -> dict:
    record = {
        "aid": item["aid"],
        "bvid": av2bv(item["aid"]),
        "title": item["title"],
        "cover": item["pic"].replace("http://", "https://", 1),
        "desc": item.get("description", ""),
        "tags": tags,
        "cid": cid,
        "created_at": datetime.fromtimestamp(item["created"], TZ).strftime("%Y-%m-%d %H:%M"),
        "created_timestamp": item["created"],
        "duration": None,
        "status_code": 0,
        "status_description": "OK",
        "is_available": True,
        "status_check_time": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "deleted_found_at": None,
        "restored_at": None,
    }
    if view and view.get("code") == 0:
        data = view["data"]
        record["duration"] = int(data["duration"])
        s = data.get("stat", {})
        record["stat"] = {k: int(s.get(k, 0)) for k in STAT_KEYS}
        record["stat"]["at"] = now.strftime("%Y-%m-%d")
    return record


def fetch_new(api, mid: str, known: set[int], max_pages: int = 5) -> list[dict]:
    new: list[dict] = []
    for pn in range(1, max_pages + 1):
        res = api.get_vids(mid, str(pn))
        vlist = (res.get("list") or {}).get("vlist") or []
        fresh = [x for x in vlist if x["aid"] not in known]
        new.extend(fresh)
        if not vlist or len(fresh) < len(vlist):
            break
    return new


def main() -> int:
    api = BilibiliAPI()
    api.login_with_cookie()
    db = json.loads(DB.read_text(encoding="utf-8"))
    videos = db["videos"]
    known = {v["aid"] for v in videos}
    now = datetime.now(TZ)
    session = requests.Session()
    for item in fetch_new(api, MID, known):
        aid = item["aid"]
        tags = [t["tag_name"] for t in (api.get_tags(str(aid)) or {}).get("data", [])]
        cid = (api.get_cid(str(aid)) or {}).get("data", [{}])[0].get("cid", 0)
        record = make_record(item, tags, cid, api.get_view(aid), now)
        data = fetch(record["cover"], session)
        if data:
            COVER_DIR.mkdir(exist_ok=True)
            (COVER_DIR / f"{aid}.webp").write_bytes(to_webp(data))
            record["cover_local"] = f"covers/{aid}.webp"
        videos.append(record)
        print(f"新增 av{aid} {record['title']}")
        time.sleep(0.5)
    videos.sort(key=lambda v: v["created_timestamp"], reverse=True)
    db["schema_version"] = 2
    db["generated_at"] = now_iso()
    db["metadata"] = recompute_metadata(videos, db.get("metadata", {}).get("last_recheck"))
    write_db(db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
