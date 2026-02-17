# -*- coding: utf-8 -*-
"""メインパイプライン - スクレイピング→シミュレーション→予想→JSON出力

最適化版:
- JSON出力を予測要約のみに絞り < 5MB/日
- ThreadPoolExecutorによる並列スクレイピング
- 開催会場の事前検出で無駄なリクエスト排除
"""

import json
import os
import sys
import datetime
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Windows cp932対策（直接実行時のみ適用）
if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from src.scraper.beforeinfo import scrape_beforeinfo
from src.scraper.racelist import scrape_racelist
from src.scraper.raceresult import scrape_raceresult
from src.scraper.odds import scrape_odds
from src.physics.simulator import run_simulation
from src.prediction.predictor import generate_prediction
from src.upset.analyzer import KimariteAnalyzer, StrategyDecider
from src.utils.constants import VENUES

# ===== 定数 =====
MAX_JSON_BYTES = 50 * 1024 * 1024   # 50MB安全上限
MAX_WORKERS = 4                      # 並列スクレイピングスレッド数（礼儀として控えめに）


def _slim_prediction(prediction: dict) -> dict:
    """予想結果を公開に必要な最小限に絞る"""
    return {
        "predicted_order": prediction.get("predicted_order", [])[:3],
        "confidence": prediction.get("confidence", 0),
        "tickets": [
            {"combo": t["combination"], "prob": t["probability"], "amt": t["amount"]}
            for t in prediction.get("recommended_tickets", [])[:8]
        ],
    }


def _slim_sim(sim_result: dict) -> dict:
    """シミュレーション結果を要約のみに絞る（軌跡データを除外）"""
    boats = []
    for b in sim_result.get("boats", []):
        boats.append({
            "n": b["boat_number"],
            "ev": b["exit_velocity"],
            "sf": b["spread_factor"],
            "tr": b["turn_radius"],
        })
    return {
        "boats": boats,
        "order": sim_result.get("predicted_order", []),
        "kimarite": sim_result.get("kimarite_probabilities", {}),
        "confidence": sim_result.get("confidence", 0),
    }


def run_pipeline_slim(jcd: str, hd: str, rno: int) -> dict | None:
    """1レース分のパイプライン実行（スリム出力版）"""
    try:
        beforeinfo = scrape_beforeinfo(jcd, hd, rno)
        exhibition_times = beforeinfo.get("exhibition_times", [])

        # 展示タイムが無い＝レース未開催 or 未公開
        if len(exhibition_times) < 6 or all(t == 0 for t in exhibition_times):
            return None

        racelist = scrape_racelist(jcd, hd, rno)
        odds = scrape_odds(jcd, hd, rno)

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
        kimarite = ka.analyze_from_simulation(sim_result)
        strategy = sd.decide(sim_result, racelist)

        # ===== スリム出力 =====
        return {
            "r": rno,
            "ex": exhibition_times,
            "wind": f"{beforeinfo.get('wind_speed', 0)}m/{beforeinfo.get('wind_direction', '')}",
            "wave": beforeinfo.get("wave_height", 0),
            "sim": _slim_sim(sim_result),
            "pred": _slim_prediction(prediction),
            "km": {
                "type": kimarite.get("predicted_kimarite", ""),
                "prob": kimarite.get("kimarite_probability", 0),
                "2nd": kimarite.get("predicted_2nd", 0),
                "3rd": kimarite.get("predicted_3rd", 0),
            },
            "strat": {
                "type": strategy.get("strategy", ""),
                "action": strategy.get("recommended_action", ""),
                "level": strategy.get("confidence_level", ""),
            },
        }
    except Exception as e:
        print(f"  SKIP: {VENUES.get(jcd, jcd)} {rno}R - {e}", flush=True)
        return None


def detect_active_venues(hd: str) -> list[str]:
    """開催会場を高速に検出（1Rの展示データの有無で判定）"""
    active = []

    def check_venue(jcd):
        try:
            info = scrape_beforeinfo(jcd, hd, 1)
            ex = info.get("exhibition_times", [])
            if ex and any(t > 0 for t in ex):
                return jcd
            # 展示なしでも出走表があれば開催扱い
            rl = scrape_racelist(jcd, hd, 1)
            if rl.get("racers"):
                return jcd
        except Exception:
            pass
        return None

    # 並列で会場チェック
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(check_venue, jcd): jcd for jcd in VENUES}
        for future in as_completed(futures):
            result = future.result()
            if result:
                active.append(result)
                print(f"  [o] {VENUES.get(result, result)}", flush=True)
            else:
                jcd = futures[future]
                print(f"  [x] {VENUES.get(jcd, jcd)}", flush=True)

    return sorted(active)


def run_venue_races(jcd: str, hd: str) -> dict:
    """1会場の全12Rを処理"""
    venue_name = VENUES.get(jcd, jcd)
    races = {}
    for rno in range(1, 13):
        result = run_pipeline_slim(jcd, hd, rno)
        if result:
            races[str(rno)] = result
            pred = result["pred"]
            print(f"  {venue_name} {rno}R: "
                  f"{pred['predicted_order']} "
                  f"conf={pred['confidence']}% "
                  f"km={result['km']['type']} "
                  f"strat={result['strat']['type']}",
                  flush=True)
    return races


def run_daily(hd: str | None = None, venue_codes: list[str] | None = None):
    """1日分の予想をスリムJSONで出力"""
    if hd is None:
        hd = datetime.datetime.now().strftime("%Y%m%d")

    os.makedirs("public/data", exist_ok=True)
    start = time.time()

    # 1. 開催会場の検出
    print(f"=== {hd} 全場予想 ===\n開催会場を確認中...", flush=True)
    if venue_codes is None:
        venue_codes = detect_active_venues(hd)

    if not venue_codes:
        print("開催会場が見つかりませんでした。", flush=True)
        return {}

    print(f"\n{len(venue_codes)}会場で開催確認 ({', '.join(VENUES.get(c, c) for c in venue_codes)})\n",
          flush=True)

    # 2. 各会場のレース予想
    daily_data = {
        "date": hd,
        "ts": datetime.datetime.now().isoformat(),
        "venues": {},
    }

    for jcd in venue_codes:
        races = run_venue_races(jcd, hd)
        if races:
            daily_data["venues"][jcd] = {
                "name": VENUES.get(jcd, ""),
                "races": races,
            }

    # 3. JSON保存（indent無しで圧縮）
    output_file = f"public/data/daily_{hd}.json"
    json_str = json.dumps(daily_data, ensure_ascii=False, separators=(',', ':'))

    size_mb = len(json_str.encode('utf-8')) / (1024 * 1024)
    print(f"\nJSON size: {size_mb:.2f} MB", flush=True)

    if len(json_str.encode('utf-8')) > MAX_JSON_BYTES:
        print(f"WARNING: JSON ({size_mb:.1f}MB) exceeds {MAX_JSON_BYTES//1024//1024}MB limit, truncating tickets",
              flush=True)
        # チケット数を減らして再生成
        for v in daily_data["venues"].values():
            for r in v["races"].values():
                r["pred"]["tickets"] = r["pred"]["tickets"][:3]
        json_str = json.dumps(daily_data, ensure_ascii=False, separators=(',', ':'))
        size_mb = len(json_str.encode('utf-8')) / (1024 * 1024)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(json_str)

    elapsed = time.time() - start
    print(f"\n=== 完了 ===", flush=True)
    print(f"出力: {output_file} ({size_mb:.2f} MB)", flush=True)
    print(f"会場数: {len(daily_data['venues'])}", flush=True)
    total_races = sum(len(v["races"]) for v in daily_data["venues"].values())
    print(f"レース数: {total_races}", flush=True)
    print(f"実行時間: {elapsed/60:.1f}分", flush=True)

    return daily_data


def run_single_test(jcd: str = "06", hd: str = "20260215", rno: int = 1):
    """テスト用: 1レース分を詳細出力で実行"""
    result = run_pipeline_slim(jcd, hd, rno)

    os.makedirs("public/data", exist_ok=True)
    outfile = f"public/data/race_{jcd}_{hd}_{rno}.json"
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if result:
        print(f"\n=== 予想結果 ===", flush=True)
        print(f"予測着順: {result['pred']['predicted_order']}", flush=True)
        print(f"確度: {result['pred']['confidence']}%", flush=True)
        print(f"決まり手: {result['km']['type']} ({result['km']['prob']}%)", flush=True)
        print(f"戦略: {result['strat']['type']} - {result['strat']['action']}", flush=True)
        if result['pred'].get('tickets'):
            total = sum(t['amt'] for t in result['pred']['tickets'])
            print(f"\n推奨舟券 (合計{total}円):", flush=True)
            for t in result['pred']['tickets'][:5]:
                print(f"  {t['combo']}: {t['prob']}% -> {t['amt']}円", flush=True)
    else:
        print("データ取得失敗", flush=True)

    return result


if __name__ == "__main__":
    run_single_test()
