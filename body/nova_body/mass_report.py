"""质量闭环的报告：算几种身体、几种假设，写成一份中文的 Markdown。

用法：python -m nova_body.mass_report [--output 路径]
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from nova_body.actuator_mass import QDD_SAMPLES, ActuatorMassModel, best_today_model, conservative_model
from nova_body.anthropometry import SEGMENT_NAMES, Segment, human_segment_mass_kg
from nova_body.design import CORE_BODY, FULL_BODY, HAND_ALL_TENDON, BodyVariant, Strength
from nova_body.mass_closure import ActuatorLine, Assumptions, MassBudget, MassClosureError, close_mass

DEFAULT_OUTPUT = Path("/docs/报告/质量闭环.md")
LIGHT_HOME_STRENGTH = 0.5
LARGE_BATTERY_KWH = 2.3
HEAVY_STRUCTURE_FRACTION = 0.25
PERCENT = 100.0
NOT_CLOSED = "闭不上"


def build_report() -> str:
    """算全部的情况，返回报告的全文。"""
    base = Assumptions()
    best = best_today_model()
    conservative = conservative_model()
    core_best = close_mass(CORE_BODY, base, best)
    full_best = close_mass(FULL_BODY, base, best)
    sections = [
        _header(),
        _summary_section(base, (best, conservative)),
        _what_if_section(core_best, base, best),
        _detail_section("3. 核心版的明细（今天最好的驱动）", core_best),
        _detail_section("4. 完整版的明细（今天最好的驱动）", full_best),
        _assumptions_section(base),
        _samples_section((best, conservative)),
        _limits_section(),
    ]
    return "\n\n".join(sections) + "\n"


def _header() -> str:
    return "\n".join(
        [
            "# 质量闭环的结果",
            "",
            "**这份报告是程序算出来的，不要手改。** 要改就改 `body/nova_body` 里的假设，再运行：",
            "",
            "```bash",
            "docker compose run --rm body python -m nova_body.mass_report",
            "```",
            "",
            "质量闭环是什么：腿和躯干要出的力矩跟着体重变。身体重了，腿的驱动器就要更大、更重，身体又更重。",
            "把这个循环算到不再变，得到的就是体重。",
        ]
    )


def _summary_section(base: Assumptions, models: tuple[ActuatorMassModel, ...]) -> str:
    rows = ["## 1. 结论", "", "| 身体 | 自由度 | 驱动的假设 | 体重 | 多带 1 kg，总重加多少 |", "|---|---|---|---|---|"]
    for variant in (CORE_BODY, FULL_BODY):
        for model in models:
            outcome = _try_close(variant, base, model)
            if outcome is None:
                rows.append(f"| {variant.name} | {variant.total_dof()} | {model.name} | {NOT_CLOSED} | - |")
            else:
                rows.append(
                    f"| {variant.name} | {variant.total_dof()} | {model.name} "
                    f"| **{outcome.total_kg:.0f} kg** | {outcome.growth_per_added_kg:.2f} kg |"
                )
    rows += [
        "",
        "- **今天最好的驱动**：按 8 个真实产品的数拟合，包括每公斤力矩最大的那个（Unitree M107，厂商的数）。",
        "- **保守的驱动**：去掉最好的那个再拟合。",
        "- 两个都是按**峰值**力矩算的。真实的体重大概在两者之间。",
    ]
    return "\n".join(rows)


def _what_if_section(baseline: MassBudget, base: Assumptions, model: ActuatorMassModel) -> str:
    all_tendon = replace(CORE_BODY, name="核心版 + 全肌腱的手", hand=HAND_ALL_TENDON)
    cases: tuple[tuple[str, BodyVariant, Assumptions], ...] = (
        ("不要液冷", CORE_BODY, replace(base, liquid_cooling=False)),
        ("不要保底的东西（双绕组、超级电容、制动器、安全板）", CORE_BODY, replace(base, fallbacks=False)),
        (
            f"电池从 {base.battery_kwh:g} kWh 加到 {LARGE_BATTERY_KWH:g} kWh",
            CORE_BODY,
            replace(base, battery_kwh=LARGE_BATTERY_KWH),
        ),
        ("手换成全肌腱的（A）", all_tendon, base),
        (
            f"骨架占总重的 {HEAVY_STRUCTURE_FRACTION:.0%}（基准是 {base.structure_fraction:.0%}）",
            CORE_BODY,
            replace(base, structure_fraction=HEAVY_STRUCTURE_FRACTION),
        ),
        ("驱动器按人的峰值（初估）定，不按动作算的", CORE_BODY, replace(base, strength=Strength.HUMAN_PEAK)),
        ("力量减半（轻的家用身体）", CORE_BODY, replace(base, strength_factor=LIGHT_HOME_STRENGTH)),
        (f"完整版（{FULL_BODY.total_dof()} 个自由度，全肌腱的手）", FULL_BODY, base),
    )
    rows = [
        "## 2. 每样东西加多少重量",
        "",
        f"基准：核心版、{model.name}，**{baseline.total_kg:.1f} kg**。",
        "",
        "| 改动 | 体重 | 和基准差 |",
        "|---|---|---|",
    ]
    for label, variant, assumptions in cases:
        outcome = _try_close(variant, assumptions, model)
        if outcome is None:
            rows.append(f"| {label} | {NOT_CLOSED} | - |")
        else:
            rows.append(f"| {label} | {outcome.total_kg:.1f} kg | {outcome.total_kg - baseline.total_kg:+.1f} kg |")
    return "\n".join(rows)


def _detail_section(title: str, budget: MassBudget) -> str:
    rows = [
        f"## {title}",
        "",
        f"体重 **{budget.total_kg:.1f} kg**；迭代 {budget.iterations} 次收敛；"
        f"多带 1 kg，总重加 {budget.growth_per_added_kg:.2f} kg。",
        "",
        "### 各部分",
        "",
        "| 部分 | 重量 | 占比 |",
        "|---|---|---|",
    ]
    for category, mass in sorted(budget.by_category.items(), key=lambda item: item[1], reverse=True):
        if mass > 0:
            rows.append(f"| {category} | {mass:.1f} kg | {mass / budget.total_kg * PERCENT:.0f}% |")
    rows += [
        "",
        "### 各段和人比（一侧的重量）",
        "",
        "| 段 | Nova | 同样体重的人 | 是人的几倍 |",
        "|---|---|---|---|",
    ]
    for segment in Segment:
        human = human_segment_mass_kg(segment, budget.total_kg)
        nova = budget.by_segment[segment]
        rows.append(f"| {SEGMENT_NAMES[segment]} | {nova:.1f} kg | {human:.1f} kg | {nova / human:.1f} |")
    rows += [
        "",
        "### 驱动器（不含手）",
        "",
        '"要一直出的"是一轮家务里要一直出的力矩（[驱动器的报告](驱动器.md)）；重量取峰值和发热里要求大的那个。',
        "",
        "| 关节 | 个数 | 每个的峰值力矩 | 要一直出的 | 冷却 | 每个多重 | 一共 | 备注 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for line in sorted(budget.actuators, key=lambda item: item.total_kg, reverse=True):
        rows.append(
            f"| {line.name} | {line.count} | {_torque(line.torque_nm)} | "
            f"{_torque(None if line.drive is None else line.drive.required_continuous_nm)} | "
            f"{'-' if line.drive is None else line.drive.cooling.value} | "
            f"{line.mass_each_kg:.2f} kg | {line.total_kg:.1f} kg | {_actuator_note(line)} |"
        )
    return "\n".join(rows)


def _torque(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f} N·m"


def _actuator_note(line: ActuatorLine) -> str:
    """这一行驱动器的备注：重量怎么来的。"""
    if line.drive is None:
        return "按固定的重量估的"
    notes = []
    if line.drive.sized_by_heat:
        notes.append("按发热选的（要一直出的力大）")
    if line.beyond_data:
        notes.append("峰值超出了样本的范围，是外推的")
    return "；".join(notes)


def _assumptions_section(base: Assumptions) -> str:
    cooling = f"{base.liquid_cooling_kg:g} kg" if base.liquid_cooling else "不要"
    items = [
        ("身高", f"{base.height_m:g} m"),
        ("驱动器的力量", f"{base.strength.value}；动作没算出目标的关节（颈、肩转、前臂转、腕）用人的峰值"),
        (
            "规格里的力矩对应的体重和身高",
            f'{base.reference_body_mass_kg:g} kg、{base.reference_height_m:g} m；腿和躯干的力矩按"体重 x 身高"放大',
        ),
        (
            "驱动器怎么选",
            "峰值力矩和一直要出的力矩（发热）里要求大的那个；怎么冷却按机体规格第 12 节（见驱动器的报告）",
        ),
        ("骨架", f"占总重的 {base.structure_fraction:.0%}"),
        ("线", f"占总重的 {base.wiring_fraction:.0%}"),
        ("电池", f"{base.battery_kwh:g} kWh，每公斤 {base.battery_wh_per_kg:g} Wh（高倍率的电池包）"),
        ("电脑", f"{base.computer_kg:g} kg"),
        ("液冷（泵、散热器、冷却液、管）", cooling),
        ("皮肤、软外壳、外衣", f"{base.skin_and_cover_kg:g} kg（身高 {base.reference_height_m:g} m 时；按身高²变）"),
        ("传感器（相机、麦克风等）", f"{base.sensors_kg:g} kg"),
        ("脚里的东西（踝的六轴力传感器、脚底的压力皮肤、脚板）", f"每只脚 {base.foot_hardware_kg:g} kg"),
        ("超级电容", f"{base.supercapacitor_kg:g} kg"),
        ("制动器", f"膝和髋共 4 个，每个 {base.brake_kg:g} kg"),
        ("安全控制板", f"{base.safety_board_kg:g} kg"),
        ("双绕组的电机", f"比单绕组重 {base.dual_winding_overhead:.0%}"),
        ("手臂", f"水平伸直、手里端 {base.arm_payload_kg:g} kg，再乘 {base.arm_dynamic_factor:g} 倍；和规格值取大的"),
        ("推杆（腰椎、胸椎）", "按出同样力矩的旋转驱动器的重量算"),
    ]
    rows = ["## 5. 用的假设", "", "| 项目 | 取值 |", "|---|---|"]
    rows += [f"| {label} | {value} |" for label, value in items]
    return "\n".join(rows)


def _samples_section(models: tuple[ActuatorMassModel, ...]) -> str:
    rows = [
        "## 6. 驱动器的数据",
        "",
        "都是厂商或经销商公布的峰值力矩，没有独立测过。",
        "",
        "| 驱动器 | 峰值力矩 | 重量 | 每公斤的力矩 | 来源 |",
        "|---|---|---|---|---|",
    ]
    for sample in QDD_SAMPLES:
        density = sample.peak_torque_nm / sample.mass_kg
        rows.append(
            f"| {sample.name} | {sample.peak_torque_nm:g} N·m | {sample.mass_kg:g} kg "
            f"| {density:.0f} N·m/kg | [链接]({sample.source}) |"
        )
    rows += ["", "拟合出来的两条线（质量 = 系数 × 力矩^指数）：", "", "| 名字 | 系数 | 指数 |", "|---|---|---|"]
    rows += [f"| {model.name} | {model.coefficient:.4f} | {model.exponent:.3f} |" for model in models]
    return "\n".join(rows)


def _limits_section() -> str:
    return "\n".join(
        [
            "## 7. 这个模型还不知道的",
            "",
            "- **驱动器**：按峰值和发热选（[驱动器的报告](驱动器.md)）。"
            "电机常数、每公斤能散多少热来自公开的产品数和一篇论文，"
            "没有实测；转速只改绕组和电流，不改重量。",
            "- **推杆**：没有核实过的重量数据，先按旋转驱动器算。",
            "- **手**：三种手的重量都是估的。",
            "- **骨架**：按总重的固定比例算，没有按受力算。",
            "- **肩胛**：推杆要多大的力还没测，按每个 0.3 kg 估。",
        ]
    )


def _try_close(variant: BodyVariant, assumptions: Assumptions, model: ActuatorMassModel) -> MassBudget | None:
    """闭得上就返回结果，闭不上返回 None（报告里写"闭不上"）。"""
    try:
        return close_mass(variant, assumptions, model)
    except MassClosureError:
        return None


def main(argv: list[str] | None = None) -> int:
    """命令行入口：算一遍，写报告，打印结论。"""
    parser = argparse.ArgumentParser(description="算 Nova 的质量闭环，写一份报告。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="报告写到哪里")
    arguments = parser.parse_args(argv)
    report = build_report()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report, encoding="utf-8")
    summary_end = report.index("## 2.")
    print(report[report.index("## 1.") : summary_end].strip())
    print(f"\n报告写到了 {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
