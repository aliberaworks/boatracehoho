# -*- coding: utf-8 -*-
"""予想エンジン - 統計分析・予想生成・舟券ポートフォリオ"""

import math
import json
import os
import sys
from itertools import permutations

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class Analyzer:
    """統計分析モジュール"""
    
    def __init__(self, history_file: str = "data/race_history.json"):
        self.history_file = history_file
        self.history = self._load_history()
    
    def _load_history(self) -> list:
        """過去の予測・結果履歴を読み込み"""
        if os.path.exists(self.history_file):
            with open(self.history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    def save_history(self):
        """履歴を保存"""
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)
    
    def add_prediction(self, prediction: dict, result: dict | None = None):
        """予測結果を履歴に追加"""
        entry = {
            "prediction": prediction,
            "result": result,
        }
        self.history.append(entry)
        self.save_history()
    
    def calc_hit_rate(self) -> dict:
        """的中率を算出"""
        total = 0
        hits_3rentan = 0
        hits_1st = 0
        
        for entry in self.history:
            if entry.get("result") is None:
                continue
            total += 1
            
            pred = entry["prediction"]
            result = entry["result"]
            
            # 1着予測の的中
            if (pred.get("predicted_order") and result.get("result_order")
                and len(pred["predicted_order"]) > 0 and len(result["result_order"]) > 0):
                pred_1st = pred["predicted_order"][0]
                actual_1st = result["result_order"][0].get("boat_number", 0) if isinstance(result["result_order"][0], dict) else result["result_order"][0]
                if pred_1st == actual_1st:
                    hits_1st += 1
            
            # 3連単の的中
            if pred.get("recommended_tickets"):
                actual_order = []
                for r in result.get("result_order", [])[:3]:
                    if isinstance(r, dict):
                        actual_order.append(r.get("boat_number", 0))
                    else:
                        actual_order.append(r)
                
                actual_key = "-".join(str(x) for x in actual_order)
                for ticket in pred["recommended_tickets"]:
                    if ticket.get("combination") == actual_key:
                        hits_3rentan += 1
                        break
        
        return {
            "total_races": total,
            "hit_rate_1st": round(hits_1st / total * 100, 1) if total > 0 else 0,
            "hit_rate_3rentan": round(hits_3rentan / total * 100, 1) if total > 0 else 0,
        }
    
    def calc_roi(self) -> dict:
        """回収率を算出"""
        total_bet = 0
        total_return = 0
        
        for entry in self.history:
            if entry.get("result") is None:
                continue
            
            pred = entry["prediction"]
            result = entry["result"]
            
            if not pred.get("recommended_tickets"):
                continue
            
            # 賭け金合計
            for ticket in pred["recommended_tickets"]:
                total_bet += ticket.get("amount", 0)
            
            # 払戻金
            actual_order = []
            for r in result.get("result_order", [])[:3]:
                if isinstance(r, dict):
                    actual_order.append(r.get("boat_number", 0))
                else:
                    actual_order.append(r)
            
            actual_key = "-".join(str(x) for x in actual_order)
            for ticket in pred["recommended_tickets"]:
                if ticket.get("combination") == actual_key:
                    # 3連単配当 × 賭け金 / 100
                    payout_info = result.get("payouts", {}).get("3rentan", [])
                    for p in payout_info:
                        if p.get("combination") == actual_key:
                            total_return += p.get("payout", 0) * ticket.get("amount", 0) / 100
                            break
        
        return {
            "total_bet": total_bet,
            "total_return": int(total_return),
            "roi": round(total_return / total_bet * 100, 1) if total_bet > 0 else 0,
        }


class Predictor:
    """予想生成モジュール"""
    
    def predict_probabilities(self, sim_result: dict) -> dict[str, float]:
        """
        シミュレーション結果から各3連単の確率を計算
        
        温度付きソフトマックスで小さな速度差を増幅し、
        実際の競艇に近い確率分布を生成する。
        
        Args:
            sim_result: simulator.run() の結果
        Returns:
            {"1-2-3": 0.15, "1-3-2": 0.08, ...}
        """
        boats = sim_result.get("boats", [])
        if len(boats) < 6:
            return {}
        
        # 各艇のスコアを算出（出口速度 + 位置 + 膨らみ）
        raw_scores = {}
        for boat in boats:
            bn = boat["boat_number"]
            exit_v = boat.get("exit_velocity", 0)
            spread = boat.get("spread_factor", 1.0)
            
            # スコア = 出口速度 - 膨らみペナルティ
            score = exit_v * 3.0 - max(0, spread - 1.0) * 10.0
            raw_scores[bn] = max(0.1, score)
        
        # 温度付きソフトマックスで確率変換 (temperature=0.3 で差を増幅)
        temperature = 0.3
        max_score = max(raw_scores.values())
        exp_scores = {}
        for bn, s in raw_scores.items():
            exp_scores[bn] = math.exp((s - max_score) / temperature)
        exp_total = sum(exp_scores.values())
        probs = {bn: e / exp_total for bn, e in exp_scores.items()}
        
        # 3連単の全120通りの確率を概算（条件付き確率）
        trifecta_probs = {}
        boat_nums = list(range(1, 7))
        
        for perm in permutations(boat_nums, 3):
            first, second, third = perm
            p_first = probs.get(first, 0.1)
            remaining_after_1st = {k: v for k, v in probs.items() if k != first}
            total_r1 = sum(remaining_after_1st.values())
            p_second = remaining_after_1st.get(second, 0.05) / total_r1 if total_r1 > 0 else 0.1
            
            remaining_after_2nd = {k: v for k, v in remaining_after_1st.items() if k != second}
            total_r2 = sum(remaining_after_2nd.values())
            p_third = remaining_after_2nd.get(third, 0.05) / total_r2 if total_r2 > 0 else 0.1
            
            combo_prob = p_first * p_second * p_third
            key = f"{first}-{second}-{third}"
            trifecta_probs[key] = round(combo_prob, 6)
        
        return trifecta_probs


class Portfolio:
    """舟券ポートフォリオ最適化"""
    
    def __init__(self, total_budget: int = 10000, min_probability: float = 0.02):
        """
        Args:
            total_budget: 合計予算 [円]
            min_probability: 最低確率閾値（これ以下は除外）
        """
        self.total_budget = total_budget
        self.min_probability = min_probability
    
    def generate_tickets(self, trifecta_probs: dict[str, float],
                         odds: dict[str, float] | None = None) -> list[dict]:
        """
        推奨舟券を生成
        確率が高いものほど多く賭ける（ケリー基準ベース）
        
        Args:
            trifecta_probs: 各3連単の確率
            odds: 各3連単のオッズ（オプション）
        Returns:
            推奨舟券リスト
        """
        # 確率閾値でフィルタ
        candidates = {k: v for k, v in trifecta_probs.items() 
                      if v >= self.min_probability}
        
        if not candidates:
            # 閾値を下げて上位10個を選択
            sorted_probs = sorted(trifecta_probs.items(), key=lambda x: x[1], reverse=True)
            candidates = dict(sorted_probs[:10])
        
        # ケリー基準に基づく金額配分
        tickets = []
        total_prob = sum(candidates.values())
        
        for combo, prob in sorted(candidates.items(), key=lambda x: x[1], reverse=True):
            # 確率に比例した配分
            ratio = prob / total_prob
            amount = max(100, round(self.total_budget * ratio / 100) * 100)  # 100円単位
            
            # 期待値の計算
            if odds and combo in odds:
                expected_value = prob * odds[combo] * 100
            else:
                expected_value = 0
            
            tickets.append({
                "combination": combo,
                "probability": round(prob * 100, 2),
                "amount": amount,
                "expected_value": round(expected_value, 0),
            })
        
        # 合計金額を予算に調整
        total_amount = sum(t["amount"] for t in tickets)
        if total_amount > self.total_budget:
            # 比例配分で調整
            scale = self.total_budget / total_amount
            for t in tickets:
                t["amount"] = max(100, round(t["amount"] * scale / 100) * 100)
        
        # 最終調整：合計が予算を超えない範囲で最後のチケットから削除
        while sum(t["amount"] for t in tickets) > self.total_budget:
            tickets[-1]["amount"] -= 100
            if tickets[-1]["amount"] < 100:
                tickets.pop()
        
        # 予算が余っている場合、最有力候補に追加
        remainder = self.total_budget - sum(t["amount"] for t in tickets)
        if remainder >= 100 and tickets:
            tickets[0]["amount"] += (remainder // 100) * 100
        
        return tickets


def generate_prediction(sim_result: dict, odds_data: dict | None = None) -> dict:
    """
    予想を生成するメイン関数
    
    Args:
        sim_result: シミュレーション結果
        odds_data: オッズデータ（オプション）
    Returns:
        予測結果dict
    """
    predictor = Predictor()
    portfolio = Portfolio()
    
    # 確率計算
    trifecta_probs = predictor.predict_probabilities(sim_result)
    
    # オッズデータを整形
    odds = odds_data.get("odds_3rentan", {}) if odds_data else None
    
    # 推奨舟券生成
    tickets = portfolio.generate_tickets(trifecta_probs, odds)
    
    return {
        "predicted_order": sim_result.get("predicted_order", []),
        "kimarite_probabilities": sim_result.get("kimarite_probabilities", {}),
        "confidence": sim_result.get("confidence", 0),
        "recommended_tickets": tickets,
        "trifecta_top10": dict(sorted(trifecta_probs.items(), 
                                       key=lambda x: x[1], reverse=True)[:10]),
    }


if __name__ == "__main__":
    # テスト
    from src.physics.simulator import run_simulation
    
    test_times = [6.78, 6.82, 6.85, 6.90, 6.88, 6.95]
    sim_result = run_simulation(test_times, wind_speed=3.0, wind_direction="北",
                                 wave_height=5.0, water_temp=15.0)
    
    prediction = generate_prediction(sim_result)
    
    print("=== 予想結果 ===")
    print(f"予測着順: {prediction['predicted_order']}")
    print(f"確度: {prediction['confidence']}%")
    print(f"\n推奨舟券 (合計{sum(t['amount'] for t in prediction['recommended_tickets'])}円):")
    for t in prediction['recommended_tickets']:
        print(f"  {t['combination']}: {t['probability']}% → {t['amount']}円")
