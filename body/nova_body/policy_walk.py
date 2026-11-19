"""在测试台上考一个按指令走的策略：照一张命令表走一遍，量跟得上没有、摔了没有。

身体用练的时候的那个模型（规约里写的、核对过 SHA-256），换成测试台的步长、积分的方法和地面。
策略给的关节命令经过脊髓层（换成驱动器的命令、守住硬限制）和驱动器那一层（命令晚 1 毫秒到）（2.1 步）。
状态估计一直跟着跑，量它估得准不准；走两遍：策略看仿真里的真数一遍，看身体自己感觉到的（IMU、状态估计）一遍。
用法：docker compose run --rm body python -m nova_body.policy_walk /results/policies/<名字>/contract.json
结果写在规约旁边的 walk.json。
"""

import argparse
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import mujoco
import numpy as np

from nova_body import actuation
from nova_body.actuation import DriveLayer
from nova_body.bench import FLOOR, add_floor, use_bench_settings
from nova_body.estimation import POLICY_BODY_SETUPS, BodyFeel
from nova_body.policy import Policy, load_policy
from nova_body.policy_runner import PolicyRunner, root_body
from nova_body.spine import impedance_command, spine_for, step_spine

WALK_RESULT_NAME = "walk.json"
# 开始时脚底离地面这么高，落下去再开始（和练的时候一样，从一点点高的地方放下）。
START_CLEARANCE_M = 0.01
# 每一段的前面这么久不算：从上一段的速度换过来要时间。
SETTLE_S = 1.0
# 每隔这么多步看一次状态估计和真的差多少（每步都看太慢）。
ESTIMATE_CHECK_EVERY = 20
# 骨盆歪过这么多度，或者低到开始时的这么多倍，就算摔倒了。
FALLEN_TILT_DEG = 60.0
FALLEN_HEIGHT_SHARE = 0.5
STILL = {"lin_vel_x": 0.0, "lin_vel_y": 0.0, "ang_vel_z": 0.0}


@dataclass(frozen=True)
class Segment:
    """命令表里的一段：叫什么、多久、命令是什么。"""

    label: str
    duration_s: float
    command: Mapping[str, float]


SCHEDULE = (
    Segment("站着", 3.0, STILL),
    Segment("往前慢走", 6.0, {**STILL, "lin_vel_x": 0.5}),
    Segment("往前走", 6.0, {**STILL, "lin_vel_x": 1.0}),
    Segment("边走边往左转", 6.0, {**STILL, "lin_vel_x": 0.5, "ang_vel_z": 0.5}),
    Segment("往左横着走", 5.0, {**STILL, "lin_vel_y": 0.5}),
    Segment("往后退", 5.0, {**STILL, "lin_vel_x": -0.5}),
    Segment("停下来站着", 4.0, STILL),
)


@dataclass(frozen=True)
class SegmentResult:
    label: str
    command: Mapping[str, float]
    measured: Mapping[str, float]
    error: Mapping[str, float]
    distance_m: float
    fell: bool
    # 这一段里，脊髓层把哪个关节的命令改小过的步数占多少（0 是一次都没有）。
    limited_share: float
    # 状态估计和真的差多少（这一段的平均）：IMU 那一点的速度（m/s）、身体的歪斜（度）。
    velocity_error_m_s: float
    tilt_error_deg: float


def load_policy_body(policy: Policy) -> mujoco.MjModel:
    """练的时候用的身体模型，放到测试台上：测试台的步长、积分的方法、地面。"""
    spec = mujoco.MjSpec.from_file(str(policy.body_model_path))
    use_bench_settings(spec)
    if not any(geom.name == FLOOR for geom in spec.geoms):
        add_floor(spec)
    return spec.compile()


def start_data(model: mujoco.MjModel, policy: Policy) -> mujoco.MjData:
    """默认的姿势，脚底比地面高一点。"""
    data = mujoco.MjData(model)
    for joint in policy.joints:
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint.name)
        data.qpos[model.jnt_qposadr[joint_id]] = joint.default_position_rad
    mujoco.mj_forward(model, data)
    root_address = model.jnt_qposadr[_free_joint(model)]
    data.qpos[root_address + 2] += START_CLEARANCE_M - lowest_point_m(model, data)
    mujoco.mj_forward(model, data)
    return data


def lowest_point_m(model: mujoco.MjModel, data: mujoco.MjData) -> float:
    """身体能碰到地面的形状里最低的一点（按每个形状的包围盒算）。"""
    floor = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, FLOOR)
    lowest = math.inf
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=float)
    for geom in range(model.ngeom):
        if geom == floor or model.geom_bodyid[geom] == 0 or model.geom_contype[geom] == 0:
            continue
        center, half = model.geom_aabb[geom, :3], model.geom_aabb[geom, 3:]
        rotation = data.geom_xmat[geom].reshape(3, 3)
        points = data.geom_xpos[geom] + (center + corners * half) @ rotation.T
        lowest = min(lowest, float(points[:, 2].min()))
    return lowest


def walk(policy: Policy, schedule: tuple[Segment, ...] = SCHEDULE, *, sensed: bool = False) -> list[SegmentResult]:
    """照命令表走一遍。摔倒了就停，后面的段不走。

    sensed：策略看身体自己感觉到的速度、角速度、重力方向（IMU 和状态估计），不看仿真里的真数。
    """
    model = load_policy_body(policy)
    spine = spine_for(model)
    drives = DriveLayer(model, [None] * model.nu)
    runner = PolicyRunner(model, policy, spine)
    data = start_data(model, policy)
    feel = _body_feel(model, policy, spine, data, sensed=sensed)
    root = root_body(model)
    start_height = float(data.xpos[root][2])
    timestep = float(model.opt.timestep)
    ground_position = slice(model.jnt_qposadr[_free_joint(model)], model.jnt_qposadr[_free_joint(model)] + 2)
    results = []
    for segment in schedule:
        samples, distance, fell, limited_steps, estimate_errors = [], 0.0, False, 0, []
        steps = round(segment.duration_s / timestep)
        settle_steps = round(SETTLE_S / timestep)
        for step in range(steps):
            before = data.qpos[ground_position].copy()
            sense = feel.step(data, timestep) if feel else None
            spinal = step_spine(spine, data, runner.step(data, segment.command, sense if sensed else None))
            limited_steps += bool(spinal.limited.any())
            drives.command_impedance(impedance_command(spinal))
            actuation.step(model, data, drives)
            if feel:
                feel.sample(data)
            distance += float(np.linalg.norm(data.qpos[ground_position] - before))
            if has_fallen(data, root, start_height):
                fell = True
                break
            if step >= settle_steps:
                samples.append(heading_velocity(model, data))
            if feel and step % ESTIMATE_CHECK_EVERY == 0:
                estimate_errors.append(feel.errors(data))
        results.append(
            _segment_result(
                segment,
                samples,
                distance_m=distance,
                fell=fell,
                limited_share=limited_steps / max(1, step + 1),
                estimate_errors=estimate_errors,
            )
        )
        if fell:
            break
    return results


def _body_feel(model: mujoco.MjModel, policy: Policy, spine, data: mujoco.MjData, *, sensed: bool) -> BodyFeel | None:
    """测试台认识这个身体（知道 IMU、脚在哪）就跟着做状态估计；不认识的不做，要策略看感觉到的就拒绝。"""
    setup = POLICY_BODY_SETUPS.get(policy.body_name)
    if setup is None:
        if sensed:
            raise ValueError(f"测试台不知道身体 {policy.body_name} 的 IMU 和脚在哪，做不了状态估计")
        return None
    return BodyFeel(model, setup, spine, data)


def heading_velocity(model: mujoco.MjModel, data: mujoco.MjData) -> np.ndarray:
    """骨盆的速度，按它朝的方向（只转了偏航）：往前、往左、往左转。"""
    address = model.jnt_dofadr[_free_joint(model)]
    linear_world = data.qvel[address : address + 3]
    angular_local = data.qvel[address + 3 : address + 6]
    rotation = data.xmat[root_body(model)].reshape(3, 3)
    yaw = math.atan2(rotation[1, 0], rotation[0, 0])
    cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
    forward = cos_yaw * linear_world[0] + sin_yaw * linear_world[1]
    left = -sin_yaw * linear_world[0] + cos_yaw * linear_world[1]
    turn = float((rotation @ angular_local)[2])
    return np.array([forward, left, turn])


def has_fallen(data: mujoco.MjData, root: int, start_height_m: float) -> bool:
    up = data.xmat[root].reshape(3, 3)[:, 2]
    tilt_deg = math.degrees(math.acos(max(-1.0, min(1.0, float(up[2])))))
    return tilt_deg > FALLEN_TILT_DEG or float(data.xpos[root][2]) < FALLEN_HEIGHT_SHARE * start_height_m


def _segment_result(
    segment: Segment,
    samples: list[np.ndarray],
    *,
    distance_m: float,
    fell: bool,
    limited_share: float,
    estimate_errors: list[tuple[float, float]],
) -> SegmentResult:
    fields = ("lin_vel_x", "lin_vel_y", "ang_vel_z")
    mean = np.mean(samples, axis=0) if samples else np.full(len(fields), math.nan)
    errors = (
        np.mean([np.abs(sample - [segment.command[f] for f in fields]) for sample in samples], axis=0)
        if samples
        else mean
    )
    return SegmentResult(
        label=segment.label,
        command=dict(segment.command),
        measured={name: float(value) for name, value in zip(fields, mean, strict=True)},
        error={name: float(value) for name, value in zip(fields, errors, strict=True)},
        distance_m=distance_m,
        fell=fell,
        limited_share=limited_share,
        velocity_error_m_s=float(np.mean([speed for speed, _ in estimate_errors])) if estimate_errors else math.nan,
        tilt_error_deg=float(np.mean([tilt for _, tilt in estimate_errors])) if estimate_errors else math.nan,
    )


def _free_joint(model: mujoco.MjModel) -> int:
    return next(joint for joint in range(model.njnt) if model.jnt_type[joint] == mujoco.mjtJoint.mjJNT_FREE)


def describe(results: list[SegmentResult]) -> str:
    """一张表：每一段的命令、量到的速度、平均差多少、走了多远、摔了没有。没量到的（一开始就摔了）写 —。"""
    lines = [
        "| 段 | 命令（前、左、转） | 量到的 | 平均差 | 走了 | 摔了没有 | 脊髓层改小过 | 估的速度差 | 估的歪斜差 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        command = _numbers(result.command.values(), "+.2f")
        measured = _numbers(result.measured.values(), "+.2f")
        error = _numbers(result.error.values(), ".2f")
        fell = "摔了" if result.fell else "没有"
        limited = f"{result.limited_share:.0%} 的步"
        estimate = f"{_numbers([result.velocity_error_m_s], '.3f')} m/s | {_numbers([result.tilt_error_deg], '.2f')}°"
        cells = [result.label, command, measured, error, f"{result.distance_m:.1f} m", fell, limited, estimate]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _numbers(values, spec: str) -> str:
    return "、".join("—" if math.isnan(value) else format(value, spec) for value in values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path, help="策略的规约（contract.json）")
    arguments = parser.parse_args()
    policy = load_policy(arguments.contract)
    runs = {"truth": walk(policy), "sensed": walk(policy, sensed=True)}
    output = arguments.contract.parent / WALK_RESULT_NAME
    summary = {name: [asdict(result) for result in results] for name, results in runs.items()}
    output.write_text(json.dumps({"policy": policy.name, **summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, title in (("truth", "策略看仿真里的真数"), ("sensed", "策略看身体自己感觉到的（IMU、状态估计）")):
        print(title)
        print(describe(runs[name]))
    print(f"写进了 {output}")


if __name__ == "__main__":
    main()
