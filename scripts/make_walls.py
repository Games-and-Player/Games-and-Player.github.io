"""生成页眉横幅用的封面墙：static/wall.webp（投稿存档）与 static/wall-live.webp（直播回放）。

每面墙是一张预先合成好的图，页面只多一次请求，不在浏览器里逐张加载封面。
选图按月取样，所以两张图每月最多变一次：
- 投稿墙：从第一条投稿所在月到本月，每月取当月最早一条有本地封面的投稿；
  月份多于格子数时在月份序列上均匀抽取（左上最早，右下最新）——整面墙就是存档的时间线。
- 直播墙：取本月之前（不含本月）最近的若干场直播封面，从旧到新排。
合成结果和磁盘上的文件字节相同就不写回，workflow 据此判断有没有东西要提交。

  python scripts/make_walls.py           生成 / 更新两张图
  python scripts/make_walls.py --check   只报告会不会变，不写文件
"""
import argparse
import io
import json
import sys
from datetime import date
from pathlib import Path

from PIL import Image

DB = Path("db.json")
LIVES = Path("data/lives.json")
OUT_HOME = Path("static/wall.webp")
OUT_LIVE = Path("static/wall-live.webp")

TILE_W, TILE_H = 120, 75          # 16:10，与封面比例一致
HOME_GRID = (16, 5)               # 80 格 → 1920×375
LIVE_GRID = (16, 4)               # 64 格 → 1920×300
QUALITY = 62                      # 横幅上还要叠一层遮罩，细节不重要，体积优先


def pick_home(videos: list[dict], n: int, root: Path = Path(".")) -> list[str]:
    """每月最早一条有本地封面的投稿，月份多于 n 时均匀抽 n 个，从旧到新。"""
    first_of_month: dict[str, str] = {}
    for v in sorted(videos, key=lambda v: v.get("created_at", "")):
        cover = v.get("cover_local")
        if not cover or not (root / cover).exists():
            continue
        first_of_month.setdefault(v["created_at"][:7], cover)
    months = sorted(first_of_month)
    if len(months) <= n:
        return [first_of_month[m] for m in months]
    return [first_of_month[months[round(i * (len(months) - 1) / (n - 1))]] for i in range(n)]


def pick_live(lives: list[dict], n: int, today: date, root: Path = Path(".")) -> list[str]:
    """本月之前最近的 n 场直播封面，从旧到新；本月的场次下个月才进墙，图因此每月最多变一次。"""
    this_month = today.strftime("%Y-%m")
    eligible = [l for l in lives
                if l["date"][:7] < this_month and l.get("cover_local") and (root / l["cover_local"]).exists()]
    eligible.sort(key=lambda l: (l["date"], l.get("part", 1)))
    return [l["cover_local"] for l in eligible[-n:]]


def compose(paths: list[str], cols: int, rows: int, root: Path = Path(".")) -> bytes:
    """把封面裁成 16:10 小块拼成一张 webp；封面不够填满时循环使用。"""
    canvas = Image.new("RGB", (cols * TILE_W, rows * TILE_H), (20, 26, 33))
    if paths:
        ratio = TILE_W / TILE_H
        for i in range(cols * rows):
            with Image.open(root / paths[i % len(paths)]) as src:
                im = src.convert("RGB")
            w, h = im.size
            if w / h > ratio:
                nw = int(h * ratio)
                im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
            else:
                nh = int(w / ratio)
                im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
            canvas.paste(im.resize((TILE_W, TILE_H), Image.LANCZOS), ((i % cols) * TILE_W, (i // cols) * TILE_H))
    buf = io.BytesIO()
    canvas.save(buf, "WEBP", quality=QUALITY, method=6)
    return buf.getvalue()


def write_if_changed(path: Path, data: bytes, dry_run: bool = False) -> bool:
    """内容有变化才写；返回是否变化。"""
    if path.exists() and path.read_bytes() == data:
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只报告会不会变，不写文件")
    args = ap.parse_args(argv)

    videos = json.loads(DB.read_text(encoding="utf-8"))["videos"]
    lives = json.loads(LIVES.read_text(encoding="utf-8"))["lives"] if LIVES.exists() else []

    home = pick_home(videos, HOME_GRID[0] * HOME_GRID[1])
    live = pick_live(lives, LIVE_GRID[0] * LIVE_GRID[1], date.today())
    if not home:
        print("walls: 没有可用的本地封面，跳过", file=sys.stderr)
        return 1

    changed_home = write_if_changed(OUT_HOME, compose(home, *HOME_GRID), args.check)
    changed_live = write_if_changed(OUT_LIVE, compose(live, *LIVE_GRID), args.check) if live else False
    print(f"walls: home={'changed' if changed_home else 'unchanged'} ({len(home)} covers) "
          f"live={'changed' if changed_live else 'unchanged'} ({len(live)} covers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
