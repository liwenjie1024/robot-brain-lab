"""基线报告的测试：两个身体的数并排写对了；有一个没过的时候，结论要说没过。"""

from dataclasses import replace
from xml.etree import ElementTree

import pytest

from nova_body.baseline import g1_manifest
from nova_body.baseline_report import PUSH_SHARES, Measured, compose_report, main, measure
from nova_body.standing import stood_well

SVG = "{http://www.w3.org/2000/svg}"
FORWARD, SIDEWAYS = "往前", "往侧面"


@pytest.fixture(scope="module")
def measured(nova, g1) -> tuple[Measured, Measured]:
    """两个身体各量一遍，只量一次（里面要仿真好多次）。"""
    return measure(nova.body), measure(g1)


@pytest.fixture(scope="module")
def report(measured) -> str:
    return compose_report(measured, g1_manifest())


def section(report: str, number: int) -> str:
    """报告里的第几节。"""
    start = report.index(f"## {number}.")
    following = report.find(f"## {number + 1}.")
    return report[start:] if following < 0 else report[start:following]


def table_rows(text: str) -> list[list[str]]:
    """一段文字里表格的每一行（不要表头和分隔线）。"""
    lines = [line for line in text.splitlines() if line.startswith("| ")]
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]


# 量 --------------------------------------------------------------------------------------------------


def test_both_bodies_pass_the_same_tests(measured):
    """两个身体都过：站得合格，不给控制会倒。"""
    for one in measured:
        assert one.passed, one.body.name
        assert stood_well(one.standing)
        assert one.limp.fell


def test_pushes_grow_until_the_body_falls(measured):
    """每个方向从体重的 2% 推起，一档一档加，最后一档是倒了的那一档，前面的都没倒。"""
    for one in measured:
        assert set(one.pushes) == {FORWARD, SIDEWAYS}
        for ladder in one.pushes.values():
            shares = [share for share, _ in ladder]
            assert shares == list(PUSH_SHARES[: len(shares)])
            assert [result.fell for _, result in ladder[:-1]] == [False] * (len(ladder) - 1)
            assert ladder[-1][1].fell


def test_strongest_push_survived_is_the_step_before_the_fall(measured):
    """最多扛得住的推力，就是倒了的那一档的前一档。往前：Nova 是体重的 10%，G1 是 6%。"""
    nova, g1 = measured
    assert nova.strongest_push_survived(FORWARD) == pytest.approx(0.10)
    assert g1.strongest_push_survived(FORWARD) == pytest.approx(0.06)
    for one in measured:
        for direction, ladder in one.pushes.items():
            assert one.strongest_push_survived(direction) == pytest.approx(ladder[-2][0])
    fell_at_once = replace(nova, pushes={FORWARD: nova.pushes[FORWARD][-1:], SIDEWAYS: nova.pushes[SIDEWAYS]})
    assert fell_at_once.strongest_push_survived(FORWARD) is None


def test_nova_cannot_squat_as_deep_as_the_baseline_with_an_upright_trunk(measured):
    """躯干竖直时 Nova 蹲得没有 G1 深：它的踝让脚尖向上 45°，膝最多弯到 86°；G1 的踝能到 50°，膝能弯到 97°。"""
    nova, g1 = measured
    assert (nova.toe_up_limit_deg, g1.toe_up_limit_deg) == pytest.approx((45.0, 50.0), abs=0.01)
    assert (nova.deepest_knee_bend_deg, g1.deepest_knee_bend_deg) == (86.0, 97.0)


# 报告 ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "heading",
    [
        "## 1. 结论",
        "## 2. 基线是什么、从哪来",
        "## 3. 站姿",
        "## 4. 站 10 秒",
        "## 5. 推一下",
        "## 6. G1 的关节",
        "## 7. 看这份报告要记住的",
    ],
)
def test_report_has_every_section(report, heading):
    """报告里每一节都有。"""
    assert heading in report


def test_summary_puts_the_two_bodies_side_by_side(report):
    """结论里两个身体的数并排着：身高、质量、自由度、驱动器；都站住了。"""
    summary = section(report, 1)
    assert "**同一套测试，两个身体都过了。**" in summary
    assert "| 项目 | Nova（核心版） | Unitree G1 |" in summary
    assert "| 身高 | 1.70 m | 1.32 m |" in summary
    assert "| 质量 | 74.71 kg | 33.34 kg |" in summary
    assert "| 自由度 | 75 | 29 |" in summary
    assert "| 驱动器 | 67 | 29 |" in summary
    assert summary.count("站住了：最多歪 0.0") == 2
    assert "没有站好" not in summary
    assert "| 往前推，最多扛得住 | 体重的 10%（73 N） | 体重的 6%（20 N） |" in summary
    assert "| 往侧面推，最多扛得住 | 体重的 10%（73 N） | 体重的 14%（46 N） |" in summary
    assert "| 躯干竖直时，膝最多能弯到 | 86° | 97° |" in summary


def test_source_section_says_where_the_baseline_comes_from(report):
    """来源那一节写着：哪个仓库、哪个提交、什么许可证、多少文件、怎么下载；厂家写的和模型里量到的。"""
    source = section(report, 2)
    manifest = g1_manifest()
    assert manifest.source in source
    assert f"`{manifest.commit[:12]}`（{manifest.commit_date}）" in source
    assert manifest.commit not in source
    assert "BSD-3-Clause（可以商用" in source
    assert "37 个，19.7 MB" in source
    assert "python -m nova_body.third_party" in source
    assert "| 厂家写的 | 身高 1.32 m，约 35 kg（带电池） |" in source
    assert "身高 1.32 m；33.34 kg（文件里各段质量加起来，比厂家写的轻 1.7 kg）" in source
    assert "每个关节都是 500 N·m/rad" in source


def test_pose_section_compares_the_stand_poses(report):
    """站姿那一节：同样弯 15° 的膝；各自的踝和髋；重心的高度；每个身体最费力的驱动器都在踝上。"""
    pose = section(report, 3)
    assert "| 膝 | 弯 15.0° | 弯 15.0° |" in pose
    assert "| 踝 | 脚尖向上 11.7° | 脚尖向上 10.6° |" in pose
    assert "| 重心的高度 | 0.944 m（身高的 0.56） | 0.689 m（身高的 0.52） |" in pose
    assert "| 脚底着地的那一段 | 长 25.8 cm | 长 18.0 cm |" in pose
    assert "| 踝最多能让脚尖向上 | 45° | 50° |" in pose
    assert "| 踝 前后、侧（并联甲） | 11.2 N·m | 8.9% |" in pose
    assert "| 踝 前后 | 5.6 N·m | 11.2% |" in pose
    assert pose.count("| 驱动器 | 出的力 | 是峰值的 |") == 2
    hardest = [row for row in table_rows(pose) if row[-1].endswith("%")]
    assert len(hardest) == 2 * 4
    assert not any(row[0].startswith(("左 ", "右 ")) for row in hardest)


def test_standing_section_uses_the_same_pass_lines(report):
    """站 10 秒那一节：每一行是两个身体的结果和同一条合格线。"""
    standing = section(report, 4)
    assert "| 项目 | Nova（核心版） | Unitree G1 | 合格线 |" in standing
    assert "| 倒了没有 | 没倒 | 没倒 | 不倒 |" in standing
    assert "| 地面托着的重量 | 74.71 kg | 33.34 kg | 等于体重 |" in standing
    assert "| < 2° |" in standing and "| < 5 mm |" in standing and "| < 1 mm |" in standing
    assert "在脚跟前面 12.9 cm（脚底长 25.8 cm）" in standing
    assert "在脚跟前面 9.0 cm（脚底长 18.0 cm）" in standing
    rows = table_rows(standing)
    assert all(len(row) == 4 for row in rows)
    assert rows[-1][0] == "驱动器不出力" and rows[-1][3] == "会倒"
    assert all("秒后倒了" in cell for cell in rows[-1][1:3])


def test_push_table_goes_up_until_everyone_has_fallen(report, measured):
    """推一下那一节：一行一档；每一列先是歪了多少度，然后正好一个"倒了"，再往下是 -。"""
    rows = table_rows(section(report, 5))[1:]
    longest = max(len(ladder) for one in measured for ladder in one.pushes.values())
    assert [row[0] for row in rows] == [f"{share:.0%}" for share in PUSH_SHARES[:longest]]
    for column in range(1, 5):
        cells = [row[column] for row in rows]
        fall = cells.index("倒了")
        assert all(cell.endswith("°") for cell in cells[:fall])
        assert all(cell == "-" for cell in cells[fall + 1 :])
    assert rows[0][1:] == ["0.6°", "0.1°", "1.0°", "0.0°"]


def test_joint_table_lists_one_side_of_every_g1_joint(report):
    """关节表列了腰的 3 个和左侧的 13 个；范围是文件里的，刚度是测试台定的。"""
    joints = section(report, 6)
    rows = table_rows(joints)[1:]
    assert len(rows) == 3 + 13
    assert "| 膝 | -5° ~ 165° | 139 N·m | 1390 N·m/rad |" in joints
    assert "| 腕 上下 | -93° ~ 93° | 5 N·m | 50 N·m/rad |" in joints
    assert "| 腰 转 | -150° ~ 150° | 88 N·m | 880 N·m/rad |" in joints
    assert "这不是 G1 出厂的设置" in joints
    assert not any(row[0].startswith(("左 ", "右 ")) for row in rows)


def test_caveats_say_what_is_not_compared_yet(report):
    """最后一节说清楚：只比了站着；G1 没有手指；软硬和地面是测试台定的。"""
    caveats = section(report, 7)
    assert "比的只是站着" in caveats
    assert "G1 没有手指" in caveats
    assert "给自己的脚写的摩擦（0.6）在这里不起作用" in caveats
    assert "仿真的步长是 1 毫秒" in caveats


def test_report_links_the_picture_and_the_plan(report):
    """报告里放了图，指到核心和待证明、P1 计划。"""
    assert "](基线身体.svg)" in report
    assert "](../核心和待证明.md)" in report
    assert "](../P1计划.md)" in report


# 有一个没过的时候 ------------------------------------------------------------------------------------


def test_report_says_so_when_a_body_does_not_stand(measured):
    """有一个身体没站好：结论写"没有都过"，那一格写"没有站好"。"""
    nova, g1 = measured
    fallen = replace(g1, standing=replace(g1.standing, fell=True))
    assert not fallen.passed
    summary = section(compose_report((nova, fallen), g1_manifest()), 1)
    assert "**同一套测试，没有都过。**" in summary
    assert "两个身体都过了" not in summary
    assert summary.count("**没有站好**") == 1


def test_report_says_so_when_a_body_stands_without_control(measured):
    """不给控制也没倒（那就不是控制让它站住的）：也算没过。"""
    nova, g1 = measured
    stuck = replace(nova, limp=replace(nova.limp, fell=False))
    assert not stuck.passed
    report = compose_report((stuck, g1), g1_manifest())
    assert "**同一套测试，没有都过。**" in report
    assert "**3 秒里没倒**" in report


def test_summary_when_the_first_push_knocks_it_over_or_nothing_does(measured):
    """第一档就倒了，写"体重的 2% 就倒了"；推到最大一档还没倒，写"再大的没有试"。"""
    nova, g1 = measured
    first_falls = replace(g1, pushes={FORWARD: g1.pushes[FORWARD][-1:], SIDEWAYS: g1.pushes[SIDEWAYS]})
    never_falls = replace(nova, pushes={FORWARD: nova.pushes[FORWARD][:-1], SIDEWAYS: nova.pushes[SIDEWAYS]})
    summary = section(compose_report((never_falls, first_falls), g1_manifest()), 1)
    assert "| 往前推，最多扛得住 | 体重的 10%（73 N），再大的没有试 | 体重的 2% 就倒了 |" in summary


# 命令行 ----------------------------------------------------------------------------------------------


def test_command_line_writes_the_same_report_and_the_lineup_picture(tmp_path, capsys, report):
    """命令行把报告和图写到指定的地方，并打印结论。再量一遍，报告一个字都不差。"""
    output = tmp_path / "报告" / "基线身体.md"
    assert main(["--output", str(output)]) == 0
    text = output.read_text(encoding="utf-8")
    assert text == report
    assert text.startswith("# 基线的身体：Unitree G1")
    assert "\r" not in text
    picture = ElementTree.fromstring(output.with_suffix(".svg").read_text(encoding="utf-8"))
    names = [element.text for element in picture.iter(SVG + "text")]
    assert "Nova（核心版）" in names and "Unitree G1" in names
    printed = capsys.readouterr().out
    assert "## 1. 结论" in printed
    assert "## 2." not in printed
