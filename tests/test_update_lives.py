import pytest

from scripts.update_lives import parse_live_title, recheck_lives, sort_and_number, upsert_owner
from utils.bilibili_api import BilibiliAPI

OWNER = {"name": "風二中", "mid": 509617361}


def test_parse_live_title_standard():
    title = "【直播回放】宋少弘直播 | 20260908 | 时之笛直面会 | 附直播弹幕"
    assert parse_live_title(title) == ("2026-09-08", "时之笛直面会")


def test_parse_live_title_no_topic_falls_back_to_regex():
    assert parse_live_title("宋少弘直播录屏20221202") == ("2022-12-02", "")


def test_parse_live_title_no_date():
    assert parse_live_title("完全没有日期的标题") == (None, "")


def archive(aid, title, pic="http://i0.hdslb.com/bfs/archive/x.jpg", duration=100,
            view=1, pubdate=1757304000):
    return {"aid": aid, "bvid": f"BV{aid}", "title": title, "pic": pic,
            "duration": duration, "pubdate": pubdate, "stat": {"view": view}}


def make_owner(aid, dead_at=None, views=1, title="旧标题 | 20260101 | 旧主题 | 附直播弹幕"):
    return {"date": "2026-01-01", "topic": "旧主题", "part": 1, "source": "owner",
            "aid": aid, "bvid": f"BV{aid}", "title": title, "duration": 1,
            "uploaded_at": "2026-01-01", "views": views, "cover": "http://x/y.jpg",
            "cover_local": None, "author": dict(OWNER), "dead_at": dead_at}


def make_early(aid):
    return {"date": "2022-06-13", "topic": "", "part": 1, "source": "early",
            "aid": aid, "bvid": f"BV{aid}", "title": "宋少弘直播录屏20220613", "duration": 6822,
            "uploaded_at": "2022-06-13", "views": 9997, "cover": "http://x/e.jpg",
            "cover_local": None, "author": {"name": "辰默呵", "mid": 175513102}, "dead_at": None}


def test_upsert_owner_leaves_early_records_untouched():
    early = make_early(1)
    lives, new = upsert_owner([early], [], "2026-09-09")
    assert lives == [early] and new == 0


def test_upsert_owner_updates_matching_owner_record_by_aid():
    existing = make_owner(42, views=1)
    a = archive(42, "新标题 | 20260101 | 新主题 | 附直播弹幕", view=999, duration=222)
    lives, new = upsert_owner([existing], [a], "2026-09-09")
    assert new == 0
    r = lives[0]
    assert r["views"] == 999 and r["duration"] == 222 and r["title"] == a["title"]
    assert r["topic"] == "新主题" and r["dead_at"] is None


def test_upsert_owner_marks_missing_owner_records_dead_without_deleting():
    existing = make_owner(42)
    lives, new = upsert_owner([existing], [], "2026-09-09")
    assert new == 0
    assert len(lives) == 1
    assert lives[0]["aid"] == 42 and lives[0]["dead_at"] == "2026-09-09"


def test_upsert_owner_does_not_overwrite_an_already_set_dead_at():
    existing = make_owner(42, dead_at="2026-01-01")
    lives, _ = upsert_owner([existing], [], "2026-09-09")
    assert lives[0]["dead_at"] == "2026-01-01"


def test_upsert_owner_skips_unparseable_titles(capsys):
    a = archive(7, "完全没有日期的标题")
    lives, new = upsert_owner([], [a], "2026-09-09")
    assert lives == [] and new == 0
    assert "无法解析" in capsys.readouterr().out


def test_upsert_owner_adds_new_records():
    a = archive(99, "标题 | 20260201 | 主题 | 附直播弹幕")
    lives, new = upsert_owner([], [a], "2026-09-09")
    assert new == 1
    assert lives[0]["aid"] == 99 and lives[0]["source"] == "owner" and lives[0]["dead_at"] is None


class FakeApi:
    def __init__(self, results):
        self.results = results

    def get_view(self, aid):
        return self.results[aid]


def test_recheck_lives_marks_invisible_dead():
    lives = [make_owner(1)]
    api = FakeApi({1: {"code": 62002, "message": "不可见"}})
    changed = recheck_lives(lives, api, "2026-09-09", sleep=0)
    assert lives[0]["dead_at"] == "2026-09-09"
    assert changed == {"dead": 1, "revived": 0}


def test_recheck_lives_clears_dead_at_when_visible_again():
    lives = [make_owner(1, dead_at="2026-08-01")]
    api = FakeApi({1: {"code": 0, "data": {}}})
    changed = recheck_lives(lives, api, "2026-09-09", sleep=0)
    assert lives[0]["dead_at"] is None
    assert changed == {"dead": 0, "revived": 1}


def test_recheck_lives_leaves_unknown_status_untouched():
    lives = [make_owner(1)]
    api = FakeApi({1: {"code": 62004, "message": "审核中"}})
    changed = recheck_lives(lives, api, "2026-09-09", sleep=0)
    assert lives[0]["dead_at"] is None
    assert changed == {"dead": 0, "revived": 0}


def test_recheck_lives_marks_early_record_dead_without_touching_other_fields():
    """辰默呵的号不受我们控制：巡检也要能把早期录像标成已失效，但除 dead_at 外一个字段都不能碰。"""
    early = make_early(1)
    before = dict(early)
    api = FakeApi({1: {"code": 62002, "message": "不可见"}})
    changed = recheck_lives([early], api, "2026-09-09", sleep=0)
    assert changed == {"dead": 1, "revived": 0}
    assert early["dead_at"] == "2026-09-09"
    assert {k: v for k, v in early.items() if k != "dead_at"} == \
           {k: v for k, v in before.items() if k != "dead_at"}


def test_recheck_lives_revives_early_record():
    early = make_early(1)
    early["dead_at"] = "2026-08-01"
    api = FakeApi({1: {"code": 0, "data": {}}})
    changed = recheck_lives([early], api, "2026-09-09", sleep=0)
    assert changed == {"dead": 0, "revived": 1}
    assert early["dead_at"] is None


def test_upsert_owner_never_touches_early_even_when_archives_reference_other_aids():
    early = make_early(1)
    before = dict(early)
    a = archive(2, "标题 | 20260201 | 主题 | 附直播弹幕")
    lives, _ = upsert_owner([early, make_owner(2)], [a], "2026-09-09")
    assert lives[0] == before


class UnknownApi:
    """>20% 的记录返回未知状态（审核中/风控），巡检必须放弃写回而不是带着半套结果落盘。"""

    def get_view(self, aid):
        return {"code": 62004} if aid % 3 == 0 else {"code": 0}


def test_recheck_lives_aborts_without_mutating_when_too_many_unknown():
    lives = [make_owner(i) for i in range(60)]  # aid%3==0 → 20/60 未知，超过 UNKNOWN_LIMIT=0.2
    with pytest.raises(SystemExit) as exc:
        recheck_lives(lives, UnknownApi(), "2026-09-09", sleep=0)
    assert exc.value.code == 2
    assert all(r["dead_at"] is None for r in lives)


def test_sort_and_number_orders_by_date_desc_then_part_asc_by_aid():
    a = make_owner(10)
    a["date"] = "2026-09-01"
    b = make_owner(20)
    b["date"] = "2026-09-01"
    c = make_owner(5)
    c["date"] = "2026-09-02"
    result = sort_and_number([a, b, c])
    assert [(r["aid"], r["date"], r["part"]) for r in result] == [
        (5, "2026-09-02", 1), (10, "2026-09-01", 1), (20, "2026-09-01", 2)]


def test_fake_api_surface_exists_on_real_api():
    """假 API 只在测试里用函数引用传（get_view 等），grep 找不到；每个公开方法都必须真的存在于 BilibiliAPI。"""
    for name in dir(FakeApi):
        if not name.startswith("_"):
            assert callable(getattr(BilibiliAPI, name, None)), f"BilibiliAPI 缺少 {name}"
