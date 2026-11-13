"""质量闭环报告的测试。"""

import pytest

from nova_body.actuator_mass import QDD_SAMPLES
from nova_body.mass_report import build_report, main


@pytest.fixture(scope="module")
def report() -> str:
    """整份报告只算一次。"""
    return build_report()


@pytest.mark.parametrize(
    "heading",
    [
        "## 1. 结论",
        "## 2. 每样东西加多少重量",
        "## 3. 核心版的明细",
        "## 4. 完整版的明细",
        "## 5. 用的假设",
        "## 6. 驱动器的数据",
    ],
)
def test_report_has_every_section(report, heading):
    """报告里每一节都有。"""
    assert heading in report


def test_report_lists_both_bodies_and_both_actuator_assumptions(report):
    """结论里有核心版、完整版，各有两种驱动的假设。"""
    summary = report[report.index("## 1.") : report.index("## 2.")]
    assert summary.count("| 核心版 | 75 |") == 2
    assert summary.count("| 完整版 | 98 |") == 2
    assert summary.count("今天最好的驱动") >= 2
    assert summary.count("保守的驱动") >= 2


def test_report_cites_every_actuator_sample(report):
    """每个真实的驱动器和它的来源都写在报告里。"""
    for sample in QDD_SAMPLES:
        assert sample.name in report
        assert sample.source in report


def test_command_line_writes_the_report(tmp_path, capsys):
    """命令行把报告写到指定的地方，并打印结论。"""
    output = tmp_path / "报告" / "质量闭环.md"
    assert main(["--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == build_report()
    printed = capsys.readouterr().out
    assert "## 1. 结论" in printed
    assert "## 2." not in printed
