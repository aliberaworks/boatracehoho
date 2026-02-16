# -*- coding: utf-8 -*-
"""荒れレース攻略モジュール - スクリーニング・決まり手分析・戦略判断"""

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class UpsetScreener:
    """1号艇勝率40%以下のレースをスクリーニング"""
    
    def __init__(self, history_data: list[dict] | None = None):
        self.history_data = history_data or []
    
    def screen_races(self, race_data_list: list[dict]) -> list[dict]:
        """
        1号艇の勝率が40%以下のレースをフィルタリング
        
        Args:
            race_data_list: 出走表データのリスト
        Returns:
            条件を満たすレースのリスト
        """
        upset_races = []
        
        for race in race_data_list:
            racers = race.get("racers", [])
            if not racers:
                continue
            
            # 1号艇の選手情報
            boat1 = next((r for r in racers if r.get("boat_number") == 1), None)
            if not boat1:
                continue
            
            win_rate = boat1.get("win_rate", 0)
            
            # 1号艇の勝率が低いレースのスクリーニング基準:
            # ・選手の全国勝率が低い（B級ボーダー）
            # ・モーター2連率が低い
            # ・当地勝率が低い
            is_upset_candidate = False
            
            if win_rate > 0 and win_rate < 5.0:  # B級レベル
                is_upset_candidate = True
            
            # 1号艇の2連率（勝率相当）が40%以下
            motor_rate = boat1.get("motor_2renritsu", 0)
            if motor_rate > 0 and motor_rate < 35.0:
                is_upset_candidate = True
            
            # 内枠の選手が明らかに弱い場合
            if win_rate > 0 and win_rate < 4.5:
                is_upset_candidate = True
            
            if is_upset_candidate:
                race["upset_score"] = self._calc_upset_score(race)
                upset_races.append(race)
        
        return upset_races
    
    def _calc_upset_score(self, race: dict) -> float:
        """荒れ度スコアを算出（高いほど荒れやすい）"""
        score = 50.0
        racers = race.get("racers", [])
        
        if not racers:
            return score
        
        # 1号艇と他の艇との実力差
        boat1 = next((r for r in racers if r.get("boat_number") == 1), None)
        if not boat1:
            return score
        
        boat1_rate = boat1.get("win_rate", 5.0)
        
        for racer in racers:
            if racer.get("boat_number") == 1:
                continue
            other_rate = racer.get("win_rate", 5.0)
            if other_rate > boat1_rate:
                score += (other_rate - boat1_rate) * 5.0
        
        return min(100.0, score)
    
    def analyze_payout_distribution(self, all_results: list[dict],
                                     upset_results: list[dict]) -> dict:
        """全体と荒れレースの平均配当を比較分析"""
        all_payouts = []
        upset_payouts = []
        
        for r in all_results:
            payouts = r.get("payouts", {}).get("3rentan", [])
            for p in payouts:
                payout_val = p.get("payout", 0)
                if payout_val > 0:
                    all_payouts.append(payout_val)
        
        for r in upset_results:
            payouts = r.get("payouts", {}).get("3rentan", [])
            for p in payouts:
                payout_val = p.get("payout", 0)
                if payout_val > 0:
                    upset_payouts.append(payout_val)
        
        avg_all = sum(all_payouts) / len(all_payouts) if all_payouts else 0
        avg_upset = sum(upset_payouts) / len(upset_payouts) if upset_payouts else 0
        
        return {
            "all_races": {
                "count": len(all_payouts),
                "average_payout": round(avg_all),
                "median_payout": round(sorted(all_payouts)[len(all_payouts)//2]) if all_payouts else 0,
            },
            "upset_races": {
                "count": len(upset_payouts),
                "average_payout": round(avg_upset),
                "median_payout": round(sorted(upset_payouts)[len(upset_payouts)//2]) if upset_payouts else 0,
            },
            "payout_ratio": round(avg_upset / avg_all, 2) if avg_all > 0 else 0,
        }


class KimariteAnalyzer:
    """決まり手分析モジュール"""
    
    def analyze_from_simulation(self, sim_result: dict) -> dict:
        """
        物理シミュレーション結果から決まり手を予測し、2,3着も推定
        
        Args:
            sim_result: シミュレーション結果
        Returns:
            決まり手予測と2,3着予測
        """
        kimarite_probs = sim_result.get("kimarite_probabilities", {})
        boats = sim_result.get("boats", [])
        predicted_order = sim_result.get("predicted_order", [])
        confidence = sim_result.get("confidence", 0)
        
        # 最も確率の高い決まり手
        if kimarite_probs:
            top_kimarite = max(kimarite_probs, key=kimarite_probs.get)
            top_prob = kimarite_probs[top_kimarite]
        else:
            top_kimarite = "不明"
            top_prob = 0
        
        # 決まり手に基づく2,3着の推定
        second_third = self._predict_second_third(top_kimarite, boats, predicted_order)
        
        return {
            "predicted_kimarite": top_kimarite,
            "kimarite_probability": round(top_prob * 100, 1),
            "predicted_2nd": second_third[0] if len(second_third) > 0 else 0,
            "predicted_3rd": second_third[1] if len(second_third) > 1 else 0,
            "confidence": confidence,
            "all_probabilities": {k: round(v*100, 1) for k, v in kimarite_probs.items()},
        }
    
    def _predict_second_third(self, kimarite: str, boats: list,
                               predicted_order: list) -> list[int]:
        """決まり手から2,3着を推定"""
        if len(predicted_order) < 3:
            return predicted_order[1:3] if len(predicted_order) > 1 else [0, 0]
        
        # 決まり手に応じた2,3着パターン
        if kimarite == "逃げ":
            # 逃げの場合、内側の艇が2,3着に来やすい
            return predicted_order[1:3]
        
        elif kimarite == "差し":
            # 差しの場合、2号艇が1着、1号艇が2着に残りやすい
            # 3着は3,4号艇
            first = predicted_order[0]
            remaining = [b for b in predicted_order if b != first]
            return remaining[:2] if len(remaining) >= 2 else [0, 0]
        
        elif kimarite == "まくり":
            # まくりの場合、まくった艇の外側が2着、内側が3着
            first = predicted_order[0]
            remaining = [b for b in predicted_order if b != first]
            return remaining[:2] if len(remaining) >= 2 else [0, 0]
        
        elif kimarite == "まくり差し":
            # まくり差しの場合、まくった艇が2着に残る
            first = predicted_order[0]
            remaining = [b for b in predicted_order if b != first]
            return remaining[:2] if len(remaining) >= 2 else [0, 0]
        
        return predicted_order[1:3]


class StrategyDecider:
    """3択戦略判断モジュール"""
    
    # 物理的確度の閾値
    HIGH_CONFIDENCE = 70.0
    LOW_CONFIDENCE = 40.0
    
    def decide(self, sim_result: dict, race_data: dict,
               local_stats: dict | None = None) -> dict:
        """
        3択の戦略判断
        
        1. 物理的確度が高い → シミュレーション予想に従う
        2. 確度が低い + 地元選手あり → 地元選手の勝率で判断
        3. 確度が低い + 地元選手なし → 高オッズ狙いまたは見送り
        
        Args:
            sim_result: シミュレーション結果
            race_data: 出走表データ
            local_stats: 地元選手の統計データ
        Returns:
            戦略判断結果
        """
        confidence = sim_result.get("confidence", 0)
        venue_code = race_data.get("venue_code", "")
        racers = race_data.get("racers", [])
        
        result = {
            "strategy": "",
            "reasoning": "",
            "confidence_level": "",
            "recommended_action": "",
            "detail": {},
        }
        
        # ==== 物理的確度が高い場合 ====
        if confidence >= self.HIGH_CONFIDENCE:
            result["strategy"] = "physics_prediction"
            result["confidence_level"] = "高"
            result["reasoning"] = (
                f"物理的確度 {confidence}% は高水準。展示タイムの差が明確で、"
                "風・波の条件も安定しているため、シミュレーション予想の信頼性が高い。"
            )
            result["recommended_action"] = "シミュレーション予想に従って舟券購入"
            return result
        
        # ==== 物理的確度が低い場合 ====
        # 地元選手チェック
        local_racers = self._find_local_racers(racers, venue_code)
        
        if local_racers and confidence < self.HIGH_CONFIDENCE:
            # 地元選手がいる場合
            best_local = max(local_racers, key=lambda r: r.get("local_win_rate", 0))
            local_rate = best_local.get("local_win_rate", 0)
            
            if local_rate >= 6.0:  # 地元勝率が高い
                result["strategy"] = "local_racer"
                result["confidence_level"] = "中"
                result["reasoning"] = (
                    f"物理的確度 {confidence}% は低いが、"
                    f"{best_local.get('name', '')}選手（{best_local.get('boat_number', '')}号艇）は"
                    f"当地勝率 {local_rate:.2f} と地元で高い実績がある。"
                    "水面特性の理解度が高く、不安定な条件下でも安定した走りが期待できる。"
                )
                result["recommended_action"] = (
                    f"{best_local.get('boat_number', '')}号艇を軸にした3連単を推奨"
                )
                result["detail"] = {
                    "local_racer": best_local.get("name", ""),
                    "boat_number": best_local.get("boat_number", 0),
                    "local_win_rate": local_rate,
                }
                return result
        
        # ==== 物理的確度が低い＋地元選手なし/弱い ====
        if confidence < self.LOW_CONFIDENCE:
            result["strategy"] = "skip"
            result["confidence_level"] = "低"
            result["reasoning"] = (
                f"物理的確度 {confidence}% は非常に低く、有力な地元選手も不在。"
                "このレースは予測困難であり、見送りを推奨する。"
                "無理に購入するよりも資金を温存し、確度の高いレースに集中すべき。"
            )
            result["recommended_action"] = "このレースは見送り"
            return result
        
        # 中間的な確度：高オッズ狙い
        result["strategy"] = "high_odds"
        result["confidence_level"] = "中低"
        result["reasoning"] = (
            f"物理的確度 {confidence}% は中程度。シミュレーション予想の信頼性は限定的だが、"
            "荒れる可能性が高いため、5,6号艇絡みの高オッズ3連単に絞って少額投資する戦略が有効。"
            "的中時の高配当で回収率の向上を狙う。"
        )
        result["recommended_action"] = "5,6号艇絡みの高オッズ3連単に少額投資"
        return result
    
    def _find_local_racers(self, racers: list, venue_code: str) -> list:
        """地元選手を特定"""
        # 会場コードから地域を特定
        venue_regions = {
            "01": "群馬", "02": "埼玉", "03": "東京", "04": "東京",
            "05": "東京", "06": "静岡", "07": "愛知", "08": "愛知",
            "09": "三重", "10": "福井", "11": "滋賀", "12": "大阪",
            "13": "兵庫", "14": "徳島", "15": "香川", "16": "岡山",
            "17": "広島", "18": "山口", "19": "山口", "20": "福岡",
            "21": "福岡", "22": "福岡", "23": "佐賀", "24": "長崎",
        }
        
        region = venue_regions.get(venue_code, "")
        if not region:
            return []
        
        return [r for r in racers if r.get("branch") == region]


if __name__ == "__main__":
    from src.physics.simulator import run_simulation
    
    # テスト
    test_times = [6.78, 6.82, 6.85, 6.90, 6.88, 6.95]
    sim_result = run_simulation(test_times, wind_speed=3.0, wind_direction="北",
                                 wave_height=5.0, water_temp=15.0)
    
    # 荒れレーススクリーニング
    screener = UpsetScreener()
    
    # 決まり手分析
    ka = KimariteAnalyzer()
    kimarite_result = ka.analyze_from_simulation(sim_result)
    print("=== 決まり手分析 ===")
    print(json.dumps(kimarite_result, ensure_ascii=False, indent=2))
    
    # 戦略判断
    sd = StrategyDecider()
    strategy = sd.decide(sim_result, {"venue_code": "06", "racers": []})
    print("\n=== 戦略判断 ===")
    print(json.dumps(strategy, ensure_ascii=False, indent=2))
