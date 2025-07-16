#!/usr/bin/python3

from dataclasses import dataclass
from dataclasses import field


@dataclass
class LoginConfig:
    """登录配置类"""
    cookie_file: str = "./data/cookie.json"
    log_file: str = "./data/login.log"
    max_retry: int = 5


@dataclass
class UserInfo:
    """用户信息类"""
    ban: bool = False
    coins: int = 0
    face: str = ""
    level: int = 0
    nickname: str = ""
    live_room: dict = field(default_factory=dict)
