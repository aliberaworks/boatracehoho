# -*- coding: utf-8 -*-
"""シミュレーション実行エンジン - 時間ステップで6艇の1マーク旋回をシミュレート

改善版: 
- エンジン推力を導入（直線区間は巡航速度を維持）
- 旋回時のみ速度低下が起こる
- 波・風は微調整として作用（巡航速度自体は安定）
"""

import math
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.constants import PHYSICS
from src.physics.fluid import FluidDynamics, exhibition_time_to_velocity
from src.physics.turn_model import TurnModel, BoatState


class Simulator:
    """1マーク旋回シミュレーター"""
    
    MARK1_X = 15.0
    MARK1_Y = 30.0
    TURN_ANGLE = math.pi  # 180度ターン
    
    def __init__(self, wind_speed: float = 0.0, wind_direction: str = "",
                 wave_height: float = 0.0, water_temp: float = 20.0):
        self.fluid = FluidDynamics(wind_speed, wind_direction, wave_height, water_temp)
        self.turn_model = TurnModel(self.fluid)
        self.dt = PHYSICS["dt"]
    
    def run(self, exhibition_times: list[float],
            courses: list[int] | None = None,
            max_time: float = 15.0) -> dict:
        if courses is None:
            courses = [1, 2, 3, 4, 5, 6]
        
        states = self.turn_model.create_initial_states(exhibition_times, courses)
        
        # 各艇の旋回半径と巡航速度を事前計算
        for i, state in enumerate(states):
            course = courses[i] if i < len(courses) else i + 1
            state.turn_radius = self.turn_model.calc_turn_radius(
                course, state.velocity
            )
            # 巡航速度を記録
            state._cruise_velocity = state.velocity
        
        t = 0.0
        all_finished = False
        
        while t < max_time and not all_finished:
            all_finished = True
            
            for i, state in enumerate(states):
                course = courses[i] if i < len(courses) else i + 1
                
                if state.phase == "approach":
                    self._simulate_approach(state, course)
                elif state.phase == "turning":
                    self._simulate_turn(state, course)
                elif state.phase == "exit":
                    self._simulate_exit(state, course)
                elif state.phase == "finished":
                    continue
                
                if state.phase != "finished":
                    all_finished = False
            
            t += self.dt
        
        # Ensure exit velocity is set for boats that timed out
        for state in states:
            if state.exit_velocity == 0.0:
                state.exit_velocity = state.velocity
            state.spread_factor = self.turn_model.calc_spread_factor(
                state.turn_radius, courses[states.index(state)]
            )
        
        predicted_order = self.turn_model.predict_finish_order(states)
        kimarite_probs = self.turn_model.predict_kimarite(states)
        confidence = self._calc_confidence(exhibition_times)
        
        return {
            "boats": [s.to_dict() for s in states],
            "predicted_order": predicted_order,
            "kimarite_probabilities": kimarite_probs,
            "confidence": round(confidence, 2),
            "conditions": {
                "wind_speed": self.fluid.wind_speed,
                "wind_direction": self.fluid.wind_direction,
                "wave_height": self.fluid.wave_height * 100,
                "water_temp": self.fluid.water_temp,
            },
        }
    
    def _simulate_approach(self, state: BoatState, course: int):
        """アプローチ区間：エンジン推力で巡航速度を維持しつつ直進"""
        target_y = self.MARK1_Y + 5.0
        
        if state.y <= target_y:
            state.phase = "turning"
            state.turn_progress = 0.0
            return
        
        # 巡航速度を維持（風・波は微小な影響のみ）
        cruise_v = getattr(state, '_cruise_velocity', state.velocity)
        
        # 風による微調整（±0.5m/s程度）
        heading = math.pi
        wind_delta = self.fluid.calc_wind_effect(cruise_v, heading) * self.dt * 0.1
        # 波による微調整（波高による速度低下は最大3%程度）
        wave_penalty = 1.0 - min(0.03, self.fluid.wave_height * 0.6)
        
        state.velocity = cruise_v * wave_penalty + wind_delta
        state.heading = heading
        state.update_position(self.dt)
    
    def _simulate_turn(self, state: BoatState, course: int):
        """旋回区間：スロットルを絞り、遠心力と戦いながらターン"""
        r = state.turn_radius
        if r <= 0:
            r = PHYSICS["turn_radius_base"]
            state.turn_radius = r
        
        # 旋回中の目標速度（巡航速度の60-75%）
        cruise_v = getattr(state, '_cruise_velocity', 20.0)
        turn_speed_ratio = 0.70  # 旋回時速度比
        target_v = cruise_v * turn_speed_ratio
        
        # 波が高いとさらに減速
        wave_penalty = 1.0 - min(0.05, self.fluid.wave_height * 0.8)
        target_v *= wave_penalty
        
        # 速度を目標に漸近
        if state.velocity > target_v:
            state.velocity = max(target_v, state.velocity - 8.0 * self.dt)
        else:
            state.velocity = min(target_v, state.velocity + 3.0 * self.dt)
        
        # 旋回角速度
        omega = state.velocity / r
        
        # 方角更新（左旋回）
        delta_heading = omega * self.dt
        state.heading -= delta_heading
        state.turn_progress += delta_heading / self.TURN_ANGLE
        
        state.update_position(self.dt)
        
        if state.turn_progress >= 1.0:
            state.phase = "exit"
            state.exit_velocity = state.velocity
    
    def _simulate_exit(self, state: BoatState, course: int):
        """旋回後の加速区間"""
        cruise_v = getattr(state, '_cruise_velocity', 20.0)
        
        # ターン出口から巡航速度に戻る
        accel = 5.0
        if state.velocity < cruise_v:
            state.velocity = min(cruise_v, state.velocity + accel * self.dt)
        
        # 風の影響
        heading = 0.0
        wind_delta = self.fluid.calc_wind_effect(state.velocity, heading) * self.dt * 0.1
        state.velocity += wind_delta
        state.velocity = max(1.0, state.velocity)
        state.heading = heading
        state.update_position(self.dt)
        
        state.exit_velocity = max(state.exit_velocity, state.velocity)
        
        # 50ステップ（0.5秒）後に終了
        exit_steps = len([p for p in state.trajectory 
                          if state.phase == "exit"]) if hasattr(state, '_exit_step_count') else 0
        if not hasattr(state, '_exit_step_count'):
            state._exit_step_count = 0
        state._exit_step_count += 1
        
        if state._exit_step_count >= 50:
            state.phase = "finished"
    
    def _calc_confidence(self, exhibition_times: list[float]) -> float:
        """物理的確度を計算（0~100%）"""
        confidence = 50.0
        
        valid_times = [t for t in exhibition_times if t > 0]
        if len(valid_times) >= 2:
            mean_t = sum(valid_times) / len(valid_times)
            variance = sum((t - mean_t)**2 for t in valid_times) / len(valid_times)
            confidence += min(25.0, variance * 500)
        else:
            confidence -= 20.0
        
        if self.fluid.wind_speed <= 2.0:
            confidence += 10.0
        elif self.fluid.wind_speed > 5.0:
            confidence -= 10.0
        
        if self.fluid.wave_height <= 0.03:
            confidence += 10.0
        elif self.fluid.wave_height > 0.10:
            confidence -= 15.0
        
        return max(5.0, min(95.0, confidence))
    
    def to_json(self, result: dict) -> str:
        """結果をJSON文字列に変換（フロントエンド用）"""
        import copy
        output = copy.deepcopy(result)
        for boat in output["boats"]:
            traj = boat["trajectory"]
            if len(traj) > 200:
                step = len(traj) // 200
                boat["trajectory"] = traj[::step]
        return json.dumps(output, ensure_ascii=False)


def run_simulation(exhibition_times: list[float],
                   wind_speed: float = 0.0,
                   wind_direction: str = "",
                   wave_height: float = 0.0,
                   water_temp: float = 20.0) -> dict:
    sim = Simulator(wind_speed, wind_direction, wave_height, water_temp)
    return sim.run(exhibition_times)


if __name__ == "__main__":
    test_times = [6.78, 6.82, 6.85, 6.90, 6.88, 6.95]
    result = run_simulation(
        test_times,
        wind_speed=3.0,
        wind_direction="北",
        wave_height=5.0,
        water_temp=15.0
    )
    
    print("=== シミュレーション結果 ===")
    print(f"物理的確度: {result['confidence']}%")
    print(f"予測着順: {result['predicted_order']}")
    print(f"決まり手確率:")
    for k, v in result['kimarite_probabilities'].items():
        print(f"  {k}: {v*100:.1f}%")
    print(f"\n各艇情報:")
    for boat in result['boats']:
        print(f"  {boat['boat_number']}号艇: 出口速度={boat['exit_velocity']}m/s, "
              f"膨らみ度={boat['spread_factor']}, 旋回半径={boat['turn_radius']}m")
