"""驱动器和热的报告（1.6 步）：每组关节选的驱动器、一轮家务的热预算、一直出力的时候、要多大的电，写成中文的 Markdown。

用法：python -m nova_body.drive_report [--output 路径]
要让 Nova 做一遍全部的动作（几个进程一起算），一两分钟。
"""

import argparse
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from nova_body.actuator_mass import best_today_model, conservative_model
from nova_body.design import CONTINUOUS_TARGETS, CORE_BODY, FULL_BODY, JOINT_GROUPS, JointGroup
from nova_body.drives import (
    COOLANT_C,
    COULOMB_SHARE_OF_PEAK,
    DERATE_FROM_C,
    HEAT_REMOVAL_W_PER_KG,
    KM_REFERENCE_NM_PER_SQRT_W,
    MIN_KNEE_SPEED_RAD_S,
    STALL_TO_PEAK,
    WINDING_MAX_C,
    Cooling,
    DriveSpec,
    hot_resistance_factor,
    with_cooling,
)
from nova_body.heat import (
    CHORE_CYCLE,
    CONTINUOUS_MARGIN,
    CYCLE_S,
    CYCLES,
    REST,
    SIZING_WINDOW_S,
    STRESS_HOLDS,
    HoldHeat,
    Motor,
    RoundHeat,
    chore_round,
    continuous_targets,
    hold_after_round,
    motors_of,
)
from nova_body.mass_closure import Assumptions, MassBudget, close_mass
from nova_body.model import PART_STYLES, NovaModel, PartKind, build_nova
from nova_body.motions import Level
from nova_body.packaging import DIAMETER_FIT, LENGTH_FIT, USABLE_SHARE, pelvis_fit
from nova_body.strength import NOVA, REFERENCE_BODY_MASS_KG, MotionDemand, run_tasks, tasks_for

DEFAULT_OUTPUT = Path("/docs/报告/驱动器.md")
# 主电脑的热（系统结构第 5 节：一套约 100~150 W），取上限。
COMPUTER_W = 150.0
# 母线电压：比这几档。RobStride 04 在 48 V 时，力矩常数（2.1 N·m/A）x 空载转速（20.9 rad/s）约 44：
# 绕组按转速选，同样的电压下，转得越快的绕组，同样的力矩要的电流越大。
BUS_VOLTAGES_V = (48.0, 72.0, 96.0)
REFERENCE_BUS_V = 48.0
KT_TIMES_NO_LOAD = 2.1 * 200.0 * 2.0 * math.pi / 60.0
# 一个驱动器的电流上限按 RobStride 04 的峰值相电流（90 A 峰值，约 64 A 有效值）。
DRIVER_CURRENT_LIMIT_A = 90.0 / math.sqrt(2.0)
# 双绕组的驱动器：两套绕组各接一个驱动板，平时一起出力，各出一半的电流（机体规格第 2 节）。
DUAL_WINDING_BOARDS = 2
HEIGHTS_M = (1.60, 1.70, 1.80)
# 算功率时绕组按 60 °C（一轮家务里一般的温度）。
POWER_WINDING_C = 60.0
SIDE_PREFIXES = ("左 ", "右 ")
# 肩前后和肘改成了液冷。比一比：同样的驱动器不液冷的话，端着箱子站着会怎样。
ARM_GROUPS_COOLED = ("shoulder_pitch", "elbow")
PERCENT = 100.0
MM_PER_M = 1000.0
LITRES_PER_M3 = 1000.0
# 放东西的余地不到这么多，就当是满了。
ROOM_MARGIN = 0.02


@dataclass(frozen=True)
class _Results:
    """报告要的全部数。"""

    nova: NovaModel
    demands: dict[str, MotionDemand]
    motors: list[Motor]
    round_heat: RoundHeat
    holds: list[HoldHeat]
    arms_enclosed: HoldHeat


def build_report() -> str:
    """做全部的动作、算热，返回报告的全文。"""
    results = _measure()
    targets = continuous_targets(results.round_heat, results.holds, results.nova.body.mass_kg, REFERENCE_BODY_MASS_KG)
    sections = [
        _header(),
        _summary_section(results),
        _method_section(),
        _drives_section(results.nova.budget),
        _round_section(results),
        _holds_section(results),
        _targets_section(targets),
        _power_section(results),
        _closure_section(),
        _pelvis_section(results.nova),
        _limits_section(),
    ]
    return "\n\n".join(sections) + "\n"


def _measure() -> _Results:
    nova = build_nova()
    demands = {demand.key: demand for demand in run_tasks(tasks_for(nova.body, NOVA))}
    motors = motors_of(nova.body, nova.budget.drives)
    round_heat = chore_round(motors, demands)
    holds = [hold_after_round(hold, motors, demands, round_heat) for hold in STRESS_HOLDS]
    enclosed = [
        replace(motor, drive=with_cooling(motor.drive, Cooling.ENCLOSED)) if motor.group in ARM_GROUPS_COOLED else motor
        for motor in motors
    ]
    arms_enclosed = hold_after_round(STRESS_HOLDS[0], enclosed, demands, chore_round(enclosed, demands))
    return _Results(nova, demands, motors, round_heat, holds, arms_enclosed)


# 各节 -----------------------------------------------------------------------------------------------


def _header() -> str:
    return "\n".join(
        [
            "# 驱动器和热",
            "",
            "**这份报告是程序算出来的，不要手改。** "
            "要改就改 `body/nova_body` 里的驱动器的模型、家务的循环或者假设，再运行：",
            "",
            "```bash",
            "docker compose run --rm body python -m nova_body.drive_report",
            "```",
            "",
            "P1 的 1.6 步：每个关节的驱动器按电机的物理选（峰值力矩、能一直出的力矩、转速），"
            "再让 Nova 做一轮家务（连续 2 小时），算每个驱动器热到多少度、身体要散走多少热、要多大的电。",
        ]
    )


def _summary_section(results: _Results) -> str:
    budget = results.nova.budget
    hottest = max(results.round_heat.motors, key=lambda item: item.hottest_c)
    derated = [item for item in results.round_heat.motors if item.derating_s > 0]
    by_heat = _groups_by_heat(budget)
    liquid, enclosed = _loss_by_cooling(results.round_heat)
    holds_ok = all(item.derate_after_s is None for hold in results.holds for item in hold.motors)
    currents = _phase_currents(budget)
    pelvis = pelvis_fit(budget, results.nova.dimensions)
    lines = [
        "## 1. 结论",
        "",
        f"- **体重**：核心版 **{budget.total_kg:.1f} kg**（今天最好的驱动；保守的 "
        f"{close_mass(CORE_BODY, Assumptions(), conservative_model()).total_kg:.1f} kg）。"
        "1.5 步算的是 74.2 kg：并联的驱动器改按动作里同一刻要的选（轻了），有几组改成也按发热选（重了，见下一条）。",
        f"- **按发热选得更大的**：{'、'.join(by_heat) if by_heat else '没有'}。它们要一直出的力矩（一直保持一个姿势、"
        "一轮家务里最费力的 5 分钟）比照峰值选的驱动器能一直出的大。",
        f"- **一轮家务（连续 2 小时）**：最热的是{hottest.motor.label}，{hottest.hottest_c:.0f} °C"
        f"（绕组到 {DERATE_FROM_C:.0f} °C 才开始降额）。"
        + ("没有一个驱动器降额。" if not derated else f"降额的：{'、'.join(item.motor.label for item in derated)}。"),
        f"- **身体要散走的热**：驱动器平均 {results.round_heat.mean_loss_w:.0f} W（液冷的 {liquid:.0f} W、"
        f"不液冷的 {enclosed:.0f} W），最忙的一分钟 {results.round_heat.busiest_minute_w:.0f} W；"
        f"加上主电脑约 {COMPUTER_W:.0f} W，散热器按平均约 {results.round_heat.mean_loss_w + COMPUTER_W:.0f} W、"
        f"最多约 {results.round_heat.busiest_minute_w + COMPUTER_W:.0f} W 设计。",
        "- **一直出力**："
        + ("、".join(hold.hold.name for hold in results.holds))
        + f"各 {STRESS_HOLDS[0].seconds / 60:.0f} 分钟（从一轮家务做完时的温度开始）："
        + ("都不降额。" if holds_ok else "有驱动器降额，见第 5 节。")
        + "前提是肩前后和肘也用液冷：冷却液本来就经过手臂通到前臂里手的驱动，顺路冷却它们。"
        + _arms_enclosed_sentence(results.arms_enclosed),
        f"- **母线电压**：电流最大的驱动板（{currents[0][0]}）出峰值力矩时的相电流，"
        + "、".join(
            f"{volts:.0f} V 约 {current:.0f} A" for volts, current in zip(BUS_VOLTAGES_V, currents[0][1], strict=True)
        )
        + "（腿和腰是双绕组，每套绕组一个驱动板，各出一半的电流；第 7 节）。",
        f"- **骨盆里放得下吗**：按驱动器的大小粗算，骨盆里的东西占 {_percent(pelvis.share)}"
        f"（能用的按 {_percent(USABLE_SHARE)} 算），{'放得下' if pelvis.fits else '放不下'}；"
        "超级电容挪到了腹部（第 9 节）。",
    ]
    return "\n".join(lines)


def _method_section() -> str:
    rows = [
        [
            "峰值力矩 → 重量",
            "真实产品的峰值和重量拟合的线（质量闭环那两条：今天最好的、保守的）",
            "8 个低减速比关节电机，见质量闭环的报告",
        ],
        [
            "电机常数（力矩 ÷ √铜损）",
            f"{KM_REFERENCE_NM_PER_SQRT_W} N·m/√W（1.17 kg 时），随重量的 5/6 次方变",
            "CubeMars AK10-9 V2.0（4.05）、RobStride 04（4.29）；形状相似的电机的比例关系",
        ],
        [
            "每公斤能一直散走的热",
            f"液冷 {HEAT_REMOVAL_W_PER_KG[Cooling.LIQUID]:.0f} W/kg、"
            f"不液冷 {HEAT_REMOVAL_W_PER_KG[Cooling.ENCLOSED]:.0f} W/kg",
            "AK10-9 V2.0 能一直出 15 N·m；液冷让能一直出的力矩变成 2.58 倍（Paine 等，Actuators 2015）",
        ],
        [
            "温度",
            f"冷却液（或身体里面的空气）{COOLANT_C:.0f} °C；绕组最高 {WINDING_MAX_C:.0f} °C，"
            f"{DERATE_FROM_C:.0f} °C 起降额",
            "绝缘按 B 级（130 °C）留 10 K；铜的电阻每 K 多 0.393 %",
        ],
        ["热得多快", "两个节点：铜（重量的 15 %）和驱动器的身子；热阻三七分", "假设：只改热得多快，不改最后热到多少"],
        [
            "转速",
            f"峰值力矩一直出到动作要的转速（至少 {MIN_KNEE_SPEED_RAD_S:.0f} rad/s），往上直线掉到 0；"
            f"空载转速是它的 {STALL_TO_PEAK / (STALL_TO_PEAK - 1):.2f} 倍",
            "RobStride 04 在 48 V 时，电压推得动的力矩是峰值的约 4.3 倍；绕组只改电流，不改重量和发热",
        ],
        [
            "摩擦、转子惯量",
            f"干摩擦是峰值的 {COULOMB_SHARE_OF_PEAK * PERCENT:.0f} %，转起来再加；转子惯量随重量的 5/3 次方变",
            "AK10-9 V2.0（反推 0.8 N·m、转子 1002 g·cm²、减速比 9）、RobStride 04（空载电流 2 A）",
        ],
    ]
    return "\n".join(
        [
            "## 2. 怎么选驱动器",
            "",
            "每个驱动器按三样选，重量取要求最大的那样：",
            "",
            "1. **峰值力矩**（几秒的大力，由电流和磁定）：1.5 步从动作算的目标。",
            "2. **能一直出的力矩**（由发热定）：铜损 = (力矩 ÷ 电机常数)²，电机越大电机常数越大；"
            "能一直散走多少热看怎么冷却。"
            "绕组热到最高温度时，铜损正好等于能散走的热，这时的力矩就是能一直出的。",
            "3. **转速**：选绕组，让峰值力矩一直出到动作要的转速。"
            "绕组只改电流，所以转速不改重量，改的是母线电压和电流（第 7 节）。",
            "",
            "并联的一对（踝、腰、腕）：一个驱动器出两个关节力矩之和的一半，另一个出之差的一半（两个方向的力臂按一样长算）。"
            '峰值按动作里同一刻要的选（1.5 步量的），比"两个峰值同时来"小。',
            "",
            *_table(["项目", "用的数", "来源"], rows),
            "",
            "数都是公开的产品数和一篇论文，没有自己测过。所以最后热到多少度只是估计；"
            "真的驱动器做出来以后，按实测的电机常数、热阻、热容改这里。",
        ]
    )


def _drives_section(budget: MassBudget) -> str:
    rows = []
    for group in CORE_BODY.joint_groups():
        for position, drive in enumerate(budget.drives.get(group.key, ())):
            rows.append(
                [
                    _drive_label(group, position),
                    drive.cooling.value,
                    f"{drive.peak_torque_nm:.0f}",
                    f"{drive.required_continuous_nm:.0f}",
                    f"{drive.continuous_torque_nm:.0f}",
                    "发热" if drive.sized_by_heat else "峰值",
                    f"{drive.mass_kg:.2f}",
                    f"{drive.knee_speed_rad_s:.1f} / {drive.no_load_speed_rad_s:.1f}",
                    f"{drive.friction_nm:.1f}",
                    f"{drive.armature_kg_m2:.4f}",
                    f"{drive.thermal.winding_time_constant_s:.0f} / {drive.thermal.housing_time_constant_s:.0f}",
                ]
            )
    return "\n".join(
        [
            "## 3. 每组关节的驱动器",
            "",
            f"核心版，体重 {budget.total_kg:.1f} kg，今天最好的驱动。一侧的；力矩都在关节上（N·m）。"
            '"要一直出的"已经按体重放大、留了余地（第 6 节）；双绕组的驱动器重量里多算了一成（第二套绕组和驱动）。',
            "",
            *_table(
                [
                    "驱动器",
                    "冷却",
                    "峰值",
                    "要一直出的",
                    "能一直出的",
                    "重量按",
                    "重量（kg）",
                    "峰值出到 / 空载（rad/s）",
                    "干摩擦（N·m）",
                    "转子惯量（kg·m²）",
                    "热得多快：绕组 / 身子（秒）",
                ],
                rows,
            ),
        ]
    )


def _round_section(results: _Results) -> str:
    cycle_rows = []
    busy = 0.0
    for step in CHORE_CYCLE:
        seconds = results.demands[step.motion].series.duration_s * step.times
        busy += seconds
        cycle_rows.append([results.demands[step.motion].name, f"{step.times}", f"{seconds:.0f}"])
    cycle_rows.append([REST.name, "-", f"{CYCLE_S - busy:.0f}"])
    heat_rows = [
        [
            item.motor.label,
            item.motor.drive.cooling.value,
            f"{item.hottest_c:.0f}",
            f"{item.hottest_at_s / 60:.0f}",
            f"{item.mean_loss_w:.1f}",
            f"{item.hardest_rms_nm:.1f}",
            _percent(item.continuous_share),
        ]
        for item in sorted(results.round_heat.motors, key=lambda item: -item.hottest_c)
        if not item.motor.label.startswith(SIDE_PREFIXES[1])
    ]
    liquid, enclosed = _loss_by_cooling(results.round_heat)
    return "\n".join(
        [
            "## 4. 一轮家务的热预算",
            "",
            f"一轮家务（Nova 考试：连续 2 小时，第一批的六项）写成一个 {CYCLE_S / 60:.0f} 分钟的循环，做 {CYCLES} 遍。"
            "每样事用 1.5 步写好的动作（每一帧的力矩来自逆动力学），再加上驱动器自己的摩擦；"
            "剩下的时间站着歇（站直，顶住重力）。"
            '拿碗盘、遥控器这些轻东西的时候手臂的力不大，算在"站着歇"和"擦桌子"里。',
            "",
            *_table(["一个循环里做的", "几遍", "一共（秒）"], cycle_rows),
            "",
            f"从冷的（和冷却液一样 {COOLANT_C:.0f} °C）开始做 2 小时。每个驱动器（只列左侧和中间的，右侧差不多）：",
            "",
            *_table(
                [
                    "驱动器",
                    "冷却",
                    "最热（°C）",
                    "什么时候（分钟）",
                    "平均发热（W）",
                    "最费力的 5 分钟（N·m）",
                    "是能一直出的",
                ],
                heat_rows,
            ),
            "",
            f"全身的驱动器平均发热 **{results.round_heat.mean_loss_w:.0f} W**（液冷的 {liquid:.0f} W 走冷却液，"
            f"不液冷的 {enclosed:.0f} W 先散到身体里面的空气，再由液冷带走），最忙的一分钟平均 "
            f"**{results.round_heat.busiest_minute_w:.0f} W**。软外壳、皮肤、外衣都不导热，热只能从背上的散热器走"
            "（机体规格第 12 节），所以加上主电脑，散热器按上面结论里的数设计。",
        ]
    )


def _holds_section(results: _Results) -> str:
    parts = [
        "## 5. 一直出力的时候",
        "",
        "机体规格第 5 节第 12 条：端着东西站着、蹲着干活时，低减速比的电机会一直发热。"
        f"这里从一轮家务做完时的温度开始，一直保持 {STRESS_HOLDS[0].seconds / 60:.0f} 分钟（只列出力最大的几个）：",
    ]
    for hold in results.holds:
        rows = [
            [
                item.motor.label,
                f"{item.torque_nm:.1f}",
                f"{item.motor.drive.continuous_torque_nm:.1f}",
                f"{item.start_c:.0f}",
                f"{item.end_c:.0f}",
                "不会" if item.derate_after_s is None else f"{item.derate_after_s / 60:.1f} 分钟",
            ]
            for item in sorted(hold.motors, key=lambda item: -item.torque_nm / item.motor.drive.continuous_torque_nm)[
                :6
            ]
        ]
        parts += [
            "",
            f"**{hold.hold.name}**",
            "",
            *_table(
                ["驱动器", "要出的（N·m）", "能一直出的（N·m）", "开始（°C）", "保持完（°C）", "多久开始降额"], rows
            ),
        ]
    parts += [
        "",
        f"**对照：肩前后和肘不液冷**（同样的驱动器，{results.arms_enclosed.hold.name}）",
        "",
        *_table(
            ["驱动器", "要出的（N·m）", "能一直出的（N·m）", "开始（°C）", "多久开始降额"],
            [
                [
                    item.motor.label,
                    f"{item.torque_nm:.1f}",
                    f"{item.motor.drive.continuous_torque_nm:.1f}",
                    f"{item.start_c:.0f}",
                    "不会" if item.derate_after_s is None else f"{item.derate_after_s / 60:.1f} 分钟",
                ]
                for item in results.arms_enclosed.motors
                if item.motor.group in ARM_GROUPS_COOLED and not item.motor.label.startswith(SIDE_PREFIXES[1])
            ],
        ),
        "",
        '开始降额只是峰值变小；只要要出的比"能一直出的"小，就能一直保持下去。所以驱动器按'
        '"一直保持这几个姿势"也选了一遍（第 6 节）：膝按蹲着干活选，肩前后和肘按端着箱子站着选（改成液冷）。',
    ]
    return "\n".join(parts)


def _power_section(results: _Results) -> str:
    power_rows = []
    for demand in results.demands.values():
        if demand.series is None:
            continue
        electric = _electric_power_w(results.motors, demand)
        name = demand.name if demand.level is Level.CORE else f"{demand.name}（只拿来比）"
        power_rows.append([name, f"{electric.max():.0f}", f"{max(0.0, -electric.min()):.0f}"])
    current_rows = [
        [label, *(f"{current:.0f}" for current in currents)]
        for label, currents in _phase_currents(results.nova.budget)[:6]
    ]
    return "\n".join(
        [
            "## 7. 要多大的电",
            "",
            "每个动作里全身的驱动器一共要的电功率（出的机械功率加上铜损，绕组按 "
            f"{POWER_WINDING_C:.0f} °C；负的是往回收的，比如下楼时膝在刹）：",
            "",
            *_table(["动作", "最多要（W）", "最多收回（W）"], power_rows),
            "",
            "**母线电压**：同样的力矩和转速，母线电压越高，要的电流越小（绕组按转速选，电压按电池快没电的时候算）。"
            "电流最大的几个驱动板出峰值力矩时的相电流（有效值，A）。双绕组的驱动器有两套绕组、两个驱动板，"
            f"每个出一半。RobStride 04 的驱动板，相电流最多约 {DRIVER_CURRENT_LIMIT_A:.0f} A。",
            "",
            *_table(["驱动器（每个驱动板）", *(f"{volts:.0f} V" for volts in BUS_VOLTAGES_V)], current_rows),
        ]
    )


def _targets_section(targets: dict[str, tuple[float, ...]]) -> str:
    rows = []
    for group in JOINT_GROUPS:
        if group.key not in targets:
            continue
        design = CONTINUOUS_TARGETS.get(group.key, ())
        for position, value in enumerate(targets[group.key]):
            written = f"{design[position]:.1f}" if position < len(design) else "-"
            rows.append([_drive_label(group, position), f"{value:.1f}", written])
    return "\n".join(
        [
            "## 6. 写进设计的",
            "",
            "每个驱动器要一直出的力矩：一轮家务里最费力的 "
            f"{SIZING_WINDOW_S / 60:.0f} 分钟的均方根（液冷的驱动器身子约 5 分钟热透），和一直保持那两个姿势要的，"
            f'取大的，再 x {CONTINUOUS_MARGIN}（夏天屋里热、一轮做完接着做）；左右取大的，"随体重"的按 70 kg 折算。'
            '"这一遍算的"和"设计里的"（`design.CONTINUOUS_TARGETS`）差得多，就把新的写进去再算一遍：换了驱动器，体重也变。',
            "",
            *_table(["驱动器", "这一遍算的（N·m）", "设计里的（N·m）"], rows),
        ]
    )


def _closure_section() -> str:
    rows = []
    for variant in (CORE_BODY, FULL_BODY):
        best = close_mass(variant, Assumptions(), best_today_model())
        careful = close_mass(variant, Assumptions(), conservative_model())
        rows.append([variant.name, f"{best.total_kg:.1f}", f"{careful.total_kg:.1f}"])
    heights = [
        [f"{height:.2f} m", f"{close_mass(CORE_BODY, Assumptions(height_m=height), best_today_model()).total_kg:.1f}"]
        for height in HEIGHTS_M
    ]
    return "\n".join(
        [
            "## 8. 质量闭环（按新的驱动器）",
            "",
            *_table(["身体", "今天最好的驱动（kg）", "保守的驱动（kg）"], rows),
            "",
            '**换身高**："随体重"的力矩按"体重 x 身高"放大（同样的姿势，各段长了，力臂也长），皮肤和外衣按表面积变。'
            "以前体重不随身高变（1.2 步的报告里记的问题），现在：",
            "",
            *_table(["身高", "核心版（kg）"], heights),
        ]
    )


def _pelvis_section(nova: NovaModel) -> str:
    fit = pelvis_fit(nova.budget, nova.dimensions)
    rows = [
        [
            content.name,
            f"{content.count}",
            "-" if content.diameter_m is None else f"{content.diameter_m * MM_PER_M:.0f}",
            f"{content.volume_m3 * LITRES_PER_M3:.2f}",
        ]
        for content in fit.contents
    ]
    depth, width, height = (side * MM_PER_M for side in fit.box_m)
    verdict = "**放得下**" if fit.fits else "**放不下**"
    supercapacitor = Assumptions().supercapacitor_kg / PART_STYLES[PartKind.FALLBACK].density
    with_supercapacitor = (fit.used_m3 + supercapacitor) / fit.box_volume_m3
    return "\n".join(
        [
            "## 9. 骨盆里放得下吗",
            "",
            "按驱动器的重量估它有多大（RobStride 的五个关节电机拟合：直径 ∝ 重量^"
            f"{DIAMETER_FIT[1]:.2f}、长度 ∝ 重量^{LENGTH_FIT[1]:.2f}），电机当圆柱；别的东西按密度算体积。"
            "腰的推杆跨在腰的关节上，一半算在胸里。粗算，不排位置。",
            "",
            *_table(["骨盆里的", "几个", "直径（mm）", "一共（升）"], rows),
            "",
            f"骨盆约 {depth:.0f} x {width:.0f} x {height:.0f} mm（前后、左右、上下），"
            f"{fit.box_volume_m3 * LITRES_PER_M3:.1f} 升；里面的东西 {fit.used_m3 * LITRES_PER_M3:.1f} 升，"
            f"占 {_percent(fit.share)}。圆柱之间、线、冷却液的管、骨架要留空，按能用 {_percent(USABLE_SHARE)} 算；"
            f"最粗的电机 {fit.widest_m * MM_PER_M:.0f} mm，"
            f"骨盆最窄的那一边 {min(fit.box_m) * MM_PER_M:.0f} mm。{verdict}。"
            f"超级电容原来也在骨盆里，那样要占 {with_supercapacitor:.1%}（能用的按 {_percent(USABLE_SHARE)} 算），"
            f"{_room_left(USABLE_SHARE - with_supercapacitor)}，所以挪到了腹部（电池下面）。真的排位置要等结构设计。",
        ]
    )


def _room_left(margin: float) -> str:
    """还剩多少余地，说成一句话（不到 2% 就算没有余地）。"""
    return "一点余地都没有" if margin < ROOM_MARGIN else f"只剩 {_percent(margin)} 的余地"


def _limits_section() -> str:
    return "\n".join(
        [
            "## 10. 还没算的",
            "",
            "- 手里的 36 个小电机：手的重量按估的定，热也没算（拿的都是轻东西）。",
            "- 驱动板、电池、线上的损耗：只算了电机的铜损。电机转起来的铁损算在摩擦里。",
            "- 散热器、水泵、冷却液的温度怎么随负载变：冷却液一直按 40 °C 算。",
            "- 力矩和转速的关系、发热以后降额、命令的延迟：这里只是选驱动器和算热；"
            "仿真里让驱动器真的照这样出力，在 1.6 步的下一部分做。",
        ]
    )


# 小的帮手 -------------------------------------------------------------------------------------------


def _arms_enclosed_sentence(hold: HoldHeat) -> str:
    """肩前后和肘不液冷时，端着箱子站着多久开始降额（左侧）。"""
    found = [
        f"{item.motor.label.removeprefix(SIDE_PREFIXES[0])} {item.derate_after_s / 60:.1f} 分钟"
        for item in hold.motors
        if item.motor.group in ARM_GROUPS_COOLED
        and item.motor.label.startswith(SIDE_PREFIXES[0])
        and item.derate_after_s is not None
    ]
    if not found:
        return "不液冷也不会降额。"
    return f"不液冷的话，{hold.hold.name}，{'、'.join(found)}就开始降额。"


def _groups_by_heat(budget: MassBudget) -> list[str]:
    groups = {group.key: group for group in JOINT_GROUPS}
    return [groups[key].name for key, drives in budget.drives.items() if any(drive.sized_by_heat for drive in drives)]


def _loss_by_cooling(round_heat: RoundHeat) -> tuple[float, float]:
    liquid = sum(item.mean_loss_w for item in round_heat.motors if item.motor.drive.cooling is Cooling.LIQUID)
    return liquid, round_heat.mean_loss_w - liquid


def _electric_power_w(motors: Sequence[Motor], demand: MotionDemand) -> np.ndarray:
    """每一帧全身的驱动器一共要的电功率：机械功率 + 铜损。"""
    series = demand.series
    total = np.zeros(len(series.torques_nm))
    for motor in motors:
        drive = motor.drive
        speeds = motor.speeds_rad_s(series.speeds_rad_s)
        torques = (
            motor.torques_nm(series.torques_nm) + np.sign(speeds) * drive.friction_nm + drive.viscous_nm_s * speeds
        )
        loss = (torques / drive.km_nm_per_sqrt_w) ** 2 * hot_resistance_factor(POWER_WINDING_C)
        total += torques * speeds + loss
    return total


def _phase_currents(budget: MassBudget) -> list[tuple[str, tuple[float, ...]]]:
    """每个驱动板（一侧）出峰值力矩时的相电流，按几档母线电压，从大到小排。双绕组的两个板各出一半。"""
    found = []
    for group in CORE_BODY.joint_groups():
        boards = DUAL_WINDING_BOARDS if group.dual_winding else 1
        for position, drive in enumerate(budget.drives.get(group.key, ())):
            found.append((_drive_label(group, position), _currents(drive, boards)))
    return sorted(found, key=lambda item: -item[1][0])


def _currents(drive: DriveSpec, boards: int) -> tuple[float, ...]:
    return tuple(
        drive.peak_torque_nm / (KT_TIMES_NO_LOAD * volts / REFERENCE_BUS_V / drive.no_load_speed_rad_s) / boards
        for volts in BUS_VOLTAGES_V
    )


def _drive_label(group: JointGroup, position: int) -> str:
    if group.parallel:
        return f"{group.name}（并联{'甲乙'[position]}）"
    if group.actuators > 1:
        return f"{group.name}（第 {position + 1} 个）"
    return group.name


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _percent(share: float) -> str:
    return f"{share * PERCENT:.0f}%"


def main(argv: list[str] | None = None) -> int:
    """命令行入口：算一遍，写报告，打印结论。"""
    parser = argparse.ArgumentParser(description="选 Nova 的驱动器、算一轮家务的热，写一份报告。")
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
