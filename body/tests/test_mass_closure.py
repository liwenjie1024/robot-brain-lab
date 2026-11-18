"""质量闭环的测试。"""

from dataclasses import replace

import pytest

from nova_body.actuator_mass import ActuatorMassModel, best_today_model, conservative_model
from nova_body.anthropometry import Segment, segment_count
from nova_body.design import CORE_BODY, FULL_BODY, HAND_ALL_TENDON, PARALLEL_TARGETS, Strength
from nova_body.drives import Cooling, continuous_torque_for_mass_nm
from nova_body.mass_closure import (
    Assumptions,
    MassBudget,
    MassClosureError,
    close_mass,
    group_drives,
    joint_peak_torques_nm,
)

BASE = Assumptions()


def group_of(key: str):
    return next(group for group in CORE_BODY.joint_groups() if group.key == key)


def close_core(assumptions: Assumptions = BASE) -> MassBudget:
    """用今天最好的驱动算核心版。"""
    return close_mass(CORE_BODY, assumptions, best_today_model())


def line_for(budget: MassBudget, key: str):
    """找出某一组关节的那一行。"""
    return next(line for line in budget.actuators if line.key == key)


def test_core_body_converges_to_a_plausible_mass():
    """核心版能收敛，体重在人形机器人的范围里。"""
    budget = close_core()
    assert 40 < budget.total_kg < 120
    assert budget.iterations > 1


def test_repeated_runs_give_the_same_result():
    """同样的输入算两次，结果一样。"""
    assert close_core() == close_core()


def test_categories_add_up_to_total():
    """各部分的重量加起来等于体重。"""
    budget = close_core()
    assert sum(budget.by_category.values()) == pytest.approx(budget.total_kg)


def test_segments_add_up_to_total():
    """各段的重量（成对的算两侧）加起来等于体重。"""
    budget = close_core()
    total = sum(budget.by_segment[segment] * segment_count(segment) for segment in Segment)
    assert total == pytest.approx(budget.total_kg)


def test_full_body_is_heavier_than_core_body():
    """完整版比核心版重。"""
    assert close_mass(FULL_BODY, BASE, best_today_model()).total_kg > close_core().total_kg


def test_conservative_actuators_make_the_body_heavier():
    """用保守的驱动，身体更重。"""
    assert close_mass(CORE_BODY, BASE, conservative_model()).total_kg > close_core().total_kg


def test_one_added_kilogram_costs_more_than_one_kilogram():
    """多带 1 kg，总重加的不止 1 kg：骨架、线、腿的驱动都要跟着变重。"""
    assert close_core().growth_per_added_kg > 1.0


def test_leg_torque_scales_with_body_mass():
    """腿的力矩按体重等比例放大：设计里写的是 70 kg 时的（动作算的目标，或者人的峰值 300 N·m）。"""
    budget = close_core()
    knee = group_of("knee").daily_torques_nm[0]
    assert line_for(budget, "knee").torque_nm == pytest.approx(knee * budget.total_kg / 70.0, rel=1e-6)
    peak = close_core(replace(BASE, strength=Strength.HUMAN_PEAK))
    assert line_for(peak, "knee").torque_nm == pytest.approx(300.0 * peak.total_kg / 70.0, rel=1e-6)


def test_motion_targets_make_a_lighter_body_than_human_peaks():
    """按动作算的力量（做家务的那一档）比按人的峰值轻。"""
    assert close_core().total_kg < close_core(replace(BASE, strength=Strength.HUMAN_PEAK)).total_kg


def test_half_strength_body_is_lighter():
    """力量减半的身体更轻。"""
    assert close_core(replace(BASE, strength_factor=0.5)).total_kg < close_core().total_kg


def test_bigger_battery_makes_the_body_heavier():
    """电池越大，身体越重；没有电池也能算。"""
    masses = [close_core(replace(BASE, battery_kwh=kwh)).total_kg for kwh in (0.0, 1.0, 2.3)]
    assert masses == sorted(masses)
    assert len(set(masses)) == len(masses)


def test_removing_liquid_cooling_saves_more_than_its_own_mass():
    """去掉液冷省下的重量，比液冷本身的重量多。"""
    saved = close_core().total_kg - close_core(replace(BASE, liquid_cooling=False)).total_kg
    assert saved > BASE.liquid_cooling_kg


def test_all_tendon_hand_is_heavier_than_in_hand_drive():
    """全肌腱的手加上前臂里的驱动，比驱动放在手里的更重。"""
    all_tendon = replace(CORE_BODY, hand=HAND_ALL_TENDON)
    assert close_mass(all_tendon, BASE, best_today_model()).total_kg > close_core().total_kg


def test_shoulder_uses_spec_torque_for_normal_payload():
    """端的东西不重时，肩用设计里的力矩（动作算的目标；按人的峰值时是 135 N·m）。"""
    shoulder = group_of("shoulder_pitch").daily_torques_nm[0]
    assert line_for(close_core(), "shoulder_pitch").torque_nm == pytest.approx(shoulder)
    peak = close_core(replace(BASE, strength=Strength.HUMAN_PEAK))
    assert line_for(peak, "shoulder_pitch").torque_nm == pytest.approx(135.0)


def test_heavy_payload_raises_shoulder_and_elbow_torque():
    """手里端的东西很重时，肩和肘的力矩跟着变大。"""
    budget = close_core(replace(BASE, arm_payload_kg=20.0))
    assert line_for(budget, "shoulder_pitch").torque_nm > 135.0
    assert line_for(budget, "elbow").torque_nm > 100.0


def test_dual_winding_adds_mass_only_with_fallbacks():
    """双绕组多出来的重量，只在算保底的东西时才加。"""
    model = best_today_model()
    with_fallbacks = line_for(close_core(), "hip_pitch")
    without_fallbacks = line_for(close_core(replace(BASE, fallbacks=False)), "hip_pitch")
    assert with_fallbacks.mass_each_kg == pytest.approx(model.mass_kg(with_fallbacks.torque_nm) * 1.10)
    assert without_fallbacks.mass_each_kg == pytest.approx(model.mass_kg(without_fallbacks.torque_nm))


def test_marks_leg_torque_beyond_the_samples():
    """腿的力矩超出了样本的范围时，那一行要标出来。"""
    weak_data = replace(best_today_model(), max_torque_nm=100.0)
    budget = close_mass(CORE_BODY, BASE, weak_data)
    assert line_for(budget, "knee").beyond_data
    assert not line_for(budget, "neck_upper").beyond_data


def test_fixed_mass_groups_count_their_actuators():
    """按固定重量估的组：个数是驱动器的个数，一组的总重不变。"""
    budget = close_mass(FULL_BODY, BASE, best_today_model())
    scapula = line_for(budget, "scapula")
    assert scapula.count == 6
    assert scapula.total_kg == pytest.approx(1.8)
    assert scapula.torque_nm is None
    passive_toes = line_for(budget, "toes_arch")
    assert passive_toes.count == 2
    assert passive_toes.total_kg == pytest.approx(0.2)


# 驱动器的模型（1.6 步） ------------------------------------------------------------------------------


def test_every_driven_group_records_its_drives():
    """闭合以后每组关节（一侧）每个驱动器选的样子都记下来；按固定重量估的组没有。"""
    budget = close_core()
    for group in CORE_BODY.joint_groups():
        assert len(group_drives(group, budget)) == group.actuators
    eyes = next(group for group in FULL_BODY.joint_groups() if group.key == "eyes")
    assert group_drives(eyes, close_mass(FULL_BODY, BASE, best_today_model())) == ()


def test_knee_is_sized_by_heat_and_can_hold_what_it_must():
    """膝要一直出的力（蹲着干活）比照峰值选的驱动器能一直出的大：按发热选，更重，正好能一直出这么大。"""
    knee = line_for(close_core(), "knee")
    drive = knee.drive
    assert drive.sized_by_heat
    assert drive.motor_mass_kg > best_today_model().mass_kg(knee.torque_nm)
    assert drive.continuous_torque_nm == pytest.approx(drive.required_continuous_nm)
    assert drive.continuous_torque_nm == pytest.approx(
        continuous_torque_for_mass_nm(drive.motor_mass_kg, Cooling.LIQUID)
    )


def test_parallel_pairs_use_the_share_measured_in_the_motions():
    """并联的踝：每个驱动器按动作里同一刻要的选（随体重放大），比两个峰值同时来小；两个是一样的零件，并成一行。"""
    budget = close_core()
    ankle = [line for line in budget.actuators if line.key == "ankle"]
    assert len(ankle) == 1
    assert ankle[0].count == 4
    assert ankle[0].torque_nm == pytest.approx(PARALLEL_TARGETS["ankle"] * budget.total_kg / 70.0, rel=1e-6)


def test_without_continuous_needs_only_the_peak_counts():
    """人的峰值那一档不算发热：每个驱动器的重量就是峰值那条线说的。"""
    budget = close_core(replace(BASE, strength=Strength.HUMAN_PEAK))
    model = best_today_model()
    for line in budget.actuators:
        assert not line.drive.sized_by_heat
        assert line.drive.motor_mass_kg == pytest.approx(model.mass_kg(line.torque_nm))


def test_taller_bodies_are_heavier():
    """身高越高越重：随体重的力矩按"体重 x 身高"放大，皮肤按身高²变。"""
    masses = [close_core(replace(BASE, height_m=height)).total_kg for height in (1.60, 1.70, 1.80)]
    assert masses == sorted(masses)
    assert len(set(masses)) == 3


def test_leg_torque_scales_with_mass_times_height():
    """腿的力矩 = 70 kg、1.70 m 时的目标 x 体重的倍数 x 身高的倍数。"""
    tall = replace(BASE, height_m=1.87)
    budget = close_core(tall)
    knee = group_of("knee").daily_torques_nm[0]
    expected = knee * budget.total_kg / 70.0 * 1.87 / 1.70
    assert line_for(budget, "knee").torque_nm == pytest.approx(expected, rel=1e-6)


def test_skin_scales_with_the_body_surface():
    """皮肤、软外壳、外衣按表面积（身高²）变：1.70 m 时是写的数。"""
    assert BASE.skin_kg == pytest.approx(BASE.skin_and_cover_kg)
    assert replace(BASE, height_m=1.87).skin_kg == pytest.approx(BASE.skin_and_cover_kg * 1.21)
    budget = close_core(replace(BASE, height_m=1.87))
    assert budget.by_category["皮肤、软外壳、外衣"] == pytest.approx(BASE.skin_and_cover_kg * 1.21)


def item_for(budget: MassBudget, key: str):
    """找出某一样东西（电池、电脑……）。"""
    return next(item for item in budget.items if item.key == key)


def test_every_segment_is_parts_plus_its_share_of_structure():
    """每一段的重量 = 这一段里的驱动器 + 这一段里的东西 + 分到这一段的骨架、线和皮肤。"""
    budget = close_core()
    for segment in Segment:
        parts = sum(part.total_kg for part in (*budget.actuators, *budget.items) if part.segment == segment)
        expected = parts / segment_count(segment) + budget.spread_on_kg(segment)
        assert budget.by_segment[segment] == pytest.approx(expected)


def test_spread_mass_is_structure_wiring_and_skin():
    """按比例分的重量就是骨架、线、皮肤三样。"""
    budget = close_core()
    expected = budget.by_category["骨架"] + budget.by_category["线"] + budget.by_category["皮肤、软外壳、外衣"]
    assert budget.spread_kg == pytest.approx(expected)


def test_battery_is_above_the_lumbar_joint_and_fallbacks_below():
    """电池、电脑、液冷、超级电容在胸和腹（超级电容 1.6 步从骨盆挪上来：骨盆里满了）；安全板、髋的制动器在骨盆；
    膝的制动器在大腿。"""
    budget = close_core()
    assert {item_for(budget, key).segment for key in ("battery", "computer", "cooling", "supercapacitor")} == {
        Segment.CHEST
    }
    assert {item_for(budget, key).segment for key in ("safety_board", "hip_brake")} == {Segment.PELVIS}
    assert item_for(budget, "knee_brake").segment == Segment.THIGH
    assert item_for(budget, "battery").mass_each_kg == pytest.approx(5.0)


def test_items_without_mass_are_not_listed():
    """重量是 0 的东西不列：核心版的手在前臂里没有驱动；不要保底时没有制动器。"""
    keys = {item.key for item in close_core().items}
    assert "hand_drive" not in keys
    assert "extra" not in keys
    without_fallbacks = {item.key for item in close_core(replace(BASE, fallbacks=False)).items}
    assert without_fallbacks.isdisjoint({"supercapacitor", "safety_board", "hip_brake", "knee_brake"})


def test_all_tendon_hand_puts_its_drives_in_the_forearm():
    """全肌腱的手：驱动放在前臂里，一侧 12 个绞盘共 1.44 kg。"""
    budget = close_mass(replace(CORE_BODY, hand=HAND_ALL_TENDON), BASE, best_today_model())
    drive = item_for(budget, "hand_drive")
    assert drive.segment == Segment.FOREARM
    assert drive.count == 2
    assert drive.mass_each_kg == pytest.approx(1.44)


def test_joint_peak_torques_follow_the_closed_mass():
    """闭合以后每个关节的峰值力矩：腿的随体重放大，颈的不变，并联的一组每个自由度各算各的。"""
    budget = close_core()
    scale = budget.total_kg / 70.0
    groups = {group.key: group for group in CORE_BODY.joint_groups()}
    knee, ankle = groups["knee"].daily_torques_nm, groups["ankle"].daily_torques_nm
    assert joint_peak_torques_nm(groups["knee"], BASE, budget) == pytest.approx((knee[0] * scale,))
    assert joint_peak_torques_nm(groups["ankle"], BASE, budget) == pytest.approx((ankle[0] * scale, ankle[1] * scale))
    assert joint_peak_torques_nm(groups["neck_upper"], BASE, budget) == pytest.approx((20.0, 20.0))
    shoulder = groups["shoulder_pitch"].daily_torques_nm
    assert joint_peak_torques_nm(groups["shoulder_pitch"], BASE, budget) == pytest.approx(shoulder)


def test_joint_peak_torques_of_fixed_mass_group_are_empty():
    """按固定重量估的组没有力矩。"""
    budget = close_mass(FULL_BODY, BASE, best_today_model())
    eyes = next(group for group in FULL_BODY.joint_groups() if group.key == "eyes")
    assert joint_peak_torques_nm(eyes, BASE, budget) == ()


def test_fails_when_actuators_are_too_heavy_to_close():
    """驱动器太重时闭不上，要报错而不是给一个假的数。"""
    hopeless = ActuatorMassModel(
        "每 N·m 一公斤", coefficient=1.0, exponent=1.0, min_torque_nm=1.0, max_torque_nm=1000.0
    )
    with pytest.raises(MassClosureError, match="闭不上"):
        close_mass(CORE_BODY, BASE, hopeless)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"structure_fraction": 0.7, "wiring_fraction": 0.3}, "加起来必须小于 1"),
        ({"battery_kwh": -1.0}, "电池的电量不能小于 0"),
        ({"height_m": 0.0}, "身高必须大于 0"),
        ({"reference_height_m": 0.0}, "参考身高必须大于 0"),
        ({"strength_factor": 0.0}, "力量的倍数必须大于 0"),
        ({"dual_winding_overhead": -0.1}, "双绕组多出来的比例不能小于 0"),
    ],
    ids=["骨架和线占满了", "电池是负数", "身高是 0", "参考身高是 0", "力量是 0", "双绕组的比例是负数"],
)
def test_rejects_impossible_assumptions(changes, message):
    """假设不合理时拒绝。"""
    with pytest.raises(ValueError, match=message):
        replace(BASE, **changes)


def test_lumbar_pushers_are_split_between_pelvis_and_chest():
    """腰的推杆跨在腰的关节上：每个推杆的重量一半算骨盆、一半算胸；加起来还是整个推杆的重量。"""
    budget = close_core()
    lines = [line for line in budget.actuators if line.key == "lumbar_pitch_roll"]
    assert {line.segment for line in lines} == {Segment.PELVIS, Segment.CHEST}
    assert all(line.share == pytest.approx(0.5) for line in lines)
    drive = lines[0].drive
    assert sum(line.total_kg for line in lines) == pytest.approx(2 * drive.mass_kg)
    others = [line for line in budget.actuators if line.key != "lumbar_pitch_roll"]
    assert all(line.share == 1.0 for line in others)
