"""状态估计接到测试台上的测试（真的跑物理）：腿的运动学算的脚的位置对；着地的判断（两个门槛、来回）；
仿真里脚和地面的接触力加起来是体重；Nova 站着、被推一下都估得准（骨盆上是高精度的 IMU）；身体的设置。"""

import copy
import math

import mujoco
import numpy as np
import pytest

from nova_body import actuation
from nova_body.bench import FLOOR, STAND_KEY
from nova_body.body import ImuGrade
from nova_body.estimation import (
    POLICY_BODY_SETUPS,
    BodyFeel,
    ContactDetector,
    GroundContact,
    LegKinematics,
    setup_for_body,
    setup_for_policy_body,
    tilt_error_deg,
)
from nova_body.spine import spine_for, spine_joints
from nova_body.standing import drive_layer

STAND_SECONDS = 5.0
CHECK_EVERY = 50


def stand_data(model: mujoco.MjModel) -> mujoco.MjData:
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, STAND_KEY))
    mujoco.mj_forward(model, data)
    return data


def stand_and_estimate(nova, seconds: float, push_n: float = 0.0):
    """Nova 照站姿站着（第 1 秒推一下骨盆 0.2 秒），状态估计跟着跑：回速度、歪斜的差，和被推时真的最快速度。"""
    body = nova.body
    model = copy.copy(body.model)
    data = stand_data(model)
    drives = drive_layer(body, model)
    drives.command(body.stand.ctrl)
    feel = BodyFeel(model, setup_for_body(body, model), spine_for(model), data)
    root = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body.anatomy.root)
    timestep = float(model.opt.timestep)
    speeds, tilts, fastest = [], [], 0.0
    for step in range(round(seconds / timestep)):
        pushing = 1.0 <= step * timestep < 1.2
        data.xfrc_applied[root, 0] = push_n if pushing else 0.0
        feel.step(data, timestep)
        actuation.step(model, data, drives)
        feel.sample(data)
        if step % CHECK_EVERY == 0:
            speed, tilt = feel.errors(data)
            speeds.append(speed)
            tilts.append(tilt)
            fastest = max(fastest, float(np.linalg.norm(data.qvel[:3])))
    return speeds, tilts, fastest, feel


def test_leg_kinematics_gives_the_feet_seen_from_the_imu(nova):
    """腿的运动学（骨盆放在原点）算的脚底的点在 IMU 坐标里的位置，和整个仿真里看到的一样（骨盆随便放、关节随便动）。"""
    model = copy.copy(nova.body.model)
    setup = setup_for_body(nova.body, model)
    data = stand_data(model)
    joints = spine_joints(model)
    rng = np.random.default_rng(5)
    data.qpos[model.jnt_qposadr[joints]] += rng.uniform(-0.2, 0.2, len(joints))
    data.qpos[:3] = [0.3, -0.7, 1.1]
    data.qpos[3:7] = [math.cos(0.4), 0.2, 0.3, math.sin(0.4)]
    data.qpos[3:7] /= np.linalg.norm(data.qpos[3:7])
    mujoco.mj_forward(model, data)
    legs = LegKinematics(model, joints, setup.imu_site, setup.feet)
    feet = legs.feet_in_imu(data.qpos[model.jnt_qposadr[joints]])
    imu = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, setup.imu_site)
    sole_ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, foot) for foot in setup.feet]
    expected = (data.site_xpos[sole_ids] - data.site_xpos[imu]) @ data.site_xmat[imu].reshape(3, 3)
    np.testing.assert_allclose(feet, expected, atol=1e-12)


def test_contact_detection_uses_two_thresholds():
    """大过 100 N 才算着地，小过 50 N 才算抬起来；中间照上一次的；正好 50 N 不算抬起。"""
    detector = ContactDetector(2, on_n=100.0, off_n=50.0)
    np.testing.assert_array_equal(detector.update([120.0, 70.0]), [True, False])
    np.testing.assert_array_equal(detector.update([70.0, 120.0]), [True, True])
    np.testing.assert_array_equal(detector.update([40.0, 50.0]), [False, True])
    np.testing.assert_array_equal(detector.update([40.0, 49.9]), [False, False])
    detector.reset()
    np.testing.assert_array_equal(detector.state, [False, False])


@pytest.mark.parametrize(("on_n", "off_n"), [(50.0, 50.0), (40.0, 60.0), (10.0, -1.0)], ids=["一样高", "反了", "负的"])
def test_contact_thresholds_must_be_ordered(on_n, off_n):
    """着地的门槛要比抬起来的高，抬起来的不能是负的。"""
    with pytest.raises(ValueError, match="门槛"):
        ContactDetector(2, on_n=on_n, off_n=off_n)


def test_contact_forces_of_the_wrong_length_are_refused():
    """脚上的力给的个数不对就拒绝。"""
    with pytest.raises(ValueError, match="要给 2 个"):
        ContactDetector(2, on_n=100.0, off_n=50.0).update([1.0, 2.0, 3.0])


def test_ground_contact_adds_up_to_the_weight(nova):
    """Nova 站稳以后，仿真里两只脚和地面之间的力加起来是体重（差 5% 以内）。"""
    body = nova.body
    model = copy.copy(body.model)
    data = stand_data(model)
    drives = drive_layer(body, model)
    drives.command(body.stand.ctrl)
    for _ in range(500):
        actuation.step(model, data, drives)
    setup = setup_for_body(body, model)
    forces = GroundContact(model, setup.foot_bodies, FLOOR).forces(data)
    weight = mujoco.mj_getTotalmass(model) * 9.81
    assert forces.sum() == pytest.approx(weight, rel=0.05)
    assert forces.min() > 0.3 * weight


def test_nova_standing_is_estimated_closely(nova):
    """Nova 站 5 秒（骨盆上是高精度的 IMU）：速度一直差不到 1 cm/s；歪斜开头最多差 0.2°（零偏还没估出来），
    最后差不到 0.03°；横滚、俯仰的角速度零偏估准了（差不到 0.01 °/s）。"""
    speeds, tilts, _, feel = stand_and_estimate(nova, STAND_SECONDS)
    assert max(speeds) < 0.01
    assert max(tilts) < 0.2
    assert tilts[-1] < 0.03
    bias_error = np.degrees(feel.estimator.gyro_bias[:2] - feel.true_gyro_bias[:2])
    np.testing.assert_allclose(bias_error, 0.0, atol=0.01)


def test_a_push_is_followed(nova):
    """站着被推一下（体重的 10%，0.2 秒）：身体动起来（最快超过 5 cm/s），估出来的速度一直差不到 2 cm/s。"""
    weight = mujoco.mj_getTotalmass(nova.body.model) * 9.81
    speeds, tilts, fastest, _ = stand_and_estimate(nova, 2.0, push_n=0.10 * weight)
    assert fastest > 0.05
    assert max(speeds) < 0.02
    assert max(tilts) < 0.2


def test_the_setup_uses_the_precise_pelvis_imu_and_the_soles(nova):
    """Nova 的状态估计用骨盆上的高精度 IMU，两只脚底正中间的点。"""
    setup = setup_for_body(nova.body, nova.body.model)
    assert setup.grade == ImuGrade.PRECISE
    assert setup.accelerometer == "pelvis_imu_acc"
    assert set(setup.feet) == {"left_sole", "right_sole"}


def test_an_unknown_policy_body_is_refused():
    """测试台不认识的身体（不知道 IMU、脚在哪）就拒绝；练 G1 的那个认得。"""
    assert "unitree_g1" in POLICY_BODY_SETUPS
    with pytest.raises(ValueError, match="不知道身体 robot_x"):
        setup_for_policy_body("robot_x")


def test_tilt_error_ignores_yaw():
    """歪斜的差只看横滚、俯仰：绕竖轴转多少都是 0°，绕前后的轴转 10° 就是 10°。"""
    yaw = np.array([[math.cos(1.0), -math.sin(1.0), 0.0], [math.sin(1.0), math.cos(1.0), 0.0], [0.0, 0.0, 1.0]])
    roll = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(math.radians(10)), -math.sin(math.radians(10))],
            [0.0, math.sin(math.radians(10)), math.cos(math.radians(10))],
        ]
    )
    assert tilt_error_deg(yaw, np.eye(3)) == pytest.approx(0.0, abs=1e-9)
    assert tilt_error_deg(roll, np.eye(3)) == pytest.approx(10.0)
