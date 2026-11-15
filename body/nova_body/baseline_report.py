"""基线的报告：把现成的 Unitree G1 和 Nova 放上同一个测试台，一条一条地比，写成中文的 Markdown 和一张图。

用法：python -m nova_body.baseline_report [--output 路径]
图和报告放在一起，名字一样，后缀是 .svg：两个身体按同一个比例并排站着。
"""

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

from nova_body.baseline import (
    OFFICIAL_HEIGHT_M,
    OFFICIAL_MASS_KG,
    PUBLISHED_FOOT_FRICTION,
    PUBLISHED_STIFFNESS,
    g1_manifest,
    load_g1,
)
from nova_body.bench import DAMPING_TIME_S, FULL_TORQUE_ERROR_RAD, TIMESTEP_S, stiffness_for
from nova_body.body import Body, DrivenJoint
from nova_body.drawing import draw_lineup
from nova_body.mass_closure import GRAVITY_M_S2
from nova_body.model import build_nova
from nova_body.posture import KNEE_BEND_DEG, deepest_knee_bend_deg, toe_up_limit_deg
from nova_body.standing import (
    MAX_END_SPEED_RAD_S,
    MAX_FOOT_SLIP_M,
    MAX_PELVIS_DROP_M,
    MAX_TILT_DEG,
    STAND_SECONDS,
    Push,
    StandingResult,
    push_until_it_falls,
    simulate_standing,
    stood_well,
)
from nova_body.third_party import BYTES_PER_MB, FETCH_COMMAND, Manifest

DEFAULT_OUTPUT = Path("/docs/报告/基线身体.md")
LIMP_SECONDS = 3.0
HOLDING_ROWS = 4
MM_PER_M = 1000.0
CM_PER_M = 100.0
FREE_JOINT_DOF = 6
SHORT_COMMIT = 12
# 推力从体重的 2% 起，每档加 2%，推到倒了为止。
PUSH_SHARES: tuple[float, ...] = tuple(step / 50 for step in range(1, 11))
FORWARD, SIDEWAYS = "往前", "往侧面"
PUSH_DIRECTIONS: dict[str, tuple[float, float, float]] = {FORWARD: (1.0, 0.0, 0.0), SIDEWAYS: (0.0, 1.0, 0.0)}
LEFT_PREFIX = "左 "
RIGHT_PREFIX = "右 "


@dataclass(frozen=True)
class Measured:
    """一个身体在测试台上量出来的全部结果。

    pushes：每个方向一档一档推的结果，推到倒了为止。
    toe_up_limit_deg：踝最多能让脚尖向上多少；deepest_knee_bend_deg：躯干竖直时膝最多能弯到多少还站得住。
    """

    body: Body
    standing: StandingResult
    limp: StandingResult
    pushes: dict[str, list[tuple[float, StandingResult]]]
    toe_up_limit_deg: float
    deepest_knee_bend_deg: float

    @property
    def passed(self) -> bool:
        """同一套测试过没过：站得合格，而且不给控制会倒。"""
        return stood_well(self.standing) and self.limp.fell

    def strongest_push_survived(self, direction: str) -> float | None:
        """这个方向上没倒的最大的一档（体重的几分之几）。一档都没扛住就是 None。"""
        survived = [share for share, result in self.pushes[direction] if not result.fell]
        return max(survived) if survived else None


def measure(body: Body) -> Measured:
    """把一个身体在测试台上该量的都量一遍。"""
    return Measured(
        body=body,
        standing=simulate_standing(body),
        limp=simulate_standing(body, LIMP_SECONDS, controlled=False),
        pushes={label: push_until_it_falls(body, axis, PUSH_SHARES) for label, axis in PUSH_DIRECTIONS.items()},
        toe_up_limit_deg=toe_up_limit_deg(body.model, body.anatomy),
        deepest_knee_bend_deg=deepest_knee_bend_deg(body),
    )


def build_report(nova: Body | None = None, g1: Body | None = None) -> str:
    """两个身体都量一遍，返回报告的全文。"""
    return compose_report((measure(nova or build_nova().body), measure(g1 or load_g1())), g1_manifest())


def compose_report(bodies: tuple[Measured, Measured], manifest: Manifest) -> str:
    """把量好的结果（先 Nova，后基线）写成报告。"""
    sections = [
        _header(),
        _summary_section(bodies),
        _source_section(bodies[1].body, manifest),
        _pose_section(bodies),
        _standing_section(bodies),
        _push_section(bodies),
        _joints_section(bodies[1].body),
        _caveats_section(),
    ]
    return "\n\n".join(sections) + "\n"


def _header() -> str:
    return "\n".join(
        [
            "# 基线的身体：Unitree G1",
            "",
            "**这份报告和图是程序生成的，不要手改。** 要改就改 `body/nova_body` 里的代码，再运行：",
            "",
            "```bash",
            "docker compose run --rm body python -m nova_body.baseline_report",
            "```",
            "",
            "基线是一个现成的身体。把它和 Nova 放上同一个测试台、跑同一套测试，Nova 每加一样东西都有得比"
            "（[核心和待证明](../核心和待证明.md)第 2 节）。",
            "",
            "![Nova 和基线按同一个比例并排站着：正面和侧面。Nova 的外壳是半透明的；基线画的是它的外形](基线身体.svg)",
        ]
    )


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    """一张 Markdown 的表。"""
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return lines + ["| " + " | ".join(row) + " |" for row in rows]


def _names(bodies: tuple[Measured, ...]) -> list[str]:
    return [measured.body.name for measured in bodies]


def _summary_section(bodies: tuple[Measured, ...]) -> str:
    verdict = "**同一套测试，两个身体都过了。**" if all(m.passed for m in bodies) else "**同一套测试，没有都过。**"
    rows = [
        ["身高", *(f"{m.body.height_m:.2f} m" for m in bodies)],
        ["质量", *(f"{m.body.mass_kg:.2f} kg" for m in bodies)],
        ["自由度", *(f"{m.body.model.nv - FREE_JOINT_DOF}" for m in bodies)],
        ["驱动器", *(f"{m.body.model.nu}" for m in bodies)],
        [f"用关节控制站 {STAND_SECONDS:g} 秒", *(_stand_verdict(m.standing) for m in bodies)],
        ["驱动器不出力", *(_limp_outcome(m.limp) for m in bodies)],
        *([f"{label}推，最多扛得住", *(_strongest_push(m, label) for m in bodies)] for label in PUSH_DIRECTIONS),
        ["躯干竖直时，膝最多能弯到", *(f"{m.deepest_knee_bend_deg:.0f}°" for m in bodies)],
    ]
    lines = [
        "## 1. 结论",
        "",
        verdict,
        f"这里说的测试是：用关节控制站 {STAND_SECONDS:g} 秒（合格线一样），不给控制就倒。",
        "别的几条（模型的质量和来源对得上、传感器读数合理、仿真比实时快）在自动测试里查，两个身体跑的也是同一套。",
        "",
        *_table(["项目", *_names(bodies)], rows),
        "",
        "推力按体重的比例算：同样是体重的 4%，重的身体受的力大。",
        "仿真比实时快多少，每次运行不一样，所以不写在这里；量出来的数记在 [P1 计划](../P1计划.md)。",
    ]
    return "\n".join(lines)


def _stand_verdict(standing: StandingResult) -> str:
    if not stood_well(standing):
        return "**没有站好**"
    return f"站住了：最多歪 {standing.max_tilt_deg:.3f}°"


def _limp_outcome(limp: StandingResult) -> str:
    return f"{limp.seconds:.2f} 秒后倒了" if limp.fell else f"**{LIMP_SECONDS:g} 秒里没倒**"


def _strongest_push(measured: Measured, direction: str) -> str:
    share = measured.strongest_push_survived(direction)
    if share is None:
        return f"体重的 {PUSH_SHARES[0]:.0%} 就倒了"
    force = share * measured.body.mass_kg * GRAVITY_M_S2
    still_standing = not measured.pushes[direction][-1][1].fell
    return f"体重的 {share:.0%}（{force:.0f} N）" + ("，再大的没有试" if still_standing else "")


def _source_section(g1: Body, manifest: Manifest) -> str:
    lighter = OFFICIAL_MASS_KG - g1.mass_kg
    rows = [
        ["模型文件", "MuJoCo Menagerie 里的 `unitree_g1/g1.xml`：29 个自由度的 G1，没有灵巧手"],
        ["从哪来", manifest.source],
        [
            "版本",
            f"提交 `{manifest.commit[:SHORT_COMMIT]}`（{manifest.commit_date}），"
            f"写死在 `third_party/{manifest.name}.json`",
        ],
        ["许可证", f"{manifest.license}（可以商用；许可证的原文和模型放在一起）"],
        [
            "文件",
            f"{len(manifest.files)} 个，{manifest.total_bytes / BYTES_PER_MB:.1f} MB。不提交进仓库，"
            f"用 `{FETCH_COMMAND}` 下载；每次用之前都核对每个文件的 SHA-256",
        ],
        ["厂家写的", f"身高 {OFFICIAL_HEIGHT_M:.2f} m，约 {OFFICIAL_MASS_KG:.0f} kg（带电池）"],
        [
            "模型里量到的",
            f"身高 {g1.height_m:.2f} m；{g1.mass_kg:.2f} kg（文件里各段质量加起来，比厂家写的轻 {lighter:.1f} kg）",
        ],
    ]
    lines = [
        "## 2. 基线是什么、从哪来",
        "",
        *_table(["项目", "内容"], rows),
        "",
        "放上测试台时：",
        "",
        "- **没有改的（身体本身）**：各段的质量和惯量、关节的位置和范围、电机的峰值力矩、关节的摩擦、"
        "转子的惯量、碰撞的形状。模型文件一个字都不改。",
        "- **换成和 Nova 一样的（测试台定的）**：地面、仿真的步长、关节位置控制的软硬、站姿的算法。"
        f"文件里自带的软硬是没有调过的（每个关节都是 {PUBLISHED_STIFFNESS:g} N·m/rad），自带的站姿腿是直的；"
        "自带的站姿改名叫 `published_stand` 留着，用它原样也站得住。",
        "- **加上的**：每只脚底正中间的一个点（量脚滑了多少、算站姿用），每个关节的位置、速度、力矩的传感器。",
    ]
    return "\n".join(lines)


def _pose_section(bodies: tuple[Measured, ...]) -> str:
    stands = [m.body.stand for m in bodies]
    ratios = [m.body.stand.center_of_mass_height_m / m.body.height_m for m in bodies]
    rows = [
        ["膝", *(f"弯 {stand.knee_deg:.1f}°" for stand in stands)],
        ["踝", *(f"脚尖向上 {stand.ankle_deg:.1f}°" for stand in stands)],
        ["髋", *(f"向前抬 {stand.hip_deg:.1f}°" for stand in stands)],
        [
            "重心的高度",
            *(
                f"{stand.center_of_mass_height_m:.3f} m（身高的 {ratio:.2f}）"
                for stand, ratio in zip(stands, ratios, strict=True)
            ),
        ],
        ["脚底着地的那一段", *(f"长 {m.body.foot_length_m * CM_PER_M:.1f} cm" for m in bodies)],
        ["踝最多能让脚尖向上", *(f"{m.toe_up_limit_deg:.0f}°" for m in bodies)],
        ["躯干竖直时，膝最多能弯到", *(f"{m.deepest_knee_bend_deg:.0f}°" for m in bodies)],
    ]
    lines = [
        "## 3. 站姿",
        "",
        f"两个身体用同一个办法算：膝弯 {KNEE_BEND_DEG:g}°；髋和踝配合着让躯干竖直、脚底贴地；"
        "踝的角度是算出来的，让重心正好在两只脚的正中间上面。手臂放在各自放松的位置上。",
        "",
        *_table(["项目", *_names(bodies)], rows),
        "",
        "最后两行：躯干竖直、脚底贴地的时候，膝弯得越多，踝就要让脚尖向上越多，重心才能留在脚的中间上面。"
        "所以踝能转多少，就定了这样能蹲多深。要蹲得再深，得让身体往前倾，那是 P2 的事。",
        "",
        f"站着时最费力的 {HOLDING_ROWS} 个关节（左右一样的只列左侧）：",
    ]
    for measured in bodies:
        lines += [
            "",
            f"**{measured.body.name}**",
            "",
            *_table(["关节", "出的力矩", "是峰值的"], _holding_rows(measured.body)),
        ]
    return "\n".join(lines)


def _holding_rows(body: Body) -> list[list[str]]:
    holding = [
        (abs(torque), joint)
        for joint, torque in zip(body.joints, body.stand.holding_torque_nm, strict=True)
        if not joint.label.startswith(RIGHT_PREFIX)
    ]
    hardest = sorted(holding, key=lambda row: row[0], reverse=True)[:HOLDING_ROWS]
    return [
        [joint.label.removeprefix(LEFT_PREFIX), f"{torque:.1f} N·m", f"{torque / joint.peak_torque_nm:.1%}"]
        for torque, joint in hardest
    ]


def _standing_section(bodies: tuple[Measured, ...]) -> str:
    results = [m.standing for m in bodies]
    rows = [
        ["倒了没有", *("倒了" if result.fell else "没倒" for result in results), "不倒"],
        ["骨盆最多歪了", *(f"{result.max_tilt_deg:.3f}°" for result in results), f"< {MAX_TILT_DEG:g}°"],
        [
            "骨盆最多低了",
            *(f"{result.pelvis_drop_m * MM_PER_M:.2f} mm" for result in results),
            f"< {MAX_PELVIS_DROP_M * MM_PER_M:g} mm",
        ],
        [
            "脚滑了",
            *(f"{result.foot_slip_m * MM_PER_M:.2f} mm" for result in results),
            f"< {MAX_FOOT_SLIP_M * MM_PER_M:g} mm",
        ],
        [
            "最后关节的速度",
            *(f"{result.end_joint_speed_rad_s:.4f} rad/s" for result in results),
            f"< {MAX_END_SPEED_RAD_S:g} rad/s",
        ],
        ["地面托着的重量", *(f"{result.support_force_n / GRAVITY_M_S2:.2f} kg" for result in results), "等于体重"],
        [
            "压力中心",
            *(
                f"在脚跟前面 {result.pressure_center_from_heel_m * CM_PER_M:.1f} cm"
                f"（脚底长 {result.foot_length_m * CM_PER_M:.1f} cm）"
                for result in results
            ),
            "在脚底里面",
        ],
        ["驱动器不出力", *(_limp_outcome(m.limp) for m in bodies), "会倒"],
    ]
    lines = [
        f"## 4. 站 {STAND_SECONDS:g} 秒",
        "",
        "每个关节的驱动器顶在站姿的角度上（位置控制），没有平衡的控制。合格线两个身体一样。",
        "",
        *_table(["项目", *_names(bodies), "合格线"], rows),
        "",
        "不给控制马上就倒，说明是关节的控制让它们站住的。",
    ]
    return "\n".join(lines)


def _push_section(bodies: tuple[Measured, ...]) -> str:
    push = Push((0.0, 0.0, 0.0))
    columns = [(measured, label) for measured in bodies for label in PUSH_DIRECTIONS]
    rows = []
    for share in PUSH_SHARES:
        cells = [_push_cell(dict(measured.pushes[label]).get(share)) for measured, label in columns]
        if all(cell == "-" for cell in cells):
            break
        rows.append([f"{share:.0%}", *cells])
    lines = [
        "## 5. 推一下",
        "",
        f"站稳以后在胸上推 {push.duration_s:g} 秒。力从体重的 {PUSH_SHARES[0]:.0%} 起，每档加 {PUSH_SHARES[0]:.0%}，"
        "推到倒了为止（倒了以后更大的就不试了，写成 -）。没倒的写最多歪了多少度。",
        "",
        *_table(["推力是体重的", *(f"{measured.body.name} {label}" for measured, label in columns)], rows),
        "",
        "两个身体都是稍微用力一推就倒：现在只是关节顶着，没有平衡的控制。"
        "被推了还能站住，要靠小脑层的平衡控制，是下一阶段（P2）的事。到那时这张表就是比较的起点。",
    ]
    return "\n".join(lines)


def _push_cell(result: StandingResult | None) -> str:
    if result is None:
        return "-"
    return "倒了" if result.fell else f"{result.max_tilt_deg:.1f}°"


def _joints_section(g1: Body) -> str:
    shown = [joint for joint in g1.joints if not joint.label.startswith(RIGHT_PREFIX)]
    lines = [
        "## 6. G1 的关节",
        "",
        f"一共 {len(g1.joints)} 个，每个都有驱动器。左右两侧一样，下面只列中间的和左侧的。"
        "范围和峰值力矩是模型文件里的。",
        f"刚度是测试台定的，和 Nova 同一条规则：关节偏了 {FULL_TORQUE_ERROR_RAD:g} 弧度"
        f"（约 {math.degrees(FULL_TORQUE_ERROR_RAD):.0f}°）就出全力，阻尼 = 刚度 x {DAMPING_TIME_S:g} 秒。"
        "这不是 G1 出厂的设置。",
        "",
        *_table(["关节", "范围", "峰值力矩", "刚度"], [_joint_row(joint) for joint in shown]),
    ]
    return "\n".join(lines)


def _joint_row(joint: DrivenJoint) -> list[str]:
    return [
        joint.label.removeprefix(LEFT_PREFIX),
        f"{math.degrees(joint.lower_rad):.0f}° ~ {math.degrees(joint.upper_rad):.0f}°",
        f"{joint.peak_torque_nm:.0f} N·m",
        f"{stiffness_for(joint.peak_torque_nm):.0f} N·m/rad",
    ]


def _caveats_section() -> str:
    return "\n".join(
        [
            "## 7. 看这份报告要记住的",
            "",
            "- **比的只是站着。** 走、被推以后恢复、摔倒后起来是 P2 的事，家务是 P3 以后的事。"
            "基线真正的用处在那时候：它有现成的、练好的权重。",
            "- **G1 没有手指。** 这个模型的手是一块橡胶的手掌，所以它只有 29 个自由度；Nova 的两只手就有 44 个。"
            "要比抓东西（P4），得给基线另找手的模型。",
            "- **G1 的头和颈不能动**，模型里也没有相机、脚底和手腕的力传感器、皮肤。它自己的传感器只有两个 IMU"
            "（骨盆、躯干）；关节的位置、速度、力矩是测试台加的（真机的电机也会报这三样）。",
            "- **关节的软硬是测试台定的同一条规则**，不是 G1 出厂的，也不是 Nova 最后会用的。"
            '所以"扛得住多大的推力"现在主要看身体的比例（脚多长、重心多高），不看控制得好不好。',
            "- **地面由测试台定。** 和地面的摩擦、软硬都用地面的；"
            f"G1 的模型给自己的脚写的摩擦（{PUBLISHED_FOOT_FRICTION:g}）在这里不起作用。"
            "这样同一块地面对两个身体才是一样的。",
            f"- **仿真的步长是 {TIMESTEP_S * MM_PER_M:g} 毫秒**，两个身体一样（G1 的文件自己写的步长不用）。",
            "- **G1 的网格只用来看。** 图上画的是每个网格的凸包，只有大的轮廓。",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    """命令行入口：两个身体都量一遍，写报告和图，打印结论。"""
    parser = argparse.ArgumentParser(description="把基线（Unitree G1）和 Nova 放上同一个测试台，写一份报告。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="报告写到哪里")
    arguments = parser.parse_args(argv)
    nova, g1 = build_nova().body, load_g1()
    report = build_report(nova, g1)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report, encoding="utf-8", newline="\n")
    picture = arguments.output.with_suffix(".svg")
    picture.write_text(draw_lineup([nova, g1]), encoding="utf-8", newline="\n")
    print(report[report.index("## 1.") : report.index("## 2.")].strip())
    print(f"\n报告写到了 {arguments.output}，图写到了 {picture}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
