"""力量的报告：让 Nova（和基线 G1）做第一次考试要做的动作，算出每个关节要多大的力矩、转多快，写成中文的 Markdown。

用法：python -m nova_body.strength_report [--output 路径]
动作很多，几个进程一起算，也要两三分钟。
"""

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from nova_body.actuator_mass import best_today_model, conservative_model
from nova_body.baseline import load_g1
from nova_body.body import Body, Region
from nova_body.design import CORE_BODY, FULL_BODY, JOINT_GROUPS, Strength, TorqueRule
from nova_body.mass_closure import Assumptions, close_mass
from nova_body.model import build_nova
from nova_body.motions import (
    BOX_KG,
    MAX_BALANCE_ERROR_M,
    MAX_REACH_ERROR_M,
    STAIR_RISER_M,
    STAIR_TREAD_M,
    Level,
)
from nova_body.skeleton import LINKS
from nova_body.strength import (
    G1,
    NOVA,
    REFERENCE_BODY_MASS_KG,
    SPEED_MARGIN,
    TORQUE_MARGIN,
    GroupTarget,
    JointNeed,
    MotionDemand,
    Task,
    group_targets,
    joint_needs,
    run_tasks,
    tasks_for,
)

DEFAULT_OUTPUT = Path("/docs/报告/力量.md")
# 试踝的范围：这几个"往上最多转多少度"，每个都做这几个最要踝的动作。现在的范围另算（就是上面全部的动作）。
ANKLE_TRIALS_DEG = (20.0, 40.0)
ANKLE_TRIAL_MOTIONS = ("walk_fast", "stairs_down", "squat")
ANKLE_KEY = "ankle_pitch"
FRICTION_CHECKED = 0.6
# "新的身体做同样的动作"那张表只列用到峰值这么多以上的关节。
USAGE_SHOWN = 0.3
PERCENT = 100.0
MM_PER_M = 1000.0


@dataclass(frozen=True)
class _Results:
    """报告要的全部数。"""

    nova: Body
    nova_mass_kg: float
    nova_demands: list[MotionDemand]
    g1: Body
    g1_mass_kg: float
    g1_demands: list[MotionDemand]
    ankle_trials: dict[float, list[MotionDemand]]


def build_report() -> str:
    """算全部的动作，返回报告的全文。"""
    results = _measure()
    needs = joint_needs(results.nova, results.nova_demands)
    targets = group_targets(needs, results.nova_demands, results.nova_mass_kg)
    sections = [
        _header(),
        _summary_section(results, targets),
        _method_section(),
        _motions_section(results.nova, results.nova_demands),
        _targets_section(targets),
        _usage_section(results.nova, needs),
        _ankle_section(results),
        _baseline_section(results),
        _jump_section(results),
        _limits_section(),
    ]
    return "\n\n".join(sections) + "\n"


def _measure() -> _Results:
    nova_model = build_nova()
    nova = nova_model.body
    g1 = load_g1()
    nova_tasks = tasks_for(nova, NOVA)
    g1_tasks = tasks_for(g1, G1)
    lower = math.degrees(_joint_range(nova, ANKLE_KEY)[0])
    trial_tasks = [
        Task(NOVA, key, ((ANKLE_KEY, lower, upper),)) for upper in ANKLE_TRIALS_DEG for key in ANKLE_TRIAL_MOTIONS
    ]
    demands = run_tasks([*nova_tasks, *g1_tasks, *trial_tasks])
    nova_demands = demands[: len(nova_tasks)]
    g1_demands = demands[len(nova_tasks) : len(nova_tasks) + len(g1_tasks)]
    trials = demands[len(nova_tasks) + len(g1_tasks) :]
    per_trial = len(ANKLE_TRIAL_MOTIONS)
    ankle_trials = {
        upper: trials[index * per_trial : (index + 1) * per_trial] for index, upper in enumerate(ANKLE_TRIALS_DEG)
    }
    return _Results(
        nova=nova,
        nova_mass_kg=float(nova_model.budget.total_kg),
        nova_demands=nova_demands,
        g1=g1,
        g1_mass_kg=_mass(g1),
        g1_demands=g1_demands,
        ankle_trials=ankle_trials,
    )


# 各节 -----------------------------------------------------------------------------------------------


def _header() -> str:
    return "\n".join(
        [
            "# 力量到底要多大",
            "",
            "**这份报告是程序算出来的，不要手改。** 要改就改 `body/nova_body` 里的动作或者假设，再运行：",
            "",
            "```bash",
            "docker compose run --rm body python -m nova_body.strength_report",
            "```",
            "",
            "P1 的 1.5 步：让 Nova 做第一次考试要做的那些动作（走、上下楼、蹲起、端东西……），"
            "从动作反推每个关节要多大的力矩、转多快，再留余地，就是驱动器的目标。",
        ]
    )


def _summary_section(results: _Results, targets: list[GroupTarget]) -> str:
    best, conservative = best_today_model(), conservative_model()
    daily, peak = Assumptions(), Assumptions(strength=Strength.HUMAN_PEAK)
    core = close_mass(CORE_BODY, daily, best).total_kg
    core_conservative = close_mass(CORE_BODY, daily, conservative).total_kg
    core_peak = close_mass(CORE_BODY, peak, best).total_kg
    full = close_mass(FULL_BODY, daily, best).total_kg
    knee = _target(targets, "knee")
    hip = _target(targets, "hip_pitch")
    ankle = _target(targets, "ankle")
    feasible = sum(demand.feasible for demand in results.nova_demands)
    upper = math.degrees(_joint_range(results.nova, ANKLE_KEY)[1])
    counted = [demand for demand in results.nova_demands if demand.feasible and demand.level is Level.CORE]
    worst_edge = min(demand.edge_margin_m for demand in counted if not math.isnan(demand.edge_margin_m))
    worst_friction = max(demand.friction_ratio for demand in counted)
    trials = "；".join(
        f"{trial:.0f}° 时"
        + (
            _names_of(_infeasible(results.ankle_trials[trial])) + "做不出来"
            if _infeasible(results.ankle_trials[trial])
            else "都做得出来"
        )
        for trial in ANKLE_TRIALS_DEG
    )
    return "\n".join(
        [
            "## 1. 结论",
            "",
            f"- **{len(results.nova_demands)} 个动作里 Nova 做得出来 {feasible} 个**：每一帧都够得着、站得稳。"
            f"脚底的压力中心最多跑出脚底 {-worst_edge * MM_PER_M:.0f} mm（几乎都在里面），"
            f"不打滑最多要 {worst_friction:.2f} 的摩擦（地面按 {FRICTION_CHECKED} 算）。",
            f"- **核心版的体重 {core:.1f} kg**（今天最好的驱动；保守的驱动 {core_conservative:.1f} kg；"
            f"完整版 {full:.1f} kg）。"
            f'驱动器还按原来的"人的峰值"估的话是 {core_peak:.1f} kg。',
            f"- **腿的力量省不下来**：下这种最陡的楼梯，膝要的力矩留了余地以后是 {knee.daily_torques_nm[0]:.0f} N·m"
            f"（按 70 kg），比原来估的人的峰值 {knee.group.peak_torques_nm[0]:.0f} N·m 还大；"
            f"髋前后 {hip.daily_torques_nm[0]:.0f} N·m、踝前后 {ankle.daily_torques_nm[0]:.0f} N·m，"
            "和原来估的差不多。",
            "- **省下来的是侧摆、转动、腰和手臂**：这些关节在动作里出的力比人的峰值小得多。",
            f"- **踝往上（脚尖向上）的范围从 20° 改成 {upper:.0f}°**：{trials}（见第 6 节）。",
            f"- 跳（跳起 25 cm）只拿来比，不算进目标：{_jump_verdict(results)}（见第 8 节）。",
        ]
    )


def _method_section() -> str:
    return "\n".join(
        [
            "## 2. 怎么算的",
            "",
            "1. **把动作一帧一帧写出来**（每秒 100 帧）：说清楚脚踩在哪、手去哪、重心在哪，全身的姿势由逆运动学算"
            "（`motions.py`、`ik.py`）。对哪个身体都一样，所以 G1 也能做同样的动作。",
            "2. **走路和楼梯用机器人常用的办法**（倒立摆 + 压力中心，`gait.py`），但像人一样："
            "后面那只脚离地以前先抬脚跟、用脚掌蹬；下楼时落下的脚先用脚掌着地；"
            '重心的高低按"两条腿都够得着、姿势尽量像站着"来定，再平滑一下。'
            "算出来的压力中心和计划差得多，就修正重心的路，修正 3 遍。",
            "3. **逆动力学**（`inverse.py`）：由每一帧的姿势算出速度、加速度（先像量人的动作那样低通滤一下，约 6 Hz），"
            "MuJoCo 算出要多大的力；骨盆上的那份力由地面（或者膝盖、手）给，分给撑着的地方；剩下的就是每个关节的力矩。"
            "同时检查：压力中心在不在脚底里面、要多大的摩擦。",
            f"4. **目标 = 能做的动作里最大的那个 x 余地**：力矩 x {TORQUE_MARGIN}，转速 x {SPEED_MARGIN}。"
            '余地是给"真的做起来没这么顺"的：被碰一下、脚下打滑、端着东西上下楼、驱动器旧了、天热降额。',
            f"5. **按体重折算**：腿和腰的力矩跟着体重变，按 {REFERENCE_BODY_MASS_KG:.0f} kg 写进设计，"
            "质量闭环再按算出来的体重放大；手臂主要是端东西，不折算。",
            "6. **算两遍**：先用旧的身体算出目标，按目标重新算质量、生成身体，再用新的身体算一遍，"
            "写进设计的是第二遍的数。",
            "",
            f"算得出来、算不出来按这个分：脚、手的位置差得比 {MAX_REACH_ERROR_M * MM_PER_M:.0f} mm 多，"
            f"或者重心差得比 {MAX_BALANCE_ERROR_M * MM_PER_M:.0f} mm 多，就是这个身体做不出这个动作。",
        ]
    )


def _motions_section(body: Body, demands: list[MotionDemand]) -> str:
    rows = []
    for demand in demands:
        rows.append(
            [
                demand.name,
                demand.description,
                f"{demand.duration_s:.1f} s",
                "能" if demand.feasible else "**做不出来**",
                _mm(demand.edge_margin_m),
                f"{demand.friction_ratio:.2f}",
                _hardest(body, demand),
            ]
        )
    lines = [
        "## 3. 动作",
        "",
        '"离边"是脚底的压力中心离脚底的边最近的时候还有多远（负的是跑到了外面一点：这一帧要的力矩脚底给不了，'
        '真机要靠别的办法补，比如手扶着）。只看撑着一成以上重量的脚。"摩擦"是不打滑最少要的摩擦系数。',
        "",
        *_table(["动作", "说明", "多长", "能不能做", "压力中心离边", "摩擦", "最费力的关节（N·m）"], rows),
        "",
        f"楼梯照考场：一级高 {STAIR_RISER_M * 100:.0f} cm、踏面 {STAIR_TREAD_M * 100:.0f} cm，比 Nova 的脚还短。"
        f"箱子 {BOX_KG:.0f} kg。",
        "",
        "**没有算进来的**：单膝跪地再站起来。后脚离前脚太远，慢慢地（每一刻都站得稳）站不起来，"
        "要借一点冲劲（人也是），留到 P2 用控制器真的做。",
    ]
    return "\n".join(lines)


def _targets_section(targets: list[GroupTarget]) -> str:
    rows = []
    for target in targets:
        group = target.group
        scaled = group.torque_rule is TorqueRule.BODY_MASS
        for index in range(group.dof):
            rows.append(
                [
                    group.name if index == 0 else "",
                    _dof_label(group.key, index),
                    f"{target.torques_nm[index]:.0f}",
                    target.torque_motions[index],
                    f"{target.daily_torques_nm[index]:.0f}" + ("" if scaled else "（不折算）"),
                    _design_daily(group.key, index),
                    f"{group.peak_torques_nm[index]:.0f}",
                    f"{target.speeds_rad_s[index]:.1f}（{target.speed_motions[index]}）",
                    f"{target.speed_targets_rad_s[index]:.1f}",
                ]
            )
    shared = [target for target in targets if target.shared_nm is not None]
    lines = [
        "## 4. 每组关节的目标",
        "",
        f'"动作里最多"是现在这个身体（{_mass_note()}）做动作时要的，左右取大的；'
        f'"这一遍算的目标"= 它 x {TORQUE_MARGIN}，腿和腰按 70 kg 折算；"设计里的"是写进 `design.py` 的'
        "（上一遍算的，和这一遍差得不多就是算到头了）。力矩 N·m，转速 rad/s。",
        "",
        *_table(
            [
                "关节组",
                "自由度",
                "动作里最多",
                "在哪个动作",
                "这一遍算的目标",
                "设计里的",
                "人的峰值（初估）",
                "转速：动作里最多",
                f"转速目标（x {SPEED_MARGIN}）",
            ],
            rows,
        ),
        "",
        "**并联的组**（两个驱动器一起带两个自由度）：每个驱动器要出的是同一刻两个力矩之和的一半。"
        '质量闭环保守地按"两个峰值同时来"算，动作里同时要的其实小一些：',
        "",
        *_table(
            ["关节组", "同一刻要的（留了余地、折算以后）", "质量闭环按的"],
            [
                [
                    target.group.name,
                    f"{target.shared_nm:.0f}",
                    f"{_closure_shared(target):.0f}",
                ]
                for target in shared
            ],
        ),
        "",
        "**动作没算出目标的组**：颈、肩转、前臂转、腕。它们在这些动作里几乎不出力（拧门把手、转头看、拿着东西转手腕这些"
        '动作还没写），算出来的数太小，不能当目标，还用人的峰值。肩侧摆和肘的目标比"手臂水平伸直、端着 5 kg、'
        '动起来 x 2"小，质量闭环取两个里大的那个。',
    ]
    return "\n".join(lines)


def _usage_section(body: Body, needs: list[JointNeed]) -> str:
    peaks = {joint.name: joint.peak_torque_nm for joint in body.joints}
    rows = [
        [need.label, f"{need.torque_nm:.0f}", f"{peaks[need.name]:.0f}", _percent(need.torque_nm / peaks[need.name])]
        for need in needs
        if not need.name.startswith("right_") and need.torque_nm / peaks[need.name] > USAGE_SHOWN
    ]
    return "\n".join(
        [
            "## 5. 新的身体做同样的动作",
            "",
            f"按上面的目标重新算了质量、生成了身体（{_mass_note()}），再做一遍全部的动作。"
            f"每个关节最多用到它峰值的多少（只列用到三成以上的、只列左侧）。留了 {TORQUE_MARGIN} 倍的余地，"
            f"所以最费力的那个动作大约用到 {1 / TORQUE_MARGIN * PERCENT:.0f}%：",
            "",
            *_table(["关节", "动作里最多（N·m）", "这个关节的峰值（N·m）", "用到"], rows),
        ]
    )


def _ankle_section(results: _Results) -> str:
    current = math.degrees(_joint_range(results.nova, ANKLE_KEY)[1])
    by_key = {demand.key: demand for demand in results.nova_demands}
    columns = [results.ankle_trials[upper] for upper in ANKLE_TRIALS_DEG]
    rows = []
    for index, key in enumerate(ANKLE_TRIAL_MOTIONS):
        row = [by_key[key].name]
        row += [_feasible(trials[index]) for trials in columns]
        row.append(_feasible(by_key[key]))
        rows.append(row)
    header = ["动作", *(f"往上最多 {upper:.0f}°" for upper in ANKLE_TRIALS_DEG), f"往上最多 {current:.0f}°（现在的）"]
    return "\n".join(
        [
            "## 6. 踝要多大的范围",
            "",
            "Nova 的踝原来照人定：脚尖往上最多 20°。站着时（膝弯 15°）已经用掉 12°，剩下的太少：腿缩不短，"
            "走路时抬脚、下楼时撑着的那条腿弯下去、蹲下，都要踝再往上转。人负重的时候踝能到 35~45°（膝弯着），"
            "G1 是 50°。同样的动作换几个范围试（只改踝，别的都一样）：",
            "",
            *_table(header, rows),
            "",
            f"所以改成 {current:.0f}°：这是能把这些动作都做出来的最小的整 5 度。有的帧踝转到了头，靠髋和腰补上；"
            "做机构的时候限位最好比这个再多几度。",
        ]
    )


def _baseline_section(results: _Results) -> str:
    # Nova 也只算 G1 做了的那些动作，才好比。
    done = {demand.key for demand in results.g1_demands}
    nova_needs: dict[str, JointNeed] = {}
    for need in joint_needs(results.nova, [demand for demand in results.nova_demands if demand.key in done]):
        kind = _kind(need.label)
        if kind not in nova_needs or need.torque_nm > nova_needs[kind].torque_nm:
            nova_needs[kind] = need
    g1_counted = [demand for demand in results.g1_demands if demand.feasible and demand.level is Level.CORE]
    g1_needs = joint_needs(results.g1, results.g1_demands)
    g1_peaks = {joint.name: joint.peak_torque_nm for joint in results.g1.joints}
    rows = []
    for need in g1_needs:
        if need.name.startswith("right_") or _region(results.g1, need.name) not in {Region.LEG, Region.WAIST}:
            continue
        nova = nova_needs.get(_kind(need.label))
        rows.append(
            [
                _kind(need.label),
                f"{nova.torque_nm / results.nova_mass_kg:.2f}" if nova else "-",
                f"{need.torque_nm / results.g1_mass_kg:.2f}",
                f"{need.torque_nm:.0f}（{need.torque_motion}）",
                f"{g1_peaks[need.name]:.0f}",
                _percent(need.torque_nm / g1_peaks[need.name]),
            ]
        )
    over = _over_peak(results.g1, g1_counted)
    return "\n".join(
        [
            "## 7. 和基线（G1）比",
            "",
            f"G1（{results.g1_mass_kg:.1f} kg，没有手）做同样的、只用腿的动作（{len(g1_counted)} 个都做得出来）。"
            "Nova 这一列也只算这几个动作。按每公斤体重比，两个身体的腿要的差不多：说明算法对哪个身体都一样，"
            "差在身体上（比如 G1 的踝能往上转 50°、腿短）。",
            "",
            *_table(
                ["关节", "Nova 每公斤（N·m/kg）", "G1 每公斤", "G1 最多要（N·m）", "G1 的电机峰值", "G1 用到"],
                rows,
            ),
            "",
            "G1 自己的电机不够做的动作（要的比峰值大）：" + (over or "没有") + "。"
            "G1 实际走路的样子和这里不一样（步子小、迈得快，是训练出来的），所以这只说明这些动作对它的踝和髋很吃力。",
        ]
    )


@dataclass(frozen=True)
class _JumpUse:
    """跳的时候一个关节要多少、家务动作里最多要多少、现在的峰值。"""

    label: str
    jump_nm: float
    chores_nm: float
    peak_nm: float

    @property
    def share(self) -> float:
        return self.jump_nm / self.peak_nm


def _jump_uses(results: _Results) -> list[_JumpUse]:
    """腿和腰的每个关节（只算左侧）：跳的时候用到峰值的多少。"""
    jump = next(demand for demand in results.nova_demands if demand.level is Level.REFERENCE)
    names = [joint.name for joint in results.nova.joints]
    peaks = {joint.name: joint.peak_torque_nm for joint in results.nova.joints}
    uses = []
    for need in joint_needs(results.nova, results.nova_demands):
        if need.name.startswith("right_") or _region(results.nova, need.name) not in {Region.LEG, Region.WAIST}:
            continue
        torque = float(jump.torques_nm[names.index(need.name)])
        uses.append(_JumpUse(need.label, torque, need.torque_nm, peaks[need.name]))
    return uses


def _jump_verdict(results: _Results) -> str:
    """一句话：按现在的力量跳不跳得起来。"""
    uses = _jump_uses(results)
    over = [use for use in uses if use.share > 1]
    if over:
        return f"按现在的力量跳不了这么高（{'、'.join(_kind(use.label) for use in over)}的峰值不够）"
    hardest = max(uses, key=lambda use: use.share)
    return f"按现在的力量也跳得起来，最吃力的是{_kind(hardest.label)}（用到峰值的 {_percent(hardest.share)}）"


def _jump_section(results: _Results) -> str:
    jump = next(demand for demand in results.nova_demands if demand.level is Level.REFERENCE)
    uses = _jump_uses(results)
    hardest = max(uses, key=lambda use: use.share)
    rows = [
        [use.label, f"{use.jump_nm:.0f}", f"{use.chores_nm:.0f}", f"{use.peak_nm:.0f}", _percent(use.share)]
        for use in uses
        if use.share >= USAGE_SHOWN
    ]
    return "\n".join(
        [
            "## 8. 跳（运动员级，只拿来比）",
            "",
            f"{jump.description}。蹬地只有零点几秒，{_kind(hardest.label)}要 {hardest.jump_nm:.0f} N·m，"
            f"是家务动作里最多的 {hardest.jump_nm / hardest.chores_nm:.1f} 倍。",
            "",
            "只列跳的时候用到峰值三成以上的关节（左侧）：",
            "",
            *_table(["关节", "跳要的（N·m）", "家务动作里最多", "现在的峰值", "跳要用到"], rows),
            "",
            f"{_jump_verdict(results)}。跳得更高、跑起来这些运动员级的动作要不要做，以后再定（力量要加，身体会重很多）。",
        ]
    )


def _limits_section() -> str:
    return "\n".join(
        [
            "## 9. 还不准的地方",
            "",
            "- 动作是规划出来的（逆运动学 + 逆动力学），不是控制器真的在仿真里做出来的。真的做起来不会这么顺，"
            "所以留了余地；P2 用控制器做的时候再对一遍。",
            "- 脚是一块硬的平板（核心版没有脚趾）。脚跟抬起时只有脚掌最前面一条撑着，"
            "压力中心偶尔跑出去一点（第 3 节）。",
            "- 只算了第一次考试的这些动作。拧门把手、转头、拿着东西转手腕没写，那几个关节还用人的峰值。",
            "- 转速目标是这些动作要的；动作都不快，手臂、腰的转速目标偏小，做快的动作时要再看（1.6 步）。",
            "- 驱动器只按力矩估重量，转速、发热、降额是 1.6 步的事。",
        ]
    )


# 小零件 -----------------------------------------------------------------------------------------------


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _target(targets: list[GroupTarget], key: str) -> GroupTarget:
    return next(target for target in targets if target.group.key == key)


def _design_daily(key: str, index: int) -> str:
    group = next(group for group in JOINT_GROUPS if group.key == key)
    return f"{group.daily_torques_nm[index]:.0f}" if group.daily_torques_nm else "-"


def _dof_label(key: str, index: int) -> str:
    """一组关节里第 index 个自由度叫什么（取骨架里的名字）。"""
    for part in LINKS:
        for joint in part.joints:
            if joint.group == key and joint.index == index:
                return joint.name
    return "-"


def _hardest(body: Body, demand: MotionDemand) -> str:
    """这个动作里出力最大的关节和它的力矩。"""
    if not demand.feasible:
        return "-"
    index = int(np.nanargmax(demand.torques_nm))
    return f"{_kind(body.joints[index].label)} {demand.torques_nm[index]:.0f}"


def _closure_shared(target: GroupTarget) -> float:
    """质量闭环里并联的每个驱动器按多大的力矩算（两个峰值之和的一半，按 70 kg）。"""
    torques = target.group.spec_torques_nm(Strength.DAILY)
    return sum(torques) / len(torques)


def _infeasible(demands: list[MotionDemand]) -> list[MotionDemand]:
    return [demand for demand in demands if not demand.feasible]


def _names_of(demands: list[MotionDemand]) -> str:
    return "、".join(demand.name for demand in demands)


def _feasible(demand: MotionDemand) -> str:
    return "能" if demand.feasible else "做不出来"


def _over_peak(body: Body, demands: list[MotionDemand]) -> str:
    peaks = np.array([joint.peak_torque_nm for joint in body.joints])
    found = []
    for demand in demands:
        over = [
            body.joints[index].label
            for index in np.flatnonzero(demand.torques_nm > peaks)
            if not body.joints[index].name.startswith("right_")
        ]
        if over:
            found.append(f"{demand.name}（{'、'.join(_kind(label) for label in over)}）")
    return "，".join(found)


def _kind(label: str) -> str:
    """去掉"左 ""右 "：剩下的是关节的种类，两个身体一样。"""
    for prefix in ("左 ", "右 "):
        if label.startswith(prefix):
            return label[len(prefix) :]
    return label


def _region(body: Body, name: str) -> Region:
    return next(joint.region for joint in body.joints if joint.name == name)


def _joint_range(body: Body, key: str) -> tuple[float, float]:
    joint = next(joint for joint in body.joints if joint.name.endswith(key))
    return joint.lower_rad, joint.upper_rad


def _mass(body: Body) -> float:
    return float(body.model.body_subtreemass[body.model.body(body.anatomy.root).id])


def _mass_note() -> str:
    return f"体重 {close_mass(CORE_BODY, Assumptions(), best_today_model()).total_kg:.1f} kg"


def _mm(value_m: float) -> str:
    return "-" if math.isnan(value_m) else f"{value_m * MM_PER_M:.0f} mm"


def _percent(share: float) -> str:
    return f"{share * PERCENT:.0f}%"


def main(argv: list[str] | None = None) -> int:
    """命令行入口：算一遍，写报告，打印结论。"""
    parser = argparse.ArgumentParser(description="从动作反推 Nova 每个关节要的力量，写一份报告。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="报告写到哪里")
    arguments = parser.parse_args(argv)
    report = build_report()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report, encoding="utf-8", newline="\n")
    print(report[report.index("## 1.") : report.index("## 2.")].strip())
    print(f"\n报告写到了 {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
