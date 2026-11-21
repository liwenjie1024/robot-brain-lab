"""P2 考试的测试：每道题的规则（推力一档一档地加、站起来要站住、楼梯走到哪算上了几级、一圈该走多远、几段的平均差），
每道题用测试用的小策略跑得通（时间短），考的是身体感觉到的，结果的表。"""

import math
from pathlib import Path

import pytest

from nova_body.bench import Stairs
from nova_body.p2_exam import (
    PUSH_ATTEMPTS,
    PUSH_DIRECTIONS,
    SETTLE_S,
    WALK_LAP,
    ExamResult,
    GetUpResult,
    PushAttempt,
    PushResult,
    PushTrial,
    StairsResult,
    StairsTrial,
    StandResult,
    UprightWatch,
    WalkResult,
    describe,
    exam_get_up,
    exam_push,
    exam_stairs,
    exam_stand,
    exam_tasks,
    exam_walk,
    lap_distance_m,
    mean_errors,
    merged,
    push_delays_s,
    push_trial,
    refusals,
    run_exam,
    run_task,
    stairs_command,
    stairs_progress,
)
from nova_body.policy import load_policy
from nova_body.policy_bench import STILL, UPRIGHT_HEIGHT_SHARE, StartPose
from nova_body.policy_walk import Segment, SegmentResult

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "policy"
SMALL_STAIRS = Stairs(start_x=1.0, rise_m=0.2, tread_m=0.25, steps=3, landing_m=0.5, width_m=1.0)
NO_ERROR = {"lin_vel_x": math.nan, "lin_vel_y": math.nan, "ang_vel_z": math.nan}


@pytest.fixture
def policy():
    return load_policy(FIXTURE_DIR / "contract.json")


def segment_result(label: str, seconds: float, error: dict[str, float]) -> SegmentResult:
    return SegmentResult(
        label=label,
        command=dict(STILL),
        measured=dict(NO_ERROR),
        error=error,
        distance_m=0.0,
        seconds=seconds,
        fell=False,
        limited_share=0.0,
        reflex_share=0.0,
        velocity_error_m_s=math.nan,
        tilt_error_deg=math.nan,
    )


@pytest.mark.parametrize(
    ("furthest_x", "up", "down"),
    [
        (-math.inf, 0, 0),
        (0.5, 0, 0),
        (1.1, 1, 0),
        (1.6, 3, 0),
        (2.0, 3, 0),
        (2.3, 3, 1),
        (2.6, 3, 2),
        (2.75, 3, 3),
        (4.0, 3, 3),
    ],
)
def test_stairs_progress_counts_steps_up_and_down(furthest_x, up, down):
    """站得好好的走到哪，就算上了几级、下了几级：上到平台是 3 级，过了最后一级踩到地面是下了 3 级。"""
    assert stairs_progress(SMALL_STAIRS, furthest_x) == (up, down)


def watch(times_upright: list[tuple[float, bool]], deadline_s: float = 10.0, stay_s: float = 2.0) -> float | None:
    upright = UprightWatch(deadline_s, stay_s)
    for time_s, up in times_upright:
        upright.update(time_s, up)
    return upright.stood_up_at_s


def test_getting_up_counts_only_if_it_stays_up():
    """第 3 秒站起来、一直站着：算第 3 秒站起来。站了 1 秒又倒了，第 6 秒再站起来：算第 6 秒。"""
    steps = [step * 0.5 for step in range(25)]
    assert watch([(t, t >= 3.0) for t in steps]) == 3.0
    assert watch([(t, 3.0 <= t <= 4.0 or t >= 6.0) for t in steps]) == 6.0


def test_getting_up_after_the_deadline_does_not_count():
    """10 秒以后才站起来不算；正好第 10 秒站起来、站住 2 秒算（边界）。只站住 1.5 秒不算。"""
    late = [(t / 2, t / 2 >= 10.5) for t in range(30)]
    assert watch(late) is None
    on_time = [(t / 2, t / 2 >= 10.0) for t in range(30)]
    assert watch(on_time) == 10.0
    short = [(t / 2, 3.0 <= t / 2 <= 4.5) for t in range(30)]
    assert watch(short) is None


def test_a_lap_is_as_long_as_its_commands():
    """照命令走一圈该走的路：每一段的时间 × 速度（往前、横着合起来），转弯不算路。"""
    assert lap_distance_m(WALK_LAP) == pytest.approx(5.0 + 10.0 + 11.0 + 2 * 6.4 + 2 * 1.5 + 2.5)


def test_mean_errors_weigh_by_time_and_skip_what_was_not_measured():
    """几段的平均差：按走的时间算权重（1 秒的差 0.1、3 秒的差 0.3，平均 0.25）；没量到的段不算；都没量到是 nan。"""
    results = [
        segment_result("甲", 1.0, {"lin_vel_x": 0.1, "lin_vel_y": 0.0, "ang_vel_z": 0.2}),
        segment_result("乙", 3.0, {"lin_vel_x": 0.3, "lin_vel_y": 0.4, "ang_vel_z": 0.2}),
        segment_result("丙", 5.0, dict(NO_ERROR)),
    ]
    assert mean_errors(results) == pytest.approx({"lin_vel_x": 0.25, "lin_vel_y": 0.3, "ang_vel_z": 0.2})
    assert all(math.isnan(value) for value in mean_errors(results[2:]).values())


@pytest.mark.parametrize("shares", [(), (0.0, 0.1), (0.2, 0.1), (0.1, 0.1)], ids=["没有", "有 0", "从大到小", "重复"])
def test_push_shares_must_go_up(policy, shares):
    """推力要从小到大、每档大于 0、不重复，不然拒绝。"""
    with pytest.raises(ValueError, match="从小到大"):
        exam_push(policy, "往前", shares=shares, sensed=False)


def test_an_unknown_push_direction_is_refused(policy):
    with pytest.raises(ValueError, match="没有这个推的方向"):
        exam_push(policy, "往上", sensed=False)


def test_pushing_goes_up_until_it_falls(policy):
    """一档一档地推，每档推 4 次：有倒的只会是最后一档，之后更大的不推；扛得住的最大一档是最后一次都没倒的那一档；
    力 = 体重 × 比例。"""
    shares = (0.05, 2.0, 3.0)
    result = exam_push(policy, "往左", shares=shares, sensed=False)
    tried = [trial.share for trial in result.trials]
    assert tried == list(shares[: len(tried)])
    assert all(trial.attempts == PUSH_ATTEMPTS for trial in result.trials)
    assert all(trial.held for trial in result.trials[:-1])
    assert not result.trials[-1].held or len(tried) == len(shares)
    held = [trial for trial in result.trials if trial.held]
    assert result.strongest_share == (held[-1].share if held else 0.0)
    weights = {trial.force_n / trial.share for trial in result.trials}
    assert max(weights) == pytest.approx(min(weights))
    assert result.trials[-1].falls == PUSH_ATTEMPTS, "2 倍体重推 0.5 秒，小身体每一次都倒"


def test_the_pushes_of_one_level_are_spread_over_one_policy_period():
    """每一档的 4 次推，推的时刻在策略的一个周期里平均地错开：每秒算 50 次的策略，晚 0、5、10、15 毫秒。"""
    assert push_delays_s(50.0) == pytest.approx([0.0, 0.005, 0.010, 0.015])


def test_a_level_is_held_only_if_no_push_of_it_fell():
    """一档里 4 次有 1 次倒了，这一档就不算扛得住；最多歪了多少只看没倒的那几次；都倒了是 nan。"""
    attempts = [
        PushAttempt(10.0, False, 12.0, False),
        PushAttempt(10.0, True, 61.0, True),
        PushAttempt(10.0, False, 20.0, False),
    ]
    trial = push_trial(0.1, attempts)
    assert (trial.attempts, trial.falls, trial.held) == (3, 1, False)
    assert trial.max_tilt_deg == 20.0
    assert trial.fall_reflex
    everyone_fell = push_trial(0.2, [PushAttempt(20.0, True, 60.5, True)] * 2)
    assert math.isnan(everyone_fell.max_tilt_deg)
    assert push_trial(0.05, attempts[:1]).held


def test_a_short_stand_measures_after_settling(policy):
    """站一小会儿（比落下来站稳的时间长一点）：没倒就量了歪斜、挪了多远、功率；小身体没有驱动器的发热模型。"""
    result = exam_stand(policy, seconds=SETTLE_S + 0.3, sensed=False)
    assert math.isnan(result.hottest_winding_c)
    if result.fell:
        assert result.seconds < SETTLE_S + 0.3
    else:
        assert result.seconds == pytest.approx(SETTLE_S + 0.3)
        assert result.max_tilt_deg >= 0.0
        assert result.drift_m >= 0.0
        assert result.mean_power_w >= 0.0


def test_a_short_walk_goes_at_least_one_lap(policy):
    """走一点点路也至少走一圈；每一段都有平均差；摔了就不算走够。"""
    lap = (Segment("往前", 0.2, {**STILL, "lin_vel_x": 0.2}), Segment("往左转", 0.2, {**STILL, "ang_vel_z": 0.2}))
    result = exam_walk(policy, distance_m=0.001, lap=lap, sensed=False)
    assert result.laps >= 1
    assert set(result.errors) == {"往前", "往左转"}
    assert result.distance_m >= 0.0
    if result.fell:
        assert not result.reached


def test_a_walk_that_cannot_go_anywhere_is_refused(policy):
    """一圈的命令一步也不走（全是站着），就考不了走 1 公里。"""
    with pytest.raises(ValueError, match="大于 0"):
        exam_walk(policy, lap=(Segment("站着", 1.0, STILL),), sensed=False)


def test_a_short_stairs_run_has_not_reached_the_stairs(policy):
    """在楼梯前面 1 m 开始，走 0.5 秒还没到楼梯：上了 0 级，没走完，也还没碰。"""
    trial = StairsTrial("测试", SMALL_STAIRS, bump=True)
    result = exam_stairs(policy, trial, time_s=0.5, sensed=False)
    assert (result.up_steps, result.down_steps) == (0, 0)
    assert not result.finished
    assert not result.bumped
    assert result.seconds <= 0.5 + 1e-9


def test_lying_down_the_small_body_does_not_get_up(policy):
    """测试用的小身体从趴着起不来：没站起来，没有站起来的时刻，骨盆最高也不到站着时的八成。"""
    result = exam_get_up(policy, StartPose.PRONE, deadline_s=0.3, stay_s=0.1, sensed=False)
    assert not result.stood_up
    assert math.isnan(result.seconds)
    assert 0.0 < result.best_height_share < UPRIGHT_HEIGHT_SHARE


def test_the_exam_has_every_part_once_with_the_stand_first():
    """要考的：站（最久的，先开始）、四个方向推、走、三种楼梯、三种躺着，一共 12 份；只考几道也行；没有的题拒绝。"""
    tasks = exam_tasks()
    assert len(tasks) == 1 + len(PUSH_DIRECTIONS) + 1 + 3 + 3
    assert len(set(tasks)) == len(tasks)
    assert tasks[0] == ("stand", "")
    assert exam_tasks(["walk"]) == [("walk", "")]
    with pytest.raises(ValueError, match="没有这几道题"):
        exam_tasks(["fly"])


def test_the_exam_is_taken_with_what_the_body_feels():
    """考试时策略看身体自己感觉到的：测试台不认识的身体（测试用的小身体）就考不了。"""
    with pytest.raises(ValueError, match="做不了状态估计"):
        run_task(str(FIXTURE_DIR / "contract.json"), "get_up", StartPose.PRONE.value)


def test_the_report_has_every_item_and_writes_a_dash_for_what_was_not_measured():
    """结果的表：每道题一行；没量到的写 —，不写 nan；推的细表里倒了以后不再推的写 —。"""
    exam = ExamResult(
        policy="测试",
        date="2026-11-19",
        stand=StandResult(3600.0, False, 1.5, 0.3, math.nan, 0.0, 0.0, math.nan),
        pushes=[
            PushResult(
                "往前", [PushTrial(0.04, 13.0, 4, 0, 3.0, False), PushTrial(0.08, 26.0, 4, 1, 8.0, True)], 0.04, 13.0
            ),
            PushResult("往后", [PushTrial(0.04, 13.0, 4, 4, math.nan, True)], 0.0, 0.0),
        ],
        walk=WalkResult(
            1000.0,
            1400.0,
            23,
            False,
            True,
            {segment.label: {"lin_vel_x": 0.05, "lin_vel_y": 0.04, "ang_vel_z": 0.1} for segment in WALK_LAP},
            {"lin_vel_x": 0.05, "lin_vel_y": 0.04, "ang_vel_z": 0.1},
            120.0,
            0.37,
            0.1,
            0.0,
        ),
        stairs=[StairsResult("平常的", 3, 0, False, True, 12.0, False)],
        get_up=[GetUpResult("趴着", False, math.nan, 0.3), GetUpResult("仰着", True, 4.2, 1.0)],
    )
    table = describe(exam)
    assert "nan" not in table
    for expected in (
        "没倒",
        "往前 4%（13 N）",
        "往后 0%",
        "走了 1000 m",
        "上了 3 级、下了 0 级，摔了",
        "没起来",
        "第 4.2 秒站起来",
    ):
        assert expected in table, expected
    assert "| 4% | 歪 3° | 倒了 4/4 |" in table
    assert "| 8% | 倒了 1/4 | — |" in table
    assert "平均机械功率 — W" in table


def test_the_hardest_landing_of_a_fallen_level_is_kept():
    """一档里倒了的几次，记身上砸到地上最重的那一下（体重的几倍）；都没倒是 nan。"""
    attempts = [
        PushAttempt(10.0, True, 70.0, True, 1.5),
        PushAttempt(10.0, False, 12.0, False, 0.2),
        PushAttempt(10.0, True, 65.0, True, 2.5),
    ]
    assert push_trial(0.3, attempts).fall_impact_weights == 2.5
    assert math.isnan(push_trial(0.1, attempts[1:2]).fall_impact_weights)


def test_a_partial_exam_is_merged_into_the_previous_results():
    """只补考了被推：被推换成新的，别的照旧；换了一个策略就不并，整份换掉。"""
    previous = {
        "policy": "测试",
        "date": "2026-11-19",
        "stand": {"seconds": 3600.0},
        "pushes": [],
        "walk": None,
        "stairs": [],
        "get_up": [],
    }
    fresh = ExamResult(policy="测试", date="2026-11-21", pushes=[PushResult("往前", [], 0.0, 0.0)])
    combined = merged(previous, fresh, ["push"])
    assert combined["stand"] == {"seconds": 3600.0}
    assert combined["pushes"][0]["direction"] == "往前"
    assert combined["date"] == "2026-11-21"
    assert merged({**previous, "policy": "别的"}, fresh, ["push"])["stand"] is None


def test_items_whose_commands_the_brain_cannot_take_are_found_before_the_exam(policy):
    """开考前先问：测试用的小策略练到 1 m/s，走的一圈里有 1.1 m/s，走考不了（说为什么）；
    楼梯（0.3 m/s）、站、推、起来考得了。"""
    found = refusals(policy)
    assert list(found) == ["walk"]
    assert "lin_vel_x = 1.1" in found["walk"]
    assert refusals(policy, ["stairs", "stand"]) == {}


def test_an_item_that_cannot_be_taken_is_not_run():
    """考不了的题不考（不开进程、不跑仿真），结果里写明为什么，那道题的结果是空的。"""
    exam = run_exam(str(FIXTURE_DIR / "contract.json"), ["walk"])
    assert exam.walk is None
    assert "超出了练过的范围" in exam.refused["walk"]


def test_the_report_says_why_an_item_could_not_be_taken():
    """结果的表里，考不了的题写"考不了"和为什么。"""
    exam = ExamResult(
        policy="测试", date="2026-11-21", refused={"walk": "命令 lin_vel_x = 1.1 超出了练过的范围 [-1, 1]"}
    )
    assert "| 走 1 公里 | 考不了：命令 lin_vel_x = 1.1 超出了练过的范围 [-1, 1] |" in describe(exam)


def test_merging_keeps_the_reasons_of_items_not_taken_again():
    """补考几道题时：这几道考不了的理由换成新的（这次考得了就去掉），别的题考不了的理由照旧。"""
    previous = {
        "policy": "测试",
        "date": "2026-11-19",
        "walk": None,
        "stairs": [],
        "refused": {"walk": "旧的理由", "stairs": "楼梯的理由"},
    }
    fresh = ExamResult(policy="测试", date="2026-11-21", refused={})
    assert merged(previous, fresh, ["walk"])["refused"] == {"stairs": "楼梯的理由"}
    fresh = ExamResult(policy="测试", date="2026-11-21", refused={"walk": "新的理由"})
    assert merged(previous, fresh, ["walk"])["refused"] == {"walk": "新的理由", "stairs": "楼梯的理由"}


@pytest.mark.parametrize(
    ("heading", "turn"),
    [(0.0, 0.0), (0.4, -0.2), (-0.4, 0.2), (2.0, -0.5), (-2.0, 0.5), (math.pi - 0.1, -0.5), (-math.pi + 0.1, 0.5)],
    ids=[
        "朝前",
        "往左偏了一点",
        "往右偏了一点",
        "往左偏了很多（夹到最大）",
        "往右偏了很多",
        "快要朝后（往右转回来）",
        "快要朝后（往左转回来）",
    ],
)
def test_on_the_stairs_the_heading_is_held_like_in_training(heading, turn):
    """楼梯上像训练时那样把住方向：转的速度 = 0.5 × 朝向差（要朝 +x），最多 ±0.5 rad/s；往前还是 0.3 m/s。"""
    command = stairs_command(heading)
    assert command["ang_vel_z"] == pytest.approx(turn)
    assert (command["lin_vel_x"], command["lin_vel_y"]) == (0.3, 0.0)
