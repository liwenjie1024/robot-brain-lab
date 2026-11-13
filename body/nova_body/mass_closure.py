"""质量闭环：把"Nova 有多重"算到收敛。

为什么要迭代：腿和躯干要出的力矩跟着体重变。身体重了，腿的驱动器就要更大、更重，身体又更重。
这个循环停下来的地方，就是 Nova 的体重。
"""

from dataclasses import dataclass, replace

from nova_body.actuator_mass import ActuatorMassModel
from nova_body.anthropometry import MASS_FRACTION, Segment, segment_count, segment_length_m
from nova_body.design import HAND_COUNT, BodyVariant, JointGroup, TorqueRule

GRAVITY_M_S2 = 9.81
TOLERANCE_KG = 1e-6
MAX_ITERATIONS = 200
# 超过这个数就认为闭不上：人形机器人不会这么重，再算下去没有意义。
MAX_PLAUSIBLE_MASS_KG = 300.0
EXTRA_PROBE_KG = 1.0
HALF = 0.5
WH_PER_KWH = 1000.0
HIP_BRAKES_PER_BODY = 2

CATEGORY_ACTUATORS = "身体的驱动器"
CATEGORY_HANDS = "手和手的驱动"
CATEGORY_STRUCTURE = "骨架"
CATEGORY_WIRING = "线"
CATEGORY_BATTERY = "电池"
CATEGORY_COMPUTER = "电脑"
CATEGORY_COOLING = "液冷"
CATEGORY_SKIN = "皮肤、软外壳、外衣"
CATEGORY_SENSORS = "传感器"
CATEGORY_FALLBACKS = "保底（超级电容、制动器、安全板）"
CATEGORY_EXTRA = "额外带的东西"


class MassClosureError(RuntimeError):
    """质量闭不上：算不出一个稳定的体重。"""


@dataclass(frozen=True)
class Assumptions:
    """算质量时用的假设。每个数都会写进报告。

    reference_body_mass_kg：机体规格里的峰值力矩是按这个体重定的。
    strength_factor：力量的倍数。"轻的家用身体"用 0.5。
    structure_fraction、wiring_fraction：骨架、线各占总重的比例。
    fallbacks：要不要算上保底的东西（双绕组多出来的重量、超级电容、制动器、安全板）。
    arm_payload_kg、arm_dynamic_factor：手臂伸直端着这么重的东西，再乘上动起来的倍数。
    """

    height_m: float = 1.70
    reference_body_mass_kg: float = 70.0
    strength_factor: float = 1.0
    structure_fraction: float = 0.20
    wiring_fraction: float = 0.04
    battery_kwh: float = 1.0
    battery_wh_per_kg: float = 200.0
    computer_kg: float = 1.5
    liquid_cooling: bool = True
    liquid_cooling_kg: float = 3.0
    skin_and_cover_kg: float = 3.5
    sensors_kg: float = 1.0
    fallbacks: bool = True
    supercapacitor_kg: float = 1.0
    brake_kg: float = 0.25
    safety_board_kg: float = 0.5
    dual_winding_overhead: float = 0.10
    arm_payload_kg: float = 5.0
    arm_dynamic_factor: float = 2.0

    def __post_init__(self) -> None:
        positive = {
            "身高": self.height_m,
            "参考体重": self.reference_body_mass_kg,
            "力量的倍数": self.strength_factor,
            "电池每公斤的电量": self.battery_wh_per_kg,
        }
        for label, value in positive.items():
            if value <= 0:
                raise ValueError(f"{label}必须大于 0，收到的是 {value}")
        non_negative = {
            "骨架的比例": self.structure_fraction,
            "线的比例": self.wiring_fraction,
            "电池的电量": self.battery_kwh,
            "电脑的重量": self.computer_kg,
            "液冷的重量": self.liquid_cooling_kg,
            "皮肤和外壳的重量": self.skin_and_cover_kg,
            "传感器的重量": self.sensors_kg,
            "超级电容的重量": self.supercapacitor_kg,
            "制动器的重量": self.brake_kg,
            "安全板的重量": self.safety_board_kg,
            "双绕组多出来的比例": self.dual_winding_overhead,
            "手臂端的重量": self.arm_payload_kg,
            "手臂动起来的倍数": self.arm_dynamic_factor,
        }
        for label, value in non_negative.items():
            if value < 0:
                raise ValueError(f"{label}不能小于 0，收到的是 {value}")
        if self.structure_fraction + self.wiring_fraction >= 1:
            raise ValueError("骨架和线的比例加起来必须小于 1")


@dataclass(frozen=True)
class ActuatorLine:
    """报告里驱动器的一行：同一组关节里要出一样力矩的驱动器。"""

    key: str
    name: str
    segment: Segment
    count: int
    torque_nm: float | None
    mass_each_kg: float
    beyond_data: bool

    @property
    def total_kg(self) -> float:
        """这一行一共多重。"""
        return self.count * self.mass_each_kg


@dataclass(frozen=True)
class MassBudget:
    """闭合以后的质量。by_segment 是每一段一侧的重量。"""

    variant_name: str
    model_name: str
    total_kg: float
    by_category: dict[str, float]
    by_segment: dict[Segment, float]
    actuators: tuple[ActuatorLine, ...]
    iterations: int = 0
    growth_per_added_kg: float = 0.0


def close_mass(variant: BodyVariant, assumptions: Assumptions, model: ActuatorMassModel) -> MassBudget:
    """算出这种身体的体重，以及"多带 1 kg，总重加多少"。"""
    budget = _iterate(variant, assumptions, model, extra_kg=0.0)
    heavier = _iterate(variant, assumptions, model, extra_kg=EXTRA_PROBE_KG)
    growth = (heavier.total_kg - budget.total_kg) / EXTRA_PROBE_KG
    return replace(budget, growth_per_added_kg=growth)


@dataclass(frozen=True)
class _Guess:
    """迭代里猜的体重：总重，和每一段一侧的重量。"""

    total_kg: float
    by_segment: dict[Segment, float]


def _iterate(variant: BodyVariant, assumptions: Assumptions, model: ActuatorMassModel, extra_kg: float) -> MassBudget:
    start_kg = assumptions.reference_body_mass_kg
    guess = _Guess(start_kg, {segment: fraction * start_kg for segment, fraction in MASS_FRACTION.items()})
    for iteration in range(1, MAX_ITERATIONS + 1):
        budget = _evaluate(variant, assumptions, model, guess, extra_kg)
        if budget.total_kg > MAX_PLAUSIBLE_MASS_KG:
            raise MassClosureError(
                f"{variant.name}闭不上：算到 {budget.total_kg:.0f} kg 还在涨。"
                "驱动器每公斤出的力矩太小，或者骨架和线占的比例太大。"
            )
        if abs(budget.total_kg - guess.total_kg) < TOLERANCE_KG:
            return replace(budget, iterations=iteration)
        guess = _Guess(budget.total_kg, budget.by_segment)
    raise MassClosureError(f"{variant.name}迭代了 {MAX_ITERATIONS} 次还没有收敛")


def _evaluate(
    variant: BodyVariant,
    assumptions: Assumptions,
    model: ActuatorMassModel,
    guess: _Guess,
    extra_kg: float,
) -> MassBudget:
    """按猜的体重算一遍各部分的重量，得到新的体重。"""
    lines = tuple(
        line for group in variant.joint_groups() for line in _actuator_lines(group, assumptions, model, guess)
    )
    located = dict.fromkeys(Segment, 0.0)
    for line in lines:
        located[line.segment] += line.total_kg / segment_count(line.segment)
    located[Segment.HAND] += variant.hand.hand_mass_kg
    located[Segment.FOREARM] += variant.hand.forearm_drive_mass_kg

    battery = assumptions.battery_kwh * WH_PER_KWH / assumptions.battery_wh_per_kg
    cooling = assumptions.liquid_cooling_kg if assumptions.liquid_cooling else 0.0
    hip_brakes = HIP_BRAKES_PER_BODY * assumptions.brake_kg if assumptions.fallbacks else 0.0
    knee_brake = assumptions.brake_kg if assumptions.fallbacks else 0.0
    torso_fallbacks = (assumptions.supercapacitor_kg + assumptions.safety_board_kg) if assumptions.fallbacks else 0.0
    located[Segment.TORSO] += battery + assumptions.computer_kg + cooling + torso_fallbacks + hip_brakes + extra_kg
    located[Segment.THIGH] += knee_brake
    located[Segment.HEAD] += assumptions.sensors_kg

    by_category = {
        CATEGORY_ACTUATORS: sum(line.total_kg for line in lines),
        CATEGORY_HANDS: HAND_COUNT * (variant.hand.hand_mass_kg + variant.hand.forearm_drive_mass_kg),
        CATEGORY_BATTERY: battery,
        CATEGORY_COMPUTER: assumptions.computer_kg,
        CATEGORY_COOLING: cooling,
        CATEGORY_SKIN: assumptions.skin_and_cover_kg,
        CATEGORY_SENSORS: assumptions.sensors_kg,
        CATEGORY_FALLBACKS: torso_fallbacks + hip_brakes + segment_count(Segment.THIGH) * knee_brake,
        CATEGORY_EXTRA: extra_kg,
    }
    # 骨架和线按总重的比例算，所以总重 = 其它东西 ÷ (1 - 两个比例)。
    shared_fraction = assumptions.structure_fraction + assumptions.wiring_fraction
    total = sum(by_category.values()) / (1 - shared_fraction)
    by_category[CATEGORY_STRUCTURE] = assumptions.structure_fraction * total
    by_category[CATEGORY_WIRING] = assumptions.wiring_fraction * total

    # 骨架、线、皮肤没有固定的位置，按人各段的质量比例分到各段。
    spread = by_category[CATEGORY_STRUCTURE] + by_category[CATEGORY_WIRING] + assumptions.skin_and_cover_kg
    by_segment = {segment: located[segment] + MASS_FRACTION[segment] * spread for segment in Segment}
    return MassBudget(
        variant_name=variant.name,
        model_name=model.name,
        total_kg=total,
        by_category=by_category,
        by_segment=by_segment,
        actuators=lines,
    )


def _actuator_lines(
    group: JointGroup, assumptions: Assumptions, model: ActuatorMassModel, guess: _Guess
) -> list[ActuatorLine]:
    """一组关节的驱动器各多重。要出一样力矩的并成一行。"""
    if group.fixed_mass_kg is not None:
        # 被动的组没有驱动器，按一侧一个机构来数。
        parts_per_side = max(group.actuators, 1)
        return [
            ActuatorLine(
                key=group.key,
                name=group.name,
                segment=group.segment,
                count=parts_per_side * group.sides,
                torque_nm=None,
                mass_each_kg=group.fixed_mass_kg / parts_per_side,
                beyond_data=False,
            )
        ]
    overhead = assumptions.dual_winding_overhead if (group.dual_winding and assumptions.fallbacks) else 0.0
    counts: dict[float, int] = {}
    for spec_torque in group.actuator_torques_nm():
        torque = _required_torque_nm(group.torque_rule, spec_torque, assumptions, guess)
        counts[torque] = counts.get(torque, 0) + group.sides
    return [
        ActuatorLine(
            key=group.key,
            name=group.name,
            segment=group.segment,
            count=count,
            torque_nm=torque,
            mass_each_kg=model.mass_kg(torque) * (1 + overhead),
            beyond_data=model.is_beyond_data(torque),
        )
        for torque, count in counts.items()
    ]


def _required_torque_nm(rule: TorqueRule, spec_torque_nm: float, assumptions: Assumptions, guess: _Guess) -> float:
    """这个驱动器实际要出多大的峰值力矩。"""
    scaled = spec_torque_nm * assumptions.strength_factor
    if rule is TorqueRule.BODY_MASS:
        return scaled * guess.total_kg / assumptions.reference_body_mass_kg
    if rule is TorqueRule.SHOULDER_LOAD:
        return max(scaled, _arm_holding_torque_nm(assumptions, guess.by_segment, from_shoulder=True))
    if rule is TorqueRule.ELBOW_LOAD:
        return max(scaled, _arm_holding_torque_nm(assumptions, guess.by_segment, from_shoulder=False))
    return scaled


def _arm_holding_torque_nm(
    assumptions: Assumptions, segment_guess: dict[Segment, float], *, from_shoulder: bool
) -> float:
    """手臂水平伸直、手里端着东西时，肩（或肘）要出的力矩，再乘上动起来的倍数。

    手臂自己越重，这个力矩越大：这就是"前臂变重，肩的要求变高"。
    """
    upper = segment_length_m(Segment.UPPER_ARM, assumptions.height_m)
    fore = segment_length_m(Segment.FOREARM, assumptions.height_m)
    hand = segment_length_m(Segment.HAND, assumptions.height_m)
    held_kg = segment_guess[Segment.HAND] + assumptions.arm_payload_kg * assumptions.strength_factor
    if from_shoulder:
        moment_kg_m = (
            segment_guess[Segment.UPPER_ARM] * HALF * upper
            + segment_guess[Segment.FOREARM] * (upper + HALF * fore)
            + held_kg * (upper + fore + HALF * hand)
        )
    else:
        moment_kg_m = segment_guess[Segment.FOREARM] * HALF * fore + held_kg * (fore + HALF * hand)
    return assumptions.arm_dynamic_factor * GRAVITY_M_S2 * moment_kg_m
