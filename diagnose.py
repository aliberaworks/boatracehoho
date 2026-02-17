# -*- coding: utf-8 -*-
"""診断スクリプト: スクレイピングの各段階を詳細にトレース"""
import sys, os, io, json, re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))

from src.utils.helpers import fetch_page
from src.utils.constants import URLS, VENUES

TARGET_DATE = "20260217"

def diagnose_venue(jcd, hd, rno=1):
    venue = VENUES.get(jcd, jcd)
    print(f"\n{'='*60}")
    print(f"[DIAG] {venue} (jcd={jcd}) {hd} {rno}R")
    print(f"{'='*60}")

    # 1. beforeinfo ページを直接取得
    url_bi = URLS["beforeinfo"].format(rno=rno, jcd=jcd, hd=hd)
    print(f"\n[1] beforeinfo URL: {url_bi}")
    try:
        soup_bi = fetch_page(url_bi)
        page_text = soup_bi.get_text()[:500]
        print(f"    Page text preview: {page_text[:200]}")
        print(f"    Page title: {soup_bi.title.string if soup_bi.title else 'N/A'}")

        # CSS selectors の確認
        t1 = soup_bi.select("div.table1 table tbody")
        print(f"    div.table1 table tbody: {len(t1)} matches")
        
        t2 = soup_bi.select("div.grid.is-type2__multilabel table tbody tr")
        print(f"    div.grid.is-type2__multilabel: {len(t2)} matches")

        # 全 td からパターンマッチ
        all_tds = soup_bi.select("td")
        print(f"    Total <td> elements: {len(all_tds)}")
        
        # 展示タイムっぽい値を探す
        found_times = []
        for td in all_tds:
            text = td.get_text(strip=True)
            if re.match(r'^\d\.\d{2}$', text):
                val = float(text)
                if 6.0 <= val <= 8.0:
                    found_times.append(val)
        print(f"    Exhibition time candidates (6.00-8.00): {found_times}")

        # is-fs14 セレクタ
        fs14 = soup_bi.select("td.is-fs14")
        print(f"    td.is-fs14: {len(fs14)} matches")
        if fs14:
            for c in fs14[:12]:
                print(f"      -> {c.get_text(strip=True)}")

        # 気象情報
        w1 = soup_bi.select("div.weather1")
        w2 = soup_bi.select("div.is-weather")
        print(f"    div.weather1: {len(w1)}, div.is-weather: {len(w2)}")

        # テキスト内の風速/波高
        wind_m = re.search(r'風速\s*(\d+)\s*m', page_text)
        wave_m = re.search(r'波高\s*(\d+)\s*cm', page_text)
        print(f"    Wind regex: {wind_m.group(0) if wind_m else 'not found'}")
        print(f"    Wave regex: {wave_m.group(0) if wave_m else 'not found'}")

    except Exception as e:
        print(f"    ERROR: {e}")
        return

    # 2. racelist ページ
    url_rl = URLS["racelist"].format(rno=rno, jcd=jcd, hd=hd)
    print(f"\n[2] racelist URL: {url_rl}")
    try:
        soup_rl = fetch_page(url_rl)
        racer_links = soup_rl.select("a[href*='racersearch/profile']")
        print(f"    Racer links found: {len(racer_links)}")
        for link in racer_links[:3]:
            print(f"      -> {link.get_text(strip=True)}")

        table = soup_rl.select("div.table1 table tbody")
        print(f"    div.table1 table tbody: {len(table)} matches")
        if table:
            rows = table[0].select("tr")
            print(f"    Rows in first table: {len(rows)}")
    except Exception as e:
        print(f"    ERROR: {e}")

    # 3. 実際のスクレイパーモジュール呼び出し
    print(f"\n[3] scrape_beforeinfo() output:")
    try:
        from src.scraper.beforeinfo import scrape_beforeinfo
        bi = scrape_beforeinfo(jcd, hd, rno)
        print(f"    exhibition_times: {bi.get('exhibition_times', [])}")
        print(f"    wind: {bi.get('wind_speed')}m {bi.get('wind_direction')}")
        print(f"    wave: {bi.get('wave_height')}cm")
        print(f"    racers: {len(bi.get('racers', []))}")
    except Exception as e:
        print(f"    ERROR: {e}")

    # 4. シミュレーション
    print(f"\n[4] Full pipeline test:")
    try:
        from main import run_pipeline_slim
        result = run_pipeline_slim(jcd, hd, rno)
        if result:
            print(f"    SUCCESS: pred_order={result['pred']['predicted_order']}")
            print(f"    Tickets: {len(result['pred'].get('tickets', []))}")
        else:
            print(f"    RESULT IS NONE")
    except Exception as e:
        import traceback
        print(f"    ERROR: {e}")
        traceback.print_exc()


# 5つの主要会場を診断
venues_to_test = ["04", "06", "10", "21", "24"]
for jcd in venues_to_test:
    diagnose_venue(jcd, TARGET_DATE, 1)

print("\n\n=== DIAGNOSIS COMPLETE ===")
