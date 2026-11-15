"""基线的身体（Unitree G1）的测试。

文件是清单上的那一版；放上测试台以后，身体本身还是文件里的（质量、关节、电机、摩擦、形状），
测试台加的东西（地面、软硬、脚底的点、站姿）加对了。站不站得住在 test_standing.py，和 Nova 是同一套。
"""

import math
import shutil
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import pytest

from nova_body.baseline import (
    BODY_NAME,
    G1_ASSETS,
    G1_MODEL_FILE,
    IMUS,
    JOINT_LABELS,
    OFFICIAL_HEIGHT_M,
    OFFICIAL_MASS_KG,
    PUBLISHED_FOOT_FRICTION,
    PUBLISHED_STAND_KEY,
    PUBLISHED_STIFFNESS,
    VISUAL_GROUP,
    BaselineError,
    g1_manifest,
    joint_label,
    joint_name,
    load_g1,
    load_published_g1,
    put_on_bench,
    read_g1_spec,
)
from nova_body.bench import FLOOR, STAND_KEY, stiffness_for
from nova_body.body import Side
from nova_body.third_party import FETCH_COMMAND, THIRD_PARTY_DIR, AssetError, ManifestError

X, Y, Z = 0, 1, 2
G1_FILE = THIRD_PARTY_DIR / G1_ASSETS / G1_MODEL_FILE
BALL_RADIUS_M = 0.005


@pytest.fixture(scope="module")
def published() -> mujoco.MjModel:
    """文件原样的 G1（只加了地面）。"""
    return load_published_g1()


@pytest.fixture(scope="module")
def file_tree() -> ET.Element:
    """模型文件本身（XML），不经过 MuJoCo，用来对照。"""
    return ET.parse(G1_FILE).getroot()


# 文件从哪来 ------------------------------------------------------------------------------------------


def test_g1_comes_from_a_pinned_commit_of_mujoco_menagerie():
    """清单写着：MuJoCo Menagerie 的一个固定的提交，BSD-3 许可证；模型文件、许可证和 35 个网格。"""
    manifest = g1_manifest()
    assert manifest.source == "https://github.com/google-deepmind/mujoco_menagerie"
    assert manifest.license == "BSD-3-Clause"
    assert manifest.base_url.endswith(f"/{manifest.commit}/unitree_g1/")
    paths = [file.path for file in manifest.files]
    assert paths[:2] == ["LICENSE", G1_MODEL_FILE]
    assert len([path for path in paths if path.startswith("assets/") and path.endswith(".STL")]) == 35
    assert len(paths) == 37


def test_license_text_is_kept_next_to_the_model():
    """许可证的原文和模型放在一起（BSD-3 要求留着版权声明）。"""
    text = (THIRD_PARTY_DIR / G1_ASSETS / "LICENSE").read_text(encoding="utf-8")
    assert "Unitree Robotics" in text
    assert "Redistribution and use in source and binary forms" in text


def test_manifest_lists_exactly_the_meshes_the_model_uses(file_tree):
    """模型文件用到的每个网格都在清单里，清单里也没有多余的网格。"""
    used = {"assets/" + mesh.get("file") for mesh in file_tree.iter("mesh")}
    listed = {file.path for file in g1_manifest().files if file.path.startswith("assets/")}
    assert used == listed


# 身体本身还是文件里的 --------------------------------------------------------------------------------


def test_g1_has_29_driven_joints(g1):
    """29 个自由度：腿 12、腰 3、手臂 14，每个都有驱动器；没有手指。"""
    model = g1.model
    assert g1.name == BODY_NAME
    assert (model.nq, model.nv, model.nu) == (7 + 29, 6 + 29, 29)
    names = [joint.name for joint in g1.joints]
    assert len([name for name in names if "hip" in name or "knee" in name or "ankle" in name]) == 12
    assert len([name for name in names if "waist" in name]) == 3
    assert len([name for name in names if "shoulder" in name or "elbow" in name or "wrist" in name]) == 14
    assert names == [model.actuator(index).name for index in range(model.nu)]


def test_mass_is_the_sum_of_the_masses_in_the_file(g1, file_tree):
    """模型的总质量就是文件里各段质量加起来：33.34 kg。比厂家写的"约 35 kg"轻一点（差不到 10%）。"""
    in_file = sum(float(inertial.get("mass")) for inertial in file_tree.iter("inertial"))
    assert g1.mass_kg == pytest.approx(in_file, rel=1e-9)
    assert g1.mass_kg == pytest.approx(33.34, abs=0.005)
    assert 0.9 * OFFICIAL_MASS_KG < g1.mass_kg < OFFICIAL_MASS_KG


def test_height_matches_the_official_height(g1):
    """站直时从脚底到头顶的高度，和厂家写的 1.32 m 差不到 1 cm。"""
    assert g1.height_m == pytest.approx(OFFICIAL_HEIGHT_M, abs=0.01)


def test_joint_ranges_and_peak_torques_come_from_the_file(g1, file_tree):
    """每个关节的范围和电机的峰值力矩，就是文件里写的：膝 139 N·m，腕上下只有 5 N·m。"""
    in_file = {joint.get("name"): joint for joint in file_tree.iter("joint") if joint.get("range")}
    assert len(in_file) == len(g1.joints)
    for joint in g1.joints:
        lower, upper = (float(value) for value in in_file[joint.name].get("range").split())
        low_torque, high_torque = (float(value) for value in in_file[joint.name].get("actuatorfrcrange").split())
        assert (joint.lower_rad, joint.upper_rad) == pytest.approx((lower, upper)), joint.name
        assert (-joint.peak_torque_nm, joint.peak_torque_nm) == pytest.approx((low_torque, high_torque)), joint.name
    peak = {joint.name: joint.peak_torque_nm for joint in g1.joints}
    assert peak[joint_name("knee", Side.LEFT)] == 139.0
    assert peak[joint_name("ankle_pitch", Side.RIGHT)] == 50.0
    assert peak[joint_name("wrist_pitch", Side.LEFT)] == 5.0
    assert peak[joint_name("waist_yaw")] == 88.0


@pytest.mark.parametrize(
    "field",
    [
        "body_mass",
        "body_inertia",
        "body_ipos",
        "body_pos",
        "body_quat",
        "jnt_axis",
        "jnt_range",
        "jnt_actfrcrange",
        "dof_armature",
        "dof_frictionloss",
        "dof_damping",
        "geom_type",
        "geom_size",
        "geom_pos",
        "geom_contype",
        "geom_conaffinity",
        "geom_friction",
        "qpos0",
    ],
)
def test_bench_does_not_change_the_body(g1, published, field):
    """放上测试台以后，身体的每一样（质量、惯量、关节、摩擦、转子的惯量、碰撞的形状）都和文件原样的一样。"""
    assert np.array_equal(getattr(g1.model, field), getattr(published, field))


def test_joint_friction_and_rotor_inertia_are_the_ones_in_the_file(g1):
    """文件给每个关节写的摩擦（0.3 N·m）和转子的惯量（0.01 kg·m²）都留着。"""
    assert g1.model.dof_frictionloss[6:] == pytest.approx(np.full(29, 0.3))
    assert g1.model.dof_armature[6:] == pytest.approx(np.full(29, 0.01))


def test_imus_are_the_two_in_the_file(g1):
    """IMU 是文件里的两个：骨盆和躯干。"""
    assert g1.imus == IMUS
    assert [imu.label for imu in g1.imus] == ["骨盆", "躯干"]
    for imu in g1.imus:
        assert g1.model.sensor(imu.accelerometer).type[0] == mujoco.mjtSensor.mjSENS_ACCELEROMETER
        assert g1.model.sensor(imu.gyro).type[0] == mujoco.mjtSensor.mjSENS_GYRO


def test_only_the_visible_meshes_are_drawn(g1):
    """画图只画文件里看得见的那一组形状：都是网格，都不参加碰撞。"""
    model = g1.model
    assert g1.drawn_groups == (VISUAL_GROUP,)
    drawn = [geom for geom in range(model.ngeom) if model.geom_group[geom] == VISUAL_GROUP]
    assert len(drawn) == 35
    for geom in drawn:
        assert model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_MESH
        assert (model.geom_contype[geom], model.geom_conaffinity[geom]) == (0, 0)


# 测试台加的东西 --------------------------------------------------------------------------------------


def test_only_the_softness_of_the_drives_changed(g1, published):
    """文件里每个关节的刚度都是 500（没调过的）；测试台按峰值力矩重新定：膝 1390，腕上下 50。范围没变。"""
    assert published.actuator_gainprm[:, 0] == pytest.approx(np.full(29, PUBLISHED_STIFFNESS))
    names = [joint.name for joint in g1.joints]
    assert g1.model.actuator_gainprm[names.index(joint_name("knee", Side.LEFT)), 0] == pytest.approx(1390.0)
    assert g1.model.actuator_gainprm[names.index(joint_name("wrist_pitch", Side.LEFT)), 0] == pytest.approx(50.0)
    for index, joint in enumerate(g1.joints):
        assert g1.model.actuator_gainprm[index, 0] == pytest.approx(stiffness_for(joint.peak_torque_nm))
    assert np.array_equal(g1.model.actuator_ctrlrange, published.actuator_ctrlrange)


def test_foot_friction_in_the_file_gives_way_to_the_floor(g1, published):
    """文件给脚上的小球写的摩擦是 0.6、优先级是 1；放上测试台以后这两样还在，但地面的优先级更高，摩擦用地面的。"""
    for model in (published, g1.model):
        balls = [geom for geom in range(model.ngeom) if model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_SPHERE]
        assert len(balls) == 8
        for ball in balls:
            assert model.geom_friction[ball][0] == pytest.approx(PUBLISHED_FOOT_FRICTION)
            assert model.geom_priority[ball] == 1
    assert (PUBLISHED_STIFFNESS, PUBLISHED_FOOT_FRICTION) == (500.0, 0.6)
    assert g1.model.geom_friction[g1.model.geom(FLOOR).id][0] == pytest.approx(1.0)


def test_published_stand_pose_is_kept_under_another_name(g1, published):
    """文件自带的站姿（腿是直的）改名留着；测试台算的站姿（膝弯 15°）叫 stand。"""
    model = g1.model
    assert [model.key(index).name for index in range(model.nkey)] == [PUBLISHED_STAND_KEY, STAND_KEY]
    assert np.array_equal(model.key(PUBLISHED_STAND_KEY).qpos, published.key(STAND_KEY).qpos)
    knee = model.joint(joint_name("knee", Side.LEFT)).qposadr[0]
    assert model.key(PUBLISHED_STAND_KEY).qpos[knee] == 0.0
    assert model.key(STAND_KEY).qpos[knee] == pytest.approx(math.radians(15.0))


def test_published_model_stands_as_it_is(published):
    """文件原样的 G1（自带的站姿、自带的软硬、自带的步长）在同一块地面上也站得住 10 秒。"""
    data = mujoco.MjData(published)
    mujoco.mj_resetDataKeyframe(published, data, published.key(STAND_KEY).id)
    mujoco.mj_forward(published, data)
    pelvis = published.body("pelvis").id
    start_height = data.xpos[pelvis][Z]
    for _ in range(round(10.0 / published.opt.timestep)):
        mujoco.mj_step(published, data)
    assert published.opt.timestep == 0.002
    assert data.xpos[pelvis][Z] == pytest.approx(start_height, abs=0.01)
    assert data.xmat[pelvis].reshape(3, 3)[Z, Z] > math.cos(math.radians(2.0))
    assert np.abs(data.qvel).max() < 0.001


def test_sole_point_is_under_the_middle_of_the_foot_balls(g1):
    """脚底的点在四个小球的正中间、最低处；脚底着地的那一段长 18 cm。"""
    model = g1.model
    data = mujoco.MjData(model)
    mujoco.mj_kinematics(model, data)
    for leg in g1.anatomy.legs.values():
        foot = model.body(leg.foot).id
        balls = [
            geom
            for geom in range(model.ngeom)
            if model.geom_bodyid[geom] == foot and model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_SPHERE
        ]
        assert len(balls) == 4
        centers = np.array([data.geom_xpos[geom] for geom in balls])
        sole = data.site_xpos[model.site(leg.sole).id]
        assert sole[X] == pytest.approx((centers[:, X].min() + centers[:, X].max()) / 2)
        assert sole[Y] == pytest.approx((centers[:, Y].min() + centers[:, Y].max()) / 2)
        assert sole[Z] == pytest.approx(centers[:, Z].min() - BALL_RADIUS_M)
        assert g1.foot_length_m == pytest.approx(centers[:, X].max() - centers[:, X].min() + 2 * BALL_RADIUS_M)
    assert g1.foot_length_m == pytest.approx(0.18)


def test_arms_rest_where_the_file_puts_them(g1):
    """站着时手臂放在文件自带的站姿上：肩稍微往后、往外，肘弯着。腿上的三个关节是算出来的，不在这里面。"""
    expected = {
        joint_name("shoulder_pitch", Side.LEFT): 0.2,
        joint_name("shoulder_roll", Side.LEFT): 0.2,
        joint_name("elbow", Side.LEFT): 1.28,
        joint_name("shoulder_pitch", Side.RIGHT): 0.2,
        joint_name("shoulder_roll", Side.RIGHT): -0.2,
        joint_name("elbow", Side.RIGHT): 1.28,
    }
    assert g1.anatomy.relaxed_rad == pytest.approx(expected)
    for name, angle in expected.items():
        assert g1.stand.qpos[g1.model.joint(name).qposadr[0]] == angle


def test_anatomy_names_the_pelvis_the_torso_and_the_legs(g1):
    """测试台认得的地方：骨盆、躯干（推的地方）、两条腿上的关节、脚和脚底。"""
    anatomy = g1.anatomy
    assert (anatomy.root, anatomy.trunk) == ("pelvis", "torso_link")
    left = anatomy.legs[Side.LEFT]
    assert (left.hip_pitch, left.knee, left.ankle_pitch) == (
        "left_hip_pitch_joint",
        "left_knee_joint",
        "left_ankle_pitch_joint",
    )
    assert (left.foot, left.sole) == ("left_ankle_roll_link", "left_sole")
    assert anatomy.legs[Side.RIGHT].knee == "right_knee_joint"
    assert g1.model.geom(FLOOR).id >= 0


def test_loading_twice_gives_the_same_body(g1):
    """读两次，得到一样的身体和站姿。"""
    again = load_g1()
    assert again.stand == g1.stand
    assert again.joints == g1.joints
    assert again.height_m == g1.height_m


# 名字 ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("left_knee_joint", "左 膝"),
        ("right_hip_pitch_joint", "右 髋 前后"),
        ("waist_yaw_joint", "腰 转"),
        ("left_wrist_roll_joint", "左 前臂转"),
        ("right_ankle_roll_joint", "右 踝 侧"),
    ],
)
def test_joint_labels_are_in_chinese(name, label):
    """关节的中文名：左右加在前面，腰的关节没有左右。"""
    assert joint_label(name) == label


def test_every_joint_has_its_own_label(g1):
    """29 个关节都有中文名，没有重复的；表里也没有用不上的名字。"""
    labels = [joint.label for joint in g1.joints]
    assert len(set(labels)) == 29
    kinds = {joint.name.removeprefix("left_").removeprefix("right_").removesuffix("_joint") for joint in g1.joints}
    assert kinds == set(JOINT_LABELS)


def test_unknown_joint_has_no_label():
    """不认识的关节（比如换了一个带手指的文件）：报错，不瞎起名字。"""
    with pytest.raises(BaselineError, match="不认识的关节：left_thumb_0_joint"):
        joint_label("left_thumb_0_joint")


def test_joint_name_follows_the_file():
    """关节在文件里的名字：左右在前，后面是 _joint。"""
    assert joint_name("knee", Side.LEFT) == "left_knee_joint"
    assert joint_name("waist_roll") == "waist_roll_joint"


# 文件和这里以为的不一样的时候 ------------------------------------------------------------------------


def test_rejects_a_model_with_a_different_number_of_drives():
    """驱动器不是 29 个（比如换成了带手的文件）：报错。"""
    spec = read_g1_spec()
    spec.delete(spec.actuators[-1])
    with pytest.raises(BaselineError, match="应该是 29 个驱动器的 G1，这个文件有 28 个"):
        put_on_bench(spec)


def test_rejects_a_model_without_the_published_stand_pose():
    """文件里没有自带的站姿：报错。"""
    spec = read_g1_spec()
    spec.keys[0].name = "home"
    with pytest.raises(BaselineError, match="应该正好有一个叫 stand 的站姿，找到 0 个"):
        put_on_bench(spec)


def test_rejects_a_drive_that_is_not_a_position_servo():
    """有一个驱动器不是位置控制（换成了直接给力矩的）：报错。"""
    spec = read_g1_spec()
    spec.actuators[3].set_to_motor()
    with pytest.raises(BaselineError, match="left_knee_joint：不是这里以为的那种驱动器"):
        put_on_bench(spec)


@pytest.mark.parametrize("limits", [(-88.0, 50.0), (0.0, 0.0)], ids=["上下限不对称", "没有写上限"])
def test_rejects_a_joint_without_a_symmetric_torque_limit(limits):
    """关节的力矩上下限不对称，或者没有写：不知道峰值力矩是多少，报错。"""
    spec = read_g1_spec()
    spec.joint("left_hip_pitch_joint").actfrcrange = list(limits)
    with pytest.raises(BaselineError, match="left_hip_pitch_joint：不是这里以为的那种驱动器"):
        put_on_bench(spec)


def test_rejects_a_foot_without_contact_balls():
    """脚上没有和地面接触的小球（文件换了脚的做法）：找不到脚底，报错。"""
    spec = read_g1_spec()
    foot = spec.body("left_ankle_roll_link")
    for geom in [geom for geom in foot.geoms if geom.type == mujoco.mjtGeom.mjGEOM_SPHERE]:
        spec.delete(geom)
    with pytest.raises(BaselineError, match="left_ankle_roll_link 上没有和地面接触的小球"):
        put_on_bench(spec)


def test_tells_how_to_download_when_the_files_are_missing(tmp_path):
    """清单在、文件还没下载：报错里写着要运行哪条命令。"""
    shutil.copy(THIRD_PARTY_DIR / f"{G1_ASSETS}.json", tmp_path)
    with pytest.raises(AssetError, match="unitree_g1 的文件和清单对不上") as error:
        load_g1(tmp_path)
    assert FETCH_COMMAND in str(error.value)


def test_refuses_a_model_file_that_was_edited(tmp_path):
    """模型文件被人改过一个字：和清单对不上，不用它。"""
    shutil.copy(THIRD_PARTY_DIR / f"{G1_ASSETS}.json", tmp_path)
    shutil.copytree(THIRD_PARTY_DIR / G1_ASSETS, tmp_path / G1_ASSETS)
    edited = tmp_path / G1_ASSETS / G1_MODEL_FILE
    edited.write_bytes(edited.read_bytes().replace(b'mass="7.818"', b'mass="7.819"'))
    with pytest.raises(AssetError, match=r"g1\.xml 的内容和清单不一样"):
        load_g1(tmp_path)


def test_needs_the_manifest(tmp_path):
    """连清单都没有：报错。"""
    with pytest.raises(ManifestError, match="读不出来"):
        load_g1(tmp_path)
