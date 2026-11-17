"""逆动力学：一个动作（每一帧的姿势）做出来，每个关节要出多大的力矩、转多快。

做法：
1. 用相邻的几帧算出每个自由度的速度和加速度。
2. MuJoCo 的逆动力学算出"要让身体这样动，每个自由度上一共要多大的力"。
3. 骨盆上的那 6 个（往哪边推、往哪边转）关节出不了，只能由地面（还有手、膝盖撑着的地方）给。
   把这份力分给这一帧撑着身体的地方：在满足的分法里，选力最小、压力中心最靠中间的那一种。
   撑着的地方只能推、不能拉；算出来要拉的那一处就当它离开了地面，再分一遍。
4. 剩下的就是每个关节的驱动器要出的力矩。

同时检查这个动作能不能真的做：每只脚的压力中心在不在脚底里面，要不要比地面能给的摩擦更大的力。
"""

import copy
import math
from dataclasses import dataclass, field
from enum import StrEnum

import mujoco
import numpy as np

from nova_body.body import Body

GRAVITY: np.ndarray = np.array([0.0, 0.0, -9.81])
FREE_JOINT_DOF = 6
FORCE, MOMENT = 3, 3
WRENCH = FORCE + MOMENT
UP = 2
# 分力的时候：力矩按"力 x 这么长的力臂"算代价，所以脚上的力矩越大越不划算，压力中心就落在中间。
MOMENT_ARM_M = 0.05
# 沿着地面的力比压在地面上的力贵这么多倍：能不用摩擦就不用。
TANGENTIAL_COST = 4.0
# 地面的摩擦系数按这个检查（比仿真里的地面保守）。
FRICTION = 0.6
# 撑着的地方要被压着（法向的力大于这个才算撑着）。
MIN_PRESSING_N = 1.0e-6
# 骨盆上的力分不出去（谁也没撑着）时，剩下的力大于这个就算这一帧做不出来。
UNBALANCED_TOLERANCE = 1.0e-3
# 压力中心跑出脚底时，这只脚的力矩每一轮贵这么多倍，最多试这么多轮；至少要两处撑着才有得分。
REWEIGHT_FACTOR = 10.0
MAX_REWEIGHT_ROUNDS = 6
MIN_SHARED_SUPPORTS = 2
# 算速度和加速度至少要这么多帧。
MIN_FRAMES = 2
# 检查压力中心和摩擦时，只看撑着这一帧这么多重量以上的地方。
LOADED_SHARE = 0.1
# 算加速度以前，帧和帧之间的速度先用这么宽（秒）的高斯平滑一下，约等于 6 Hz 的低通：量人的动作再算关节力矩时
# 也这样滤（人的动作里几乎没有比这更快的成分）。不滤的话，逆运动学里一点点的折角（某个关节刚好转到头）
# 会算出假的大加速度和力矩。高斯两边各取这么多倍的宽度。
SMOOTHING_S = 0.025
SMOOTHING_REACH = 3


class SupportKind(StrEnum):
    """撑着身体的地方是哪一种。"""

    FOOT = "foot"
    POINT = "point"


@dataclass(frozen=True)
class Support:
    """一处撑着身体的地方：模型里的一个点（site）压在一个朝上的平面上。

    FOOT 是一块脚底：能给力，也能给力矩（压力中心在脚底里面挪），
    half_length、half_width 是踩着的那一块的一半长、一半宽，沿着这个点自己的 x、y 轴。
    offset_m 是踩着的那一块的中间在这个点前面多远
    （台阶比脚短、只踩着一部分，或者脚跟抬起来只用脚掌前面撑着的时候不是 0）。
    POINT 是一个点（膝盖、手心、脚尖）：只能给力。
    """

    label: str
    site: str
    kind: SupportKind
    half_length: float = 0.0
    half_width: float = 0.0
    offset_m: float = 0.0


@dataclass(frozen=True)
class CarriedLoad:
    """手里拿着的东西：重量和它跟着手动起来要的力，都压在这个点上。"""

    site: str
    mass_kg: float


@dataclass(frozen=True)
class PushingForce:
    """外面给这个点的力（世界坐标，牛顿），比如门往前拉着手。"""

    site: str
    force_n: np.ndarray


@dataclass(frozen=True)
class Frame:
    """动作的一帧：姿势、这一帧撑着身体的地方、外面加的力。"""

    qpos: np.ndarray
    supports: tuple[Support, ...]
    loads: tuple[CarriedLoad | PushingForce, ...] = ()


@dataclass(frozen=True)
class SupportForce:
    """一处撑着的地方这一帧受的力（世界坐标）和压力中心离边还有多远（米，负的是在外面；点是 nan）。"""

    label: str
    force_n: np.ndarray
    moment_nm: np.ndarray
    edge_margin_m: float
    friction_ratio: float


@dataclass(frozen=True)
class Demand:
    """一个动作要的力。torques、speeds 是每一帧 x 每个驱动的关节（顺序和 body.joints 一样）。

    support_forces 是每一帧每处撑着的地方受的力。lifted 是撑着、却要被地面拉住的地方（当它离开了地面）。
    unbalanced_n 是每一帧分不出去的力（大于 0 就是这一帧做不出来：没有地方撑着，或者撑着的地方给不了）。
    """

    times: np.ndarray
    torques: np.ndarray
    speeds: np.ndarray
    support_forces: list[list[SupportForce]]
    unbalanced_n: np.ndarray
    lifted: list[list[str]] = field(default_factory=list)

    def worst_edge_margin_m(self) -> float:
        """整个动作里，压力中心离脚底的边最近的时候还有多远（负的是跑到了外面）。只看撑着一成以上重量的脚。"""
        margins = [force.edge_margin_m for force in self._loaded()]
        margins = [margin for margin in margins if not np.isnan(margin)]
        return min(margins, default=float("nan"))

    def worst_friction_ratio(self) -> float:
        """整个动作里，要多大的摩擦系数才不滑：每一帧沿地面的力合起来和压着地面的力合起来之比，取最大的。

        沿地面的力按压着的力的比例分给各处撑着的地方时，每一处的比都是这个数，所以这是最少要的摩擦。
        （分力时没有这样分，单看某一只几乎没压着的脚，比值会大得没有意义。）
        """
        ratios = []
        for frame in self.support_forces:
            pressing = sum(float(force.force_n[UP]) for force in frame)
            sliding = np.hypot(*sum((force.force_n[:UP] for force in frame), np.zeros(UP)))
            if pressing > MIN_PRESSING_N:
                ratios.append(float(sliding) / pressing)
        return max(ratios, default=0.0)

    def _loaded(self) -> list[SupportForce]:
        """每一帧里撑着一成以上重量的地方（几乎没压着的地方，比值、离边多远都没有意义）。"""
        loaded = []
        for frame in self.support_forces:
            total = sum(max(float(force.force_n[UP]), 0.0) for force in frame)
            loaded += [force for force in frame if force.force_n[UP] >= LOADED_SHARE * total]
        return loaded


class InverseDynamics:
    """一个身体的逆动力学。"""

    def __init__(self, body: Body) -> None:
        # 自己用一份模型，把接触、关节限位、联动都关掉：这些力由这里自己算，不让 MuJoCo 再算一遍。
        self.model = _without_constraints(body.model)
        self.data = mujoco.MjData(self.model)
        model = self.model
        self.root = model.body(body.anatomy.root).id
        root_joint = int(model.body_jntadr[self.root])
        self.root_dofs = slice(int(model.jnt_dofadr[root_joint]), int(model.jnt_dofadr[root_joint]) + FREE_JOINT_DOF)
        self.joint_dofs = np.array([int(model.joint(joint.name).dofadr[0]) for joint in body.joints])
        # 跟着别的关节动的关节（手指的远指间）：它要的力矩由带着它的那个关节出。
        self.followers = [
            (
                int(model.jnt_dofadr[model.eq_obj1id[index]]),
                int(model.jnt_dofadr[model.eq_obj2id[index]]),
                float(model.eq_data[index, 1]),
            )
            for index in range(model.neq)
            if model.eq_type[index] == mujoco.mjtEq.mjEQ_JOINT
        ]
        self._jacp = np.zeros((FORCE, model.nv))
        self._jacr = np.zeros((MOMENT, model.nv))

    def demand(self, frames: list[Frame], dt: float, *, ends_at_rest: bool = True) -> Demand:
        """整个动作每一帧要的力矩和速度。动作开头时是停着的；ends_at_rest 是结尾时也停着（跳就不是）。"""
        if len(frames) < MIN_FRAMES:
            raise ValueError(f"一个动作至少要 {MIN_FRAMES} 帧")
        if dt <= 0:
            raise ValueError(f"每一帧的时间必须大于 0，收到的是 {dt}")
        velocities, accelerations = self._finite_differences(
            [frame.qpos for frame in frames], dt, ends_at_rest=ends_at_rest
        )
        site_accelerations = self._site_accelerations(frames, dt)
        torques, speeds, forces, lifted, unbalanced = [], [], [], [], []
        for index, frame in enumerate(frames):
            result = self._frame(frame, velocities[index], accelerations[index], site_accelerations[index])
            torques.append(result[0])
            speeds.append(velocities[index][self.joint_dofs])
            forces.append(result[1])
            lifted.append(result[2])
            unbalanced.append(result[3])
        return Demand(
            times=np.arange(len(frames)) * dt,
            torques=np.array(torques),
            speeds=np.array(speeds),
            support_forces=forces,
            unbalanced_n=np.array(unbalanced),
            lifted=lifted,
        )

    def required_wrench(
        self, frame: Frame, velocity: np.ndarray, acceleration: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """要外面（地面等）一共给多大的力和多大的力矩（绕世界的原点），身体才会这样动。手里的东西不算在里面。"""
        base = self._generalized_need(frame, velocity, acceleration, {})[self.root_dofs]
        mapping = self._root_wrench_map()
        wrench = np.linalg.solve(mapping, base)
        return wrench[:FORCE], wrench[FORCE:]

    def zero_moment_points(self, frames: list[Frame], dt: float, heights: np.ndarray) -> np.ndarray:
        """每一帧的压力中心该在哪（x、y）：外面要给的力和力矩合起来，作用在高度为 heights 的平面上的那一点。

        这只看身体怎么动，不管脚踩在哪：用来检查、修正走路的计划。没有往上托的力时是 nan。
        """
        velocities, accelerations = self._finite_differences([frame.qpos for frame in frames], dt)
        site_accelerations = self._site_accelerations(frames, dt)
        points = np.full((len(frames), 2), np.nan)
        for index, frame in enumerate(frames):
            need = self._generalized_need(frame, velocities[index], accelerations[index], site_accelerations[index])
            # 这张表跟着骨盆在哪变，每一帧都要重新算。
            wrench = np.linalg.solve(self._root_wrench_map(), need[self.root_dofs])
            points[index] = zero_moment_point(wrench[:FORCE], wrench[FORCE:], float(heights[index]))
        return points

    # 一帧 -------------------------------------------------------------------------------------------

    def _frame(self, frame: Frame, velocity, acceleration, site_acceleration):
        need = self._generalized_need(frame, velocity, acceleration, site_acceleration)
        active = list(frame.supports)
        lifted: list[str] = []
        dearer: dict[str, float] = {}
        rounds = 0
        while True:
            maps = [self._support_map(support) for support in active]
            wrenches, unbalanced = self._distribute(need[self.root_dofs], maps, active, dearer)
            pulling = [(wrench[UP], index) for index, wrench in enumerate(wrenches) if wrench[UP] < -MIN_PRESSING_N]
            if pulling:
                lifted.append(active.pop(min(pulling)[1]).label)
                continue
            # 压力中心跑出了哪只脚底、别的地方还能帮着撑：让这只脚的力矩更"贵"，把力多分给别处，再分一遍。
            outside = [
                support.label
                for support, wrench in zip(active, wrenches, strict=True)
                if self._support_force(support, wrench).edge_margin_m < 0
            ]
            if not outside or len(active) < MIN_SHARED_SUPPORTS or rounds >= MAX_REWEIGHT_ROUNDS:
                break
            for label in outside:
                dearer[label] = dearer.get(label, 1.0) * REWEIGHT_FACTOR
            rounds += 1
        joints_need = need.copy()
        for mapping, wrench in zip(maps, wrenches, strict=True):
            joints_need -= mapping @ wrench
        for follower, leader, ratio in self.followers:
            joints_need[leader] += ratio * joints_need[follower]
        forces = [self._support_force(support, wrench) for support, wrench in zip(active, wrenches, strict=True)]
        return joints_need[self.joint_dofs], forces, lifted, unbalanced

    def _generalized_need(self, frame: Frame, velocity, acceleration, site_acceleration) -> np.ndarray:
        """每个自由度上一共要多大的力，减掉手里的东西和外面推的力帮的（或拖的）那一份。"""
        model, data = self.model, self.data
        data.qpos[:] = frame.qpos
        data.qvel[:] = velocity
        data.qacc[:] = acceleration
        mujoco.mj_inverse(model, data)
        need = data.qfrc_inverse.copy()
        applied = np.zeros(model.nv)
        for load in frame.loads:
            site = model.site(load.site).id
            if isinstance(load, CarriedLoad):
                acceleration_here = site_acceleration.get(load.site, np.zeros(3))
                force = load.mass_kg * (GRAVITY - acceleration_here)
            else:
                force = load.force_n
            mujoco.mj_applyFT(
                model, data, force, np.zeros(3), data.site_xpos[site], int(model.site_bodyid[site]), applied
            )
        return need - applied

    def _support_map(self, support: Support) -> np.ndarray:
        """这处撑着的地方受的力（和力矩）落到每个自由度上是多少：一个 nv x 3（或 6）的矩阵。"""
        model, data = self.model, self.data
        site = model.site(support.site).id
        point = data.site_xpos[site] + data.site_xmat[site].reshape(3, 3)[:, 0] * support.offset_m
        mujoco.mj_jac(model, data, self._jacp, self._jacr, point, int(model.site_bodyid[site]))
        if support.kind is SupportKind.POINT:
            return self._jacp.T.copy()
        return np.hstack([self._jacp.T, self._jacr.T])

    def _distribute(
        self, base_need: np.ndarray, maps: list[np.ndarray], supports: list[Support], dearer: dict[str, float]
    ):
        """把骨盆上的 6 个力分给撑着的地方：满足平衡的分法里，代价（力的大小、沿地面的力、力矩）最小的一种。"""
        if not supports:
            return [], float(np.linalg.norm(base_need))
        blocks = [mapping[self.root_dofs] for mapping in maps]
        matrix = np.hstack(blocks)
        costs = np.concatenate([_cost(support, dearer.get(support.label, 1.0)) for support in supports])
        # 加权最小范数：x = C⁻¹ Aᵀ (A C⁻¹ Aᵀ)⁺ b。
        scaled = matrix / costs
        solution = scaled.T @ np.linalg.pinv(matrix @ scaled.T) @ base_need
        unbalanced = float(np.linalg.norm(matrix @ solution - base_need))
        wrenches, start = [], 0
        for block in blocks:
            wrenches.append(solution[start : start + block.shape[1]])
            start += block.shape[1]
        return wrenches, unbalanced if unbalanced > UNBALANCED_TOLERANCE else 0.0

    def _support_force(self, support: Support, wrench: np.ndarray) -> SupportForce:
        force = wrench[:FORCE]
        moment = wrench[FORCE:] if support.kind is SupportKind.FOOT else np.zeros(MOMENT)
        pressing = float(force[UP])
        sliding = float(np.hypot(force[0], force[1]))
        friction_ratio = sliding / pressing if pressing > MIN_PRESSING_N else 0.0
        margin = float("nan")
        if support.kind is SupportKind.FOOT and pressing > MIN_PRESSING_N:
            site = self.model.site(support.site).id
            local = self.data.site_xmat[site].reshape(3, 3).T @ moment
            forward, left = -local[1] / pressing, local[0] / pressing
            margin = min(support.half_length - abs(forward), support.half_width - abs(left))
        return SupportForce(support.label, force.copy(), moment.copy(), margin, friction_ratio)

    def _root_wrench_map(self) -> np.ndarray:
        """在世界的原点加一个力（或力矩），骨盆的 6 个自由度上各是多少：6 x 6 的矩阵。"""
        model, data = self.model, self.data
        mapping = np.zeros((WRENCH, WRENCH))
        for column in range(WRENCH):
            unit = np.zeros(WRENCH)
            unit[column] = 1.0
            generalized = np.zeros(model.nv)
            mujoco.mj_applyFT(model, data, unit[:FORCE], unit[FORCE:], np.zeros(3), self.root, generalized)
            mapping[:, column] = generalized[self.root_dofs]
        return mapping

    # 速度和加速度 -----------------------------------------------------------------------------------

    def _finite_differences(
        self, positions: list[np.ndarray], dt: float, *, ends_at_rest: bool = True
    ) -> tuple[np.ndarray, np.ndarray]:
        """用相邻的帧算速度和加速度。帧和帧之间的速度先低通滤一下，取平均当这一帧的速度；开头当它是停着的。

        ends_at_rest 是结尾也停着；不是的话，最后一帧以后按最后的速度接着动（加速度不突然变成别的）。
        """
        model = self.model
        between = np.zeros((len(positions) - 1, model.nv))
        for index in range(len(positions) - 1):
            mujoco.mj_differentiatePos(model, between[index], dt, positions[index], positions[index + 1])
        kernel = _gaussian_kernel(SMOOTHING_S / dt)
        half = len(kernel) // 2
        after = np.zeros(model.nv) if ends_at_rest else between[-1]
        # 前后各补上停着（或者接着动）的那几帧，再滤：开头、结尾的速度也是平滑地变到 0。
        padded = np.vstack([np.zeros((half + 1, model.nv)), between, np.tile(after, (half + 1, 1))])
        smoothed = np.stack([np.convolve(column, kernel, mode="valid") for column in padded.T], axis=1)
        velocities = (smoothed[:-1] + smoothed[1:]) / 2
        accelerations = (smoothed[1:] - smoothed[:-1]) / dt
        return velocities, accelerations

    def _site_accelerations(self, frames: list[Frame], dt: float) -> list[dict[str, np.ndarray]]:
        """手里拿着东西的那些点，每一帧的加速度（世界坐标）。"""
        sites = sorted({load.site for frame in frames for load in frame.loads if isinstance(load, CarriedLoad)})
        if not sites:
            return [{} for _ in frames]
        model, data = self.model, self.data
        ids = [model.site(site).id for site in sites]
        positions = np.zeros((len(frames), len(sites), 3))
        for index, frame in enumerate(frames):
            data.qpos[:] = frame.qpos
            mujoco.mj_kinematics(model, data)
            positions[index] = data.site_xpos[ids]
        padded = np.concatenate([positions[:1], positions, positions[-1:]])
        accelerations = (padded[2:] - 2 * padded[1:-1] + padded[:-2]) / dt**2
        return [dict(zip(sites, accelerations[index], strict=True)) for index in range(len(frames))]


def zero_moment_point(force: np.ndarray, moment: np.ndarray, height: float) -> np.ndarray:
    """外面给的力 force 和绕世界原点的力矩 moment，合起来作用在高度为 height 的平面上的哪一点（x、y）。

    在这一点上，水平方向的力矩是 0。往上托的力不大于 0 时没有这一点（nan）。
    """
    pressing = float(force[UP])
    if pressing <= MIN_PRESSING_N:
        return np.full(2, np.nan)
    return np.array([(height * force[0] - moment[1]) / pressing, (moment[0] + height * force[1]) / pressing])


def _gaussian_kernel(width_frames: float) -> np.ndarray:
    """宽度（一个标准差）是 width_frames 帧的高斯，两边各取 SMOOTHING_REACH 倍，加起来是 1。"""
    half = max(1, math.ceil(SMOOTHING_REACH * width_frames))
    offsets = np.arange(-half, half + 1)
    weights = np.exp(-0.5 * (offsets / max(width_frames, 1e-9)) ** 2)
    return weights / weights.sum()


def _without_constraints(model: mujoco.MjModel) -> mujoco.MjModel:
    """同一个模型，但不算接触、关节限位和联动。"""
    copied = copy.copy(model)
    copied.opt.disableflags |= mujoco.mjtDisableBit.mjDSBL_CONSTRAINT
    return copied


def _cost(support: Support, moment_factor: float = 1.0) -> np.ndarray:
    """每个力分量的代价：压着地面的力 1，沿着地面的贵一些；脚底的力矩按力臂折算，再乘上 moment_factor。"""
    force = np.array([TANGENTIAL_COST, TANGENTIAL_COST, 1.0])
    if support.kind is SupportKind.POINT:
        return force
    return np.concatenate([force, np.full(MOMENT, moment_factor / MOMENT_ARM_M**2)])
