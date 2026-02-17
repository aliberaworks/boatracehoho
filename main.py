# -*- coding: utf-8 -*-
"""メインパイプライン - 2パス方式 + 多層フィルタ

フロー:
  Pass 1: 全レースの出走表を並列スキャン → 1号艇勝率を取得
  Pass 2-filter: 多層フィルタ
    - Tier 1 (勝率 ≤ 4.0): 本命・荒れレース → メルマガ向け
    - Tier 2 (勝率 ≤ 5.5): 準・勝負レース → ダッシュボード向け
    - Tier 3: 物理異常検出 → 勝率不問で風/波が旋回に大影響のレース
    - Fallback: 上記ゼロの場合 → 最も荒れる可能性がある次点1レースを選出
  Pass 3: 対象レースだけ物理シミュレーション（並列）
 
目標: 全体15分以内に完了
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
from src.scraper.odds import scrape_odds
from src.physics.simulator import run_simulation
from src.prediction.predictor import generate_prediction
from src.upset.analyzer import KimariteAnalyzer, StrategyDecider
from src.utils.constants import VENUES

# ===== 設定 =====
MAX_JSON_BYTES = 50 * 1024 * 1024
SCAN_WORKERS = 6
SIM_WORKERS = 4

# 勝率フィルタ閾値（ボートレースの勝率は10点満点スケール）
TIER1_THRESHOLD = 4.0    # 本命荒れレース（メルマガ向け）
TIER2_THRESHOLD = 5.5    # 準・勝負レース（ダッシュボード向け）

# 物理異常検出の閾値
SPREAD_ANOMALY_RATIO = 1.5  # 旋回半径が通常の1.5倍以上に膨らむレース

LOG_PREFIX = {
    "scan": "[SCAN]",
    "skip": "[SKIP]",
    "sim":  "[SIM ]",
    "ok":   "[ OK ]",
    "warn": "[WARN]",
    "done": "[DONE]",
    "phys": "[PHYS]",
}


def log(cat: str, msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {LOG_PREFIX.get(cat, '     ')} {msg}", flush=True)


# ====================================================================
# Pass 1: 高速スキャン
# ====================================================================

def _scan_one_race(args: tuple) -> dict | None:
    """1レースの出走表を取得して1号艇勝率を返す"""
    jcd, hd, rno = args
    try:
        racelist = scrape_racelist(jcd, hd, rno)
        racers = racelist.get("racers", [])
        if not racers:
            return None
        boat1 = next((r for r in racers if r.get("boat_number") == 1), None)
        win_rate_1 = boat1.get("win_rate", 0.0) if boat1 else 0.0
        return {
            "jcd": jcd, "hd": hd, "rno": rno,
            "win_rate_1": win_rate_1,
            "race_name": racelist.get("race_name", ""),
            "racers": racers,
        }
    except Exception:
        return None


def scan_all_races(hd: str, venue_codes: list[str] | None = None) -> list[dict]:
    """全レースを並列スキャン"""
    if venue_codes is None:
        venue_codes = list(VENUES.keys())
    log("scan", f"{len(venue_codes)}場 x 12R = {len(venue_codes)*12} race scan...")
    tasks = [(jcd, hd, rno) for jcd in venue_codes for rno in range(1, 13)]
    results = []
    venue_found = set()
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        futures = {pool.submit(_scan_one_race, t): t for t in tasks}
        done = 0
        for future in as_completed(futures):
            done += 1
            r = future.result()
            if r:
                results.append(r)
                venue_found.add(r["jcd"])
            if done % 48 == 0:
                log("scan", f"  {done}/{len(tasks)} done...")
    for jcd in venue_codes:
        vn = VENUES.get(jcd, jcd)
        if jcd in venue_found:
            cnt = sum(1 for r in results if r["jcd"] == jcd)
            log("ok", f"{vn}: {cnt}R")
        else:
            log("skip", f"{vn}: non-open")
    log("scan", f"Scan done: {len(venue_found)} venues / {len(results)} races")
    return results


# ====================================================================
# Pass 2: 多層フィルタ
# ====================================================================

def _quick_wind_check(jcd: str, hd: str, rno: int) -> dict | None:
    """直前情報を取得して風速・波高を返す（物理異常検出用の軽量チェック）"""
    try:
        bi = scrape_beforeinfo(jcd, hd, rno)
        return {
            "wind_speed": bi.get("wind_speed", 0),
            "wind_direction": bi.get("wind_direction", ""),
            "wave_height": bi.get("wave_height", 0),
            "exhibition_times": bi.get("exhibition_times", []),
        }
    except Exception:
        return None


def detect_physical_anomalies(scanned: list[dict], already_selected: set) -> list[dict]:
    """
    物理異常検出: 統計では逃げだが、風・波で旋回半径が1.5倍に膨らむレース
    勝率に関わらずピックアップ
    """
    # 高勝率レース（通常イン逃げ）で直前情報をチェック
    candidates = [r for r in scanned
                  if r["win_rate_1"] > TIER2_THRESHOLD
                  and (r["jcd"], r["rno"]) not in already_selected]

    if not candidates:
        return []

    log("phys", f"Physics anomaly check: {len(candidates)} stable races...")
    anomalies = []

    # 上位20レースだけチェック（時間節約）
    top_stable = sorted(candidates, key=lambda x: x["win_rate_1"], reverse=True)[:20]

    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        future_map = {}
        for r in top_stable:
            f = pool.submit(_quick_wind_check, r["jcd"], r["hd"], r["rno"])
            future_map[f] = r

        for future in as_completed(future_map):
            race = future_map[future]
            weather = future.result()
            if not weather:
                continue

            wind = weather["wind_speed"]
            wave = weather["wave_height"]

            # 物理異常判定: 強風(5m以上) or 高波(10cm以上) の組合せ
            is_anomaly = False
            reason = ""

            if wind >= 5 and wave >= 5:
                is_anomaly = True
                reason = f"wind={wind}m + wave={wave}cm"
            elif wind >= 7:
                is_anomaly = True
                reason = f"strong wind={wind}m"
            elif wave >= 10:
                is_anomaly = True
                reason = f"high wave={wave}cm"

            if is_anomaly:
                vn = VENUES.get(race["jcd"], race["jcd"])
                log("phys", f"  ANOMALY: {vn} {race['rno']}R "
                    f"(wr1={race['win_rate_1']}, {reason})")
                race["tier"] = "physics"
                race["anomaly_reason"] = reason
                race["weather"] = weather
                anomalies.append(race)

    if not anomalies:
        log("phys", "  No physics anomalies detected")

    return anomalies


def filter_races(scanned: list[dict]) -> list[dict]:
    """多層フィルタ: Tier1 → Tier2 → 物理異常 → Fallback"""
    tier1 = []
    tier2 = []
    selected_keys = set()

    for r in scanned:
        wr = r["win_rate_1"]
        if wr <= TIER1_THRESHOLD:
            r["tier"] = "tier1"
            tier1.append(r)
            selected_keys.add((r["jcd"], r["rno"]))
        elif wr <= TIER2_THRESHOLD:
            r["tier"] = "tier2"
            tier2.append(r)
            selected_keys.add((r["jcd"], r["rno"]))

    # 物理異常検出（既選択を除外）
    anomalies = detect_physical_anomalies(scanned, selected_keys)
    for a in anomalies:
        selected_keys.add((a["jcd"], a["rno"]))

    # ---- ログ出力 ----
    log("scan", "=" * 50)
    log("scan", "Filter results:")
    log("scan", f"  Tier 1 (wr <= {TIER1_THRESHOLD}): {len(tier1)}R [newsletter]")
    log("scan", f"  Tier 2 (wr <= {TIER2_THRESHOLD}): {len(tier2)}R [dashboard]")
    log("scan", f"  Physics anomaly:     {len(anomalies)}R")

    combined = tier1 + tier2 + anomalies

    # ---- Fallback: ゼロなら最も荒れそうな次点1Rを選出 ----
    if not combined and scanned:
        # 最も1号艇勝率が低いレースを選出
        best = min(scanned, key=lambda x: x["win_rate_1"])
        best["tier"] = "fallback"
        combined = [best]
        vn = VENUES.get(best["jcd"], best["jcd"])
        log("warn", f"  No candidates! Fallback: {vn} {best['rno']}R "
            f"(wr1={best['win_rate_1']}) -- best available upset")

    log("scan", f"  TOTAL for simulation: {len(combined)}R")
    log("scan", "=" * 50)

    # 会場ごとのサマリー
    venue_tiers = {}
    for r in combined:
        jcd = r["jcd"]
        vn = VENUES.get(jcd, jcd)
        if vn not in venue_tiers:
            venue_tiers[vn] = {"t1": 0, "t2": 0, "phys": 0, "fb": 0}
        t = r.get("tier", "")
        if t == "tier1":
            venue_tiers[vn]["t1"] += 1
        elif t == "tier2":
            venue_tiers[vn]["t2"] += 1
        elif t == "physics":
            venue_tiers[vn]["phys"] += 1
        elif t == "fallback":
            venue_tiers[vn]["fb"] += 1

    for vn, s in sorted(venue_tiers.items()):
        parts = []
        if s["t1"]:
            parts.append(f"t1={s['t1']}")
        if s["t2"]:
            parts.append(f"t2={s['t2']}")
        if s["phys"]:
            parts.append(f"phys={s['phys']}")
        if s["fb"]:
            parts.append(f"fallback={s['fb']}")
        log("sim", f"  {vn}: {', '.join(parts)}")

    return combined


# ====================================================================
# Pass 3: シミュレーション
# ====================================================================

def _slim_prediction(prediction: dict) -> dict:
    return {
        "predicted_order": prediction.get("predicted_order", [])[:3],
        "confidence": prediction.get("confidence", 0),
        "tickets": [
            {"combo": t["combination"], "prob": t["probability"], "amt": t["amount"]}
            for t in prediction.get("recommended_tickets", [])[:8]
        ],
    }


def _slim_sim(sim_result: dict) -> dict:
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


def simulate_one_race(race_info: dict) -> tuple[str, int, dict | None]:
    """1レースのフルシミュレーション"""
    jcd = race_info["jcd"]
    hd = race_info["hd"]
    rno = race_info["rno"]

    try:
        beforeinfo = scrape_beforeinfo(jcd, hd, rno)
        exhibition_times = beforeinfo.get("exhibition_times", [])
        if len(exhibition_times) < 6 or all(t == 0 for t in exhibition_times):
            return (jcd, rno, None)

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
        racelist_dict = {"racers": race_info.get("racers", [])}
        strategy = sd.decide(sim_result, racelist_dict)

        # 旋回膨らみ検出
        boat1_sim = next((b for b in sim_result.get("boats", []) if b["boat_number"] == 1), None)
        spread_warning = ""
        if boat1_sim:
            sf = boat1_sim.get("spread_factor", 1.0)
            if sf >= SPREAD_ANOMALY_RATIO:
                spread_warning = f"spread={sf:.2f}x"

        output = {
            "r": rno,
            "tier": race_info.get("tier", ""),
            "win1": race_info["win_rate_1"],
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

        if spread_warning:
            output["spread_warning"] = spread_warning
        if race_info.get("anomaly_reason"):
            output["anomaly"] = race_info["anomaly_reason"]

        return (jcd, rno, output)
    except Exception:
        return (jcd, rno, None)


def run_simulations(races: list[dict]) -> dict:
    """対象レースを並列シミュレーション"""
    if not races:
        log("warn", "No races to simulate")
        return {}
    log("sim", f"Simulating {len(races)}R (workers={SIM_WORKERS})...")
    venues_data = {}
    done = 0
    with ThreadPoolExecutor(max_workers=SIM_WORKERS) as pool:
        futures = {pool.submit(simulate_one_race, r): r for r in races}
        for future in as_completed(futures):
            done += 1
            jcd, rno, result = future.result()
            vn = VENUES.get(jcd, jcd)
            if result:
                if jcd not in venues_data:
                    venues_data[jcd] = {"name": vn, "races": {}}
                venues_data[jcd]["races"][str(rno)] = result
                pred = result["pred"]
                tier_tag = f"[{result.get('tier','?')}]"
                extra = ""
                if result.get("spread_warning"):
                    extra = f" !! {result['spread_warning']}"
                if result.get("anomaly"):
                    extra += f" !! {result['anomaly']}"
                log("ok", f"[{done}/{len(races)}] {tier_tag} {vn} {rno}R: "
                    f"wr1={result['win1']} -> {pred['predicted_order']} "
                    f"conf={pred['confidence']}% km={result['km']['type']}{extra}")
            else:
                log("skip", f"[{done}/{len(races)}] {vn} {rno}R: no data")
    return venues_data


# ====================================================================
# メイン
# ====================================================================

def run_daily(hd: str | None = None, venue_codes: list[str] | None = None):
    """1日分の予想パイプライン"""
    if hd is None:
        hd = datetime.datetime.now().strftime("%Y%m%d")
    os.makedirs("public/data", exist_ok=True)
    start = time.time()

    log("done", f"=== {hd} Pipeline Start ===")

    # Pass 1: Scan
    t1 = time.time()
    scanned = scan_all_races(hd, venue_codes)
    scan_sec = time.time() - t1
    log("scan", f"Pass 1 done: {scan_sec:.0f}s")

    if not scanned:
        log("warn", "No races found today.")
        out = f"public/data/daily_{hd}.json"
        with open(out, 'w', encoding='utf-8') as f:
            json.dump({"date": hd, "ts": datetime.datetime.now().isoformat(),
                       "venues": {}, "stats": {"scanned": 0}}, f)
        log("done", f"Empty output: {out}")
        return {}

    # Pass 2: Filter
    t2 = time.time()
    targets = filter_races(scanned)
    filter_sec = time.time() - t2
    log("scan", f"Pass 2 done: {filter_sec:.0f}s")

    # Pass 3: Simulate
    t3 = time.time()
    venues_data = run_simulations(targets)
    sim_sec = time.time() - t3
    log("sim", f"Pass 3 done: {sim_sec:.0f}s")

    # Output
    total_sim = sum(len(v["races"]) for v in venues_data.values())
    daily_data = {
        "date": hd,
        "ts": datetime.datetime.now().isoformat(),
        "stats": {
            "scanned": len(scanned),
            "tier1": sum(1 for r in targets if r.get("tier") == "tier1"),
            "tier2": sum(1 for r in targets if r.get("tier") == "tier2"),
            "physics": sum(1 for r in targets if r.get("tier") == "physics"),
            "fallback": sum(1 for r in targets if r.get("tier") == "fallback"),
            "simulated": total_sim,
            "thresholds": {"t1": TIER1_THRESHOLD, "t2": TIER2_THRESHOLD},
            "timing": {"scan": round(scan_sec), "filter": round(filter_sec),
                       "sim": round(sim_sec), "total": round(time.time() - start)},
        },
        "venues": venues_data,
    }

    output_file = f"public/data/daily_{hd}.json"
    json_str = json.dumps(daily_data, ensure_ascii=False, separators=(',', ':'))
    size_mb = len(json_str.encode('utf-8')) / (1024 * 1024)

    if len(json_str.encode('utf-8')) > MAX_JSON_BYTES:
        log("warn", f"JSON {size_mb:.1f}MB > limit, truncating")
        for v in daily_data["venues"].values():
            for r in v["races"].values():
                r["pred"]["tickets"] = r["pred"]["tickets"][:3]
        json_str = json.dumps(daily_data, ensure_ascii=False, separators=(',', ':'))
        size_mb = len(json_str.encode('utf-8')) / (1024 * 1024)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(json_str)

    elapsed = time.time() - start
    log("done", "=" * 50)
    log("done", f"Pipeline Complete: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log("done", f"Output: {output_file} ({size_mb:.2f}MB)")
    log("done", f"Scanned {len(scanned)}R -> Filtered {len(targets)}R -> Simulated {total_sim}R")
    log("done", "=" * 50)

    return daily_data


def run_single_test(jcd: str = "04", hd: str = "20260217", rno: int = 1):
    """テスト用: 1レース"""
    race_info = {"jcd": jcd, "hd": hd, "rno": rno, "win_rate_1": 0.0, "racers": []}
    _, _, result = simulate_one_race(race_info)
    if result:
        log("ok", f"Order: {result['pred']['predicted_order']}")
        log("ok", f"Confidence: {result['pred']['confidence']}%")
        log("ok", f"Kimarite: {result['km']['type']} ({result['km']['prob']}%)")
    else:
        log("warn", "Failed")
    return result


if __name__ == "__main__":
    run_single_test()
