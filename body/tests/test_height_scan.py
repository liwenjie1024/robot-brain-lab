"""高度扫描的测试（真的打射线）：网格的顺序和 mjlab 一样；平地上每条射线读到骨盆的高度；楼梯上读到它下面那一级；
网格跟着骨盆转偏航、不跟着歪；打不到的读最远的距离；只打给定的几组形状；不对的设置拒绝。"""

import math

import mujoco
import numpy as np
import pytest

from nova_body.bench import Stairs, add_floor, add_stairs
from nova_body.height_scan import HeightScanner, HeightScanSpec, yaw_rotation

SPEC = HeightScanSpec("pelvis", (1.6, 1.0), (0.1, 0.1), (0.0, 0.0), 5.0, (0,))
# 台阶的边不落在网格的点上（点都在 0.1 的整数倍上），免得一条射线正好打在边上。
STAIRS = Stairs(start_x=0.33, rise_m=0.2, tread_m=0.25, steps=3, landing_m=0.5, width_m=2.0)
ROBOT_GROUP = 3
PELVIS_HEIGHT_M = 1.5


def scan_model(stairs: Stairs | None = None, leg_group: int = ROBOT_GROUP, floor: bool = True) -> mujoco.MjModel:
    """一个骨盆（带自由关节）和它下面的一条腿，站在平地（和楼梯）上方。"""
    spec = mujoco.MjSpec()
    if floor:
        add_floor(spec)
    if stairs is not None:
        add_stairs(spec, stairs)
    pelvis = spec.worldbody.add_body(name="pelvis", pos=[0.0, 0.0, PELVIS_HEIGHT_M])
    pelvis.add_freejoint()
    pelvis.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[0.1, 0.1, 0.05], group=ROBOT_GROUP)
    leg = pelvis.add_body(name="leg", pos=[0.0, 0.0, -0.3])
    leg.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[0.05, 0.05, 0.2], group=leg_group)
    return spec.compile()


def posed(model: mujoco.MjModel, *, yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0) -> mujoco.MjData:
    data = mujoco.MjData(model)
    quaternion = np.zeros(4)
    matrix = (rotation_z(yaw) @ rotation_y(pitch) @ rotation_x(roll)).flatten()
    mujoco.mju_mat2Quat(quaternion, matrix)
    data.qpos[3:7] = quaternion
    mujoco.mj_forward(model, data)
    return data


def rotation_x(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rotation_y(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rotation_z(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def test_the_grid_is_ordered_like_mjlab():
    """1.6 m × 1.0 m、每 10 cm 一点：17 × 11 = 187 点，两头都有；先 y 后 x 地排（第 2 点是 x 往前挪了 10 cm）。"""
    grid = SPEC.grid_m()
    assert SPEC.size == 17 * 11
    np.testing.assert_allclose(grid[0], [-0.8, -0.5], atol=1e-9)
    np.testing.assert_allclose(grid[1], [-0.7, -0.5], atol=1e-9)
    np.testing.assert_allclose(grid[17], [-0.8, -0.4], atol=1e-9)
    np.testing.assert_allclose(grid[-1], [0.8, 0.5], atol=1e-9)


def test_the_grid_can_be_moved():
    """中心可以挪：往前 0.2 m，每一点都往前 0.2 m。"""
    moved = HeightScanSpec("pelvis", (1.6, 1.0), (0.1, 0.1), (0.2, 0.0), 5.0, (0,))
    np.testing.assert_allclose(moved.grid_m() - SPEC.grid_m(), [[0.2, 0.0]] * SPEC.size, atol=1e-9)


def test_over_flat_ground_every_ray_reads_the_pelvis_height():
    """平地上：每条射线都读到骨盆的高度（1.5 m）。"""
    model = scan_model()
    heights = HeightScanner(model, SPEC).scan(posed(model))
    np.testing.assert_allclose(heights, PELVIS_HEIGHT_M, atol=1e-9)


def test_on_stairs_each_ray_reads_the_step_below_it():
    """楼梯上：每条射线读到骨盆比它下面那一级高多少。"""
    model = scan_model(STAIRS)
    heights = HeightScanner(model, SPEC).scan(posed(model))
    expected = [PELVIS_HEIGHT_M - STAIRS.height_at(x) for x, _ in SPEC.grid_m()]
    np.testing.assert_allclose(heights, expected, atol=1e-9)
    assert len(set(np.round(heights, 6))) == 3  # 地面和两级（第三级从 x = 0.83 m 起，网格只到 0.8 m）


def test_the_grid_turns_with_the_heading():
    """骨盆往左转了 90°：网格也转过来，网格上的 (x, y) 在世界里是 (-y, x)。"""
    model = scan_model(STAIRS)
    heights = HeightScanner(model, SPEC).scan(posed(model, yaw=math.pi / 2))
    expected = [PELVIS_HEIGHT_M - STAIRS.height_at(-y) for _, y in SPEC.grid_m()]
    np.testing.assert_allclose(heights, expected, atol=1e-9)


def test_the_grid_does_not_tilt_with_the_pelvis():
    """骨盆往前歪 20°、往左歪 10°：网格还是平的，射线还是竖直的，读到的和没歪时一样。"""
    model = scan_model(STAIRS)
    scanner = HeightScanner(model, SPEC)
    np.testing.assert_allclose(
        scanner.scan(posed(model, pitch=math.radians(20), roll=math.radians(10))), scanner.scan(posed(model)), atol=1e-9
    )


def test_rays_that_hit_nothing_read_the_max_distance():
    """没有地面（打不到），或者地面比最远的距离还远，都读最远的距离（5 m）。"""
    model = scan_model(floor=False)
    assert np.all(HeightScanner(model, SPEC).scan(posed(model)) == SPEC.max_distance_m)
    near = HeightScanSpec("pelvis", (1.6, 1.0), (0.1, 0.1), (0.0, 0.0), 1.0, (0,))
    model = scan_model()
    assert np.all(HeightScanner(model, near).scan(posed(model)) == near.max_distance_m)


@pytest.mark.parametrize(
    ("leg_group", "hit_leg"), [(ROBOT_GROUP, False), (0, True)], ids=["身体在别的组", "身体也在第 0 组"]
)
def test_only_the_given_geom_groups_are_hit(leg_group, hit_leg):
    """只打给定的组：腿在别的组，正下方的射线穿过它读到地面；腿也在第 0 组，就读到腿的顶上（骨盆下面 0.1 m）。
    骨盆自己一直不打。"""
    model = scan_model(leg_group=leg_group)
    heights = HeightScanner(model, SPEC).scan(posed(model))
    center = SPEC.size // 2
    assert heights[center] == pytest.approx(0.1 if hit_leg else PELVIS_HEIGHT_M)


def test_the_heading_comes_from_the_left_side_when_lying():
    """骨盆的前方竖直（躺着）时，偏航用左方算：左方朝世界的 +y，偏航就是 0。"""
    lying = np.array([[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
    np.testing.assert_allclose(yaw_rotation(lying), np.eye(3), atol=1e-9)


def test_a_missing_frame_body_is_refused():
    with pytest.raises(ValueError, match="没有高度扫描的身体"):
        HeightScanner(scan_model(), HeightScanSpec("torso", (1.0, 1.0), (0.1, 0.1), (0.0, 0.0), 5.0, (0,)))


@pytest.mark.parametrize(
    ("size", "resolution", "distance", "groups"),
    [
        ((-1.0, 1.0), (0.1, 0.1), 5.0, (0,)),
        ((1.0, 1.0), (0.0, 0.1), 5.0, (0,)),
        ((1.0, 1.0), (0.1, 0.1), 0.0, (0,)),
        ((1.0, 1.0), (0.1, 0.1), 5.0, ()),
        ((1.0, 1.0), (0.1, 0.1), 5.0, (6,)),
    ],
    ids=["负的大小", "间隔是 0", "最远是 0", "没有组", "没有第 6 组"],
)
def test_bad_scan_settings_are_refused(size, resolution, distance, groups):
    with pytest.raises(ValueError):
        HeightScanSpec("pelvis", size, resolution, (0.0, 0.0), distance, groups)
