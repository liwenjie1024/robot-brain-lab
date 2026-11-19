"""按命令表考一个走路的策略的测试：每走过一段有一个结果；在跑着的测试台上接着走；结果的表。
用测试用的小策略和小身体（测试台的部分在 test_policy_bench.py）。"""

import math
from pathlib import Path

import pytest

from nova_body.policy import load_policy
from nova_body.policy_bench import STILL, PolicyBench
from nova_body.policy_walk import Segment, SegmentResult, describe, walk, walk_on

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "policy"


@pytest.fixture
def policy():
    return load_policy(FIXTURE_DIR / "contract.json")


def test_a_short_schedule_gives_one_result_per_segment_walked(policy):
    """照一张短的命令表走：每走过一段有一个结果，名字、命令和表里的一样，走过的路不是负的。"""
    schedule = (Segment("站着", 0.2, STILL), Segment("转弯", 0.2, {**STILL, "ang_vel_z": 0.2}))
    results = walk(policy, schedule)
    assert 1 <= len(results) <= len(schedule)
    for result, segment in zip(results, schedule, strict=False):
        assert result.label == segment.label
        assert result.command == segment.command
        assert result.distance_m >= 0.0
        assert 0.0 <= result.limited_share <= 1.0
        assert 0.0 <= result.reflex_share <= 1.0
    if len(results) < len(schedule):
        assert results[-1].fell


def test_walking_on_goes_on_from_where_the_bench_is(policy):
    """在跑着的测试台上接着走：时间接着往下走，走过的路是两次加起来的。"""
    bench = PolicyBench(policy, sensed=False)
    schedule = (Segment("站着", 0.1, STILL),)
    first = walk_on(bench, schedule)
    after_first = bench.time_s
    second = walk_on(bench, schedule)
    assert after_first == pytest.approx(0.1)
    assert bench.time_s == pytest.approx(0.2)
    assert first[0].distance_m + second[0].distance_m == pytest.approx(bench.distance_m)


def test_the_table_writes_a_dash_for_what_was_not_measured():
    """一开始就摔了、没量到的，表里写 —，不写 nan。"""
    fallen = SegmentResult(
        label="站着",
        command=dict(STILL),
        measured={"lin_vel_x": math.nan, "lin_vel_y": math.nan, "ang_vel_z": math.nan},
        error={"lin_vel_x": math.nan, "lin_vel_y": math.nan, "ang_vel_z": math.nan},
        distance_m=0.3,
        seconds=0.05,
        fell=True,
        limited_share=0.25,
        reflex_share=0.0,
        velocity_error_m_s=math.nan,
        tilt_error_deg=math.nan,
    )
    table = describe([fallen])
    assert "nan" not in table
    assert "—、—、—" in table
    assert "摔了" in table
    assert "25% 的步" in table


def test_a_sensed_walk_needs_a_body_the_bench_knows(policy):
    """测试台不认识的身体（测试用的小身体没有 IMU 的传感器）：只看真数可以走，要策略看感觉到的就拒绝。"""
    with pytest.raises(ValueError, match="做不了状态估计"):
        walk(policy, (Segment("站着", 0.1, STILL),), sensed=True)
