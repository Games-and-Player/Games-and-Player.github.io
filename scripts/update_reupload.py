#!/usr/bin/env python3
"""从站主账号的补档合集抓取视频列表，匹配 db.json 并写入 reupload_aid。可重复执行，只新增、不覆盖。
用法：
  python scripts/update_reupload.py            抓取 + 写回
  python scripts/update_reupload.py --dry-run  只报告
  python scripts/update_reupload.py --verify   用新匹配规则复核已有的 reupload_aid，报告不一致与已不在合集中的补档
需要 data/cookie.json（風二中账号）或环境变量 BILIBILI_COOKIE：合集接口要 wbi 签名，
而签名密钥取自已登录的 nav 响应，所以登录失败就没法往下走。"""
import argparse
import difflib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.enrich import now_iso, recompute_metadata, write_db  # noqa: E402
from utils.bilibili_api import BilibiliAPI  # noqa: E402

DB = Path("db.json")
CACHE = Path("data/uploaded_archives.json")
MID = "509617361"        # 站主账号 風二中
SEASON_ID = "5480949"    # 补档合集
SUFFIX = re.compile(r"\s*\|\s*(附弹幕|仅音频)\s*$")
DATE = re.compile(r"\s*\(?(20\d{6})\)?\s*$")
MIN_RATIO = 0.6


def normalize(s: str) -> str:
    s = re.sub(r"\s+", "", s)
    for a, b in (("：", ":"), ("，", ","), ("！", "!"), ("？", "?"), ("（", "("), ("）", ")")):
        s = s.replace(a, b)
    return s.lower()


def parse_title(title: str) -> tuple[str, str | None]:
    t = SUFFIX.sub("", title).strip()
    m = DATE.search(t)
    if not m:
        return t, None
    d = m.group(1)
    return DATE.sub("", t).strip(), f"{d[:4]}-{d[4:6]}-{d[6:]}"


def find_original(title: str, videos: list[dict]) -> int | None:
    clean, day = parse_title(title)
    nt = normalize(clean)
    if day:
        best, best_ratio = None, 0.0
        for i, v in enumerate(videos):
            if v["created_at"][:10] != day:
                continue
            r = difflib.SequenceMatcher(None, nt, normalize(v["title"])).ratio()
            if r > best_ratio:
                best, best_ratio = i, r
        return best if best_ratio >= MIN_RATIO else None
    for i, v in enumerate(videos):
        if normalize(v["title"]) == nt:
            return i
    return None


def match_reuploads(archives: list[dict], videos: list[dict]) -> tuple[int, int, list[str]]:
    new = skip = 0
    unmatched: list[str] = []
    for a in archives:
        idx = find_original(a["title"], videos)
        if idx is None:
            unmatched.append(a["title"])
        elif videos[idx].get("reupload_aid"):
            skip += 1
        else:
            videos[idx]["reupload_aid"] = a["aid"]
            new += 1
    return new, skip, unmatched


def fetch_season_archives(api: BilibiliAPI, mid: str = MID, season_id: str = SEASON_ID) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        params = {"mid": mid, "season_id": season_id, "sort_reverse": "false",
                  "page_size": "30", "page_num": str(page), "wts": str(int(time.time()))}
        params["w_rid"] = api.sign_params(params)
        url = "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list?" + urlencode(params)
        resp = api._request("get", url, headers=api.api_headers)
        if not resp or resp.get("code") != 0:
            raise SystemExit(f"第 {page} 页请求失败: {resp.get('message') if resp else '无响应'}")
        archives = resp["data"].get("archives", [])
        if not archives:
            break
        out.extend(archives)
        if len(out) >= resp["data"].get("page", {}).get("total", 0):
            break
        page += 1
        time.sleep(0.5)
    return out


def verify(archives: list[dict], videos: list[dict]) -> int:
    """用新规则复核已有的 reupload_aid：既报新旧不一致，也报已不在合集中的补档（多半是补档视频本身被删了）。
    只报告不改数据——取消要站主自己确认。返回两类问题之和。"""
    by_reupload = {v["reupload_aid"]: i for i, v in enumerate(videos) if v.get("reupload_aid")}
    bad = 0
    for a in archives:
        if a["aid"] not in by_reupload:
            continue
        idx = find_original(a["title"], videos)
        if idx != by_reupload[a["aid"]]:
            bad += 1
            got = videos[idx]["title"] if idx is not None else None
            print(f"不一致：{a['title']!r} 现指向 {videos[by_reupload[a['aid']]]['title']!r}，新规则 → {got!r}")
    in_season = {a["aid"] for a in archives}
    stale = 0
    for aid, i in by_reupload.items():
        if aid not in in_season:
            stale += 1
            print(f"已不在合集中的补档：av{aid} ← {videos[i]['title']}")
    print(f"复核完成：{bad} 处不一致，{stale} 条补档已不在合集")
    return bad + stale


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv[1:])
    api = BilibiliAPI()
    if not api.login_with_cookie():
        print("登录失败：cookie 可能已过期", file=sys.stderr)
        return 1
    archives = fetch_season_archives(api)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(archives, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"合集共 {len(archives)} 个视频")
    db = json.loads(DB.read_text(encoding="utf-8"))
    videos = db["videos"]
    if args.verify:
        return 1 if verify(archives, videos) else 0
    new, skip, unmatched = match_reuploads(archives, videos)
    print(f"新增 {new}，已存在 {skip}，未匹配 {len(unmatched)}")
    for t in unmatched:
        print("  未匹配：", t)
    if new and not args.dry_run:
        db["metadata"] = recompute_metadata(videos, db.get("metadata", {}).get("last_recheck"))
        db["generated_at"] = now_iso()
        write_db(db)
        print("已写回 db.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
