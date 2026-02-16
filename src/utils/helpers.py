# -*- coding: utf-8 -*-
"""ユーティリティ関数"""

import time
import requests
from bs4 import BeautifulSoup

# リクエスト間隔 (秒) - サーバー負荷軽減
REQUEST_INTERVAL = 0.5

_last_request_time = 0


def fetch_page(url: str) -> BeautifulSoup:
    """指定URLのページを取得してBeautifulSoupオブジェクトを返す"""
    global _last_request_time
    
    # レート制限
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    }
    
    response = requests.get(url, headers=headers, timeout=15)
    response.encoding = "utf-8"
    _last_request_time = time.time()
    
    return BeautifulSoup(response.text, "lxml")


def safe_float(text: str, default: float = 0.0) -> float:
    """文字列を安全にfloatに変換"""
    try:
        return float(text.strip().replace("　", ""))
    except (ValueError, AttributeError):
        return default


def safe_int(text: str, default: int = 0) -> int:
    """文字列を安全にintに変換"""
    try:
        return int(text.strip().replace("　", ""))
    except (ValueError, AttributeError):
        return default


def format_date(year: int, month: int, day: int) -> str:
    """日付をYYYYMMDD形式に変換"""
    return f"{year:04d}{month:02d}{day:02d}"
