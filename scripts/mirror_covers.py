"""把 db.json 里的封面镜像为 covers/{aid}.webp（480w，质量 80）。
用法：python scripts/mirror_covers.py [--limit N] [--all-first]
默认已删除视频优先。可重复运行，已存在的文件跳过。
--limit N：最多处理前 N 条（按排序），已存在/失败也计数。"""
import argparse
import io
import json
import sys
import time
from pathlib import Path

import requests
from PIL import Image

COVER_DIR = Path("covers")
WIDTH = 480
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com/",
}


def to_webp(data: bytes, width: int = WIDTH) -> bytes:
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "WEBP", quality=80, method=6)
    return out.getvalue()


def fetch(url: str, session) -> bytes | None:
    url = url.replace("http://", "https://", 1)
    for attempt in range(3):
        try:
            r = session.get(url, headers=HEADERS, timeout=15)
            content_type = str(r.headers.get("Content-Type", "")).lower()
            if r.status_code == 200 and r.content and content_type.startswith("image/"):
                return r.content
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    return None


def mirror(videos: list[dict], session, cover_dir: Path, limit: int | None = None,
           dead_first: bool = True, sleep: float = 0.2) -> dict:
    cover_dir.mkdir(exist_ok=True)
    order = sorted(videos, key=lambda v: (v["is_available"], -v["created_timestamp"])) if dead_first else list(videos)
    if limit is not None:
        order = order[:limit]
    result = {"ok": 0, "skip": 0, "fail": []}
    for v in order:
        target = cover_dir / f"{v['aid']}.webp"
        if target.exists() or not v.get("cover"):
            result["skip"] += 1
            continue
        data = fetch(v["cover"], session)
        if data is None:
            result["fail"].append(v["aid"])
            continue
        try:
            target.write_bytes(to_webp(data))
        except (OSError, ValueError):
            result["fail"].append(v["aid"])
            continue
        result["ok"] += 1
        time.sleep(sleep)
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="最多处理前 N 条（按排序），已存在/失败也计数")
    ap.add_argument("--all-first", action="store_true", help="不按已删除优先")
    args = ap.parse_args(argv[1:])
    db = json.loads(Path("db.json").read_text(encoding="utf-8"))
    result = mirror(db["videos"], requests.Session(), COVER_DIR, limit=args.limit, dead_first=not args.all_first)
    print(f"ok={result['ok']} skip={result['skip']} fail={len(result['fail'])}")
    if result["fail"]:
        print("失败 aid：", result["fail"][:30])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
