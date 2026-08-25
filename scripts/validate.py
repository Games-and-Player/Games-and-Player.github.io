"""校验 db.json：字段、类型、唯一性、状态一致性。
用法：python scripts/validate.py [db.json]；有错误时退出码 1。
schema_version >= 2 时启用严格检查。"""
import json
import re
import sys
from pathlib import Path

REQUIRED = {
    "aid": int, "title": str, "cover": str, "desc": str, "tags": list, "cid": int,
    "created_at": str, "created_timestamp": int, "status_code": int,
    "status_description": str, "is_available": bool, "status_check_time": str,
}
OPTIONAL = {
    "bvid": str, "cover_local": str, "duration": int, "deleted_found_at": str,
    "restored_at": str, "reupload_aid": int, "reupload_dead_at": str, "stat": dict,
}
CREATED_AT = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


def validate(db: dict) -> list[str]:
    errors: list[str] = []
    videos = db.get("videos")
    if not isinstance(videos, list):
        return ["videos 不是列表"]
    strict = db.get("schema_version", 1) >= 2
    seen: set[int] = set()
    prev_ts = None
    for v in videos:
        aid = v.get("aid")
        for key, typ in REQUIRED.items():
            if key not in v:
                errors.append(f"{aid}: 缺少字段 {key}")
            elif not isinstance(v[key], typ):
                errors.append(f"{aid}: 字段 {key} 类型应为 {typ.__name__}")
        for key, typ in OPTIONAL.items():
            if key in v and v[key] is not None and not isinstance(v[key], typ):
                errors.append(f"{aid}: 字段 {key} 类型应为 {typ.__name__}")
        extra = set(v) - set(REQUIRED) - set(OPTIONAL)
        if extra:
            errors.append(f"{aid}: 未知字段 {sorted(extra)}")
        if aid in seen:
            errors.append(f"{aid}: aid 重复")
        seen.add(aid)
        if v.get("is_available") is True and v.get("status_code") != 0:
            errors.append(f"{aid}: is_available 为 true 但 status_code={v.get('status_code')}")
        if v.get("is_available") is False and v.get("status_code") == 0:
            errors.append(f"{aid}: is_available 为 false 但 status_code=0")
        if not CREATED_AT.fullmatch(v.get("created_at", "")):
            errors.append(f"{aid}: created_at 格式错误")
        if strict:
            if not v.get("bvid"):
                errors.append(f"{aid}: v2 需要 bvid")
            if str(v.get("cover", "")).startswith("http://"):
                errors.append(f"{aid}: cover 应为 https")
            if v.get("is_available") is False and not v.get("deleted_found_at"):
                errors.append(f"{aid}: 不可用视频需要 deleted_found_at")
            if v.get("reupload_dead_at") and not v.get("reupload_aid"):
                errors.append(f"{aid}: reupload_dead_at 需要 reupload_aid")
            ts = v.get("created_timestamp", 0)
            if prev_ts is not None and ts > prev_ts:
                errors.append(f"{aid}: 未按 created_timestamp 倒序")
            prev_ts = ts
    return errors


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("db.json")
    db = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(db)
    for e in errors[:50]:
        print(e)
    if errors:
        print(f"共 {len(errors)} 个问题")
        return 1
    print(f"OK: {len(db['videos'])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
