import json
from pathlib import Path

from scripts.validate import validate


def base_video(**over):
    v = {
        "aid": 1, "title": "t", "cover": "https://i0.hdslb.com/x.jpg", "desc": "", "tags": [],
        "cid": 2, "created_at": "2026-08-25 07:30", "created_timestamp": 1787614200,
        "status_code": 0, "status_description": "OK", "is_available": True,
        "status_check_time": "2026-08-25T12:48:02",
    }
    v.update(over)
    return v


def test_valid_v1_passes():
    assert validate({"videos": [base_video()]}) == []


def test_duplicate_aid_detected():
    errs = validate({"videos": [base_video(), base_video()]})
    assert any("aid 重复" in e for e in errs)


def test_status_inconsistency_detected():
    errs = validate({"videos": [base_video(is_available=False, status_code=0)]})
    assert any("is_available" in e for e in errs)


def test_strict_mode_requires_v2_fields():
    db = {"schema_version": 2, "videos": [base_video(cover="http://i0.hdslb.com/x.jpg", is_available=False, status_code=62002)]}
    errs = validate(db)
    assert any("bvid" in e for e in errs)
    assert any("https" in e for e in errs)
    assert any("deleted_found_at" in e for e in errs)


def test_strict_mode_requires_descending_order():
    db = {"schema_version": 2, "videos": [
        base_video(aid=1, bvid="BV1", created_timestamp=100, deleted_found_at=None),
        base_video(aid=2, bvid="BV2", created_timestamp=200, deleted_found_at=None),
    ]}
    assert any("倒序" in e for e in validate(db))


def test_real_db_passes_current_schema():
    db = json.loads(Path("db.json").read_text(encoding="utf-8"))
    assert validate(db) == []


def test_reupload_dead_at_is_optional_and_needs_reupload_aid():
    ok = base_video(is_available=False, status_code=62002, reupload_aid=5, reupload_dead_at="2026-08-26")
    assert validate({"videos": [ok]}) == []
    db = {"schema_version": 2, "videos": [base_video(bvid="BV1", is_available=False, status_code=62002,
                                                   deleted_found_at="2026-04-04", reupload_dead_at="2026-08-26")]}
    assert any("reupload_dead_at" in e for e in validate(db))
