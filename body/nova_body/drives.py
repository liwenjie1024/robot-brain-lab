"""驱动器的模型（1.6 步）：一个关节的驱动器能出多大的力、能一直出多大、转多快、怎么发热、多重。

按电机的物理来定，不只靠"峰值力矩 → 重量"的一条线：
- 峰值力矩（磁和电流）：重量照真实产品的峰值拟合（actuator_mass）。峰值只能出几秒。
- 能一直出的力矩（发热）：铜损 = (力矩 ÷ 电机常数)²，电机越大电机常数越大；能散走多少热看怎么冷却。
  一直要出大力的关节（蹲着干活、端着东西站），驱动器要按发热选得更大。
- 转速：选绕组，让峰值力矩一直出到要的转速，再往上按电压掉下去。绕组只改电流，不改重量和发热。

发热用两个"热的节点"：绕组（热得快）和驱动器的身子（热得慢），热经身子走到冷却液（或者身体里面的空气）。
数都写在下面，每个都有来源或者说清楚是假设；报告（docs/报告/驱动器.md）把它们列出来。
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

import numpy as np

from nova_body.actuator_mass import ActuatorMassModel


class Cooling(StrEnum):
    """驱动器怎么冷却（机体规格第 12 节）。"""

    LIQUID = "绕组直接液冷"
    ENCLOSED = "不液冷，包在身体里"


# 电机常数（输出端，N·m/√W）：力矩 = 电机常数 x √铜损。两个公布了电阻和力矩常数的产品：
# CubeMars AK10-9 V2.0 KV100（0.96 kg）电机端 0.45，减速比 9 → 4.05；
# RobStride 04（1.42 kg）输出端 2.1 N·m/Arms、线电阻 0.16 Ω → 4.29。取两者的几何平均。
# 形状相似的电机，电机常数² 随直径⁴ x 长度变，所以随重量的 5/6 次方变。
KM_REFERENCE_NM_PER_SQRT_W = 4.17
KM_REFERENCE_MASS_KG = 1.168
KM_MASS_EXPONENT = 5.0 / 6.0
# 每公斤驱动器能一直散走多少瓦（绕组比冷却液或者身体里面的空气热 80 K 时）。
# 不液冷：AK10-9 V2.0 能一直出 15 N·m，按它的电机常数约是 14~20 W，0.96 kg，取 15 W/kg。
# 绕组直接液冷：同一个电机加液冷，能一直出的力矩是原来的 2.58 倍（Paine 等，Actuators 2015），
# 铜损就是 2.58² 倍，取 100 W/kg。
HEAT_REMOVAL_W_PER_KG: dict[Cooling, float] = {Cooling.ENCLOSED: 15.0, Cooling.LIQUID: 100.0}
# 冷却液（或者身体里面的空气）和绕组最高的温度（°C）。绕组的绝缘按 B 级（130 °C）留 10 K。
COOLANT_C = 40.0
WINDING_MAX_C = 120.0
# 绕组过了这个温度，驱动器开始把力矩的上限往"能一直出的"降；超过最高温度 10 K 就降到 0（保护）。
DERATE_FROM_C = 100.0
CUTOFF_ABOVE_MAX_K = 10.0
# 铜的电阻随温度变：每 K 多 0.393 %。电机常数是 20 °C 时的。
COPPER_TEMPERATURE_COEFFICIENT = 0.00393
REFERENCE_C = 20.0
# 两个节点：铜约占驱动器重量的 15 %（比热 385 J/kg/K），其它的（钢、铝）按 600 J/kg/K。
# 热阻：从绕组到身子占三成，从身子到冷却液占七成。这几个是假设，用来定"热得多快"，不改变最后热到多少。
COPPER_FRACTION = 0.15
COPPER_HEAT_J_PER_KG_K = 385.0
HOUSING_HEAT_J_PER_KG_K = 600.0
WINDING_SHARE_OF_RESISTANCE = 0.3
# 电压能推动的最大力矩（不限电流时）是峰值的几倍：RobStride 04 在 48 V 时约 4.3 倍。
# 绕组照这个选：峰值力矩一直出到要的转速，往上按电压直线掉到空载转速。
STALL_TO_PEAK = 4.0
# 峰值力矩至少一直出到这个转速（约 460°/s）：动作里转得慢的、没量过转速的关节（颈、腕……）也一样，
# 平常也要能很快地伸手、转头。绕组只改电流，不改重量和发热，所以不多花重量。
MIN_KNEE_SPEED_RAD_S = 8.0
# 摩擦：反推一个不通电的驱动器要的力矩约是峰值的 2 %（AK10-9 V2.0：0.8 N·m）；
# 空载转到最快（200 rpm）时，摩擦加上转动的损耗约是峰值的 3.5 %（RobStride 04：空载电流 2 A x 2.1 N·m/A），
# 多出来的 1.5 % 当作随转速的。电机转多快只看关节转多快（减速比都差不多），所以按关节的转速算。
COULOMB_SHARE_OF_PEAK = 0.02
VISCOUS_SHARE_OF_PEAK_PER_RAD_S = (0.035 - COULOMB_SHARE_OF_PEAK) / (200.0 * 2.0 * math.pi / 60.0)
# 转子折算到关节上的惯量 = 减速比² x 转子的惯量。AK10-9 V2.0：转子 1002 g·cm²、减速比 9、0.96 kg。
# 形状相似的电机，转子的惯量随重量的 5/3 次方变。
ARMATURE_REFERENCE_KG_M2 = 1.002e-4 * 9**2
ARMATURE_REFERENCE_MASS_KG = 0.96
ARMATURE_MASS_EXPONENT = 5.0 / 3.0


def km_out(mass_kg: float) -> float:
    """这么重的驱动器，输出端的电机常数（N·m/√W，20 °C）。"""
    _require_positive("驱动器的重量", mass_kg)
    return KM_REFERENCE_NM_PER_SQRT_W * (mass_kg / KM_REFERENCE_MASS_KG) ** KM_MASS_EXPONENT


def heat_removal_w(mass_kg: float, cooling: Cooling) -> float:
    """这么重的驱动器，绕组热到最高温度时能一直散走多少瓦。"""
    _require_positive("驱动器的重量", mass_kg)
    return HEAT_REMOVAL_W_PER_KG[cooling] * mass_kg


def hot_resistance_factor(temperature_c: float) -> float:
    """铜的电阻在这个温度是 20 °C 时的几倍。"""
    return 1.0 + COPPER_TEMPERATURE_COEFFICIENT * (temperature_c - REFERENCE_C)


def continuous_torque_for_mass_nm(mass_kg: float, cooling: Cooling) -> float:
    """这么重的驱动器能一直出的力矩：铜损（绕组在最高温度时）正好等于能散走的热。"""
    allowed_w = heat_removal_w(mass_kg, cooling) / hot_resistance_factor(WINDING_MAX_C)
    return km_out(mass_kg) * math.sqrt(allowed_w)


# 能一直出的力矩随重量的这个次方变（电机常数的 5/6 次方，加上散热的 1/2 次方）。
CONTINUOUS_MASS_EXPONENT = KM_MASS_EXPONENT + 0.5


def mass_for_continuous_torque_kg(torque_nm: float, cooling: Cooling) -> float:
    """要能一直出这么大的力矩，驱动器至少多重。"""
    _require_positive("能一直出的力矩", torque_nm)
    at_reference = continuous_torque_for_mass_nm(KM_REFERENCE_MASS_KG, cooling)
    return KM_REFERENCE_MASS_KG * (torque_nm / at_reference) ** (1.0 / CONTINUOUS_MASS_EXPONENT)


@dataclass(frozen=True)
class ThermalNetwork:
    """两个节点的热：绕组 → 驱动器的身子 → 冷却液。电阻 K/W，热容 J/K。"""

    winding_to_housing_k_per_w: float
    housing_to_coolant_k_per_w: float
    winding_j_per_k: float
    housing_j_per_k: float

    @property
    def winding_time_constant_s(self) -> float:
        """绕组自己热起来要多久（只看绕组到身子这一段）。"""
        return self.winding_to_housing_k_per_w * self.winding_j_per_k

    @property
    def housing_time_constant_s(self) -> float:
        """驱动器的身子热起来要多久。"""
        return self.housing_to_coolant_k_per_w * self.housing_j_per_k


def thermal_network(mass_kg: float, cooling: Cooling) -> ThermalNetwork:
    """按重量和冷却定的热：一直散走 heat_removal_w 瓦时，绕组正好比冷却液热 80 K。"""
    total = (WINDING_MAX_C - COOLANT_C) / heat_removal_w(mass_kg, cooling)
    return ThermalNetwork(
        winding_to_housing_k_per_w=WINDING_SHARE_OF_RESISTANCE * total,
        housing_to_coolant_k_per_w=(1.0 - WINDING_SHARE_OF_RESISTANCE) * total,
        winding_j_per_k=COPPER_FRACTION * mass_kg * COPPER_HEAT_J_PER_KG_K,
        housing_j_per_k=(1.0 - COPPER_FRACTION) * mass_kg * HOUSING_HEAT_J_PER_KG_K,
    )


@dataclass(frozen=True)
class Temperatures:
    """一个驱动器的绕组和身子现在多热（°C）。"""

    winding_c: float
    housing_c: float


COLD = Temperatures(COOLANT_C, COOLANT_C)


@dataclass(frozen=True)
class DriveSpec:
    """一个关节的驱动器：选好以后的样子。力矩都在关节上（输出端）。

    peak_torque_nm：能出几秒的最大力矩（电流的上限）。continuous_torque_nm：能一直出的（绕组热到最高温度）。
    knee_speed_rad_s：峰值力矩能一直出到的转速；no_load_speed_rad_s：再往上力矩直线掉到 0 的转速（只在出力推着转时）。
    required_continuous_nm 是选的时候要求一直出的（0 是没要求）；sized_by_heat：重量是按发热定的，不是按峰值。
    motor_mass_kg 是算电机常数、发热用的重量（不算双绕组多出来的那一份）。
    """

    peak_torque_nm: float
    continuous_torque_nm: float
    knee_speed_rad_s: float
    no_load_speed_rad_s: float
    mass_kg: float
    cooling: Cooling
    km_nm_per_sqrt_w: float
    thermal: ThermalNetwork
    friction_nm: float
    viscous_nm_s: float
    armature_kg_m2: float
    required_continuous_nm: float = 0.0
    sized_by_heat: bool = False
    motor_mass_kg: float = 0.0

    def torque_limits_nm(self, speed_rad_s: float, temperature: Temperatures) -> tuple[float, float]:
        """在这个转速、这个温度下，驱动器能出的力矩的范围（下限、上限）。

        往转的方向推（出功）时受电压限：快到一定程度就推不动了；往反方向刹（收功）时不受电压限。
        绕组热了，两个方向都按温度降。
        """
        thermal = self.thermal_limit_nm(temperature.winding_c)
        pushing = min(thermal, self.speed_limit_nm(abs(speed_rad_s)))
        if speed_rad_s > 0:
            return -thermal, pushing
        if speed_rad_s < 0:
            return -pushing, thermal
        return -pushing, pushing

    def speed_limit_nm(self, speed_rad_s: float) -> float:
        """往转的方向推时，电压在这个转速下能推出多大的力矩。"""
        if speed_rad_s <= self.knee_speed_rad_s:
            return self.peak_torque_nm
        if speed_rad_s >= self.no_load_speed_rad_s:
            return 0.0
        fraction = (self.no_load_speed_rad_s - speed_rad_s) / (self.no_load_speed_rad_s - self.knee_speed_rad_s)
        return self.peak_torque_nm * fraction

    def thermal_limit_nm(self, winding_c: float) -> float:
        """绕组这么热时，力矩的上限：先从峰值降到能一直出的，再超过最高温度就降到 0。"""
        if winding_c <= DERATE_FROM_C:
            return self.peak_torque_nm
        if winding_c <= WINDING_MAX_C:
            share = (winding_c - DERATE_FROM_C) / (WINDING_MAX_C - DERATE_FROM_C)
            return self.peak_torque_nm + share * (self.continuous_torque_nm - self.peak_torque_nm)
        over = (winding_c - WINDING_MAX_C) / CUTOFF_ABOVE_MAX_K
        return max(0.0, self.continuous_torque_nm * (1.0 - over))

    def copper_loss_w(self, torque_nm: float, winding_c: float) -> float:
        """出这么大的力矩时绕组发多少热（铜损，绕组越热电阻越大）。"""
        return (torque_nm / self.km_nm_per_sqrt_w) ** 2 * hot_resistance_factor(winding_c)

    def friction_nm_at(self, speed_rad_s: float) -> float:
        """在这个转速下驱动器自己的摩擦（顺着转的方向为正）：干摩擦加上随转速的。"""
        coulomb = 0.0 if speed_rad_s == 0 else math.copysign(self.friction_nm, speed_rad_s)
        return coulomb + self.viscous_nm_s * speed_rad_s

    def heat(self, temperature: Temperatures, torque_nm: float, seconds: float) -> Temperatures:
        """出着这么大的力矩过了 seconds 秒，绕组和身子变成多热。

        热容小的绕组几毫秒就能变很多，所以按时间切成小段一步一步算（显式积分，每段不超过绕组时间常数的十分之一）。
        """
        if seconds < 0:
            raise ValueError(f"时间不能是负的：{seconds}")
        network = self.thermal
        steps = max(1, math.ceil(seconds / (0.1 * network.winding_time_constant_s)))
        dt = seconds / steps
        winding, housing = temperature.winding_c, temperature.housing_c
        for _ in range(steps):
            loss = self.copper_loss_w(torque_nm, winding)
            to_housing = (winding - housing) / network.winding_to_housing_k_per_w
            to_coolant = (housing - COOLANT_C) / network.housing_to_coolant_k_per_w
            winding += dt * (loss - to_housing) / network.winding_j_per_k
            housing += dt * (to_housing - to_coolant) / network.housing_j_per_k
        return Temperatures(winding, housing)


@dataclass(frozen=True)
class DriveArrays:
    """几个驱动器的数排成数组，一起算力的上下限和发热（仿真里每一步、热预算里每一段）。

    规则和 DriveSpec 的一样（测试里两边对着比），只是一次算全部。
    """

    peak_nm: np.ndarray
    continuous_nm: np.ndarray
    knee_speed_rad_s: np.ndarray
    no_load_speed_rad_s: np.ndarray
    km_squared: np.ndarray
    to_housing_k_per_w: np.ndarray
    to_coolant_k_per_w: np.ndarray
    winding_j_per_k: np.ndarray
    housing_j_per_k: np.ndarray

    @classmethod
    def of(cls, drives: Sequence[DriveSpec]) -> "DriveArrays":
        """把这几个驱动器的数排成数组。"""

        def column(read) -> np.ndarray:
            return np.array([read(drive) for drive in drives], dtype=float)

        return cls(
            peak_nm=column(lambda drive: drive.peak_torque_nm),
            continuous_nm=column(lambda drive: drive.continuous_torque_nm),
            knee_speed_rad_s=column(lambda drive: drive.knee_speed_rad_s),
            no_load_speed_rad_s=column(lambda drive: drive.no_load_speed_rad_s),
            km_squared=column(lambda drive: drive.km_nm_per_sqrt_w) ** 2,
            to_housing_k_per_w=column(lambda drive: drive.thermal.winding_to_housing_k_per_w),
            to_coolant_k_per_w=column(lambda drive: drive.thermal.housing_to_coolant_k_per_w),
            winding_j_per_k=column(lambda drive: drive.thermal.winding_j_per_k),
            housing_j_per_k=column(lambda drive: drive.thermal.housing_j_per_k),
        )

    def thermal_limit_nm(self, winding_c: np.ndarray) -> np.ndarray:
        """绕组这么热时每个驱动器力的上限（DriveSpec.thermal_limit_nm 一样的规则）。"""
        share = np.clip((winding_c - DERATE_FROM_C) / (WINDING_MAX_C - DERATE_FROM_C), 0.0, 1.0)
        derated = self.peak_nm + share * (self.continuous_nm - self.peak_nm)
        over = np.clip((winding_c - WINDING_MAX_C) / CUTOFF_ABOVE_MAX_K, 0.0, 1.0)
        return np.where(winding_c <= WINDING_MAX_C, derated, self.continuous_nm * (1.0 - over))

    def speed_limit_nm(self, speed_rad_s: np.ndarray) -> np.ndarray:
        """往转的方向推时，电压在这个转速（绝对值）下推得出多大的力（DriveSpec.speed_limit_nm 一样的规则）。"""
        fraction = (self.no_load_speed_rad_s - speed_rad_s) / (self.no_load_speed_rad_s - self.knee_speed_rad_s)
        return self.peak_nm * np.clip(fraction, 0.0, 1.0)

    def torque_limits_nm(self, speed_rad_s: np.ndarray, winding_c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """每个驱动器在这个转速、这个温度下能出的力的下限和上限（DriveSpec.torque_limits_nm 一样的规则）。"""
        return self.limits_with(speed_rad_s, self.thermal_limit_nm(winding_c))

    def limits_with(self, speed_rad_s: np.ndarray, thermal_nm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """按温度的上限已经算好了（温度变得慢，不用每一步都算），再按转速定下限和上限。"""
        thermal = thermal_nm
        pushing = np.minimum(thermal, self.speed_limit_nm(np.abs(speed_rad_s)))
        upper = np.where(speed_rad_s < 0, thermal, pushing)
        lower = -np.where(speed_rad_s > 0, thermal, pushing)
        return lower, upper

    def heat(
        self, winding_c: np.ndarray, housing_c: np.ndarray, torque_squared: np.ndarray, seconds: float
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """出着这么大的力（平方）过了 seconds 秒：绕组、身子变成多热，最后一小步每个驱动器发多少热（瓦）。

        按时间切成小段一步一步算（显式积分，每段不超过最快的绕组时间常数的十分之一），和 DriveSpec.heat 一样。
        """
        fastest = float(np.min(self.to_housing_k_per_w * self.winding_j_per_k))
        steps = max(1, math.ceil(seconds / (0.1 * fastest)))
        dt = seconds / steps
        winding, housing = winding_c.astype(float), housing_c.astype(float)
        loss = np.zeros_like(winding)
        for _ in range(steps):
            loss = torque_squared / self.km_squared * (1.0 + COPPER_TEMPERATURE_COEFFICIENT * (winding - REFERENCE_C))
            flow = (winding - housing) / self.to_housing_k_per_w
            out = (housing - COOLANT_C) / self.to_coolant_k_per_w
            winding = winding + dt * (loss - flow) / self.winding_j_per_k
            housing = housing + dt * (flow - out) / self.housing_j_per_k
        return winding, housing, loss


def size_drive(
    peak_torque_nm: float,
    continuous_torque_nm: float,
    knee_speed_rad_s: float | None,
    cooling: Cooling,
    mass_model: ActuatorMassModel,
    *,
    mass_overhead: float = 0.0,
) -> DriveSpec:
    """按要的峰值力矩、要一直出的力矩、要的转速选一个驱动器。

    重量取两个里大的：照峰值的那条线，和"能一直出这么大"要的。mass_overhead 是另外多出来的比例（双绕组）。
    continuous_torque_nm 是 0 就只看峰值。
    """
    _require_positive("峰值力矩", peak_torque_nm)
    if continuous_torque_nm < 0:
        raise ValueError(f"能一直出的力矩不能是负的：{continuous_torque_nm}")
    if mass_overhead < 0:
        raise ValueError(f"多出来的比例不能是负的：{mass_overhead}")
    by_peak_kg = mass_model.mass_kg(peak_torque_nm)
    by_heat_kg = mass_for_continuous_torque_kg(continuous_torque_nm, cooling) if continuous_torque_nm > 0 else 0.0
    core_kg = max(by_peak_kg, by_heat_kg)
    if knee_speed_rad_s is not None:
        _require_positive("转速", knee_speed_rad_s)
    knee = max(MIN_KNEE_SPEED_RAD_S, knee_speed_rad_s or 0.0)
    no_load = knee * STALL_TO_PEAK / (STALL_TO_PEAK - 1.0)
    # 双绕组多出来的是第二套绕组和驱动：算进重量，不算进电机常数和散热（保守）。
    return DriveSpec(
        peak_torque_nm=peak_torque_nm,
        continuous_torque_nm=min(continuous_torque_for_mass_nm(core_kg, cooling), peak_torque_nm),
        knee_speed_rad_s=knee,
        no_load_speed_rad_s=no_load,
        mass_kg=core_kg * (1.0 + mass_overhead),
        cooling=cooling,
        km_nm_per_sqrt_w=km_out(core_kg),
        thermal=thermal_network(core_kg, cooling),
        friction_nm=COULOMB_SHARE_OF_PEAK * peak_torque_nm,
        viscous_nm_s=VISCOUS_SHARE_OF_PEAK_PER_RAD_S * peak_torque_nm,
        armature_kg_m2=ARMATURE_REFERENCE_KG_M2 * (core_kg / ARMATURE_REFERENCE_MASS_KG) ** ARMATURE_MASS_EXPONENT,
        required_continuous_nm=continuous_torque_nm,
        sized_by_heat=by_heat_kg > by_peak_kg,
        motor_mass_kg=core_kg,
    )


def with_cooling(drive: DriveSpec, cooling: Cooling) -> DriveSpec:
    """同一个驱动器换一种冷却：重量不变，能一直出的力矩和热的网络跟着变（比"不液冷会怎样"用）。"""
    return replace(
        drive,
        cooling=cooling,
        continuous_torque_nm=min(continuous_torque_for_mass_nm(drive.motor_mass_kg, cooling), drive.peak_torque_nm),
        thermal=thermal_network(drive.motor_mass_kg, cooling),
    )


def _require_positive(label: str, value: float) -> None:
    if not value > 0:
        raise ValueError(f"{label}必须大于 0，收到的是 {value}")
