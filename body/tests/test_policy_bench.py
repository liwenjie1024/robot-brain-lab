"""测试台上跑一个策略的测试：身体放上测试台（步长、积分的方法、地面、楼梯）；站着、躺着开始；摔倒怎么算；
骨盆的高度从脚下那一级算；速度按骨盆朝的方向量；推在胸上；功和走过的路；跌倒的反射可以关掉。
用测试用的小策略和小身体（测试台不认识它：推骨盆、不做状态估计、反射看真的歪斜）。"""

import itertools
import math
from pathlib import Path

import mujoco
import nova_rt
import numpy as np
import pytest

from nova_body.bench import FLOOR, GROUND_CONDIM, GROUND_GROUP, SLIPPERY_FRICTION, TIMESTEP_S, Stairs
from nova_body.policy import load_policy
from nova_body.policy_bench import (
    START_CLEARANCE_M,
    STILL,
    PolicyBench,
    StartPose,
    default_positions,
    load_policy_body,
    lowest_point_m,
    start_data,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "policy"
STAIRS = Stairs(start_x=1.0, rise_m=0.2, tread_m=0.25, steps=3, landing_m=0.5, width_m=1.0)
DEFAULT_FRICTION = 1.0


@pytest.fixture
def policy():
    return load_policy(FIXTURE_DIR / "contract.json")


def stair_geoms(model: mujoco.MjModel) -> list[int]:
    return [geom for geom in range(model.ngeom) if model.geom(geom).name.startswith("stair_")]


def test_the_policy_body_gets_the_bench_settings_and_floor(policy):
    """练的时候用的身体放上测试台：步长 1 毫秒（练的时候是 5 毫秒）、隐式的积分、测试台的地面，没有楼梯。"""
    model = load_policy_body(policy)
    assert model.opt.timestep == TIMESTEP_S
    assert model.opt.integrator == mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, FLOOR) >= 0
    assert stair_geoms(model) == []


def test_the_start_is_the_default_pose_just_above_the_floor(policy):
    """站着开始：关节在默认的姿势，最低的一点比地面高 1 厘米，没有歪。"""
    model = load_policy_body(policy)
    data = start_data(model, default_positions(policy))
    assert lowest_point_m(model, data) == pytest.approx(START_CLEARANCE_M, abs=1e-9)
    for joint in policy.joints:
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint.name)
        assert data.qpos[model.jnt_qposadr[joint_id]] == joint.default_position_rad
    assert data.xmat[1].reshape(3, 3)[2, 2] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("pose", "axis", "points_up"),
    [
        (StartPose.PRONE, 0, False),  # 趴着：骨盆的前方朝下
        (StartPose.SUPINE, 0, True),  # 仰着：骨盆的前方朝上
        (StartPose.SIDE, 1, True),  # 侧躺着：骨盆的左边朝上（右边着地）
    ],
    ids=["趴着", "仰着", "侧躺着"],
)
def test_lying_starts_turn_the_pelvis_and_rest_just_above_the_floor(policy, pose, axis, points_up):
    """躺着开始：骨盆横过来（歪 90°），头朝 +x，该朝上的朝上；最低的一点也比地面高 1 厘米。"""
    model = load_policy_body(policy)
    data = start_data(model, default_positions(policy), pose)
    rotation = data.xmat[1].reshape(3, 3)
    assert rotation[2, 2] == pytest.approx(0.0, abs=1e-9)
    assert rotation[0, 2] == pytest.approx(1.0)
    assert rotation[2, axis] == pytest.approx(1.0 if points_up else -1.0)
    assert lowest_point_m(model, data) == pytest.approx(START_CLEARANCE_M, abs=1e-9)


def test_the_start_can_be_moved_along_x(policy):
    """可以在 x 的别处开始（比如楼梯前面）。"""
    model = load_policy_body(policy)
    assert start_data(model, default_positions(policy), x_m=-2.0).xpos[1][0] == pytest.approx(-2.0)


def test_stairs_go_up_to_a_landing_and_down_again():
    """3 级的楼梯：上 3 级（每级 0.25 m）、0.5 m 的平台、下 3 级（最后一下踩到地面）；前后都是地面。"""
    assert (STAIRS.top_start_x, STAIRS.top_end_x, STAIRS.end_x) == pytest.approx((1.75, 2.25, 2.75))
    expected = {0.99: 0, 1.0: 1, 1.24: 1, 1.25: 2, 1.6: 3, 2.0: 3, 2.25: 2, 2.5: 1, 2.74: 1, 2.75: 0, 5.0: 0}
    for x, level in expected.items():
        assert STAIRS.step_at(x) == level, x
    assert STAIRS.height_at(2.0) == pytest.approx(0.6)


def test_each_stair_box_is_where_its_level_is():
    """楼梯的每一块正中间就是它那一级；一共 2 × 3 块，没有缝。"""
    boxes = STAIRS.boxes()
    assert len(boxes) == 2 * STAIRS.steps
    for begin, end, level in boxes:
        assert STAIRS.step_at((begin + end) / 2) == level
    for (_, end, _), (begin, _, _) in itertools.pairwise(boxes):
        assert begin == pytest.approx(end)


def test_stairs_on_the_bench_are_solid_and_feel_like_the_floor(policy):
    """楼梯上了测试台：每一块从地面垒到那一级的高度，接触和地面一样（只被身体碰、地面说了算）；
    滑的那一级（上的和下的）摩擦小，别的和地面一样。"""
    model = load_policy_body(policy, Stairs(**{**STAIRS.__dict__, "slippery_levels": frozenset({2})}))
    floor = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, FLOOR)
    geoms = stair_geoms(model)
    assert len(geoms) == 2 * STAIRS.steps
    for geom, (_, _, level) in zip(geoms, STAIRS.boxes(), strict=True):
        assert 2 * model.geom_size[geom][2] == pytest.approx(level * STAIRS.rise_m)
        assert model.geom_pos[geom][2] == pytest.approx(level * STAIRS.rise_m / 2)
        assert model.geom_priority[geom] == model.geom_priority[floor]
        assert (model.geom_contype[geom], model.geom_conaffinity[geom]) == (0, 1)
        friction = SLIPPERY_FRICTION[0] if level == 2 else DEFAULT_FRICTION
        assert model.geom_friction[geom][0] == pytest.approx(friction)
    assert sum(model.geom_friction[geom][0] < DEFAULT_FRICTION for geom in geoms) == 2


def test_falling_is_a_big_tilt_or_a_low_pelvis(policy):
    """骨盆歪过 60° 算摔倒，50° 不算；骨盆低到站着时的一半以下也算。"""
    bench = PolicyBench(policy, sensed=False)
    data = bench.data
    assert not bench.fallen()
    for tilt_deg, fallen in ((50.0, False), (61.0, True)):
        data.qpos[3:7] = [math.cos(math.radians(tilt_deg) / 2), math.sin(math.radians(tilt_deg) / 2), 0.0, 0.0]
        mujoco.mj_kinematics(bench.model, data)
        assert bench.tilt_deg() == pytest.approx(tilt_deg)
        assert bench.fallen() is fallen
    data.qpos[3:7] = [1.0, 0.0, 0.0, 0.0]
    data.qpos[2] = 0.4 * bench.standing_height_m
    mujoco.mj_kinematics(bench.model, data)
    assert bench.fallen()


def test_the_pelvis_height_is_counted_from_the_step_below(policy):
    """在楼梯上，骨盆的高度从它下面那一级算：站在第 2 级上和站在地上一样高，就没有摔倒。"""
    bench = PolicyBench(policy, sensed=False, stairs=STAIRS)
    data = bench.data
    data.qpos[0] = 1.3
    data.qpos[2] = bench.standing_height_m + 2 * STAIRS.rise_m
    mujoco.mj_kinematics(bench.model, data)
    assert bench.pelvis_height_m() == pytest.approx(bench.standing_height_m)
    assert not bench.fallen()


def test_velocity_is_measured_along_where_the_pelvis_faces(policy):
    """骨盆朝世界的 y 方向（转了 90°），往 y 走 1 m/s、绕竖轴转 0.5 rad/s：就是往前 1、往左 0、往左转 0.5。"""
    bench = PolicyBench(policy, sensed=False)
    data = bench.data
    data.qpos[3:7] = [math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4)]
    data.qvel[:3] = [0.0, 1.0, 0.0]
    data.qvel[3:6] = [0.0, 0.0, 0.5]
    mujoco.mj_kinematics(bench.model, data)
    np.testing.assert_allclose(bench.heading_velocity(), [1.0, 0.0, 0.5], atol=1e-9)


def test_a_push_is_applied_only_on_the_step_it_is_given(policy):
    """推的力只在给的那一步加在推的地方上（不认识的身体推骨盆），下一步不给就没有了。"""
    bench = PolicyBench(policy, sensed=False)
    assert bench.trunk == bench.root
    bench.step(STILL, push_n=(5.0, -2.0, 0.0))
    np.testing.assert_allclose(bench.data.xfrc_applied[bench.trunk, :3], [5.0, -2.0, 0.0])
    bench.step(STILL)
    np.testing.assert_allclose(bench.data.xfrc_applied[bench.trunk], 0.0)


def test_work_distance_and_time_only_add_up(policy):
    """走过的路、做的正功只会变多；每一步是 1 毫秒。"""
    bench = PolicyBench(policy, sensed=False)
    work, distance = 0.0, 0.0
    for step in range(1, 301):
        bench.step(STILL, push_n=(3.0, 0.0, 0.0) if step < 100 else (0.0, 0.0, 0.0))
        assert bench.work_j >= work
        assert bench.distance_m >= distance
        work, distance = bench.work_j, bench.distance_m
    assert bench.time_s == pytest.approx(300 * TIMESTEP_S)
    assert distance > 0.0


def test_a_sensed_bench_needs_a_body_it_knows(policy):
    """策略要看感觉到的（IMU、状态估计），测试台得知道 IMU 和脚在哪；测试用的小身体不知道，就拒绝。"""
    with pytest.raises(ValueError, match="做不了状态估计"):
        PolicyBench(policy, sensed=True)


@pytest.mark.parametrize(("fall_reflex", "mode"), [(True, nova_rt.MODE_FALLING), (False, nova_rt.MODE_NORMAL)])
def test_the_fall_reflex_can_be_switched_off_for_getting_up(policy, fall_reflex, mode):
    """趴着开始：跌倒的反射开着，马上就是"在摔倒"（全身变软）；关掉（考"起来"的时候），策略照常管。"""
    bench = PolicyBench(policy, sensed=False, start=StartPose.PRONE, fall_reflex=fall_reflex)
    tick = bench.step(STILL)
    assert tick.mode == mode
    assert tick.reflexes is fall_reflex


def test_the_ground_does_not_take_the_body_models_defaults():
    """看脚下高度的小身体在模型里说"形状都在第 3 组"：测试台的地面、楼梯照样在第 0 组（高度扫描打的那一组），
    摩擦、软硬照样是测试台的。"""
    policy = load_policy(Path(__file__).parent / "fixtures" / "policy_scan" / "contract.json")
    model = load_policy_body(policy, STAIRS)
    ground = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, FLOOR), *stair_geoms(model)]
    for geom in ground:
        assert model.geom_group[geom] == GROUND_GROUP
        assert model.geom_friction[geom][0] == pytest.approx(DEFAULT_FRICTION)
        assert model.geom_condim[geom] == GROUND_CONDIM
    pelvis = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "pelvis")
    assert model.geom_group[pelvis] == 3
