"""驱动器质量模型（"驱动器有多重"）的测试。"""

import pytest

from nova_body.actuator_mass import (
    QDD_SAMPLES,
    ActuatorSample,
    best_today_model,
    conservative_model,
    fit_power_law,
)

# 拟合的线和每个真实产品的重量最多差这么多（比例）。
FIT_TOLERANCE = 0.35


@pytest.mark.parametrize("sample", QDD_SAMPLES, ids=[sample.name for sample in QDD_SAMPLES])
def test_fit_stays_close_to_every_sample(sample):
    """拟合出来的线，离每个真实的驱动器都不太远。"""
    predicted = best_today_model().mass_kg(sample.peak_torque_nm)
    assert predicted == pytest.approx(sample.mass_kg, rel=FIT_TOLERANCE)


def test_two_points_are_fitted_exactly():
    """两个点正好在一条幂律上时，拟合能把它还原出来。"""
    samples = (
        ActuatorSample("小的", 16.0, 0.4, "测试"),
        ActuatorSample("大的", 256.0, 1.6, "测试"),
    )
    model = fit_power_law("测试", samples)
    assert model.exponent == pytest.approx(0.5)
    assert model.coefficient == pytest.approx(0.1)
    assert model.mass_kg(64.0) == pytest.approx(0.8)


def test_more_torque_means_more_mass():
    """要出的力矩越大，驱动器越重。"""
    model = best_today_model()
    masses = [model.mass_kg(torque) for torque in (10.0, 50.0, 150.0, 300.0)]
    assert masses == sorted(masses)
    assert len(set(masses)) == len(masses)


def test_bigger_actuators_have_higher_torque_density():
    """大的驱动器每公斤出的力矩更大（指数小于 1）。"""
    for model in (best_today_model(), conservative_model()):
        assert 0 < model.exponent < 1


def test_conservative_model_is_heavier_for_big_joints():
    """保守的线不算最好的那个产品，所以大关节算出来更重。"""
    knee_torque_nm = 300.0
    assert conservative_model().mass_kg(knee_torque_nm) > best_today_model().mass_kg(knee_torque_nm)


def test_marks_torque_outside_the_samples():
    """力矩超出样本的范围时要标出来。"""
    model = best_today_model()
    assert not model.is_beyond_data(100.0)
    assert not model.is_beyond_data(model.max_torque_nm)
    assert model.is_beyond_data(model.max_torque_nm + 1.0)
    assert model.is_beyond_data(model.min_torque_nm - 1.0)


@pytest.mark.parametrize("torque_nm", [0.0, -5.0], ids=["力矩是 0", "力矩是负数"])
def test_rejects_non_positive_torque(torque_nm):
    """力矩不是正数时拒绝。"""
    with pytest.raises(ValueError, match="峰值力矩必须大于 0"):
        best_today_model().mass_kg(torque_nm)


def test_rejects_fit_with_too_few_samples():
    """只有一个样本时不能拟合。"""
    with pytest.raises(ValueError, match="至少要 2 个样本"):
        fit_power_law("测试", (ActuatorSample("只有一个", 10.0, 0.3, "测试"),))


def test_rejects_samples_with_non_positive_values():
    """样本里有不是正数的重量时拒绝。"""
    samples = (
        ActuatorSample("正常的", 10.0, 0.3, "测试"),
        ActuatorSample("重量是 0", 20.0, 0.0, "测试"),
    )
    with pytest.raises(ValueError, match="都必须大于 0"):
        fit_power_law("测试", samples)
