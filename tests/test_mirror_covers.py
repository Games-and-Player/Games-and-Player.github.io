import io
from pathlib import Path

from PIL import Image

from scripts.mirror_covers import mirror, to_webp


def jpeg_bytes(w=1146, h=717):
    im = Image.new("RGB", (w, h), (200, 30, 30))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code, self.content = status_code, content


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
