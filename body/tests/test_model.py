"""身体模型的测试：能生成，数对得上，质量和质量闭环一样，关节往说的方向转，传感器和相机都在。"""

import math
from dataclasses import replace

import mujoco
import numpy as np
import pytest

from nova_body.actuator_mass import best_today_model, conservative_model
from nova_body.anthropometry import Segment, segment_count
from nova_body.design import CORE_BODY
from nova_body.hand import DIGITS, hand_joints
from nova_body.mass_closure import Assumptions, FixedItem, close_mass
from nova_body.model import (
    CHEST_DEPTH_CAMERA,
    CHEST_DEPTH_PITCH_DOWN_DEG,
    CONTACT_SUFFIX,
    DAMPING_TIME_S,
    EYE_SPACING_M,
    FLOOR,
    FULL_TORQUE_ERROR_RAD,
    POSITION_SUFFIX,
    ROOT_JOINT,
    STAND_KEY,
    TIMESTEP_S,
    TORQUE_SUFFIX,
    ModelError,
    NovaModel,
    PartKind,
    build_from_budget,
    build_nova,
    tip_force_sensor,
    tip_site,
    wrist_ft_site,
)
from nova_body.skeleton import EYE_HEIGHT_RATIO, LINKS, ROOT_LINK, Side, sides_of, sole_site
from nova_body.standing import read_sensor, simulate_standing, standing_data, stood_well

BODY_DOF = 31
HAND_DOF = 22
HAND_MOTORS = 18
FREE_JOINT_POSITIONS = 7
FREE_JOINT_VELOCITIES = 6
TEST_ANGLE_RAD = 0.15
X, Y, Z = 0, 1, 2


def body_mass(nova: NovaModel, name: str) -> float:
    """模型里一个身体自己的质量。"""
    return float(nova.model.body_mass[nova.model.body(name).id])


def subtree_mass(nova: NovaModel, name: str) -> float:
    """模型里一个身体和它带着的所有身体的质量。"""
    return float(nova.model.body_subtreemass[nova.model.body(name).id])


def posed(nova: NovaModel, angles: dict[str, float]) -> mujoco.MjData:
    """从零位开始，把几个关节转到给的角度（弧度），算好位置。"""
    data = mujoco.MjData(nova.model)
    for name, angle in angles.items():
        data.qpos[nova.model.joint(name).qposadr[0]] = angle
    mujoco.mj_forward(nova.model, data)
    return data


def probe(nova: NovaModel, data: mujoco.MjData, kind: str, name: str) -> np.ndarray:
    """量一个东西：一个点的位置、一个身体的位置、一个身体"朝下"的方向，或者一台相机看的方向。"""
    model = nova.model
    if kind == "site":
        return data.site_xpos[model.site(name).id].copy()
    if kind == "body":
        return data.xpos[model.body(name).id].copy()
    if kind == "down":
        return -data.xmat[model.body(name).id].reshape(3, 3)[:, Z]
    if kind == "look":
        return -data.cam_xmat[model.camera(name).id].reshape(3, 3)[:, Z]
    raise ValueError(kind)


# 生成 ------------------------------------------------------------------------------------------------


def test_model_has_75_joints_and_67_motors(nova):
    """核心版：75 个自由度（身体 31 + 两只手 44），67 个驱动器（身体 31 + 两只手 36）。"""
    model = nova.model
    assert model.nv == FREE_JOINT_VELOCITIES + BODY_DOF + 2 * HAND_DOF
    assert model.nq == FREE_JOINT_POSITIONS + BODY_DOF + 2 * HAND_DOF
    assert model.nu == BODY_DOF + 2 * HAND_MOTORS
    assert len(nova.joints) == CORE_BODY.total_dof()
    assert len(nova.actuated_joints) == model.nu


def test_joint_list_matches_the_model(nova):
    """模型里除了身体的自由关节，每个关节都在关节的清单里，顺序一样；驱动器的顺序也一样。"""
    model = nova.model
    names = [model.joint(index).name for index in range(model.njnt)]
    assert names[0] == ROOT_JOINT
    assert names[1:] == [joint.name for joint in nova.joints]
    assert [model.actuator(index).name for index in range(model.nu)] == [joint.name for joint in nova.actuated_joints]


def test_simulation_settings(nova):
    """仿真每秒 1000 步，用把驱动器的阻尼算进去的积分方法。"""
    assert nova.model.opt.timestep == TIMESTEP_S
    assert nova.model.opt.integrator == mujoco.mjtIntegrator.mjINT_IMPLICITFAST


def test_building_twice_gives_the_same_model():
    """生成两次，得到一样的模型。"""
    first, second = build_nova(), build_nova()
    assert first.spec.to_xml() == second.spec.to_xml()
    assert first.stand == second.stand


# 质量 ------------------------------------------------------------------------------------------------


def test_total_mass_equals_mass_closure(nova):
    """模型的总质量和质量闭环算出来的一样。"""
    assert subtree_mass(nova, ROOT_LINK) == pytest.approx(nova.budget.total_kg, rel=1e-9)


@pytest.mark.parametrize("part", LINKS, ids=[part.key for part in LINKS])
def test_every_segment_mass_equals_mass_closure(nova, part):
    """每一段的质量（手是手掌加所有手指）和质量闭环里那一段一样。"""
    for side in sides_of(part):
        name = part.key if side is None else f"{side.value}_{part.key}"
        mass = subtree_mass(nova, name) if part.segment is Segment.HAND else body_mass(nova, name)
        assert mass == pytest.approx(nova.budget.by_segment[part.segment], rel=1e-9), name


def test_every_part_in_the_budget_is_placed(nova):
    """质量闭环里的每个驱动器、每样东西，模型里都有一块（手的重量分在手掌和手指上）。"""
    budget = nova.budget
    expected = sum(part.count for part in (*budget.actuators, *budget.items) if part.key != "hand")
    placed = [kind for kind in nova.part_kinds.values() if kind is not PartKind.SHELL]
    assert len(placed) == expected
    assert placed.count(PartKind.BATTERY) == 1
    assert placed.count(PartKind.MOTOR) == sum(line.count for line in budget.actuators)


def test_left_and_right_are_mirror_images(nova, zero_pose):
    """左右对称：每一段左右一样重，位置是镜像；重心在正中间。"""
    model = nova.model
    for index in range(model.nbody):
        name = model.body(index).name
        if not name.startswith("left_"):
            continue
        twin = model.body("right_" + name.removeprefix("left_")).id
        assert model.body_mass[index] == pytest.approx(model.body_mass[twin]), name
        assert zero_pose.xpos[index] * [1, -1, 1] == pytest.approx(zero_pose.xpos[twin], abs=1e-12), name
    assert zero_pose.subtree_com[model.body(ROOT_LINK).id][Y] == pytest.approx(0.0, abs=1e-9)


# 零位的样子 ------------------------------------------------------------------------------------------


def test_zero_pose_is_standing_straight(nova, zero_pose):
    """零位是站直：脚底在地面上，头顶是身高，手臂垂着，指尖在肩下面一个手臂加一个手的地方。"""
    model, d = nova.model, nova.dimensions
    for side in Side:
        assert zero_pose.site_xpos[model.site(sole_site(side)).id][Z] == pytest.approx(0.0, abs=1e-9)
        tip = zero_pose.site_xpos[model.site(tip_site(side, "middle")).id]
        assert tip[Z] == pytest.approx(d.shoulder_height - d.upper_arm_length - d.forearm_length - d.hand_length)
    head = model.geom("head.shell")
    assert zero_pose.geom_xpos[head.id][Z] + head.size[Z] == pytest.approx(d.height)


def test_feet_point_forward_and_ankle_is_inside_the_foot(nova, zero_pose):
    """脚尖朝前：脚底的中心在踝的前面；脚底的盒子有脚那么长、那么宽。"""
    model, d = nova.model, nova.dimensions
    sole = zero_pose.site_xpos[model.site(sole_site(Side.LEFT)).id]
    ankle = zero_pose.xpos[model.body("left_foot").id]
    assert sole[X] - ankle[X] == pytest.approx(d.foot_length / 2 - d.heel_behind_ankle)
    assert model.geom("left_foot.sole").size == pytest.approx(
        [d.foot_length / 2, d.foot_width / 2, d.sole_thickness / 2]
    )


# 关节 ------------------------------------------------------------------------------------------------


def test_joint_ranges_are_in_the_model(nova):
    """模型里每个关节的范围，就是关节清单里的范围；膝是 0~150°。"""
    for joint in nova.joints:
        assert nova.model.joint(joint.name).range == pytest.approx([joint.lower_rad, joint.upper_rad]), joint.name
    assert nova.model.joint("left_knee").range == pytest.approx([0.0, math.radians(150)])


def test_motor_limits_follow_the_mass_closure(nova):
    """驱动器最多出的力矩是质量闭环给的峰值力矩：膝按体重放大，颈不变，手是估的值。"""
    model = nova.model
    scale = nova.budget.total_kg / 70.0
    assert model.actuator("left_knee").forcerange == pytest.approx([-300 * scale, 300 * scale])
    assert model.actuator("right_ankle_pitch").forcerange == pytest.approx([-250 * scale, 250 * scale])
    assert model.actuator("right_ankle_roll").forcerange == pytest.approx([-100 * scale, 100 * scale])
    assert model.actuator("neck_yaw").forcerange == pytest.approx([-20, 20])
    assert model.actuator("left_index_mcp_flex").forcerange == pytest.approx([-2.5, 2.5])


def test_motors_are_position_servos_with_damping(nova):
    """每个驱动器是位置控制：偏 0.1 弧度出全力，阻尼 = 刚度 x 0.05 秒；目标只能在关节的范围里。"""
    model = nova.model
    for index, joint in enumerate(nova.actuated_joints):
        stiffness = joint.peak_torque_nm / FULL_TORQUE_ERROR_RAD
        assert model.actuator_gainprm[index, 0] == pytest.approx(stiffness), joint.name
        assert model.actuator_biasprm[index, 1] == pytest.approx(-stiffness), joint.name
        assert model.actuator_biasprm[index, 2] == pytest.approx(-stiffness * DAMPING_TIME_S), joint.name
        assert model.actuator_ctrlrange[index] == pytest.approx([joint.lower_rad, joint.upper_rad]), joint.name


def test_joints_without_motor_follow_another_joint(nova):
    """没有驱动器的只有 8 个远指间，每个都有一条联动连到同一根手指的近指间。"""
    followers = [joint for joint in nova.joints if joint.peak_torque_nm is None]
    assert len(followers) == 2 * (HAND_DOF - HAND_MOTORS)
    assert nova.model.neq == len(followers)
    for joint in followers:
        assert joint.key.endswith("_dip")
        assert joint.follows == joint.name.replace("_dip", "_pip")
        assert joint.stiffness == 0.0


def test_far_finger_joint_follows_in_simulation(nova):
    """仿真里让食指的近指间弯到 60°，远指间跟着弯到约 46°（60 x 80/105）。"""
    model = nova.model
    data = standing_data(model)
    data.ctrl[model.actuator("left_index_pip").id] = math.radians(60)
    for _ in range(round(1.5 / TIMESTEP_S)):
        mujoco.mj_step(model, data)
    near = math.degrees(read_sensor(model, data, "left_index_pip" + POSITION_SUFFIX)[0])
    far = math.degrees(read_sensor(model, data, "left_index_dip" + POSITION_SUFFIX)[0])
    assert near == pytest.approx(60, abs=3)
    assert far == pytest.approx(near * 80 / 105, abs=1.5)


# 每个关节往正方向转，身体往说的那个方向动。
# (关节, 量什么, 量哪个, 看哪个坐标, 左侧变大还是变小, 右侧变大还是变小, 先摆好的别的关节)
PAIRED_MOTIONS = [
    ("hip_pitch", "site", "sole", X, +1, +1, {}),
    ("hip_roll", "site", "sole", Y, +1, -1, {}),
    ("hip_yaw", "site", "sole", Y, +1, -1, {}),
    ("knee", "site", "sole", X, -1, -1, {}),
    ("ankle_pitch", "site", "sole", Z, +1, +1, {}),
    ("ankle_roll", "down", "foot", Y, -1, +1, {}),
    ("shoulder_pitch", "site", "wrist_ft", X, +1, +1, {}),
    ("shoulder_roll", "site", "wrist_ft", Y, +1, -1, {}),
    ("shoulder_yaw", "site", "wrist_ft", Y, +1, -1, {"elbow": math.pi / 2}),
    ("elbow", "site", "wrist_ft", X, +1, +1, {}),
    ("forearm_roll", "look", "palm_camera", X, +1, +1, {}),
    ("wrist_flex", "site", "middle_tip", Y, -1, +1, {}),
    ("wrist_deviation", "site", "middle_tip", X, +1, +1, {}),
    ("palm_arch", "site", "little_tip", Y, -1, +1, {}),
    ("index_mcp_flex", "site", "index_tip", Y, -1, +1, {}),
    ("index_mcp_spread", "site", "index_tip", X, +1, +1, {}),
    ("middle_pip", "site", "middle_tip", Y, -1, +1, {}),
    ("ring_dip", "site", "ring_tip", Y, -1, +1, {}),
    ("little_mcp_flex", "site", "little_tip", Y, -1, +1, {}),
    ("thumb_cmc_flex", "site", "thumb_tip", X, -1, -1, {}),
    ("thumb_cmc_lift", "site", "thumb_tip", Y, -1, +1, {}),
    ("thumb_mcp_flex", "site", "thumb_tip", X, -1, -1, {}),
    ("thumb_mcp_spread", "site", "thumb_tip", Y, -1, +1, {}),
    ("thumb_ip", "site", "thumb_tip", X, -1, -1, {}),
]

CENTRAL_MOTIONS = [
    ("lumbar_pitch", "body", "head", X, +1),
    ("lumbar_roll", "body", "head", Y, -1),
    ("lumbar_yaw", "body", "left_upper_arm", X, -1),
    ("neck_pitch", "look", "left_eye", Z, -1),
    ("neck_yaw", "look", "left_eye", Y, +1),
]


@pytest.mark.parametrize("motion", PAIRED_MOTIONS, ids=[motion[0] for motion in PAIRED_MOTIONS])
def test_paired_joint_moves_the_way_it_says(nova, motion):
    """左右两侧的关节往正方向转：两侧做的是同一个动作（比如都往外、都往手心）。"""
    key, kind, target, axis, left_sign, right_sign, preset = motion
    for side, sign in ((Side.LEFT, left_sign), (Side.RIGHT, right_sign)):
        base = {f"{side.value}_{name}": angle for name, angle in preset.items()}
        before = probe(nova, posed(nova, base), kind, f"{side.value}_{target}")
        after = probe(nova, posed(nova, base | {f"{side.value}_{key}": TEST_ANGLE_RAD}), kind, f"{side.value}_{target}")
        assert sign * (after[axis] - before[axis]) > 1e-4, f"{side.value}_{key}"


@pytest.mark.parametrize("motion", CENTRAL_MOTIONS, ids=[motion[0] for motion in CENTRAL_MOTIONS])
def test_central_joint_moves_the_way_it_says(nova, motion):
    """腰和颈往正方向转：向前弯、向右弯、向左转、低头。"""
    key, kind, target, axis, sign = motion
    before = probe(nova, posed(nova, {}), kind, target)
    after = probe(nova, posed(nova, {key: TEST_ANGLE_RAD}), kind, target)
    assert sign * (after[axis] - before[axis]) > 1e-4


def test_every_joint_has_a_motion_test():
    """上面的方向测试覆盖了身体的每个关节（手的关节每一种都有）。"""
    tested = {motion[0] for motion in PAIRED_MOTIONS} | {motion[0] for motion in CENTRAL_MOTIONS}
    body_joints = {joint.key for part in LINKS for joint in part.joints}
    assert body_joints <= tested
    hand_kinds = {key.split("_", 1)[1] for key in (joint.key for joint in hand_joints()) if "_" in key}
    tested_kinds = {key.split("_", 1)[1] for key in tested if "_" in key}
    assert hand_kinds <= tested_kinds


# 传感器和相机 ----------------------------------------------------------------------------------------


def test_core_sensors_are_all_there(nova):
    """核心的传感器都有：每个关节的位置和速度、每个驱动器的力矩、两个 IMU、踝和腕的六轴力、指尖和全身的接触力。"""
    model = nova.model
    counts: dict[int, int] = {}
    for index in range(model.nsensor):
        counts[int(model.sensor_type[index])] = counts.get(int(model.sensor_type[index]), 0) + 1
    assert counts == {
        int(mujoco.mjtSensor.mjSENS_JOINTPOS): 75,
        int(mujoco.mjtSensor.mjSENS_JOINTVEL): 75,
        int(mujoco.mjtSensor.mjSENS_ACTUATORFRC): 67,
        int(mujoco.mjtSensor.mjSENS_ACCELEROMETER): 2,
        int(mujoco.mjtSensor.mjSENS_GYRO): 2,
        int(mujoco.mjtSensor.mjSENS_FORCE): 4,
        int(mujoco.mjtSensor.mjSENS_TORQUE): 4,
        int(mujoco.mjtSensor.mjSENS_CONTACT): 25,
    }


def test_every_fingertip_and_segment_has_a_contact_sensor(nova):
    """10 个指尖各有一个力传感器；15 段身体各有一个接触力的传感器，都是三个数。"""
    model = nova.model
    names = [tip_force_sensor(side, digit.key) for side in Side for digit in DIGITS]
    names += [
        (part.key if side is None else f"{side.value}_{part.key}") + CONTACT_SUFFIX
        for part in LINKS
        for side in sides_of(part)
    ]
    assert len(names) == 25
    for name in names:
        assert model.sensor(name).dim[0] == 3, name


def test_joint_sensors_read_the_joint(nova):
    """关节的位置传感器读到的就是关节的角度；力矩传感器读到的就是驱动器出的力矩。"""
    model = nova.model
    data = standing_data(model)
    for _ in range(200):
        mujoco.mj_step(model, data)
    # 仿真走完一步以后，传感器里还是这一步开始时的值；再算一遍才是现在的。
    mujoco.mj_forward(model, data)
    for name in ("left_knee", "right_elbow", "lumbar_pitch"):
        angle = data.qpos[model.joint(name).qposadr[0]]
        assert read_sensor(model, data, name + POSITION_SUFFIX)[0] == pytest.approx(angle)
        torque = data.actuator_force[model.actuator(name).id]
        assert read_sensor(model, data, name + TORQUE_SUFFIX)[0] == pytest.approx(torque)


def test_eyes_look_forward_from_eye_height(nova, zero_pose):
    """两只眼在眼的高度，间距 63 mm，朝正前方看。"""
    model = nova.model
    left = zero_pose.cam_xpos[model.camera("left_eye").id]
    right = zero_pose.cam_xpos[model.camera("right_eye").id]
    assert left[Z] == pytest.approx(EYE_HEIGHT_RATIO * nova.dimensions.height)
    assert left[Y] - right[Y] == pytest.approx(EYE_SPACING_M)
    for name in ("left_eye", "right_eye"):
        assert probe(nova, zero_pose, "look", name) == pytest.approx([1.0, 0.0, 0.0], abs=1e-9)


def test_chest_camera_looks_at_the_ground_ahead(nova, zero_pose):
    """胸前的深度相机朝前下方看，画面的上方朝前。"""
    pitch = math.radians(CHEST_DEPTH_PITCH_DOWN_DEG)
    look = probe(nova, zero_pose, "look", CHEST_DEPTH_CAMERA)
    assert look == pytest.approx([math.cos(pitch), 0.0, -math.sin(pitch)], abs=1e-9)
    image_up = zero_pose.cam_xmat[nova.model.camera(CHEST_DEPTH_CAMERA).id].reshape(3, 3)[:, Y]
    assert image_up[X] > 0


@pytest.mark.parametrize(
    ("side", "toward_body"), [(Side.LEFT, -1.0), (Side.RIGHT, 1.0)], ids=["左手朝右看", "右手朝左看"]
)
def test_palm_cameras_look_out_of_the_palm(nova, zero_pose, side, toward_body):
    """手掌相机朝手心的方向看：手垂着时朝着身体。"""
    look = probe(nova, zero_pose, "look", f"{side.value}_palm_camera")
    assert look == pytest.approx([0.0, toward_body, 0.0], abs=1e-9)


def test_wrist_sensor_is_at_the_wrist(nova, zero_pose):
    """腕部力传感器在腕关节上：肩下面一个上臂加一个前臂的地方。"""
    d = nova.dimensions
    wrist = zero_pose.site_xpos[nova.model.site(wrist_ft_site(Side.LEFT)).id]
    assert wrist == pytest.approx(
        [0.0, d.shoulder_half_spacing, d.shoulder_height - d.upper_arm_length - d.forearm_length], abs=1e-9
    )


# 碰撞 ------------------------------------------------------------------------------------------------


def test_only_the_feet_touch_the_floor_when_standing(nova):
    """站着的时候，只有两只脚的脚底碰着地面；身体的各段之间不算碰撞。"""
    model = nova.model
    data = standing_data(model)
    for _ in range(500):
        mujoco.mj_step(model, data)
    floor = model.geom(FLOOR).id
    soles = {model.geom(f"{side.value}_foot.sole").id for side in Side}
    assert data.ncon > 0
    for index in range(data.ncon):
        pair = set(int(geom) for geom in data.contact[index].geom)
        assert floor in pair
        assert pair - {floor} <= soles


# 一族身体 --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "actuators"),
    [
        ({"height_m": 1.50}, best_today_model),
        ({"height_m": 1.90}, best_today_model),
        ({"strength_factor": 0.5}, best_today_model),
        ({"fallbacks": False, "liquid_cooling": False}, best_today_model),
        ({}, conservative_model),
    ],
    ids=["矮的（1.50 m）", "高的（1.90 m）", "力量减半", "不要保底和液冷", "保守的驱动"],
)
def test_other_bodies_in_the_family_also_stand(changes, actuators):
    """换一个身高、力量或者驱动的假设，照样能生成模型，质量对得上，也能站住。"""
    other = build_nova(replace(Assumptions(), **changes), actuators())
    assert subtree_mass(other, ROOT_LINK) == pytest.approx(other.budget.total_kg, rel=1e-9)
    assert other.model.nu == BODY_DOF + 2 * HAND_MOTORS
    assert stood_well(simulate_standing(other, 3.0))


def test_taller_body_has_longer_legs_and_higher_stand_pose():
    """身高高的身体，站姿的骨盆也高。"""
    short = build_nova(replace(Assumptions(), height_m=1.50))
    tall = build_nova(replace(Assumptions(), height_m=1.90))
    assert tall.stand.pelvis_height_m > short.stand.pelvis_height_m
    assert tall.model.key(STAND_KEY).qpos[Z] == pytest.approx(tall.stand.pelvis_height_m)


# 数据对不上的时候 ------------------------------------------------------------------------------------


def core_budget():
    """核心版的质量。"""
    return close_mass(CORE_BODY, Assumptions(), best_today_model())


def test_rejects_a_part_without_a_place():
    """质量闭环里多了一样模型不认识的东西：报错，不能悄悄丢掉它的重量。"""
    budget = core_budget()
    mystery = FixedItem("mystery", "不认识的东西", "别的", Segment.CHEST, 1, 2.0)
    with pytest.raises(ModelError, match="还没有给 mystery 定位置"):
        build_from_budget(replace(budget, items=(*budget.items, mystery)), Assumptions())


def test_rejects_a_part_count_that_differs_from_its_places():
    """一样东西的个数和给它定的位置数对不上：报错。"""
    budget = core_budget()
    items = tuple(replace(item, count=3) if item.key == "hip_brake" else item for item in budget.items)
    with pytest.raises(ModelError, match="hip_brake：这一段里有 3 个，却给了 2 个位置"):
        build_from_budget(replace(budget, items=items), Assumptions())


def test_rejects_an_odd_count_on_a_paired_segment():
    """左右各一个的段里，东西的个数是单数：分不到两侧，报错。"""
    budget = core_budget()
    assert segment_count(Segment.THIGH) == 2
    items = tuple(replace(item, count=3) if item.key == "knee_brake" else item for item in budget.items)
    with pytest.raises(ModelError, match="膝的制动器：3 个分不到左右两侧"):
        build_from_budget(replace(budget, items=items), Assumptions())
