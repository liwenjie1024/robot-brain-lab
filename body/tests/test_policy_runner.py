"""把策略接到身体上的测试：观测的每一项算得对、放得对；按策略的周期才算一次；策略给的是关节的命令
（目标 = 默认 + 动作 x 比例，软硬照规约），交给脊髓层；身体对不上（没有这个关节、没有驱动器带着、步长凑不成周期）
就拒绝；策略不管的关节照测试台给的命令。

用测试用的小策略：动作 0 = 重力方向的 x，动作 1 = 转弯的命令。
"""

import math
from pathlib import Path

import mujoco
import numpy as np
import pytest

from nova_body.bench import Stairs
from nova_body.policy import PolicyError, load_policy
from nova_body.policy_bench import load_policy_body
from nova_body.policy_runner import BodySense, PolicyRunner, bind_joints, steps_per_action
from nova_body.spine import JointCommand, spine_for

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "policy"
STILL = {"lin_vel_x": 0.0, "lin_vel_y": 0.0, "ang_vel_z": 0.0}


@pytest.fixture
def policy():
    return load_policy(FIXTURE_DIR / "contract.json")


def fixture_spec(timestep_s: float = 0.001) -> mujoco.MjSpec:
    spec = mujoco.MjSpec.from_file(str(FIXTURE_DIR / "body.xml"))
    spec.option.timestep = timestep_s
    return spec


def runner_and_data(policy, spec: mujoco.MjSpec | None = None, base: JointCommand | None = None):
    model = (spec or fixture_spec()).compile()
    runner = PolicyRunner(model, policy, spine_for(model), base)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    return model, runner, data


def segment(policy, observation: np.ndarray, term: str) -> np.ndarray:
    start = 0
    for item in policy.observations:
        if item.term == term:
            return observation[start : start + item.size]
        start += item.size
    raise KeyError(term)


def pitch_quaternion(angle_rad: float) -> list[float]:
    return [math.cos(angle_rad / 2), 0.0, math.sin(angle_rad / 2), 0.0]


def yaw_quaternion(angle_rad: float) -> list[float]:
    return [math.cos(angle_rad / 2), 0.0, 0.0, math.sin(angle_rad / 2)]


def with_third_joint(spec: mujoco.MjSpec) -> mujoco.MjSpec:
    """小身体再加一条腿（joint_c）：策略不管它。"""
    leg = spec.body("pelvis").add_body(name="leg_c", pos=[0.05, 0.0, -0.05])
    leg.add_joint(name="joint_c", type=mujoco.mjtJoint.mjJNT_HINGE, axis=[0, 1, 0], range=[-1, 1])
    leg.add_geom(type=mujoco.mjtGeom.mjGEOM_CAPSULE, fromto=[0, 0, 0, 0, 0, -0.3], size=[0.02, 0, 0], mass=0.5)
    actuator = spec.add_actuator(name="joint_c", trntype=mujoco.mjtTrn.mjTRN_JOINT, target="joint_c")
    actuator.set_to_position(kp=10.0)
    return spec


@pytest.mark.parametrize(
    ("timestep", "rate", "steps"),
    [(0.001, 50.0, 20), (0.005, 50.0, 4), (0.001, 1000.0, 1), (0.002, 125.0, 4)],
    ids=["1 毫秒、每秒 50 次", "5 毫秒、每秒 50 次（练的时候）", "每一步都算", "2 毫秒、每秒 125 次"],
)
def test_steps_per_action_divides_the_period(timestep, rate, steps):
    """策略每隔几步算一次：步长 x 它正好是策略的周期。"""
    assert steps_per_action(timestep, rate) == steps


@pytest.mark.parametrize(
    ("timestep", "rate"), [(0.001, 30.0), (0.002, 1000.0)], ids=["凑不成整数（33.3 步）", "比一步还短"]
)
def test_steps_per_action_refuses_a_period_the_timestep_cannot_make(timestep, rate):
    """步长凑不成策略的周期就拒绝（策略的时间会乱）。"""
    with pytest.raises(PolicyError, match="凑不成策略的周期"):
        steps_per_action(timestep, rate)


def test_the_joint_command_carries_the_policy_gains(policy):
    """关节的命令里，刚度、阻尼照规约；目标转速、前馈力矩是 0。"""
    _, runner, data = runner_and_data(policy)
    command = runner.step(data, STILL)
    np.testing.assert_array_equal(command.stiffness_nm_per_rad, [20.0, 30.0])
    np.testing.assert_array_equal(command.damping_nms_per_rad, [1.0, 2.0])
    np.testing.assert_array_equal(command.velocity_rad_s, [0.0, 0.0])
    np.testing.assert_array_equal(command.torque_nm, [0.0, 0.0])


def test_upright_and_still_the_observation_is_gravity_down_and_offsets(policy):
    """站直不动：重力朝下 (0, 0, -1)，速度都是 0，关节的观测是角度减默认，命令在最后。"""
    _, runner, data = runner_and_data(policy)
    command = np.array([0.3, -0.2, 0.1])
    observation = runner.observation(data, command)
    np.testing.assert_allclose(segment(policy, observation, "projected_gravity"), [0.0, 0.0, -1.0], atol=1e-12)
    np.testing.assert_allclose(segment(policy, observation, "base_lin_vel"), 0.0, atol=1e-12)
    np.testing.assert_allclose(segment(policy, observation, "base_ang_vel"), 0.0, atol=1e-12)
    np.testing.assert_allclose(segment(policy, observation, "joint_pos"), [-0.1, 0.2])
    np.testing.assert_allclose(segment(policy, observation, "command"), command)


def test_pitching_forward_tilts_gravity_in_the_body_frame(policy):
    """骨盆绕左右的轴转 30°：在骨盆的坐标里重力方向是 (sin 30°, 0, -cos 30°)。"""
    spec = fixture_spec()
    spec.body("pelvis").quat = pitch_quaternion(math.radians(30.0))
    _, runner, data = runner_and_data(policy, spec)
    gravity = segment(policy, runner.observation(data, np.zeros(3)), "projected_gravity")
    np.testing.assert_allclose(gravity, [0.5, 0.0, -math.sqrt(3) / 2], atol=1e-9)


def test_base_velocity_is_measured_in_the_imu_frame(policy):
    """骨盆朝左（转了 90°）往世界的 x 方向走 1 m/s：在 IMU 的坐标里是往右（-y）1 m/s。"""
    spec = fixture_spec()
    spec.body("pelvis").quat = yaw_quaternion(math.pi / 2)
    _, runner, data = runner_and_data(policy, spec)
    data.qvel[:3] = [1.0, 0.0, 0.0]
    velocity = segment(policy, runner.observation(data, np.zeros(3)), "base_lin_vel")
    np.testing.assert_allclose(velocity, [0.0, -1.0, 0.0], atol=1e-9)


def test_base_angular_velocity_is_the_gyro_reading(policy):
    """骨盆绕自己的竖轴转 1 rad/s：IMU 量到的角速度是 (0, 0, 1)。"""
    _, runner, data = runner_and_data(policy)
    data.qvel[3:6] = [0.0, 0.0, 1.0]
    angular = segment(policy, runner.observation(data, np.zeros(3)), "base_ang_vel")
    np.testing.assert_allclose(angular, [0.0, 0.0, 1.0], atol=1e-9)


def test_joint_velocity_is_the_joint_speed(policy):
    """关节的观测里的转速就是关节在转的速度。"""
    model, runner, data = runner_and_data(policy)
    joint_b = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "joint_b")
    data.qvel[model.jnt_dofadr[joint_b]] = -2.0
    velocity = segment(policy, runner.observation(data, np.zeros(3)), "joint_vel")
    np.testing.assert_allclose(velocity, [0.0, -2.0])


def test_a_step_sets_targets_from_default_plus_scaled_action(policy):
    """算一次：目标 = 默认 + 动作 x 比例。动作 0 = 重力的 x（0.5），动作 1 = 转弯的命令（0.4）。"""
    spec = fixture_spec()
    spec.body("pelvis").quat = pitch_quaternion(math.radians(30.0))
    _, runner, data = runner_and_data(policy, spec)
    command = runner.step(data, {**STILL, "ang_vel_z": 0.4})
    np.testing.assert_allclose(runner.last_action, [0.5, 0.4], atol=1e-6)
    np.testing.assert_allclose(command.position_rad, [0.1 + 0.5 * 0.5, -0.2 + 0.25 * 0.4], atol=1e-6)


def test_targets_hold_between_policy_steps(policy):
    """两次之间（20 步，1 毫秒的步长、每秒 50 次）命令不变，给的命令变了也不变；到第 21 步才按新的算。"""
    model, runner, data = runner_and_data(policy)
    first = runner.step(data, {**STILL, "ang_vel_z": 0.2})
    for _ in range(runner.steps_per_action - 1):
        assert runner.step(data, {**STILL, "ang_vel_z": -0.4}) is first
        mujoco.mj_step(model, data)
    later = runner.step(data, {**STILL, "ang_vel_z": -0.4})
    assert later.position_rad[1] == pytest.approx(-0.2 + 0.25 * -0.4, abs=1e-6)


def test_the_last_action_is_fed_back_and_reset_clears_it(policy):
    """上一次的动作放进下一次的观测（last_action）；重新开始就清零，关节回到默认的姿势。"""
    _, runner, data = runner_and_data(policy)
    runner.step(data, {**STILL, "ang_vel_z": 0.3})
    observation = runner.observation(data, np.zeros(3))
    np.testing.assert_allclose(segment(policy, observation, "last_action"), runner.last_action)
    runner.reset()
    np.testing.assert_array_equal(runner.last_action, [0.0, 0.0])


def test_a_command_beyond_the_trained_range_is_refused(policy):
    """到了算的那一步，命令超出练过的范围就拒绝（不剪）。"""
    _, runner, data = runner_and_data(policy)
    with pytest.raises(PolicyError, match="超出了练过的范围"):
        runner.step(data, {**STILL, "ang_vel_z": 0.6})


def test_an_action_that_is_not_a_number_is_refused(policy):
    """姿态坏了（四元数是 NaN），策略算出来的动作不是数：拒绝，不交给脊髓层。"""
    _, runner, data = runner_and_data(policy)
    data.qpos[3:7] = np.nan
    with pytest.raises(PolicyError, match="不是数的动作"):
        runner.step(data, STILL)


def test_a_body_without_the_joint_is_refused(policy):
    """身体里没有策略的关节就拒绝。"""
    spec = fixture_spec()
    spec.delete(spec.actuator("joint_b"))
    spec.delete(spec.joint("joint_b"))
    model = spec.compile()
    with pytest.raises(PolicyError, match="没有关节 joint_b"):
        bind_joints(model, policy, spine_for(model))


def test_a_joint_no_actuator_drives_is_refused(policy):
    """关节在，可是没有驱动器带着它（脊髓层管不了）就拒绝。"""
    spec = fixture_spec()
    spec.delete(spec.actuator("joint_b"))
    model = spec.compile()
    with pytest.raises(PolicyError, match="关节 joint_b 没有驱动器带着"):
        bind_joints(model, policy, spine_for(model))


def test_a_body_without_the_imu_site_is_refused(policy):
    """身体里没有 IMU 的点就拒绝。"""
    spec = fixture_spec()
    spec.delete(spec.site("imu"))
    with pytest.raises(PolicyError, match="没有 IMU 的点 imu"):
        runner_and_data(policy, spec)


def test_a_timestep_that_cannot_make_the_policy_period_is_refused(policy):
    """仿真的步长（3 毫秒）凑不成策略的周期（20 毫秒）就拒绝。"""
    with pytest.raises(PolicyError, match="凑不成策略的周期"):
        runner_and_data(policy, fixture_spec(timestep_s=0.003))


def test_joints_the_policy_does_not_drive_need_a_base_command(policy):
    """策略没有管全部的关节（多了一条腿），又没给别的关节的命令：拒绝。"""
    with pytest.raises(PolicyError, match="别的关节要测试台给命令"):
        runner_and_data(policy, with_third_joint(fixture_spec()))


def test_joints_the_policy_does_not_drive_follow_the_base_command(policy):
    """策略不管的那条腿照测试台给的命令（目标 0.3、刚度 7）；策略的两个关节照策略。"""
    base = JointCommand(
        position_rad=np.array([0.0, 0.0, 0.3]),
        velocity_rad_s=np.zeros(3),
        stiffness_nm_per_rad=np.array([1.0, 1.0, 7.0]),
        damping_nms_per_rad=np.array([0.1, 0.1, 0.7]),
        torque_nm=np.array([0.0, 0.0, 0.5]),
    )
    _, runner, data = runner_and_data(policy, with_third_joint(fixture_spec()), base)
    command = runner.step(data, STILL)
    assert command.position_rad[2] == 0.3
    assert command.stiffness_nm_per_rad[2] == 7.0
    assert command.torque_nm[2] == 0.5
    np.testing.assert_array_equal(command.stiffness_nm_per_rad[:2], [20.0, 30.0])


def test_sensed_values_replace_the_simulation_truth(policy):
    """给了身体自己感觉到的（BodySense），速度、角速度、重力方向就用它的，不用仿真里的真数；关节的还用读数。"""
    _, runner, data = runner_and_data(policy)
    sense = BodySense(
        base_lin_vel=np.array([0.4, -0.1, 0.05]),
        base_ang_vel=np.array([0.01, 0.02, -0.3]),
        projected_gravity=np.array([0.1, 0.0, -0.995]),
    )
    observation = runner.observation(data, np.zeros(3), sense)
    np.testing.assert_array_equal(segment(policy, observation, "base_lin_vel"), sense.base_lin_vel)
    np.testing.assert_array_equal(segment(policy, observation, "base_ang_vel"), sense.base_ang_vel)
    np.testing.assert_array_equal(segment(policy, observation, "projected_gravity"), sense.projected_gravity)
    np.testing.assert_allclose(segment(policy, observation, "joint_pos"), [-0.1, 0.2])


def test_the_action_follows_the_sensed_gravity(policy):
    """策略看的是感觉到的重力方向：动作 0（重力的 x）就是给的 0.1。"""
    _, runner, data = runner_and_data(policy)
    sense = BodySense(np.zeros(3), np.zeros(3), np.array([0.1, 0.0, -0.995]))
    runner.step(data, STILL, sense)
    assert runner.last_action[0] == pytest.approx(0.1, abs=1e-6)


SCAN_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "policy_scan"
# 看脚下高度的小策略：观测的高度扫描乘 1 / 5 m。
SCAN_SCALE = 0.2


def scan_runner(stairs: Stairs | None = None):
    """看脚下高度的小策略放上测试台（地面在第 0 组，身体的形状在第 3 组）。"""
    policy = load_policy(SCAN_FIXTURE_DIR / "contract.json")
    model = load_policy_body(policy, stairs)
    runner = PolicyRunner(model, policy, spine_for(model))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    return policy, runner, data


def test_the_height_scan_reads_how_high_the_pelvis_is_above_the_floor():
    """平地上：3 x 3 个点都读骨盆离地多高（0.4 m），乘 1/5 m 是 0.08，放在观测的最后；身体自己的腿不挡。"""
    policy, runner, data = scan_runner()
    observation = runner.observation(data, policy.command.vector(STILL))
    pelvis_height = float(data.xpos[1][2])
    np.testing.assert_allclose(segment(policy, observation, "height_scan"), pelvis_height * SCAN_SCALE, atol=1e-9)
    assert observation.size == policy.observation_size


def test_the_height_scan_sees_a_step_in_front_in_grid_order():
    """骨盆前面 5 cm 起有一级 10 cm 高的台阶：网格上往前那一列（x = 0.1 m）读 0.3 m，别的读 0.4 m；先 y 后 x 地排。
    策略的两个动作就是第一个点和正中间的点（都在地面上）。"""
    step = Stairs(start_x=0.05, rise_m=0.1, tread_m=0.3, steps=1, landing_m=0.5, width_m=2.0)
    policy, runner, data = scan_runner(step)
    scan = segment(policy, runner.observation(data, policy.command.vector(STILL)), "height_scan") / SCAN_SCALE
    np.testing.assert_allclose(scan, [0.4, 0.4, 0.3] * 3, atol=1e-9)
    runner.step(data, STILL)
    np.testing.assert_allclose(runner.last_action, [0.4 * SCAN_SCALE, 0.4 * SCAN_SCALE], atol=1e-6)
