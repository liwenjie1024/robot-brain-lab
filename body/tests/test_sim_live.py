"""实时仿真的测试：跟着钟走、暂停、推一下、松开、重新开始；发给网页的状态合规约，数是对的。

前面的每个身体（Nova 和基线）都跑。这里不等真的时间：直接告诉它"钟走了多少秒"。
"""

import json

import mujoco
import numpy as np
import pytest

from nova_body.bench import TIMESTEP_S
from nova_body.mass_closure import GRAVITY_M_S2
from nova_body.sensing import ACCELEROMETER, FORCE_STD_N, GYRO, TOUCH_STD_N, per_reading_std
from nova_sim.live import BROKEN_NUMBERS, MAX_CATCH_UP_S, PUSH_DURATION_S, CommandRejectedError, LiveSim
from nova_sim.protocol import MESSAGE, problems

TICK_S = 1.0 / 60.0
X, Y, Z = 0, 1, 2


def run(sim: LiveSim, seconds: float) -> None:
    """让钟走 seconds 秒，一小格一小格地走，像服务里那样。"""
    for _ in range(round(seconds / TICK_S)):
        sim.advance(TICK_S)


@pytest.fixture
def sim(body) -> LiveSim:
    """刚放上测试台的身体。"""
    return LiveSim("some-key", body, episode=5)


# 开始 ------------------------------------------------------------------------------------------------


def test_starts_standing_still(sim, body):
    """刚放上去：在站姿上，时间是 0，仿真在走，驱动器在出力，没倒，没在推，没有问题。"""
    state = sim.state()
    assert (state["type"], state["body"], state["episode"]) == ("state", "some-key", 5)
    assert (state["time_s"], state["speed"]) == (0.0, 0.0)
    assert (state["running"], state["controlled"], state["fallen"]) == (True, True, False)
    assert (state["problem"], state["push"]) == (None, None)
    angles = [body.stand.qpos[body.model.joint(joint.name).qposadr[0]] for joint in body.joints]
    assert state["joints"]["angles_rad"] == pytest.approx(angles, abs=1e-4)
    assert state["pelvis_height_m"] == pytest.approx(body.stand.pelvis_height_m, abs=1e-5)
    assert state["center_of_mass"][Z] == pytest.approx(body.stand.center_of_mass_height_m, abs=1e-5)


def test_state_follows_the_contract_in_every_situation(sim, body):
    """刚开始、推着、倒在地上、悬在空中：每一种状态都合规约，都能变成 JSON（没有"不是数"）。"""
    states = [sim.state()]
    run(sim, 0.5)
    sim.push("left", 0.3)
    run(sim, 0.2)
    states.append(sim.state())
    run(sim, 3.0)
    states.append(sim.state())
    assert states[-1]["fallen"]
    sim.reset()
    sim.data.qpos[Z] += 1.0
    states.append(sim.state())
    for state in states:
        assert problems(MESSAGE, state) == []
        json.dumps(state, allow_nan=False)
    links = body.model.nbody - 1
    assert len(states[0]["link_positions"]) == 3 * links
    assert len(states[0]["link_orientations"]) == 4 * links
    for readings in states[0]["joints"].values():
        assert len(readings) == len(body.joints)
    assert len(states[0]["imus"]) == len(body.imus)
    assert len(states[0]["forces"]) == len(body.force_sensors)
    assert len(states[0]["touches"]) == len(body.touch_sensors)


def test_link_poses_are_the_ones_in_the_simulation(sim):
    """每一段的位置和姿态就是仿真里的（不带"世界"），连着排成一排。"""
    run(sim, 0.2)
    state = sim.state()
    assert state["link_positions"] == pytest.approx(sim.data.xpos[1:].ravel(), abs=1e-5)
    assert state["link_orientations"] == pytest.approx(sim.data.xquat[1:].ravel(), abs=1e-6)


# 跟着钟走 --------------------------------------------------------------------------------------------


def test_follows_the_wall_clock(sim):
    """钟走了 1 秒，仿真也走了 1 秒；量出来仿真是实时的 1 倍。"""
    run(sim, 1.0)
    assert sim.time_s == pytest.approx(1.0, abs=0.002)
    assert sim.state()["speed"] == pytest.approx(1.0, abs=0.02)


def test_tiny_ticks_add_up(sim):
    """钟每次只走 0.4 毫秒（不到一步）：攒够了再走，5 次正好走 2 步。"""
    for _ in range(5):
        sim.advance(0.0004)
    assert sim.time_s == pytest.approx(0.002)


def test_does_not_chase_after_a_long_stall(sim):
    """电脑卡了 5 秒：仿真只补 0.1 秒，不去硬追（那样只会越卡越久）。"""
    sim.advance(5.0)
    assert sim.time_s == pytest.approx(MAX_CATCH_UP_S, abs=0.002)
    assert sim.state()["speed"] < 0.1


def test_pause_stops_the_clock_and_resume_starts_it_again(sim):
    """暂停着的时候钟怎么走，仿真都不动；继续以后接着走。"""
    run(sim, 0.5)
    sim.pause()
    before = sim.time_s
    run(sim, 1.0)
    state = sim.state()
    assert (sim.time_s, state["running"], state["speed"]) == (before, False, 0.0)
    sim.resume()
    run(sim, 0.5)
    assert sim.time_s == pytest.approx(before + 0.5, abs=0.002)
    assert sim.state()["running"]


@pytest.mark.parametrize("seconds", [-0.001, -5.0], ids=["一点点", "很多"])
def test_time_cannot_run_backwards(sim, seconds):
    """钟不能往回走：报错。"""
    with pytest.raises(ValueError, match="时间不能往回走"):
        sim.advance(seconds)


def test_zero_seconds_changes_nothing(sim):
    """钟没走：仿真不动。"""
    sim.advance(0.0)
    assert sim.time_s == 0.0


# 站着的时候量到的 ------------------------------------------------------------------------------------


def test_floor_carries_the_weight_under_both_feet(sim, body):
    """站稳以后：地面托着的力等于体重，两只脚各托一半左右，压力中心在两只脚中间、重心的正下面。"""
    run(sim, 2.0)
    state = sim.state()
    weight = body.mass_kg * GRAVITY_M_S2
    assert state["support_n"] == pytest.approx(weight, rel=1e-3)
    left, right = state["feet"]
    assert left["support_n"] + right["support_n"] == pytest.approx(state["support_n"], abs=1e-3)
    assert left["support_n"] == pytest.approx(weight / 2, rel=0.01)
    assert left["pressure_center"][Y] > 0 > right["pressure_center"][Y]
    assert state["pressure_center"][X] == pytest.approx(state["center_of_mass"][X], abs=0.002)
    assert state["pressure_center"][Y] == pytest.approx(0.0, abs=0.002)
    assert state["tilt_deg"] < 0.1
    assert not state["fallen"]


def test_joint_readings_are_the_holding_torques(sim, body):
    """站稳以后：每个关节的力矩就是站姿里算好的"顶住重力要的力矩"，速度是 0。"""
    run(sim, 2.0)
    readings = sim.state()["joints"]
    for joint, torque, expected in zip(body.joints, readings["torques_nm"], body.joint_holding_torques_nm, strict=True):
        assert torque == pytest.approx(expected, abs=0.02 * joint.peak_torque_nm), joint.name
    assert np.abs(readings["speeds_rad_s"]).max() < 0.01


def test_imus_feel_gravity(sim, body):
    """站稳以后：每个 IMU 量到朝上的 9.81，没有在转。读数是真的传感器读到的：差的不超过零偏加上 5 倍的噪声。"""
    run(sim, 2.0)
    readings = sim.state()["imus"]
    assert len(readings) == len(body.imus)
    for imu, reading in zip(body.imus, readings, strict=True):
        accelerometer, gyro = ACCELEROMETER[imu.grade], GYRO[imu.grade]
        lean = accelerometer.bias + 5 * per_reading_std(accelerometer.density, TIMESTEP_S)
        turning = gyro.bias + 5 * per_reading_std(gyro.density, TIMESTEP_S)
        assert reading["acceleration"][Z] == pytest.approx(GRAVITY_M_S2, abs=lean), imu.label
        assert reading["angular_velocity"] == pytest.approx([0.0, 0.0, 0.0], abs=turning), imu.label


def test_nova_feels_its_feet_and_wrists(nova):
    """Nova 自己的感觉：踝的力传感器压着"半个身体减去脚"，腕的量到手的重量；接触力只有两只脚有。"""
    sim = LiveSim("nova", nova.body)
    run(sim, 2.0)
    state = sim.state()
    model = nova.model
    labels = [sensor.label for sensor in nova.body.force_sensors]
    foot_kg = float(model.body_subtreemass[model.body("left_foot").id])
    hand_kg = float(model.body_subtreemass[model.body("left_hand").id])
    ankle = state["forces"][labels.index("左踝")]["force"]
    wrist = state["forces"][labels.index("右腕")]["force"]
    assert -ankle[Z] == pytest.approx((nova.body.mass_kg / 2 - foot_kg) * GRAVITY_M_S2, abs=5 * 2 * FORCE_STD_N)
    assert np.linalg.norm(wrist) == pytest.approx(hand_kg * GRAVITY_M_S2, abs=5 * FORCE_STD_N * 3)
    touched = {
        sensor.label: force
        for sensor, force in zip(nova.body.touch_sensors, state["touches"], strict=True)
        if np.linalg.norm(force) > 10 * TOUCH_STD_N
    }
    assert set(touched) == {"左 脚", "右 脚"}
    assert touched["左 脚"][Z] == pytest.approx(nova.body.mass_kg * GRAVITY_M_S2 / 2, abs=5 * TOUCH_STD_N)


def test_nothing_under_the_feet_when_lifted(sim):
    """把身体提到空中：地面不托着它，压力中心没有。"""
    sim.data.qpos[Z] += 1.0
    state = sim.state()
    assert state["support_n"] == 0.0
    assert state["pressure_center"] is None
    assert [foot["pressure_center"] for foot in state["feet"]] == [None, None]
    assert [foot["support_n"] for foot in state["feet"]] == [0.0, 0.0]


# 推一下 ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "axis", "sign"),
    [("forward", X, 1), ("backward", X, -1), ("left", Y, 1), ("right", Y, -1)],
    ids=["往前", "往后", "往左", "往右"],
)
def test_push_goes_the_way_it_says(sim, body, direction, axis, sign):
    """往哪边推，力就朝哪边，大小是体重的那么多倍。"""
    sim.push(direction, 0.04)
    force = sim.state()["push"]["force_n"]
    expected = [0.0, 0.0, 0.0]
    expected[axis] = sign * 0.04 * body.mass_kg * GRAVITY_M_S2
    assert force == pytest.approx(expected, abs=1e-3)


def test_push_lasts_half_a_second_of_simulated_time(sim, body):
    """推 0.5 秒（仿真里的时间）：推的时候胸上有力、身体歪了；推完力就没了，可以再推。"""
    run(sim, 0.5)
    sim.push("forward", 0.04)
    assert sim.state()["push"]["remaining_s"] == pytest.approx(PUSH_DURATION_S, abs=1e-3)
    run(sim, 0.25)
    trunk = sim.model.body(body.anatomy.trunk).id
    assert sim.data.xfrc_applied[trunk, X] == pytest.approx(0.04 * body.mass_kg * GRAVITY_M_S2)
    assert sim.state()["push"]["remaining_s"] == pytest.approx(0.25, abs=0.02)
    tilted = sim.state()["tilt_deg"]
    assert tilted > 0.05
    run(sim, 0.3)
    assert sim.state()["push"] is None
    assert not sim.data.xfrc_applied.any()
    assert not sim.state()["fallen"]
    sim.push("backward", 0.02)


def test_hard_push_knocks_it_over(sim):
    """用力推（体重的 40%）：倒了，状态里记着倒过。"""
    run(sim, 0.5)
    sim.push("forward", 0.4)
    run(sim, 3.0)
    state = sim.state()
    assert state["fallen"]
    assert state["tilt_deg"] > 45.0


def test_rejects_a_push_it_cannot_do(sim):
    """暂停着推不了；上一下没推完不能再推；不认识的方向不推。都说为什么。"""
    with pytest.raises(CommandRejectedError, match="不认识的方向：up"):
        sim.push("up", 0.1)
    sim.pause()
    with pytest.raises(CommandRejectedError, match="暂停着的时候推不了，先点继续"):
        sim.push("left", 0.1)
    sim.resume()
    sim.push("left", 0.1)
    with pytest.raises(CommandRejectedError, match="上一下还没推完"):
        sim.push("right", 0.1)


# 松开、重新开始 --------------------------------------------------------------------------------------


def test_letting_go_makes_it_fall_and_reset_stands_it_up_again(sim, body):
    """松开驱动器：1 秒多就倒了。重新开始：回到站姿，驱动器又出力，算新的一回。共用的模型没被改。"""
    sim.set_controlled(False)
    assert not sim.state()["controlled"]
    run(sim, 1.5)
    assert sim.state()["fallen"]
    sim.pause()
    sim.reset()
    state = sim.state()
    assert state["episode"] == 6
    assert (state["time_s"], state["running"], state["controlled"], state["fallen"]) == (0.0, True, True, False)
    assert state["pelvis_height_m"] == pytest.approx(body.stand.pelvis_height_m, abs=1e-5)
    run(sim, 2.0)
    assert not sim.state()["fallen"]
    assert not body.model.opt.disableflags & mujoco.mjtDisableBit.mjDSBL_ACTUATION


def test_fallen_stays_fallen_until_reset(sim):
    """倒过就一直记着，重新让驱动器出力也不算没倒过；重新开始才清掉。"""
    sim.set_controlled(False)
    run(sim, 1.5)
    sim.set_controlled(True)
    run(sim, 0.5)
    assert sim.state()["fallen"]
    assert sim.state()["controlled"]
    sim.reset()
    assert not sim.state()["fallen"]


def test_reset_clears_a_push(sim):
    """推到一半重新开始：那一下不算了。"""
    sim.push("forward", 0.3)
    run(sim, 0.1)
    sim.reset()
    assert sim.state()["push"] is None
    assert not sim.data.xfrc_applied.any()
    sim.push("left", 0.02)


def test_switching_control_twice_is_the_same_as_once(sim):
    """连着松开两次、连着顶住两次，和各一次一样。"""
    sim.set_controlled(False)
    sim.set_controlled(False)
    assert not sim.controlled
    sim.set_controlled(True)
    sim.set_controlled(True)
    assert sim.controlled


# 出了问题 --------------------------------------------------------------------------------------------


def test_broken_numbers_stop_the_simulation(sim, body):
    """仿真里算出了"不是数"：停下，放回站姿（发给网页的还都是正常的数），说是什么问题；要重新开始才能继续。"""
    run(sim, 0.2)
    sim.data.qvel[0] = np.nan
    sim.advance(TICK_S)
    state = sim.state()
    assert state["problem"] == BROKEN_NUMBERS
    assert not state["running"]
    assert problems(MESSAGE, state) == []
    json.dumps(state, allow_nan=False)
    assert state["pelvis_height_m"] == pytest.approx(body.stand.pelvis_height_m, abs=1e-5)
    before = sim.time_s
    run(sim, 0.5)
    assert sim.time_s == before
    with pytest.raises(CommandRejectedError, match="仿真出了问题，要先重新开始"):
        sim.resume()
    sim.reset()
    assert sim.state()["problem"] is None
    run(sim, 0.5)
    assert sim.time_s == pytest.approx(0.5, abs=0.002)
