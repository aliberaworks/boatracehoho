# -*- coding: utf-8 -*-
"""出走表スクレイパー - 選手・モーター・ボート情報を取得"""

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.constants import URLS
from src.utils.helpers import fetch_page, safe_float, safe_int


def scrape_racelist(jcd: str, hd: str, rno: int) -> dict:
    """
    出走表ページから選手・モーター・ボート情報を取得
    
    Args:
        jcd: 会場コード
        hd:  日付 YYYYMMDD
        rno: レース番号
    
    Returns:
        dict: レース出走情報
    """
    url = URLS["racelist"].format(rno=rno, jcd=jcd, hd=hd)
    soup = fetch_page(url)
    
    result = {
        "venue_code": jcd,
        "date": hd,
        "race_number": rno,
        "race_name": "",
        "racers": [],
    }
    
    # レース名
    race_name_elem = soup.select("h2.heading2_titleName")
    if race_name_elem:
        result["race_name"] = race_name_elem[0].get_text(strip=True)
    
    # 出走表テーブルから選手情報を取得
    table = soup.select("div.table1 table tbody")
    if table:
        rows = table[0].select("tr")
        for i, row in enumerate(rows):
            racer = _parse_racer_row(row, i + 1)
            if racer:
                result["racers"].append(racer)
    
    # テーブルが見つからない場合のフォールバック
    if not result["racers"]:
        # 選手リンクから基本情報を取得
        racer_links = soup.select("a[href*='racersearch/profile']")
        for i, link in enumerate(racer_links[:6]):
            toban_match = re.search(r'toban=(\d+)', link.get("href", ""))
            if toban_match:
                result["racers"].append({
                    "boat_number": i + 1,
                    "registration_number": toban_match.group(1),
                    "name": link.get_text(strip=True),
                    "class": "",
                    "branch": "",
                    "weight": 0.0,
                    "motor_number": "",
                    "motor_2renritsu": 0.0,
                    "boat_number_id": "",
                    "boat_2renritsu": 0.0,
                    "win_rate": 0.0,
                    "local_win_rate": 0.0,
                })
    
    return result


def _parse_racer_row(row, boat_number: int) -> dict | None:
    """出走表の1行をパースして選手情報dictを返す"""
    cells = row.select("td")
    if len(cells) < 3:
        return None
    
    racer = {
        "boat_number": boat_number,
        "registration_number": "",
        "name": "",
        "class": "",
        "branch": "",
        "weight": 0.0,
        "motor_number": "",
        "motor_2renritsu": 0.0,
        "boat_number_id": "",
        "boat_2renritsu": 0.0,
        "win_rate": 0.0,
        "local_win_rate": 0.0,
    }
    
    # 選手名リンク
    name_link = row.select_one("a[href*='racersearch/profile']")
    if name_link:
        racer["name"] = name_link.get_text(strip=True)
        toban_match = re.search(r'toban=(\d+)', name_link.get("href", ""))
        if toban_match:
            racer["registration_number"] = toban_match.group(1)
    
    # 級別
    class_elem = row.select_one("span[class*='is-']")
    if class_elem:
        text = class_elem.get_text(strip=True)
        if text in ("A1", "A2", "B1", "B2"):
            racer["class"] = text
    
    # テキストからデータ抽出
    all_text = row.get_text()
    
    # 支部
    branch_match = re.search(r'(東京|大阪|愛知|福岡|群馬|埼玉|静岡|三重|福井|滋賀|兵庫|徳島|香川|岡山|広島|山口|佐賀|長崎)', all_text)
    if branch_match:
        racer["branch"] = branch_match.group(1)
    
    # 体重
    weight_match = re.search(r'(\d{2}\.\d)\s*kg', all_text)
    if weight_match:
        racer["weight"] = safe_float(weight_match.group(1))
    
    # 勝率
    rate_matches = re.findall(r'(\d\.\d{2})', all_text)
    if len(rate_matches) >= 2:
        racer["win_rate"] = safe_float(rate_matches[0])
        racer["local_win_rate"] = safe_float(rate_matches[1])
    
    return racer


if __name__ == "__main__":
    import json
    data = scrape_racelist("06", "20260215", 1)
    print(json.dumps(data, ensure_ascii=False, indent=2))
