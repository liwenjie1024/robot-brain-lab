"""基线的身体：现成的 Unitree G1（29 个自由度，没有灵巧手），放上和 Nova 同一个测试台。

模型文件是 MuJoCo Menagerie 里的 unitree_g1/g1.xml（BSD-3），按 third_party 里的清单下载，文件一个字都不改。
读进来以后，只做测试台对每个身体都做的事：
- 放到同一块地面上，用同一个步长；
- 关节位置控制的软硬换成同一条规则（文件里的 kp=500 是没有调过的）；
- 给每只脚加一个"脚底正中间"的点，给每个关节加位置、速度、力矩的传感器；
- 用同一个办法算站姿，存成 stand。文件里自带的站姿改名叫 published_stand，留着对照。

身体本身都是文件里的：各段的质量、关节的范围、电机的峰值力矩、摩擦、碰撞的形状。
"""

from pathlib import Path

import mujoco
import numpy as np

from nova_body.bench import (
    STAND_KEY,
    add_floor,
    add_joint_sensors,
    damping_for,
    stiffness_for,
    store_stand_pose,
    use_bench_settings,
)
from nova_body.body import SIDE_NAMES, Anatomy, Body, DrivenJoint, Imu, Leg, Side
from nova_body.posture import solve_stand_pose
from nova_body.third_party import MANIFEST_SUFFIX, THIRD_PARTY_DIR, Manifest, load_manifest, require

G1_ASSETS = "unitree_g1"
G1_MODEL_FILE = "g1.xml"
BODY_NAME = "Unitree G1"
PUBLISHED_STAND_KEY = "published_stand"
# 厂家网页上写的：身高，带电池的重量（"约 35 kg"）。模型文件里各段质量加起来比这个轻一点。
OFFICIAL_HEIGHT_M = 1.32
OFFICIAL_MASS_KG = 35.0
# 文件自带的两样设置，放上测试台以后不用它们（写在这里是为了说明和核对）：
# 每个关节位置控制的刚度（N·m/rad，没有调过的），和脚与地面的摩擦。
PUBLISHED_STIFFNESS = 500.0
PUBLISHED_FOOT_FRICTION = 0.6

DRIVEN_JOINTS = 29
ROOT_BODY = "pelvis"
TRUNK_BODY = "torso_link"
FOOT_BODY = "ankle_roll_link"
JOINT_SUFFIX = "_joint"
HIP_PITCH, KNEE, ANKLE_PITCH = "hip_pitch", "knee", "ankle_pitch"
SOLE_SUFFIX = "_sole"
# 文件里看得见的形状（网格）都在这一组；碰撞用的形状在另一组，画图时不画。
VISUAL_GROUP = 2
STIFFNESS_GAIN, STIFFNESS_BIAS, DAMPING_BIAS = 0, 1, 2
UP_AXIS = 2

IMUS: tuple[Imu, ...] = (
    Imu("骨盆", "imu-pelvis-linear-acceleration", "imu-pelvis-angular-velocity"),
    Imu("躯干", "imu-torso-linear-acceleration", "imu-torso-angular-velocity"),
)

# 关节在文件里的名字（去掉左右和后面的 _joint）对应的中文名。
JOINT_LABELS: dict[str, str] = {
    "hip_pitch": "髋 前后",
    "hip_roll": "髋 侧摆",
    "hip_yaw": "髋 转",
    "knee": "膝",
    "ankle_pitch": "踝 前后",
    "ankle_roll": "踝 侧",
    "waist_yaw": "腰 转",
    "waist_roll": "腰 侧弯",
    "waist_pitch": "腰 前后",
    "shoulder_pitch": "肩 前后",
    "shoulder_roll": "肩 侧摆",
    "shoulder_yaw": "肩 转",
    "elbow": "肘",
    "wrist_roll": "前臂转",
    "wrist_pitch": "腕 上下",
    "wrist_yaw": "腕 左右",
}


class BaselineError(RuntimeError):
    """文件里的模型和这里以为的不一样（比如换了一个版本）。"""


def g1_manifest(directory: Path = THIRD_PARTY_DIR) -> Manifest:
    """G1 的清单：从哪来、哪个版本、什么许可证。"""
    return load_manifest(directory / (G1_ASSETS + MANIFEST_SUFFIX))


def load_g1(directory: Path = THIRD_PARTY_DIR) -> Body:
    """读进 G1，放上测试台。"""
    return put_on_bench(read_g1_spec(directory))


def read_g1_spec(directory: Path = THIRD_PARTY_DIR) -> mujoco.MjSpec:
    """核对文件和清单一样，再把模型文件读进来（还没有改过）。"""
    assets = require(g1_manifest(directory), directory)
    return mujoco.MjSpec.from_file(str(assets / G1_MODEL_FILE))


def put_on_bench(spec: mujoco.MjSpec) -> Body:
    """把读进来的 G1 放上测试台：同一块地面、同一条关节控制的规则、同一个办法算的站姿。"""
    use_bench_settings(spec)
    add_floor(spec)
    _keep_published_stand(spec)
    joints = _use_bench_drives(spec)
    foot_lengths = {side: _add_sole(spec, side) for side in Side}
    names = [joint.name for joint in joints]
    add_joint_sensors(spec, joints=names, driven=names)

    # 编译两遍：第一遍的模型用来算站姿，第二遍把站姿存进模型里。
    first = spec.compile()
    anatomy = _anatomy(first)
    stand = solve_stand_pose(first, anatomy)
    store_stand_pose(spec, stand)
    model = spec.compile()
    return Body(
        name=BODY_NAME,
        model=model,
        anatomy=anatomy,
        joints=joints,
        imus=IMUS,
        stand=stand,
        height_m=_zero_pose_height(model, anatomy),
        foot_length_m=min(foot_lengths.values()),
        drawn_groups=(VISUAL_GROUP,),
    )


def load_published_g1(directory: Path = THIRD_PARTY_DIR) -> mujoco.MjModel:
    """文件原样的 G1，只加上测试台的地面。用来确认"原样也站得住"；文件自带的站姿叫 stand。"""
    spec = read_g1_spec(directory)
    add_floor(spec)
    return spec.compile()


def joint_name(kind: str, side: Side | None = None) -> str:
    """关节在文件里的名字。kind 比如 knee、waist_yaw；腰的关节没有左右。"""
    prefix = "" if side is None else f"{side.value}_"
    return prefix + kind + JOINT_SUFFIX


def joint_label(name: str) -> str:
    """关节的中文名，比如"左 膝"。不认识的关节报错。"""
    kind = name.removesuffix(JOINT_SUFFIX)
    side = next((side for side in Side if kind.startswith(f"{side.value}_")), None)
    if side is not None:
        kind = kind.removeprefix(f"{side.value}_")
    if kind not in JOINT_LABELS:
        raise BaselineError(f"不认识的关节：{name}")
    return JOINT_LABELS[kind] if side is None else f"{SIDE_NAMES[side]} {JOINT_LABELS[kind]}"


def _keep_published_stand(spec: mujoco.MjSpec) -> None:
    """文件自带的站姿也叫 stand，和测试台的重名，所以给它改个名字留着。"""
    published = [key for key in spec.keys if key.name == STAND_KEY]
    if len(published) != 1:
        raise BaselineError(f"文件里应该正好有一个叫 {STAND_KEY} 的站姿，找到 {len(published)} 个")
    published[0].name = PUBLISHED_STAND_KEY


def _use_bench_drives(spec: mujoco.MjSpec) -> tuple[DrivenJoint, ...]:
    """每个关节的位置控制换成测试台的软硬；峰值力矩和范围用文件里的。返回关节的清单。"""
    if len(spec.actuators) != DRIVEN_JOINTS:
        raise BaselineError(f"应该是 {DRIVEN_JOINTS} 个驱动器的 G1，这个文件有 {len(spec.actuators)} 个")
    joints = []
    for actuator in spec.actuators:
        joint = spec.joint(actuator.target)
        lower_torque, peak_torque = (float(limit) for limit in joint.actfrcrange)
        is_position_servo = (
            actuator.gaintype == mujoco.mjtGain.mjGAIN_FIXED and actuator.biastype == mujoco.mjtBias.mjBIAS_AFFINE
        )
        if actuator.name != joint.name or not is_position_servo or peak_torque <= 0 or lower_torque != -peak_torque:
            raise BaselineError(f"{actuator.name}：不是这里以为的那种驱动器（位置控制，力矩的上下限对称）")
        actuator.gainprm[STIFFNESS_GAIN] = stiffness_for(peak_torque)
        actuator.biasprm[STIFFNESS_BIAS] = -stiffness_for(peak_torque)
        actuator.biasprm[DAMPING_BIAS] = -damping_for(peak_torque)
        lower, upper = (float(limit) for limit in joint.range)
        joints.append(DrivenJoint(joint.name, joint_label(joint.name), lower, upper, peak_torque))
    return tuple(joints)


def _add_sole(spec: mujoco.MjSpec, side: Side) -> float:
    """在脚底的正中间加一个点。返回脚底着地的那一段有多长。

    G1 的脚用几个小球和地面接触。脚底就是这些小球的最低处，正中间是它们前后、左右的正中间。
    """
    foot = spec.body(f"{side.value}_{FOOT_BODY}")
    balls = [geom for geom in foot.geoms if geom.type == mujoco.mjtGeom.mjGEOM_SPHERE]
    if not balls:
        raise BaselineError(f"{foot.name} 上没有和地面接触的小球")
    lowest = np.min([np.asarray(ball.pos) - ball.size[0] for ball in balls], axis=0)
    highest = np.max([np.asarray(ball.pos) + ball.size[0] for ball in balls], axis=0)
    middle = (lowest + highest) / 2
    foot.add_site(name=_sole(side), pos=[middle[0], middle[1], lowest[UP_AXIS]])
    return float(highest[0] - lowest[0])


def _sole(side: Side) -> str:
    return side.value + SOLE_SUFFIX


def _anatomy(model: mujoco.MjModel) -> Anatomy:
    """测试台要认得的地方。站着时腿以外的关节放在文件自带的站姿上（手臂垂着、肘弯着）。"""
    legs = {
        side: Leg(
            hip_pitch=joint_name(HIP_PITCH, side),
            knee=joint_name(KNEE, side),
            ankle_pitch=joint_name(ANKLE_PITCH, side),
            foot=f"{side.value}_{FOOT_BODY}",
            sole=_sole(side),
        )
        for side in Side
    }
    solved = {name for leg in legs.values() for name in (leg.hip_pitch, leg.knee, leg.ankle_pitch)}
    published = model.key(PUBLISHED_STAND_KEY).qpos
    relaxed = {}
    for index in range(model.njnt):
        name = model.joint(index).name
        angle = float(published[model.jnt_qposadr[index]])
        if model.jnt_type[index] == mujoco.mjtJoint.mjJNT_HINGE and name not in solved and angle != 0.0:
            relaxed[name] = angle
    return Anatomy(root=ROOT_BODY, trunk=TRUNK_BODY, legs=legs, relaxed_rad=relaxed)


def _zero_pose_height(model: mujoco.MjModel, anatomy: Anatomy) -> float:
    """站直（零位）时从脚底到头顶有多高：看所有网格里最高的那个点。"""
    data = mujoco.MjData(model)
    mujoco.mj_kinematics(model, data)
    top = -np.inf
    for geom in range(model.ngeom):
        if model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_MESH:
            mesh = model.geom_dataid[geom]
            start = model.mesh_vertadr[mesh]
            points = model.mesh_vert[start : start + model.mesh_vertnum[mesh]]
            heights = points @ data.geom_xmat[geom].reshape(3, 3)[UP_AXIS] + data.geom_xpos[geom][UP_AXIS]
            top = max(top, float(heights.max()))
    soles = [data.site_xpos[model.site(leg.sole).id][UP_AXIS] for leg in anatomy.legs.values()]
    return top - float(np.mean(soles))
