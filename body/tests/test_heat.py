"""一轮家务的热预算的测试：关节怎么分给驱动器（并联的一对）、按 0.1 秒一段算铜损、循环正好 10 分钟、
算温度的两种写法一样、最费力的 5 分钟、一直保持一个姿势多久降额、写进设计的目标。

动作用假的（每一帧的力矩、转速自己摆），不跑逆动力学，所以快、数也算得出来。
"""

import numpy as np
import pytest

from nova_body.design import JOINT_GROUPS
from nova_body.drives import COOLANT_C, DERATE_FROM_C, Temperatures
from nova_body.heat import (
    CHORE_CYCLE,
    CONTINUOUS_MARGIN,
    CYCLE_S,
    CYCLES,
    REST,
    STRESS_HOLDS,
    Blocks,
    Do,
    Hold,
    Moment,
    chore_round,
    continuous_targets,
    cycle_blocks,
    hardest_window_rms_nm,
    held_blocks,
    hold_after_round,
    motion_blocks,
    motors_of,
    run_heat,
)
from nova_body.motions import Level
from nova_body.strength import MotionDemand, MotionSeries

DT = 0.01


@pytest.fixture(scope="module")
def motors(nova):
    """Nova 的每个驱动器（不算手）。"""
    return motors_of(nova.body, nova.budget.drives)


def joint_index(nova, name: str) -> int:
    return [joint.name for joint in nova.body.joints].index(name)


def series(nova, frames: int, torques: dict[str, float] | None = None, speeds: dict[str, float] | None = None):
    """一个假的动作：每一帧一样，没写的关节力矩、转速都是 0。"""
    count = len(nova.body.joints)
    torque, speed = np.zeros((frames, count)), np.zeros((frames, count))
    for name, value in (torques or {}).items():
        torque[:, joint_index(nova, name)] = value
    for name, value in (speeds or {}).items():
        speed[:, joint_index(nova, name)] = value
    return MotionSeries(DT, torque, speed)


def demand(key: str, motion: MotionSeries) -> MotionDemand:
    """把假的动作包成一个"动作的要求"。"""
    count = motion.torques_nm.shape[1]
    return MotionDemand(
        key=key,
        name=key,
        description="",
        level=Level.CORE,
        feasible=True,
        duration_s=motion.duration_s,
        reach_error_m=0.0,
        balance_error_m=0.0,
        torques_nm=np.abs(motion.torques_nm).max(axis=0),
        torque_times_s=np.zeros(count),
        speeds_rad_s=np.abs(motion.speeds_rad_s).max(axis=0),
        shared_nm={},
        edge_margin_m=0.0,
        friction_ratio=0.0,
        unbalanced_n=0.0,
        series=motion,
    )


def all_demands(nova, frames: int = 100, torques: dict[str, float] | None = None) -> dict[str, MotionDemand]:
    """循环里每个动作、站着歇、一直保持的那几个，都给一个一样的假动作。"""
    keys = {step.motion for step in CHORE_CYCLE} | {REST.motion} | {hold.motion for hold in STRESS_HOLDS}
    return {key: demand(key, series(nova, frames, torques)) for key in keys}


def motor(motors, name: str):
    return next(item for item in motors if item.name == name)


# 驱动器 ----------------------------------------------------------------------------------------------


def test_every_body_joint_has_a_motor(nova, motors):
    """身体的每个关节（不算手）都分到驱动器上：31 个关节，31 个驱动器；并联的一对是两个驱动器带两个关节。"""
    body_joints = [joint for joint in nova.body.joints if joint.region.value != "手"]
    assert len(motors) == len(body_joints) == 31
    pairs = [item for item in motors if len(item.joints) == 2]
    assert len(pairs) == 10
    assert {item.group for item in pairs} == {group.key for group in JOINT_GROUPS if group.parallel} - {
        "thoracic_pitch_roll"
    }


def test_a_parallel_pair_splits_the_torques_and_adds_the_speeds(nova, motors):
    """并联的一对：甲出两个力矩之和的一半，乙出之差的一半；甲转两个转速之和，乙转之差；功率对得上。"""
    motion = series(
        nova, 3, {"left_ankle_pitch": 10.0, "left_ankle_roll": 4.0}, {"left_ankle_pitch": 2.0, "left_ankle_roll": 1.0}
    )
    first, second = motor(motors, "left_ankle_pitch_0"), motor(motors, "left_ankle_pitch_1")
    assert first.torques_nm(motion.torques_nm)[0] == pytest.approx(7.0)
    assert second.torques_nm(motion.torques_nm)[0] == pytest.approx(3.0)
    assert first.speeds_rad_s(motion.speeds_rad_s)[0] == pytest.approx(3.0)
    assert second.speeds_rad_s(motion.speeds_rad_s)[0] == pytest.approx(1.0)
    motor_power = 7.0 * 3.0 + 3.0 * 1.0
    assert motor_power == pytest.approx(10.0 * 2.0 + 4.0 * 1.0)
    assert "（并联甲）" in first.label and first.label.startswith("左 ")


# 每一段 -----------------------------------------------------------------------------------------------


def test_blocks_average_the_square_every_tenth_of_a_second(nova, motors):
    """不动、一直出 20 N·m：每 0.1 秒一段，平方的平均是 400；最后不满 0.1 秒的那一段按它自己的长短。"""
    blocks = motion_blocks(series(nova, 25, {"left_knee": 20.0}), motors)
    column = motors.index(motor(motors, "left_knee"))
    assert blocks.seconds.tolist() == pytest.approx([0.1, 0.1, 0.05])
    assert blocks.mean_square_nm2[:, column] == pytest.approx([400.0] * 3)
    assert blocks.duration_s == pytest.approx(0.25)


def test_moving_adds_the_drives_own_friction(nova, motors):
    """不出力、只是转：驱动器还要顶住自己的摩擦（干摩擦 + 随转速的）。"""
    knee = motor(motors, "left_knee")
    blocks = motion_blocks(series(nova, 10, speeds={"left_knee": 1.0}), motors)
    expected = (knee.drive.friction_nm + knee.drive.viscous_nm_s) ** 2
    assert blocks.mean_square_nm2[0, motors.index(knee)] == pytest.approx(expected)


def test_holding_picks_the_last_or_the_hardest_frame(nova, motors):
    """一直保持：最后一刻，或者全身最费力的那一刻；不动，所以没有摩擦。"""
    torque = np.zeros((3, len(nova.body.joints)))
    knee = joint_index(nova, "left_knee")
    torque[:, knee] = [5.0, 50.0, 7.0]
    motion = MotionSeries(DT, torque, np.ones_like(torque))
    column = motors.index(motor(motors, "left_knee"))
    last = held_blocks(motion, Moment.LAST, motors, 2.0)
    hardest = held_blocks(motion, Moment.HARDEST, motors, 2.0)
    assert last.mean_square_nm2[0, column] == pytest.approx(49.0)
    assert hardest.mean_square_nm2[0, column] == pytest.approx(2500.0)
    assert hardest.duration_s == pytest.approx(2.0)


def test_a_cycle_is_exactly_ten_minutes(nova, motors):
    """一个循环：做完循环里的事，剩下的站着歇，正好 10 分钟。"""
    blocks = cycle_blocks(CHORE_CYCLE, all_demands(nova), motors)
    assert blocks.duration_s == pytest.approx(CYCLE_S)


def test_a_cycle_that_is_too_long_is_refused(nova, motors):
    """循环里的动作加起来比 10 分钟还长：报错，不偷偷截掉。"""
    long = all_demands(nova, frames=10_000)
    with pytest.raises(ValueError, match="比一个循环"):
        cycle_blocks((Do("walk", 70),), long, motors)


def test_a_missing_motion_is_refused(nova, motors):
    """循环里要的动作没算出来：报错，说是哪一个。"""
    demands = all_demands(nova)
    del demands["walk"]
    with pytest.raises(ValueError, match="动作 walk 没有算出来"):
        cycle_blocks(CHORE_CYCLE, demands, motors)


# 温度 -------------------------------------------------------------------------------------------------


def test_vector_heat_matches_the_single_drive_heat(nova, motors):
    """一起算全部驱动器的温度，和一个驱动器自己算的一样。"""
    knee = motor(motors, "left_knee")
    squares = np.zeros((1, len(motors)))
    squares[0, motors.index(knee)] = 150.0**2
    trace = run_heat(motors, Blocks(squares, np.array([100.0])))
    alone = knee.drive.heat(Temperatures(COOLANT_C, COOLANT_C), 150.0, 100.0)
    column = motors.index(knee)
    assert trace.winding_c[-1, column] == pytest.approx(alone.winding_c, rel=1e-9)
    assert trace.housing_c[-1, column] == pytest.approx(alone.housing_c, rel=1e-9)


def test_no_torque_stays_at_the_coolant_temperature(motors):
    """都不出力：一直和冷却液一样，不发热。"""
    blocks = Blocks(np.zeros((5, len(motors))), np.full(5, 60.0))
    trace = run_heat(motors, blocks)
    assert np.allclose(trace.winding_c, COOLANT_C)
    assert np.allclose(trace.loss_w, 0.0)


def test_hardest_window_finds_the_burst():
    """一长段里有 5 分钟出 10 N·m，别的时候不出：最费力的 5 分钟的均方根是 10。"""
    seconds = np.ones(2300)
    squares = np.zeros((2300, 1))
    squares[1000:1300] = 100.0
    assert hardest_window_rms_nm(Blocks(squares, seconds))[0] == pytest.approx(10.0)


def test_hardest_window_of_a_short_stretch_is_its_own_rms():
    """一共不到 5 分钟：取全部的均方根。"""
    blocks = Blocks(np.array([[9.0], [16.0]]), np.array([1.0, 1.0]))
    assert hardest_window_rms_nm(blocks)[0] == pytest.approx(np.sqrt(12.5))


# 一轮家务、一直保持 -----------------------------------------------------------------------------------


def test_a_light_round_lasts_two_hours_and_never_derates(nova, motors):
    """出力很小的一轮家务：一共 2 小时，最热的也只比冷却液高一点，没有降额；最忙的一分钟不比平均小。"""
    result = chore_round(motors, all_demands(nova, torques={"left_knee": 10.0}))
    assert result.duration_s == pytest.approx(CYCLES * CYCLE_S)
    assert all(item.derating_s == 0 for item in result.motors)
    assert max(item.hottest_c for item in result.motors) < COOLANT_C + 5
    assert result.busiest_minute_w >= result.mean_loss_w * 0.999


def test_holding_too_much_derates_and_holding_little_does_not(nova, motors):
    """一直保持：膝要出的比能一直出的大，过一会儿就降额；小的不会。"""
    knee = motor(motors, "left_knee")
    demands = all_demands(nova, torques={"left_knee": knee.drive.continuous_torque_nm * 1.3})
    result = chore_round(motors, all_demands(nova))
    hold = Hold("试", "squat", Moment.LAST, 600.0)
    heavy = hold_after_round(hold, motors, demands, result)
    light = hold_after_round(hold, motors, all_demands(nova, torques={"left_knee": 5.0}), result)
    heavy_knee = next(item for item in heavy.motors if item.motor is knee)
    light_knee = next(item for item in light.motors if item.motor is knee)
    assert heavy_knee.derate_after_s is not None and 0 < heavy_knee.derate_after_s < 600
    assert heavy_knee.end_c > DERATE_FROM_C
    assert light_knee.derate_after_s is None


def test_targets_take_the_larger_need_add_the_margin_and_scale_to_70_kg(nova, motors):
    """写进设计的目标：最费力的 5 分钟和一直保持的取大的，x 1.2；"随体重"的（膝）按 70 kg 折算，肘不折算。"""
    demands = all_demands(nova, torques={"left_knee": 30.0, "left_elbow": 3.0})
    result = chore_round(motors, demands)
    hold = hold_after_round(STRESS_HOLDS[0], motors, all_demands(nova, torques={"left_elbow": 8.0}), result)
    targets = continuous_targets(result, [hold], body_mass_kg=80.0, reference_mass_kg=70.0)
    assert targets["knee"][0] == pytest.approx(30.0 * CONTINUOUS_MARGIN * 70.0 / 80.0, rel=1e-3)
    assert targets["elbow"][0] == pytest.approx(8.0 * CONTINUOUS_MARGIN, rel=1e-3)
    assert len(targets["ankle"]) == 2
