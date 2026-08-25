"""列出未识别栏目的视频（最新在前），供填写 data/overrides.json。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generator.model import classify, load_overrides, load_series_rules  # noqa: E402

rules = load_series_rules(Path("data/series_rules.json"))
overrides = load_overrides(Path("data/overrides.json"))
videos = json.loads(Path("db.json").read_text(encoding="utf-8"))["videos"]
unmatched = [v for v in videos if classify(v, rules, overrides) is None]
print(f"未匹配 {len(unmatched)} / {len(videos)}")
for v in unmatched:
    print(f"{v['aid']}\t{v['created_at'][:10]}\t{'现存' if v['is_available'] else '已删'}\t{v['title']}")
