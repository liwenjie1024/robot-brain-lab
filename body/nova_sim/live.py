"""实时的仿真：一个身体站在测试台上，跟着墙上的钟往前走。网页看的就是它。

和测试里"站 10 秒"用的是同一个模型、同一个站姿、同一套量法。不同的只是它跟着真实的时间走，
中间可以暂停、松开驱动器、推一下、重新开始。
"""

import copy
from dataclasses import replace

import mujoco
import numpy as np

from nova_body.actuation import step
from nova_body.body import Body
from nova_body.sensing import Readings, SensorModel
from nova_body.standing import (
    FALLEN_HEIGHT_FRACTION,
    FALLEN_TILT_DEG,
    Push,
    drive_layer,
    floor_support,
    push_of_weight,
    standing_data,
    tilt_deg,
)

# 电脑一时算不过来（或者网页卡了一下）以后，最多补这么久的仿真；再多就让仿真慢下来，不去硬追。
MAX_CATCH_UP_S = 0.1
PUSH_DURATION_S = 0.5
DIRECTIONS: dict[str, tuple[float, float, float]] = {
    "forward": (1.0, 0.0, 0.0),
    "backward": (-1.0, 0.0, 0.0),
    "left": (0.0, 1.0, 0.0),
    "right": (0.0, -1.0, 0.0),
}
# "仿真是实时的多少倍"是一小段时间里的平均：每次往前走，新的值占这么多。
SPEED_SMOOTHING = 0.1
UP_AXIS = 2
ACTUATION_OFF = int(mujoco.mjtDisableBit.mjDSBL_ACTUATION)
# 给网页的数留几位小数：位置（米）、姿态、别的（力、力矩、角度）。
POSITION_DIGITS = 5
ORIENTATION_DIGITS = 6
VALUE_DIGITS = 4
BROKEN_NUMBER_WARNINGS = (
    mujoco.mjtWarning.mjWARN_BADQPOS,
    mujoco.mjtWarning.mjWARN_BADQVEL,
    mujoco.mjtWarning.mjWARN_BADQACC,
)
BROKEN_NUMBERS = "仿真里的数坏了（算出了不是数的值），已经停下，放回了站姿。请重新开始"


class CommandRejectedError(Exception):
    """现在做不了这条命令。说的话是给人看的。"""


class LiveSim:
    """测试台上的一个身体，和它这一回的状态。"""

    def __init__(self, key: str, body: Body, episode: int = 0) -> None:
        self.key = key
        self.body = body
        self.episode = episode
        # 自己用一份模型：松开驱动器是改模型里的开关，不能改到大家共用的那一份。
        self.model = copy.copy(body.model)
        self.data = standing_data(self.model)
        # 驱动器照它们的样子出力、发热；命令晚 1 毫秒到（改的是上面那一份自己的模型）。
        self.drives = drive_layer(body, self.model)
        # 身体自己的传感器：每一步读一次，加上噪声、零偏、延迟。网页上"感觉"那一块给的是它们读到的。
        self.sensors = SensorModel(self.model, body, seed=episode)
        self._root = self.model.body(body.anatomy.root).id
        self._trunk = self.model.body(body.anatomy.trunk).id
        self._feet = [self.model.body(leg.foot).id for leg in body.anatomy.legs.values()]
        # 每个关节、每个传感器的数存在哪，开始时找一次。
        joints = [self.model.joint(joint.name) for joint in body.joints]
        self._joint_angles = np.array([joint.qposadr[0] for joint in joints], dtype=int)
        self._joint_speeds = np.array([joint.dofadr[0] for joint in joints], dtype=int)
        self._timestep = float(self.model.opt.timestep)
        self.running = True
        self.fallen = False
        self.problem: str | None = None
        self._push: Push | None = None
        self._owed_s = 0.0
        self._speed = 0.0
        self._start_height = float(self.data.xpos[self._root][UP_AXIS])

    @property
    def controlled(self) -> bool:
        """驱动器是不是在出力。"""
        return not self.model.opt.disableflags & ACTUATION_OFF

    @property
    def time_s(self) -> float:
        """这一回里仿真过了多久。"""
        return float(self.data.time)

    # 命令 -------------------------------------------------------------------------------------------

    def reset(self) -> None:
        """重新开始：回到站姿，驱动器出力，时间归零，算新的一回。"""
        self.episode += 1
        self.set_controlled(True)
        self._put_in_stand_pose()
        self.running = True
        self.fallen = False
        self.problem = None

    def pause(self) -> None:
        """暂停。"""
        self.running = False

    def resume(self) -> None:
        """继续。出了问题的要先重新开始。"""
        if self.problem is not None:
            raise CommandRejectedError("仿真出了问题，要先重新开始")
        self.running = True

    def set_controlled(self, on: bool) -> None:
        """让驱动器出力，或者松开。"""
        flags = int(self.model.opt.disableflags)
        self.model.opt.disableflags = flags & ~ACTUATION_OFF if on else flags | ACTUATION_OFF

    def push(self, direction: str, share: float) -> None:
        """在胸上推一下：往 direction 推，力是体重的 share 倍，推 PUSH_DURATION_S 秒。"""
        if direction not in DIRECTIONS:
            raise CommandRejectedError(f"不认识的方向：{direction}")
        if not self.running:
            raise CommandRejectedError("暂停着的时候推不了，先点继续")
        if self._push is not None:
            raise CommandRejectedError("上一下还没推完")
        push = push_of_weight(self.body, share, DIRECTIONS[direction])
        self._push = replace(push, start_s=self.time_s, duration_s=PUSH_DURATION_S)

    # 往前走 -----------------------------------------------------------------------------------------

    def advance(self, wall_seconds: float) -> None:
        """墙上的钟过了 wall_seconds 秒：仿真也往前走这么久（暂停着就不走）。"""
        if wall_seconds < 0:
            raise ValueError(f"时间不能往回走，收到的是 {wall_seconds}")
        if not self.running:
            self._speed = 0.0
            return
        self._owed_s = min(self._owed_s + wall_seconds, MAX_CATCH_UP_S)
        steps = int(self._owed_s / self._timestep)
        for _ in range(steps):
            self._step()
            if self.problem is not None:
                return
        self._owed_s -= steps * self._timestep
        if wall_seconds > 0:
            self._speed += SPEED_SMOOTHING * (steps * self._timestep / wall_seconds - self._speed)

    def _step(self) -> None:
        pushing = self._push is not None and self._push.is_active(self.time_s)
        self.data.xfrc_applied[self._trunk, :3] = self._push.force_n if pushing else 0.0
        if self._push is not None and not pushing:
            self._push = None
        step(self.model, self.data, self.drives)
        self.sensors.sample(self.data)
        if self._numbers_broke():
            self._stop_with_problem(BROKEN_NUMBERS)
            return
        too_low = self.data.xpos[self._root][UP_AXIS] < FALLEN_HEIGHT_FRACTION * self._start_height
        if too_low or tilt_deg(self.data, self._root) > FALLEN_TILT_DEG:
            self.fallen = True

    def _numbers_broke(self) -> bool:
        """仿真算出了不是数的值没有。MuJoCo 遇到这种情况会自己悄悄回到零位，只留下一条警告，所以警告也要看。"""
        warned = any(self.data.warning[warning].number > 0 for warning in BROKEN_NUMBER_WARNINGS)
        return warned or not (np.isfinite(self.data.qpos).all() and np.isfinite(self.data.qvel).all())

    def _stop_with_problem(self, problem: str) -> None:
        """出了问题：停下，放回站姿（这样发给网页的还都是正常的数），记下是什么问题。"""
        self._put_in_stand_pose()
        self.running = False
        self.problem = problem

    def _put_in_stand_pose(self) -> None:
        self.drives.reset()
        self.sensors.reset()
        self.data = standing_data(self.model)
        self._push = None
        self._owed_s = 0.0
        self._speed = 0.0

    # 给网页的状态 -----------------------------------------------------------------------------------

    def state(self) -> dict:
        """这一刻的状态（contracts/sim/message.schema.json 的 State）。"""
        model, data = self.model, self.data
        # 仿真走完一步以后，传感器和接触还是那一步开始时的；再算一遍才是现在的。
        mujoco.mj_forward(model, data)
        support, center = floor_support(model, data)
        readings = self._readings()
        return {
            "type": "state",
            "body": self.key,
            "episode": self.episode,
            "time_s": round(self.time_s, VALUE_DIGITS),
            "running": self.running,
            "controlled": self.controlled,
            "fallen": self.fallen,
            "speed": round(self._speed, 2),
            "problem": self.problem,
            "link_positions": _rounded(data.xpos[1:], POSITION_DIGITS),
            "link_orientations": _rounded(data.xquat[1:], ORIENTATION_DIGITS),
            "joints": {
                "angles_rad": _rounded(data.qpos[self._joint_angles]),
                "speeds_rad_s": _rounded(data.qvel[self._joint_speeds]),
                "torques_nm": _rounded(data.qfrc_actuator[self._joint_speeds]),
            },
            "imus": [
                {"acceleration": _rounded(acceleration), "angular_velocity": _rounded(turning)}
                for acceleration, turning in readings.imus
            ],
            "forces": [{"force": _rounded(force), "moment": _rounded(moment)} for force, moment in readings.forces],
            "touches": [_rounded(touch) for touch in readings.touches],
            "feet": [_support(*floor_support(model, data, foot)) for foot in self._feet],
            "support_n": round(float(support), VALUE_DIGITS),
            "pressure_center": _point(support, center),
            "center_of_mass": _rounded(data.subtree_com[self._root], POSITION_DIGITS),
            "tilt_deg": round(tilt_deg(data, self._root), VALUE_DIGITS),
            "pelvis_height_m": round(float(data.xpos[self._root][UP_AXIS]), POSITION_DIGITS),
            "push": self._push_state(),
        }

    def _readings(self) -> Readings:
        """身体的传感器现在拿得到的读数。刚开始（还没走过一步）就先读一次。"""
        if not self.sensors.ready:
            self.sensors.sample(self.data)
        return self.sensors.latest()

    def _push_state(self) -> dict | None:
        if self._push is None:
            return None
        remaining = max(0.0, self._push.start_s + self._push.duration_s - self.time_s)
        return {"force_n": _rounded(self._push.force_n), "remaining_s": round(remaining, VALUE_DIGITS)}


def _support(force: float, center: np.ndarray) -> dict:
    return {"support_n": round(float(force), VALUE_DIGITS), "pressure_center": _point(force, center)}


def _point(force: float, center: np.ndarray) -> list[float] | None:
    """压力中心。地面没有托着（力是 0）的时候没有压力中心。"""
    return _rounded(center, POSITION_DIGITS) if force > 0 else None


def _rounded(values, digits: int = VALUE_DIGITS) -> list[float]:
    """一串数，留几位小数，排成一排。"""
    return np.round(np.asarray(values, dtype=float).ravel(), digits).tolist()
