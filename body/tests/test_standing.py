"""站着的测试：在仿真里真的站 10 秒；不给控制会倒；轻推不倒、用力推会倒；传感器读到的对得上。"""

import math
from dataclasses import replace

import mujoco
import numpy as np
import pytest

from nova_body.mass_closure import GRAVITY_M_S2
from nova_body.model import (
    ACCELERATION_SUFFIX,
    CONTACT_SUFFIX,
    FORCE_SUFFIX,
    GYRO_SUFFIX,
    HEAD_IMU,
    MOMENT_SUFFIX,
    PELVIS_IMU,
    ankle_ft_site,
    tip_force_sensor,
    wrist_ft_site,
)
from nova_body.skeleton import LINKS, Side, sides_of
from nova_body.standing import (
    MAX_TILT_DEG,
    STAND_SECONDS,
    Push,
    StandingResult,
    floor_support,
    measure_realtime_factor,
    pressure_center_from_ankle,
    read_sensor,
    simulate_standing,
    standing_data,
    stood_well,
)

X, Y, Z = 0, 1, 2
FREE_JOINT_POSITIONS = 7
GENTLE_PUSH_N = 30.0
HARD_PUSH_N = 300.0
SETTLE_STEPS = 3000


@pytest.fixture(scope="module")
def stood(nova) -> StandingResult:
    """站 10 秒的结果，只仿真一次。"""
    return simulate_standing(nova)


@pytest.fixture(scope="module")
def settled(nova) -> mujoco.MjData:
    """站了 3 秒、已经静下来的状态。"""
    data = standing_data(nova.model)
    for _ in range(SETTLE_STEPS):
        mujoco.mj_step(nova.model, data)
    return data


# 站住 ------------------------------------------------------------------------------------------------


def test_stands_for_ten_seconds(stood):
    """用关节控制站满 10 秒：没倒，几乎没歪、没塌，脚没滑，最后是静止的。"""
    assert stood.seconds == pytest.approx(STAND_SECONDS)
    assert not stood.fell
    assert stood.max_tilt_deg < MAX_TILT_DEG
    assert stood_well(stood)


def test_floor_carries_the_whole_weight(stood, nova):
    """最后地面托着的力等于体重。"""
    assert stood.weight_n == pytest.approx(nova.budget.total_kg * GRAVITY_M_S2)
    assert stood.support_force_n == pytest.approx(stood.weight_n, rel=1e-3)


def test_pressure_center_is_in_the_middle_of_the_foot(stood):
    """压力中心在脚的正中间（差不到 2 mm）：重心就在它上面。"""
    assert stood.pressure_center_from_heel_m == pytest.approx(stood.foot_length_m / 2, abs=0.002)


def test_body_stays_at_the_stand_pose(nova, settled):
    """站姿是平衡的位置：站了几秒，每个关节离站姿不到 0.1°，骨盆没有移动超过 1 mm。"""
    joints_start = FREE_JOINT_POSITIONS
    stand = np.array(nova.stand.qpos)
    assert np.abs(settled.qpos[joints_start:] - stand[joints_start:]).max() < math.radians(0.1)
    assert np.abs(settled.qpos[:3] - stand[:3]).max() < 0.001


def test_motors_give_the_holding_torque(nova, settled):
    """站着时每个驱动器出的力矩，就是站姿里算好的"顶住重力要的力矩"。"""
    torques = settled.actuator_force
    for index, joint in enumerate(nova.actuated_joints):
        assert torques[index] == pytest.approx(nova.stand.holding_torque_nm[index], abs=0.02 * joint.peak_torque_nm)
    ankle = [joint.name for joint in nova.actuated_joints].index("left_ankle_pitch")
    assert torques[ankle] == pytest.approx(nova.stand.holding_torque_nm[ankle], rel=0.02)


def test_standing_is_repeatable(nova, stood):
    """同样的开始再站一次，结果一模一样。"""
    assert simulate_standing(nova) == stood


def test_falls_without_control(nova):
    """驱动器不出力时，1 秒之内就倒了：是控制让它站住的。"""
    limp = simulate_standing(nova, 3.0, controlled=False)
    assert limp.fell
    assert limp.seconds < 1.0
    assert not stood_well(limp)


def test_limp_run_does_not_change_the_shared_model(nova):
    """ "不出力"是在模型的副本上做的，原来的模型还是有驱动的。"""
    simulate_standing(nova, 0.1, controlled=False)
    assert not nova.model.opt.disableflags & mujoco.mjtDisableBit.mjDSBL_ACTUATION


@pytest.mark.parametrize(
    "direction",
    [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, -1.0, 0.0)],
    ids=["往前推", "往后推", "往左推", "往右推"],
)
def test_survives_a_gentle_push(nova, direction):
    """在胸上轻推 30 N、0.5 秒，四个方向都不倒，之后又静下来。"""
    push = Push(tuple(GENTLE_PUSH_N * axis for axis in direction))
    result = simulate_standing(nova, 5.0, push)
    assert not result.fell
    assert result.max_tilt_deg < 5.0
    assert result.end_joint_speed_rad_s < 0.01


def test_hard_push_knocks_it_over(nova):
    """用力推 300 N 就倒了：现在只是关节顶着，没有平衡的控制。"""
    result = simulate_standing(nova, 5.0, Push((HARD_PUSH_N, 0.0, 0.0)))
    assert result.fell
    assert result.seconds < 5.0


def test_left_and_right_pushes_are_mirror_images(nova):
    """往左推和往右推，歪的程度一样（身体是对称的）。"""
    left = simulate_standing(nova, 3.0, Push((0.0, GENTLE_PUSH_N, 0.0)))
    right = simulate_standing(nova, 3.0, Push((0.0, -GENTLE_PUSH_N, 0.0)))
    assert left.max_tilt_deg == pytest.approx(right.max_tilt_deg, rel=1e-6)


@pytest.mark.parametrize("seconds", [0.0, -1.0], ids=["0 秒", "负的时间"])
def test_rejects_non_positive_duration(nova, seconds):
    """仿真的时间不是正数时拒绝。"""
    with pytest.raises(ValueError, match="仿真的时间必须大于 0"):
        simulate_standing(nova, seconds)


@pytest.mark.parametrize(
    ("time_s", "active"),
    [(0.99, False), (1.0, True), (1.49, True), (1.5, False), (3.0, False)],
    ids=["开始之前", "正好开始", "快结束", "正好结束", "结束以后"],
)
def test_push_is_active_only_during_its_window(time_s, active):
    """推从 1 秒开始、持续 0.5 秒：开始的那一刻算，结束的那一刻不算。"""
    assert Push((10.0, 0.0, 0.0), start_s=1.0, duration_s=0.5).is_active(time_s) is active


def test_stood_well_needs_every_condition(stood):
    """合不合格要每一条都过：倒了、歪了、塌了、脚滑了、还在动、地面托的力不对，任何一条都不合格。"""
    assert stood_well(stood)
    assert not stood_well(replace(stood, fell=True))
    assert not stood_well(replace(stood, max_tilt_deg=2.5))
    assert not stood_well(replace(stood, pelvis_drop_m=0.01))
    assert not stood_well(replace(stood, foot_slip_m=0.002))
    assert not stood_well(replace(stood, end_joint_speed_rad_s=0.01))
    assert not stood_well(replace(stood, support_force_n=0.9 * stood.weight_n))


# 传感器 ----------------------------------------------------------------------------------------------


def test_ankle_sensors_carry_the_body_above_the_feet(nova, settled):
    """踝部的力传感器：两只脚各压着一半的"体重减去脚"。"""
    model = nova.model
    foot_kg = float(model.body_subtreemass[model.body("left_foot").id])
    expected = (nova.budget.total_kg - 2 * foot_kg) * GRAVITY_M_S2 / 2
    for side in Side:
        force = read_sensor(model, settled, ankle_ft_site(side) + FORCE_SUFFIX)
        assert -force[Z] == pytest.approx(expected, rel=1e-3)


def test_pressure_center_from_ankle_sensor_matches_the_contacts(nova, settled):
    """用踝部力传感器算出来的压力中心，和直接从脚底的接触点算的差不到 2 mm。"""
    model = nova.model
    floor = model.geom("floor").id
    for side in Side:
        sole = model.geom(f"{side.value}_foot.sole").id
        total, weighted = 0.0, np.zeros(3)
        force = np.zeros(6)
        for index in range(settled.ncon):
            contact = settled.contact[index]
            if {int(contact.geom[0]), int(contact.geom[1])} == {floor, sole}:
                mujoco.mj_contactForce(model, settled, index, force)
                total += force[0]
                weighted += force[0] * contact.pos
        truth = weighted / total - settled.site_xpos[model.site(ankle_ft_site(side)).id]
        forward, left = pressure_center_from_ankle(
            read_sensor(model, settled, ankle_ft_site(side) + FORCE_SUFFIX),
            read_sensor(model, settled, ankle_ft_site(side) + MOMENT_SUFFIX),
            nova.dimensions.ankle_height,
        )
        assert forward == pytest.approx(truth[X], abs=0.002)
        assert left == pytest.approx(truth[Y], abs=0.002)


def test_pressure_center_needs_a_loaded_foot():
    """脚没有踩在地上（没有往下压的力）时，没有压力中心：报错。"""
    with pytest.raises(ValueError, match="没有踩在地上"):
        pressure_center_from_ankle(np.array([0.0, 0.0, 5.0]), np.zeros(3), 0.066)
    with pytest.raises(ValueError, match="没有踩在地上"):
        pressure_center_from_ankle(np.zeros(3), np.zeros(3), 0.066)


def test_pressure_center_formula():
    """压 100 N、力矩 5 N·m：压力中心在踝前面 5 cm；有水平力时按踝的高度修正。"""
    forward, left = pressure_center_from_ankle(np.array([0.0, 0.0, -100.0]), np.array([0.0, 5.0, 0.0]), 0.066)
    assert (forward, left) == pytest.approx((0.05, 0.0))
    forward, left = pressure_center_from_ankle(np.array([10.0, -10.0, -100.0]), np.array([2.0, 5.0, 0.0]), 0.1)
    assert (forward, left) == pytest.approx((0.06, -0.03))


def test_imus_feel_gravity_and_no_rotation(nova, settled):
    """站着不动时，骨盆和头的 IMU 量到的加速度是重力（朝上 9.81），角速度是 0。"""
    for site in (PELVIS_IMU, HEAD_IMU):
        acceleration = read_sensor(nova.model, settled, site + ACCELERATION_SUFFIX)
        assert np.linalg.norm(acceleration) == pytest.approx(GRAVITY_M_S2, rel=1e-3)
        assert acceleration[Z] == pytest.approx(GRAVITY_M_S2, rel=1e-3)
        assert read_sensor(nova.model, settled, site + GYRO_SUFFIX) == pytest.approx(np.zeros(3), abs=1e-3)


def test_wrist_sensors_carry_the_hands(nova, settled):
    """手垂着时，腕部的力传感器量到的就是手的重量。"""
    model = nova.model
    hand_kg = float(model.body_subtreemass[model.body("left_hand").id])
    for side in Side:
        force = read_sensor(model, settled, wrist_ft_site(side) + FORCE_SUFFIX)
        assert np.linalg.norm(force) == pytest.approx(hand_kg * GRAVITY_M_S2, rel=1e-3)


def test_only_the_feet_feel_contact(nova, settled):
    """全身的接触力：两只脚各被地面往上托着一半体重，别的地方和指尖都是 0。"""
    model = nova.model
    half_weight = nova.budget.total_kg * GRAVITY_M_S2 / 2
    for part in LINKS:
        for side in sides_of(part):
            name = part.key if side is None else f"{side.value}_{part.key}"
            force = read_sensor(model, settled, name + CONTACT_SUFFIX)
            if part.key == "foot":
                assert force[Z] == pytest.approx(half_weight, rel=1e-3), name
            else:
                assert force == pytest.approx(np.zeros(3)), name
    for side in Side:
        assert read_sensor(model, settled, tip_force_sensor(side, "index")) == pytest.approx(np.zeros(3))


def test_fingertip_sensor_feels_a_touch(nova):
    """把腿收起来、身体放低，让两只手的中指指尖先碰到地面：指尖的力传感器量到往上的力，别的地方没有。"""
    model = nova.model
    data = mujoco.MjData(model)
    tucked = {"hip_pitch": 130.0, "knee": 150.0, "ankle_pitch": 20.0}
    for side in Side:
        for key, degrees in tucked.items():
            data.qpos[model.joint(f"{side.value}_{key}").qposadr[0]] = math.radians(degrees)
    mujoco.mj_forward(model, data)
    tip_height = data.site_xpos[model.site("left_middle_tip").id][Z]
    # 指尖压进地面 2 mm。
    data.qpos[Z] -= tip_height + 0.002
    mujoco.mj_forward(model, data)
    for side in Side:
        touch = read_sensor(model, data, tip_force_sensor(side, "middle"))
        assert touch[Z] > 0, side
        assert read_sensor(model, data, f"{side.value}_hand" + CONTACT_SUFFIX) == pytest.approx(touch)
        assert read_sensor(model, data, tip_force_sensor(side, "thumb")) == pytest.approx(np.zeros(3))
        assert read_sensor(model, data, f"{side.value}_foot" + CONTACT_SUFFIX) == pytest.approx(np.zeros(3))
    assert read_sensor(model, data, "chest" + CONTACT_SUFFIX) == pytest.approx(np.zeros(3))


def test_read_sensor_returns_a_copy(nova, settled):
    """读出来的值是一份拷贝，改它不会改到仿真里的数。"""
    first = read_sensor(nova.model, settled, PELVIS_IMU + ACCELERATION_SUFFIX)
    first[:] = 0.0
    assert read_sensor(nova.model, settled, PELVIS_IMU + ACCELERATION_SUFFIX)[Z] > 9.0


# 地面 ------------------------------------------------------------------------------------------------


def test_floor_support_without_contact(nova):
    """身体悬在空中时，地面不托着它：力是 0，压力中心不存在。"""
    model = nova.model
    data = standing_data(model)
    data.qpos[Z] += 1.0
    mujoco.mj_forward(model, data)
    total, center = floor_support(model, data)
    assert total == 0.0
    assert all(math.isnan(value) for value in center)


def test_floor_support_when_standing(nova, settled):
    """站着时，地面托着的力等于体重，压力中心在两只脚中间（左右方向）。"""
    total, center = floor_support(nova.model, settled)
    assert total == pytest.approx(nova.budget.total_kg * GRAVITY_M_S2, rel=1e-3)
    assert center[Y] == pytest.approx(0.0, abs=1e-6)
    assert center[Z] == pytest.approx(0.0, abs=1e-3)


# 速度 ------------------------------------------------------------------------------------------------


def test_simulation_runs_faster_than_real_time(nova):
    """仿真跑得比实时快。"""
    assert measure_realtime_factor(nova) > 1.0
