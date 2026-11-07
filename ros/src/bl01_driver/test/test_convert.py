"""몸의 JSON 메시지 ↔ BL-01 ROS 2 메시지 바꾸기"""

import math

import pytest
from bl01_msgs.msg import CombatEvent, MechaStatus
from geometry_msgs.msg import Twist

from bl01_driver import convert

from .samples import DESTROYED, SHOT_HIT, SHOT_MISS, STATE


def test_state_keeps_every_field_of_the_contract():
    """상태 한 장의 모든 값이 이름만 바뀌어(snake_case) 그대로 옮겨진다"""
    message = convert.state_message(STATE)

    assert (message.seq, message.episode, message.sim_time, message.scenario) == (41, 3, 12.345, "skirmish")
    assert list(message.bodies) == STATE["bodies"]
    mecha = message.mecha
    assert list(mecha.position) == [10.0, 0.0, 30.5]
    assert mecha.mode == MechaStatus.MODE_FLYING
    assert (mecha.hp, mecha.max_hp, mecha.energy, mecha.pushing) == (960.0, 1000.0, 80.5, False)
    assert (mecha.velocity.linear.x, mecha.velocity.linear.y, mecha.velocity.linear.z, mecha.velocity.angular.z) == (19.6, -0.5, 0.2, 0.1)
    assert mecha.command.linear.x == 20.0
    assert (mecha.weapon.aim_target, mecha.weapon.has_aim_error, mecha.weapon.aim_error) == ("drone-1", True, 0.4)
    assert mecha.weapon.has_aim_point is False
    unit = message.units[0]
    assert (unit.id, unit.name, unit.hp, unit.max_hp, unit.alive, unit.armed) == ("drone-1", "표적 드론 1", 30.0, 60.0, True, True)
    assert list(unit.velocity) == [0.0, 12.0, 0.0]
    assert (message.threats[0].shooter, message.threats[0].seconds_to_fire) == ("drone-1", 0.8)


def test_state_stamp_is_simulation_time_in_odom_frame():
    """header는 시뮬레이션 시각과 odom 좌표계 (rosbag2로 다시 돌릴 때 시뮬레이션 시각을 따른다)"""
    header = convert.state_message(STATE).header

    assert (header.stamp.sec, header.stamp.nanosec, header.frame_id) == (12, 345_000_000, "odom")


def test_missing_values_become_empty_text_and_flags():
    """규약에서 없는 값(null·빠진 필드)은 빈 글과 has_* 표시로 옮긴다"""
    state = {**STATE, "mecha": {**STATE["mecha"], "weapon": {"ready": False, "cooldown": 0.3, "aimTarget": None}}}

    weapon = convert.state_message(state).mecha.weapon

    assert (weapon.aim_target, weapon.has_aim_error, weapon.has_aim_point) == ("", False, False)
    assert convert.state_message(STATE).mecha.guard.unit == ""


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.0, (0, 0)), (1.5, (1, 500_000_000)), (2.9999999999, (3, 0))],
    ids=["0초", "1.5초", "반올림으로 다음 초"],
)
def test_stamp_boundaries(seconds, expected):
    """경계값: 나노초가 10억이 되면 다음 초로 넘긴다"""
    time = convert.stamp(seconds)

    assert (time.sec, time.nanosec) == expected


def test_combat_events():
    """맞힌 사격·빗나간 사격·격파를 한 메시지 꼴로 옮긴다"""
    hit = convert.combat_event(SHOT_HIT)
    miss = convert.combat_event(SHOT_MISS)
    destroyed = convert.combat_event(DESTROYED)

    assert (hit.kind, hit.shooter, hit.has_hit, hit.hit_unit, hit.hit_damage, hit.hit_blocked) == (
        CombatEvent.KIND_SHOT,
        "mecha",
        True,
        "drone-1",
        30.0,
        False,
    )
    assert list(hit.origin) == [10.0, 0.0, 32.0]
    assert list(hit.end) == [180.0, 0.0, 30.0]
    assert (miss.has_hit, miss.hit_unit) == (False, "")
    assert (destroyed.kind, destroyed.unit, destroyed.sim_time) == (CombatEvent.KIND_DESTROYED, "drone-1", 14.0)


def test_odometry_uses_torso_pose_and_body_velocity():
    """표준 /odom·/tf: 위치는 기체 위치, 자세는 몸통의 실제 자세, 속도는 몸 기준"""
    odom, transform = convert.odometry(STATE)

    assert (odom.header.frame_id, odom.child_frame_id) == ("odom", "base_link")
    assert (odom.pose.pose.position.x, odom.pose.pose.position.z) == (10.0, 30.5)
    assert odom.pose.pose.orientation.z == pytest.approx(0.3826834)
    assert odom.twist.twist.linear.x == 19.6
    assert transform.transform.translation.z == 30.5
    assert transform.child_frame_id == "base_link"


def test_orientation_falls_back_to_heading_without_body_poses():
    """경계값: 몸체 자세가 없으면 기수 방향만으로 자세를 만든다"""
    qw, qx, qy, qz = convert.torso_orientation([], math.pi / 2)

    assert (qw, qx, qy, qz) == pytest.approx((math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4)))


def test_commands_from_requests():
    """서비스 요청 → 몸의 명령: 빈 글은 '없음'으로 보고 필드를 뺀다"""
    velocity = Twist()
    velocity.linear.x, velocity.linear.y, velocity.linear.z, velocity.angular.z = 20.0, -5.0, 2.0, 0.3

    assert convert.velocity_command(velocity) == {"type": "velocity", "forward": 20.0, "sideways": -5.0, "up": 2.0, "turn": 0.3}
    assert convert.guard_command(True, "drone-2") == {"type": "guard", "raised": True, "unit": "drone-2"}
    assert convert.guard_command(False, "") == {"type": "guard", "raised": False}
    assert convert.reset_command("") == {"type": "reset"}
    assert convert.reset_command("skirmish") == {"type": "reset", "scenario": "skirmish"}
    assert convert.push_command([0.0, -1e6, 0.0], 200) == {"type": "push", "force": [0.0, -1e6, 0.0], "durationMs": 200}


@pytest.mark.parametrize("missing", ["episode", "mecha", "units"], ids=["되돌린 횟수", "기체", "드론"])
def test_state_without_required_field_fails(missing):
    """실패: 규약의 필드가 빠진 상태는 바꾸지 못하고 KeyError (노드가 버리고 기록한다)"""
    state = {key: value for key, value in STATE.items() if key != missing}

    with pytest.raises(KeyError):
        convert.state_message(state)
