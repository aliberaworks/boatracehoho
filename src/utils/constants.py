# -*- coding: utf-8 -*-
"""ボートレース定数定義"""

# 全24場の会場コード
VENUES = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島",
    "05": "多摩川", "06": "浜名湖", "07": "蒲郡", "08": "常滑",
    "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
    "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島",
    "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
    "21": "芦屋", "22": "福岡", "23": "からつ", "24": "大村",
}

# ボートの色（艇番→色名）
BOAT_COLORS = {
    1: "#FFFFFF",  # 白
    2: "#000000",  # 黒
    3: "#FF0000",  # 赤
    4: "#0066FF",  # 青
    5: "#FFDD00",  # 黄
    6: "#00CC00",  # 緑
}

BOAT_COLOR_NAMES = {
    1: "白", 2: "黒", 3: "赤", 4: "青", 5: "黄", 6: "緑",
}

# URL テンプレート
BASE_URL = "https://www.boatrace.jp/owpc/pc/race"
URLS = {
    "racelist": f"{BASE_URL}/racelist?rno={{rno}}&jcd={{jcd}}&hd={{hd}}",
    "beforeinfo": f"{BASE_URL}/beforeinfo?rno={{rno}}&jcd={{jcd}}&hd={{hd}}",
    "raceresult": f"{BASE_URL}/raceresult?rno={{rno}}&jcd={{jcd}}&hd={{hd}}",
    "odds3t": f"{BASE_URL}/odds3t?rno={{rno}}&jcd={{jcd}}&hd={{hd}}",
    "raceindex": f"{BASE_URL}/raceindex?jcd={{jcd}}&hd={{hd}}",
}

# 物理定数
PHYSICS = {
    "water_density": 1000.0,      # 水の密度 [kg/m³]
    "air_density": 1.225,         # 空気密度 [kg/m³]
    "boat_mass": 160.0,           # 艇＋選手の平均質量 [kg]（艇33kg+モーター20kg+選手55kg+装備etc）
    "boat_drag_coeff": 0.35,      # 抗力係数
    "boat_wetted_area": 0.8,      # 浸水面積 [m²]
    "wind_effect_coeff": 0.15,    # 風の影響係数
    "wave_effect_coeff": 0.08,    # 波の影響係数
    "turn_radius_base": 15.0,     # 基準旋回半径 [m]
    "course_width": 60.0,         # コース幅（1マーク付近）[m]
    "exhibition_distance": 150.0, # 展示タイム計測区間 [m]
    "dt": 0.01,                   # シミュレーション時間ステップ [s]
}

# 決まり手
KIMARITE = {
    "nige": "逃げ",
    "makuri": "まくり",
    "sashi": "差し",
    "makuri_sashi": "まくり差し",
    "nuki": "抜き",
    "kouten": "恵まれ",
}

# 選手級別
RACER_CLASS = {
    "A1": "A1級",
    "A2": "A2級",
    "B1": "B1級",
    "B2": "B2級",
}
