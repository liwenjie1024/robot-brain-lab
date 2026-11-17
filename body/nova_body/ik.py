"""全身的逆运动学：说出脚、手、膝盖、重心、躯干要在哪里，算出全身每个关节的角度。

对哪个身体都一样：只用模型里的点（site）、身体的名字，和 MuJoCo 算的雅可比矩阵。
做法是加了权重的最小二乘，一步步逼近：要求紧的（脚踩在哪）权重大，要求松的（躯干正不正）权重小，
再轻轻地拉向一个参照的姿势（站姿），这样没说到的关节不会乱跑。
一个动作的每一帧都从上一帧的解开始算，所以算出来的动作是连续的。手指不动，停在参照的姿势上。
"""

import math
from dataclasses import dataclass

import mujoco
import numpy as np

from nova_body.body import Body, Region

# 权重：脚、膝盖、手心这种"必须在那里"的点用 HARD；重心用 BALANCE；姿态用 SOFT；参照的姿势用 POSTURE。
HARD = 1.0e4
BALANCE = 1.0e3
SOFT = 10.0
POSTURE = 1.0e-2
# 关节离范围的边不到这么多时就开始"不划算"，越靠近越不划算（权重 LIMIT_WEIGHT）：这样别的关节早一点、慢慢地去补，
# 不会等它一下子顶到头，别的关节在一帧里突然跳过去（那样算出来的加速度和力矩是假的）。
LIMIT_MARGIN_RAD = math.radians(5.0)
LIMIT_WEIGHT = SOFT
# 一帧一帧解的时候，离上一帧的姿势近一点（Goals.near），免得用不着的关节（手臂、腰）在一帧里跳过去。
CONTINUITY = 0.1
# 每一步解方程时加一点阻尼，奇异的时候也解得出来。
DAMPING = 1.0e-4
# 一步里关节最多转这么多（弧度）：离要求还远的时候不一下子跳过头。
MAX_STEP_RAD = 0.2
MAX_ITERATIONS = 80
# 关节的角度一步变得比这个还小，就算收敛了。
STEP_TOLERANCE = 1.0e-10
# 关节离范围的边不到这么多（弧度），就算顶在边上了。
AT_LIMIT_RAD = 1.0e-9
FREE_JOINT_DOF = 6
POSITION = 3
ROTATION = 3


class IkError(RuntimeError):
    """要求的姿势做不出来（脚够不着、点不认识……）。"""


@dataclass(frozen=True)
class PointGoal:
    """模型里一个点（site）要去的位置（世界坐标）。rotation 不是 None 时，这个点的姿态也要对上。

    rotation_weight 是姿态那一项的权重，None 是和位置一样。
    """

    site: str
    position: np.ndarray
    rotation: np.ndarray | None = None
    weight: float = HARD
    rotation_weight: float | None = None


@dataclass(frozen=True)
class AttitudeGoal:
    """一段身体要摆成的姿态（世界里的旋转矩阵）。"""

    body: str
    rotation: np.ndarray
    weight: float = SOFT


@dataclass(frozen=True)
class CarriedMass:
    """手里拿着的东西：跟着这个点走。算重心的时候要算上它。"""

    site: str
    mass_kg: float


@dataclass(frozen=True)
class Goals:
    """一帧要做到的事。

    center_of_mass 是整个身体（加上手里拿着的东西）的重心要在的位置；某个方向写 nan 就是这个方向不管。
    near 是要离得近一点的姿势（一帧一帧解时给上一帧的），None 是不管。
    posture 是这一帧拉向的参照姿势（只看关节的角度），None 是建 WholeBodyIk 时给的那个；posture_weight 是它的权重。
    """

    points: tuple[PointGoal, ...] = ()
    attitudes: tuple[AttitudeGoal, ...] = ()
    center_of_mass: np.ndarray | None = None
    center_of_mass_weight: float = BALANCE
    carried: tuple[CarriedMass, ...] = ()
    near: np.ndarray | None = None
    posture: np.ndarray | None = None
    posture_weight: float = POSTURE


@dataclass(frozen=True)
class IkResult:
    """解出来的姿势，和离要求还差多少：点的位置最多差多少米、重心差多少米。"""

    qpos: np.ndarray
    point_error_m: float
    center_of_mass_error_m: float
    iterations: int


class WholeBodyIk:
    """一个身体的全身逆运动学。"""

    def __init__(self, body: Body, reference_qpos: np.ndarray, *, moving: frozenset[Region] | None = None) -> None:
        """moving 是会动的那几部分（None 是手以外的全部）。别的关节不动，停在 solve 开始时给的角度上。"""
        model = body.model
        self.model = model
        self.data = mujoco.MjData(model)
        self.root = model.body(body.anatomy.root).id
        root_joint = int(model.body_jntadr[self.root])
        if root_joint < 0 or model.jnt_type[root_joint] != mujoco.mjtJoint.mjJNT_FREE:
            raise IkError(f"{body.anatomy.root} 没有自由关节，不能做全身的逆运动学")
        free = int(model.jnt_dofadr[root_joint])
        regions = moving if moving is not None else frozenset(Region) - {Region.HAND}
        driven = [joint for joint in body.joints if joint.region in regions]
        joints = [model.joint(joint.name) for joint in driven]
        self.active = np.array([*range(free, free + FREE_JOINT_DOF), *(int(joint.dofadr[0]) for joint in joints)])
        # 参照的姿势只拉关节（不拉骨盆在哪），每个关节在 qpos 里的位置。
        self.posture_dofs = np.arange(FREE_JOINT_DOF, len(self.active))
        self.posture_qpos = np.array([int(joint.qposadr[0]) for joint in joints])
        # 有范围的关节：它在会动的自由度里排第几、角度在 qpos 里的位置、范围。
        self.limits = [
            (FREE_JOINT_DOF + index, int(joint.qposadr[0]), float(joint.range[0]), float(joint.range[1]))
            for index, joint in enumerate(joints)
            if model.jnt_limited[joint.id]
        ]
        self.reference = np.array(reference_qpos, dtype=float)
        self.mass = float(model.body_subtreemass[self.root])
        self._jacp = np.zeros((POSITION, model.nv))
        self._jacr = np.zeros((ROTATION, model.nv))

    def solve(self, goals: Goals, start_qpos: np.ndarray) -> IkResult:
        """从 start_qpos 出发，找满足 goals 的姿势。"""
        model, data = self.model, self.data
        qpos = np.array(start_qpos, dtype=float)
        step = np.zeros(model.nv)
        iterations = 0
        while iterations < MAX_ITERATIONS:
            iterations += 1
            data.qpos[:] = qpos
            mujoco.mj_kinematics(model, data)
            mujoco.mj_comPos(model, data)
            hessian, gradient = self._normal_equations(goals, qpos)
            change = self._step_within_limits(hessian, gradient, qpos)
            size = float(np.abs(change).max())
            if size > MAX_STEP_RAD:
                change *= MAX_STEP_RAD / size
            step[:] = 0.0
            step[self.active] = change
            mujoco.mj_integratePos(model, qpos, step, 1.0)
            for _index, address, low, high in self.limits:
                qpos[address] = min(max(qpos[address], low), high)
            if np.linalg.norm(change) < STEP_TOLERANCE:
                break
        data.qpos[:] = qpos
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)
        return IkResult(
            qpos=qpos,
            point_error_m=max((self._point_error(goal) for goal in goals.points), default=0.0),
            center_of_mass_error_m=self._center_of_mass_error(goals),
            iterations=iterations,
        )

    def center_of_mass(self, carried: tuple[CarriedMass, ...] = ()) -> np.ndarray:
        """现在（上一次 solve 以后）身体加上手里东西的重心。"""
        return self._system_center(carried)[0]

    def _step_within_limits(self, hessian: np.ndarray, gradient: np.ndarray, qpos: np.ndarray) -> np.ndarray:
        """解这一步。已经顶在范围的边上、还要往外转的关节冻住不动，让别的关节去补，再解一遍。"""
        free = np.ones(len(gradient), dtype=bool)
        change = np.zeros(len(gradient))
        for _ in range(len(self.limits) + 1):
            change[:] = 0.0
            change[free] = np.linalg.solve(hessian[np.ix_(free, free)], gradient[free])
            stuck = [
                index
                for index, address, low, high in self.limits
                if free[index]
                and (
                    (qpos[address] <= low + AT_LIMIT_RAD and change[index] < 0)
                    or (qpos[address] >= high - AT_LIMIT_RAD and change[index] > 0)
                )
            ]
            if not stuck:
                break
            free[stuck] = False
        return change

    # 拼方程 -----------------------------------------------------------------------------------------

    def _normal_equations(self, goals: Goals, qpos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """最小二乘的法方程：Σ 权重·JᵀJ 和 Σ 权重·Jᵀ·误差（只算会动的那些自由度）。"""
        size = len(self.active)
        hessian = DAMPING * np.eye(size)
        gradient = np.zeros(size)

        def add(jacobian: np.ndarray, error: np.ndarray, weight: float) -> None:
            nonlocal hessian, gradient
            local = jacobian[:, self.active]
            hessian += weight * local.T @ local
            gradient += weight * local.T @ error

        for goal in goals.points:
            site = self._site_id(goal.site)
            mujoco.mj_jacSite(self.model, self.data, self._jacp, self._jacr, site)
            add(self._jacp, goal.position - self.data.site_xpos[site], goal.weight)
            if goal.rotation is not None:
                current = self.data.site_xmat[site].reshape(3, 3)
                weight = goal.weight if goal.rotation_weight is None else goal.rotation_weight
                add(self._jacr, rotation_error(current, goal.rotation), weight)
        for goal in goals.attitudes:
            body = self.model.body(goal.body).id
            mujoco.mj_jacBody(self.model, self.data, self._jacp, self._jacr, body)
            add(self._jacr, rotation_error(self.data.xmat[body].reshape(3, 3), goal.rotation), goal.weight)
        if goals.center_of_mass is not None:
            center, jacobian = self._system_center(goals.carried)
            wanted = ~np.isnan(goals.center_of_mass)
            error = np.where(wanted, goals.center_of_mass, center) - center
            add(jacobian[wanted], error[wanted], goals.center_of_mass_weight)
        reference = self.reference if goals.posture is None else goals.posture
        posture_error = reference[self.posture_qpos] - qpos[self.posture_qpos]
        hessian[self.posture_dofs, self.posture_dofs] += goals.posture_weight
        gradient[self.posture_dofs] += goals.posture_weight * posture_error
        if goals.near is not None:
            hessian[self.posture_dofs, self.posture_dofs] += CONTINUITY
            gradient[self.posture_dofs] += CONTINUITY * (goals.near[self.posture_qpos] - qpos[self.posture_qpos])
        for index, address, low, high in self.limits:
            near_low = low + LIMIT_MARGIN_RAD - qpos[address]
            near_high = qpos[address] - (high - LIMIT_MARGIN_RAD)
            if near_low > 0:
                hessian[index, index] += LIMIT_WEIGHT
                gradient[index] += LIMIT_WEIGHT * near_low
            elif near_high > 0:
                hessian[index, index] += LIMIT_WEIGHT
                gradient[index] -= LIMIT_WEIGHT * near_high
        return hessian, gradient

    def _system_center(self, carried: tuple[CarriedMass, ...]) -> tuple[np.ndarray, np.ndarray]:
        """身体加上手里东西的重心，和它的雅可比矩阵。"""
        jacobian = np.zeros((POSITION, self.model.nv))
        mujoco.mj_jacSubtreeCom(self.model, self.data, jacobian, self.root)
        total = self.mass
        center = self.mass * self.data.subtree_com[self.root].copy()
        jacobian *= self.mass
        for item in carried:
            site = self._site_id(item.site)
            mujoco.mj_jacSite(self.model, self.data, self._jacp, self._jacr, site)
            center += item.mass_kg * self.data.site_xpos[site]
            jacobian += item.mass_kg * self._jacp
            total += item.mass_kg
        return center / total, jacobian / total

    def _point_error(self, goal: PointGoal) -> float:
        return float(np.linalg.norm(goal.position - self.data.site_xpos[self._site_id(goal.site)]))

    def _center_of_mass_error(self, goals: Goals) -> float:
        if goals.center_of_mass is None:
            return 0.0
        center = self._system_center(goals.carried)[0]
        wanted = ~np.isnan(goals.center_of_mass)
        return float(np.linalg.norm((goals.center_of_mass - center)[wanted]))

    def _site_id(self, name: str) -> int:
        try:
            return self.model.site(name).id
        except KeyError:
            raise IkError(f"模型里没有叫 {name} 的点") from None


def rotation_error(current: np.ndarray, target: np.ndarray) -> np.ndarray:
    """从 current 转到 target 要绕哪根轴转多少（世界坐标，转得不多的时候准）。"""
    return 0.5 * sum(np.cross(current[:, axis], target[:, axis]) for axis in range(3))


def yaw_rotation(yaw_rad: float) -> np.ndarray:
    """绕朝上的轴转 yaw_rad。"""
    cosine, sine = np.cos(yaw_rad), np.sin(yaw_rad)
    return np.array([[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]])


def pitch_rotation(pitch_rad: float) -> np.ndarray:
    """绕朝左的轴转 pitch_rad：正的是往前低头、往前倾。"""
    cosine, sine = np.cos(pitch_rad), np.sin(pitch_rad)
    return np.array([[cosine, 0.0, sine], [0.0, 1.0, 0.0], [-sine, 0.0, cosine]])
