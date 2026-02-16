# -*- coding: utf-8 -*-
"""流体力学計算モジュール - ボートの水上力学モデル"""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.constants import PHYSICS


class FluidDynamics:
    """流体力学計算クラス"""
    
    def __init__(self, wind_speed: float = 0.0, wind_direction: str = "",
                 wave_height: float = 0.0, water_temp: float = 20.0):
        """
        Args:
            wind_speed: 風速 [m/s]
            wind_direction: 風向（北、南、etc）
            wave_height: 波高 [cm]
            water_temp: 水温 [℃]
        """
        self.wind_speed = wind_speed
        self.wind_direction = wind_direction
        self.wind_angle_rad = self._direction_to_angle(wind_direction)
        self.wave_height = wave_height / 100.0  # cm → m
        self.water_temp = water_temp
        
        # 水温による粘性変化（高温→低粘性→低抵抗）
        self.viscosity_factor = 1.0 + 0.005 * (20.0 - water_temp)
    
    def _direction_to_angle(self, direction: str) -> float:
        """風向を角度(ラジアン)に変換。北=0, 東=π/2, 南=π, 西=3π/2
        レースコースはホームストレッチが南向き想定"""
        dirs = {
            "北": 0, "北北東": math.pi/8, "北東": math.pi/4, "東北東": 3*math.pi/8,
            "東": math.pi/2, "東南東": 5*math.pi/8, "南東": 3*math.pi/4, "南南東": 7*math.pi/8,
            "南": math.pi, "南南西": 9*math.pi/8, "南西": 5*math.pi/4, "西南西": 11*math.pi/8,
            "西": 3*math.pi/2, "西北西": 13*math.pi/8, "北西": 7*math.pi/4, "北北西": 15*math.pi/8,
        }
        return dirs.get(direction, 0)
    
    def calc_drag_force(self, velocity: float) -> float:
        """
        水の抵抗力を計算
        F_drag = 0.5 * ρ * v² * Cd * A * viscosity_factor
        
        Args:
            velocity: 艇速 [m/s]
        Returns:
            抵抗力 [N]
        """
        rho = PHYSICS["water_density"]
        cd = PHYSICS["boat_drag_coeff"]
        area = PHYSICS["boat_wetted_area"]
        
        return 0.5 * rho * velocity**2 * cd * area * self.viscosity_factor
    
    def calc_wind_effect(self, velocity: float, heading_rad: float) -> float:
        """
        風による速度補正を計算
        
        Args:
            velocity: 現在の艇速 [m/s]
            heading_rad: 艇の進行方向 [rad]（0=北、π/2=東、π=南）
        Returns:
            速度変化量 [m/s]（正=加速、負=減速）
        """
        # 風の艇進行方向成分
        relative_angle = self.wind_angle_rad - heading_rad
        wind_component = self.wind_speed * math.cos(relative_angle)
        
        return PHYSICS["wind_effect_coeff"] * wind_component
    
    def calc_wave_resistance(self, velocity: float) -> float:
        """
        波による追加抵抗力を計算
        F_wave = k_wave * wave_height * v² * viscosity
        
        Args:
            velocity: 艇速 [m/s]
        Returns:
            波の追加抵抗力 [N]
        """
        return (PHYSICS["wave_effect_coeff"] * self.wave_height * 
                velocity**2 * PHYSICS["water_density"] * self.viscosity_factor)
    
    def calc_centripetal_force(self, velocity: float, radius: float) -> float:
        """
        旋回時の遠心力を計算
        F = m * v² / r
        
        Args:
            velocity: 旋回速度 [m/s]
            radius: 旋回半径 [m]
        Returns:
            遠心力 [N]
        """
        if radius <= 0:
            return float('inf')
        return PHYSICS["boat_mass"] * velocity**2 / radius
    
    def max_turn_velocity(self, radius: float, grip_factor: float = 1.0) -> float:
        """
        旋回半径から最大旋回速度を計算
        バランス条件: 遠心力 = グリップ力（水面との摩擦力的なもの）
        v_max = sqrt(grip * r / m)
        
        Args:
            radius: 旋回半径 [m]
            grip_factor: グリップ係数（選手の技術、波の影響など）
        Returns:
            最大旋回速度 [m/s]
        """
        # 波が高いとグリップが低下
        wave_grip_penalty = 1.0 - 0.3 * min(self.wave_height, 0.3) / 0.3
        effective_grip = grip_factor * wave_grip_penalty * 8000.0  # 基準グリップ力[N]
        
        return math.sqrt(effective_grip * radius / PHYSICS["boat_mass"])
    
    def effective_velocity(self, base_velocity: float, heading_rad: float) -> float:
        """
        風と波の影響を考慮した実効速度
        ※1タイムステップあたりの速度変化を当てはめる
        
        Args:
            base_velocity: 基本速度 [m/s]
            heading_rad: 進行方向 [rad]
        Returns:
            実効速度 [m/s]
        """
        dt = PHYSICS["dt"]
        # 風の影響（加速度として作用）
        wind_accel = self.calc_wind_effect(base_velocity, heading_rad)
        # 波の影響（減速加速度）
        wave_decel = self.calc_wave_resistance(base_velocity) / PHYSICS["boat_mass"]
        
        # dtを換算して速度変化を計算
        delta_v = (wind_accel - wave_decel) * dt
        
        return max(0.1, base_velocity + delta_v)


def exhibition_time_to_velocity(exhibition_time: float) -> float:
    """
    展示タイムから直線速度を推定
    展示タイム = 150m区間のタイム（秒）
    
    Args:
        exhibition_time: 展示タイム [秒]（例: 6.78）
    Returns:
        推定速度 [m/s]
    """
    if exhibition_time <= 0:
        return 0.0
    return PHYSICS["exhibition_distance"] / exhibition_time
