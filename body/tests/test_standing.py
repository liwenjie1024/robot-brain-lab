"""站着的测试。每个身体（Nova 和基线）跑的是同一套：在仿真里真的站 10 秒；不给控制会倒；轻推不倒、用力推会倒。"""

import math
from dataclasses import replace

import mujoco
import numpy as np
import pytest

from nova_body.bench import FLOOR, POSITION_SUFFIX, TORQUE_SUFFIX, VELOCITY_SUFFIX
from nova_body.mass_closure import GRAVITY_M_S2
from nova_body.standing import (
    MAX_TILT_DEG,
    STAND_SECONDS,
    Push,
    StandingResult,
    floor_support,
    measure_realtime_factor,
    push_of_weight,
    push_until_it_falls,
    read_sensor,
    simulate_standing,
    standing_data,
    stood_well,
)

X, Y, Z = 0, 1, 2
FREE_JOINT_POSITIONS = 7
# 推力按体重的比例定，这样轻的身体和重的身体受的是同样分量的一推。
GENTLE_PUSH_OF_WEIGHT = 0.04
HARD_PUSH_OF_WEIGHT = 0.40
SETTLE_STEPS = 3000
FORWARD, BACKWARD, LEFT, RIGHT = (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, -1.0, 0.0)


@pytest.fixture(scope="module")
def stood(body) -> StandingResult:
    """站 10 秒的结果，每个身体只仿真一次。"""
    return simulate_standing(body)


@pytest.fixture(scope="module")
def settled(body) -> mujoco.MjData:
    """站了 3 秒、已经静下来的状态。"""
    data = standing_data(body.model)
    for _ in range(SETTLE_STEPS):
        mujoco.mj_step(body.model, data)
    # 仿真走完一步以后，传感器里还是这一步开始时的值；再算一遍才是现在的。
    mujoco.mj_forward(body.model, data)
    return data


# 站住 ------------------------------------------------------------------------------------------------


def test_stands_for_ten_seconds(stood):
    """用关节控制站满 10 秒：没倒，几乎没歪、没塌，脚没滑，最后是静止的。"""
    assert stood.seconds == pytest.approx(STAND_SECONDS)
    assert not stood.fell
    assert stood.max_tilt_deg < MAX_TILT_DEG
    assert stood_well(stood)


def test_floor_carries_the_whole_weight(stood, body):
    """最后地面托着的力等于体重。"""
    assert stood.weight_n == pytest.approx(body.mass_kg * GRAVITY_M_S2)
    assert stood.support_force_n == pytest.approx(stood.weight_n, rel=1e-3)


def test_pressure_center_is_in_the_middle_of_the_foot(stood, body):
    """压力中心在脚的正中间（差不到 2 mm）：重心就在它上面。"""
    assert stood.foot_length_m == body.foot_length_m
    assert stood.pressure_center_from_heel_m == pytest.approx(stood.foot_length_m / 2, abs=0.002)


def test_body_stays_at_the_stand_pose(body, settled):
    """站姿是平衡的位置：站了几秒，每个关节离站姿不到 0.1°，骨盆没有移动超过 1 mm。"""
    joints_start = FREE_JOINT_POSITIONS
    stand = np.array(body.stand.qpos)
    assert np.abs(settled.qpos[joints_start:] - stand[joints_start:]).max() < math.radians(0.1)
    assert np.abs(settled.qpos[:3] - stand[:3]).max() < 0.001


def test_motors_give_the_holding_torque(body, settled):
    """站着时每个驱动器给关节的力矩，就是站姿里算好的"顶住重力要的力矩"。"""
    torques = [settled.qfrc_actuator[body.model.joint(joint.name).dofadr[0]] for joint in body.joints]
    holding = body.joint_holding_torques_nm
    for index, joint in enumerate(body.joints):
        assert torques[index] == pytest.approx(holding[index], abs=0.02 * joint.peak_torque_nm)
    names = [joint.name for joint in body.joints]
    for leg in body.anatomy.legs.values():
        ankle = names.index(leg.ankle_pitch)
        assert torques[ankle] == pytest.approx(holding[ankle], rel=0.02)


def test_standing_is_repeatable(body, stood):
    """同样的开始再站一次，结果一模一样。"""
    assert simulate_standing(body) == stood


def test_falls_without_control(body):
    """驱动器不出力时，1 秒之内就倒了：是控制让它站住的。"""
    limp = simulate_standing(body, 3.0, controlled=False)
    assert limp.fell
    assert limp.seconds < 1.0
    assert not stood_well(limp)


def test_limp_run_does_not_change_the_shared_model(body):
    """ "不出力"是在模型的副本上做的，原来的模型还是有驱动的。"""
    simulate_standing(body, 0.1, controlled=False)
    assert not body.model.opt.disableflags & mujoco.mjtDisableBit.mjDSBL_ACTUATION


@pytest.mark.parametrize("direction", [FORWARD, BACKWARD, LEFT, RIGHT], ids=["往前推", "往后推", "往左推", "往右推"])
def test_survives_a_gentle_push(body, direction):
    """在胸上轻推 0.5 秒，力是体重的 4%：四个方向都不倒，之后又静下来。"""
    result = simulate_standing(body, 5.0, push_of_weight(body, GENTLE_PUSH_OF_WEIGHT, direction))
    assert not result.fell
    assert result.max_tilt_deg < 5.0
    assert result.end_joint_speed_rad_s < 0.01


def test_hard_push_knocks_it_over(body):
    """用力推（体重的 40%）就倒了：现在只是关节顶着，没有平衡的控制。"""
    result = simulate_standing(body, 5.0, push_of_weight(body, HARD_PUSH_OF_WEIGHT, FORWARD))
    assert result.fell
    assert result.seconds < 5.0


def test_left_and_right_pushes_tilt_about_the_same(body):
    """往左推和往右推，歪的程度差不多（身体左右差不多是对称的）。"""
    left = simulate_standing(body, 3.0, push_of_weight(body, GENTLE_PUSH_OF_WEIGHT, LEFT))
    right = simulate_standing(body, 3.0, push_of_weight(body, GENTLE_PUSH_OF_WEIGHT, RIGHT))
    assert left.max_tilt_deg == pytest.approx(right.max_tilt_deg, rel=0.02)


def test_nova_tilts_exactly_the_same_both_ways(nova):
    """Nova 是按左右镜像生成的，所以往左推和往右推歪得一模一样。"""
    left = simulate_standing(nova.body, 3.0, push_of_weight(nova.body, GENTLE_PUSH_OF_WEIGHT, LEFT))
    right = simulate_standing(nova.body, 3.0, push_of_weight(nova.body, GENTLE_PUSH_OF_WEIGHT, RIGHT))
    assert left.max_tilt_deg == pytest.approx(right.max_tilt_deg, rel=1e-6)


def test_push_of_weight_scales_with_the_body(body):
    """按体重的比例推：体重的 4%，方向不变；重的身体受的力大。"""
    push = push_of_weight(body, 0.04, BACKWARD)
    assert push.force_n == pytest.approx((-0.04 * body.mass_kg * GRAVITY_M_S2, 0.0, 0.0))
    assert (push.start_s, push.duration_s) == (1.0, 0.5)


def test_pushing_harder_step_by_step_stops_at_the_first_fall(body):
    """一档一档地加力，推到倒了为止：前面几档都没倒，最后一档倒了，再大的不试了。"""
    ladder = push_until_it_falls(body, FORWARD, [0.04, 0.20, 0.40, 0.60])
    assert [share for share, _ in ladder] == [0.04, 0.20]
    assert [result.fell for _, result in ladder] == [False, True]
    assert ladder[0][1] == simulate_standing(body, 5.0, push_of_weight(body, 0.04, FORWARD))


def test_pushing_gently_only_never_reports_a_fall(body):
    """每一档都扛住了：每一档的结果都在，没有一档是倒了的。"""
    ladder = push_until_it_falls(body, LEFT, [0.01, 0.02], seconds=2.0)
    assert [share for share, _ in ladder] == [0.01, 0.02]
    assert not any(result.fell for _, result in ladder)
    assert ladder[0][1].max_tilt_deg < ladder[1][1].max_tilt_deg


@pytest.mark.parametrize(
    "shares",
    [[], [0.0, 0.1], [-0.1, 0.1], [0.2, 0.1], [0.1, 0.1]],
    ids=["一档都没有", "有一档是 0", "有一档是负的", "从大到小", "有重复的"],
)
def test_rejects_push_steps_that_do_not_grow(body, shares):
    """推力要从小到大、都大于 0、不重复，不然拒绝。"""
    with pytest.raises(ValueError, match="推力要从小到大排"):
        push_until_it_falls(body, FORWARD, shares)


@pytest.mark.parametrize("seconds", [0.0, -1.0], ids=["0 秒", "负的时间"])
def test_rejects_non_positive_duration(body, seconds):
    """仿真的时间不是正数时拒绝。"""
    with pytest.raises(ValueError, match="仿真的时间必须大于 0"):
        simulate_standing(body, seconds)


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


# 每个身体都有的传感器 --------------------------------------------------------------------------------


def test_imus_feel_gravity_and_no_rotation(body, settled):
    """站着不动时，每个 IMU 量到的加速度是重力（朝上 9.81），角速度是 0。"""
    assert len(body.imus) > 0
    for imu in body.imus:
        acceleration = read_sensor(body.model, settled, imu.accelerometer)
        assert np.linalg.norm(acceleration) == pytest.approx(GRAVITY_M_S2, rel=1e-3), imu.label
        assert acceleration[Z] == pytest.approx(GRAVITY_M_S2, rel=1e-3), imu.label
        assert read_sensor(body.model, settled, imu.gyro) == pytest.approx(np.zeros(3), abs=1e-3), imu.label


def test_joint_sensors_read_the_joint(body, settled):
    """每个关节的传感器读到的就是这个关节的角度、速度，和驱动器给它的力矩。"""
    model = body.model
    for joint in body.joints:
        address = model.joint(joint.name)
        assert read_sensor(model, settled, joint.name + POSITION_SUFFIX)[0] == settled.qpos[address.qposadr[0]]
        assert read_sensor(model, settled, joint.name + VELOCITY_SUFFIX)[0] == settled.qvel[address.dofadr[0]]
        assert read_sensor(model, settled, joint.name + TORQUE_SUFFIX)[0] == settled.qfrc_actuator[address.dofadr[0]]


def test_read_sensor_returns_a_copy(body, settled):
    """读出来的值是一份拷贝，改它不会改到仿真里的数。"""
    name = body.imus[0].accelerometer
    first = read_sensor(body.model, settled, name)
    first[:] = 0.0
    assert read_sensor(body.model, settled, name)[Z] > 9.0


# 地面 ------------------------------------------------------------------------------------------------


def test_only_the_feet_touch_the_floor(body, settled):
    """站着的时候只有两只脚碰着地面；身体的各段之间也没有互相顶着。"""
    model = body.model
    floor = model.geom(FLOOR).id
    feet = {model.body(leg.foot).id for leg in body.anatomy.legs.values()}
    assert settled.ncon > 0
    touching = set()
    for index in range(settled.ncon):
        first, second = (int(geom) for geom in settled.contact[index].geom)
        assert floor in {first, second}
        touching.add(int(model.geom_bodyid[second if first == floor else first]))
    assert touching == feet


def test_floor_support_without_contact(body):
    """身体悬在空中时，地面不托着它：力是 0，压力中心不存在。"""
    model = body.model
    data = standing_data(model)
    data.qpos[Z] += 1.0
    mujoco.mj_forward(model, data)
    total, center = floor_support(model, data)
    assert total == 0.0
    assert all(math.isnan(value) for value in center)


def test_floor_support_when_standing(body, settled):
    """站着时，地面托着的力等于体重，压力中心在两只脚中间（左右方向）。"""
    total, center = floor_support(body.model, settled)
    assert total == pytest.approx(body.mass_kg * GRAVITY_M_S2, rel=1e-3)
    assert center[Y] == pytest.approx(0.0, abs=1e-3)
    assert center[Z] == pytest.approx(0.0, abs=1e-3)


# 速度 ------------------------------------------------------------------------------------------------


def test_simulation_runs_faster_than_real_time(body):
    """仿真跑得比实时快。"""
    assert measure_realtime_factor(body) > 1.0
