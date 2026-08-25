import json
from datetime import datetime

import pytz

from scripts import update
from scripts.update import fetch_new, make_record

NOW = pytz.timezone("Asia/Shanghai").localize(datetime(2026, 8, 25, 12, 48, 2))
ITEM = {"aid": 117132146908944, "title": "深巷的汤包店", "pic": "http://i2.hdslb.com/bfs/archive/x.jpg",
        "description": "d", "created": 1787295071}


def test_make_record_produces_v2_fields():
    view = {"code": 0, "data": {"duration": 807, "stat": {"view": 10, "like": 1, "coin": 0, "favorite": 0, "danmaku": 0}}}
    r = make_record(ITEM, ["a", "b"], 41121022941, view, NOW)
    assert r["bvid"] == "BV1LB8T6xEWe" and r["cover"].startswith("https://")
    assert r["created_at"] == "2026-08-21 14:51" and r["duration"] == 807 and r["stat"]["view"] == 10
    assert r["is_available"] is True and r["deleted_found_at"] is None and r["status_check_time"] == "2026-08-25T12:48:02"


def test_make_record_without_view():
    r = make_record(ITEM, [], 1, None, NOW)
    assert r["duration"] is None and "stat" not in r


class FakeApi:
    def __init__(self, pages):
        self.pages = pages

    def get_vids(self, mid, pn):
        return self.pages.get(int(pn), {})


def test_fetch_new_stops_at_first_page_without_new_aid():
    pages = {1: {"list": {"vlist": [{"aid": 3}, {"aid": 2}]}}, 2: {"list": {"vlist": [{"aid": 1}]}}, 3: {"list": {"vlist": [{"aid": 0}]}}}
    assert [i["aid"] for i in fetch_new(FakeApi(pages), "67390259", known={1, 0})] == [3, 2]


def test_main_skips_write_when_no_new_videos(tmp_path, monkeypatch, capsys):
    """没有新稿时不重写 db.json，workflow 的 no changes 分支才会真正生效。"""
    db_path = tmp_path / "db.json"
    content = json.dumps({"schema_version": 2, "generated_at": "x", "videos": [], "metadata": {}},
                         ensure_ascii=False, indent=4)
    db_path.write_text(content, encoding="utf-8")

    class StubApi:
        def login_with_cookie(self):
            return True

        def get_vids(self, mid, pn):
            return {}

    monkeypatch.setattr(update, "BilibiliAPI", StubApi)
    monkeypatch.setattr(update, "DB", db_path)
    # write_db 的 path 默认值在定义时就绑定了 enrich.DB，改模块属性无效；
    # 切换工作目录才能保证「万一回归」时写的是临时目录而不是真实 db.json。
    monkeypatch.chdir(tmp_path)

    assert update.main() == 0
    assert db_path.read_text(encoding="utf-8") == content
    assert "没有新视频" in capsys.readouterr().out
