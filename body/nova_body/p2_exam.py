"""P2 的考试（P2 计划第 1 节的表）：站 1 小时、被推、走 1 公里、上下楼梯、摔倒了起来。

每道题都在 `PolicyBench` 上考：策略经过脊髓层（反射、硬限制、换算）和驱动器那一层，看的是身体自己感觉到的
（IMU、状态估计）。裁判看仿真里的真数。几道题互不相干，分在几个进程里一起考。
用法：docker compose run --rm body python -m nova_body.p2_exam /results/policies/<名字>/contract.json
结果写在规约旁边的 exam.json，表打印出来（抄进 P2 计划）。
"""

import argparse
import datetime
import json
import math
import multiprocessing
import os
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import nova_rt
import numpy as np

from nova_body.bench import Stairs
from nova_body.policy import Policy, load_policy
from nova_body.policy_bench import STILL, PolicyBench, StartPose
from nova_body.policy_walk import Segment, SegmentResult, numbers, walk_on

EXAM_RESULT_NAME = "exam.json"
NO_PUSH = (0.0, 0.0, 0.0)
VELOCITY_FIELDS = ("lin_vel_x", "lin_vel_y", "ang_vel_z")
# 仿真的时刻比较时留的一点余量（同一刻因为实数的误差差一点点）。
TIME_EPSILON_S = 1e-9

# 站：站 1 小时。落下来站稳以后才开始量歪斜、挪了多远、功率。
STAND_S = 3600.0
SETTLE_S = 2.0

# 被推：站稳以后在胸上推 0.5 秒（和 P1 一样），力是体重的 4%、8%……60%，推到倒了为止；推完再看 4 秒。
# 每一档推几次：推的时刻在策略的一个周期里错开（推到时策略算到哪一步不一样，G1 最多差 9°，倒不倒都会变），
# 几次都没倒才算扛得住。
PUSH_ATTEMPTS = 4
PUSH_START_S = 2.0
PUSH_DURATION_S = 0.5
PUSH_WATCH_S = 4.0
PUSH_SHARE_STEP = 0.04
PUSH_SHARES: tuple[float, ...] = tuple(round(PUSH_SHARE_STEP * level, 2) for level in range(1, 16))
PUSH_DIRECTIONS: dict[str, tuple[float, float, float]] = {
    "往前": (1.0, 0.0, 0.0),
    "往后": (-1.0, 0.0, 0.0),
    "往左": (0.0, 1.0, 0.0),
    "往右": (0.0, -1.0, 0.0),
}

# 走：照这一圈的命令一圈一圈地走，走够 1 公里。往前 0~1.1 m/s，能横着走、转弯（P2 计划第 1 节）。
WALK_DISTANCE_M = 1000.0
# 照命令该走的路的这么多倍的时间还没走够，就不走了（站着不动的策略不会一直考下去）。
WALK_TIME_ALLOWANCE = 2.0
WALK_LAP = (
    Segment("往前慢走", 10.0, {**STILL, "lin_vel_x": 0.5}),
    Segment("往前走", 10.0, {**STILL, "lin_vel_x": 1.0}),
    Segment("快走", 10.0, {**STILL, "lin_vel_x": 1.1}),
    Segment("边走边往左转", 8.0, {**STILL, "lin_vel_x": 0.8, "ang_vel_z": 0.5}),
    Segment("边走边往右转", 8.0, {**STILL, "lin_vel_x": 0.8, "ang_vel_z": -0.5}),
    Segment("往左横着走", 5.0, {**STILL, "lin_vel_y": 0.3}),
    Segment("往右横着走", 5.0, {**STILL, "lin_vel_y": -0.3}),
    Segment("往后退", 5.0, {**STILL, "lin_vel_x": -0.5}),
)

# 上下楼梯：套内楼梯里最难的（一级 0.20 m、踏面 0.22 m），上 15 级、1 m 的平台、下 15 级。慢慢往前走。
STAIRS = Stairs(start_x=1.0, rise_m=0.20, tread_m=0.22, steps=15, landing_m=1.0, width_m=1.2)
STAIRS_COMMAND = {**STILL, "lin_vel_x": 0.3}
STAIRS_TIME_S = 90.0
# 下完了再往前这么远（站得好好的），算走完了。
STAIRS_FINISH_M = 0.5
# 中间被碰一下：骨盆走到上去的那一段的一半时，往右推胸，体重的 10%，0.3 秒。
STAIRS_BUMP_SHARE = 0.10
STAIRS_BUMP_S = 0.3
STAIRS_BUMP_DIRECTION = (0.0, -1.0, 0.0)
SLIPPERY_LEVEL = 8

# 起来：从躺着开始，10 秒内站起来，再站住 2 秒。
GET_UP_S = 10.0
STAY_UP_S = 2.0
LYING_POSES = (StartPose.PRONE, StartPose.SUPINE, StartPose.SIDE)

# 一起考的进程最多这么多个，再给别的程序留几个核（BL-01 的服务可能在跑）。
SPARE_CPUS = 4


@dataclass(frozen=True)
class StandResult:
    """站：seconds 是站了多久（倒了就是倒的那一刻）。站稳以后：最多歪了多少，骨盆在地上挪了多远（命令是站着不动），
    平均的机械功率（正功）。hottest_winding_c：最热的绕组（没有驱动器的发热模型是 nan）。"""

    seconds: float
    fell: bool
    max_tilt_deg: float
    drift_m: float
    mean_power_w: float
    limited_share: float
    reflex_share: float
    hottest_winding_c: float


@dataclass(frozen=True)
class PushAttempt:
    """推一下：力多大（牛顿），倒了没有，最多歪了多少，跌倒的反射动了没有。"""

    force_n: float
    fell: bool
    max_tilt_deg: float
    fall_reflex: bool


@dataclass(frozen=True)
class PushTrial:
    """推一档：力是体重的 share 倍（force_n 牛顿），推了几次、倒了几次；没倒的那几次最多歪了多少（都倒了是 nan），
    跌倒的反射动过没有。"""

    share: float
    force_n: float
    attempts: int
    falls: int
    max_tilt_deg: float
    fall_reflex: bool

    @property
    def held(self) -> bool:
        return self.falls == 0


@dataclass(frozen=True)
class PushResult:
    """往一个方向一档一档地推，推到倒了为止。strongest_share：扛得住的最大一档（第一档就倒了是 0）。"""

    direction: str
    trials: list[PushTrial]
    strongest_share: float
    strongest_n: float


@dataclass(frozen=True)
class WalkResult:
    """走：一共走了多远、多久、几圈，摔了没有，走够了没有。errors：一圈里每一段（每种命令）平均差多少，
    mean_error：全部的平均。work_per_m_j：每走 1 米做的正功；cost_of_transport：正功 ÷（体重 × 走的路）。"""

    distance_m: float
    seconds: float
    laps: int
    fell: bool
    reached: bool
    errors: Mapping[str, Mapping[str, float]]
    mean_error: Mapping[str, float]
    work_per_m_j: float
    cost_of_transport: float
    limited_share: float
    reflex_share: float


@dataclass(frozen=True)
class StairsTrial:
    name: str
    stairs: Stairs
    bump: bool = False


STAIRS_TRIALS = (
    StairsTrial("平常的", STAIRS),
    StairsTrial("中间被碰一下", STAIRS, bump=True),
    StairsTrial(f"第 {SLIPPERY_LEVEL} 级是滑的", replace(STAIRS, slippery_levels=frozenset({SLIPPERY_LEVEL}))),
)


@dataclass(frozen=True)
class StairsResult:
    """上下楼梯：上了几级、下了几级（按站得好好的走到的最远的地方算），走完了没有，摔了没有，用了多久，碰了没有。"""

    trial: str
    up_steps: int
    down_steps: int
    finished: bool
    fell: bool
    seconds: float
    bumped: bool


@dataclass(frozen=True)
class GetUpResult:
    """起来：站起来了没有、第几秒站起来的（没站起来是 nan），骨盆最高到了站着时的几成。"""

    pose: str
    stood_up: bool
    seconds: float
    best_height_share: float


@dataclass(frozen=True)
class ExamResult:
    policy: str
    date: str
    stand: StandResult | None = None
    pushes: list[PushResult] = field(default_factory=list)
    walk: WalkResult | None = None
    stairs: list[StairsResult] = field(default_factory=list)
    get_up: list[GetUpResult] = field(default_factory=list)


def exam_stand(policy: Policy, *, seconds: float = STAND_S, sensed: bool = True) -> StandResult:
    """站 seconds 秒（命令是站着不动）。"""
    bench = PolicyBench(policy, sensed=sensed)
    settle_steps = round(SETTLE_S / bench.timestep)
    max_tilt, limited, reflexes, fell = math.nan, 0, 0, False
    settled_xy, settled_work = None, 0.0
    steps = 0
    for step in range(round(seconds / bench.timestep)):
        tick = bench.step(STILL)
        steps = step + 1
        limited += tick.limited
        reflexes += tick.reflexes
        if bench.fallen():
            fell = True
            break
        if step == settle_steps:
            settled_xy, settled_work = bench.pelvis_xy(), bench.work_j
        if step >= settle_steps:
            max_tilt = bench.tilt_deg() if math.isnan(max_tilt) else max(max_tilt, bench.tilt_deg())
    measured_s = (steps - settle_steps) * bench.timestep
    winding = bench.drives.winding_c
    return StandResult(
        seconds=steps * bench.timestep,
        fell=fell,
        max_tilt_deg=max_tilt,
        drift_m=float(np.linalg.norm(bench.pelvis_xy() - settled_xy)) if settled_xy is not None else math.nan,
        mean_power_w=(bench.work_j - settled_work) / measured_s
        if settled_xy is not None and measured_s > 0
        else math.nan,
        limited_share=limited / max(1, steps),
        reflex_share=reflexes / max(1, steps),
        hottest_winding_c=float(winding.max()) if winding.size else math.nan,
    )


def exam_push(
    policy: Policy, direction: str, *, shares: Sequence[float] = PUSH_SHARES, sensed: bool = True
) -> PushResult:
    """往 direction 一档一档地推（力是体重的 share 倍），每档推 PUSH_ATTEMPTS 次，有一次倒了就不再往上推。"""
    if direction not in PUSH_DIRECTIONS:
        raise ValueError(f"没有这个推的方向：{direction}（有 {'、'.join(PUSH_DIRECTIONS)}）")
    if not shares or shares[0] <= 0 or list(shares) != sorted(set(shares)):
        raise ValueError("推力要从小到大排，每一档都大于 0，不能重复")
    trials = []
    for share in shares:
        attempts = [
            push_once(policy, PUSH_DIRECTIONS[direction], share, delay_s, sensed=sensed)
            for delay_s in push_delays_s(policy.rate_hz)
        ]
        trials.append(push_trial(share, attempts))
        if not trials[-1].held:
            break
    held = [trial for trial in trials if trial.held]
    return PushResult(
        direction=direction,
        trials=trials,
        strongest_share=held[-1].share if held else 0.0,
        strongest_n=held[-1].force_n if held else 0.0,
    )


def push_delays_s(rate_hz: float) -> list[float]:
    """每一次推比 PUSH_START_S 晚多少：在策略的一个周期里平均地错开。"""
    return [attempt / (PUSH_ATTEMPTS * rate_hz) for attempt in range(PUSH_ATTEMPTS)]


def push_trial(share: float, attempts: Sequence[PushAttempt]) -> PushTrial:
    """一档推的几次合起来。"""
    standing = [attempt.max_tilt_deg for attempt in attempts if not attempt.fell]
    return PushTrial(
        share=share,
        force_n=attempts[0].force_n,
        attempts=len(attempts),
        falls=sum(attempt.fell for attempt in attempts),
        max_tilt_deg=max(standing) if standing else math.nan,
        fall_reflex=any(attempt.fall_reflex for attempt in attempts),
    )


def push_once(
    policy: Policy, direction: tuple[float, float, float], share: float, delay_s: float, *, sensed: bool
) -> PushAttempt:
    """站稳以后推一下（比 PUSH_START_S 晚 delay_s），再看一会儿倒没倒。"""
    bench = PolicyBench(policy, sensed=sensed)
    force = share * bench.weight_n * np.array(direction)
    start_s = PUSH_START_S + delay_s
    max_tilt, fall_reflex, fell = 0.0, False, False
    for _ in range(round((start_s + PUSH_DURATION_S + PUSH_WATCH_S) / bench.timestep)):
        pushing = start_s - TIME_EPSILON_S <= bench.time_s < start_s + PUSH_DURATION_S - TIME_EPSILON_S
        tick = bench.step(STILL, tuple(force) if pushing else NO_PUSH)
        fall_reflex |= tick.mode == nova_rt.MODE_FALLING
        max_tilt = max(max_tilt, bench.tilt_deg())
        if bench.fallen():
            fell = True
            break
    return PushAttempt(float(np.linalg.norm(force)), fell, max_tilt, fall_reflex)


def exam_walk(
    policy: Policy,
    *,
    distance_m: float = WALK_DISTANCE_M,
    lap: tuple[Segment, ...] = WALK_LAP,
    sensed: bool = True,
) -> WalkResult:
    """照一圈的命令一圈一圈地走，走够 distance_m（或者摔了、时间到了）。至少走一圈。"""
    if distance_m <= 0 or lap_distance_m(lap) <= 0:
        raise ValueError("要走的路和一圈照命令走的路都要大于 0")
    bench = PolicyBench(policy, sensed=sensed)
    lap_s = sum(segment.duration_s for segment in lap)
    time_limit_s = WALK_TIME_ALLOWANCE * distance_m / lap_distance_m(lap) * lap_s
    walked: list[SegmentResult] = []
    laps = 0
    while laps == 0 or (bench.distance_m < distance_m and bench.time_s < time_limit_s):
        results = walk_on(bench, lap)
        walked.extend(results)
        laps += 1
        if results[-1].fell:
            break
    seconds = sum(result.seconds for result in walked)
    per_label = {segment.label: mean_errors([r for r in walked if r.label == segment.label]) for segment in lap}
    distance = bench.distance_m
    return WalkResult(
        distance_m=distance,
        seconds=seconds,
        laps=laps,
        fell=walked[-1].fell,
        reached=distance >= distance_m and not walked[-1].fell,
        errors=per_label,
        mean_error=mean_errors(walked),
        work_per_m_j=bench.work_j / distance if distance > 0 else math.nan,
        cost_of_transport=bench.work_j / (bench.weight_n * distance) if distance > 0 else math.nan,
        limited_share=sum(r.limited_share * r.seconds for r in walked) / seconds,
        reflex_share=sum(r.reflex_share * r.seconds for r in walked) / seconds,
    )


def lap_distance_m(lap: tuple[Segment, ...]) -> float:
    """照命令走一圈该走多远。"""
    return sum(
        segment.duration_s * math.hypot(segment.command["lin_vel_x"], segment.command["lin_vel_y"]) for segment in lap
    )


def mean_errors(results: Sequence[SegmentResult]) -> dict[str, float]:
    """几段的平均差多少（按每段走的时间算权重）；没量到的段不算。都没量到是 nan。"""
    measured = [r for r in results if not any(math.isnan(r.error[name]) for name in VELOCITY_FIELDS)]
    total = sum(r.seconds for r in measured)
    if total <= 0:
        return dict.fromkeys(VELOCITY_FIELDS, math.nan)
    return {name: sum(r.error[name] * r.seconds for r in measured) / total for name in VELOCITY_FIELDS}


def exam_stairs(
    policy: Policy, trial: StairsTrial, *, time_s: float = STAIRS_TIME_S, sensed: bool = True
) -> StairsResult:
    """从楼梯前面 1 m 开始，慢慢往前走，上去、下来。"""
    stairs = trial.stairs
    bench = PolicyBench(policy, sensed=sensed, stairs=stairs)
    bump_force = tuple(STAIRS_BUMP_SHARE * bench.weight_n * np.array(STAIRS_BUMP_DIRECTION))
    bump_x = (stairs.start_x + stairs.top_start_x) / 2
    bump_until = None
    furthest_x, fell, finished = -math.inf, False, False
    for _ in range(round(time_s / bench.timestep)):
        x = float(bench.pelvis_xy()[0])
        if trial.bump and bump_until is None and x >= bump_x:
            bump_until = bench.time_s + STAIRS_BUMP_S
        bumping = bump_until is not None and bench.time_s < bump_until - TIME_EPSILON_S
        bench.step(STAIRS_COMMAND, bump_force if bumping else NO_PUSH)
        if bench.fallen():
            fell = True
            break
        if bench.upright():
            furthest_x = max(furthest_x, float(bench.pelvis_xy()[0]))
        if furthest_x >= stairs.end_x + STAIRS_FINISH_M:
            finished = True
            break
    up, down = stairs_progress(stairs, furthest_x)
    return StairsResult(trial.name, up, down, finished, fell, bench.time_s, bump_until is not None)


def stairs_progress(stairs: Stairs, furthest_x: float) -> tuple[int, int]:
    """站得好好的走到了 furthest_x：上了几级、下了几级。"""
    if furthest_x < stairs.top_start_x:
        return stairs.step_at(furthest_x), 0
    if furthest_x < stairs.top_end_x:
        return stairs.steps, 0
    return stairs.steps, stairs.steps - stairs.step_at(furthest_x)


class UprightWatch:
    """看站起来了没有：deadline_s 以前站起来，并且一直站住 stay_s，才算（记站起来的那一刻）。"""

    def __init__(self, deadline_s: float, stay_s: float) -> None:
        self._deadline_s = deadline_s
        self._stay_s = stay_s
        self._since_s: float | None = None
        self.stood_up_at_s: float | None = None

    def update(self, time_s: float, upright: bool) -> None:
        if self.stood_up_at_s is not None:
            return
        if not upright:
            self._since_s = None
            return
        if self._since_s is None:
            if time_s > self._deadline_s + TIME_EPSILON_S:
                return
            self._since_s = time_s
        if time_s - self._since_s >= self._stay_s - TIME_EPSILON_S:
            self.stood_up_at_s = self._since_s


def exam_get_up(
    policy: Policy, pose: StartPose, *, deadline_s: float = GET_UP_S, stay_s: float = STAY_UP_S, sensed: bool = True
) -> GetUpResult:
    """从躺着开始（跌倒的反射关掉，像小脑层在做起来的动作时那样），命令是站着不动。"""
    bench = PolicyBench(policy, sensed=sensed, start=pose, fall_reflex=False)
    watch = UprightWatch(deadline_s, stay_s)
    best = 0.0
    for _ in range(round((deadline_s + stay_s) / bench.timestep)):
        bench.step(STILL)
        best = max(best, bench.pelvis_height_m() / bench.standing_height_m)
        watch.update(bench.time_s, bench.upright())
        if watch.stood_up_at_s is not None:
            break
    stood_up = watch.stood_up_at_s is not None
    return GetUpResult(pose.value, stood_up, watch.stood_up_at_s if stood_up else math.nan, best)


# 一道题（或者一道题的一部分）在一个进程里考：(题, 哪一个)。
EXAM_ITEMS = ("stand", "push", "walk", "stairs", "get_up")


def exam_tasks(items: Sequence[str] = EXAM_ITEMS) -> list[tuple[str, str]]:
    """要考的每一份：站（最久的，先开始）、四个方向推、走、三种楼梯、三种躺着。"""
    unknown = sorted(set(items) - set(EXAM_ITEMS))
    if unknown:
        raise ValueError(f"没有这几道题：{'、'.join(unknown)}（有 {'、'.join(EXAM_ITEMS)}）")
    parts = {
        "stand": [""],
        "push": list(PUSH_DIRECTIONS),
        "walk": [""],
        "stairs": [trial.name for trial in STAIRS_TRIALS],
        "get_up": [pose.value for pose in LYING_POSES],
    }
    return [(item, part) for item in EXAM_ITEMS if item in items for part in parts[item]]


def run_task(contract_path: Path, item: str, part: str):
    """在一个进程里考一份（策略在这个进程里读：ONNX 的会话不能跨进程传）。"""
    policy = load_policy(contract_path)
    if item == "stand":
        return exam_stand(policy)
    if item == "push":
        return exam_push(policy, part)
    if item == "walk":
        return exam_walk(policy)
    if item == "stairs":
        return exam_stairs(policy, next(trial for trial in STAIRS_TRIALS if trial.name == part))
    return exam_get_up(policy, StartPose(part))


def run_exam(contract_path: Path, items: Sequence[str] = EXAM_ITEMS, workers: int | None = None) -> ExamResult:
    """考一个策略：每一份一个进程，一起考，按题的顺序收起来。"""
    policy = load_policy(contract_path)
    tasks = exam_tasks(items)
    workers = workers or max(1, min(len(tasks), (os.cpu_count() or 1) - SPARE_CPUS))
    # 用 spawn 开进程：父进程里已经有 ONNX 的线程，fork 出来的子进程可能卡住。
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(run_task, contract_path, item, part) for item, part in tasks]
        results = [future.result() for future in futures]
    found = {
        item: [result for (task_item, _), result in zip(tasks, results, strict=True) if task_item == item]
        for item in EXAM_ITEMS
    }
    return ExamResult(
        policy=policy.name,
        date=datetime.date.today().isoformat(),
        stand=found["stand"][0] if found["stand"] else None,
        pushes=found["push"],
        walk=found["walk"][0] if found["walk"] else None,
        stairs=found["stairs"],
        get_up=found["get_up"],
    )


def describe(exam: ExamResult) -> str:
    """考试的结果：一张总表，再加被推、走、楼梯的细表。没考的题不写。"""
    lines = [f"策略 {exam.policy}（{exam.date}）", "", "| 题 | 结果 |", "|---|---|"]
    if exam.stand:
        lines.append(f"| 站 {STAND_S / 3600:g} 小时 | {describe_stand(exam.stand)} |")
    if exam.pushes:
        held = "、".join(
            f"{push.direction} {push.strongest_share:.0%}（{push.strongest_n:.0f} N）" for push in exam.pushes
        )
        lines.append(f"| 被推（扛得住体重的几成） | {held} |")
    if exam.walk:
        lines.append(f"| 走 {WALK_DISTANCE_M / 1000:g} 公里 | {describe_walk(exam.walk)} |")
    if exam.stairs:
        lines.append(
            f"| 上下楼梯（{STAIRS.steps} 级） | {'；'.join(describe_stairs(result) for result in exam.stairs)} |"
        )
    if exam.get_up:
        lines.append(
            f"| 摔倒了起来（{GET_UP_S:g} 秒内） | {'；'.join(describe_get_up(result) for result in exam.get_up)} |"
        )
    if exam.pushes:
        lines += ["", *push_table(exam.pushes)]
    if exam.walk:
        lines += ["", *walk_table(exam.walk)]
    return "\n".join(lines)


def describe_stand(stand: StandResult) -> str:
    fell = f"第 {stand.seconds:.0f} 秒倒了" if stand.fell else "没倒"
    winding = (
        "没有驱动器的发热模型"
        if math.isnan(stand.hottest_winding_c)
        else f"最热的绕组 {stand.hottest_winding_c:.0f} °C"
    )
    return (
        f"{fell}；最多歪 {numbers([stand.max_tilt_deg], '.1f')}°，挪了 {numbers([stand.drift_m], '.2f')} m，"
        f"平均机械功率 {numbers([stand.mean_power_w], '.1f')} W；{winding}"
    )


def describe_walk(walk: WalkResult) -> str:
    state = "摔了" if walk.fell else ("没摔" if walk.reached else "没摔，但时间到了没走够")
    error = numbers(walk.mean_error.values(), ".2f")
    return (
        f"走了 {walk.distance_m:.0f} m（{walk.seconds / 60:.0f} 分钟），{state}；跟指令平均差（前、左、转）{error}；"
        f"每米正功 {numbers([walk.work_per_m_j], '.0f')} J（移动代价 {numbers([walk.cost_of_transport], '.2f')}）"
    )


def describe_stairs(result: StairsResult) -> str:
    state = "走完了" if result.finished else ("摔了" if result.fell else "时间到了")
    return f"{result.trial}：上了 {result.up_steps} 级、下了 {result.down_steps} 级，{state}"


def describe_get_up(result: GetUpResult) -> str:
    if result.stood_up:
        return f"{result.pose}：第 {result.seconds:.1f} 秒站起来"
    return f"{result.pose}：没起来（骨盆最高到站着时的 {result.best_height_share:.0%}）"


def push_table(pushes: list[PushResult]) -> list[str]:
    """每一档推的结果：都没倒的写最多歪了多少度，有倒的写倒了几次，倒了以后不再推的写 —。"""
    shares = sorted({trial.share for push in pushes for trial in push.trials})
    lines = [
        "| 推力是体重的 | " + " | ".join(push.direction for push in pushes) + " |",
        "|---|" + "---|" * len(pushes),
    ]
    for share in shares:
        cells = []
        for push in pushes:
            trial = next((trial for trial in push.trials if trial.share == share), None)
            cells.append("—" if trial is None else push_cell(trial))
        lines.append(f"| {share:.0%} | " + " | ".join(cells) + " |")
    return lines


def push_cell(trial: PushTrial) -> str:
    if trial.held:
        return f"歪 {trial.max_tilt_deg:.0f}°"
    return f"倒了 {trial.falls}/{trial.attempts}"


def walk_table(walk: WalkResult) -> list[str]:
    """一圈里每一段（每种命令）跟指令平均差多少。"""
    lines = ["| 一圈里的段 | 命令（前、左、转） | 平均差 |", "|---|---|---|"]
    for segment in WALK_LAP:
        if segment.label in walk.errors:
            command = numbers(segment.command.values(), "+.2f")
            lines.append(f"| {segment.label} | {command} | {numbers(walk.errors[segment.label].values(), '.2f')} |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path, help="策略的规约（contract.json）")
    parser.add_argument("--items", nargs="+", choices=EXAM_ITEMS, default=list(EXAM_ITEMS), help="只考这几道题")
    parser.add_argument("--workers", type=int, default=None, help="最多同时开几个进程")
    arguments = parser.parse_args()
    exam = run_exam(arguments.contract, arguments.items, arguments.workers)
    output = arguments.contract.parent / EXAM_RESULT_NAME
    output.write_text(json.dumps(asdict(exam), ensure_ascii=False, indent=2), encoding="utf-8")
    print(describe(exam))
    print(f"写进了 {output}")


if __name__ == "__main__":
    main()
