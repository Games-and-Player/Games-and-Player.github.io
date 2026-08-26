import json

from utils.bilibili_api import BilibiliAPI


def _api_with_fake_nav(monkeypatch, responses):
    """responses: list of nav responses returned in order (None = network failure)."""
    monkeypatch.setenv("BILIBILI_COOKIE", json.dumps({"SESSDATA": "x", "bili_jct": "y"}))
    calls = []

    def fake_request(self, method, url, **kwargs):
        calls.append(url)
        return responses.pop(0) if responses else None

    monkeypatch.setattr(BilibiliAPI, "_request", fake_request)
    monkeypatch.setattr("utils.bilibili_api.time.sleep", lambda s: None)
    return BilibiliAPI(), calls


def test_login_succeeds_when_nav_reports_logged_in(monkeypatch):
    api, calls = _api_with_fake_nav(monkeypatch, [{"code": 0, "data": {"isLogin": True, "uname": "u", "mid": 1}}])
    assert api.login_with_cookie() is True
    assert all("web-interface/nav" in u for u in calls)


def test_login_retries_transient_nav_failure(monkeypatch):
    api, calls = _api_with_fake_nav(monkeypatch, [{"code": -352, "message": "风控"}, {"code": 0, "data": {"isLogin": True, "uname": "u", "mid": 1}}])
    assert api.login_with_cookie() is True
    assert len(calls) == 2


def test_login_fails_when_not_logged_in(monkeypatch):
    api, calls = _api_with_fake_nav(monkeypatch, [{"code": -101, "data": {"isLogin": False}}] * 3)
    assert api.login_with_cookie() is False
