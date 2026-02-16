# -*- coding: utf-8 -*-
"""1マーク旋回モデル - 6艇の旋回シミュレーション"""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.constants import PHYSICS
from src.physics.fluid import FluidDynamics, exhibition_time_to_velocity


class BoatState:
    """艇の状態を表すクラス"""
    
    def __init__(self, boat_number: int, x: float, y: float,
                 velocity: float, heading: float):
        self.boat_number = boat_number
        self.x = x
        self.y = y
        self.velocity = velocity
        self.heading = heading  # 進行方向 [rad] (0=北, π/2=東, π=南, 3π/2=西)
        self.turn_radius = 0.0
        self.trajectory = [(x, y)]
        self.phase = "approach"  # approach | turning | exit
        self.turn_progress = 0.0  # 旋回進行度 (0-1)
        self.spread_factor = 1.0  # 膨らみ度
        self.exit_velocity = 0.0
    
    def update_position(self, dt: float):
        """位置を更新
        heading=0: 北(y+), heading=π/2: 東(x+), heading=π: 南(y-), heading=3π/2: 西(x-)
        画面座標系: y軸は上が大きく、南に進むとyが減少
        """
        dx = self.velocity * math.sin(self.heading) * dt
        dy = self.velocity * math.cos(self.heading) * dt  # heading=πでcos=-1 → y減少
        self.x += dx
        self.y += dy
        self.trajectory.append((self.x, self.y))
    
    def to_dict(self):
        return {
            "boat_number": self.boat_number,
            "trajectory": self.trajectory,
            "exit_velocity": round(self.exit_velocity, 2),
            "spread_factor": round(self.spread_factor, 2),
            "turn_radius": round(self.turn_radius, 2),
        }


class TurnModel:
    """1マーク旋回モデル"""
    
    # 各コースの旋回半径補正（内側ほど小さい）
    COURSE_RADIUS_FACTOR = {
        1: 0.65,   # 最内コース
        2: 0.78,
        3: 0.90,
        4: 1.00,   # 基準
        5: 1.12,
        6: 1.25,   # 最外コース
    }
    
    # コース位置のY方向オフセット（手前ほど大きい = 内側が有利）
    COURSE_Y_OFFSET = {
        1: 0.0,
        2: 2.5,
        3: 5.0,
        4: 7.5,
        5: 10.0,
        6: 12.5,
    }
    
    # コースのX方向初期位置（内側が1マークに近い）
    COURSE_X_OFFSET = {
        1: 5.0,
        2: 12.0,
        3: 19.0,
        4: 26.0,
        5: 33.0,
        6: 40.0,
    }
    
    def __init__(self, fluid: FluidDynamics):
        self.fluid = fluid
    
    def create_initial_states(self, exhibition_times: list[float],
                              courses: list[int] | None = None) -> list[BoatState]:
        """
        展示タイムからの初期状態を生成
        
        Args:
            exhibition_times: 6艇の展示タイム（秒）
            courses: 進入コース（枠番→コース番号のマッピング）。None=枠なり
        Returns:
            6艇のBoatState
        """
        if courses is None:
            courses = [1, 2, 3, 4, 5, 6]
        
        states = []
        for i in range(min(len(exhibition_times), 6)):
            boat_num = i + 1
            course = courses[i]
            
            # 展示タイムから速度推定
            velocity = exhibition_time_to_velocity(exhibition_times[i])
            if velocity <= 0:
                velocity = 20.0  # デフォルト速度
            
            # 初期位置：1マーク手前の直線
            x = self.COURSE_X_OFFSET.get(course, 20.0)
            y = 80.0 + self.COURSE_Y_OFFSET.get(course, 0.0)
            
            state = BoatState(boat_num, x, y, velocity, heading=math.pi)
            states.append(state)
        
        return states
    
    def calc_turn_radius(self, course: int, velocity: float,
                         skill_factor: float = 1.0) -> float:
        """
        旋回半径を計算
        
        Args:
            course: コース番号
            velocity: 進入速度
            skill_factor: 選手の技術係数 (0.8~1.2)
        Returns:
            旋回半径 [m]
        """
        base_r = PHYSICS["turn_radius_base"]
        course_factor = self.COURSE_RADIUS_FACTOR.get(course, 1.0)
        
        # 速度が高い → 旋回半径が大きくなる
        speed_factor = 1.0 + 0.05 * max(0, velocity - 20.0)
        
        # 波の影響 → 膨らみやすい
        wave_factor = 1.0 + 0.3 * self.fluid.wave_height
        
        # 風の影響（横風だと膨らむ）
        wind_cross = abs(math.sin(self.fluid.wind_angle_rad))
        wind_factor = 1.0 + 0.1 * self.fluid.wind_speed * wind_cross
        
        return base_r * course_factor * speed_factor * wave_factor * wind_factor / skill_factor
    
    def calc_spread_factor(self, actual_radius: float, course: int) -> float:
        """
        膨らみ度を計算（1.0=最適、>1.0=膨らんでいる）
        
        Args:
            actual_radius: 実際の旋回半径
            course: コース番号
        Returns:
            膨らみ度
        """
        optimal_r = PHYSICS["turn_radius_base"] * self.COURSE_RADIUS_FACTOR.get(course, 1.0)
        return actual_radius / optimal_r if optimal_r > 0 else 1.0
    
    def predict_kimarite(self, states: list[BoatState]) -> dict:
        """
        物理シミュレーション結果から決まり手を予測
        
        Args:
            states: シミュレーション後の6艇の状態
        Returns:
            dict: 各決まり手の確率
        """
        if not states:
            return {}
        
        # 1号艇（最内）の状態
        inner_boat = states[0]
        
        # 膨らみ度、出口速度の相対比較
        inner_spread = inner_boat.spread_factor
        inner_exit_v = inner_boat.exit_velocity
        
        kimarite_probs = {
            "逃げ": 0.0,
            "差し": 0.0,
            "まくり": 0.0,
            "まくり差し": 0.0,
            "抜き": 0.0,
            "恵まれ": 0.0,
        }
        
        # 各外艇との比較
        outer_boats = [s for s in states[1:]]
        if not outer_boats:
            kimarite_probs["逃げ"] = 1.0
            return kimarite_probs
        
        max_outer_exit_v = max(s.exit_velocity for s in outer_boats) if outer_boats else 0
        avg_outer_exit_v = sum(s.exit_velocity for s in outer_boats) / len(outer_boats) if outer_boats else 0
        
        # ===== 決まり手確率の計算 =====
        
        # 逃げ: 内側の艇が膨らまず、出口速度も維持
        nige_score = 1.0
        if inner_spread > 1.15:
            nige_score *= max(0.1, 1.0 - (inner_spread - 1.0))
        if inner_exit_v < avg_outer_exit_v:
            nige_score *= max(0.1, inner_exit_v / avg_outer_exit_v) if avg_outer_exit_v > 0 else 0.5
        kimarite_probs["逃げ"] = nige_score
        
        # 差し: 内側の艇が膨らんだとき、差しが決まりやすい
        sashi_score = 0.0
        if inner_spread > 1.15:
            sashi_score = min(1.0, (inner_spread - 1.0) * 2.0)
            # 2号艇の出口速度が高い場合は差しが効く
            if len(outer_boats) > 0 and outer_boats[0].exit_velocity > inner_exit_v:
                sashi_score *= 1.3
        kimarite_probs["差し"] = min(1.0, sashi_score)
        
        # まくり: 外側の艇が速い＋内側が遅い
        makuri_score = 0.0
        if max_outer_exit_v > inner_exit_v * 1.05:
            makuri_score = min(1.0, (max_outer_exit_v / inner_exit_v - 1.0) * 5.0) if inner_exit_v > 0 else 0.5
        kimarite_probs["まくり"] = makuri_score
        
        # まくり差し: 内側が膨らむ＋外側に速い艇
        makuri_sashi_score = 0.0
        if inner_spread > 1.1 and max_outer_exit_v > inner_exit_v:
            makuri_sashi_score = min(1.0, (inner_spread - 1.0) * 1.5 * (max_outer_exit_v / inner_exit_v)) if inner_exit_v > 0 else 0.3
        kimarite_probs["まくり差し"] = min(1.0, makuri_sashi_score)
        
        # 正規化
        total = sum(kimarite_probs.values())
        if total > 0:
            kimarite_probs = {k: round(v / total, 4) for k, v in kimarite_probs.items()}
        
        return kimarite_probs
    
    def predict_finish_order(self, states: list[BoatState]) -> list[int]:
        """
        旋回後の隊列から着順を予測
        出口速度と位置の組み合わせで判定
        
        Returns:
            着順の艇番リスト [1着の番, 2着の艇番, ...]
        """
        if not states:
            return []
        
        # 各艇のスコア = 出口速度重み + 位置優位性
        scores = []
        for s in states:
            # x位置が小さい=内側（有利）、y位置が小さい=前方（有利）
            position_score = -s.y * 2.0 - s.x * 0.5
            velocity_score = s.exit_velocity * 3.0
            spread_penalty = -max(0, s.spread_factor - 1.0) * 10.0
            
            total = position_score + velocity_score + spread_penalty
            scores.append((s.boat_number, total))
        
        # スコア降順でソート
        scores.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in scores]
