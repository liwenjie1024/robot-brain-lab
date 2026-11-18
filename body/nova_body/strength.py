"""力量到底要多大（P1 的 1.5 步）：让身体做第一次考试要做的那些动作，从动作反推每个关节要多大的力矩、转多快。

1. 动作一帧一帧写出来（motions），逆动力学算出每一帧每个关节要的力矩和转速（inverse）。
2. 每个关节取能做的核心动作里最大的那一个（力矩、转速都取绝对值）；左右两侧取大的。
3. 再留余地，就是驱动器的目标：力矩 x 1.5，转速 x 1.3。
4. 两个驱动器并联、一起带两个自由度的（踝、腰、腕）：每个驱动器要出的是同一刻两个力矩之和的一半。

跳（运动员级）只拿来比，不算进目标。动作很多、每个都要解几百帧，所以分给几个进程一起算。
"""

import math
import os
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cache

import mujoco
import numpy as np

from nova_body.baseline import load_g1
from nova_body.bench import FLOOR
from nova_body.body import Body, Region
from nova_body.design import JOINT_GROUPS, JointGroup, TorqueRule
from nova_body.inverse import InverseDynamics
from nova_body.model import build_nova
from nova_body.motions import Level, Motion, MotionBuilder
from nova_body.skeleton import LINKS, side_prefix, sides_of

# 余地：动作不会每次都做得这么顺，还有要多出力的时候（被碰一下、脚下打滑、驱动器旧了、天热降额）。
TORQUE_MARGIN = 1.5
SPEED_MARGIN = 1.3
# 质量闭环里"随体重"的那些关节，力矩是按这个体重写的。
REFERENCE_BODY_MASS_KG = 70.0
# 最多同时用这么多个进程（每个进程要自己生成一个身体，占几百 MB 内存）。
MAX_WORKERS = 12
NOVA, G1 = "nova", "g1"


class Uses(StrEnum):
    """这个动作要用到身体的哪些地方：身体的描述里没有的就不做。"""

    LEGS = "腿和身体"
    HANDS = "手"
    KNEES = "膝盖和手"


@dataclass(frozen=True)
class MotionEntry:
    """要做的一个动作：名字、说明、要用到什么，和怎么写出它。"""

    key: str
    name: str
    description: str
    uses: Uses
    build: Callable[[MotionBuilder, "MotionEntry"], Motion]


def _walk(speed_m_s: float) -> Callable[[MotionBuilder, MotionEntry], Motion]:
    return lambda builder, entry: builder.walk(entry.key, entry.name, speed_m_s, entry.description)


MOTIONS: tuple[MotionEntry, ...] = (
    MotionEntry("walk_slow", "慢走", "0.5 m/s，直着走 6 步", Uses.LEGS, _walk(0.5)),
    MotionEntry("walk", "走", "0.8 m/s，平常走路的速度", Uses.LEGS, _walk(0.8)),
    MotionEntry("walk_fast", "快走", "1.1 m/s", Uses.LEGS, _walk(1.1)),
    MotionEntry(
        "stairs_up",
        "上楼",
        "套内楼梯：一级高 20 cm、踏面 22 cm（住宅标准里最陡的），上 4 级",
        Uses.LEGS,
        lambda builder, entry: builder.stairs(entry.key, entry.name, up=True, description=entry.description),
    ),
    MotionEntry(
        "stairs_down",
        "下楼",
        "同样的楼梯，下 4 级",
        Uses.LEGS,
        lambda builder, entry: builder.stairs(entry.key, entry.name, up=False, description=entry.description),
    ),
    MotionEntry(
        "squat",
        "蹲到底再站起",
        "重心降到站着时的一半，脚跟不离地",
        Uses.LEGS,
        lambda builder, entry: builder.squat(entry.key, entry.name, entry.description),
    ),
    MotionEntry(
        "lean",
        "前倾、后仰",
        "脚不动，重心挪到离脚尖、脚跟 3 cm 的地方再回来",
        Uses.LEGS,
        lambda builder, entry: builder.lean(entry.key, entry.name, entry.description),
    ),
    MotionEntry(
        "lift_box",
        "从地上搬箱子",
        "10 kg 的箱子，把手离地 20 cm，搬起来端在身前",
        Uses.HANDS,
        lambda builder, entry: builder.lift_box(entry.key, entry.name, entry.description),
    ),
    MotionEntry(
        "carry_walk",
        "端着箱子走",
        "端着 10 kg 的箱子，0.8 m/s",
        Uses.HANDS,
        lambda builder, entry: builder.carry_walk(entry.key, entry.name, entry.description),
    ),
    MotionEntry(
        "shelf",
        "放到柜子上",
        "5 kg 的东西从身前举到 1.8 m 高",
        Uses.HANDS,
        lambda builder, entry: builder.shelf(entry.key, entry.name, entry.description),
    ),
    MotionEntry(
        "pull_door",
        "拉门",
        "右手抓住 1 m 高的门把手，用 50 N 拉开 30 cm",
        Uses.HANDS,
        lambda builder, entry: builder.pull_door(entry.key, entry.name, entry.description),
    ),
    MotionEntry(
        "wipe_table",
        "擦桌子",
        "右手在 75 cm 高的桌上来回擦 3 下，往下压 20 N",
        Uses.HANDS,
        lambda builder, entry: builder.wipe_table(entry.key, entry.name, entry.description),
    ),
    MotionEntry(
        "push_up_from_knees",
        "跪着撑起来",
        "跪着、两手撑地，身体沉下 12 cm 再撑起来",
        Uses.KNEES,
        lambda builder, entry: builder.push_up_from_knees(
            entry.key, entry.name, entry.description, builder.all_fours()
        ),
    ),
    MotionEntry(
        "jump",
        "原地跳",
        "跳起 25 cm（运动员级，只拿来比，不算进目标）",
        Uses.LEGS,
        lambda builder, entry: builder.jump(entry.key, entry.name, entry.description),
    ),
)


def motion_entry(key: str) -> MotionEntry:
    """按名字找一个动作。"""
    for entry in MOTIONS:
        if entry.key == key:
            return entry
    raise KeyError(f"没有叫 {key} 的动作")


def can_do(builder: MotionBuilder, entry: MotionEntry) -> bool:
    """这个身体有没有这个动作要用到的地方（手心、膝盖的点）。"""
    if entry.uses is Uses.HANDS:
        return builder.has_hands
    if entry.uses is Uses.KNEES:
        return builder.has_hands and builder.can_kneel
    return True


@dataclass(frozen=True)
class MotionSeries:
    """一个动作每一帧每个关节的力矩和转速（带正负，顺序和 body.joints 一样）。热的预算要用。"""

    dt_s: float
    torques_nm: np.ndarray
    speeds_rad_s: np.ndarray

    @property
    def duration_s(self) -> float:
        """这一段有多长。"""
        return self.dt_s * len(self.torques_nm)


@dataclass(frozen=True)
class MotionDemand:
    """一个动作量出来的要求，只留下算目标、写报告用得着的数。顺序和 body.joints 一样。

    做不出来的动作（feasible 是 False）不算逆动力学，力矩、转速都是 nan。
    shared_nm 是并联的每一对关节（按关节的名字）：同一刻两个力矩的绝对值之和的一半，最大是多少。
    edge_margin_m：脚底的压力中心离边最近的时候还有多远；friction_ratio：要的摩擦最大是多少（地面按 0.6 算）。
    series 是每一帧的力矩和转速（做不出来的动作是 None）。
    self_contacts_m 是动作里身体的哪两段插到了一起、最深插进去多少米（逆运动学还不躲开自己）。
    """

    key: str
    name: str
    description: str
    level: Level
    feasible: bool
    duration_s: float
    reach_error_m: float
    balance_error_m: float
    torques_nm: np.ndarray
    torque_times_s: np.ndarray
    speeds_rad_s: np.ndarray
    shared_nm: dict[tuple[str, str], float]
    edge_margin_m: float
    friction_ratio: float
    unbalanced_n: float
    series: MotionSeries | None = None
    self_contacts_m: dict[tuple[str, str], float] = field(default_factory=dict)


def measure_motion(body: Body, builder: MotionBuilder, entry: MotionEntry) -> MotionDemand:
    """写出一个动作，做得出来的话再算每个关节要的力矩和转速。"""
    motion = entry.build(builder, entry)
    count = len(body.joints)
    nan = np.full(count, np.nan)
    common = {
        "key": entry.key,
        "name": entry.name,
        "description": entry.description,
        "level": motion.level,
        "feasible": motion.feasible,
        "duration_s": motion.duration_s,
        "reach_error_m": motion.reach_error_m,
        "balance_error_m": motion.balance_error_m,
    }
    if not motion.feasible:
        return MotionDemand(
            **common,
            torques_nm=nan,
            torque_times_s=nan,
            speeds_rad_s=nan,
            shared_nm={},
            edge_margin_m=math.nan,
            friction_ratio=math.nan,
            unbalanced_n=math.nan,
        )
    demand = InverseDynamics(body).demand(motion.frames, motion.dt, ends_at_rest=motion.ends_at_rest)
    torques = np.abs(demand.torques)
    names = [joint.name for joint in body.joints]
    shared = {
        pair: float(np.max(torques[:, names.index(pair[0])] + torques[:, names.index(pair[1])]) / 2)
        for pair in parallel_pairs(body)
    }
    return MotionDemand(
        **common,
        torques_nm=torques.max(axis=0),
        torque_times_s=demand.times[torques.argmax(axis=0)],
        speeds_rad_s=np.abs(demand.speeds).max(axis=0),
        shared_nm=shared,
        edge_margin_m=demand.worst_edge_margin_m(),
        friction_ratio=demand.worst_friction_ratio(),
        unbalanced_n=float(demand.unbalanced_n.max()),
        series=MotionSeries(motion.dt, demand.torques, demand.speeds),
        self_contacts_m=self_contacts(body, [frame.qpos for frame in motion.frames]),
    )


def self_contacts(body: Body, poses: Iterable[np.ndarray]) -> dict[tuple[str, str], float]:
    """这些姿势里，身体的哪两段碰在一起、最深插进去多少米（不算和地面的，按身体的名字排好）。"""
    model = body.model
    data = mujoco.MjData(model)
    floor = model.geom(FLOOR).id
    deepest: dict[tuple[str, str], float] = {}
    for qpos in poses:
        data.qpos[:] = qpos
        mujoco.mj_forward(model, data)
        for index in range(data.ncon):
            contact = data.contact[index]
            if floor in (int(contact.geom[0]), int(contact.geom[1])):
                continue
            pair = tuple(sorted(model.body(model.geom_bodyid[geom]).name for geom in contact.geom[:2]))
            deepest[pair] = max(deepest.get(pair, 0.0), -float(contact.dist))
    return {pair: depth for pair, depth in deepest.items() if depth > 0.0}


@dataclass(frozen=True)
class Task:
    """分给一个进程算的一件事：哪个身体（Nova 可以换关节的范围）、哪个动作。"""

    body: str
    motion: str
    joint_ranges_deg: tuple[tuple[str, float, float], ...] = ()


def run_tasks(tasks: Iterable[Task], workers: int | None = None) -> list[MotionDemand]:
    """一起算很多个动作。结果的顺序和 tasks 一样。"""
    tasks = list(tasks)
    workers = workers or min(MAX_WORKERS, os.cpu_count() or 1, len(tasks))
    if workers <= 1:
        return [_run(task) for task in tasks]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_run, tasks))


def _run(task: Task) -> MotionDemand:
    body, builder = _prepared(task.body, task.joint_ranges_deg)
    return measure_motion(body, builder, motion_entry(task.motion))


@cache
def _prepared(name: str, joint_ranges_deg: tuple[tuple[str, float, float], ...]) -> tuple[Body, MotionBuilder]:
    """每个进程里每个身体只生成一次。"""
    if name == NOVA:
        ranges = {key: (lower, upper) for key, lower, upper in joint_ranges_deg}
        body = build_nova(joint_ranges_deg=ranges).body
    elif name == G1:
        body = load_g1()
    else:
        raise ValueError(f"不认识的身体：{name}")
    return body, MotionBuilder(body)


def tasks_for(body: Body, name: str, joint_ranges_deg: tuple[tuple[str, float, float], ...] = ()) -> list[Task]:
    """这个身体能做的全部动作。"""
    builder = MotionBuilder(body)
    return [Task(name, entry.key, joint_ranges_deg) for entry in MOTIONS if can_do(builder, entry)]


# 汇总 -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class JointNeed:
    """一个关节在能做的核心动作里最多要多大的力矩、多快，在哪个动作里。"""

    name: str
    label: str
    torque_nm: float
    torque_motion: str
    speed_rad_s: float
    speed_motion: str


def joint_needs(body: Body, demands: list[MotionDemand]) -> list[JointNeed]:
    """每个有驱动器的关节（不算手指）：取能做的核心动作里最大的那个。"""
    counted = [demand for demand in demands if demand.feasible and demand.level is Level.CORE]
    if not counted:
        raise ValueError("没有一个能做的核心动作")
    needs = []
    for index, joint in enumerate(body.joints):
        if joint.region is Region.HAND:
            continue
        torque = max(counted, key=lambda demand: demand.torques_nm[index])
        speed = max(counted, key=lambda demand: demand.speeds_rad_s[index])
        needs.append(
            JointNeed(
                name=joint.name,
                label=joint.label,
                torque_nm=float(torque.torques_nm[index]),
                torque_motion=torque.name,
                speed_rad_s=float(speed.speeds_rad_s[index]),
                speed_motion=speed.name,
            )
        )
    return needs


@dataclass(frozen=True)
class GroupTarget:
    """设计里的一组关节（一侧的）：每个自由度在动作里最多要多少、留了余地以后的目标。

    torques_nm、speeds_rad_s 是这个身体（体重 body_mass_kg）做动作时要的，左右取大的。
    daily_torques_nm 是写进设计的目标：留了余地；"随体重"的组按 70 kg 折算（质量闭环再按算出来的体重放大）。
    shared_nm 是并联的一组里每个驱动器要的（同一刻两个力矩之和的一半，留了余地，按同样的办法折算）；不是并联的是 None。
    """

    group: JointGroup
    torques_nm: tuple[float, ...]
    torque_motions: tuple[str, ...]
    speeds_rad_s: tuple[float, ...]
    speed_motions: tuple[str, ...]
    daily_torques_nm: tuple[float, ...]
    speed_targets_rad_s: tuple[float, ...]
    shared_nm: float | None


def group_targets(needs: list[JointNeed], demands: list[MotionDemand], body_mass_kg: float) -> list[GroupTarget]:
    """按设计里的关节组汇总 Nova 的需要。核心版没有的关节（没有动作的数）不列。"""
    by_name = {need.name: need for need in needs}
    members = group_members()
    targets = []
    for group in JOINT_GROUPS:
        dofs = members.get(group.key)
        if not dofs or any(name not in by_name for names in dofs for name in names):
            continue
        worst = [max((by_name[name] for name in names), key=lambda need: need.torque_nm) for names in dofs]
        fastest = [max((by_name[name] for name in names), key=lambda need: need.speed_rad_s) for names in dofs]
        scale = REFERENCE_BODY_MASS_KG / body_mass_kg if group.torque_rule is TorqueRule.BODY_MASS else 1.0
        shared = None
        if group.parallel:
            pairs = list(zip(dofs[0], dofs[1], strict=True))
            needed = max(
                (demand.shared_nm.get(pair, 0.0) for demand in demands if _counts(demand) for pair in pairs),
                default=0.0,
            )
            shared = needed * TORQUE_MARGIN * scale
        targets.append(
            GroupTarget(
                group=group,
                torques_nm=tuple(need.torque_nm for need in worst),
                torque_motions=tuple(need.torque_motion for need in worst),
                speeds_rad_s=tuple(need.speed_rad_s for need in fastest),
                speed_motions=tuple(need.speed_motion for need in fastest),
                daily_torques_nm=tuple(need.torque_nm * TORQUE_MARGIN * scale for need in worst),
                speed_targets_rad_s=tuple(need.speed_rad_s * SPEED_MARGIN for need in fastest),
                shared_nm=shared,
            )
        )
    return targets


def parallel_pairs(body: Body) -> list[tuple[str, str]]:
    """这个身体里并联的每一对关节（按设计里的组，左右各一对）。不是 Nova 的身体没有。"""
    names = {joint.name for joint in body.joints}
    pairs = []
    for group in JOINT_GROUPS:
        dofs = group_members().get(group.key)
        if group.parallel and dofs:
            pairs += [pair for pair in zip(dofs[0], dofs[1], strict=True) if set(pair) <= names]
    return pairs


def _counts(demand: MotionDemand) -> bool:
    return demand.feasible and demand.level is Level.CORE


@cache
def group_members() -> dict[str, tuple[tuple[str, ...], ...]]:
    """设计里每组关节的每个自由度，对应模型里哪几个关节（左右两侧各一个，中间的一个）。"""
    found: dict[str, dict[int, list[str]]] = {}
    for part in LINKS:
        for side in sides_of(part):
            for joint in part.joints:
                found.setdefault(joint.group, {}).setdefault(joint.index, []).append(side_prefix(side) + joint.key)
    return {group: tuple(tuple(indexes[index]) for index in sorted(indexes)) for group, indexes in found.items()}
