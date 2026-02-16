# -*- coding: utf-8 -*-
"""明日 (2026-02-17) の全場予想実行スクリプト"""
import sys
import os
import json
import datetime
import io

# Windows cp932問題回避
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from src.scraper.beforeinfo import scrape_beforeinfo
from src.scraper.racelist import scrape_racelist
from src.scraper.odds import scrape_odds
from src.physics.simulator import run_simulation
from src.prediction.predictor import generate_prediction
from src.upset.analyzer import KimariteAnalyzer, StrategyDecider
from src.utils.constants import VENUES

TARGET_DATE = "20260217"

def run_race(jcd, hd, rno):
    """1レースの予想を実行"""
    try:
        racelist = scrape_racelist(jcd, hd, rno)
        beforeinfo = scrape_beforeinfo(jcd, hd, rno)
        odds = scrape_odds(jcd, hd, rno)
        
        exhibition_times = beforeinfo.get("exhibition_times", [])
        if len(exhibition_times) < 6 or all(t == 0 for t in exhibition_times):
            return None  # データなし
        
        sim_result = run_simulation(
            exhibition_times,
            wind_speed=beforeinfo.get("wind_speed", 0),
            wind_direction=beforeinfo.get("wind_direction", ""),
            wave_height=beforeinfo.get("wave_height", 0),
            water_temp=beforeinfo.get("water_temperature", 20),
        )
        
        prediction = generate_prediction(sim_result, odds)
        
        ka = KimariteAnalyzer()
        sd = StrategyDecider()
        kimarite_analysis = ka.analyze_from_simulation(sim_result)
        strategy = sd.decide(sim_result, racelist)
        
        return {
            "meta": {
                "venue_code": jcd,
                "venue_name": VENUES.get(jcd, ""),
                "date": hd,
                "race_number": rno,
            },
            "beforeinfo": {
                "exhibition_times": exhibition_times,
                "wind_speed": beforeinfo.get("wind_speed", 0),
                "wind_direction": beforeinfo.get("wind_direction", ""),
                "wave_height": beforeinfo.get("wave_height", 0),
            },
            "prediction": prediction,
            "kimarite_analysis": kimarite_analysis,
            "strategy": strategy,
        }
    except Exception as e:
        return None


def main():
    hd = TARGET_DATE
    print(f"=== {hd} 全場予想 ===\n")
    
    os.makedirs("public/data", exist_ok=True)
    
    all_data = {}
    active_venues = []
    
    # まず各会場の1Rだけ試して開催の有無を確認
    print("開催会場を確認中...")
    for jcd, name in VENUES.items():
        try:
            info = scrape_beforeinfo(jcd, hd, 1)
            ex_times = info.get("exhibition_times", [])
            if ex_times and any(t > 0 for t in ex_times):
                active_venues.append(jcd)
                print(f"  ✓ {name} (jcd={jcd}) - 開催あり")
            else:
                # 展示タイムがないが、出走表はあるかも
                racelist = scrape_racelist(jcd, hd, 1)
                if racelist.get("racers"):
                    active_venues.append(jcd)
                    print(f"  ✓ {name} (jcd={jcd}) - 出走表あり（展示前）")
                else:
                    print(f"  ✗ {name} - 開催なし")
        except Exception:
            print(f"  ✗ {name} - データ取得失敗")
    
    if not active_venues:
        print("\n開催会場が見つかりませんでした。")
        print("直前情報（展示タイム）はレース当日に公開されるため、")
        print("レース開始前に再度実行してください。")
        # デモデータで全場予想を生成
        print("\n--- デモモードで予想を生成します ---\n")
        generate_demo_predictions(hd)
        return
    
    print(f"\n{len(active_venues)}会場で開催確認。全レース予想を開始...\n")
    
    for jcd in active_venues:
        venue_name = VENUES.get(jcd, jcd)
        venue_data = {"venue_name": venue_name, "races": {}}
        
        for rno in range(1, 13):
            result = run_race(jcd, hd, rno)
            if result:
                venue_data["races"][str(rno)] = result
                pred = result["prediction"]
                strategy = result["strategy"]
                
                top_combo = pred["recommended_tickets"][0]["combination"] if pred.get("recommended_tickets") else "-"
                print(f"  {venue_name} {rno}R: "
                      f"着順{pred['predicted_order'][:3]} "
                      f"確度{pred['confidence']}% "
                      f"決まり手={result['kimarite_analysis']['predicted_kimarite']} "
                      f"戦略={strategy['strategy']} "
                      f"本命={top_combo}")
        
        if venue_data["races"]:
            all_data[jcd] = venue_data
    
    # JSON保存
    output = {
        "date": hd,
        "generated_at": datetime.datetime.now().isoformat(),
        "venues": all_data,
    }
    
    outfile = f"public/data/daily_{hd}.json"
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== 完了: {outfile} に保存 ===")
    print(f"予想会場数: {len(all_data)}")
    total_races = sum(len(v["races"]) for v in all_data.values())
    print(f"予想レース数: {total_races}")


def generate_demo_predictions(hd):
    """展示タイムが未公開の場合、出走表ベースのデモ予想を生成"""
    import random
    
    all_data = {}
    
    # 主要6会場で予想
    demo_venues = ["04", "06", "09", "17", "21", "24"]
    
    for jcd in demo_venues:
        venue_name = VENUES.get(jcd, jcd)
        venue_data = {"venue_name": venue_name, "races": {}}
        
        for rno in range(1, 13):
            # ランダムな展示タイムを生成（現実的な範囲）
            base = 6.75 + random.random() * 0.15
            times = [round(base + random.gauss(0, 0.05), 2) for _ in range(6)]
            
            wind_speed = round(random.uniform(1, 5), 1)
            wind_dirs = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"]
            wind_dir = random.choice(wind_dirs)
            wave_height = round(random.uniform(1, 10), 0)
            water_temp = round(random.uniform(10, 18), 0)
            
            sim_result = run_simulation(times, wind_speed, wind_dir, wave_height, water_temp)
            prediction = generate_prediction(sim_result)
            
            ka = KimariteAnalyzer()
            sd = StrategyDecider()
            kimarite = ka.analyze_from_simulation(sim_result)
            strategy = sd.decide(sim_result, {"venue_code": jcd, "racers": []})
            
            race_data = {
                "meta": {"venue_code": jcd, "venue_name": venue_name, "date": hd, "race_number": rno},
                "beforeinfo": {
                    "exhibition_times": times,
                    "wind_speed": wind_speed,
                    "wind_direction": wind_dir,
                    "wave_height": wave_height,
                },
                "prediction": prediction,
                "kimarite_analysis": kimarite,
                "strategy": strategy,
                "demo": True,
            }
            venue_data["races"][str(rno)] = race_data
            
            top = prediction["recommended_tickets"][0]["combination"] if prediction.get("recommended_tickets") else "-"
            print(f"  {venue_name} {rno}R: "
                  f"着順{prediction['predicted_order'][:3]} "
                  f"確度{prediction['confidence']}% "
                  f"本命={top}")
        
        all_data[jcd] = venue_data
    
    output = {
        "date": hd,
        "generated_at": datetime.datetime.now().isoformat(),
        "demo_mode": True,
        "venues": all_data,
    }
    
    outfile = f"public/data/daily_{hd}.json"
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== 完了: {outfile} に保存（デモモード） ===")


if __name__ == "__main__":
    main()
