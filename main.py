# -*- coding: utf-8 -*-
"""メインパイプライン - スクレイピング→シミュレーション→予想→JSON出力"""

import json
import os
import sys
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from src.scraper.beforeinfo import scrape_beforeinfo
from src.scraper.racelist import scrape_racelist
from src.scraper.raceresult import scrape_raceresult
from src.scraper.odds import scrape_odds
from src.physics.simulator import run_simulation
from src.prediction.predictor import generate_prediction
from src.upset.analyzer import UpsetScreener, KimariteAnalyzer, StrategyDecider
from src.utils.constants import VENUES


def run_pipeline(jcd: str, hd: str, rno: int, include_result: bool = False) -> dict:
    """
    1レース分のフルパイプライン実行
    """
    print(f"[{VENUES.get(jcd, jcd)}] {hd} {rno}R - 処理開始...")
    
    # 1. 出走表取得
    racelist = scrape_racelist(jcd, hd, rno)
    
    # 2. 直前情報取得
    beforeinfo = scrape_beforeinfo(jcd, hd, rno)
    
    # 3. オッズ取得
    odds = scrape_odds(jcd, hd, rno)
    
    # 4. 物理シミュレーション
    exhibition_times = beforeinfo.get("exhibition_times", [])
    if len(exhibition_times) < 6:
        exhibition_times = [6.80] * 6  # デフォルト値
    
    sim_result = run_simulation(
        exhibition_times,
        wind_speed=beforeinfo.get("wind_speed", 0),
        wind_direction=beforeinfo.get("wind_direction", ""),
        wave_height=beforeinfo.get("wave_height", 0),
        water_temp=beforeinfo.get("water_temperature", 20),
    )
    
    # 5. 予想生成
    prediction = generate_prediction(sim_result, odds)
    
    # 6. 荒れレース分析
    screener = UpsetScreener()
    ka = KimariteAnalyzer()
    sd = StrategyDecider()
    
    kimarite_analysis = ka.analyze_from_simulation(sim_result)
    strategy = sd.decide(sim_result, racelist)
    
    # 7. 結果取得（過去レースの場合）
    result_data = None
    if include_result:
        try:
            result_data = scrape_raceresult(jcd, hd, rno)
        except Exception:
            result_data = None
    
    # 出力組み立て
    output = {
        "meta": {
            "venue_code": jcd,
            "venue_name": VENUES.get(jcd, ""),
            "date": hd,
            "race_number": rno,
            "generated_at": datetime.datetime.now().isoformat(),
        },
        "racelist": racelist,
        "beforeinfo": {
            "exhibition_times": exhibition_times,
            "wind_speed": beforeinfo.get("wind_speed", 0),
            "wind_direction": beforeinfo.get("wind_direction", ""),
            "wave_height": beforeinfo.get("wave_height", 0),
            "temperature": beforeinfo.get("temperature", 0),
            "water_temperature": beforeinfo.get("water_temperature", 0),
        },
        "simulation": sim_result,
        "prediction": prediction,
        "kimarite_analysis": kimarite_analysis,
        "strategy": strategy,
        "result": result_data,
    }
    
    return output


def run_daily(hd: str | None = None, venue_codes: list[str] | None = None):
    """
    1日分の全レースを処理してJSONファイルに出力
    """
    if hd is None:
        hd = datetime.datetime.now().strftime("%Y%m%d")
    
    if venue_codes is None:
        venue_codes = list(VENUES.keys())
    
    os.makedirs("public/data", exist_ok=True)
    
    daily_data = {
        "date": hd,
        "generated_at": datetime.datetime.now().isoformat(),
        "venues": {},
    }
    
    for jcd in venue_codes:
        venue_data = {"races": {}}
        for rno in range(1, 13):
            try:
                race_data = run_pipeline(jcd, hd, rno)
                venue_data["races"][str(rno)] = race_data
            except Exception as e:
                print(f"  ERROR: {VENUES.get(jcd, jcd)} {rno}R - {e}")
                continue
        
        if venue_data["races"]:
            daily_data["venues"][jcd] = venue_data
    
    # JSON出力
    output_file = f"public/data/daily_{hd}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(daily_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n出力完了: {output_file}")
    return daily_data


def run_single_test(jcd: str = "06", hd: str = "20260215", rno: int = 1):
    """テスト用: 1レース分を実行"""
    result = run_pipeline(jcd, hd, rno, include_result=True)
    
    os.makedirs("public/data", exist_ok=True)
    outfile = f"public/data/race_{jcd}_{hd}_{rno}.json"
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== 予想結果 ===")
    print(f"会場: {result['meta']['venue_name']}")
    print(f"予測着順: {result['prediction']['predicted_order']}")
    print(f"確度: {result['prediction']['confidence']}%")
    print(f"決まり手予測: {result['kimarite_analysis']['predicted_kimarite']} "
          f"({result['kimarite_analysis']['kimarite_probability']}%)")
    print(f"戦略: {result['strategy']['strategy']} - {result['strategy']['recommended_action']}")
    
    if result['prediction'].get('recommended_tickets'):
        total = sum(t['amount'] for t in result['prediction']['recommended_tickets'])
        print(f"\n推奨舟券 (合計{total}円):")
        for t in result['prediction']['recommended_tickets'][:5]:
            print(f"  {t['combination']}: 確率{t['probability']}% → {t['amount']}円")
    
    return result


if __name__ == "__main__":
    run_single_test()
