from datetime import date

from PIL import Image

from scripts.make_walls import TILE_H, TILE_W, compose, pick_home, pick_live, write_if_changed


def _cover(root, name, color=(200, 30, 30), size=(480, 300)):
    path = root / "covers" / f"{name}.webp"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "WEBP")
    return f"covers/{name}.webp"


def test_pick_home_takes_earliest_cover_per_month_oldest_first(tmp_path):
    a = _cover(tmp_path, "a"); b = _cover(tmp_path, "b"); c = _cover(tmp_path, "c")
    videos = [
        {"created_at": "2020-02-20 10:00", "cover_local": b},
        {"created_at": "2020-01-05 10:00", "cover_local": a},
        {"created_at": "2020-02-01 10:00", "cover_local": c},   # 二月最早的是 c
        {"created_at": "2020-03-01 10:00", "cover_local": "covers/missing.webp"},  # 文件不存在，跳过
        {"created_at": "2020-03-02 10:00"},                                         # 没有本地封面，跳过
    ]
    assert pick_home(videos, 10, tmp_path) == [a, c]


def test_pick_home_samples_months_evenly_keeping_both_ends(tmp_path):
    videos = []
    for m in range(1, 13):
        name = f"m{m:02d}"
        videos.append({"created_at": f"2021-{m:02d}-01 00:00", "cover_local": _cover(tmp_path, name)})
    picked = pick_home(videos, 4, tmp_path)
    assert len(picked) == 4
    assert picked[0].endswith("m01.webp") and picked[-1].endswith("m12.webp")
    assert picked == sorted(picked)


def test_pick_live_excludes_current_month_and_keeps_most_recent(tmp_path):
    lives = [
        {"date": "2026-07-05", "part": 1, "cover_local": _cover(tmp_path, "l1")},
        {"date": "2026-08-10", "part": 1, "cover_local": _cover(tmp_path, "l2")},
        {"date": "2026-08-10", "part": 2, "cover_local": _cover(tmp_path, "l3")},
        {"date": "2026-09-13", "part": 1, "cover_local": _cover(tmp_path, "l4")},   # 本月，不进墙
        {"date": "2026-06-01", "part": 1, "cover_local": None},
    ]
    assert pick_live(lives, 2, date(2026, 9, 24), tmp_path) == ["covers/l2.webp", "covers/l3.webp"]
    assert pick_live(lives, 10, date(2026, 9, 24), tmp_path) == ["covers/l1.webp", "covers/l2.webp", "covers/l3.webp"]


def test_compose_fills_the_grid_and_is_deterministic(tmp_path):
    paths = [_cover(tmp_path, "x", (10, 120, 200)), _cover(tmp_path, "y", (220, 180, 20), size=(300, 300))]
    data = compose(paths, 3, 2, tmp_path)
    assert data == compose(paths, 3, 2, tmp_path)
    out = tmp_path / "wall.webp"
    out.write_bytes(data)
    with Image.open(out) as im:
        assert im.size == (3 * TILE_W, 2 * TILE_H)
        assert im.format == "WEBP"


def test_write_if_changed_only_writes_new_bytes(tmp_path):
    target = tmp_path / "static" / "wall.webp"
    assert write_if_changed(target, b"one") is True
    assert target.read_bytes() == b"one"
    assert write_if_changed(target, b"one") is False
    assert write_if_changed(target, b"two", dry_run=True) is True
    assert target.read_bytes() == b"one"
