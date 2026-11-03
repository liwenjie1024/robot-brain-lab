"""시험 기체 BL-01: 날고 무장한 사람형 기체 (이 프로젝트의 독자 설계).

크기는 애니메이션의 대형 기체 정도(키 약 16m, 약 37t)로 잡았다. 다리는 굳어 있고(비행 중심), 팔은 어깨 관절 두 개
(돌리기, 들기)로 소총과 방패를 겨눈다. 등의 추진기 묶음이 위·앞뒤·옆으로 미는 힘과 세 축으로 돌리는 힘을 낸다.
모양은 기본 도형(상자·캡슐·원기둥)으로 만들어 외부 파일이 필요 없다.

좌표: x 앞, y 왼쪽, z 위. 길이 m, 질량 kg. 위치는 몸통 중심 기준.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import mujoco

# 사격 광선과 충돌을 나누는 묶음. 광선은 geom 묶음으로, 충돌은 비트로 고른다.
WORLD_GROUP = 0
MECHA_GROUP = 1
DRONE_GROUP = 2
WORLD_BIT = 1
MECHA_BIT = 2
DRONE_BIT = 4

MECHA_NAME = "BL-01"
MECHA_HEIGHT_M = 16.0
# 착지했을 때 몸통 중심의 높이 (발바닥 아래 끝이 몸통 중심에서 10.5m 아래)
STAND_HEIGHT_M = 10.5
ROOT_BODY = "mecha_torso"
THRUST_SITE = "mecha_thrust"
MUZZLE_SITE = "mecha_muzzle"
SHIELD_GEOM = "mecha_shield"
SHOULDER_HEIGHT_M = 1.2
SHOULDER_SIDE_M = 2.9
UPPER_ARM_M = 3.6
FOREARM_M = 3.2
RIFLE_OFFSET_M = 0.7
# 방패 판의 반 폭. 몸통 쪽으로 오는 사격을 어깨 옆(2.9m)에서 든 방패로 막으려면 그보다 넓어야 한다.
SHIELD_HALF_M = 3.0
# 소총을 든 팔을 앞으로 뻗어 버티는 데 약 12만 Nm가 든다. 넉넉히 두 배 반.
ARM_TORQUE_MAX_NM = 300_000.0

ARMOR = [0.42, 0.45, 0.5, 1.0]
ACCENT = [0.95, 0.6, 0.15, 1.0]
DARK = [0.15, 0.16, 0.18, 1.0]
VISOR = [0.2, 0.9, 1.0, 1.0]

BOX = mujoco.mjtGeom.mjGEOM_BOX
CAPSULE = mujoco.mjtGeom.mjGEOM_CAPSULE
CYLINDER = mujoco.mjtGeom.mjGEOM_CYLINDER
SPHERE = mujoco.mjtGeom.mjGEOM_SPHERE
HINGE = mujoco.mjtJoint.mjJNT_HINGE
LIMITED = mujoco.mjtLimited.mjLIMITED_TRUE
SITE_TRANSMISSION = mujoco.mjtTrn.mjTRN_SITE
JOINT_TRANSMISSION = mujoco.mjtTrn.mjTRN_JOINT
# 소총의 사격 방향(사이트의 z축)을 팔의 아래쪽(-z, 팔이 뻗는 쪽)으로 돌린다: x축으로 180도
BARREL_ALONG_ARM = [0.0, 1.0, 0.0, 0.0]


@dataclass(frozen=True)
class ArmJoints:
    """한쪽 팔의 관절 이름 (돌리기: 몸통 z축, 들기: 앞으로 드는 쪽이 +)"""

    side: str
    yaw: str
    pitch: str
    yaw_range_deg: tuple[float, float]
    pitch_range_deg: tuple[float, float] = (0.0, 170.0)


RIGHT_ARM = ArmJoints("right", "mecha_right_shoulder_yaw", "mecha_right_shoulder_pitch", (-100.0, 45.0))
LEFT_ARM = ArmJoints("left", "mecha_left_shoulder_yaw", "mecha_left_shoulder_pitch", (-45.0, 100.0))

THRUSTERS = ("thrust_up", "thrust_forward", "thrust_side", "torque_roll", "torque_pitch", "torque_yaw")
THRUSTER_GEARS = {
    "thrust_up": [0, 0, 1, 0, 0, 0],
    "thrust_forward": [1, 0, 0, 0, 0, 0],
    "thrust_side": [0, 1, 0, 0, 0, 0],
    "torque_roll": [0, 0, 0, 1, 0, 0],
    "torque_pitch": [0, 0, 0, 0, 1, 0],
    "torque_yaw": [0, 0, 0, 0, 0, 1],
}


def _mecha_geom(body, name: str | None = None, **kwargs) -> None:
    geom = body.add_geom(group=MECHA_GROUP, contype=MECHA_BIT, conaffinity=WORLD_BIT | DRONE_BIT, **kwargs)
    if name:
        geom.name = name


def add_mecha(spec: mujoco.MjSpec, position: tuple[float, float, float]) -> None:
    """기체를 더한다. 추진기 액추에이터의 힘 한도는 질량을 안 뒤에 정한다 (set_thruster_ranges)."""
    torso = spec.worldbody.add_body(name=ROOT_BODY, pos=list(position))
    torso.add_freejoint(name="mecha_root")
    # 무게 중심을 재기 전에는 몸통 중심에 둔다 (move_thrust_site로 옮긴다).
    torso.add_site(name=THRUST_SITE, pos=[0, 0, 0])
    _mecha_geom(torso, type=BOX, size=[1.5, 2.1, 1.9], pos=[0, 0, 0.3], mass=12000.0, rgba=ARMOR)
    _mecha_geom(torso, type=BOX, size=[0.5, 1.2, 0.5], pos=[1.45, 0, 0.6], mass=300.0, rgba=ACCENT)
    _mecha_geom(torso, type=BOX, size=[1.1, 1.6, 0.9], pos=[0, 0, -2.4], mass=4000.0, rgba=DARK)
    _mecha_geom(torso, type=BOX, size=[0.8, 0.7, 0.8], pos=[0.1, 0, 3.0], mass=800.0, rgba=ARMOR)
    _mecha_geom(torso, type=BOX, size=[0.15, 0.55, 0.18], pos=[0.85, 0, 3.1], mass=50.0, rgba=VISOR)
    _mecha_geom(torso, type=BOX, size=[0.9, 1.5, 1.6], pos=[-2.3, 0, 0.5], mass=3500.0, rgba=DARK)
    for side in (1, -1):
        _mecha_geom(torso, type=CYLINDER, size=[0.45, 0.5, 0], pos=[-2.6, 0.8 * side, -1.4], mass=200.0, rgba=DARK)
        _mecha_geom(torso, type=BOX, size=[0.9, 0.6, 0.7], pos=[0, 2.75 * side, 1.9], mass=600.0, rgba=ACCENT)
        y = 1.0 * side
        _mecha_geom(torso, type=CAPSULE, fromto=[0, y, -3.3, 0, y, -6.8], size=[0.75, 0, 0], mass=2000.0, rgba=ARMOR)
        _mecha_geom(torso, type=CAPSULE, fromto=[0, y, -7.0, 0, y, -9.6], size=[0.85, 0, 0], mass=1500.0, rgba=ARMOR)
        _mecha_geom(torso, type=BOX, size=[1.5, 0.75, 0.4], pos=[0.3, y, -10.1], mass=600.0, rgba=DARK)
    _add_arm(torso, RIGHT_ARM, side=-1)
    _add_arm(torso, LEFT_ARM, side=1)

    for name in THRUSTERS:
        spec.add_actuator(name=name, trntype=SITE_TRANSMISSION, target=THRUST_SITE, gear=THRUSTER_GEARS[name])
    for arm in (RIGHT_ARM, LEFT_ARM):
        for joint in (arm.yaw, arm.pitch):
            spec.add_actuator(
                name=f"{joint}_motor",
                trntype=JOINT_TRANSMISSION,
                target=joint,
                ctrlrange=[-ARM_TORQUE_MAX_NM, ARM_TORQUE_MAX_NM],
                ctrllimited=LIMITED,
            )


def _add_arm(torso, joints: ArmJoints, side: int) -> None:
    shoulder = torso.add_body(name=f"mecha_{joints.side}_shoulder", pos=[0, SHOULDER_SIDE_M * side, SHOULDER_HEIGHT_M])
    low, high = (math.radians(value) for value in joints.yaw_range_deg)
    shoulder.add_joint(name=joints.yaw, type=HINGE, axis=[0, 0, 1], range=[low, high], limited=LIMITED)
    _mecha_geom(shoulder, type=SPHERE, size=[0.7, 0, 0], mass=300.0, rgba=DARK)
    arm = shoulder.add_body(name=f"mecha_{joints.side}_arm")
    low, high = (math.radians(value) for value in joints.pitch_range_deg)
    # 들기 축을 -y로 두어, 각이 커질수록 아래로 늘어진 팔이 앞으로 들린다.
    arm.add_joint(name=joints.pitch, type=HINGE, axis=[0, -1, 0], range=[low, high], limited=LIMITED)
    forearm_end = -(UPPER_ARM_M + FOREARM_M)
    _mecha_geom(arm, type=CAPSULE, fromto=[0, 0, 0, 0, 0, -UPPER_ARM_M], size=[0.6, 0, 0], mass=1500.0, rgba=ARMOR)
    _mecha_geom(
        arm, type=CAPSULE, fromto=[0, 0, -UPPER_ARM_M, 0, 0, forearm_end], size=[0.65, 0, 0], mass=1200.0, rgba=ARMOR
    )
    _mecha_geom(arm, type=SPHERE, size=[0.5, 0, 0], pos=[0, 0, forearm_end - 0.3], mass=200.0, rgba=DARK)
    if joints.side == "right":
        rifle_y = RIFLE_OFFSET_M * side
        _mecha_geom(arm, type=BOX, size=[0.35, 0.3, 2.6], pos=[0, rifle_y, forearm_end + 0.6], mass=800.0, rgba=DARK)
        arm.add_site(name=MUZZLE_SITE, pos=[0, rifle_y, forearm_end - 2.1], quat=BARREL_ALONG_ARM)
    else:
        # 팔꿈치가 없어 팔을 들면 팔에 붙인 판이 눕는다. 그래서 주먹 앞에 팔과 직각으로 든다:
        # 방패를 막을 쪽으로 팔을 뻗으면 판이 그쪽을 바로 본다.
        _mecha_geom(
            arm,
            SHIELD_GEOM,
            type=BOX,
            size=[SHIELD_HALF_M, SHIELD_HALF_M, 0.3],
            pos=[0, 0, forearm_end - 1.0],
            mass=1000.0,
            rgba=ACCENT,
        )


def move_thrust_site(spec: mujoco.MjSpec, local_position: list[float]) -> None:
    """추진기 힘이 걸리는 점을 옮긴다. 기체 전체의 무게 중심에 두어야 미는 힘이 기체를 돌리지 않는다."""
    spec.site(THRUST_SITE).pos = local_position


def set_thruster_ranges(spec: mujoco.MjSpec, ranges: dict[str, tuple[float, float]]) -> None:
    for name, (low, high) in ranges.items():
        actuator = spec.actuator(name)
        actuator.ctrlrange = [low, high]
        actuator.ctrllimited = LIMITED
