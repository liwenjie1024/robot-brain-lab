"""몸(시뮬레이터)의 JSON 메시지(contracts/sim)와 BL-01 ROS 2 메시지(bl01_msgs)를 서로 바꾼다.

바꾸는 일만 하고 보내거나 받지 않는다. 두 규약이 같은 내용이어야 하므로 필드가 바뀌면 둘 다 고치고 여기 시험을 고친다.
"""

from __future__ import annotations

import math

from bl01_msgs.msg import CombatEvent, GuardStatus, MechaStatus, State, Threat, UnitStatus, WeaponStatus
from builtin_interfaces.msg import Time
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry

ODOM_FRAME = "odom"
BASE_FRAME = "base_link"
# 상태의 bodies는 몸체마다 [x, y, z, qw, qx, qy, qz]이고, 첫 몸체가 기체 몸통이다 (장면 설명의 movingBodies 순서)
POSE_SIZE = 7
NANOS_PER_SECOND = 1_000_000_000


def stamp(seconds: float) -> Time:
    """시뮬레이션 시각(초) → ROS 시각"""
    whole = math.floor(seconds)
    nanos = round((seconds - whole) * NANOS_PER_SECOND)
    if nanos >= NANOS_PER_SECOND:
        whole, nanos = whole + 1, nanos - NANOS_PER_SECOND
    return Time(sec=int(whole), nanosec=int(nanos))


def twist(velocity: dict) -> Twist:
    """몸 기준 속도 {forward, sideways, up, turn} → Twist (REP 103: x 앞, y 왼쪽, z 위, 왼쪽으로 도는 것이 +)"""
    message = Twist()
    message.linear.x = float(velocity["forward"])
    message.linear.y = float(velocity["sideways"])
    message.linear.z = float(velocity["up"])
    message.angular.z = float(velocity["turn"])
    return message


def state_message(state: dict) -> State:
    message = State()
    message.header.stamp = stamp(state["simTime"])
    message.header.frame_id = ODOM_FRAME
    message.seq = int(state["seq"])
    message.episode = int(state["episode"])
    message.sim_time = float(state["simTime"])
    message.scenario = state["scenario"]
    message.bodies = [float(value) for value in state["bodies"]]
    message.mecha = mecha_status(state["mecha"])
    message.units = [unit_status(unit) for unit in state["units"]]
    message.threats = [Threat(shooter=threat["from"], seconds_to_fire=float(threat["secondsToFire"])) for threat in state["threats"]]
    return message


def mecha_status(mecha: dict) -> MechaStatus:
    message = MechaStatus()
    message.position = vector(mecha["position"])
    message.heading = float(mecha["heading"])
    message.altitude = float(mecha["altitude"])
    message.velocity = twist(mecha["velocity"])
    message.command = twist(mecha["command"])
    message.mode = mecha["mode"]
    message.hp = float(mecha["hp"])
    message.max_hp = float(mecha["maxHp"])
    message.energy = float(mecha["energy"])
    message.weapon = weapon_status(mecha["weapon"])
    message.guard = GuardStatus(raised=bool(mecha["guard"]["raised"]), unit=mecha["guard"]["unit"] or "")
    message.pushing = bool(mecha["pushing"])
    return message


def weapon_status(weapon: dict) -> WeaponStatus:
    message = WeaponStatus()
    message.ready = bool(weapon["ready"])
    message.cooldown = float(weapon["cooldown"])
    message.aim_target = weapon["aimTarget"] or ""
    message.has_aim_error = "aimError" in weapon
    message.aim_error = float(weapon.get("aimError", 0.0))
    message.has_aim_point = "aimPoint" in weapon
    message.aim_point = vector(weapon.get("aimPoint", [0.0, 0.0, 0.0]))
    return message


def unit_status(unit: dict) -> UnitStatus:
    return UnitStatus(
        id=unit["id"],
        kind=unit["kind"],
        name=unit["name"],
        position=vector(unit["position"]),
        velocity=vector(unit["velocity"]),
        hp=float(unit["hp"]),
        max_hp=float(unit["maxHp"]),
        alive=bool(unit["alive"]),
        armed=bool(unit["armed"]),
    )


def combat_event(event: dict) -> CombatEvent:
    message = CombatEvent()
    message.kind = event["type"]
    message.sim_time = float(event["simTime"])
    if event["type"] == CombatEvent.KIND_SHOT:
        message.shooter = event["shooter"]
        message.origin = vector(event["from"])
        message.end = vector(event["to"])
        hit = event.get("hit")
        message.has_hit = hit is not None
        if hit is not None:
            message.hit_unit = hit["unit"]
            message.hit_damage = float(hit["damage"])
            message.hit_blocked = bool(hit["blocked"])
    else:
        message.unit = event["unit"]
    return message


def odometry(state: dict) -> tuple[Odometry, TransformStamped]:
    """표준 도구(rviz2·Foxglove·rosbag2)가 읽는 기체의 위치·자세·속도와 odom → base_link 좌표 변환"""
    mecha = state["mecha"]
    time = stamp(state["simTime"])
    x, y, z = (float(value) for value in mecha["position"])
    qw, qx, qy, qz = torso_orientation(state["bodies"], float(mecha["heading"]))

    odom = Odometry()
    odom.header.stamp = time
    odom.header.frame_id = ODOM_FRAME
    odom.child_frame_id = BASE_FRAME
    odom.pose.pose.position.x, odom.pose.pose.position.y, odom.pose.pose.position.z = x, y, z
    orientation = odom.pose.pose.orientation
    orientation.w, orientation.x, orientation.y, orientation.z = qw, qx, qy, qz
    odom.twist.twist = twist(mecha["velocity"])

    transform = TransformStamped()
    transform.header.stamp = time
    transform.header.frame_id = ODOM_FRAME
    transform.child_frame_id = BASE_FRAME
    transform.transform.translation.x, transform.transform.translation.y, transform.transform.translation.z = x, y, z
    rotation = transform.transform.rotation
    rotation.w, rotation.x, rotation.y, rotation.z = qw, qx, qy, qz
    return odom, transform


def torso_orientation(bodies: list[float], heading: float) -> tuple[float, float, float, float]:
    """기체 몸통의 자세 (qw, qx, qy, qz). 몸체 자세가 없으면 기수 방향만으로 만든다."""
    if len(bodies) >= POSE_SIZE:
        qw, qx, qy, qz = (float(value) for value in bodies[3:POSE_SIZE])
        return qw, qx, qy, qz
    return math.cos(heading / 2), 0.0, 0.0, math.sin(heading / 2)


def velocity_command(velocity: Twist) -> dict:
    """Twist → 몸의 비행 속도 명령. 앞뒤·옆·위아래와 z축 돌기만 쓴다 (기체는 비행 제어가 똑바로 세운다)."""
    return {
        "type": "velocity",
        "forward": velocity.linear.x,
        "sideways": velocity.linear.y,
        "up": velocity.linear.z,
        "turn": velocity.angular.z,
    }


def guard_command(raised: bool, unit: str) -> dict:
    command: dict = {"type": "guard", "raised": raised}
    if unit:
        command["unit"] = unit
    return command


def reset_command(scenario: str) -> dict:
    return {"type": "reset", "scenario": scenario} if scenario else {"type": "reset"}


def push_command(force: list[float], duration_ms: int) -> dict:
    return {"type": "push", "force": [float(value) for value in force], "durationMs": int(duration_ms)}


def vector(values: list[float]) -> list[float]:
    return [float(value) for value in values]
