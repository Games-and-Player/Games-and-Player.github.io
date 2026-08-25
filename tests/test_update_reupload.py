from scripts import update_reupload
from scripts.update_reupload import find_original, match_reuploads, parse_title, verify

VIDEOS = [
    {"aid": 1, "title": "饮料的执念", "created_at": "2016-12-24 12:00"},
    {"aid": 2, "title": "MD精品漫改幽游白书 一个年代的记忆", "created_at": "2016-12-23 12:00"},
    {"aid": 3, "title": "摇杆漂移问题正损害NS声誉 游戏今日谈20191230", "created_at": "2019-12-30 18:51"},
    {"aid": 4, "title": "另一期同一天的节目", "created_at": "2019-12-30 20:00"},
]


def test_parse_title_strips_suffix_and_date():
    assert parse_title("饮料的执念 (20161224) | 附弹幕") == ("饮料的执念", "2016-12-24")
    assert parse_title("无日期标题 | 仅音频") == ("无日期标题", None)


def test_same_day_picks_most_similar_title():
    assert find_original("摇杆漂移问题正损害NS声誉 (20191230) | 附弹幕", VIDEOS) == 2


def test_same_day_but_unrelated_title_is_rejected():
    assert find_original("完全无关的标题 (20191230) | 附弹幕", VIDEOS) is None


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
    assert "1 条补档已不在合集" in out
    assert videos[1]["reupload_aid"] == 77


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
