import pytest

from scripts.recheck import decide, run

NOW, TODAY = "2026-08-30T04:05:00", "2026-08-30"


def video(**over):
    v = {"aid": 1, "is_available": True, "status_code": 0, "status_description": "OK",
         "status_check_time": "2026-08-25T12:48:02", "deleted_found_at": None, "restored_at": None,
         "created_at": "2026-08-25 07:30", "reupload_aid": None}
    v.update(over)
    return v


def test_available_stays_available_only_touches_time():
    assert decide(video(), {"code": 0, "data": {"stat": {}}}, NOW, TODAY) == {"status_check_time": NOW}


def test_available_becomes_deleted():
    ch = decide(video(), {"code": 62002, "message": "稿件不可见"}, NOW, TODAY)
    assert ch["is_available"] is False and ch["status_code"] == 62002
    assert ch["deleted_found_at"] == TODAY


def test_deleted_found_at_not_overwritten():
    v = video(is_available=False, status_code=62002, deleted_found_at="2026-04-04")
    ch = decide(v, {"code": 62002}, NOW, TODAY)
    assert "deleted_found_at" not in ch


def test_dead_video_restored():
    v = video(is_available=False, status_code=62012, deleted_found_at="2026-04-04")
    ch = decide(v, {"code": 0, "data": {"stat": {}}}, NOW, TODAY)
    assert ch["is_available"] is True and ch["status_code"] == 0 and ch["restored_at"] == TODAY


def test_unknown_code_changes_nothing():
    assert decide(video(), {"code": -352, "message": "风控"}, NOW, TODAY) is None
    assert decide(video(), {"code": -1, "message": "network"}, NOW, TODAY) is None


def test_stats_only_with_flag():
    resp = {"code": 0, "data": {"stat": {"view": 5, "like": 1, "coin": 0, "favorite": 0, "danmaku": 0}}}
    assert "stat" not in decide(video(), resp, NOW, TODAY)
    assert decide(video(), resp, NOW, TODAY, refresh_stats=True)["stat"]["view"] == 5


class FakeApi:
    def __init__(self, codes):
        self.codes = codes

    def get_view(self, aid):
        return {"code": self.codes.get(aid, 0), "data": {"stat": {}}}


def test_run_flags_new_deletions_and_skips_dead_by_default():
    videos = [video(aid=1), video(aid=2), video(aid=3, is_available=False, status_code=62002, deleted_found_at="2026-04-04")]
    summary = run(videos, FakeApi({2: 62002}), sleep=0, now=(NOW, TODAY))
    assert summary["checked"] == 2 and summary["new_deleted"] == [2]
    assert videos[1]["is_available"] is False and videos[1]["deleted_found_at"] == TODAY


def test_run_aborts_when_too_many_unknown():
    videos = [video(aid=i) for i in range(60)]
    api = FakeApi({i: -352 for i in range(20)})
    with pytest.raises(SystemExit) as e:
        run(videos, api, sleep=0, now=(NOW, TODAY))
    assert e.value.code == 2
    assert all(v["status_check_time"] == "2026-08-25T12:48:02" for v in videos)  # 没有写回
