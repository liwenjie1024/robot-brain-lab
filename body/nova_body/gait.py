"""走路、上下楼梯的计划：脚一步步踩在哪、什么时候抬起放下，重心怎么走才不会倒。

做法是机器人常用的那一种（倒立摆 + 压力中心）：
- 先定每一步脚踩在哪，和每一刻压力中心应该在哪（单脚撑着时在那只脚底下，从偏脚跟的地方挪到脚掌前面；
  两只脚都着地时从后面那只脚的脚掌前面挪到前面那只脚）。
- 再求重心的轨迹：把身体看成一个顶在压力中心上的倒立摆，找一条重心的路，让由它算出的压力中心尽量贴着上面那条，
  同时动得平滑。这是一个线性的最小二乘，一次解出来。
- 抬起来的那只脚走一条平滑的弧线，落地时速度和加速度都是 0。

脚跟可以离地，像人一样：后面那只脚抬起来以前，先抬脚跟、用脚掌前面蹬地（这样后面那条腿不用伸那么长，
踝也不用往上转那么多）；下楼时落下的脚先用脚掌着地，再把脚跟放下来。脚跟抬起时绕"脚踩着的那一块的最前面"转，
平地上是脚尖，下楼时是台阶的边。这里的脚都朝前（x）。
"""

import math
from dataclasses import dataclass

import numpy as np

from nova_body.body import Side

GRAVITY_M_S2 = 9.81
# 压力中心在单脚撑着的时候，从脚底中间往后这么多（脚长的倍数）挪到脚掌前面（只用脚掌前面撑着的那一块的中间）。
# 人走路时压力中心也是从脚跟走到脚掌前面；走到那里，脚跟就能抬起来了。
ZMP_SHIFT_OF_FOOT = 0.15
# 只用脚掌前面撑着（脚跟抬起来）的时候，撑着的那一块有这么长，在脚踩着的那一块的最前面。
TOE_PATCH_M = 0.04
# 用脚掌先落地的那只脚，在两只脚都着地的前这么多时间里把脚跟放下来。
HEEL_DOWN_SHARE = 0.6
# 抬起来的那只脚：脚尖朝下（抬起时的样子）保持到这么多（占抬脚的时间），再到这么多时转成落地的样子（人也是这样）。
SWING_TURN_START = 0.3
SWING_TURN_END = 0.8
# 上楼梯：抬起的脚到这么多（占抬脚的时间）时已经抬到高处，从这么多时才开始往前；下楼梯反过来（先往前，后往下）。
CLIMB_UP_BY = 0.6
CLIMB_FORWARD_FROM = 0.25
# 求重心时：压力中心差 1 米的代价是 1；动得不平滑（三阶差分）的代价按这个倍数算；两头停着的条件按这个倍数算。
SMOOTHNESS_WEIGHT = 10.0
ENDPOINT_WEIGHT = 1.0e3
# 两头各几帧是停着的（位置不变）。
REST_FRAMES = 3
# 倒立摆的高度最少算这么高，免得重心离地面太近时方程变得很硬。
MIN_PENDULUM_HEIGHT_M = 0.2

Patch = tuple[float, float]


@dataclass(frozen=True)
class Foothold:
    """一步：哪只脚踩到哪里（脚底正中间的点，世界坐标）。

    patch 是这只脚真正踩着的那一块：(长度, 它的中间在脚底正中间前面多远)。None 是整只脚都踩着。
    """

    side: Side
    position: np.ndarray
    patch: Patch | None = None


@dataclass(frozen=True)
class Timing:
    """一段走的时间（秒）：开始时把重心挪到第一只撑着的脚上、单脚撑着、两只脚都着地、最后挪回中间、停着。"""

    start_shift_s: float
    single_s: float
    double_s: float
    end_shift_s: float
    hold_s: float

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if value <= 0:
                raise ValueError(f"{name} 必须大于 0，收到的是 {value}")


@dataclass(frozen=True)
class GaitPlan:
    """按帧排好的计划。feet 是每一帧两只脚底正中间该在的位置；pitches 是每只脚的脚跟抬起了多少（弧度，0 是放平）；
    supports 是这一帧着地的脚；zmp 是压力中心该在的地方（x、y），surface 是它所在的那个面的高度。
    patches 是每一帧每只脚撑着的那一块：(长度, 它的中间在脚底正中间前面多远)；脚跟抬起时只有脚掌前面那一块。
    swings 是每一帧每只脚抬起来走到了哪（0 到 1）；着地的时候是 nan。
    """

    dt: float
    feet: dict[Side, np.ndarray]
    pitches: dict[Side, np.ndarray]
    supports: list[frozenset[Side]]
    zmp: np.ndarray
    surface: np.ndarray
    patches: dict[Side, list[Patch]]
    swings: dict[Side, np.ndarray]

    @property
    def frames(self) -> int:
        return len(self.supports)


def plan_steps(
    start: dict[Side, np.ndarray],
    footholds: list[Foothold],
    timing: Timing,
    dt: float,
    *,
    foot_length_m: float,
    lift_m: float,
    climbing: bool = False,
    heel_off_rad: float = 0.0,
    toe_landing_rad: float = 0.0,
) -> GaitPlan:
    """按一串脚步和时间排出每一帧：两只脚在哪、谁着地、压力中心该在哪。

    climbing 是上下楼梯：抬起的脚先抬高（或者先往前）再往前（或者再落下），免得踢到台阶的边。
    heel_off_rad：后面那只脚抬起来以前，脚跟先抬起这么多。
    toe_landing_rad：落下的脚先用脚掌着地，脚跟还抬着这么多。
    """
    if not footholds:
        raise ValueError("至少要走一步")
    if heel_off_rad < 0 or toe_landing_rad < 0:
        raise ValueError("脚跟抬起的角度不能是负的")
    planner = _Planner(start, dt, _Style(foot_length_m, lift_m, climbing, heel_off_rad, toe_landing_rad))
    first_stance = _other(footholds[0].side)
    middle = planner.middle_of_feet()
    planner.both_down(
        timing.start_shift_s, (middle[:2], planner.heel(first_stance)[:2]), (middle[2], planner.level(first_stance))
    )
    for number, step in enumerate(footholds):
        stance = _other(step.side)
        planner.swing(step, timing.single_s)
        heights = (planner.level(stance), planner.level(step.side))
        if number < len(footholds) - 1:
            zmp_path = (planner.toe(stance)[:2], planner.heel(step.side)[:2])
            planner.both_down(timing.double_s, zmp_path, heights, rising=stance, landing=step.side)
        else:
            middle = planner.middle_of_patches()
            zmp_path = (planner.toe(stance)[:2], middle[:2])
            planner.both_down(timing.end_shift_s, zmp_path, (heights[0], float(middle[2])), landing=step.side)
    middle = planner.middle_of_patches()
    planner.both_down(timing.hold_s, (middle[:2], middle[:2]), (float(middle[2]), float(middle[2])))
    return planner.plan()


@dataclass(frozen=True)
class _Style:
    """怎么迈步：脚多长、抬多高、是不是上下楼梯、脚跟抬起多少。"""

    foot_length_m: float
    lift_m: float
    climbing: bool
    heel_off_rad: float
    toe_landing_rad: float


class _Planner:
    """一帧一帧地记下计划。place、patch、raised 是每只脚现在踩在哪、踩着哪一块、脚跟抬着多少。"""

    def __init__(self, start: dict[Side, np.ndarray], dt: float, style: _Style) -> None:
        self.dt = dt
        self.style = style
        self.whole: Patch = (style.foot_length_m, 0.0)
        self.place = {side: np.array(position, dtype=float) for side, position in start.items()}
        self.patch = dict.fromkeys(Side, self.whole)
        self.raised = dict.fromkeys(Side, 0.0)
        self.feet: dict[Side, list[np.ndarray]] = {side: [] for side in Side}
        self.pitches: dict[Side, list[float]] = {side: [] for side in Side}
        self.patches: dict[Side, list[Patch]] = {side: [] for side in Side}
        self.swings: dict[Side, list[float]] = {side: [] for side in Side}
        self.supports: list[frozenset[Side]] = []
        self.zmp: list[np.ndarray] = []
        self.surface: list[float] = []

    def heel(self, side: Side) -> np.ndarray:
        """这只脚踩着的那一块里，压力中心起步的地方（偏后）。"""
        length, offset = self.patch[side]
        return self.place[side] + np.array([offset - ZMP_SHIFT_OF_FOOT * length, 0.0, 0.0])

    def toe(self, side: Side) -> np.ndarray:
        """这只脚踩着的那一块里，压力中心走到的地方：脚掌前面那一块的中间。"""
        _, offset = toe_patch(self.patch[side])
        return self.place[side] + np.array([offset, 0.0, 0.0])

    def level(self, side: Side) -> float:
        return float(self.place[side][2])

    def middle_of_feet(self) -> np.ndarray:
        return (self.place[Side.LEFT] + self.place[Side.RIGHT]) / 2

    def middle_of_patches(self) -> np.ndarray:
        return sum((self.heel(side) + self.toe(side) for side in Side), np.zeros(3)) / (2 * len(Side))

    def both_down(
        self,
        seconds: float,
        zmp_path: tuple[np.ndarray, np.ndarray],
        heights: tuple[float, float],
        *,
        rising: Side | None = None,
        landing: Side | None = None,
    ) -> None:
        """两只脚都着地。rising 这只脚接下来要抬起来：慢慢抬起脚跟。
        landing 这只脚刚用脚掌落地：前一段时间里放下脚跟。
        """
        count = _frames(seconds, self.dt)
        for index in range(count):
            share = (index + 1) / count
            for side in Side:
                angle = 0.0
                if side is rising:
                    angle = self.style.heel_off_rad * smooth(share)
                elif side is landing:
                    angle = self.raised[side] * (1 - smooth(share / HEEL_DOWN_SHARE))
                area = toe_patch(self.patch[side]) if angle > 0 else self.patch[side]
                self._put(side, heel_raised(self.place[side], self.patch[side], angle), angle, area)
            self.supports.append(frozenset(Side))
            self.zmp.append(zmp_path[0] + share * (zmp_path[1] - zmp_path[0]))
            self.surface.append(heights[0] + share * (heights[1] - heights[0]))
        if rising is not None:
            self.raised[rising] = self.style.heel_off_rad
        if landing is not None:
            self.raised[landing] = 0.0

    def swing(self, step: Foothold, seconds: float) -> None:
        """一只脚抬起来迈到 step，另一只脚撑着，压力中心在撑着的那只脚底下从脚跟挪到脚掌前面。"""
        stance = _other(step.side)
        style = self.style
        landing_patch = step.patch if step.patch is not None else self.whole
        start_angle = self.raised[step.side]
        origin = heel_raised(self.place[step.side], self.patch[step.side], start_angle)
        target = heel_raised(np.array(step.position, dtype=float), landing_patch, style.toe_landing_rad)
        count = _frames(seconds, self.dt)
        for index in range(count):
            phase = (index + 1) / count
            self._put(stance, self.place[stance].copy(), 0.0, self.patch[stance])
            turned = smooth((phase - SWING_TURN_START) / (SWING_TURN_END - SWING_TURN_START))
            angle = start_angle + turned * (style.toe_landing_rad - start_angle)
            position = swing_position(origin, target, phase, style.lift_m, climbing=style.climbing)
            self._put(step.side, position, angle, landing_patch, phase)
            self.supports.append(frozenset({stance}))
            self.zmp.append((self.heel(stance) + phase * (self.toe(stance) - self.heel(stance)))[:2])
            self.surface.append(self.level(stance))
        self.place[step.side] = np.array(step.position, dtype=float)
        self.patch[step.side] = landing_patch
        self.raised[step.side] = style.toe_landing_rad

    def plan(self) -> GaitPlan:
        return GaitPlan(
            dt=self.dt,
            feet={side: np.array(positions) for side, positions in self.feet.items()},
            pitches={side: np.array(angles) for side, angles in self.pitches.items()},
            supports=self.supports,
            zmp=np.array(self.zmp),
            surface=np.array(self.surface),
            patches=self.patches,
            swings={side: np.array(phases) for side, phases in self.swings.items()},
        )

    def _put(self, side: Side, position: np.ndarray, angle: float, area: Patch, phase: float = math.nan) -> None:
        self.feet[side].append(position)
        self.pitches[side].append(angle)
        self.patches[side].append(area)
        self.swings[side].append(phase)


def heel_raised(sole: np.ndarray, patch: Patch, angle_rad: float) -> np.ndarray:
    """脚跟抬起 angle_rad 以后脚底正中间的点在哪：绕脚踩着的那一块的最前面转。sole 是放平时的位置。"""
    length, offset = patch
    arm = offset + length / 2
    position = np.array(sole, dtype=float)
    position[0] += arm * (1 - math.cos(angle_rad))
    position[2] += arm * math.sin(angle_rad)
    return position


def toe_patch(patch: Patch) -> Patch:
    """脚跟抬起来时撑着的那一块：踩着的那一块最前面 TOE_PATCH_M 长的一条。"""
    length, offset = patch
    front = min(TOE_PATCH_M, length)
    return (front, offset + length / 2 - front / 2)


def swing_position(
    origin: np.ndarray, target: np.ndarray, phase: float, lift_m: float, *, climbing: bool
) -> np.ndarray:
    """抬起来的那只脚在这一刻（phase 从 0 到 1）该在哪。起点和终点的速度、加速度都是 0。

    平地上：往前走的同时抬起再放下。上楼梯：先往上，再往前。下楼梯：先往前，再往下。
    """
    rise = target[2] - origin[2]
    if climbing and rise > 0:
        forward = smooth((phase - CLIMB_FORWARD_FROM) / (1 - CLIMB_FORWARD_FROM))
        upward = smooth(phase / CLIMB_UP_BY)
    elif climbing and rise < 0:
        forward = smooth(phase / CLIMB_UP_BY)
        upward = smooth((phase - (1 - CLIMB_UP_BY)) / CLIMB_UP_BY)
    else:
        forward = upward = smooth(phase)
    position = origin + forward * (target - origin)
    position[2] = origin[2] + upward * rise + lift_m * bump(phase)
    return position


def center_of_mass_path(
    zmp: np.ndarray, height: np.ndarray, dt: float, start: np.ndarray, end: np.ndarray
) -> np.ndarray:
    """由压力中心该在的地方，求重心（x、y）的路。height 是每一帧重心在压力中心那个面上面多高。

    倒立摆：压力中心 = 重心 - 重心的加速度 ÷ ω²，ω² = g ÷ 高度。两头的重心停在 start、end。
    """
    frames = len(zmp)
    if frames < 2 * REST_FRAMES + 3:
        raise ValueError("太短了，求不出重心的路")
    omega_squared = GRAVITY_M_S2 / np.maximum(height, MIN_PENDULUM_HEIGHT_M)
    path = np.zeros((frames, 2))
    for axis in range(2):
        path[:, axis] = _solve_axis(zmp[:, axis], omega_squared, dt, float(start[axis]), float(end[axis]))
    return path


def smooth(value: float) -> float:
    """从 0 平滑地变到 1（最小急动度的曲线）：两头的速度、加速度都是 0。value 在 0 以下当 0，1 以上当 1。"""
    share = min(max(value, 0.0), 1.0)
    return share**3 * (10 - 15 * share + 6 * share**2)


def bump(phase: float) -> float:
    """从 0 起、到 0 止的一个鼓包，中间（phase = 0.5）是 1，两头的速度、加速度都是 0。"""
    share = min(max(phase, 0.0), 1.0)
    return 64 * share**3 * (1 - share) ** 3


def lower_envelope(values: np.ndarray, half_window: int) -> np.ndarray:
    """一条平滑的线，处处不高于 values：先取前后 half_window 帧里的最小，再在同样的范围里按三角形的权重取平均。

    平均的每一个值都不高于它前后 half_window 帧里每一点的最小值，所以结果不会高过原来的线。两头按最边上的值延长。
    """
    if half_window < 1:
        raise ValueError(f"窗口至少 1 帧，收到的是 {half_window}")
    width = 2 * half_window + 1
    padded = np.pad(np.asarray(values, dtype=float), half_window, mode="edge")
    lowest = np.lib.stride_tricks.sliding_window_view(padded, width).min(axis=1)
    weights = 1.0 + half_window - np.abs(np.arange(-half_window, half_window + 1))
    weights /= weights.sum()
    padded = np.pad(lowest, half_window, mode="edge")
    return np.lib.stride_tricks.sliding_window_view(padded, width) @ weights


def _solve_axis(zmp: np.ndarray, omega_squared: np.ndarray, dt: float, start: float, end: float) -> np.ndarray:
    frames = len(zmp)
    rows, targets = [], []
    for index in range(1, frames - 1):
        row = np.zeros(frames)
        curvature = 1.0 / (dt**2 * omega_squared[index])
        row[index - 1] -= curvature
        row[index] += 1.0 + 2 * curvature
        row[index + 1] -= curvature
        rows.append(row)
        targets.append(zmp[index])
    for index in range(1, frames - 2):
        row = np.zeros(frames)
        row[index - 1 : index + 3] = SMOOTHNESS_WEIGHT * np.array([-1.0, 3.0, -3.0, 1.0])
        rows.append(row)
        targets.append(0.0)
    for index in range(REST_FRAMES):
        for frame, value in ((index, start), (frames - 1 - index, end)):
            row = np.zeros(frames)
            row[frame] = ENDPOINT_WEIGHT
            rows.append(row)
            targets.append(ENDPOINT_WEIGHT * value)
    solution, *_ = np.linalg.lstsq(np.array(rows), np.array(targets), rcond=None)
    return solution


def _frames(seconds: float, dt: float) -> int:
    return max(1, round(seconds / dt))


def _other(side: Side) -> Side:
    return Side.RIGHT if side is Side.LEFT else Side.LEFT
