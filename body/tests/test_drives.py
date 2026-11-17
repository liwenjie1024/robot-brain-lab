"""驱动器的模型的测试：电机常数和真实产品对得上；能一直出的力矩随重量、冷却变；按峰值和发热选；
力矩和转速的关系、发热以后降额；热的两个节点：一直出"能一直出的"力矩，绕组正好热到最高温度。"""

import math
from dataclasses import replace

import pytest

from nova_body.actuator_mass import best_today_model
from nova_body.drives import (
    COOLANT_C,
    CUTOFF_ABOVE_MAX_K,
    DERATE_FROM_C,
    HEAT_REMOVAL_W_PER_KG,
    MIN_KNEE_SPEED_RAD_S,
    STALL_TO_PEAK,
    WINDING_MAX_C,
    Cooling,
    Temperatures,
    continuous_torque_for_mass_nm,
    hot_resistance_factor,
    km_out,
    mass_for_continuous_torque_kg,
    size_drive,
    thermal_network,
    with_cooling,
)

BEST = best_today_model()
COLD = Temperatures(COOLANT_C, COOLANT_C)


def knee(**changes) -> object:
    """一个像膝那样的驱动器：峰值 360 N·m、转到 12.4 rad/s、液冷。"""
    arguments = {
        "peak_torque_nm": 360.0,
        "continuous_torque_nm": 0.0,
        "knee_speed_rad_s": 12.4,
        "cooling": Cooling.LIQUID,
        "mass_model": BEST,
    } | changes
    return size_drive(**arguments)


# 电机常数和散热 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mass_kg", "published"),
    [(0.96, 4.05), (1.42, 4.29)],
    ids=["CubeMars AK10-9 V2.0", "RobStride 04"],
)
def test_motor_constant_matches_the_two_published_actuators(mass_kg, published):
    """电机常数按重量的比例关系算，和公布了电阻、力矩常数的两个产品差不到两成。"""
    assert km_out(mass_kg) == pytest.approx(published, rel=0.2)


def test_bigger_drives_have_bigger_motor_constants():
    """电机越大，同样的铜损出的力矩越大（随重量的 5/6 次方）。"""
    assert km_out(2.0) / km_out(1.0) == pytest.approx(2.0 ** (5 / 6))


def test_liquid_cooling_lets_the_same_drive_hold_2_58_times_the_torque():
    """同一个驱动器，液冷能一直出的力矩是不液冷的 2.58 倍（Paine 等量的）。"""
    ratio = continuous_torque_for_mass_nm(1.0, Cooling.LIQUID) / continuous_torque_for_mass_nm(1.0, Cooling.ENCLOSED)
    assert ratio == pytest.approx(math.sqrt(HEAT_REMOVAL_W_PER_KG[Cooling.LIQUID] / 15.0), rel=1e-9)
    assert ratio == pytest.approx(2.58, abs=0.01)


def test_enclosed_continuous_torque_is_below_the_datasheet_rating():
    """不液冷、包在身体里，比产品写的能一直出的（装在散热片上）小：AK10-9 V2.0 写的是 15 N·m。"""
    assert 0.6 * 15.0 < continuous_torque_for_mass_nm(0.96, Cooling.ENCLOSED) < 15.0


@pytest.mark.parametrize("cooling", list(Cooling), ids=[cooling.value for cooling in Cooling])
@pytest.mark.parametrize("torque", [5.0, 40.0, 150.0], ids=["小", "中", "大"])
def test_mass_for_continuous_torque_is_the_inverse(cooling, torque):
    """要能一直出这么大的力矩至少多重：再按这个重量算回去，正好是这个力矩。"""
    mass = mass_for_continuous_torque_kg(torque, cooling)
    assert continuous_torque_for_mass_nm(mass, cooling) == pytest.approx(torque)


def test_copper_resistance_grows_with_temperature():
    """铜的电阻 20 °C 时是 1 倍，120 °C 时多 39 %。"""
    assert hot_resistance_factor(20.0) == 1.0
    assert hot_resistance_factor(120.0) == pytest.approx(1.393)


@pytest.mark.parametrize(
    "call",
    [
        lambda: km_out(0.0),
        lambda: km_out(-1.0),
        lambda: continuous_torque_for_mass_nm(0.0, Cooling.LIQUID),
        lambda: mass_for_continuous_torque_kg(0.0, Cooling.LIQUID),
    ],
    ids=["重量是 0", "重量是负的", "按 0 kg 算能一直出的", "要一直出的力矩是 0"],
)
def test_refuses_impossible_sizes(call):
    """重量、力矩不是正数：报错。"""
    with pytest.raises(ValueError, match="必须大于 0"):
        call()


# 选驱动器 ---------------------------------------------------------------------------------------------


def test_peak_only_drive_weighs_what_the_peak_line_says():
    """只要峰值：重量就是峰值那条线说的，不是按发热选的。"""
    drive = knee()
    assert drive.mass_kg == pytest.approx(BEST.mass_kg(360.0))
    assert not drive.sized_by_heat
    assert drive.continuous_torque_nm == pytest.approx(continuous_torque_for_mass_nm(drive.mass_kg, Cooling.LIQUID))


def test_a_drive_that_must_hold_a_lot_is_sized_by_heat():
    """要一直出的力矩比照峰值选的能一直出的大：按发热选，更重，正好能一直出这么大。"""
    light = knee()
    heavy = knee(continuous_torque_nm=light.continuous_torque_nm * 1.5)
    assert heavy.sized_by_heat
    assert heavy.mass_kg > light.mass_kg
    assert heavy.continuous_torque_nm == pytest.approx(light.continuous_torque_nm * 1.5)
    assert heavy.required_continuous_nm == pytest.approx(light.continuous_torque_nm * 1.5)


def test_a_small_continuous_need_changes_nothing():
    """要一直出的比能一直出的小：还是按峰值选，一样重。"""
    assert knee(continuous_torque_nm=1.0).mass_kg == pytest.approx(knee().mass_kg)


def test_dual_winding_adds_mass_but_not_strength():
    """双绕组多出来的一成算进重量，不算进电机常数和散热（保守）。"""
    single, dual = knee(), knee(mass_overhead=0.1)
    assert dual.mass_kg == pytest.approx(single.mass_kg * 1.1)
    assert (dual.km_nm_per_sqrt_w, dual.continuous_torque_nm) == (single.km_nm_per_sqrt_w, single.continuous_torque_nm)
    assert dual.motor_mass_kg == single.motor_mass_kg


def test_continuous_torque_never_exceeds_the_peak():
    """很大的驱动器、很小的峰值：能一直出的不会比峰值还大。"""
    drive = knee(peak_torque_nm=10.0, continuous_torque_nm=9.9)
    assert drive.continuous_torque_nm <= drive.peak_torque_nm


@pytest.mark.parametrize(
    ("requested", "knee_speed"),
    [(None, MIN_KNEE_SPEED_RAD_S), (2.0, MIN_KNEE_SPEED_RAD_S), (12.4, 12.4)],
    ids=["没量过", "动作里转得慢", "动作里转得快"],
)
def test_full_torque_reaches_at_least_8_rad_s(requested, knee_speed):
    """峰值力矩至少一直出到 8 rad/s；动作要得更快就出到动作要的。空载转速按电压推得动的倍数算。"""
    drive = knee(knee_speed_rad_s=requested)
    assert drive.knee_speed_rad_s == knee_speed
    assert drive.no_load_speed_rad_s == pytest.approx(knee_speed * STALL_TO_PEAK / (STALL_TO_PEAK - 1))


@pytest.mark.parametrize(
    "changes",
    [
        {"peak_torque_nm": 0.0},
        {"peak_torque_nm": -5.0},
        {"continuous_torque_nm": -1.0},
        {"knee_speed_rad_s": 0.0},
        {"mass_overhead": -0.1},
    ],
    ids=["峰值是 0", "峰值是负的", "一直要出的是负的", "转速是 0", "多出来的比例是负的"],
)
def test_refuses_impossible_requirements(changes):
    """要求不合理：报错，不硬选。"""
    with pytest.raises(ValueError):
        knee(**changes)


def test_friction_and_armature_scale_with_the_drive():
    """干摩擦是峰值的 2 %；转子惯量随重量的 5/3 次方变，和 AK10-9 V2.0 对得上。"""
    drive = knee()
    assert drive.friction_nm == pytest.approx(0.02 * 360.0)
    small = size_drive(48.0, 0.0, None, Cooling.ENCLOSED, BEST)
    assert small.armature_kg_m2 == pytest.approx(1.002e-4 * 81 * (small.mass_kg / 0.96) ** (5 / 3))


def test_with_cooling_keeps_the_mass_and_changes_the_heat():
    """同一个驱动器换成不液冷：重量不变，能一直出的变小、热得慢（热阻大）。"""
    liquid = knee()
    enclosed = with_cooling(liquid, Cooling.ENCLOSED)
    assert enclosed.mass_kg == liquid.mass_kg
    assert enclosed.continuous_torque_nm < liquid.continuous_torque_nm
    assert enclosed.thermal.housing_time_constant_s > liquid.thermal.housing_time_constant_s


# 力矩和转速 -------------------------------------------------------------------------------------------


def test_full_torque_both_ways_when_standing_still_and_cold():
    """不转、不热：两个方向都能出峰值。"""
    drive = knee()
    assert drive.torque_limits_nm(0.0, COLD) == (-360.0, 360.0)


def test_pushing_falls_off_above_the_knee_speed_but_braking_does_not():
    """转得比"峰值出到的转速"快：往转的方向推的力直线变小，到空载转速是 0；往反方向刹不受电压限。"""
    drive = knee()
    middle = (drive.knee_speed_rad_s + drive.no_load_speed_rad_s) / 2
    assert drive.torque_limits_nm(drive.knee_speed_rad_s, COLD) == (-360.0, 360.0)
    assert drive.torque_limits_nm(middle, COLD) == pytest.approx((-360.0, 180.0))
    assert drive.torque_limits_nm(drive.no_load_speed_rad_s, COLD) == (-360.0, 0.0)
    assert drive.torque_limits_nm(drive.no_load_speed_rad_s * 2, COLD) == (-360.0, 0.0)


def test_turning_the_other_way_mirrors_the_limits():
    """往反方向转：推和刹也反过来。"""
    drive = knee()
    middle = (drive.knee_speed_rad_s + drive.no_load_speed_rad_s) / 2
    assert drive.torque_limits_nm(-middle, COLD) == pytest.approx((-180.0, 360.0))


@pytest.mark.parametrize(
    ("winding_c", "share"),
    [
        (COOLANT_C, None),
        (DERATE_FROM_C, None),
        ((DERATE_FROM_C + WINDING_MAX_C) / 2, 0.5),
        (WINDING_MAX_C, 1.0),
    ],
    ids=["冷的", "刚到降额的温度", "降额的一半", "最高温度"],
)
def test_derating_goes_from_peak_to_continuous(winding_c, share):
    """绕组从 100 °C 到 120 °C，力矩的上限从峰值直线降到能一直出的。"""
    drive = knee()
    limit = drive.thermal_limit_nm(winding_c)
    expected = 360.0 if share is None else 360.0 + share * (drive.continuous_torque_nm - 360.0)
    assert limit == pytest.approx(expected)


def test_too_hot_drops_to_zero_and_never_below():
    """超过最高温度：再往下降，超过 10 K 就是 0（保护），不会是负的。"""
    drive = knee()
    assert drive.thermal_limit_nm(WINDING_MAX_C + CUTOFF_ABOVE_MAX_K / 2) == pytest.approx(
        drive.continuous_torque_nm / 2
    )
    assert drive.thermal_limit_nm(WINDING_MAX_C + CUTOFF_ABOVE_MAX_K) == 0.0
    assert drive.thermal_limit_nm(WINDING_MAX_C + 50) == 0.0


def test_hot_drive_limits_both_ways():
    """绕组热了：推和刹都按温度降。"""
    drive = knee()
    hot = Temperatures(WINDING_MAX_C, WINDING_MAX_C)
    low, high = drive.torque_limits_nm(1.0, hot)
    assert (low, high) == pytest.approx((-drive.continuous_torque_nm, drive.continuous_torque_nm))


def test_friction_opposes_the_turning():
    """摩擦顺着转的方向挡：不转是 0；转得越快越大。"""
    drive = knee()
    assert drive.friction_nm_at(0.0) == 0.0
    assert drive.friction_nm_at(1.0) == pytest.approx(drive.friction_nm + drive.viscous_nm_s)
    assert drive.friction_nm_at(-1.0) == pytest.approx(-drive.friction_nm_at(1.0))


# 热 --------------------------------------------------------------------------------------------------


def test_holding_the_continuous_torque_heats_the_winding_to_the_maximum():
    """一直出"能一直出的"力矩：过很久，绕组正好热到最高温度（120 °C）。"""
    drive = knee()
    settled = drive.heat(COLD, drive.continuous_torque_nm, 30 * drive.thermal.housing_time_constant_s)
    assert settled.winding_c == pytest.approx(WINDING_MAX_C, abs=0.5)
    assert COOLANT_C < settled.housing_c < settled.winding_c


def test_resting_cools_back_to_the_coolant():
    """不出力：热的驱动器慢慢凉回冷却液的温度。"""
    drive = knee()
    hot = Temperatures(WINDING_MAX_C, 90.0)
    cooled = drive.heat(hot, 0.0, 30 * drive.thermal.housing_time_constant_s)
    assert cooled.winding_c == pytest.approx(COOLANT_C, abs=0.1)
    assert cooled.housing_c == pytest.approx(COOLANT_C, abs=0.1)


def test_winding_heats_faster_than_the_housing():
    """出峰值几秒：绕组一下子热起来，身子还没怎么热。"""
    drive = knee()
    after = drive.heat(COLD, drive.peak_torque_nm, 5.0)
    assert after.winding_c - COOLANT_C > 5 * (after.housing_c - COOLANT_C)


def test_no_time_no_change_and_negative_time_refused():
    """过 0 秒：温度不变。时间是负的：报错。"""
    drive = knee()
    assert drive.heat(COLD, 100.0, 0.0) == COLD
    with pytest.raises(ValueError, match="时间不能是负的"):
        drive.heat(COLD, 100.0, -1.0)


def test_peak_torque_can_only_be_held_for_seconds():
    """峰值只能出一会儿：一直出峰值，一两分钟内绕组就到降额的温度。"""
    drive = knee()
    seconds, state = 0.0, COLD
    while state.winding_c < DERATE_FROM_C and seconds < 600:
        state = drive.heat(state, drive.peak_torque_nm, 1.0)
        seconds += 1
    assert seconds < 120


def test_thermal_network_settles_80_k_above_the_coolant():
    """热的网络：一直散走能散的热时，绕组比冷却液热 80 K（两段热阻加起来）。"""
    for cooling in Cooling:
        network = thermal_network(1.5, cooling)
        heat_w = HEAT_REMOVAL_W_PER_KG[cooling] * 1.5
        total = network.winding_to_housing_k_per_w + network.housing_to_coolant_k_per_w
        assert heat_w * total == pytest.approx(WINDING_MAX_C - COOLANT_C)


def test_drive_spec_is_a_value():
    """选好的驱动器是一个值：一样的要求选出一样的，可以当字典的键（报告里按它合并）。"""
    assert knee() == knee()
    assert len({knee(), knee(), replace(knee(), friction_nm=1.0)}) == 2
