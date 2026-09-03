import json
from pathlib import Path

from scripts.enrich import av2bv, bv2av


def test_known_pair():
    # 2026-08-21 投稿《深巷的汤包店》，线上核对过的真实对应关系
    assert av2bv(117132146908944) == "BV1LB8T6xEWe"
    assert bv2av("BV1LB8T6xEWe") == 117132146908944


def test_roundtrip_over_whole_db():
    db = json.loads(Path("db.json").read_text(encoding="utf-8"))
    for v in db["videos"]:
        assert bv2av(av2bv(v["aid"])) == v["aid"]
