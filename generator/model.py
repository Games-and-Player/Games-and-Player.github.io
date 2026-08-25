"""事实（db.json）+ 规则（data/*.json）→ 视图模型。所有函数无副作用。"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from scripts.enrich import status_key


@dataclass(frozen=True)
class SeriesRule:
    slug: str
    name: str
    pattern: re.Pattern
    fields: tuple[str, ...]
    date_from: str | None
    date_to: str | None
    color: str
    blurb: str


def load_series_rules(path: Path) -> list[SeriesRule]:
    raw = json.loads(path.read_text(encoding="utf-8"))["series"]
    return [SeriesRule(r["slug"], r["name"], re.compile(r["pattern"]), tuple(r["fields"]),
                       r.get("from"), r.get("to"), r["color"], r.get("blurb", "")) for r in raw]


def load_overrides(path: Path) -> dict[int, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))["videos"]
    return {int(aid): data for aid, data in raw.items()}


def load_tag_aliases(path: Path) -> tuple[dict[str, str], set[str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k.lower(): v for k, v in raw["canonical"].items()}, set(raw["hidden"])


def classify(video: dict, rules: list[SeriesRule], overrides: dict[int, dict]) -> SeriesRule | None:
    forced = overrides.get(video["aid"], {}).get("series")
    if forced:
        return next((r for r in rules if r.name == forced), None)
    day = video["created_at"][:10]
    for r in rules:
        if r.date_from and day < r.date_from:
            continue
        if r.date_to and day > r.date_to:
            continue
        if r.pattern.search(" ".join(video.get(f, "") for f in r.fields)):
            return r
    return None


def status_of(video: dict) -> str:
    return status_key(video)


def video_tags(video: dict, canonical: dict[str, str], hidden: set[str]) -> list[str]:
    out: list[str] = []
    for tag in video.get("tags", []):
        t = tag.strip()
        if not t or t in hidden:
            continue
        t = canonical.get(t.lower(), t)
        if t not in out:
            out.append(t)
    return out
