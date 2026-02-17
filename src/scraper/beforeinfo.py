# -*- coding: utf-8 -*-
"""直前情報スクレイパー - 展示タイム・風速・波高を取得"""

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.constants import URLS
from src.utils.helpers import fetch_page, safe_float


def scrape_beforeinfo(jcd: str, hd: str, rno: int) -> dict:
    """
    直前情報ページから展示タイム・水面気象情報を取得
    
    Args:
        jcd: 会場コード (例: "06")
        hd:  日付 YYYYMMDD (例: "20260215")
        rno: レース番号 (1-12)
    
    Returns:
        dict: {
            "exhibition_times": [float, ...],  # 6艇の展示タイム
            "wind_direction": str,             # 風向
            "wind_speed": float,               # 風速 [m/s]
            "wave_height": float,              # 波高 [cm]
            "temperature": float,              # 気温 [℃]  
            "water_temperature": float,        # 水温 [℃]
            "racers": [...],                   # 選手情報
        }
    """
    url = URLS["beforeinfo"].format(rno=rno, jcd=jcd, hd=hd)
    soup = fetch_page(url)
    
    result = {
        "venue_code": jcd,
        "date": hd,
        "race_number": rno,
        "exhibition_times": [],
        "wind_direction": "",
        "wind_speed": 0.0,
        "wave_height": 0.0,
        "temperature": 0.0,
        "water_temperature": 0.0,
        "racers": [],
    }
    
    # --- 展示タイム取得 ---
    # 全 <td> から展示タイムのパターン (X.XX, 6.00~8.00) を直接探す
    # 旧CSSセレクタ (td.is-fs14等) はboatrace.jpのHTML構造にマッチしないため廃止
    for td in soup.select("td"):
        text = td.get_text(strip=True)
        if re.match(r'^\d\.\d{2}$', text):
            val = safe_float(text)
            if 6.0 <= val <= 8.0:
                result["exhibition_times"].append(val)
                if len(result["exhibition_times"]) >= 6:
                    break
    
    # --- 水面気象情報 ---
    weather_section = soup.select("div.weather1")
    if not weather_section:
        weather_section = soup.select("div.is-weather")
    
    if weather_section:
        ws = weather_section[0]
        
        # 風向 - アイコンのクラス名やテキストから判定
        wind_dir_elem = ws.select("p.is-wind")
        if wind_dir_elem:
            # class名に方向情報が含まれる場合 (例: is-wind1 ~ is-wind16)
            classes = wind_dir_elem[0].get("class", [])
            for cls in classes:
                match = re.search(r'is-wind(\d+)', cls)
                if match:
                    wind_dirs = {
                        "1": "北", "2": "北北東", "3": "北東", "4": "東北東",
                        "5": "東", "6": "東南東", "7": "南東", "8": "南南東",
                        "9": "南", "10": "南南西", "11": "南西", "12": "西南西",
                        "13": "西", "14": "西北西", "15": "北西", "16": "北北西",
                    }
                    result["wind_direction"] = wind_dirs.get(match.group(1), "")
        
        # 風速
        wind_speed_elem = ws.select("span.weather1_bodyUnitLabelData")
        if not wind_speed_elem:
            wind_speed_elem = ws.select("span.is-windSpeed")
        if wind_speed_elem:
            result["wind_speed"] = safe_float(wind_speed_elem[0].get_text(strip=True))
        
        # 波高
        wave_elem = ws.select("span.weather1_bodyUnitLabelData")
        for elem in ws.select("span"):
            text = elem.get_text(strip=True)
            if "cm" in text or re.match(r'^\d+$', text):
                parent = elem.parent
                if parent and "波高" in parent.get_text():
                    result["wave_height"] = safe_float(text.replace("cm", ""))
        
        # 気温・水温
        for elem in ws.select("span"):
            parent_text = ""
            if elem.parent:
                parent_text = elem.parent.get_text()
            text = elem.get_text(strip=True)
            
            if "気温" in parent_text and re.match(r'^\d+\.?\d*$', text):
                result["temperature"] = safe_float(text)
            elif "水温" in parent_text and re.match(r'^\d+\.?\d*$', text):
                result["water_temperature"] = safe_float(text)
    
    # --- 別パターンの気象情報取得 ---
    if result["wind_speed"] == 0.0:
        # テキストベースの検索
        body_text = soup.get_text()
        
        wind_match = re.search(r'風速\s*(\d+)\s*m', body_text)
        if wind_match:
            result["wind_speed"] = safe_float(wind_match.group(1))
        
        wave_match = re.search(r'波高\s*(\d+)\s*cm', body_text)
        if wave_match:
            result["wave_height"] = safe_float(wave_match.group(1))
        
        temp_match = re.search(r'気温\s*(\d+\.?\d*)\s*℃', body_text)
        if temp_match:
            result["temperature"] = safe_float(temp_match.group(1))
        
        wtemp_match = re.search(r'水温\s*(\d+\.?\d*)\s*℃', body_text)
        if wtemp_match:
            result["water_temperature"] = safe_float(wtemp_match.group(1))
    
    # 選手情報の基本取得
    racer_links = soup.select("a[href*='racersearch/profile']")
    for link in racer_links:
        toban_match = re.search(r'toban=(\d+)', link.get("href", ""))
        if toban_match:
            result["racers"].append({
                "registration_number": toban_match.group(1),
                "name": link.get_text(strip=True),
            })
    
    return result


if __name__ == "__main__":
    import json
    
    # テスト: 浜名湖 2026/2/15 1R
    data = scrape_beforeinfo("06", "20260215", 1)
    print(json.dumps(data, ensure_ascii=False, indent=2))
