"""身体模型的报告：生成模型，在仿真里站一站，写成一份中文的 Markdown 和一张图。

用法：python -m nova_body.model_report [--output 路径]
图和报告放在一起，名字一样，后缀是 .svg。
"""

import argparse
import math
import sys
from pathlib import Path

from nova_body.anthropometry import SEGMENT_NAMES, Segment, segment_length_m
from nova_body.bench import DAMPING_TIME_S, FULL_TORQUE_ERROR_RAD, TIMESTEP_S
from nova_body.body import Side
from nova_body.drawing import draw_body
from nova_body.hand import hand_joints
from nova_body.mass_closure import GRAVITY_M_S2
from nova_body.model import ModelJoint, NovaModel, build_nova, part_legend
from nova_body.skeleton import LINKS
from nova_body.standing import (
    MAX_END_SPEED_RAD_S,
    MAX_FOOT_SLIP_M,
    MAX_PELVIS_DROP_M,
    MAX_TILT_DEG,
    STAND_SECONDS,
    Push,
    StandingResult,
    simulate_standing,
    stood_well,
)

DEFAULT_OUTPUT = Path("/docs/报告/身体模型.md")
PUSH_SECONDS = 5.0
GENTLE_PUSH_N = 30.0
HARD_PUSH_N = 300.0
LIMP_SECONDS = 3.0
HOLDING_ROWS = 6
MM_PER_M = 1000.0
CM_PER_M = 100.0

PUSH_DIRECTIONS: tuple[tuple[str, tuple[float, float, float]], ...] = (
    ("往前", (1.0, 0.0, 0.0)),
    ("往后", (-1.0, 0.0, 0.0)),
    ("往左", (0.0, 1.0, 0.0)),
    ("往右", (0.0, -1.0, 0.0)),
)


def build_report(nova: NovaModel | None = None) -> str:
    """生成模型、做完全部的仿真，返回报告的全文。"""
    nova = nova or build_nova()
    standing = simulate_standing(nova.body)
    sections = [
        _header(),
        _summary_section(nova, standing),
        _pose_section(nova),
        _standing_section(nova, standing),
        _segments_section(nova),
        _joints_section(nova),
        _sensors_section(nova),
        _limits_section(),
    ]
    return "\n\n".join(sections) + "\n"


def _header() -> str:
    return "\n".join(
        [
            "# 身体的模型（核心版）",
            "",
            "**这份报告和图是程序生成的，不要手改。** 要改就改 `body/nova_body` 里的数据，再运行：",
            "",
            "```bash",
            "docker compose run --rm body python -m nova_body.model_report",
            "```",
            "",
            "![Nova 的身体：正面和侧面。外壳是半透明的，能看到里面的驱动器、电池和电脑](身体模型.svg)",
        ]
    )


def _summary_section(nova: NovaModel, standing: StandingResult) -> str:
    model = nova.model
    hand_total = len(hand_joints())
    hand_driven = sum(1 for joint in hand_joints() if joint.peak_torque_nm is not None)
    body_driven = len(nova.body.actuators) - len(Side) * hand_driven
    hands_total = len(Side) * hand_total
    verdict = "站住了" if stood_well(standing) else "**没有站好**"
    rows = [
        "## 1. 结论",
        "",
        "| 项目 | 结果 |",
        "|---|---|",
        f"| 自由度 | {len(nova.joints)}（两只手 {hands_total}，身体 {len(nova.joints) - hands_total}） |",
        f"| 驱动器 | {len(nova.body.actuators)}（身体 {body_driven}，每只手 {hand_driven}；"
        f"每只手有 {hand_total - hand_driven} 个远指间跟着近指间动） |",
        f"| 身高 | {nova.dimensions.height:.2f} m |",
        f"| 模型的总质量 | {nova.body.mass_kg:.2f} kg（质量闭环算的是 {nova.budget.total_kg:.2f} kg） |",
        f"| 传感器 | {model.nsensor} 个，一共 {model.nsensordata} 个数；相机 {model.ncam} 台（还没有画面） |",
        f"| 用关节控制站 {STAND_SECONDS:g} 秒 | {verdict}：最多歪 {standing.max_tilt_deg:.2f}°，"
        f"骨盆低了 {standing.pelvis_drop_m * MM_PER_M:.1f} mm |",
        f"| 仿真的步长 | {TIMESTEP_S * MM_PER_M:g} 毫秒（每秒 {1 / TIMESTEP_S:.0f} 步） |",
        "",
        "仿真比实时快多少，每次运行不一样，所以不写在这里；量出来的数记在 [P1 计划](../P1计划.md)。",
    ]
    return "\n".join(rows)


def _pose_section(nova: NovaModel) -> str:
    stand = nova.stand
    ratio = stand.center_of_mass_height_m / nova.dimensions.height
    rows = [
        "## 2. 站姿",
        "",
        "膝微弯；髋和踝配合着让躯干竖直、脚底贴地；踝的角度是算出来的，让重心正好在两只脚的正中间上面。",
        "",
        "| 项目 | 值 |",
        "|---|---|",
        f"| 膝 | 弯 {stand.knee_deg:.1f}° |",
        f"| 踝 | 脚尖向上 {stand.ankle_deg:.1f}° |",
        f"| 髋 | 向前抬 {stand.hip_deg:.1f}° |",
        f"| 骨盆（髋关节）的高度 | {stand.pelvis_height_m:.3f} m |",
        f"| 重心的高度 | {stand.center_of_mass_height_m:.3f} m（身高的 {ratio:.2f}；人约 0.55~0.57） |",
        "",
        "驱动器的目标里带着顶住重力要的力矩，所以站姿正好是平衡的位置，身体不会往下沉。",
        f"站着时最费力的 {HOLDING_ROWS} 个驱动器（左右一样的只列左侧；并联的一对是两个驱动器一起带两个关节）：",
        "",
        "| 驱动器 | 出的力 | 是峰值的 |",
        "|---|---|---|",
    ]
    holding = [
        (abs(force) / actuator.peak_torque_nm, actuator, force)
        for actuator, force in zip(nova.body.actuators, stand.holding_torque_nm, strict=True)
        if not actuator.label.startswith("右 ")
    ]
    for share, actuator, force in sorted(holding, key=lambda row: abs(row[2]), reverse=True)[:HOLDING_ROWS]:
        rows.append(f"| {actuator.label.removeprefix('左 ')} | {abs(force):.1f} N·m | {share:.1%} |")
    return "\n".join(rows)


def _standing_section(nova: NovaModel, standing: StandingResult) -> str:
    support = standing.support_force_n / GRAVITY_M_S2
    rows = [
        f"## 3. 站 {STAND_SECONDS:g} 秒",
        "",
        "每个关节的驱动器顶在站姿的角度上（位置控制），没有平衡的控制。",
        "",
        "| 项目 | 结果 | 合格线 |",
        "|---|---|---|",
        f"| 倒了没有 | {'倒了' if standing.fell else '没倒'} | 不倒 |",
        f"| 骨盆最多歪了 | {standing.max_tilt_deg:.2f}° | < {MAX_TILT_DEG:g}° |",
        f"| 骨盆最多低了 | {standing.pelvis_drop_m * MM_PER_M:.1f} mm | < {MAX_PELVIS_DROP_M * MM_PER_M:g} mm |",
        f"| 脚滑了 | {standing.foot_slip_m * MM_PER_M:.2f} mm | < {MAX_FOOT_SLIP_M * MM_PER_M:g} mm |",
        f"| 最后关节的速度 | {standing.end_joint_speed_rad_s:.4f} rad/s | < {MAX_END_SPEED_RAD_S:g} rad/s |",
        f"| 地面托着的重量 | {support:.2f} kg | 等于体重 {standing.weight_n / GRAVITY_M_S2:.2f} kg |",
        f"| 压力中心 | 在脚跟前面 {standing.pressure_center_from_heel_m * CM_PER_M:.1f} cm"
        f"（脚长 {standing.foot_length_m * CM_PER_M:.1f} cm） | 在脚底里面 |",
        "",
        "对照：",
        "",
        "| 情况 | 结果 |",
        "|---|---|",
        _limp_row(nova),
        *(_push_row(nova, GENTLE_PUSH_N, label, direction) for label, direction in PUSH_DIRECTIONS),
        _push_row(nova, HARD_PUSH_N, *PUSH_DIRECTIONS[0]),
        "",
        "不给控制马上就倒，说明是关节的控制让它站住的。用力推会倒，因为现在只是关节顶着；"
        "被推了还能站住，要靠小脑层的平衡控制，是下一阶段（P2）的事。",
    ]
    return "\n".join(rows)


def _limp_row(nova: NovaModel) -> str:
    limp = simulate_standing(nova.body, LIMP_SECONDS, controlled=False)
    outcome = f"{limp.seconds:.2f} 秒后倒了" if limp.fell else f"{LIMP_SECONDS:g} 秒里没倒"
    return f"| 驱动器不出力 | {outcome} |"


def _push_row(nova: NovaModel, force_n: float, label: str, direction: tuple[float, float, float]) -> str:
    push = Push(tuple(force_n * axis for axis in direction))
    result = simulate_standing(nova.body, PUSH_SECONDS, push)
    outcome = "倒了" if result.fell else f"没倒，最多歪 {result.max_tilt_deg:.1f}°"
    return f"| 在胸上{label}推 {force_n:g} N、{push.duration_s:g} 秒 | {outcome} |"


def _segments_section(nova: NovaModel) -> str:
    budget = nova.budget
    rows = [
        "## 4. 各段的长度和质量",
        "",
        "质量是一侧的。每一段 = 这一段里的驱动器和别的东西 + 分到这一段的骨架、线和皮肤。",
        "",
        "| 段 | 长度 | 质量 | 驱动器和别的东西 | 骨架、线、皮肤 |",
        "|---|---|---|---|---|",
    ]
    for segment in Segment:
        length = segment_length_m(segment, nova.dimensions.height)
        total = budget.by_segment[segment]
        spread = budget.spread_on_kg(segment)
        rows.append(
            f"| {SEGMENT_NAMES[segment]} | {length:.3f} m | {total:.2f} kg | {total - spread:.2f} kg "
            f"| {spread:.2f} kg |"
        )
    rows += ["", "脚的长度是踝的高度；头和颈的长度是从肩到头顶。"]
    return "\n".join(rows)


def _joints_section(nova: NovaModel) -> str:
    rows = [
        "## 5. 关节",
        "",
        "左右两侧一样，下面只列中间的和左侧的。右侧是镜像，同一个正方向是同一个动作。",
        f"刚度：关节偏了 {FULL_TORQUE_ERROR_RAD:g} 弧度（约 {math.degrees(FULL_TORQUE_ERROR_RAD):.0f}°），"
        f"驱动器就出全力；阻尼 = 刚度 x {DAMPING_TIME_S:g} 秒。这是现在站着用的值，以后由脊髓层在运行时调。",
        "",
        "| 段 | 关节 | 范围 | 往正方向转是 | 峰值力矩 | 刚度 |",
        "|---|---|---|---|---|---|",
    ]
    shown = [joint for joint in nova.joints if joint.side is not Side.RIGHT]
    hand_keys = {joint.key for joint in hand_joints()}
    link_of = {joint.key: part.name for part in LINKS for joint in part.joints}
    rows += [_joint_row(joint, link_of.get(joint.key, "手")) for joint in shown if joint.key not in hand_keys]
    rows += [_joint_row(joint, "手") for joint in shown if joint.key in hand_keys]
    rows += [
        "",
        "手用的是「驱动放在手里」的做法（B）。手的关节位置和力矩是估的，做到手和动作脑（P4）时再核对。",
    ]
    return "\n".join(rows)


def _joint_row(joint: ModelJoint, link_name: str) -> str:
    span = f"{math.degrees(joint.lower_rad):.0f}° ~ {math.degrees(joint.upper_rad):.0f}°"
    name = joint.label.removeprefix("左 ")
    if joint.peak_torque_nm is None:
        return f"| {link_name} | {name} | {span} | {joint.positive} | 跟着近指间动 | - |"
    return (
        f"| {link_name} | {name} | {span} | {joint.positive} | {joint.peak_torque_nm:.1f} N·m "
        f"| {joint.stiffness:.0f} N·m/rad |"
    )


def _sensors_section(nova: NovaModel) -> str:
    joints = len(nova.joints)
    driven = len(nova.actuated_joints)
    fingertips = len(Side) * sum(1 for joint in hand_joints() if joint.key.endswith(("_dip", "_ip")))
    contact_bodies = sum(len(Side) if part.paired else 1 for part in LINKS)
    rows = [
        "## 6. 传感器",
        "",
        "只有核心的（[核心和待证明](../核心和待证明.md)第 4 节）。读数现在是理想的：没有噪声、延迟和误差，"
        "做传感器的模型（1.6）时再加。",
        "",
        "| 传感器 | 数量 | 说明 |",
        "|---|---|---|",
        f"| 关节的位置、速度 | 各 {joints} | 每个关节 |",
        f"| 驱动器出的力矩 | {driven} | 代表电机的电流 |",
        "| IMU | 2 | 骨盆、头；各有加速度和角速度 |",
        "| 踝部六轴力 | 2 | 每只脚的合力和力矩；能算出压力中心 |",
        "| 腕部六轴力 | 2 | 每只手的合力和力矩 |",
        f"| 指尖的力 | {fingertips} | 每个指尖受到的接触力的合力（三个方向） |",
        f"| 全身的接触 | {contact_bodies} | 每段身体受到的接触力的合力；手算一整段 |",
        f"| 相机 | {nova.model.ncam} | 眼 2、手掌 2、胸前看脚下的深度 1；位置和朝向定了，画面到「看得见」（1.4）再做 |",
    ]
    return "\n".join(rows)


def _limits_section() -> str:
    return "\n".join(
        [
            "## 7. 这个模型还没有的",
            "",
            "- **连杆和推杆**：膝、踝、腕的连杆，腰椎的推杆都没有建，关节直接由一个驱动器带动。",
            "- **驱动器的模型**：摩擦、力矩-速度、发热、转子的惯量都还是粗估的（1.6 做）。",
            "- **各段的形状**：是胶囊和盒子；身体的各段之间不算碰撞，只算和地面的碰撞。",
            "- **东西的位置**：电机、电池、电脑是按机体规格第 6 节粗放的，没有做过结构设计。",
            "- **手**：手掌拢起来只建了一个关节（真手是无名指和小指两根掌骨）；拇指的转轴是简化的。",
            "- **触觉皮肤的阵列、麦克风、嗅觉**：都还没有。",
            "- **地面**：只是一块平地，摩擦用的是默认值。",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    """命令行入口：生成模型，写报告和图，打印结论。"""
    parser = argparse.ArgumentParser(description="生成 Nova 的身体模型，站一站，写一份报告。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="报告写到哪里")
    arguments = parser.parse_args(argv)
    nova = build_nova()
    report = build_report(nova)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report, encoding="utf-8", newline="\n")
    picture = arguments.output.with_suffix(".svg")
    picture.write_text(draw_body(nova.body, legend=part_legend()), encoding="utf-8", newline="\n")
    print(report[report.index("## 1.") : report.index("## 2.")].strip())
    print(f"\n报告写到了 {arguments.output}，图写到了 {picture}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
