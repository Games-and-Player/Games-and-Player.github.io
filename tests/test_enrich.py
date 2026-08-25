import json
import re
from pathlib import Path

from scripts.enrich import now_iso, recompute_metadata, status_key, upgrade_record, write_db


def video(**over):
    v = {
        "aid": 117132146908944, "title": "t", "cover": "http://i2.hdslb.com/bfs/archive/x.jpg", "desc": "",
        "tags": [], "cid": 1, "created_at": "2026-08-21 14:51", "created_timestamp": 1787295071,
        "status_code": 0, "status_description": "OK", "is_available": True,
        "status_check_time": "2026-08-25T12:48:02",
    }
    v.update(over)
    return v


def test_upgrade_adds_bvid_https_and_cover_local(tmp_path: Path):
    (tmp_path / "117132146908944.webp").write_bytes(b"x")
    out = upgrade_record(video(), tmp_path)
    assert out["bvid"] == "BV1LB8T6xEWe"
    assert out["cover"].startswith("https://")
    assert out["cover_local"] == "covers/117132146908944.webp"
    assert out["deleted_found_at"] is None and out["duration"] is None


def test_upgrade_backfills_deleted_found_at_from_check_time(tmp_path: Path):
    out = upgrade_record(video(is_available=False, status_code=62002, status_check_time="2026-04-04T15:51:12"), tmp_path)
    assert out["deleted_found_at"] == "2026-04-04"


def test_upgrade_is_idempotent(tmp_path: Path):
    once = upgrade_record(video(), tmp_path)
    assert upgrade_record(dict(once), tmp_path) == once


def test_status_key_four_states():
    assert status_key(video()) == "available"
    assert status_key(video(is_available=False, status_code=62002, reupload_aid=5)) == "backup"
    assert status_key(video(is_available=False, status_code=62012)) == "hidden"
    assert status_key(video(is_available=False, status_code=62002)) == "lost"


def test_recompute_metadata_counts():
    videos = [
        video(aid=1, created_at="2017-01-01 00:00"),
        video(aid=2, created_at="2017-02-01 00:00", is_available=False, status_code=62002, reupload_aid=9),
        video(aid=3, created_at="2018-02-01 00:00", is_available=False, status_code=62012),
    ]
    m = recompute_metadata(videos, last_recheck="2026-08-24")
    assert m["total"] == 3 and m["available"] == 1 and m["deleted"] == 1 and m["self_visible"] == 1
    assert m["reuploaded"] == 1 and m["pending_reupload"] == 1
    assert m["by_year"]["2017"] == {"available": 1, "deleted": 1}
    assert m["last_recheck"] == "2026-08-24"


def test_write_db_replaces_existing_target_and_leaves_no_tmp(tmp_path: Path):
    target = tmp_path / "db.json"
    target.write_text("old", encoding="utf-8")
    write_db({"schema_version": 2, "videos": [{"title": "游戏"}]}, target)
    assert json.loads(target.read_text(encoding="utf-8")) == {"schema_version": 2, "videos": [{"title": "游戏"}]}
    assert "游戏" in target.read_text(encoding="utf-8")
    assert not (tmp_path / "db.json.tmp").exists()


def test_now_iso_is_iso8601_with_colon_offset():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00", now_iso())


def test_dead_reupload_is_not_backup():
    v = video(is_available=False, status_code=62002, reupload_aid=5, reupload_dead_at="2026-08-26")
    assert status_key(v) == "lost"
    m = recompute_metadata([v], last_recheck=None)
    assert m["reuploaded"] == 0 and m["pending_reupload"] == 1 and m["reupload_dead"] == 1
