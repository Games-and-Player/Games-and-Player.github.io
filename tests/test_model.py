import json
from pathlib import Path

from generator.model import classify, load_overrides, load_series_rules, load_tag_aliases, status_of, video_tags

RULES = load_series_rules(Path("data/series_rules.json"))
CANON, HIDDEN = load_tag_aliases(Path("data/tag_aliases.json"))


def v(**over):
    base = {"aid": 1, "title": "", "desc": "", "tags": [], "created_at": "2026-01-01 00:00",
            "is_available": True, "status_code": 0}
    base.update(over)
    return base


def test_first_matching_rule_wins():
    assert classify(v(title="真爱至上 游戏往日谈Vol.220"), RULES, {}).slug == "wangritan"


def test_date_range_splits_breakfast_series():
    assert classify(v(desc="本期早餐车", created_at="2026-08-25 07:30"), RULES, {}).slug == "xin-zaocanche"
    assert classify(v(desc="本期早餐车", created_at="2019-06-11 08:00"), RULES, {}).slug == "zaocanche"


def test_title_only_rule_ignores_desc():
    assert classify(v(desc="今天讲个冷知识"), RULES, {}) is None


def test_override_wins():
    over = {1: {"series": "连云港游记"}}
    assert classify(v(title="海边"), RULES, over).slug == "lianyungang"


def test_coverage_on_real_db_at_least_75_percent():
    db = json.loads(Path("db.json").read_text(encoding="utf-8"))
    over = load_overrides(Path("data/overrides.json"))
    matched = sum(1 for x in db["videos"] if classify(x, RULES, over) is not None)
    assert matched / len(db["videos"]) >= 0.75


def test_status_of_four_states():
    assert status_of(v()) == "available"
    assert status_of(v(is_available=False, status_code=62002, reupload_aid=3)) == "backup"
    assert status_of(v(is_available=False, status_code=62012)) == "hidden"
    assert status_of(v(is_available=False, status_code=62002)) == "lost"


def test_video_tags_normalizes_dedups_and_hides():
    tags = ["ps4", "PS4", " switch", "NS", "宋少弘", "游戏杂谈"]
    assert video_tags(v(tags=tags), CANON, HIDDEN) == ["PS4", "Switch", "游戏杂谈"]
