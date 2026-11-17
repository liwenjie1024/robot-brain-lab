"""一轮家务的热预算（1.6 步）：每个驱动器在连续 2 小时的家务里热到多少度，身体要散走多少热。

一轮家务（Nova 考试：连续 2 小时，第一批的六项）在这里写成一个 10 分钟的循环，做 12 遍：走来走去、
蹲下捡东西、开门、擦桌子、把东西放到柜子上、偶尔搬重的、上下楼，中间站着歇。每样事用 1.5 步写好的动作，
每一帧的力矩来自逆动力学，再加上驱动器自己的摩擦。并联的两个驱动器，一个出两个力矩之和的一半，
一个出之差的一半。热按 drives 的两个节点（绕组、驱动器的身子）一段一段地算。

另外单看两种"一直出力"的（机体规格第 5 节第 12 条）：端着箱子站着、蹲着干活，从一轮家务做完时的温度开始，
多久开始降额。
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from nova_body.body import SIDE_NAMES, Body, Side
from nova_body.design import JOINT_GROUPS, JointGroup, TorqueRule
from nova_body.drives import COOLANT_C, COPPER_TEMPERATURE_COEFFICIENT, DERATE_FROM_C, REFERENCE_C, DriveSpec
from nova_body.skeleton import side_prefix
from nova_body.strength import MotionDemand, MotionSeries, group_members

# 热按 0.1 秒一段算：一段里铜损取平均（力矩的平方的平均）。绕组最快的时间常数十几秒，这样足够细。
BLOCK_S = 0.1
CYCLE_S = 600.0
CYCLES = 12
# 写进设计的"要一直出的力矩"：一轮家务里最费力的 5 分钟的均方根（液冷的驱动器身子约 5 分钟热透），再 x 1.2
# （夏天屋里热、一轮做完接着做）。
SIZING_WINDOW_S = 300.0
CONTINUOUS_MARGIN = 1.2
HOLD_S = 600.0
SECONDS_PER_MINUTE = 60.0
PAIR_SIGNS = (1.0, -1.0)
PAIR_NAMES = ("甲", "乙")


class Moment(StrEnum):
    """保持一个动作里的哪一刻。"""

    LAST = "最后一刻"
    HARDEST = "最费力的一刻"


@dataclass(frozen=True)
class Do:
    """做一个动作几遍。"""

    motion: str
    times: int


@dataclass(frozen=True)
class Hold:
    """一直保持一个动作里的一刻（力矩不变，不动）。"""

    name: str
    motion: str
    moment: Moment
    seconds: float


# 10 分钟的循环（第一批家务：收拾餐桌、整理客厅、垃圾分类、开关和取放、递东西、擦桌子）。剩下的时间站着歇。
CHORE_CYCLE: tuple[Do, ...] = (
    Do("walk", 20),
    Do("walk_slow", 6),
    Do("walk_fast", 3),
    Do("stairs_up", 1),
    Do("stairs_down", 1),
    Do("squat", 8),
    Do("lean", 2),
    Do("lift_box", 1),
    Do("carry_walk", 1),
    Do("shelf", 2),
    Do("pull_door", 4),
    Do("wipe_table", 10),
    Do("push_up_from_knees", 1),
)
# 站着歇：保持"蹲到底再站起"开始的那一刻（站直，顶住重力）。
REST = Hold("站着歇", "squat", Moment.LAST, 0.0)
STRESS_HOLDS: tuple[Hold, ...] = (
    Hold("端着 10 kg 的箱子站着", "lift_box", Moment.LAST, HOLD_S),
    Hold("蹲着干活", "squat", Moment.HARDEST, HOLD_S),
)


@dataclass(frozen=True)
class Motor:
    """一个驱动器：带哪几个关节（关节在 body.joints 里的位置、系数），选的是什么样的。

    一般的驱动器带一个关节，系数 1。并联的一对：甲 = 两个关节一起（+1、+1），乙 = 两个关节反着（+1、-1）。
    驱动器的力矩 = 两个关节力矩之和（或之差）的一半，转速 = 两个关节转速之和（或之差）。
    """

    name: str
    label: str
    group: str
    joints: tuple[tuple[int, float], ...]
    drive: DriveSpec

    def torques_nm(self, joint_torques: np.ndarray) -> np.ndarray:
        """每一帧这个驱动器要出的力矩（不算它自己的摩擦）。joint_torques 是 帧 x 关节。"""
        return sum(joint_torques[:, index] * sign for index, sign in self.joints) / len(self.joints)

    def speeds_rad_s(self, joint_speeds: np.ndarray) -> np.ndarray:
        """每一帧这个驱动器转多快。"""
        return sum(joint_speeds[:, index] * sign for index, sign in self.joints)


def motors_of(body: Body, drives: Mapping[str, Sequence[DriveSpec]]) -> list[Motor]:
    """这个身体（Nova）的每个驱动器。drives 是每组关节（一侧）选好的驱动器（质量闭环的 budget.drives）。"""
    index = {joint.name: position for position, joint in enumerate(body.joints)}
    motors = []
    for group in JOINT_GROUPS:
        if group.key not in drives or group.key not in group_members():
            continue
        dofs = group_members()[group.key]
        for side_joints in zip(*dofs, strict=True):
            if not all(name in index for name in side_joints):
                continue
            motors += _group_motors(group, side_joints, [index[name] for name in side_joints], drives[group.key])
    return motors


def _group_motors(
    group: JointGroup, names: Sequence[str], indexes: Sequence[int], drives: Sequence[DriveSpec]
) -> list[Motor]:
    side = _side_of(names[0])
    where = SIDE_NAMES[side] + " " if side else ""
    if group.parallel:
        return [
            Motor(
                name=f"{names[0]}_{part}",
                label=f"{where}{group.name}（并联{label}）",
                group=group.key,
                joints=((indexes[0], 1.0), (indexes[1], sign)),
                drive=drive,
            )
            for part, (label, sign, drive) in enumerate(zip(PAIR_NAMES, PAIR_SIGNS, drives, strict=True))
        ]
    return [
        Motor(name=name, label=f"{where}{group.name}", group=group.key, joints=((position, 1.0),), drive=drive)
        for name, position, drive in zip(names, indexes, drives, strict=True)
    ]


def _side_of(joint_name: str) -> Side | None:
    for side in Side:
        if joint_name.startswith(side_prefix(side)):
            return side
    return None


# 每一段的热 ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Blocks:
    """一段时间里，每个驱动器每 0.1 秒的力矩的平方的平均（段 x 驱动器），和每一段多长（秒）。"""

    mean_square_nm2: np.ndarray
    seconds: np.ndarray

    @property
    def duration_s(self) -> float:
        """一共多长。"""
        return float(self.seconds.sum())

    def repeated(self, times: int) -> "Blocks":
        """连着做几遍。"""
        return Blocks(np.tile(self.mean_square_nm2, (times, 1)), np.tile(self.seconds, times))


def motion_blocks(series: MotionSeries, motors: Sequence[Motor]) -> Blocks:
    """一个动作做一遍：每个驱动器要出的力矩加上它自己的摩擦，按 0.1 秒一段取平方的平均。"""
    torques = np.column_stack([_with_friction(motor, series) for motor in motors])
    per_block = max(1, round(BLOCK_S / series.dt_s))
    count = math.ceil(len(torques) / per_block)
    squares, seconds = [], []
    for block in range(count):
        part = torques[block * per_block : (block + 1) * per_block]
        squares.append(np.mean(part**2, axis=0))
        seconds.append(len(part) * series.dt_s)
    return Blocks(np.array(squares), np.array(seconds))


def held_blocks(series: MotionSeries, moment: Moment, motors: Sequence[Motor], seconds: float) -> Blocks:
    """一直保持动作里的一刻 seconds 秒：不动，所以没有摩擦。"""
    frame = len(series.torques_nm) - 1 if moment is Moment.LAST else _hardest_frame(series)
    torques = series.torques_nm[frame : frame + 1]
    squares = np.array([[float(motor.torques_nm(torques)[0]) ** 2 for motor in motors]])
    count = max(1, math.ceil(seconds / BLOCK_S))
    return Blocks(np.repeat(squares, count, axis=0), np.full(count, seconds / count))


def _hardest_frame(series: MotionSeries) -> int:
    """全身的力矩的平方加起来最大的那一帧（蹲到底的那一刻）。"""
    return int(np.argmax(np.sum(series.torques_nm**2, axis=1)))


def _with_friction(motor: Motor, series: MotionSeries) -> np.ndarray:
    """驱动器要出的力矩 = 关节要的 + 它自己的摩擦（顺着转的方向挡着）。"""
    speeds = motor.speeds_rad_s(series.speeds_rad_s)
    friction = np.sign(speeds) * motor.drive.friction_nm + motor.drive.viscous_nm_s * speeds
    return motor.torques_nm(series.torques_nm) + friction


def cycle_blocks(cycle: Sequence[Do], demands: Mapping[str, MotionDemand], motors: Sequence[Motor]) -> Blocks:
    """一个循环：按顺序做每一样，剩下的时间站着歇。动作加起来比一个循环还长就报错。"""
    parts = [motion_blocks(_series(demands, step.motion), motors).repeated(step.times) for step in cycle]
    busy = sum(part.duration_s for part in parts)
    if busy > CYCLE_S:
        raise ValueError(f"循环里的动作一共 {busy:.0f} 秒，比一个循环（{CYCLE_S:.0f} 秒）还长")
    parts.append(held_blocks(_series(demands, REST.motion), REST.moment, motors, CYCLE_S - busy))
    return _joined(parts)


def _series(demands: Mapping[str, MotionDemand], key: str) -> MotionSeries:
    demand = demands.get(key)
    if demand is None or demand.series is None:
        raise ValueError(f"动作 {key} 没有算出来（做不出来，或者没有算）")
    return demand.series


def _joined(parts: Sequence[Blocks]) -> Blocks:
    return Blocks(
        np.concatenate([part.mean_square_nm2 for part in parts]),
        np.concatenate([part.seconds for part in parts]),
    )


# 热的网络 -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HeatTrace:
    """算出来的温度：每一段结束时每个驱动器的绕组和身子多热（段 x 驱动器），每一段每个驱动器发的热（瓦）。"""

    times_s: np.ndarray
    winding_c: np.ndarray
    housing_c: np.ndarray
    loss_w: np.ndarray

    @property
    def last_winding_c(self) -> np.ndarray:
        """最后的绕组温度。"""
        return self.winding_c[-1]

    @property
    def last_housing_c(self) -> np.ndarray:
        """最后的身子温度。"""
        return self.housing_c[-1]


def run_heat(
    motors: Sequence[Motor],
    blocks: Blocks,
    winding_c: np.ndarray | None = None,
    housing_c: np.ndarray | None = None,
) -> HeatTrace:
    """一段一段地算温度。开始的温度没给就是冷的（和冷却液一样）。每一段里按小步走（显式积分）。"""
    count = len(motors)
    winding = np.full(count, COOLANT_C) if winding_c is None else winding_c.astype(float).copy()
    housing = np.full(count, COOLANT_C) if housing_c is None else housing_c.astype(float).copy()
    km2 = np.array([motor.drive.km_nm_per_sqrt_w for motor in motors]) ** 2
    to_housing_r = np.array([motor.drive.thermal.winding_to_housing_k_per_w for motor in motors])
    to_coolant_r = np.array([motor.drive.thermal.housing_to_coolant_k_per_w for motor in motors])
    winding_cap = np.array([motor.drive.thermal.winding_j_per_k for motor in motors])
    housing_cap = np.array([motor.drive.thermal.housing_j_per_k for motor in motors])
    shortest = float(np.min(to_housing_r * winding_cap))
    windings, housings, losses = [], [], []
    for squares, seconds in zip(blocks.mean_square_nm2, blocks.seconds, strict=True):
        steps = max(1, math.ceil(seconds / (0.1 * shortest)))
        dt = seconds / steps
        for _ in range(steps):
            loss = squares / km2 * (1.0 + COPPER_TEMPERATURE_COEFFICIENT * (winding - REFERENCE_C))
            flow = (winding - housing) / to_housing_r
            out = (housing - COOLANT_C) / to_coolant_r
            winding = winding + dt * (loss - flow) / winding_cap
            housing = housing + dt * (flow - out) / housing_cap
        windings.append(winding.copy())
        housings.append(housing.copy())
        losses.append(loss)
    return HeatTrace(np.cumsum(blocks.seconds), np.array(windings), np.array(housings), np.array(losses))


def hardest_window_rms_nm(blocks: Blocks, window_s: float = SIZING_WINDOW_S) -> np.ndarray:
    """每个驱动器最费力的 window_s 秒里，力矩的均方根。一共没那么长就取全部。"""
    weighted = np.vstack(
        [np.zeros(blocks.mean_square_nm2.shape[1]), np.cumsum(blocks.mean_square_nm2 * blocks.seconds[:, None], axis=0)]
    )
    times = np.concatenate([[0.0], np.cumsum(blocks.seconds)])
    if times[-1] <= window_s:
        return np.sqrt(weighted[-1] / times[-1])
    ends = np.searchsorted(times, times + window_s)
    valid = ends < len(times)
    starts = np.nonzero(valid)[0]
    sums = weighted[ends[valid]] - weighted[starts]
    spans = (times[ends[valid]] - times[starts])[:, None]
    return np.sqrt(np.max(sums / spans, axis=0))


# 结果 -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MotorHeat:
    """一个驱动器在一轮家务里：最热到多少度、什么时候，降额了多久，平均发多少热，最费力的 5 分钟要多大。"""

    motor: Motor
    hottest_c: float
    hottest_at_s: float
    derating_s: float
    mean_loss_w: float
    hardest_rms_nm: float

    @property
    def continuous_share(self) -> float:
        """最费力的 5 分钟要的，是这个驱动器能一直出的几成。"""
        return self.hardest_rms_nm / self.motor.drive.continuous_torque_nm


@dataclass(frozen=True)
class RoundHeat:
    """一轮家务的热预算。"""

    motors: tuple[MotorHeat, ...]
    cycle: Blocks
    trace: HeatTrace
    busiest_minute_w: float

    @property
    def duration_s(self) -> float:
        """一轮多长。"""
        return float(self.trace.times_s[-1])

    @property
    def mean_loss_w(self) -> float:
        """全身的驱动器平均每秒发多少热。"""
        return float(sum(item.mean_loss_w for item in self.motors))


def chore_round(motors: Sequence[Motor], demands: Mapping[str, MotionDemand], cycles: int = CYCLES) -> RoundHeat:
    """做一轮家务：循环做 cycles 遍，从冷的开始。"""
    cycle = cycle_blocks(CHORE_CYCLE, demands, motors)
    blocks = cycle.repeated(cycles)
    trace = run_heat(motors, blocks)
    hottest = np.argmax(trace.winding_c, axis=0)
    above = (trace.winding_c > DERATE_FROM_C) * blocks.seconds[:, None]
    mean_loss = (trace.loss_w * blocks.seconds[:, None]).sum(axis=0) / blocks.duration_s
    rms = hardest_window_rms_nm(blocks)
    items = tuple(
        MotorHeat(
            motor=motor,
            hottest_c=float(trace.winding_c[hottest[column], column]),
            hottest_at_s=float(trace.times_s[hottest[column]]),
            derating_s=float(above[:, column].sum()),
            mean_loss_w=float(mean_loss[column]),
            hardest_rms_nm=float(rms[column]),
        )
        for column, motor in enumerate(motors)
    )
    return RoundHeat(items, cycle, trace, _busiest_minute_w(trace, blocks))


def _busiest_minute_w(trace: HeatTrace, blocks: Blocks) -> float:
    """全身的驱动器发热最多的那一分钟，平均每秒多少瓦。"""
    total = trace.loss_w.sum(axis=1) * blocks.seconds
    energy = np.concatenate([[0.0], np.cumsum(total)])
    times = np.concatenate([[0.0], trace.times_s])
    ends = np.searchsorted(times, times + SECONDS_PER_MINUTE)
    valid = ends < len(times)
    if not valid.any():
        return float(energy[-1] / times[-1])
    starts = np.nonzero(valid)[0]
    return float(np.max((energy[ends[valid]] - energy[starts]) / (times[ends[valid]] - times[starts])))


@dataclass(frozen=True)
class HeldMotor:
    """一直保持一个姿势时的一个驱动器：开始多热、保持完多热、多久开始降额（不会降额是 None）。"""

    motor: Motor
    start_c: float
    end_c: float
    derate_after_s: float | None
    torque_nm: float


@dataclass(frozen=True)
class HoldHeat:
    """一直保持一个姿势的结果。"""

    hold: Hold
    motors: tuple[HeldMotor, ...]


def hold_after_round(
    hold: Hold, motors: Sequence[Motor], demands: Mapping[str, MotionDemand], after: RoundHeat
) -> HoldHeat:
    """一轮家务做完，接着一直保持这个姿势 hold.seconds 秒。"""
    blocks = held_blocks(_series(demands, hold.motion), hold.moment, motors, hold.seconds)
    trace = run_heat(motors, blocks, after.trace.last_winding_c, after.trace.last_housing_c)
    torques = np.sqrt(blocks.mean_square_nm2[0])
    items = []
    for column, motor in enumerate(motors):
        over = np.nonzero(trace.winding_c[:, column] > DERATE_FROM_C)[0]
        items.append(
            HeldMotor(
                motor=motor,
                start_c=float(after.trace.last_winding_c[column]),
                end_c=float(trace.winding_c[-1, column]),
                derate_after_s=float(trace.times_s[over[0]]) if len(over) else None,
                torque_nm=float(torques[column]),
            )
        )
    return HoldHeat(hold, tuple(items))


def continuous_targets(
    round_heat: RoundHeat, holds: Sequence[HoldHeat], body_mass_kg: float, reference_mass_kg: float
) -> dict[str, tuple[float, ...]]:
    """写进设计的"要一直出的力矩"：每组每个驱动器，一轮家务里最费力的 5 分钟的均方根，
    和一直保持的那几个姿势要的力矩，取大的，x 1.2；左右取大的。

    一直保持的姿势按"能一直出"算（不只是 10 分钟）：开始降额只是峰值变小，能一直出的力矩还在。
    "随体重"的组按参考体重折算（质量闭环再按算出来的体重放大）。
    """
    needs = {item.motor.name: item.hardest_rms_nm for item in round_heat.motors}
    for hold in holds:
        for item in hold.motors:
            needs[item.motor.name] = max(needs[item.motor.name], item.torque_nm)
    groups = {group.key: group for group in JOINT_GROUPS}
    found: dict[str, dict[int, float]] = {}
    for item in round_heat.motors:
        group = groups[item.motor.group]
        position = _position_in_group(item.motor)
        scale = reference_mass_kg / body_mass_kg if group.torque_rule is TorqueRule.BODY_MASS else 1.0
        value = needs[item.motor.name] * CONTINUOUS_MARGIN * scale
        slots = found.setdefault(group.key, {})
        slots[position] = max(slots.get(position, 0.0), value)
    return {key: tuple(slots[position] for position in sorted(slots)) for key, slots in found.items()}


def _position_in_group(motor: Motor) -> int:
    """这个驱动器是组里的第几个：并联的甲、乙是 0、1；别的按关节是第几个自由度。"""
    if len(motor.joints) > 1:
        return int(motor.name.rsplit("_", 1)[1])
    dofs = group_members()[motor.group]
    for position, names in enumerate(dofs):
        if motor.name in names:
            return position
    raise ValueError(f"{motor.name} 不在 {motor.group} 这一组里")
