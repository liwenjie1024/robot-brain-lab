import math

import mujoco
import numpy as np
import pytest

from nova_body.body import SIDE_NAMES, Side
from nova_body.inverse import (
    CarriedLoad,
    Frame,
    InverseDynamics,
    PushingForce,
    Support,
    SupportKind,
    zero_moment_point,
)

GRAVITY = 9.81
DT = 0.01
STILL_FRAMES = 10


def body_mass(body) -> float:
    return float(body.model.body_subtreemass[body.model.body(body.anatomy.root).id])


def feet(body) -> tuple[Support, ...]:
    return tuple(
        Support(
            f"{SIDE_NAMES[side]}脚",
            leg.sole,
            SupportKind.FOOT,
            half_length=body.foot_length_m / 2,
            half_width=body.foot_width_m / 2,
        )
        for side, leg in body.anatomy.legs.items()
    )


def standing(body, supports=None, loads=()) -> list[Frame]:
    """站着不动的几帧。"""
    qpos = np.array(body.stand.qpos)
    return [Frame(qpos.copy(), supports or feet(body), loads) for _ in range(STILL_FRAMES)]


def column(body, name: str) -> int:
    return [joint.name for joint in body.joints].index(name)


# 站着不动 --------------------------------------------------------------------------------------------


def test_standing_still_needs_the_holding_torques_of_the_stand_pose(body):
    """站着不动：每个关节要的力矩就是站姿里顶住重力的力矩（站姿是另一种算法算的，两边对得上）。"""
    demand = InverseDynamics(body).demand(standing(body), DT)
    for index, joint in enumerate(body.joints):
        if joint.region.value in {"腿", "腰"}:
            assert demand.torques[STILL_FRAMES // 2, index] == pytest.approx(
                body.stand.holding_torque_nm[index], abs=0.05 + 0.02 * abs(body.stand.holding_torque_nm[index])
            )
    assert np.abs(demand.speeds).max() == pytest.approx(0.0, abs=1e-12)


def test_standing_still_the_floor_carries_the_whole_weight(body):
    """站着不动：两只脚受的往上的力加起来就是体重，沿地面的力是 0，压力中心在脚底里面。"""
    demand = InverseDynamics(body).demand(standing(body), DT)
    forces = demand.support_forces[STILL_FRAMES // 2]
    assert sum(force.force_n[2] for force in forces) == pytest.approx(body_mass(body) * GRAVITY, rel=1e-6)
    assert demand.worst_friction_ratio() == pytest.approx(0.0, abs=1e-9)
    assert demand.worst_edge_margin_m() > 0
    assert demand.unbalanced_n.max() == 0.0
    assert not any(demand.lifted)


def test_standing_on_one_foot_with_the_weight_between_the_feet_cannot_hold(body):
    """只让一只脚撑着，可是重心在两只脚中间：这只脚的压力中心跑到了脚底外面（这样站不住）。"""
    left = feet(body)[0]
    demand = InverseDynamics(body).demand(standing(body, supports=(left,)), DT)
    assert demand.worst_edge_margin_m() < 0


def test_pressure_center_of_a_still_body_is_under_its_center_of_mass(body):
    """站着不动时，压力中心就在重心的正下方。"""
    frames = standing(body)
    points = InverseDynamics(body).zero_moment_points(frames, DT, np.zeros(len(frames)))
    data = mujoco.MjData(body.model)
    data.qpos[:] = body.stand.qpos
    mujoco.mj_kinematics(body.model, data)
    mujoco.mj_comPos(body.model, data)
    center = data.subtree_com[body.model.body(body.anatomy.root).id]
    assert points[STILL_FRAMES // 2] == pytest.approx(center[:2], abs=1e-6)


# 外面的力 --------------------------------------------------------------------------------------------


def test_carried_load_adds_its_weight_to_the_floor_and_to_the_arm(nova):
    """两只手各拿 5 kg：地面多托 10 kg 的重量，肩要出的力矩变大。"""
    body = nova.body
    loads = tuple(CarriedLoad(site, 5.0) for site in body.anatomy.palms.values())
    dynamics = InverseDynamics(body)
    empty = dynamics.demand(standing(body), DT)
    holding = dynamics.demand(standing(body, loads=loads), DT)
    middle = STILL_FRAMES // 2
    extra = sum(force.force_n[2] for force in holding.support_forces[middle]) - sum(
        force.force_n[2] for force in empty.support_forces[middle]
    )
    assert extra == pytest.approx(10.0 * GRAVITY, rel=1e-6)
    shoulder = column(body, "left_shoulder_pitch")
    assert abs(holding.torques[middle, shoulder]) > abs(empty.torques[middle, shoulder]) + 1.0


def test_pushing_force_up_at_the_hand_takes_weight_off_the_feet(nova):
    """手被往上托 50 N：两只脚少托 50 N。"""
    body = nova.body
    palm = body.anatomy.palms[Side.RIGHT]
    dynamics = InverseDynamics(body)
    empty = dynamics.demand(standing(body), DT)
    pushed = dynamics.demand(standing(body, loads=(PushingForce(palm, np.array([0.0, 0.0, 50.0])),)), DT)
    middle = STILL_FRAMES // 2
    difference = sum(force.force_n[2] for force in empty.support_forces[middle]) - sum(
        force.force_n[2] for force in pushed.support_forces[middle]
    )
    assert difference == pytest.approx(50.0, rel=1e-6)


def test_supports_that_would_have_to_pull_are_let_go(nova):
    """撑着的地方只能推、不能拉：手被往上托的力比体重还大，两只脚要往下拉住身体才行，
    就当它们都离开了地面；这一帧的力分不出去（做不出来）。"""
    body = nova.body
    lift = PushingForce(body.anatomy.palms[Side.LEFT], np.array([0.0, 0.0, 1.5 * body_mass(body) * GRAVITY]))
    demand = InverseDynamics(body).demand(standing(body, loads=(lift,)), DT)
    middle = STILL_FRAMES // 2
    assert sorted(demand.lifted[middle]) == sorted(support.label for support in feet(body))
    # 分不出去的至少有"多出来的那半个体重"（还有它绕原点的力矩）。
    assert demand.unbalanced_n[middle] >= 0.5 * body_mass(body) * GRAVITY * (1 - 1e-6)


# 动起来 ----------------------------------------------------------------------------------------------


def moving_knee(body, frames: int, speed_rad_s: float) -> list[Frame]:
    """左膝先停着、再匀速地弯、最后停住（脚撑着，只看速度）。"""
    qpos = np.array(body.stand.qpos)
    address = body.model.joint(body.anatomy.legs[Side.LEFT].knee).qposadr[0]
    angles = np.concatenate(
        [np.zeros(20), np.arange(frames) * speed_rad_s * DT, np.full(20, frames * speed_rad_s * DT)]
    )
    result = []
    for angle in angles:
        pose = qpos.copy()
        pose[address] += angle
        result.append(Frame(pose, feet(body)))
    return result


def test_speed_in_the_middle_of_a_steady_turn_is_that_speed(body):
    """一个关节匀速地转：中间那一段的速度就是这个速度（滤过以后也是）。"""
    frames = moving_knee(body, 60, 0.5)
    demand = InverseDynamics(body).demand(frames, DT)
    knee = column(body, body.anatomy.legs[Side.LEFT].knee)
    assert demand.speeds[50, knee] == pytest.approx(0.5, rel=1e-6)
    assert demand.speeds[0, knee] == pytest.approx(0.0, abs=1e-9)
    assert demand.speeds[-1, knee] == pytest.approx(0.0, abs=1e-9)


def test_motion_that_ends_moving_keeps_its_speed_at_the_end(body):
    """动作在还动着的时候结束（跳离地的那一刻）：最后一帧的速度还是那个速度，不当它停住。"""
    frames = moving_knee(body, 60, 0.5)[:-20]
    dynamics = InverseDynamics(body)
    knee = column(body, body.anatomy.legs[Side.LEFT].knee)
    moving = dynamics.demand(frames, DT, ends_at_rest=False)
    stopping = dynamics.demand(frames, DT)
    assert moving.speeds[-1, knee] == pytest.approx(0.5, rel=1e-3)
    assert stopping.speeds[-1, knee] < 0.4


def test_filtering_rounds_off_a_sudden_jump(body):
    """姿势在一帧里跳一下（逆运动学的小毛病）：滤过以后算出来的加速度小得多（约 6 Hz 的低通）。"""
    frames = standing(body)
    frames = frames * 4
    knee_address = body.model.joint(body.anatomy.legs[Side.LEFT].knee).qposadr[0]
    jumped = []
    for index, frame in enumerate(frames):
        pose = frame.qpos.copy()
        if index >= len(frames) // 2:
            pose[knee_address] += 0.05
        jumped.append(Frame(pose, frame.supports))
    dynamics = InverseDynamics(body)
    _, accelerations = dynamics._finite_differences([frame.qpos for frame in jumped], DT)
    dof = int(body.model.joint(body.anatomy.legs[Side.LEFT].knee).dofadr[0])
    raw_peak = 0.05 / DT**2
    assert np.abs(accelerations[:, dof]).max() < raw_peak / 10


# 出错和小工具 ----------------------------------------------------------------------------------------


def test_demand_needs_at_least_two_frames(nova):
    """只有一帧算不出速度：拒绝。"""
    with pytest.raises(ValueError, match="至少要 2 帧"):
        InverseDynamics(nova.body).demand(standing(nova.body)[:1], DT)


@pytest.mark.parametrize("dt", [0.0, -0.01], ids=["0", "负的"])
def test_demand_needs_a_positive_frame_time(nova, dt):
    """每一帧的时间不是正数：拒绝。"""
    with pytest.raises(ValueError, match="必须大于 0"):
        InverseDynamics(nova.body).demand(standing(nova.body), dt)


def test_zero_moment_point_of_a_plain_weight_is_straight_below_it():
    """一个只往上托的力，作用在 (0.1, -0.2) 上：压力中心就在那里，跟平面多高没有关系。"""
    force = np.array([0.0, 0.0, 700.0])
    point = np.array([0.1, -0.2, 0.0])
    moment = np.cross(point, force)
    for height in (0.0, 0.3):
        assert zero_moment_point(force, moment, height) == pytest.approx([0.1, -0.2])


def test_zero_moment_point_does_not_exist_without_an_upward_force():
    """没有往上托的力（飞在空中）：没有压力中心。"""
    assert all(math.isnan(value) for value in zero_moment_point(np.zeros(3), np.zeros(3), 0.0))
