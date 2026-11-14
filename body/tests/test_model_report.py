"""身体模型报告的测试。"""

from xml.etree import ElementTree

import pytest

from nova_body.model_report import build_report, main


@pytest.fixture(scope="module")
def report(nova) -> str:
    """整份报告只生成一次（里面要仿真好几次）。"""
    return build_report(nova)


@pytest.mark.parametrize(
    "heading",
    [
        "## 1. 结论",
        "## 2. 站姿",
        "## 3. 站 10 秒",
        "## 4. 各段的长度和质量",
        "## 5. 关节",
        "## 6. 传感器",
        "## 7. 这个模型还没有的",
    ],
)
def test_report_has_every_section(report, heading):
    """报告里每一节都有。"""
    assert heading in report


def test_summary_states_the_counts_and_the_result(report):
    """结论里有自由度、驱动器的数，模型的质量和质量闭环一样，站住了。"""
    summary = report[report.index("## 1.") : report.index("## 2.")]
    assert "| 自由度 | 75（两只手 44，身体 31） |" in summary
    assert "| 驱动器 | 67（身体 31，每只手 18；" in summary
    assert "78.18 kg（质量闭环算的是 78.18 kg）" in summary
    assert "站住了" in summary
    assert "没有站好" not in summary


def test_standing_section_shows_the_comparisons(report):
    """站 10 秒那一节有对照：不给控制倒了，轻推四个方向不倒，用力推倒了。"""
    section = report[report.index("## 3.") : report.index("## 4.")]
    assert "| 驱动器不出力 | 0." in section
    assert section.count("推 30 N、0.5 秒 | 没倒") == 4
    assert "推 300 N、0.5 秒 | 倒了 |" in section


def test_joint_table_lists_one_side_of_every_joint(report):
    """关节表列了中间的和左侧的：身体 5 + 13 个，手 22 个；远指间写的是"跟着近指间动"。"""
    section = report[report.index("## 5.") : report.index("## 6.")]
    rows = [line for line in section.splitlines() if line.startswith("| ") and "°" in line]
    assert len(rows) == 5 + 13 + 22
    assert section.count("跟着近指间动") == 4
    assert "| 小腿 | 膝 | 0° ~ 150° | 弯 |" in section
    assert "左 " not in section


def test_report_links_the_picture(report):
    """报告里放了图。"""
    assert "](身体模型.svg)" in report


def test_report_is_repeatable(report, nova):
    """同一个模型再生成一次报告，一个字都不差（报告里不写每次不一样的数）。"""
    assert build_report(nova) == report


def test_command_line_writes_report_and_picture(tmp_path, capsys):
    """命令行把报告和图写到指定的地方，并打印结论。"""
    output = tmp_path / "报告" / "身体模型.md"
    assert main(["--output", str(output)]) == 0
    text = output.read_text(encoding="utf-8")
    assert text.startswith("# 身体的模型（核心版）")
    assert "\r" not in text
    picture = output.with_suffix(".svg").read_text(encoding="utf-8")
    assert ElementTree.fromstring(picture).tag.endswith("svg")
    printed = capsys.readouterr().out
    assert "## 1. 结论" in printed
    assert "## 2." not in printed
