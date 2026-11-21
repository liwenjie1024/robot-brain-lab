"""脊髓层（C++）接到测试台的身体上的测试（真的跑物理）：照模型建得对（Nova 的 5 对并联、G1 写在关节上的力矩上限）；
从驱动器的读数算出来的关节角度和仿真里的一样；驱动器照命令出的力，在仿真里换回关节正好是要的力矩
（并联的一对两个关节软硬不一样也一样）；Nova 经过脊髓层站着，和以前直接给驱动器目标一模一样。"""

import copy
import math

import mujoco
import nova_rt
import numpy as np
import pytest

from nova_body import actuation
from nova_body.actuation import DriveLayer
from nova_body.bench import STAND_KEY
from nova_body.spine import (
    JointCommand,
    SpineError,
    impedance_command,
    joint_gains_from_actuators,
    spine_for,
    spine_joints,
    stand_command,
    step_spine,
)
from nova_body.standing import drive_layer, tilt_deg

STAND_SECONDS = 2.0


def stand_data(model: mujoco.MjModel) -> mujoco.MjData:
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, STAND_KEY))
    mujoco.mj_forward(model, data)
    return data


def test_the_nova_spine_has_its_five_parallel_pairs(nova):
    """照 Nova 的模型建：67 个关节、67 个驱动器，5 对并联（腰、两个腕、两个踝），别的一个驱动器带一个关节。"""
    spine = spine_for(nova.body.model)
    assert spine.joint_count == 67
    assert spine.actuator_count == 67
    pairs = [joints for _, joints in spine.groups if len(joints) == 2]
    assert len(pairs) == 5
    names = {spine.joint_names[joint] for pair in pairs for joint in pair}
    assert {"lumbar_pitch", "lumbar_roll", "left_ankle_pitch", "left_ankle_roll"} <= names
    assert spine.joint_names == [joint.name for joint in nova.body.joints]


def test_joint_angles_come_back_from_the_actuator_readings(nova):
    """从驱动器的读数（肌腱的长度）算出来的关节角度、转速，和仿真里的一样（站姿上再随便动一动）。"""
    model = nova.body.model
    spine = spine_for(model)
    data = stand_data(model)
    rng = np.random.default_rng(3)
    joints = spine_joints(model)
    data.qpos[model.jnt_qposadr[joints]] += rng.uniform(-0.1, 0.1, len(joints))
    data.qvel[model.jnt_dofadr[joints]] = rng.uniform(-1.0, 1.0, len(joints))
    mujoco.mj_forward(model, data)
    np.testing.assert_allclose(
        spine.joints_from_actuators(data.actuator_length.copy()), data.qpos[model.jnt_qposadr[joints]], atol=1e-12
    )
    np.testing.assert_allclose(
        spine.joints_from_actuators(data.actuator_velocity.copy()), data.qvel[model.jnt_dofadr[joints]], atol=1e-12
    )


def test_actuator_commands_give_the_wanted_joint_torques_in_the_simulation(nova):
    """驱动器照命令出力（在仿真里真的算），换回关节正好是要的力矩；踝的前后、内外翻软硬差 5 倍也一样。"""
    model = copy.copy(nova.body.model)
    spine = spine_for(model)
    data = stand_data(model)
    joints = spine_joints(model)
    rng = np.random.default_rng(7)
    count = len(joints)
    # 每个关节按自己的峰值取（手指只有一两 N·m）：偏 0.02 弧度出峰值的 5%~15%，前馈不超过 10%，都不碰限制。
    peaks = np.array([joint.peak_torque_nm for joint in nova.body.joints])
    stiffness = rng.uniform(0.05, 0.15, count) * peaks / 0.02
    names = spine.joint_names
    roll = names.index("left_ankle_roll")
    stiffness[roll] = 0.05 * peaks[roll] / 0.02
    stiffness[names.index("left_ankle_pitch")] = 5.0 * stiffness[roll]
    command = JointCommand(
        position_rad=data.qpos[model.jnt_qposadr[joints]] + rng.uniform(-0.02, 0.02, count),
        velocity_rad_s=rng.uniform(-0.1, 0.1, count),
        stiffness_nm_per_rad=stiffness,
        damping_nms_per_rad=rng.uniform(0.0, 0.02, count) * peaks,
        torque_nm=rng.uniform(-0.1, 0.1, count) * peaks,
    )
    data.qvel[model.jnt_dofadr[joints]] = rng.uniform(-0.2, 0.2, count)
    mujoco.mj_forward(model, data)
    result = step_spine(spine, data, command)
    assert not result.limited.any()
    layer = DriveLayer(model, [None] * model.nu)
    layer.command_impedance(impedance_command(result))
    for _ in range(actuation.COMMAND_DELAY_STEPS + 1):
        layer.before_step(data)
        layer.after_step(data, 0.0)
    mujoco.mj_forward(model, data)
    q = data.qpos[model.jnt_qposadr[joints]]
    qd = data.qvel[model.jnt_dofadr[joints]]
    wanted = (
        stiffness * (command.position_rad - q)
        + command.damping_nms_per_rad * (command.velocity_rad_s - qd)
        + command.torque_nm
    )
    np.testing.assert_allclose(data.qfrc_actuator[model.jnt_dofadr[joints]], wanted, rtol=1e-9, atol=1e-9)


def test_nova_stands_through_the_spine_exactly_as_with_actuator_targets(nova):
    """Nova 站 2 秒：经过脊髓层（站姿当成关节的命令）和以前直接给驱动器目标，骨盆的高度、歪了多少一样。"""
    body = nova.body
    model_a, model_b = copy.copy(body.model), copy.copy(body.model)
    data_a, data_b = stand_data(model_a), stand_data(model_b)
    drives_a, drives_b = drive_layer(body, model_a), drive_layer(body, model_b)
    spine = spine_for(model_b, [actuator.drive for actuator in body.actuators])
    command = stand_command(body, model_b, spine)
    drives_a.command(body.stand.ctrl)
    steps = round(STAND_SECONDS / model_a.opt.timestep)
    limited = 0
    for _ in range(steps):
        actuation.step(model_a, data_a, drives_a)
        result = step_spine(spine, data_b, command)
        limited += int(result.limited.any())
        drives_b.command_impedance(impedance_command(result))
        actuation.step(model_b, data_b, drives_b)
    root = mujoco.mj_name2id(model_a, mujoco.mjtObj.mjOBJ_BODY, body.anatomy.root)
    assert limited == 0
    assert data_b.xpos[root][2] == pytest.approx(data_a.xpos[root][2], abs=1e-4)
    assert tilt_deg(data_b, root) == pytest.approx(tilt_deg(data_a, root), abs=0.01)
    assert tilt_deg(data_b, root) < 2.0


def test_pair_joints_get_twice_one_actuators_stiffness(nova):
    """并联的一对两个驱动器一样硬：换到关节上，每个关节是一个驱动器的两倍（两个一起顶）；单独的就是它自己的。"""
    model = nova.body.model
    spine = spine_for(model)
    stiffness, _ = joint_gains_from_actuators(spine, np.full(model.nu, 100.0), np.full(model.nu, 5.0))
    names = spine.joint_names
    assert stiffness[names.index("left_ankle_pitch")] == pytest.approx(200.0)
    assert stiffness[names.index("left_knee")] == pytest.approx(100.0)


def test_g1_torque_limits_written_on_its_joints_are_used(g1):
    """G1 的力矩上限写在关节上（驱动器不限）：脊髓层的峰值力矩用关节上的（膝 139 N·m），超了就剪到它。"""
    spine = spine_for(g1.model)
    knee = spine.joint_names.index("left_knee_joint")
    model = g1.model
    joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "left_knee_joint")
    assert spine.joint_count == 29
    probe = JointCommand(
        position_rad=np.full(29, 0.0),
        velocity_rad_s=np.zeros(29),
        stiffness_nm_per_rad=np.full(29, 1e4),
        damping_nms_per_rad=np.zeros(29),
        torque_nm=np.zeros(29),
    )
    data = mujoco.MjData(model)
    data.qpos[model.jnt_qposadr[joint]] = -1.0  # 离目标 1 弧度，要 1 万 N·m
    mujoco.mj_forward(model, data)
    result = step_spine(spine, data, probe)
    assert result.joint_torque[knee] == pytest.approx(model.jnt_actfrcrange[joint, 1])
    assert result.limited[knee] & nova_rt.LIMIT_TORQUE


def test_drive_models_give_speed_and_power_limits(nova):
    """有驱动器的模型：膝转得比空载转速还快时不再往这个方向推（标"转速"）。"""
    body = nova.body
    model = copy.copy(body.model)
    spine = spine_for(model, [actuator.drive for actuator in body.actuators])
    names = spine.joint_names
    knee = names.index("left_knee")
    drive = next(actuator.drive for actuator in body.actuators if actuator.joints == (("left_knee", 1.0),))
    data = stand_data(model)
    joints = spine_joints(model)
    data.qvel[model.jnt_dofadr[joints[knee]]] = 1.1 * drive.no_load_speed_rad_s
    mujoco.mj_forward(model, data)
    count = len(joints)
    command = JointCommand(
        position_rad=data.qpos[model.jnt_qposadr[joints]] + 0.5,
        velocity_rad_s=np.zeros(count),
        stiffness_nm_per_rad=np.full(count, 10.0),
        damping_nms_per_rad=np.zeros(count),
        torque_nm=np.zeros(count),
    )
    result = step_spine(spine, data, command)
    assert result.limited[knee] & nova_rt.LIMIT_SPEED
    assert result.joint_torque[knee] == pytest.approx(0.0, abs=1e-9)


def test_an_actuator_that_is_not_position_controlled_is_refused():
    """只出力的驱动器（motor）接不了目标和软硬：拒绝，说是哪一个。"""
    spec = mujoco.MjSpec()
    body = spec.worldbody.add_body(name="link")
    body.add_joint(name="joint", type=mujoco.mjtJoint.mjJNT_HINGE)
    body.add_geom(type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.1, 0, 0], mass=1.0)
    spec.add_actuator(name="motor", trntype=mujoco.mjtTrn.mjTRN_JOINT, target="joint")
    with pytest.raises(SpineError, match="驱动器 motor 不是位置控制的"):
        spine_for(spec.compile())


def test_unlimited_joints_and_forces_are_infinite_limits():
    """没写范围的关节、没限力的驱动器：上限是无穷大（不限），不是 0。"""
    spec = mujoco.MjSpec()
    body = spec.worldbody.add_body(name="link")
    body.add_joint(name="joint", type=mujoco.mjtJoint.mjJNT_HINGE)
    body.add_geom(type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.1, 0, 0], mass=1.0)
    actuator = spec.add_actuator(name="servo", trntype=mujoco.mjtTrn.mjTRN_JOINT, target="joint")
    actuator.set_to_position(kp=10.0)
    model = spec.compile()
    spine = spine_for(model)
    data = mujoco.MjData(model)
    command = JointCommand(np.array([math.pi * 10]), np.zeros(1), np.array([1e3]), np.zeros(1), np.zeros(1))
    result = step_spine(spine, data, command)
    assert result.limited[0] == 0
    assert result.joint_torque[0] == pytest.approx(1e3 * math.pi * 10)


@pytest.mark.parametrize(
    ("ctrllimited", "limited"), [(True, True), (False, False)], ids=["驱动器限了目标", "驱动器不限目标"]
)
def test_targets_are_kept_in_range_only_if_the_actuator_limits_them(ctrllimited, limited):
    """关节有范围（±1 弧度）：驱动器限了目标（Nova 的都限了），给到范围外面的目标截回范围里，并且说是角度改的；
    驱动器不限目标（mjlab 的 G1、SONIC 的 G1，练的时候就能给到外面），照给的目标出力，不改。"""
    spec = mujoco.MjSpec()
    body = spec.worldbody.add_body(name="link")
    body.add_joint(
        name="joint", type=mujoco.mjtJoint.mjJNT_HINGE, limited=mujoco.mjtLimited.mjLIMITED_TRUE, range=[-1.0, 1.0]
    )
    body.add_geom(type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.1, 0, 0], mass=1.0)
    actuator = spec.add_actuator(name="servo", trntype=mujoco.mjtTrn.mjTRN_JOINT, target="joint")
    actuator.set_to_position(kp=10.0)
    actuator.ctrllimited = mujoco.mjtLimited.mjLIMITED_TRUE if ctrllimited else mujoco.mjtLimited.mjLIMITED_FALSE
    actuator.ctrlrange = [-1.0, 1.0]
    model = spec.compile()
    result = step_spine(
        spine_for(model),
        mujoco.MjData(model),
        JointCommand(np.array([1.5]), np.zeros(1), np.array([10.0]), np.zeros(1), np.zeros(1)),
    )
    assert bool(result.limited[0] & nova_rt.LIMIT_ANGLE) == limited
    if limited:
        assert result.joint_torque[0] < 10.0 * 1.0
    else:
        assert result.joint_torque[0] == pytest.approx(10.0 * 1.5)
