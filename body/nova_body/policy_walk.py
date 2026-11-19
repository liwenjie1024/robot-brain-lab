"""在测试台上考一个按指令走的策略：照一张命令表走一遍，量跟得上没有、摔了没有。

策略在 `PolicyBench` 上跑：经过脊髓层（反射、硬限制、换算）和驱动器那一层，状态估计跟着跑。
走两遍：策略看仿真里的真数一遍，看身体自己感觉到的（IMU、状态估计）一遍。
用法：docker compose run --rm body python -m nova_body.policy_walk /results/policies/<名字>/contract.json
结果写在规约旁边的 walk.json。
"""

import argparse
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from nova_body.policy import Policy, load_policy
from nova_body.policy_bench import STILL, PolicyBench

WALK_RESULT_NAME = "walk.json"
# 每一段的前面这么久不算：从上一段的速度换过来要时间。
SETTLE_S = 1.0
# 每隔这么多步看一次状态估计和真的差多少（每步都看太慢）。
ESTIMATE_CHECK_EVERY = 20


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
    # 这一段走了多久（摔了就是摔的那一刻）。
    seconds: float
    fell: bool
    # 这一段里，脊髓层把哪个关节的命令改小过的步数占多少（0 是一次都没有）。
    limited_share: float
    # 这一段里，反射动过的步数占多少（正常走路时应该是 0：没热、没被碰、没倒、没停）。
    reflex_share: float
    # 状态估计和真的差多少（这一段的平均）：IMU 那一点的速度（m/s）、身体的歪斜（度）。
    velocity_error_m_s: float
    tilt_error_deg: float


def walk(policy: Policy, schedule: tuple[Segment, ...] = SCHEDULE, *, sensed: bool = False) -> list[SegmentResult]:
    """照命令表走一遍。摔倒了就停，后面的段不走。

    sensed：策略看身体自己感觉到的速度、角速度、重力方向（IMU 和状态估计），不看仿真里的真数。
    """
    return walk_on(PolicyBench(policy, sensed=sensed), schedule)


def walk_on(bench: PolicyBench, schedule: tuple[Segment, ...]) -> list[SegmentResult]:
    """在已经在跑的测试台上接着照命令表走（考 1 公里时一圈一圈地走）。摔倒了就停。"""
    results = []
    for segment in schedule:
        samples, fell, limited_steps, reflex_steps, estimate_errors = [], False, 0, 0, []
        distance_before = bench.distance_m
        steps = round(segment.duration_s / bench.timestep)
        settle_steps = round(SETTLE_S / bench.timestep)
        for step in range(steps):
            tick = bench.step(segment.command)
            limited_steps += tick.limited
            reflex_steps += tick.reflexes
            if bench.fallen():
                fell = True
                break
            if step >= settle_steps:
                samples.append(bench.heading_velocity())
            if step % ESTIMATE_CHECK_EVERY == 0 and (errors := bench.estimate_errors()) is not None:
                estimate_errors.append(errors)
        results.append(
            _segment_result(
                segment,
                samples,
                distance_m=bench.distance_m - distance_before,
                seconds=(step + 1) * bench.timestep,
                fell=fell,
                limited_share=limited_steps / max(1, step + 1),
                reflex_share=reflex_steps / max(1, step + 1),
                estimate_errors=estimate_errors,
            )
        )
        if fell:
            break
    return results


def _segment_result(
    segment: Segment,
    samples: list[np.ndarray],
    *,
    distance_m: float,
    seconds: float,
    fell: bool,
    limited_share: float,
    reflex_share: float,
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
        seconds=seconds,
        fell=fell,
        limited_share=limited_share,
        reflex_share=reflex_share,
        velocity_error_m_s=float(np.mean([speed for speed, _ in estimate_errors])) if estimate_errors else math.nan,
        tilt_error_deg=float(np.mean([tilt for _, tilt in estimate_errors])) if estimate_errors else math.nan,
    )


def describe(results: list[SegmentResult]) -> str:
    """一张表：每一段的命令、量到的速度、平均差多少、走了多远、摔了没有。没量到的（一开始就摔了）写 —。"""
    lines = [
        "| 段 | 命令（前、左、转） | 量到的 | 平均差 | 走了 | 摔了没有 | 脊髓层改小过 | 估的速度差 | 估的歪斜差 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        command = numbers(result.command.values(), "+.2f")
        measured = numbers(result.measured.values(), "+.2f")
        error = numbers(result.error.values(), ".2f")
        fell = "摔了" if result.fell else "没有"
        limited = f"{result.limited_share:.0%} 的步"
        estimate = f"{numbers([result.velocity_error_m_s], '.3f')} m/s | {numbers([result.tilt_error_deg], '.2f')}°"
        cells = [result.label, command, measured, error, f"{result.distance_m:.1f} m", fell, limited, estimate]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def numbers(values, spec: str) -> str:
    """几个数用顿号连起来；不是数的（没量到）写 —。"""
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
