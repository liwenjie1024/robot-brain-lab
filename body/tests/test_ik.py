import math

import mujoco
import numpy as np
import pytest

from nova_body.body import Region, Side
from nova_body.ik import (
    HARD,
    POSTURE,
    SELF_CLEARANCE_M,
    SELF_WATCH_M,
    AttitudeGoal,
    CarriedMass,
    Goals,
    IkError,
    PointGoal,
    WholeBodyIk,
    pitch_rotation,
    rotation_error,
    yaw_rotation,
)

FLAT = np.eye(3)
NAN = float("nan")


class Placed:
    """站姿里各个点的位置和重心。"""

    def __init__(self, body, qpos: np.ndarray) -> None:
        self.model = body.model
        self.data = mujoco.MjData(self.model)
        self.data.qpos[:] = qpos
        mujoco.mj_kinematics(self.model, self.data)
        mujoco.mj_comPos(self.model, self.data)
        self.center = self.data.subtree_com[self.model.body(body.anatomy.root).id].copy()

    def site(self, name: str) -> np.ndarray:
        return self.data.site_xpos[self.model.site(name).id].copy()


def stand(body) -> np.ndarray:
    return np.array(body.stand.qpos)


def feet_goals(body, placed: Placed) -> tuple[PointGoal, ...]:
    return tuple(PointGoal(leg.sole, placed.site(leg.sole), FLAT) for leg in body.anatomy.legs.values())


def joint_angle(body, qpos: np.ndarray, name: str) -> float:
    return float(qpos[body.model.joint(name).qposadr[0]])


def driven_angles(body, qpos: np.ndarray, region: Region) -> np.ndarray:
    return np.array([joint_angle(body, qpos, joint.name) for joint in body.joints if joint.region is region])


# 能做到的要求 ----------------------------------------------------------------------------------------


def test_standing_goals_keep_the_stand_pose(body):
    """脚在站姿的地方、重心在站姿的地方：从站姿出发，解出来还是站姿，差不到 0.1 mm。"""
    placed = Placed(body, stand(body))
    goals = Goals(points=feet_goals(body, placed), center_of_mass=placed.center)
    result = WholeBodyIk(body, stand(body)).solve(goals, stand(body))
    assert result.point_error_m < 1e-4
    assert result.center_of_mass_error_m < 1e-4
    assert np.abs(result.qpos[7:] - stand(body)[7:]).max() < 1e-3


def test_lowering_the_center_of_mass_keeps_the_feet_and_lowers_the_hips(body):
    """重心往下 5 cm、脚不动：解出来脚还在原地（差不到 1 mm），重心到了，骨盆低了，腿弯了。"""
    placed = Placed(body, stand(body))
    target = placed.center - np.array([0.0, 0.0, 0.05])
    goals = Goals(points=feet_goals(body, placed), center_of_mass=target)
    result = WholeBodyIk(body, stand(body)).solve(goals, stand(body))
    after = Placed(body, result.qpos)
    assert result.point_error_m < 1e-3
    assert np.linalg.norm(after.center - target) < 1e-3
    root = body.model.body(body.anatomy.root).id
    assert after.data.xpos[root][2] < placed.data.xpos[root][2] - 0.03
    for leg in body.anatomy.legs.values():
        hip = body.model.joint(leg.hip_pitch).id
        before_length = np.linalg.norm(placed.data.xanchor[hip] - placed.site(leg.sole))
        assert np.linalg.norm(after.data.xanchor[hip] - after.site(leg.sole)) < before_length - 0.01


def test_joint_limits_are_never_exceeded(body):
    """要求做不到（脚不动、重心到脚前面 1 m）：解出来的每个关节都还在范围里。"""
    placed = Placed(body, stand(body))
    goals = Goals(points=feet_goals(body, placed), center_of_mass=placed.center + np.array([1.0, 0.0, 0.0]))
    result = WholeBodyIk(body, stand(body)).solve(goals, stand(body))
    model = body.model
    for joint in body.joints:
        index = model.joint(joint.name).id
        if model.jnt_limited[index]:
            low, high = model.jnt_range[index]
            assert low - 1e-9 <= joint_angle(body, result.qpos, joint.name) <= high + 1e-9
    assert result.center_of_mass_error_m > 0.05


def test_parts_that_are_close_but_clear_are_watched_and_left_alone(g1):
    """G1 站着时肘和腕离 9.5 mm：在看着的范围（SELF_WATCH_M）里，但离得比边（SELF_CLEARANCE_M）远，不推开，还是站姿。"""
    placed = Placed(g1, stand(g1))
    goals = Goals(points=feet_goals(g1, placed), center_of_mass=placed.center)
    result = WholeBodyIk(g1, stand(g1)).solve(goals, stand(g1))
    assert SELF_CLEARANCE_M < result.closest_self_m < SELF_WATCH_M
    assert result.closest_self_m == pytest.approx(0.0095, abs=5e-4)
    assert np.abs(result.qpos[7:] - stand(g1)[7:]).max() < 1e-3


def test_nothing_is_close_when_nova_stands(nova):
    """Nova 站着时，会动得开的两段最近的是两条大腿（20 mm），都不在看着的范围里（同一只手的手指之间不算）。"""
    body = nova.body
    placed = Placed(body, stand(body))
    goals = Goals(points=feet_goals(body, placed), center_of_mass=placed.center)
    assert WholeBodyIk(body, stand(body)).solve(goals, stand(body)).closest_self_m == math.inf


def test_carried_mass_counts_in_the_center_of_mass(nova):
    """手里拿着东西，重心往手那边挪：挪的量 = 东西的质量 x 到手的距离 ÷ 总质量。"""
    body = nova.body
    ik = WholeBodyIk(body, stand(body))
    placed = Placed(body, stand(body))
    goals = Goals(points=feet_goals(body, placed))
    ik.solve(goals, stand(body))
    palm = body.anatomy.palms[Side.LEFT]
    alone = ik.center_of_mass()
    holding = ik.center_of_mass((CarriedMass(palm, 5.0),))
    expected = alone + 5.0 * (placed.site(palm) - alone) / (ik.mass + 5.0)
    assert holding == pytest.approx(expected, abs=1e-6)


# 只动一部分、轻一点的要求 ------------------------------------------------------------------------------


def test_joints_outside_the_moving_regions_stay_where_they_were(nova):
    """只让腿和躯干动：重心要往前挪很多，手臂和头也一点不动（只用腿的动作就是这样）。"""
    body = nova.body
    placed = Placed(body, stand(body))
    goals = Goals(points=feet_goals(body, placed), center_of_mass=placed.center + np.array([0.06, 0.0, 0.0]))
    result = WholeBodyIk(body, stand(body), moving=frozenset({Region.LEG, Region.WAIST})).solve(goals, stand(body))
    for region in (Region.ARM, Region.NECK):
        assert driven_angles(body, result.qpos, region) == pytest.approx(driven_angles(body, stand(body), region))
    assert driven_angles(body, result.qpos, Region.LEG) != pytest.approx(driven_angles(body, stand(body), Region.LEG))


def test_dodging_arms_do_not_help_with_the_center_of_mass(nova):
    """只用腿和躯干、手臂只为躲开才动：重心要往前挪 6 cm，手臂也不帮着凑（没碰到它们，它们就不动），
    解出来和根本不让手臂动的一样。"""
    body = nova.body
    placed = Placed(body, stand(body))
    goals = Goals(points=feet_goals(body, placed), center_of_mass=placed.center + np.array([0.06, 0.0, 0.0]))
    legs = frozenset({Region.LEG, Region.WAIST})
    dodging = WholeBodyIk(body, stand(body), moving=legs, dodging=frozenset({Region.ARM})).solve(goals, stand(body))
    fixed = WholeBodyIk(body, stand(body), moving=legs).solve(goals, stand(body))
    assert driven_angles(body, dodging.qpos, Region.ARM) == pytest.approx(driven_angles(body, stand(body), Region.ARM))
    assert dodging.qpos == pytest.approx(fixed.qpos, abs=1e-9)


def test_weak_rotation_weight_lets_the_foot_stay_flat(nova):
    """脚的位置要对上、朝向（脚尖朝下 30°）只是很轻的要求：脚基本还是平的；朝向用 HARD 的话就真的转过去。"""
    body = nova.body
    placed = Placed(body, stand(body))
    leg = body.anatomy.legs[Side.LEFT]
    tilted = pitch_rotation(math.radians(30))
    lifted = placed.site(leg.sole) + np.array([0.0, 0.0, 0.08])
    others = tuple(goal for goal in feet_goals(body, placed) if goal.site != leg.sole)

    def foot_pitch_error(rotation_weight: float) -> float:
        goal = PointGoal(leg.sole, lifted, tilted, rotation_weight=rotation_weight)
        result = WholeBodyIk(body, stand(body)).solve(
            Goals(points=(*others, goal), center_of_mass=placed.center * np.array([1.0, 1.0, NAN])), stand(body)
        )
        after = Placed(body, result.qpos)
        current = after.data.site_xmat[body.model.site(leg.sole).id].reshape(3, 3)
        return float(np.linalg.norm(rotation_error(current, tilted)))

    assert foot_pitch_error(HARD) < math.radians(1)
    assert foot_pitch_error(POSTURE / 100) > math.radians(20)


def test_posture_goal_pulls_the_free_joints_toward_the_given_pose(nova):
    """这一帧给了参照的姿势：没有别的要求管的关节（肘）就去参照姿势里的角度。"""
    body = nova.body
    placed = Placed(body, stand(body))
    reference = stand(body)
    elbow = body.model.joint("left_elbow").qposadr[0]
    reference[elbow] = math.radians(60)
    goals = Goals(points=feet_goals(body, placed), posture=reference, posture_weight=1.0)
    result = WholeBodyIk(body, stand(body)).solve(goals, stand(body))
    assert result.qpos[elbow] == pytest.approx(math.radians(60), abs=1e-3)


def test_near_keeps_free_joints_close_to_the_previous_frame(nova):
    """给了上一帧的姿势（手臂抬着）：没人管的手臂留得离它更近，不一下子跳回参照的姿势。"""
    body = nova.body
    placed = Placed(body, stand(body))
    previous = stand(body)
    shoulder = body.model.joint("left_shoulder_pitch").qposadr[0]
    previous[shoulder] = math.radians(40)
    goals = Goals(points=feet_goals(body, placed))
    alone = WholeBodyIk(body, stand(body)).solve(goals, previous).qpos[shoulder]
    kept = WholeBodyIk(body, stand(body)).solve(Goals(points=feet_goals(body, placed), near=previous), previous)
    assert abs(kept.qpos[shoulder] - previous[shoulder]) < abs(alone - previous[shoulder])


def test_attitude_goal_turns_the_trunk(nova):
    """要躯干往前倾 20°（重心只管前后左右）：解出来胸往前倾了差不多 20°。"""
    body = nova.body
    placed = Placed(body, stand(body))
    lean = pitch_rotation(math.radians(20))
    goals = Goals(
        points=feet_goals(body, placed),
        attitudes=(AttitudeGoal(body.anatomy.trunk, lean, HARD),),
        center_of_mass=placed.center * np.array([1.0, 1.0, NAN]),
    )
    result = WholeBodyIk(body, stand(body)).solve(goals, stand(body))
    after = Placed(body, result.qpos)
    chest = after.data.xmat[body.model.body(body.anatomy.trunk).id].reshape(3, 3)
    assert np.linalg.norm(rotation_error(chest, lean)) < math.radians(1)


# 出错 ------------------------------------------------------------------------------------------------


def test_unknown_site_is_rejected(nova):
    """要一个模型里没有的点：报错，说清楚是哪个点。"""
    body = nova.body
    goals = Goals(points=(PointGoal("no_such_site", np.zeros(3)),))
    with pytest.raises(IkError, match="no_such_site"):
        WholeBodyIk(body, stand(body)).solve(goals, stand(body))


# 转动的小工具 ----------------------------------------------------------------------------------------


def test_pitch_rotation_positive_is_nose_down():
    """往前倾（正的）：朝前的那根轴往下转。"""
    forward = pitch_rotation(math.radians(30)) @ np.array([1.0, 0.0, 0.0])
    assert forward == pytest.approx([math.cos(math.radians(30)), 0.0, -math.sin(math.radians(30))])


def test_yaw_rotation_positive_turns_left():
    """绕朝上的轴转（正的）：朝前的那根轴往左转。"""
    forward = yaw_rotation(math.radians(90)) @ np.array([1.0, 0.0, 0.0])
    assert forward == pytest.approx([0.0, 1.0, 0.0], abs=1e-12)


@pytest.mark.parametrize("degrees", [0.0, 2.0, 5.0])
def test_rotation_error_is_the_small_turn_between_two_attitudes(degrees):
    """两个姿态差一个绕一根轴的转动：误差是这根轴乘这个角度的正弦（角度小的时候就是角度）。"""
    angle = math.radians(degrees)
    error = rotation_error(np.eye(3), pitch_rotation(angle))
    assert error == pytest.approx([0.0, math.sin(angle), 0.0], abs=1e-12)
