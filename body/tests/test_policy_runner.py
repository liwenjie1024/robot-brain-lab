"""把策略接到身体上的测试：观测的每一项算得对、放得对；按策略的周期才算一次；关节的目标 = 默认 + 动作 x 比例；
软硬写进驱动器；身体对不上（没有这个关节、没有单独的驱动器、步长凑不成周期）就拒绝。

用测试用的小策略：动作 0 = 重力方向的 x，动作 1 = 转弯的命令。
"""

import math
from pathlib import Path

import mujoco
import numpy as np
import pytest

from nova_body.policy import PolicyError, load_policy
from nova_body.policy_runner import PolicyRunner, bind_joints, steps_per_action

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "policy"
STILL = {"lin_vel_x": 0.0, "lin_vel_y": 0.0, "ang_vel_z": 0.0}


@pytest.fixture
def policy():
    return load_policy(FIXTURE_DIR / "contract.json")


def fixture_spec(timestep_s: float = 0.001) -> mujoco.MjSpec:
    spec = mujoco.MjSpec.from_file(str(FIXTURE_DIR / "body.xml"))
    spec.option.timestep = timestep_s
    return spec


def runner_and_data(policy, spec: mujoco.MjSpec | None = None):
    model = (spec or fixture_spec()).compile()
    runner = PolicyRunner(model, policy)
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


def test_the_runner_writes_the_policy_gains_into_the_actuators(policy):
    """建的时候把策略的软硬写进驱动器：刚度、阻尼、力矩的上限都照规约。"""
    model, _, _ = runner_and_data(policy)
    for joint in policy.joints:
        actuator = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, joint.name)
        assert model.actuator_gainprm[actuator, 0] == joint.stiffness_nm_per_rad
        assert model.actuator_biasprm[actuator, 1] == -joint.stiffness_nm_per_rad
        assert model.actuator_biasprm[actuator, 2] == -joint.damping_nms_per_rad
        np.testing.assert_allclose(model.actuator_forcerange[actuator], [-joint.torque_limit_nm, joint.torque_limit_nm])
        assert model.actuator_forcelimited[actuator] == 1


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
    runner.step(data, {**STILL, "ang_vel_z": 0.4})
    np.testing.assert_allclose(runner.last_action, [0.5, 0.4], atol=1e-6)
    np.testing.assert_allclose(data.ctrl, [0.1 + 0.5 * 0.5, -0.2 + 0.25 * 0.4], atol=1e-6)


def test_targets_hold_between_policy_steps(policy):
    """两次之间（20 步，1 毫秒的步长、每秒 50 次）目标不变，命令变了也不变；到第 21 步才按新的命令算。"""
    model, runner, data = runner_and_data(policy)
    runner.step(data, {**STILL, "ang_vel_z": 0.2})
    first = data.ctrl.copy()
    for _ in range(runner.steps_per_action - 1):
        runner.step(data, {**STILL, "ang_vel_z": -0.4})
        mujoco.mj_step(model, data)
        np.testing.assert_array_equal(data.ctrl, first)
    runner.step(data, {**STILL, "ang_vel_z": -0.4})
    assert data.ctrl[1] == pytest.approx(-0.2 + 0.25 * -0.4, abs=1e-6)


def test_the_last_action_is_fed_back_into_the_next_observation(policy):
    """上一次的动作放进下一次的观测（last_action）；重新开始就清零。"""
    _, runner, data = runner_and_data(policy)
    runner.step(data, {**STILL, "ang_vel_z": 0.3})
    observation = runner.observation(data, np.zeros(3))
    np.testing.assert_allclose(segment(policy, observation, "last_action"), runner.last_action)
    runner.reset()
    np.testing.assert_array_equal(runner.last_action, [0.0, 0.0])


def test_a_command_beyond_the_trained_range_stops_the_step(policy):
    """到了算的那一步，命令超出练过的范围就拒绝，目标不动。"""
    _, runner, data = runner_and_data(policy)
    before = data.ctrl.copy()
    with pytest.raises(PolicyError, match="超出了练过的范围"):
        runner.step(data, {**STILL, "ang_vel_z": 0.6})
    np.testing.assert_array_equal(data.ctrl, before)


def test_a_body_without_the_joint_is_refused(policy):
    """身体里没有策略的关节就拒绝。"""
    spec = fixture_spec()
    spec.delete(spec.actuator("joint_b"))
    spec.delete(spec.joint("joint_b"))
    with pytest.raises(PolicyError, match="没有关节 joint_b"):
        bind_joints(spec.compile(), policy)


def test_a_joint_without_its_own_position_actuator_is_refused(policy):
    """关节没有单独带着它的位置驱动器（这里传动比是 2）就拒绝：换算是脊髓层的事。"""
    spec = fixture_spec()
    spec.actuator("joint_a").gear = [2.0, 0, 0, 0, 0, 0]
    with pytest.raises(PolicyError, match="关节 joint_a 没有单独带着它的位置驱动器"):
        bind_joints(spec.compile(), policy)


def test_a_body_without_the_imu_site_is_refused(policy):
    """身体里没有 IMU 的点就拒绝。"""
    spec = fixture_spec()
    spec.delete(spec.site("imu"))
    with pytest.raises(PolicyError, match="没有 IMU 的点 imu"):
        PolicyRunner(spec.compile(), policy)


def test_a_timestep_that_cannot_make_the_policy_period_is_refused(policy):
    """仿真的步长（3 毫秒）凑不成策略的周期（20 毫秒）就拒绝。"""
    with pytest.raises(PolicyError, match="凑不成策略的周期"):
        PolicyRunner(fixture_spec(timestep_s=0.003).compile(), policy)
