import pytest

from scripts import update_reupload
from scripts.update_reupload import (fetch_season_archives, find_original, match_reuploads,
                                     parse_title, verify)

VIDEOS = [
    {"aid": 1, "title": "饮料的执念", "created_at": "2016-12-24 12:00"},
    {"aid": 2, "title": "MD精品漫改幽游白书 一个年代的记忆", "created_at": "2016-12-23 12:00"},
    {"aid": 3, "title": "摇杆漂移问题正损害NS声誉 游戏今日谈20191230", "created_at": "2019-12-30 18:51"},
    {"aid": 4, "title": "另一期同一天的节目", "created_at": "2019-12-30 20:00"},
]
# 标题里的 20171218 是节目日期，这期隔天才上传
NEXT_DAY = [{"aid": 5, "title": "最终幻想，最初心动 游戏今日谈 20171218", "created_at": "2017-12-19 14:14"}]


def test_parse_title_strips_suffix_and_date():
    assert parse_title("饮料的执念 (20161224) | 附弹幕") == ("饮料的执念", "2016-12-24")
    assert parse_title("无日期标题 | 仅音频") == ("无日期标题", None)


def test_parse_title_strips_stacked_suffixes():
    """合集里有 3 期同时挂了「仅音频」和「附弹幕」，只剥一层会把 | 仅音频 留在标题里、挡住日期。"""
    assert parse_title("荒野大镖客2的神秘事件 游戏早餐车20181203 | 仅音频 | 附弹幕") == (
        "荒野大镖客2的神秘事件 游戏早餐车", "2018-12-03")


def test_same_day_picks_most_similar_title():
    assert find_original("摇杆漂移问题正损害NS声誉 (20191230) | 附弹幕", VIDEOS) == 2


def test_same_day_but_unrelated_title_is_rejected():
    assert find_original("完全无关的标题 (20191230) | 附弹幕", VIDEOS) is None


def test_next_day_upload_still_matches():
    """节目日期与投稿日期差一天的那几期，也得认。"""
    assert find_original("最终幻想，最初心动 游戏今日谈 (20171218) | 附弹幕", NEXT_DAY) == 0


def test_next_day_but_unrelated_title_is_rejected():
    """放宽到隔天不等于放弃标题相似度这道闸。"""
    assert find_original("完全无关的标题 (20171218) | 附弹幕", NEXT_DAY) is None


def test_no_date_requires_exact_title():
    assert find_original("饮料的执念", VIDEOS) == 0
    assert find_original("饮料的执念2", VIDEOS) is None


def test_match_reuploads_never_overwrites():
    videos = [dict(v) for v in VIDEOS]
    videos[0]["reupload_aid"] = 999
    new, skip, unmatched = match_reuploads([
        {"aid": 10, "title": "饮料的执念 (20161224) | 附弹幕"},
        {"aid": 11, "title": "MD精品漫改幽游白书 一个年代的记忆 (20161223) | 附弹幕"},
        {"aid": 12, "title": "消失的名作合集 | 附弹幕"},
    ], videos)
    assert (new, skip, unmatched) == (1, 1, ["消失的名作合集 | 附弹幕"])
    assert videos[0]["reupload_aid"] == 999 and videos[1]["reupload_aid"] == 11


def test_verify_reports_reuploads_missing_from_the_collection(capsys):
    """补档视频被删掉后合集里就没有它了，复核要点名，但不能替站主擅自清空字段。"""
    videos = [dict(v) for v in VIDEOS]
    videos[0]["reupload_aid"] = 10   # 仍在合集里，且新规则指向同一条
    videos[1]["reupload_aid"] = 77   # 合集里已经没有 av77
    archives = [{"aid": 10, "title": "饮料的执念 (20161224) | 附弹幕"}]

    assert verify(archives, videos) == 1
    out = capsys.readouterr().out
    assert "已不在合集中的补档：av77 ← MD精品漫改幽游白书 一个年代的记忆" in out
    assert "复核完成：0 处矛盾，0 条无法推导，1 条补档已不在合集" in out
    assert videos[1]["reupload_aid"] == 77


def test_verify_counts_only_real_contradictions(capsys):
    """新规则指到另一条原视频上，才算数据矛盾。"""
    videos = [dict(v) for v in VIDEOS]
    videos[3]["reupload_aid"] = 30   # 现挂在「另一期同一天的节目」上
    archives = [{"aid": 30, "title": "摇杆漂移问题正损害NS声誉 (20191230) | 附弹幕"}]

    assert verify(archives, videos) == 1
    out = capsys.readouterr().out
    assert "不一致：" in out
    assert "复核完成：1 处矛盾，0 条无法推导，0 条补档已不在合集" in out


def test_verify_does_not_blame_titles_the_rule_cannot_derive(capsys):
    """像「游戏早餐车 SP3」这种无日期又非全等的标题，是规则推不出来，不是站主填错了。"""
    videos = [dict(v) for v in VIDEOS]
    videos[3]["reupload_aid"] = 20
    archives = [{"aid": 20, "title": "同一天的节目 SP3 | 附弹幕"}]

    assert verify(archives, videos) == 0
    out = capsys.readouterr().out
    assert "新规则无法推导（保留现有）：同一天的节目 SP3 | 附弹幕 → 另一期同一天的节目" in out
    assert "复核完成：0 处矛盾，1 条无法推导，0 条补档已不在合集" in out


class FakeSeasonApi:
    """够 fetch_season_archives 跑一趟的假客户端：记录签名拿到的密钥和每次请求的 URL。"""

    api_headers = {"User-Agent": "x"}

    def __init__(self, responses):
        self.responses = responses
        self.mixin_calls = 0
        self.signed_with: list[str | None] = []
        self.urls: list[str] = []

    def get_mixin_key(self):
        self.mixin_calls += 1
        return "k"

    def sign_params(self, params, mixin_key=None):
        self.signed_with.append(mixin_key)
        return "sig"

    def _request(self, method, url, headers=None):
        self.urls.append(url)
        return self.responses[len(self.urls) - 1]


def season_page(archives: list[dict], total: int) -> dict:
    return {"code": 0, "data": {"archives": archives, "page": {"total": total}}}


def test_fetch_season_archives_signs_once_and_paces_every_request(monkeypatch):
    """sign_params 每调一次就多打一次 nav；密钥取一次复用，且每个请求前都先隔开，免得吃 -412。"""
    sleeps: list[float] = []
    monkeypatch.setattr(update_reupload.time, "sleep", sleeps.append)
    api = FakeSeasonApi([season_page([{"aid": 1}, {"aid": 2}], 3), season_page([{"aid": 3}], 3)])

    assert [a["aid"] for a in fetch_season_archives(api)] == [1, 2, 3]
    assert api.mixin_calls == 1 and api.signed_with == ["k", "k"]
    assert len(api.urls) == 2
    assert len(sleeps) >= 2 and set(sleeps) == {0.5}


def test_fetch_season_archives_gives_up_on_a_failed_page(monkeypatch):
    monkeypatch.setattr(update_reupload.time, "sleep", lambda _: None)
    api = FakeSeasonApi([{"code": -412, "message": "请求被拦截"}])

    with pytest.raises(SystemExit) as e:
        fetch_season_archives(api)
    assert "请求被拦截" in str(e.value)


def test_main_fails_loudly_when_login_fails(monkeypatch, capsys):
    """合集接口要 wbi 签名，而签名依赖已登录的 nav 响应：cookie 一过期就该早退，不能带着游客身份去请求。"""

    class DeadCookieApi:
        def login_with_cookie(self):
            return False

    def boom(api):
        raise AssertionError("登录失败后不应再请求合集")

    monkeypatch.setattr(update_reupload, "BilibiliAPI", DeadCookieApi)
    monkeypatch.setattr(update_reupload, "fetch_season_archives", boom)

    assert update_reupload.main(["update_reupload.py", "--verify"]) == 1
    assert "登录失败：cookie 可能已过期" in capsys.readouterr().err


def test_offline_needs_the_cache_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(update_reupload, "CACHE", tmp_path / "uploaded_archives.json")

    assert update_reupload.main(["update_reupload.py", "--offline", "--verify"]) == 1
    assert "缺少缓存" in capsys.readouterr().err


def test_dead_reupload_is_replaced_by_a_new_upload_only():
    videos = [dict(v) for v in VIDEOS]
    videos[0]["reupload_aid"] = 999
    videos[0]["reupload_dead_at"] = "2026-08-26"
    # 合集里仍列着已死的 999：同 aid → 跳过，不清除失效标记
    new, skip, unmatched = match_reuploads([{"aid": 999, "title": "饮料的执念 (20161224) | 附弹幕"}], videos)
    assert (new, skip) == (0, 1) and videos[0]["reupload_dead_at"] == "2026-08-26"
    # 新上传的 1000 → 替换并清除失效标记
    new, skip, unmatched = match_reuploads([{"aid": 1000, "title": "饮料的执念 (20161224) | 附弹幕"}], videos)
    assert (new, skip) == (1, 0) and videos[0]["reupload_aid"] == 1000 and "reupload_dead_at" not in videos[0]
