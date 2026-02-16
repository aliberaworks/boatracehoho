# -*- coding: utf-8 -*-
"""オッズスクレイパー - 3連単オッズを取得"""

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.constants import URLS
from src.utils.helpers import fetch_page, safe_float


def scrape_odds(jcd: str, hd: str, rno: int) -> dict:
    """
    3連単オッズページからオッズを取得
    
    Args:
        jcd: 会場コード
        hd:  日付 YYYYMMDD
        rno: レース番号
    
    Returns:
        dict: {
            "odds_3rentan": {
                "1-2-3": 10.5,
                "1-2-4": 25.3,
                ...
            }
        }
    """
    url = URLS["odds3t"].format(rno=rno, jcd=jcd, hd=hd)
    soup = fetch_page(url)
    
    result = {
        "venue_code": jcd,
        "date": hd,
        "race_number": rno,
        "odds_3rentan": {},
    }
    
    # 3連単オッズテーブル解析
    odds_tables = soup.select("table.is-p10-0, div.table1 table")
    
    for table in odds_tables:
        rows = table.select("tr")
        for row in rows:
            cells = row.select("td")
            # オッズテーブルは組合せとオッズが交互に並ぶパターン
            for i in range(0, len(cells) - 1, 2):
                combo_text = cells[i].get_text(strip=True)
                odds_text = cells[i + 1].get_text(strip=True) if i + 1 < len(cells) else ""
                
                # 組合せ: "1-2-3" or "1=2=3" 等のパターン
                combo_match = re.search(r'(\d)\s*[-=＝]\s*(\d)\s*[-=＝]\s*(\d)', combo_text)
                if combo_match:
                    combo_key = f"{combo_match.group(1)}-{combo_match.group(2)}-{combo_match.group(3)}"
                    odds_val = safe_float(odds_text.replace(",", ""))
                    if odds_val > 0:
                        result["odds_3rentan"][combo_key] = odds_val
    
    # フォールバック: oddstf テーブルパターン
    if not result["odds_3rentan"]:
        # ページ全体からオッズパターンを探す
        all_tds = soup.select("td")
        i = 0
        while i < len(all_tds):
            text = all_tds[i].get_text(strip=True)
            combo_match = re.match(r'^(\d)-(\d)-(\d)$', text)
            if combo_match and i + 1 < len(all_tds):
                odds_text = all_tds[i + 1].get_text(strip=True)
                odds_val = safe_float(odds_text.replace(",", ""))
                if odds_val > 0:
                    combo_key = f"{combo_match.group(1)}-{combo_match.group(2)}-{combo_match.group(3)}"
                    result["odds_3rentan"][combo_key] = odds_val
                i += 2
            else:
                i += 1
    
    return result


if __name__ == "__main__":
    import json
    data = scrape_odds("06", "20260215", 1)
    print(json.dumps(data, ensure_ascii=False, indent=2))
