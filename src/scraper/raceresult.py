# -*- coding: utf-8 -*-
"""レース結果スクレイパー - 着順・決まり手・払戻金を取得"""

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.constants import URLS
from src.utils.helpers import fetch_page, safe_float, safe_int


def scrape_raceresult(jcd: str, hd: str, rno: int) -> dict:
    """
    レース結果ページから着順・決まり手・払戻金を取得
    
    Args:
        jcd: 会場コード
        hd:  日付 YYYYMMDD
        rno: レース番号
    
    Returns:
        dict: {
            "result_order": [int, ...],    # 着順（艇番の順序）
            "kimarite": str,               # 決まり手
            "race_time": str,              # レースタイム
            "payouts": {                   # 払戻金
                "3rentan": [(combo, payout), ...],
            }
        }
    """
    url = URLS["raceresult"].format(rno=rno, jcd=jcd, hd=hd)
    soup = fetch_page(url)
    
    result = {
        "venue_code": jcd,
        "date": hd,
        "race_number": rno,
        "result_order": [],
        "kimarite": "",
        "race_time": "",
        "winning_boat": 0,
        "payouts": {
            "3rentan": [],
            "3renpuku": [],
            "2rentan": [],
            "2renpuku": [],
        },
    }
    
    # --- 着順取得 ---
    result_table = soup.select("div.table1 table tbody")
    if result_table:
        rows = result_table[0].select("tr")
        for row in rows:
            cells = row.select("td")
            if len(cells) >= 2:
                # 着順と艇番を取得
                order_text = cells[0].get_text(strip=True)
                boat_text = cells[1].get_text(strip=True)
                
                order = safe_int(order_text)
                boat = safe_int(boat_text)
                
                if 1 <= order <= 6 and 1 <= boat <= 6:
                    result["result_order"].append({
                        "rank": order,
                        "boat_number": boat,
                    })
    
    # 1着の艇番
    if result["result_order"]:
        first = [r for r in result["result_order"] if r["rank"] == 1]
        if first:
            result["winning_boat"] = first[0]["boat_number"]
    
    # --- 決まり手 ---
    page_text = soup.get_text()
    kimarite_patterns = ["逃げ", "差し", "まくり差し", "まくり", "抜き", "恵まれ"]
    for k in kimarite_patterns:
        if k in page_text:
            # "まくり差し" を先に判定（"まくり" が含まれるため）
            if k == "まくり" and "まくり差し" in page_text:
                continue
            result["kimarite"] = k
            break
    
    # 決まり手の別パターン
    if not result["kimarite"]:
        kimarite_elem = soup.select_one("span.is-kimarite, td.is-kimarite")
        if kimarite_elem:
            result["kimarite"] = kimarite_elem.get_text(strip=True)
    
    # --- レースタイム ---
    time_match = re.search(r'(\d)[\'′](\d{2})[\"″](\d)', page_text)
    if time_match:
        result["race_time"] = f"{time_match.group(1)}'{time_match.group(2)}\"{time_match.group(3)}"
    
    # --- 払戻金 ---
    payout_sections = soup.select("div.table1")
    for section in payout_sections:
        text = section.get_text()
        
        # 3連単
        if "３連単" in text or "3連単" in text:
            rows = section.select("tr")
            for row in rows:
                cells = row.select("td")
                if len(cells) >= 2:
                    combo = cells[0].get_text(strip=True)
                    payout_text = cells[1].get_text(strip=True)
                    payout_val = safe_int(payout_text.replace(",", "").replace("円", "").replace("¥", ""))
                    if combo and payout_val > 0:
                        result["payouts"]["3rentan"].append({
                            "combination": combo,
                            "payout": payout_val,
                        })
        
        # 3連複
        if "３連複" in text or "3連複" in text:
            rows = section.select("tr")
            for row in rows:
                cells = row.select("td")
                if len(cells) >= 2:
                    combo = cells[0].get_text(strip=True)
                    payout_text = cells[1].get_text(strip=True)
                    payout_val = safe_int(payout_text.replace(",", "").replace("円", "").replace("¥", ""))
                    if combo and payout_val > 0:
                        result["payouts"]["3renpuku"].append({
                            "combination": combo,
                            "payout": payout_val,
                        })
    
    return result


if __name__ == "__main__":
    import json
    data = scrape_raceresult("06", "20260215", 1)
    print(json.dumps(data, ensure_ascii=False, indent=2))
