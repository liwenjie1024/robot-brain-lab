"""质量闭环：把"Nova 有多重"算到收敛。

为什么要迭代：腿和躯干要出的力矩跟着体重变。身体重了，腿的驱动器就要更大、更重，身体又更重。
这个循环停下来的地方，就是 Nova 的体重。

每个驱动器按两样选（drives.size_drive）：要出的峰值力矩，和一轮家务里要一直出的力矩（发热）。
"随体重"的力矩按"体重 x 身高"放大：同样的姿势，身体重一倍、各段长一倍，力矩就是四倍。
"""

from dataclasses import dataclass, field, replace

from nova_body.actuator_mass import ActuatorMassModel
from nova_body.anthropometry import MASS_FRACTION, Segment, segment_count, segment_length_m
from nova_body.design import HAND_COUNT, BodyVariant, JointGroup, Strength, TorqueRule
from nova_body.drives import DriveSpec, size_drive

GRAVITY_M_S2 = 9.81
TOLERANCE_KG = 1e-6
MAX_ITERATIONS = 200
# 超过这个数就认为闭不上：人形机器人不会这么重，再算下去没有意义。
MAX_PLAUSIBLE_MASS_KG = 300.0
EXTRA_PROBE_KG = 1.0
HALF = 0.5
WH_PER_KWH = 1000.0
HIP_BRAKES_PER_BODY = 2
# 推杆跨在关节上：一半的重量算在它装的那一段，一半算在另一头。
SPLIT_SHARE = 0.5

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
# 有固定位置的那几类。骨架、线、皮肤是另外按比例分的。
_LOCATED_CATEGORIES: tuple[str, ...] = (
    CATEGORY_ACTUATORS,
    CATEGORY_HANDS,
    CATEGORY_BATTERY,
    CATEGORY_COMPUTER,
    CATEGORY_COOLING,
    CATEGORY_SENSORS,
    CATEGORY_FALLBACKS,
    CATEGORY_EXTRA,
)


class MassClosureError(RuntimeError):
    """质量闭不上：算不出一个稳定的体重。"""


@dataclass(frozen=True)
class Assumptions:
    """算质量时用的假设。每个数都会写进报告。

    reference_body_mass_kg、reference_height_m：机体规格里的力矩是按这个体重、这个身高定的。
    strength：驱动器按哪一档力量定（做家务的动作要的，或者人的峰值）。
    strength_factor：力量的倍数。"轻的家用身体"用 0.5。
    structure_fraction、wiring_fraction：骨架、线各占总重的比例。
    fallbacks：要不要算上保底的东西（双绕组多出来的重量、超级电容、制动器、安全板）。
    arm_payload_kg、arm_dynamic_factor：手臂伸直端着这么重的东西，再乘上动起来的倍数。
    foot_hardware_kg：一只脚里的东西：踝的六轴力传感器约 0.3 kg、脚底的压力皮肤约 0.1 kg、硬的脚板约 0.2 kg。
    skin_and_cover_kg 是身高 1.70 m 时的；皮肤和外衣按表面积（身高²）变。
    """

    height_m: float = 1.70
    reference_body_mass_kg: float = 70.0
    reference_height_m: float = 1.70
    strength: Strength = Strength.DAILY
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
    foot_hardware_kg: float = 0.6
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
            "参考身高": self.reference_height_m,
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
            "脚里的东西的重量": self.foot_hardware_kg,
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

    @property
    def height_scale(self) -> float:
        """身高是参考身高的几倍。"""
        return self.height_m / self.reference_height_m

    @property
    def skin_kg(self) -> float:
        """这个身高的皮肤、软外壳和外衣（按表面积变）。"""
        return self.skin_and_cover_kg * self.height_scale**2


@dataclass(frozen=True)
class ActuatorLine:
    """报告里驱动器的一行：同一组关节里要求一样的驱动器。

    torque_nm 是要的峰值力矩；drive 是选好的驱动器（能一直出多大、怎么发热）。
    按固定重量算的组没有这两样（None）。share 是这一段分到每个驱动器重量的几成（推杆跨在关节上时是一半）。
    """

    key: str
    name: str
    segment: Segment
    count: int
    torque_nm: float | None
    mass_each_kg: float
    beyond_data: bool
    drive: DriveSpec | None = None
    share: float = 1.0

    @property
    def total_kg(self) -> float:
        """这一行一共多重。"""
        return self.count * self.mass_each_kg


@dataclass(frozen=True)
class FixedItem:
    """放在固定地方的东西（不是关节的驱动器）：电池、电脑、手……count 是全身一共几个。"""

    key: str
    name: str
    category: str
    segment: Segment
    count: int
    mass_each_kg: float

    @property
    def total_kg(self) -> float:
        """这样东西一共多重。"""
        return self.count * self.mass_each_kg


@dataclass(frozen=True)
class MassBudget:
    """闭合以后的质量。by_segment 是每一段一侧的重量。

    每一段的重量 = 这一段里的驱动器（actuators）+ 这一段里的东西（items）
    + 分到这一段的骨架、线和皮肤（spread_kg 的一份）。
    """

    variant_name: str
    model_name: str
    total_kg: float
    by_category: dict[str, float]
    by_segment: dict[Segment, float]
    actuators: tuple[ActuatorLine, ...]
    items: tuple[FixedItem, ...]
    spread_kg: float
    drives: dict[str, tuple[DriveSpec, ...]] = field(default_factory=dict)
    iterations: int = 0
    growth_per_added_kg: float = 0.0

    def spread_on_kg(self, segment: Segment) -> float:
        """骨架、线、皮肤分到这一段（一侧）的重量。它们没有固定的位置，按人各段的质量比例分。"""
        return MASS_FRACTION[segment] * self.spread_kg


def close_mass(variant: BodyVariant, assumptions: Assumptions, model: ActuatorMassModel) -> MassBudget:
    """算出这种身体的体重，以及"多带 1 kg，总重加多少"。"""
    budget = _iterate(variant, assumptions, model, extra_kg=0.0)
    heavier = _iterate(variant, assumptions, model, extra_kg=EXTRA_PROBE_KG)
    growth = (heavier.total_kg - budget.total_kg) / EXTRA_PROBE_KG
    return replace(budget, growth_per_added_kg=growth)


def joint_peak_torques_nm(group: JointGroup, assumptions: Assumptions, budget: MassBudget) -> tuple[float, ...]:
    """闭合以后，这组关节每个自由度要出的峰值力矩。按固定重量估的组返回空。"""
    guess = _Guess(budget.total_kg, budget.by_segment)
    return tuple(
        _required_torque_nm(group.torque_rule, torque, assumptions, guess)
        for torque in group.spec_torques_nm(assumptions.strength)
    )


def group_drives(group: JointGroup, budget: MassBudget) -> tuple[DriveSpec, ...]:
    """闭合以后，这组关节（一侧）每个驱动器选的样子，顺序和组里的驱动器一样。按固定重量估的组返回空。"""
    return budget.drives.get(group.key, ())


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
    drives = {
        group.key: _group_drives(group, assumptions, model, guess)
        for group in variant.joint_groups()
        if group.fixed_mass_kg is None
    }
    lines = tuple(
        line for group in variant.joint_groups() for line in _actuator_lines(group, model, drives.get(group.key, ()))
    )
    items = _fixed_items(variant, assumptions, extra_kg)

    by_category = dict.fromkeys(_LOCATED_CATEGORIES, 0.0)
    by_category[CATEGORY_ACTUATORS] = sum(line.total_kg for line in lines)
    for item in items:
        by_category[item.category] += item.total_kg
    by_category[CATEGORY_SKIN] = assumptions.skin_kg
    # 骨架和线按总重的比例算，所以总重 = 其它东西 ÷ (1 - 两个比例)。
    shared_fraction = assumptions.structure_fraction + assumptions.wiring_fraction
    total = sum(by_category.values()) / (1 - shared_fraction)
    by_category[CATEGORY_STRUCTURE] = assumptions.structure_fraction * total
    by_category[CATEGORY_WIRING] = assumptions.wiring_fraction * total

    located = dict.fromkeys(Segment, 0.0)
    for part in (*lines, *items):
        located[part.segment] += part.total_kg / segment_count(part.segment)
    # 骨架、线、皮肤没有固定的位置，按人各段的质量比例分到各段。
    spread = by_category[CATEGORY_STRUCTURE] + by_category[CATEGORY_WIRING] + assumptions.skin_kg
    by_segment = {segment: located[segment] + MASS_FRACTION[segment] * spread for segment in Segment}
    return MassBudget(
        variant_name=variant.name,
        model_name=model.name,
        total_kg=total,
        by_category=by_category,
        by_segment=by_segment,
        actuators=lines,
        items=items,
        spread_kg=spread,
        drives=drives,
    )


def _fixed_items(variant: BodyVariant, assumptions: Assumptions, extra_kg: float) -> tuple[FixedItem, ...]:
    """不是关节驱动器的东西，各放在哪一段、各多重（机体规格第 6 节）。重量是 0 的不列。"""
    battery_kg = assumptions.battery_kwh * WH_PER_KWH / assumptions.battery_wh_per_kg
    items = [
        FixedItem("hand", "手", CATEGORY_HANDS, Segment.HAND, HAND_COUNT, variant.hand.hand_mass_kg),
        FixedItem(
            "hand_drive",
            "前臂里给手用的驱动",
            CATEGORY_HANDS,
            Segment.FOREARM,
            HAND_COUNT,
            variant.hand.forearm_drive_mass_kg,
        ),
        FixedItem("battery", "电池", CATEGORY_BATTERY, Segment.CHEST, 1, battery_kg),
        FixedItem("computer", "电脑", CATEGORY_COMPUTER, Segment.CHEST, 1, assumptions.computer_kg),
        FixedItem("sensors", "传感器", CATEGORY_SENSORS, Segment.HEAD, 1, assumptions.sensors_kg),
        FixedItem(
            "foot_hardware",
            "脚里的力传感器、压力皮肤和脚板",
            CATEGORY_SENSORS,
            Segment.FOOT,
            segment_count(Segment.FOOT),
            assumptions.foot_hardware_kg,
        ),
        FixedItem("extra", "额外带的东西", CATEGORY_EXTRA, Segment.CHEST, 1, extra_kg),
    ]
    if assumptions.liquid_cooling:
        items.append(FixedItem("cooling", "液冷", CATEGORY_COOLING, Segment.CHEST, 1, assumptions.liquid_cooling_kg))
    if assumptions.fallbacks:
        items += [
            FixedItem(
                "supercapacitor", "超级电容", CATEGORY_FALLBACKS, Segment.CHEST, 1, assumptions.supercapacitor_kg
            ),
            FixedItem("safety_board", "安全控制板", CATEGORY_FALLBACKS, Segment.PELVIS, 1, assumptions.safety_board_kg),
            FixedItem(
                "hip_brake", "髋的制动器", CATEGORY_FALLBACKS, Segment.PELVIS, HIP_BRAKES_PER_BODY, assumptions.brake_kg
            ),
            FixedItem(
                "knee_brake",
                "膝的制动器",
                CATEGORY_FALLBACKS,
                Segment.THIGH,
                segment_count(Segment.THIGH),
                assumptions.brake_kg,
            ),
        ]
    return tuple(item for item in items if item.total_kg > 0)


def _group_drives(
    group: JointGroup, assumptions: Assumptions, model: ActuatorMassModel, guess: _Guess
) -> tuple[DriveSpec, ...]:
    """按猜的体重，给这组关节（一侧）的每个驱动器选一个：峰值、一直要出的、转速、怎么冷却。"""
    overhead = assumptions.dual_winding_overhead if (group.dual_winding and assumptions.fallbacks) else 0.0
    return tuple(
        size_drive(
            _required_torque_nm(group.torque_rule, peak, assumptions, guess),
            _required_continuous_nm(group.torque_rule, continuous, assumptions, guess),
            speed,
            group.cooling,
            model,
            mass_overhead=overhead,
        )
        for peak, continuous, speed in zip(
            group.actuator_torques_nm(assumptions.strength),
            group.actuator_continuous_nm(assumptions.strength),
            group.actuator_speeds_rad_s(),
            strict=True,
        )
    )


def _actuator_lines(group: JointGroup, model: ActuatorMassModel, drives: tuple[DriveSpec, ...]) -> list[ActuatorLine]:
    """一组关节的驱动器各多重。选出来一样的并成一行。"""
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
    counts: dict[DriveSpec, int] = {}
    for drive in drives:
        counts[drive] = counts.get(drive, 0) + group.sides
    shares = (
        ((group.segment, 1.0),)
        if group.split_with is None
        else ((group.segment, SPLIT_SHARE), (group.split_with, 1.0 - SPLIT_SHARE))
    )
    return [
        ActuatorLine(
            key=group.key,
            name=group.name,
            segment=segment,
            count=count,
            torque_nm=drive.peak_torque_nm,
            mass_each_kg=drive.mass_kg * share,
            beyond_data=model.is_beyond_data(drive.peak_torque_nm),
            drive=drive,
            share=share,
        )
        for drive, count in counts.items()
        for segment, share in shares
    ]


def _required_torque_nm(rule: TorqueRule, spec_torque_nm: float, assumptions: Assumptions, guess: _Guess) -> float:
    """这个驱动器实际要出多大的峰值力矩。"""
    scaled = spec_torque_nm * assumptions.strength_factor
    if rule is TorqueRule.BODY_MASS:
        return scaled * _body_scale(assumptions, guess)
    if rule is TorqueRule.SHOULDER_LOAD:
        return max(scaled, _arm_holding_torque_nm(assumptions, guess.by_segment, from_shoulder=True))
    if rule is TorqueRule.ELBOW_LOAD:
        return max(scaled, _arm_holding_torque_nm(assumptions, guess.by_segment, from_shoulder=False))
    return scaled


def _required_continuous_nm(
    rule: TorqueRule, spec_continuous_nm: float, assumptions: Assumptions, guess: _Guess
) -> float:
    """这个驱动器在一轮家务里要一直出的力矩。"随体重"的和峰值一样放大，别的不变。"""
    scaled = spec_continuous_nm * assumptions.strength_factor
    return scaled * _body_scale(assumptions, guess) if rule is TorqueRule.BODY_MASS else scaled


def _body_scale(assumptions: Assumptions, guess: _Guess) -> float:
    """ "随体重"的力矩放大几倍：体重是参考的几倍，乘上身高是参考的几倍（力臂跟着变长）。"""
    return guess.total_kg / assumptions.reference_body_mass_kg * assumptions.height_scale


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
