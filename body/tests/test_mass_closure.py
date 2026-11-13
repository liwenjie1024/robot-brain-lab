"""质量闭环的测试。"""

from dataclasses import replace

import pytest

from nova_body.actuator_mass import ActuatorMassModel, best_today_model, conservative_model
from nova_body.anthropometry import Segment, segment_count
from nova_body.design import CORE_BODY, FULL_BODY, HAND_ALL_TENDON
from nova_body.mass_closure import Assumptions, MassBudget, MassClosureError, close_mass

BASE = Assumptions()


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
    """腿的力矩按体重等比例放大：70 kg 时膝是 300 N·m。"""
    budget = close_core()
    assert line_for(budget, "knee").torque_nm == pytest.approx(300.0 * budget.total_kg / 70.0, rel=1e-6)


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
    """端的东西不重时，肩用规格里的力矩。"""
    assert line_for(close_core(), "shoulder_pitch").torque_nm == pytest.approx(135.0)


def test_heavy_payload_raises_shoulder_and_elbow_torque():
    """手里端的东西很重时，肩和肘的力矩跟着变大。"""
    budget = close_core(replace(BASE, arm_payload_kg=20.0))
    assert line_for(budget, "shoulder_pitch").torque_nm > 135.0
    assert line_for(budget, "elbow").torque_nm > 100.0


def test_dual_winding_adds_mass_only_with_fallbacks():
    """双绕组多出来的重量，只在算保底的东西时才加。"""
    model = best_today_model()
    with_fallbacks = line_for(close_core(), "knee")
    without_fallbacks = line_for(close_core(replace(BASE, fallbacks=False)), "knee")
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
        ({"strength_factor": 0.0}, "力量的倍数必须大于 0"),
        ({"dual_winding_overhead": -0.1}, "双绕组多出来的比例不能小于 0"),
    ],
    ids=["骨架和线占满了", "电池是负数", "身高是 0", "力量是 0", "双绕组的比例是负数"],
)
def test_rejects_impossible_assumptions(changes, message):
    """假设不合理时拒绝。"""
    with pytest.raises(ValueError, match=message):
        replace(BASE, **changes)
