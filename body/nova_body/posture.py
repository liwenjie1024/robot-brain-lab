"""站姿：站着的时候各关节放在什么角度。对哪个身体都是同一个办法。

膝微弯；髋和踝配合着，让躯干竖直、脚底贴地。踝的角度用数值方法找：让重心正好在两只脚的正中间上面。
腿上别的关节、手臂、手，放在这个身体自己的放松姿势上。

驱动器的目标不只是关节的角度，还带上了"顶住重力要的力矩"，所以站姿正好是平衡的位置，身体不会往下沉。
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

import mujoco
import numpy as np

from nova_body.body import Anatomy, Body, Leg, StandPose

KNEE_BEND_DEG = 15.0
KNEE_SEARCH_STEP_DEG = 1.0
BISECTION_STEPS = 60
FREE_JOINT_DOF = 6
FORWARD_AXIS, LEFT_AXIS, UP_AXIS = 0, 1, 2
LEGS = 2
# 站姿平衡时，整个身体受的合力和合力矩应该是 0；大于这个数（N 或 N·m）就是不平衡。
BALANCE_TOLERANCE = 1.0e-6
# 腿上那三个关节的转轴应该正好朝左或朝右；躯干和脚应该是正的。差得比这个多就不认。
ALIGNMENT_TOLERANCE = 1.0e-6
# 关节的角度正好在范围的边上时，算的时候会有一点点误差，这么小的不算超出。
RANGE_TOLERANCE_RAD = 1.0e-9

# 驱动器的力合起来和站姿要的关节力矩差多少还算对得上（N·m）。
FORCE_TOLERANCE_NM = 1e-6


class PostureError(RuntimeError):
    """找不到能站住的姿势。"""


@dataclass(frozen=True)
class _PitchJoint:
    """腿上一个绕左右方向转的关节。

    address 是它的角度在 qpos 里的位置。sign 是 +1 时，往正方向转是绕"朝左"的轴转（小腿往后摆的那个方向），
    -1 是反过来。不同的身体正方向定得不一样，这样写站姿就不用管它。
    """

    name: str
    address: int
    sign: float
    lower_rad: float
    upper_rad: float

    def turn(self, data: mujoco.MjData, about_left_rad: float) -> None:
        """让这个关节绕"朝左"的轴转这么多。"""
        data.qpos[self.address] = self.sign * about_left_rad


@dataclass(frozen=True)
class _LegJoints:
    hip: _PitchJoint
    knee: _PitchJoint
    ankle: _PitchJoint
    foot: int
    sole: int

    @property
    def most_toe_up_rad(self) -> float:
        """踝最多能让脚尖向上多少。"""
        return max(-self.ankle.sign * self.ankle.lower_rad, -self.ankle.sign * self.ankle.upper_rad)

    @property
    def most_knee_bend_rad(self) -> float:
        """膝最多能弯多少。"""
        return max(self.knee.sign * self.knee.lower_rad, self.knee.sign * self.knee.upper_rad)


def solve_stand_pose(model: mujoco.MjModel, anatomy: Anatomy, knee_deg: float = KNEE_BEND_DEG) -> StandPose:
    """算出站姿：膝弯 knee_deg，躯干竖直，重心在两只脚的正中间上面，脚底贴地。"""
    stance = _Stance(model, anatomy)
    knee = math.radians(knee_deg)

    def center_of_mass_ahead_of_feet(toe_up: float) -> float:
        stance.set_pose(knee, toe_up)
        return float(stance.center_of_mass[FORWARD_AXIS] - stance.between_soles[FORWARD_AXIS])

    toe_up = _find_zero(center_of_mass_ahead_of_feet, 0.0, min(leg.most_toe_up_rad for leg in stance.legs))
    stance.set_pose(knee, toe_up)
    stance.put_soles_on_the_floor()
    stance.check_within_joint_ranges()
    stance.check_upright()
    return stance.stand_pose(knee_deg, math.degrees(toe_up))


def toe_up_limit_deg(model: mujoco.MjModel, anatomy: Anatomy) -> float:
    """踝最多能让脚尖向上多少度（两条腿里小的那个）。站姿能弯多深的膝，就看它。"""
    return math.degrees(min(leg.most_toe_up_rad for leg in _Stance(model, anatomy).legs))


def deepest_knee_bend_deg(body: Body, step_deg: float = KNEE_SEARCH_STEP_DEG) -> float:
    """躯干竖直、脚底贴地时，膝最多能弯到多少度还站得住。从 step_deg 开始一格一格地试，试到站不住为止。

    站得住 = 重心还能落在两只脚的正中间上面，每个驱动器要出的力矩不超过它的峰值，目标不超出关节的范围。
    """
    if step_deg <= 0:
        raise ValueError(f"每一格要大于 0 度，收到的是 {step_deg}")
    knee_limit_deg = math.degrees(min(leg.most_knee_bend_rad for leg in _Stance(body.model, body.anatomy).legs))
    deepest = None
    steps = 1
    while steps * step_deg <= knee_limit_deg:
        try:
            pose = solve_stand_pose(body.model, body.anatomy, steps * step_deg)
        except PostureError:
            break
        if not _can_hold(body, pose):
            break
        deepest = steps * step_deg
        steps += 1
    if deepest is None:
        raise PostureError("这个身体膝弯多少都站不住")
    return deepest


def _can_hold(body: Body, pose: StandPose) -> bool:
    """这个姿势顶不顶得住：每个驱动器要出的力不超过峰值，目标在它的范围里。"""
    return all(
        abs(force) <= actuator.peak_torque_nm and actuator.lower <= target <= actuator.upper
        for actuator, force, target in zip(body.actuators, pose.holding_torque_nm, pose.ctrl, strict=True)
    )


class _Stance:
    """在一个模型上摆站姿，量重心和脚底，算顶住重力要的力矩。"""

    def __init__(self, model: mujoco.MjModel, anatomy: Anatomy) -> None:
        if len(anatomy.legs) != LEGS:
            raise PostureError(f"要两条腿才能站，这个身体有 {len(anatomy.legs)} 条")
        self.model = model
        self.data = mujoco.MjData(model)
        self.root = _named(model.body, anatomy.root, "身体").id
        self.root_height_address = _free_joint_address(model, self.root, anatomy.root) + UP_AXIS
        self.relaxed = {
            _named(model.joint, name, "关节").qposadr[0]: angle for name, angle in anatomy.relaxed_rad.items()
        }
        # 零位时看每个关节的转轴朝哪边。
        mujoco.mj_kinematics(model, self.data)
        self.legs = [self._leg_joints(leg) for leg in anatomy.legs.values()]

    @property
    def center_of_mass(self) -> np.ndarray:
        return self.data.subtree_com[self.root]

    @property
    def between_soles(self) -> np.ndarray:
        """两只脚底正中间的点。"""
        return np.mean([self.data.site_xpos[leg.sole] for leg in self.legs], axis=0)

    def set_pose(self, knee: float, toe_up: float) -> None:
        """膝弯 knee、脚尖向上 toe_up（弧度）时摆好全身。

        髋向前抬 knee - toe_up，三个关节转的加起来是 0，所以躯干是竖直的、脚底是平的。
        """
        self.data.qpos[:] = self.model.qpos0
        for address, angle in self.relaxed.items():
            self.data.qpos[address] = angle
        for leg in self.legs:
            # 绕"朝左"的轴转：膝弯是正的（小腿往后摆），脚尖向上和髋向前抬是负的。
            leg.knee.turn(self.data, knee)
            leg.ankle.turn(self.data, -toe_up)
            leg.hip.turn(self.data, -(knee - toe_up))
        self._move_coupled_joints()
        self._update_positions()

    def put_soles_on_the_floor(self) -> None:
        """把整个身体放低（或抬高），让脚底正好贴着地面。"""
        self.data.qpos[self.root_height_address] -= self.between_soles[UP_AXIS]
        self._update_positions()

    def check_within_joint_ranges(self) -> None:
        """每个关节都要在它能转的范围里（膝弯得太多、放松的姿势写错了，都会超出去）。"""
        model = self.model
        for joint in range(model.njnt):
            if model.jnt_type[joint] != mujoco.mjtJoint.mjJNT_HINGE or not model.jnt_limited[joint]:
                continue
            lower, upper = model.jnt_range[joint]
            angle = self.data.qpos[model.jnt_qposadr[joint]]
            if not lower - RANGE_TOLERANCE_RAD <= angle <= upper + RANGE_TOLERANCE_RAD:
                name = model.joint(joint).name
                raise PostureError(f"站姿里 {name} 要转到 {math.degrees(angle):.1f}°，超出了它能转的范围")

    def check_upright(self) -> None:
        """躯干和两只脚都应该是正的。不是的话，这个身体的腿不是照"三个关节加起来是 0"这样排的。"""
        for body in (self.root, *(leg.foot for leg in self.legs)):
            upright = self.data.xmat[body].reshape(3, 3)[UP_AXIS, UP_AXIS]
            if abs(upright - 1.0) > ALIGNMENT_TOLERANCE:
                raise PostureError(f"摆好站姿以后 {self.model.body(body).name} 是歪的：这个身体的腿不能这样摆")

    def stand_pose(self, knee_deg: float, toe_up_deg: float) -> StandPose:
        """把现在摆好的姿势写成站姿：位置、每个驱动器要出的力矩、每个驱动器的目标。"""
        model, data = self.model, self.data
        forces = _actuator_forces(model, data, self._holding_torques())
        stiffness = model.actuator_gainprm[:, 0]
        return StandPose(
            qpos=tuple(float(value) for value in data.qpos),
            ctrl=tuple(
                float(length + force / gain)
                for length, force, gain in zip(data.actuator_length, forces, stiffness, strict=True)
            ),
            holding_torque_nm=tuple(float(force) for force in forces),
            knee_deg=knee_deg,
            ankle_deg=toe_up_deg,
            hip_deg=knee_deg - toe_up_deg,
            pelvis_height_m=float(data.qpos[self.root_height_address]),
            center_of_mass_height_m=float(self.center_of_mass[UP_AXIS]),
        )

    def _leg_joints(self, leg: Leg) -> _LegJoints:
        return _LegJoints(
            hip=self._pitch_joint(leg.hip_pitch),
            knee=self._pitch_joint(leg.knee),
            ankle=self._pitch_joint(leg.ankle_pitch),
            foot=_named(self.model.body, leg.foot, "身体").id,
            sole=_named(self.model.site, leg.sole, "点").id,
        )

    def _pitch_joint(self, name: str) -> _PitchJoint:
        joint = _named(self.model.joint, name, "关节")
        toward_left = float(self.data.xaxis[joint.id][LEFT_AXIS])
        if joint.type[0] != mujoco.mjtJoint.mjJNT_HINGE or abs(abs(toward_left) - 1.0) > ALIGNMENT_TOLERANCE:
            raise PostureError(f"{name} 不是绕左右方向转的关节，不能用来摆站姿")
        lower, upper = (float(limit) for limit in joint.range)
        return _PitchJoint(name, int(joint.qposadr[0]), math.copysign(1.0, toward_left), lower, upper)

    def _move_coupled_joints(self) -> None:
        """跟着别的关节动的关节，按联动的比例摆好。"""
        model, data = self.model, self.data
        for index in range(model.neq):
            if model.eq_type[index] == mujoco.mjtEq.mjEQ_JOINT:
                follower = model.jnt_qposadr[model.eq_obj1id[index]]
                leader = model.jnt_qposadr[model.eq_obj2id[index]]
                data.qpos[follower] = model.eq_data[index, 0] + model.eq_data[index, 1] * data.qpos[leader]

    def _update_positions(self) -> None:
        mujoco.mj_kinematics(self.model, self.data)
        mujoco.mj_comPos(self.model, self.data)

    def _holding_torques(self) -> np.ndarray:
        """站姿上每个自由度要多大的力才能不动：顶住重力，减去地面托着两只脚的力。

        地面托每只脚的力作用在脚底的正中间。两只脚各托多少，按重心在左右方向上离哪只脚近来分
        （身体左右对称时正好各一半）。
        """
        model, data = self.model, self.data
        mujoco.mj_forward(model, data)
        weight = -model.opt.gravity[UP_AXIS] * model.body_subtreemass[self.root]
        from_floor = np.zeros(model.nv)
        for leg, share in zip(self.legs, self._weight_shares(), strict=True):
            push_up = np.array([0.0, 0.0, share * weight])
            mujoco.mj_applyFT(
                model, data, push_up, np.zeros(3), data.site_xpos[leg.sole], model.site_bodyid[leg.sole], from_floor
            )
        torques = data.qfrc_bias - from_floor
        root_dof = model.jnt_dofadr[model.body_jntadr[self.root]]
        if np.abs(torques[root_dof : root_dof + FREE_JOINT_DOF]).max() > BALANCE_TOLERANCE:
            raise PostureError("站姿不平衡：地面托着两只脚的力顶不住整个身体")
        # 跟着别的关节动的关节没有驱动器，它要的力矩由带着它的那个关节出。
        for index in range(model.neq):
            if model.eq_type[index] == mujoco.mjtEq.mjEQ_JOINT:
                follower = model.jnt_dofadr[model.eq_obj1id[index]]
                leader = model.jnt_dofadr[model.eq_obj2id[index]]
                torques[leader] += model.eq_data[index, 1] * torques[follower]
        return torques

    def _weight_shares(self) -> tuple[float, float]:
        """两只脚各托着体重的多少（加起来是 1）。"""
        first, second = (float(self.data.site_xpos[leg.sole][LEFT_AXIS]) for leg in self.legs)
        if math.isclose(first, second):
            raise PostureError("两只脚在左右方向上没有分开，站不住")
        share = (float(self.center_of_mass[LEFT_AXIS]) - second) / (first - second)
        if not 0.0 < share < 1.0:
            raise PostureError("重心不在两只脚之间，站不住")
        return share, 1.0 - share


def _actuator_forces(model: mujoco.MjModel, data: mujoco.MjData, torques: np.ndarray) -> np.ndarray:
    """每个驱动器要出多大的力，有驱动器带着的关节才得到这些力矩。

    驱动器的力经"力臂"（MuJoCo 算的 actuator_moment）变成关节的力矩：一般的驱动器力臂是 1，
    并联的一对是和、差。所以不管驱动器怎么带关节，都是解同一个方程。带不出来就报错。
    """
    moment = np.zeros((model.nu, model.nv))
    mujoco.mju_sparse2dense(moment, data.actuator_moment, data.moment_rownnz, data.moment_rowadr, data.moment_colind)
    driven = np.flatnonzero(np.any(moment != 0.0, axis=0))
    forces, *_ = np.linalg.lstsq(moment[:, driven].T, torques[driven], rcond=None)
    if not np.allclose(moment[:, driven].T @ forces, torques[driven], atol=FORCE_TOLERANCE_NM):
        raise PostureError("驱动器出不了站姿要的力矩（两个驱动器带的是同样的关节）")
    return forces


def _named(lookup: Callable, name: str, kind: str):
    """按名字找模型里的一样东西；没有就说清楚是哪个名字。"""
    try:
        return lookup(name)
    except KeyError:
        raise PostureError(f"模型里没有叫 {name} 的{kind}") from None


def _free_joint_address(model: mujoco.MjModel, root: int, name: str) -> int:
    """骨盆的自由关节在 qpos 里从哪开始。骨盆要能在空间里自由地动，不然不是一个站着的身体。"""
    joint = model.body_jntadr[root]
    if joint < 0 or model.jnt_type[joint] != mujoco.mjtJoint.mjJNT_FREE:
        raise PostureError(f"{name} 没有自由关节：这个身体是固定住的，不用算站姿")
    return int(model.jnt_qposadr[joint])


def _find_zero(function: Callable[[float], float], low: float, high: float) -> float:
    """二分法：function 在 low 是负的、在 high 是正的，找它等于 0 的地方。"""
    if function(low) > 0 or function(high) < 0:
        raise PostureError("找不到让重心落在脚中间的站姿：踝在能转的范围里做不到")
    for _ in range(BISECTION_STEPS):
        middle = (low + high) / 2
        if function(middle) < 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2
