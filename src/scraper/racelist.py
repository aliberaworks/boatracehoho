# -*- coding: utf-8 -*-
"""出走表スクレイパー - 選手・モーター・ボート情報を取得

boatrace.jp HTML構造:
  div.table1 > table > tbody[0] = 締切予定時刻
  div.table1 > table > tbody[1..6] = 各艇の選手情報
  各tbody row[0] has 24 tds:
    td[0] = 艇番 (class is-boatColorN)
    td[2] = 登番/級別/選手名 (concatenated)
    td[3] = F/L/ST (e.g. "F0L00.17")
    td[4] = 全国勝率/2連率/3連率 (concatenated e.g. "3.6110.5317.54")
    td[5] = 当地勝率/2連率/3連率 (concatenated)
    td[6] = モーター番号/2連率/3連率 (concatenated e.g. "1740.9460.63")
    td[7] = ボート番号/2連率/3連率 (concatenated)
"""

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.constants import URLS
from src.utils.helpers import fetch_page, safe_float


def scrape_racelist(jcd: str, hd: str, rno: int) -> dict:
    """出走表ページから選手・モーター・ボート情報を取得"""
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

    # 出走表: tbody[0]=スケジュール, tbody[1..6]=各艇
    tbodies = soup.select("div.table1 table tbody")

    for i, tb in enumerate(tbodies[1:7], start=1):
        racer = _parse_racer_tbody(tb, boat_number=i)
        if racer:
            result["racers"].append(racer)

    # フォールバック
    if not result["racers"]:
        racer_links = soup.select("a[href*='racersearch/profile']")
        for i, link in enumerate(racer_links[:6]):
            toban_match = re.search(r'toban=(\d+)', link.get("href", ""))
            if toban_match:
                result["racers"].append({
                    "boat_number": i + 1,
                    "registration_number": toban_match.group(1),
                    "name": link.get_text(strip=True),
                    "class": "", "branch": "", "weight": 0.0,
                    "win_rate": 0.0, "local_win_rate": 0.0,
                    "motor_2renritsu": 0.0, "boat_2renritsu": 0.0,
                })

    return result


def _split_stats(text: str) -> list[float]:
    """連結された統計値を分割: "3.6110.5317.54" → [3.61, 10.53, 17.54]"""
    # X.XX パターンを順次抽出
    vals = []
    for m in re.finditer(r'(\d+\.\d{2})', text):
        vals.append(safe_float(m.group(1)))
    return vals


def _parse_racer_tbody(tbody, boat_number: int) -> dict | None:
    """1艇分のtbody（4行）をパース"""
    racer = {
        "boat_number": boat_number,
        "registration_number": "",
        "name": "",
        "class": "",
        "branch": "",
        "weight": 0.0,
        "win_rate": 0.0,
        "local_win_rate": 0.0,
        "motor_number": "",
        "motor_2renritsu": 0.0,
        "boat_number_id": "",
        "boat_2renritsu": 0.0,
    }

    rows = tbody.select("tr")
    if not rows:
        return None

    # メインrow (row[0]) の td を取得
    tds = rows[0].select("td")
    if len(tds) < 6:
        return None

    # --- 登番・級別・選手名 (td[2]) ---
    info_text = tds[2].get_text(strip=True) if len(tds) > 2 else ""
    # パターン: "3207/B1田村　　美和東京/沖縄60歳/52.0kg"  or just "3207\n/B1田村"
    info_full = tds[2].get_text(separator="|", strip=True) if len(tds) > 2 else ""

    # 登番（4桁）
    toban_match = re.search(r'(\d{4})', info_text)
    if toban_match:
        racer["registration_number"] = toban_match.group(1)

    # 級別
    class_match = re.search(r'([AB][12])', info_text)
    if class_match:
        racer["class"] = class_match.group(1)

    # 選手名: リンクから取得
    name_link = tbody.select_one("a[href*='racersearch/profile']")
    if name_link:
        # リンクテキストが空の場合、親要素のテキストから抽出
        name = name_link.get_text(strip=True)
        if not name:
            # 級別の後〜都道府県名の前が名前
            raw = tds[2].get_text(separator=" ", strip=True)
            # パターン: "3207 /B1 田村　　美和 東京/沖縄 ..."
            name_m = re.search(r'[AB][12]\s*([\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\s　]+)', raw)
            if name_m:
                name = name_m.group(1).strip().replace("　", " ").strip()
        racer["name"] = name
        # toban from href
        href_toban = re.search(r'toban=(\d+)', name_link.get("href", ""))
        if href_toban:
            racer["registration_number"] = href_toban.group(1)

    # 体重
    weight_match = re.search(r'(\d{2}\.\d)\s*kg', info_text)
    if weight_match:
        racer["weight"] = safe_float(weight_match.group(1))

    # --- 全国成績 (td[4]): "勝率+2連率+3連率" ---
    if len(tds) > 4:
        national = _split_stats(tds[4].get_text(strip=True))
        if national:
            racer["win_rate"] = national[0]  # 全国勝率

    # --- 当地成績 (td[5]): "勝率+2連率+3連率" ---
    if len(tds) > 5:
        local = _split_stats(tds[5].get_text(strip=True))
        if local:
            racer["local_win_rate"] = local[0]  # 当地勝率

    # --- モーター (td[6]): "番号+2連率+3連率" ---
    if len(tds) > 6:
        motor_text = tds[6].get_text(strip=True)
        motor_stats = _split_stats(motor_text)
        motor_num_match = re.match(r'(\d{2,3})', motor_text)
        if motor_num_match:
            racer["motor_number"] = motor_num_match.group(1)
        if len(motor_stats) >= 1:
            racer["motor_2renritsu"] = motor_stats[0]

    # --- ボート (td[7]): "番号+2連率+3連率" ---
    if len(tds) > 7:
        boat_text = tds[7].get_text(strip=True)
        boat_stats = _split_stats(boat_text)
        boat_num_match = re.match(r'(\d{2,3})', boat_text)
        if boat_num_match:
            racer["boat_number_id"] = boat_num_match.group(1)
        if len(boat_stats) >= 1:
            racer["boat_2renritsu"] = boat_stats[0]

    return racer


if __name__ == "__main__":
    import json

    data = scrape_racelist("04", "20260217", 1)
    for r in data["racers"]:
        print(f"  {r['boat_number']}# {r['name']} {r['class']} "
              f"wr={r['win_rate']} local={r['local_win_rate']} "
              f"motor={r['motor_number']}({r['motor_2renritsu']}%)")
