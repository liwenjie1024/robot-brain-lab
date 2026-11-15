"""站着：在仿真里用关节的位置控制让一个身体站住，量它站得怎么样。对哪个身体都是同一套量法。

这里只是每个关节顶在站姿的角度上，没有平衡的控制。被推了还能站住、会走，是下一阶段（P2）的事。
量的都是仿真里真实的值（接触力、位置），不靠身体自己的传感器。
"""

import copy
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass

import mujoco
import numpy as np

from nova_body.bench import FLOOR, STAND_KEY
from nova_body.body import Anatomy, Body
from nova_body.mass_closure import GRAVITY_M_S2

STAND_SECONDS = 10.0
PUSH_SECONDS = 5.0
REALTIME_TEST_SECONDS = 2.0
# 骨盆比开始时低到这个比例以下，或者歪了这么多度，就算倒了。
FALLEN_HEIGHT_FRACTION = 0.7
FALLEN_TILT_DEG = 45.0
CONTACT_FORCE_SIZE = 6
UPRIGHT_AXIS = 2

# 站着的合格线：最多歪多少、骨盆最多低多少、脚最多滑多少、最后关节最多多快、地面托着的力和体重最多差多少。
MAX_TILT_DEG = 2.0
MAX_PELVIS_DROP_M = 0.005
MAX_FOOT_SLIP_M = 0.001
MAX_END_SPEED_RAD_S = 0.001
SUPPORT_FORCE_TOLERANCE = 0.005


@dataclass(frozen=True)
class Push:
    """推一下：在胸上加一个力（世界坐标，牛顿），从 start_s 开始，持续 duration_s。"""

    force_n: tuple[float, float, float]
    start_s: float = 1.0
    duration_s: float = 0.5

    def is_active(self, time_s: float) -> bool:
        """这个时刻是不是正在推。"""
        return self.start_s <= time_s < self.start_s + self.duration_s


@dataclass(frozen=True)
class StandingResult:
    """站着的结果。

    seconds：仿真了多久（倒了就提前结束）。pelvis_drop_m：骨盆最低时比开始低了多少。
    foot_slip_m：两只脚里滑得多的那只滑了多远。support_force_n：最后地面托着身体的力。
    pressure_center_from_heel_m：最后压力中心在脚跟前面多远（两只脚合起来）。
    """

    seconds: float
    fell: bool
    max_tilt_deg: float
    pelvis_drop_m: float
    foot_slip_m: float
    end_joint_speed_rad_s: float
    support_force_n: float
    weight_n: float
    pressure_center_from_heel_m: float
    foot_length_m: float


def push_of_weight(body: Body, share: float, direction: tuple[float, float, float]) -> Push:
    """朝一个方向推，力是体重的 share 倍。按体重的比例推，轻的身体和重的身体受的才是同样分量的一推。"""
    weight = body.mass_kg * GRAVITY_M_S2
    return Push(tuple(share * weight * axis for axis in direction))


def push_until_it_falls(
    body: Body, direction: tuple[float, float, float], shares: Sequence[float], seconds: float = PUSH_SECONDS
) -> list[tuple[float, StandingResult]]:
    """从小到大一档一档地推（力是体重的 share 倍），推到倒了为止。返回推过的每一档和它的结果。"""
    if not shares or any(share <= 0 for share in shares) or list(shares) != sorted(set(shares)):
        raise ValueError("推力要从小到大排，每一档都大于 0，不能重复")
    pushed = []
    for share in shares:
        result = simulate_standing(body, seconds, push_of_weight(body, share, direction))
        pushed.append((share, result))
        if result.fell:
            break
    return pushed


def stood_well(result: StandingResult) -> bool:
    """站得合不合格：没倒，没歪，没塌，脚没滑，最后是静止的，地面托着的力等于体重。"""
    return (
        not result.fell
        and result.max_tilt_deg < MAX_TILT_DEG
        and result.pelvis_drop_m < MAX_PELVIS_DROP_M
        and result.foot_slip_m < MAX_FOOT_SLIP_M
        and result.end_joint_speed_rad_s < MAX_END_SPEED_RAD_S
        and abs(result.support_force_n - result.weight_n) < SUPPORT_FORCE_TOLERANCE * result.weight_n
    )


def simulate_standing(
    body: Body, seconds: float = STAND_SECONDS, push: Push | None = None, *, controlled: bool = True
) -> StandingResult:
    """从站姿开始仿真 seconds 秒。controlled 是 False 时驱动器不出力（用来确认是控制让它站住的）。"""
    if seconds <= 0:
        raise ValueError(f"仿真的时间必须大于 0，收到的是 {seconds}")
    model = body.model if controlled else _without_actuation(body.model)
    data = standing_data(model)
    root = model.body(body.anatomy.root).id
    pushed = model.body(body.anatomy.trunk).id
    start_height = float(data.xpos[root][UPRIGHT_AXIS])
    start_soles = _sole_positions(model, data, body.anatomy)
    max_tilt_deg, lowest = 0.0, start_height
    fell = False
    for _ in range(round(seconds / model.opt.timestep)):
        pushing = push is not None and push.is_active(data.time)
        data.xfrc_applied[pushed, :3] = push.force_n if pushing else 0.0
        mujoco.mj_step(model, data)
        max_tilt_deg = max(max_tilt_deg, _tilt_deg(data, root))
        lowest = min(lowest, float(data.xpos[root][UPRIGHT_AXIS]))
        if lowest < FALLEN_HEIGHT_FRACTION * start_height or max_tilt_deg > FALLEN_TILT_DEG:
            fell = True
            break
    support, pressure_center = floor_support(model, data)
    end_soles = _sole_positions(model, data, body.anatomy)
    slips = np.linalg.norm((end_soles - start_soles)[:, :UPRIGHT_AXIS], axis=1)
    heel_forward = float(np.mean(end_soles[:, 0])) - body.foot_length_m / 2
    return StandingResult(
        seconds=float(data.time),
        fell=fell,
        max_tilt_deg=max_tilt_deg,
        pelvis_drop_m=start_height - lowest,
        foot_slip_m=float(slips.max()),
        end_joint_speed_rad_s=float(np.abs(data.qvel).max()),
        support_force_n=float(support),
        weight_n=body.mass_kg * GRAVITY_M_S2,
        pressure_center_from_heel_m=float(pressure_center[0]) - heel_forward,
        foot_length_m=body.foot_length_m,
    )


def standing_data(model: mujoco.MjModel) -> mujoco.MjData:
    """一份摆在站姿上的仿真状态。"""
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key(STAND_KEY).id)
    mujoco.mj_forward(model, data)
    return data


def floor_support(model: mujoco.MjModel, data: mujoco.MjData) -> tuple[float, np.ndarray]:
    """地面托着身体的力（各个接触点法向力的和），和压力中心的位置。没有接触时位置是 nan。"""
    floor = model.geom(FLOOR).id
    total = 0.0
    weighted = np.zeros(3)
    force = np.zeros(CONTACT_FORCE_SIZE)
    for index in range(data.ncon):
        contact = data.contact[index]
        if floor not in contact.geom:
            continue
        mujoco.mj_contactForce(model, data, index, force)
        total += force[0]
        weighted += force[0] * contact.pos
    center = weighted / total if total > 0 else np.full(3, math.nan)
    return total, center


def read_sensor(model: mujoco.MjModel, data: mujoco.MjData, name: str) -> np.ndarray:
    """按名字读一个传感器现在的值。"""
    sensor = model.sensor(name)
    start = sensor.adr[0]
    return data.sensordata[start : start + sensor.dim[0]].copy()


def pressure_center_from_ankle(force: np.ndarray, moment: np.ndarray, ankle_height_m: float) -> tuple[float, float]:
    """用踝部六轴力传感器的读数，算这只脚的压力中心在踝的前面、左边多远。

    传感器读的是小腿给脚的力和力矩（绕踝，脚的坐标）。脚本身很轻，这里不算它的重量。
    """
    pressing = -force[2]
    if pressing <= 0:
        raise ValueError("这只脚没有踩在地上，没有压力中心")
    forward = (moment[1] + ankle_height_m * force[0]) / pressing
    left = (-moment[0] + ankle_height_m * force[1]) / pressing
    return float(forward), float(left)


def measure_realtime_factor(body: Body, seconds: float = REALTIME_TEST_SECONDS) -> float:
    """仿真比实时快多少倍：仿真里的 seconds 秒，除以实际算了多久。"""
    model = body.model
    data = standing_data(model)
    steps = round(seconds / model.opt.timestep)
    start = time.perf_counter()
    for _ in range(steps):
        mujoco.mj_step(model, data)
    return steps * model.opt.timestep / (time.perf_counter() - start)


def _without_actuation(model: mujoco.MjModel) -> mujoco.MjModel:
    """同一个模型，但驱动器不出力。"""
    limp = copy.copy(model)
    limp.opt.disableflags |= mujoco.mjtDisableBit.mjDSBL_ACTUATION
    return limp


def _tilt_deg(data: mujoco.MjData, body: int) -> float:
    """这个身体的"上"和世界的"上"之间的夹角。"""
    upright = data.xmat[body].reshape(3, 3)[UPRIGHT_AXIS, UPRIGHT_AXIS]
    return math.degrees(math.acos(max(-1.0, min(1.0, float(upright)))))


def _sole_positions(model: mujoco.MjModel, data: mujoco.MjData, anatomy: Anatomy) -> np.ndarray:
    return np.array([data.site_xpos[model.site(leg.sole).id] for leg in anatomy.legs.values()])
