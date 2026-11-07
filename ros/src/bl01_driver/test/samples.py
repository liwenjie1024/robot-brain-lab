"""시험에서 쓰는 몸의 메시지 (contracts/sim의 규약 모양 그대로)"""

STATE = {
    "type": "state",
    "seq": 41,
    "episode": 3,
    "simTime": 12.345,
    "scenario": "skirmish",
    "bodies": [10.0, 0.0, 30.5, 0.9238795, 0.0, 0.0, 0.3826834, 1.0, 2.0, 3.0, 1.0, 0.0, 0.0, 0.0],
    "mecha": {
        "position": [10.0, 0.0, 30.5],
        "heading": 0.785398,
        "altitude": 20.0,
        "velocity": {"forward": 19.6, "sideways": -0.5, "up": 0.2, "turn": 0.1},
        "command": {"forward": 20.0, "sideways": 0.0, "up": 0.0, "turn": 0.0},
        "mode": "flying",
        "hp": 960,
        "maxHp": 1000,
        "energy": 80.5,
        "weapon": {"ready": True, "cooldown": 0.0, "aimTarget": "drone-1", "aimError": 0.4},
        "guard": {"raised": True, "unit": None},
        "pushing": False,
    },
    "units": [
        {
            "id": "drone-1",
            "kind": "drone",
            "name": "표적 드론 1",
            "position": [180.0, 0.0, 30.0],
            "velocity": [0.0, 12.0, 0.0],
            "hp": 30,
            "maxHp": 60,
            "alive": True,
            "armed": True,
        }
    ],
    "threats": [{"from": "drone-1", "secondsToFire": 0.8}],
}

SHOT_HIT = {
    "type": "shot",
    "simTime": 13.0,
    "shooter": "mecha",
    "from": [10.0, 0.0, 32.0],
    "to": [180.0, 0.0, 30.0],
    "hit": {"unit": "drone-1", "damage": 30, "blocked": False},
}

SHOT_MISS = {"type": "shot", "simTime": 13.5, "shooter": "drone-1", "from": [180.0, 0.0, 30.0], "to": [0.0, 0.0, 0.0]}

DESTROYED = {"type": "destroyed", "simTime": 14.0, "unit": "drone-1"}
