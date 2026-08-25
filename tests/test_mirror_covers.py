import io
import time
from pathlib import Path

from PIL import Image

from scripts.mirror_covers import fetch, mirror, to_webp


def jpeg_bytes(w=1146, h=717):
    im = Image.new("RGB", (w, h), (200, 30, 30))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


class FakeResponse:
    def __init__(self, status_code, content=b"", headers=None):
        self.status_code, self.content = status_code, content
        self.headers = headers if headers is not None else {"Content-Type": "image/jpeg"}


class FakeSession:
    def __init__(self, mapping):
        self.mapping, self.calls = mapping, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return self.mapping.get(url, FakeResponse(404))


def test_to_webp_resizes_and_encodes():
    out = to_webp(jpeg_bytes(), width=480)
    assert out[:4] == b"RIFF" and out[8:12] == b"WEBP"
    assert Image.open(io.BytesIO(out)).size == (480, 300)


def test_mirror_writes_dead_first_and_skips_existing(tmp_path: Path):
    videos = [
        {"aid": 1, "cover": "http://i0.hdslb.com/a.jpg", "is_available": True, "created_timestamp": 2},
        {"aid": 2, "cover": "http://i0.hdslb.com/b.jpg", "is_available": False, "created_timestamp": 1},
        {"aid": 3, "cover": "http://i0.hdslb.com/c.jpg", "is_available": False, "created_timestamp": 3},
    ]
    (tmp_path / "3.webp").write_bytes(b"existing")
    session = FakeSession({
        "https://i0.hdslb.com/a.jpg": FakeResponse(200, jpeg_bytes()),
        "https://i0.hdslb.com/b.jpg": FakeResponse(200, jpeg_bytes()),
    })
    result = mirror(videos, session, tmp_path, sleep=0)
    assert result == {"ok": 2, "skip": 1, "fail": []}
    assert session.calls[0] == "https://i0.hdslb.com/b.jpg"  # 已删除的排在前面
    assert (tmp_path / "1.webp").exists() and (tmp_path / "2.webp").exists()
    assert (tmp_path / "3.webp").read_bytes() == b"existing"


def test_mirror_records_failures(tmp_path: Path):
    videos = [{"aid": 9, "cover": "http://i0.hdslb.com/missing.jpg", "is_available": False, "created_timestamp": 1}]
    result = mirror(videos, FakeSession({}), tmp_path, sleep=0)
    assert result["fail"] == [9]


def test_fetch_rejects_non_image_content_type(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)  # 避免真实退避等待
    session = FakeSession({
        "https://i0.hdslb.com/d.jpg": FakeResponse(200, b"<html>blocked</html>", headers={"Content-Type": "text/html"}),
    })
    assert fetch("http://i0.hdslb.com/d.jpg", session) is None


def test_mirror_records_non_image_response_as_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)  # 避免真实退避等待
    videos = [{"aid": 5, "cover": "http://i0.hdslb.com/d.jpg", "is_available": False, "created_timestamp": 1}]
    session = FakeSession({
        "https://i0.hdslb.com/d.jpg": FakeResponse(200, b"<html>blocked</html>", headers={"Content-Type": "text/html"}),
    })
    result = mirror(videos, session, tmp_path, sleep=0)
    assert result["fail"] == [5]
    assert not (tmp_path / "5.webp").exists()


def test_mirror_records_undecodable_body_as_failure(tmp_path: Path):
    videos = [{"aid": 6, "cover": "http://i0.hdslb.com/e.jpg", "is_available": False, "created_timestamp": 1}]
    session = FakeSession({
        "https://i0.hdslb.com/e.jpg": FakeResponse(200, b"not actually an image"),  # 默认 Content-Type: image/jpeg
    })
    result = mirror(videos, session, tmp_path, sleep=0)
    assert result["fail"] == [6]
    assert not (tmp_path / "6.webp").exists()


def test_mirror_limit_bounds_items_considered_not_successes(tmp_path: Path):
    videos = [
        {"aid": 10, "cover": "http://i0.hdslb.com/d10.jpg", "is_available": False, "created_timestamp": 3},
        {"aid": 11, "cover": "http://i0.hdslb.com/d11.jpg", "is_available": False, "created_timestamp": 2},
        {"aid": 12, "cover": "http://i0.hdslb.com/d12.jpg", "is_available": False, "created_timestamp": 1},
        {"aid": 20, "cover": "http://i0.hdslb.com/a20.jpg", "is_available": True, "created_timestamp": 5},
    ]
    (tmp_path / "10.webp").write_bytes(b"existing")
    session = FakeSession({
        "https://i0.hdslb.com/d11.jpg": FakeResponse(200, jpeg_bytes()),
        "https://i0.hdslb.com/d12.jpg": FakeResponse(200, jpeg_bytes()),
        "https://i0.hdslb.com/a20.jpg": FakeResponse(200, jpeg_bytes()),
    })
    result = mirror(videos, session, tmp_path, limit=2, sleep=0)
    assert result == {"ok": 1, "skip": 1, "fail": []}
    assert session.calls == ["https://i0.hdslb.com/d11.jpg"]  # 只处理排序后前 2 条，alive 视频不会被请求
