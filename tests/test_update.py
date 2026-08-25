import io
import json
from datetime import datetime

import pytz
from PIL import Image

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


def test_fetch_new_paces_every_page_request(monkeypatch):
    """翻页请求之间必须有间隔，否则连打 api.bilibili.com 会吃 -412。"""
    sleeps: list[float] = []
    monkeypatch.setattr(update.time, "sleep", sleeps.append)
    pages = {1: {"list": {"vlist": [{"aid": 3}]}}, 2: {"list": {"vlist": [{"aid": 2}, {"aid": 1}]}}}
    assert [i["aid"] for i in fetch_new(FakeApi(pages), "67390259", known={1})] == [3, 2]
    assert len(sleeps) >= 2 and set(sleeps) == {0.5}


class StubApi:
    """够 main() 跑完一趟的假客户端：第 1 页一条新稿，第 2 页为空。"""

    def login_with_cookie(self):
        return True

    def get_vids(self, mid, pn):
        return {"list": {"vlist": [dict(ITEM)]}} if int(pn) == 1 else {"list": {"vlist": []}}

    def get_tags(self, aid):
        return {"data": [{"tag_name": "a"}]}

    def get_cid(self, aid):
        return {"data": [{"cid": 7}]}

    def get_view(self, aid):
        return {"code": 0, "data": {"duration": 60, "stat": {"view": 1, "like": 0, "coin": 0, "favorite": 0, "danmaku": 0}}}


def prepare(tmp_path, monkeypatch, api=StubApi):
    """建一个最小 v2 db，并把 update 的读写全部锁进 tmp_path。返回 (路径, 原始内容)。"""
    db_path = tmp_path / "db.json"
    content = json.dumps({"schema_version": 2, "generated_at": "x", "videos": [], "metadata": {}},
                         ensure_ascii=False, indent=4)
    db_path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(update, "BilibiliAPI", api)
    monkeypatch.setattr(update, "DB", db_path)
    monkeypatch.setattr(update.time, "sleep", lambda _: None)
    # write_db 的 path 默认值在定义时就绑定了 enrich.DB，改模块属性无效；
    # 切换工作目录才能保证「万一回归」时写的是临时目录而不是真实 db.json。
    monkeypatch.chdir(tmp_path)
    return db_path, content


def test_main_skips_write_when_no_new_videos(tmp_path, monkeypatch, capsys):
    """没有新稿时不重写 db.json，workflow 的 no changes 分支才会真正生效。"""

    class NoNewApi(StubApi):
        def get_vids(self, mid, pn):
            return {}

    db_path, content = prepare(tmp_path, monkeypatch, NoNewApi)

    assert update.main() == 0
    assert db_path.read_text(encoding="utf-8") == content
    assert "没有新视频" in capsys.readouterr().out


def test_main_fails_loudly_when_login_fails(tmp_path, monkeypatch, capsys):
    """cookie 过期必须报错退出，不能和「今天没新稿」长得一模一样。"""

    class DeadCookieApi(StubApi):  # 没有 get_vids 之外的行为差异：登录一失败就该早退
        def login_with_cookie(self):
            return False

    db_path, content = prepare(tmp_path, monkeypatch, DeadCookieApi)

    assert update.main() == 1
    assert db_path.read_text(encoding="utf-8") == content
    assert "登录失败" in capsys.readouterr().err


def test_main_appends_record_when_cover_cannot_be_decoded(tmp_path, monkeypatch, capsys):
    """封面解码失败只跳过 cover_local，不能让整轮抓取崩掉。"""
    db_path, _ = prepare(tmp_path, monkeypatch)
    covers = tmp_path / "covers"
    monkeypatch.setattr(update, "COVER_DIR", covers)
    monkeypatch.setattr(update, "fetch", lambda url, session: b"not an image")

    assert update.main() == 0
    db = json.loads(db_path.read_text(encoding="utf-8"))
    assert db["schema_version"] == 2 and len(db["videos"]) == 1
    v = db["videos"][0]
    assert v["bvid"] == "BV1LB8T6xEWe" and v["duration"] == 60 and v["tags"] == ["a"] and v["cid"] == 7
    assert "cover_local" not in v
    assert list(covers.iterdir()) == []
    assert f"封面处理失败 av{ITEM['aid']}" in capsys.readouterr().err


def test_main_mirrors_cover_when_image_decodes(tmp_path, monkeypatch):
    buf = io.BytesIO()
    Image.new("RGB", (600, 300), (200, 30, 30)).save(buf, "JPEG")
    db_path, _ = prepare(tmp_path, monkeypatch)
    covers = tmp_path / "covers"
    monkeypatch.setattr(update, "COVER_DIR", covers)
    monkeypatch.setattr(update, "fetch", lambda url, session: buf.getvalue())

    assert update.main() == 0
    v = json.loads(db_path.read_text(encoding="utf-8"))["videos"][0]
    assert v["cover_local"] == f"covers/{ITEM['aid']}.webp"
    assert (covers / f"{ITEM['aid']}.webp").exists()
