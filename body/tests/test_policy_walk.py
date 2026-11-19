"""按命令表考一个走路的策略的测试：身体放上测试台（步长、积分的方法、地面）；开始的姿势；摔倒怎么算；
速度按骨盆朝的方向量；结果的表。用测试用的小策略和小身体。"""

import math
from pathlib import Path

import mujoco
import numpy as np
import pytest

from nova_body.bench import FLOOR, TIMESTEP_S
from nova_body.policy import load_policy
from nova_body.policy_walk import (
    START_CLEARANCE_M,
    STILL,
    Segment,
    SegmentResult,
    describe,
    has_fallen,
    heading_velocity,
    load_policy_body,
    lowest_point_m,
    start_data,
    walk,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "policy"


@pytest.fixture
def policy():
    return load_policy(FIXTURE_DIR / "contract.json")


def test_the_policy_body_gets_the_bench_settings_and_floor(policy):
    """练的时候用的身体放上测试台：步长 1 毫秒（练的时候是 5 毫秒）、隐式的积分、测试台的地面。"""
    model = load_policy_body(policy)
    assert model.opt.timestep == TIMESTEP_S
    assert model.opt.integrator == mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, FLOOR) >= 0


def test_the_walk_starts_in_the_default_pose_just_above_the_floor(policy):
    """开始时关节在默认的姿势，最低的一点比地面高 1 厘米。"""
    model = load_policy_body(policy)
    data = start_data(model, policy)
    assert lowest_point_m(model, data) == pytest.approx(START_CLEARANCE_M, abs=1e-9)
    for joint in policy.joints:
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint.name)
        assert data.qpos[model.jnt_qposadr[joint_id]] == joint.default_position_rad


def test_falling_is_a_big_tilt_or_a_low_pelvis(policy):
    """骨盆歪过 60° 算摔倒，50° 不算；骨盆低到开始时的一半以下也算。"""
    model = load_policy_body(policy)
    data = start_data(model, policy)
    root = 1
    height = float(data.xpos[root][2])
    assert not has_fallen(data, root, height)
    for tilt_deg, fallen in ((50.0, False), (61.0, True)):
        data.qpos[3:7] = [math.cos(math.radians(tilt_deg) / 2), math.sin(math.radians(tilt_deg) / 2), 0.0, 0.0]
        mujoco.mj_kinematics(model, data)
        assert has_fallen(data, root, height) is fallen
    data.qpos[3:7] = [1.0, 0.0, 0.0, 0.0]
    data.qpos[2] = 0.4 * height
    mujoco.mj_kinematics(model, data)
    assert has_fallen(data, root, height)


def test_velocity_is_measured_along_where_the_pelvis_faces(policy):
    """骨盆朝世界的 y 方向（转了 90°），往 y 走 1 m/s、绕竖轴转 0.5 rad/s：就是往前 1、往左 0、往左转 0.5。"""
    model = load_policy_body(policy)
    data = start_data(model, policy)
    data.qpos[3:7] = [math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4)]
    data.qvel[:3] = [0.0, 1.0, 0.0]
    data.qvel[3:6] = [0.0, 0.0, 0.5]
    mujoco.mj_kinematics(model, data)
    np.testing.assert_allclose(heading_velocity(model, data), [1.0, 0.0, 0.5], atol=1e-9)


def test_a_short_schedule_gives_one_result_per_segment_walked(policy):
    """照一张短的命令表走：每走过一段有一个结果，名字、命令和表里的一样，走过的路不是负的。"""
    schedule = (Segment("站着", 0.2, STILL), Segment("转弯", 0.2, {**STILL, "ang_vel_z": 0.2}))
    results = walk(policy, schedule)
    assert 1 <= len(results) <= len(schedule)
    for result, segment in zip(results, schedule, strict=False):
        assert result.label == segment.label
        assert result.command == segment.command
        assert result.distance_m >= 0.0
        assert 0.0 <= result.limited_share <= 1.0
        assert result.reflex_share == 0.0
    if len(results) < len(schedule):
        assert results[-1].fell


def test_the_table_writes_a_dash_for_what_was_not_measured():
    """一开始就摔了、没量到的，表里写 —，不写 nan。"""
    fallen = SegmentResult(
        label="站着",
        command=dict(STILL),
        measured={"lin_vel_x": math.nan, "lin_vel_y": math.nan, "ang_vel_z": math.nan},
        error={"lin_vel_x": math.nan, "lin_vel_y": math.nan, "ang_vel_z": math.nan},
        distance_m=0.3,
        fell=True,
        limited_share=0.25,
        reflex_share=0.0,
        velocity_error_m_s=math.nan,
        tilt_error_deg=math.nan,
    )
    table = describe([fallen])
    assert "nan" not in table
    assert "—、—、—" in table
    assert "摔了" in table
    assert "25% 的步" in table


def test_a_sensed_walk_needs_a_body_the_bench_knows(policy):
    """测试台不认识的身体（测试用的小身体没有 IMU 的传感器）：只看真数可以走，要策略看感觉到的就拒绝。"""
    with pytest.raises(ValueError, match="做不了状态估计"):
        walk(policy, (Segment("站着", 0.1, STILL),), sensed=True)
