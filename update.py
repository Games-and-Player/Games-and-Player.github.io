#!/usr/bin/python3

import json
import time
from datetime import datetime

import pytz
from utils.bilibili_api import BilibiliAPI

if __name__ == '__main__':
    bili = BilibiliAPI()
    # bili.login_with_qrcode()
    bili.login_with_cookie()
    pn = 1

    with open("./db.json", "r") as f:
        original_db = json.load(f)
    aid_list = [str(x.get("aid")) for x in original_db.get("videos")]

    video_list = []

    while pn <= 1:
        res = bili.get_vids("67390259", str(pn))
        if res == {} or res.get("list").get("vlist") == []:
            break

        for x in res.get("list").get("vlist"):
            aid = x.get("aid")

            if str(aid) in aid_list:
                continue

            tag_req = bili.get_tags(str(aid))
            tags = [x.get("tag_name") for x in tag_req.get("data")]

            cid_req = bili.get_cid(str(aid))
            cid = cid_req.get("data")[0].get("cid")

            video_info = {
                "aid": x.get("aid"),
                "title": x.get("title"),
                "cover": x.get("pic"),
                "desc": x.get("description"),
                "tags": tags,
                "cid": cid,
                "created_at": datetime.fromtimestamp(x.get("created"),
                                                     pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%d %H:%M"),
                "created_timestamp": x.get("created")
            }
            video_list.append(video_info)
        pn += 1

    original_db.get("videos").extend(video_list)
    original_db["videos"] = sorted(original_db.get("videos"), key=lambda x: x.get("created_timestamp"), reverse=True)
    with open("./db.json", "w") as f:
        json.dump(original_db, f, ensure_ascii=False, indent=4)
