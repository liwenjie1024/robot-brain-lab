"""动作：第一次考试要做的那些动作，一帧一帧地写出来。每一帧有：全身的姿势、谁撑着身体、手里拿着什么。

动作是"说要做到什么"写的（脚踩在哪、手去哪、重心在哪），全身的姿势由逆运动学算出来，所以对哪个身体都能用。
要手或者膝盖的动作（搬箱子、跪着撑起来……），身体的描述里没有手心、膝盖的点就不做。
家里的尺寸（楼梯、桌子、柜子）对每个身体都一样：家不会因为机器人矮就变矮。
"""

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum

import mujoco
import numpy as np

from nova_body.body import SIDE_NAMES, Body, Region, Side
from nova_body.gait import (
    Foothold,
    GaitPlan,
    Timing,
    center_of_mass_path,
    lower_envelope,
    plan_steps,
    smooth,
)
from nova_body.ik import (
    HARD,
    SOFT,
    AttitudeGoal,
    CarriedMass,
    Goals,
    PointGoal,
    WholeBodyIk,
    pitch_rotation,
)
from nova_body.inverse import CarriedLoad, Frame, InverseDynamics, PushingForce, Support, SupportKind
from nova_body.posture import deepest_knee_bend_deg, solve_stand_pose

DT = 0.01
GRAVITY_M_S2 = 9.81
FLAT = np.eye(3)
NAN = float("nan")
UP = 2

# 走路：一步的时间 = (这个数 - 这个数 x 速度) 秒（照 1.70 m 的人），腿短的身体按腿长的平方根缩短（走得更碎）。
STEP_PERIOD_AT_REST_S = 0.8
STEP_PERIOD_PER_SPEED_S = 0.2
REFERENCE_LEG_M = 0.89
# 两只脚都着地的时间占一步的多少。
DOUBLE_SUPPORT_SHARE = 0.25
WALK_STEPS = 6
MIN_WALK_STEPS = 2
WALK_LIFT_M = 0.05
# 后面那只脚抬起来以前，脚跟先抬起这么多度（人走路时约 30~40°）。
WALK_HEEL_OFF_DEG = 20.0
# 抬起来的那只脚：刚抬起、快落地时脚底的朝向必须对上；中间那一段只是软的要求（权重 SOFT），
# 踝转到头的时候脚可以偏一点（人走路时抬起的脚也是随着腿转）。从必须对上到软的要求，在这么长的一段里慢慢变。
SWING_HOLD_SHARE = 0.1
SWING_RELEASE_SHARE = 0.15
START_SHIFT_S = 0.6
END_SHIFT_S = 0.6
HOLD_S = 0.4
# 腿最长按膝还弯着这么多度时算（不伸到最直）。
STRAIGHTEST_KNEE_DEG = 5.0
# 髋最多往下降"脚放平、上身直着时能降的"这么多倍（留一点余地）。
CROUCH_USE = 0.9
# 一步最短这么多秒：再快就是这个身体平着脚走不了这么快。
MIN_STEP_PERIOD_S = 0.35
# 逆运动学里脚、手、膝盖的位置差得比这个多，或者重心差得比这个多，就算这个身体做不出这个动作。
MAX_REACH_ERROR_M = 0.005
MAX_BALANCE_ERROR_M = 0.01
# 按算出来的压力中心修正重心的路时，一遍最多修这么多（米）。
MAX_ZMP_CORRECTION_M = 0.1
# 求重心的路以后，按算出来的压力中心修正几遍（多段的身体不是一个倒立摆）。
BALANCE_PASSES = 3
# 走路时重心的高低：自由解出来的那条线上下跳得太急，取一条处处不比它高的平滑的线，前后各看这么多秒。
HEIGHT_SMOOTHING_S = 0.15

# 楼梯照考场（Nova 考试 2.2 节）：套内楼梯一级高 20 cm、踏面 22 cm，都是住宅标准里最难的。
# 踏面比 Nova 的脚（约 26 cm）还短：上楼时脚跟悬在外面，下楼时脚尖悬在外面，只有踩着的那一块能撑着。
STAIR_RISER_M = 0.20
STAIR_TREAD_M = 0.22
# 上楼时脚尖离上一级的竖板、下楼时脚跟离后面的竖板这么远（上楼抬脚跟时脚尖往前转，要留出地方）。
STAIR_TOE_GAP_M = 0.03
STAIR_STEPS = 4
STAIR_SINGLE_S = 0.65
STAIR_DOUBLE_S = 0.25
STAIR_LIFT_M = 0.05
STAIR_EDGE_GAP_M = 0.03
# 后面那只脚离开台阶以前脚跟先抬起这么多度；下楼时落下的脚先用脚掌着地，脚跟抬着这么多度。
STAIR_HEEL_OFF_DEG = 20.0
STAIR_TOE_LANDING_DEG = 20.0

# 蹲到底再站起（考试里"柔韧和技巧"的一项）：最低的时候重心在站着时的这么多倍（人蹲到底约是一半）。
# 脚跟不离地，上身可以往前倾，手臂可以往前伸。蹲下、停住、站起各用这么多秒。
SQUAT_CENTER_RATIO = 0.5
# 蹲到底时上身往前倾这么多度（人约 40°），骨盆往前倾这么多度；蹲得越深倾得越多。只是轻轻地要（权重 SOFT/10），
# 免得逆运动学走到"往后仰着蹲"那一边去（那样站不稳，可是一开始两边差不多，它分不清）。
SQUAT_TRUNK_LEAN_DEG = 40.0
SQUAT_PELVIS_LEAN_DEG = 15.0
SQUAT_DOWN_S = 1.5
SQUAT_HOLD_S = 0.5
# 搬箱子：箱子 10 kg、30 cm 高，把手离地 20 cm，在脚尖前面 10 cm，两只手隔 32 cm；端着的时候在重心前面 30 cm。
BOX_KG = 10.0
BOX_HANDLE_HEIGHT_M = 0.20
BOX_FRONT_OF_TOES_M = 0.10
BOX_HALF_WIDTH_M = 0.16
CARRY_FORWARD_M = 0.30
CARRY_HEIGHT_OF_BODY = 0.56
CARRY_WALK_SPEED = 0.8
# 放到柜子上：5 kg，柜子高 1.8 m，在重心前面 25 cm。
SHELF_KG = 5.0
SHELF_HEIGHT_M = 1.80
SHELF_FORWARD_M = 0.25
SHELF_HALF_WIDTH_M = 0.12
# 拉门：门把手高 1 m，在右前方；拉的力 50 N，往后拉 30 cm。
DOOR_PULL_N = 50.0
DOOR_HANDLE = (0.35, -0.20, 1.00)
DOOR_PULL_BACK_M = 0.30
# 擦桌子：桌子高 75 cm；手在右前方，左右来回擦，幅度 20 cm、每秒一次，往下压 20 N，抹布和桌子的摩擦系数 0.5。
TABLE_HEIGHT_M = 0.75
WIPE_START = (0.35, -0.25)
WIPE_AMPLITUDE_M = 0.20
WIPE_HZ = 1.0
WIPE_CYCLES = 3
WIPE_PRESS_N = 20.0
WIPE_FRICTION = 0.5
# 抹布的摩擦力随速度变的快慢（m/s）：用平滑的曲线，免得来回换方向时力一下子跳过去。
WIPE_FRICTION_SPEED_M_S = 0.05
# 身体前倾、后仰：重心挪到离脚尖（脚跟）这么近。
LEAN_MARGIN_M = 0.03
# 跳：跳起 25 cm；先蹲下这么多（按腿长的倍数），蹬地的时间按平均速度是起跳速度的这么多分之一来定。
JUMP_HEIGHT_M = 0.25
JUMP_CROUCH_OF_LEG = 0.17
JUMP_PUSH_SLOWNESS = 2.2
# 跪着撑起来：身体往下沉这么多。
PUSH_UP_DEPTH_M = 0.12
# 跪着的开始姿势先按关节的角度（度）摆个大概，再用逆运动学摆准。角度按 Nova 的关节方向写
# （正的是弯、向前抬、脚尖向上）；只有身体的描述里有膝盖和脚尖的点（Nova）才做跪着的动作。
# 单膝跪地再站起来不在这里：后脚离前脚太远，慢慢地（每一刻都站得稳）站不起来，要借一点冲劲，留到 P2。
NOVA_ALL_FOURS_PITCH_DEG = 70.0
NOVA_ALL_FOURS_DEG: dict[str, float] = {
    **{f"{side}_hip_pitch": 70.0 for side in ("left", "right")},
    **{f"{side}_knee": 95.0 for side in ("left", "right")},
    **{f"{side}_ankle_pitch": -40.0 for side in ("left", "right")},
    **{f"{side}_shoulder_pitch": 75.0 for side in ("left", "right")},
    **{f"{side}_elbow": 5.0 for side in ("left", "right")},
}
# 有关键时刻的动作：从一个关键时刻走到下一个，分这么多步解出下一个时刻的姿势；
# 做动作时每一帧拉向它们之间插出来的姿势，权重这么大。
KEY_STEPS = 30
KEY_POSTURE_WEIGHT = 0.1
# 只用腿的动作（走、上下楼、蹲、倾、跳）里会动的部分：手臂和头不动，停在站姿上。
# 不这样的话，腿一时够不着要的姿势，逆运动学就在一帧里甩手臂、仰头去凑重心，算出来的力矩是假的。
LEGS_AND_TRUNK = frozenset({Region.LEG, Region.WAIST})
# 从大概的姿势摆准，逆运动学解几遍。
SETTLE_ROUNDS = 6


class Level(StrEnum):
    """这个动作算在哪一档。"""

    CORE = "第一次考试要做的"
    REFERENCE = "运动员级（只拿来比）"


@dataclass(frozen=True)
class Motion:
    """一个动作。reach_error_m：逆运动学里脚、手、膝盖的位置最多差了多少；balance_error_m：重心最多差了多少。

    这两个差得多，就是这个身体做不出这个动作（够不着、关节转不到那里、站不稳）。
    ends_at_rest 是动作结束时身体停着（跳是在脚离地的那一刻结束，那时还在动）。
    """

    key: str
    name: str
    description: str
    level: Level
    dt: float
    frames: list[Frame]
    reach_error_m: float
    balance_error_m: float
    ends_at_rest: bool = True

    @property
    def duration_s(self) -> float:
        return (len(self.frames) - 1) * self.dt

    @property
    def feasible(self) -> bool:
        """这个身体能不能做这个动作：每一帧都够得着、站得稳。"""
        return self.reach_error_m <= MAX_REACH_ERROR_M and self.balance_error_m <= MAX_BALANCE_ERROR_M


class Track:
    """一个量随时间的变化：在给定的几个时刻取给定的值，中间用最小急动度的曲线连起来（两头的速度、加速度是 0）。"""

    def __init__(self, keys: list[tuple[float, object]]) -> None:
        if not keys:
            raise ValueError("至少要一个时刻")
        times = [time for time, _ in keys]
        if times != sorted(times):
            raise ValueError("时刻要从早到晚排")
        self.times = np.array(times, dtype=float)
        self.values = [np.array(value, dtype=float) for _, value in keys]

    def __call__(self, time: float) -> np.ndarray:
        if time <= self.times[0]:
            return self.values[0].copy()
        for index in range(1, len(self.times)):
            if time <= self.times[index]:
                start, end = self.times[index - 1], self.times[index]
                share = smooth((time - start) / (end - start)) if end > start else 1.0
                return self.values[index - 1] + share * (self.values[index] - self.values[index - 1])
        return self.values[-1].copy()

    @property
    def end(self) -> float:
        return float(self.times[-1])


class MotionBuilder:
    """给一个身体写动作。"""

    def __init__(self, body: Body) -> None:
        self.body = body
        self.anatomy = body.anatomy
        self.model = body.model
        self.stand = np.array(body.stand.qpos)
        self.ik = WholeBodyIk(body, self.stand)
        self.leg_ik = WholeBodyIk(body, self.stand, moving=LEGS_AND_TRUNK)
        self.dynamics = InverseDynamics(body)
        data = mujoco.MjData(self.model)
        data.qpos[:] = self.stand
        mujoco.mj_kinematics(self.model, data)
        mujoco.mj_comPos(self.model, data)
        root = self.model.body(self.anatomy.root).id
        self.center = data.subtree_com[root].copy()
        self.soles = {
            side: data.site_xpos[self.model.site(leg.sole).id].copy() for side, leg in self.anatomy.legs.items()
        }
        self.toes = {
            side: data.site_xpos[self.model.site(leg.toe).id].copy()
            for side, leg in self.anatomy.legs.items()
            if leg.toe is not None
        }
        self.palms = {
            side: data.site_xpos[self.model.site(site).id].copy() for side, site in self.anatomy.palms.items()
        }
        hips = {
            side: data.xanchor[self.model.joint(leg.hip_pitch).id].copy() for side, leg in self.anatomy.legs.items()
        }
        ankles = {
            side: data.xanchor[self.model.joint(leg.ankle_pitch).id].copy() for side, leg in self.anatomy.legs.items()
        }
        self.leg_length = float(np.mean([np.linalg.norm(hips[side] - self.soles[side]) for side in Side]))
        self.stand_height = float(self.center[UP] - np.mean([sole[UP] for sole in self.soles.values()]))
        # 定步子多长时用：站着时髋比踝高多少，髋到踝最长多长。
        self.hip_over_ankle = float(np.mean([hips[side][UP] - ankles[side][UP] for side in Side]))
        self.leg_reach = self._hip_to_ankle(solve_stand_pose(self.model, self.anatomy, STRAIGHTEST_KNEE_DEG).qpos)
        deepest = solve_stand_pose(self.model, self.anatomy, deepest_knee_bend_deg(body))
        self.crouch = body.stand.center_of_mass_height_m - deepest.center_of_mass_height_m
        self.feet_support = {
            side: Support(
                f"{SIDE_NAMES[side]}脚",
                leg.sole,
                SupportKind.FOOT,
                half_length=body.foot_length_m / 2,
                half_width=body.foot_width_m / 2,
            )
            for side, leg in self.anatomy.legs.items()
        }

    @property
    def has_hands(self) -> bool:
        return len(self.palms) == len(Side)

    @property
    def can_kneel(self) -> bool:
        return all(leg.knee_front is not None and leg.toe is not None for leg in self.anatomy.legs.values())

    # 走路和楼梯 -------------------------------------------------------------------------------------

    def walk(self, key: str, name: str, speed_m_s: float, description: str, *, steps: int = WALK_STEPS) -> Motion:
        """直着走 steps 步（最后一步是把后面那只脚收到前面那只脚旁边），从站着开始，到站着结束。"""
        length, period = self._gait_size(speed_m_s)
        timing = Timing(
            START_SHIFT_S, (1 - DOUBLE_SUPPORT_SHARE) * period, DOUBLE_SUPPORT_SHARE * period, END_SHIFT_S, HOLD_S
        )
        plan = plan_steps(
            self.soles,
            self._straight_steps(length, steps),
            timing,
            DT,
            foot_length_m=self.body.foot_length_m,
            lift_m=WALK_LIFT_M,
            heel_off_rad=math.radians(WALK_HEEL_OFF_DEG),
        )
        return self._gait_motion(key, name, description, plan)

    def carry_walk(self, key: str, name: str, description: str) -> Motion:
        """端着 10 kg 的箱子走：开始时把箱子从手垂着的地方端到身前，再走。"""
        length, period = self._gait_size(CARRY_WALK_SPEED)
        timing = Timing(
            2 * START_SHIFT_S, (1 - DOUBLE_SUPPORT_SHARE) * period, DOUBLE_SUPPORT_SHARE * period, END_SHIFT_S, HOLD_S
        )
        plan = plan_steps(
            self.soles,
            self._straight_steps(length, WALK_STEPS),
            timing,
            DT,
            foot_length_m=self.body.foot_length_m,
            lift_m=WALK_LIFT_M,
            heel_off_rad=math.radians(WALK_HEEL_OFF_DEG),
        )
        carried = tuple(CarriedMass(site, BOX_KG / len(Side)) for site in self.anatomy.palms.values())
        lift_end = timing.start_shift_s
        height = CARRY_HEIGHT_OF_BODY * self.body.height_m

        def hands(time: float, center: np.ndarray) -> tuple[PointGoal, ...]:
            share = smooth(time / lift_end)
            goals = []
            for side, site in self.anatomy.palms.items():
                carry = np.array([center[0] + CARRY_FORWARD_M, center[1] + _sign(side) * BOX_HALF_WIDTH_M, height])
                goals.append(PointGoal(site, self.palms[side] + share * (carry - self.palms[side]), weight=SOFT * 100))
            return tuple(goals)

        return self._gait_motion(key, name, description, plan, hands=hands, carried=carried)

    def stairs(self, key: str, name: str, *, up: bool, description: str, steps: int = STAIR_STEPS) -> Motion:
        """上（或下）steps 级楼梯，一只脚一级，最后把另一只脚收上来（下去），从站着开始，到站着结束。"""
        if steps < 1:
            raise ValueError(f"至少走 1 级楼梯，收到的是 {steps}")
        rise = STAIR_RISER_M if up else -STAIR_RISER_M
        edge = max(toe[0] for toe in self._toe_positions()) + STAIR_EDGE_GAP_M
        footholds = []
        for number in range(1, steps + 1):
            side = Side.LEFT if number % 2 else Side.RIGHT
            footholds.append(self._stair_foothold(side, edge + (number - 1) * STAIR_TREAD_M, number * rise, up=up))
        last = footholds[-1]
        joining = Side.RIGHT if last.side is Side.LEFT else Side.LEFT
        position = self.soles[joining].copy()
        position[0], position[2] = last.position[0], last.position[2]
        footholds.append(Foothold(joining, position, last.patch))
        timing = Timing(START_SHIFT_S, STAIR_SINGLE_S, STAIR_DOUBLE_S, END_SHIFT_S, HOLD_S)
        plan = plan_steps(
            self.soles,
            footholds,
            timing,
            DT,
            foot_length_m=self.body.foot_length_m,
            lift_m=STAIR_LIFT_M,
            climbing=True,
            heel_off_rad=math.radians(STAIR_HEEL_OFF_DEG),
            toe_landing_rad=0.0 if up else math.radians(STAIR_TOE_LANDING_DEG),
        )
        return self._gait_motion(key, name, description, plan)

    # 站在原地的动作 ---------------------------------------------------------------------------------

    def squat(self, key: str, name: str, description: str) -> Motion:
        """蹲到底再站起来：脚放平不动，重心一直在两只脚中间的上面，降到站着时的一半，再站起来。

        上身照人的样子往前倾，踝转不到的那一部分由髋和腰来补。
        """
        low = self.center.copy()
        low[UP] = SQUAT_CENTER_RATIO * self.center[UP]
        bottom = HOLD_S + SQUAT_DOWN_S
        track = Track(
            [
                (0.0, self.center),
                (HOLD_S, self.center),
                (bottom, low),
                (bottom + SQUAT_HOLD_S, low),
                (bottom + SQUAT_HOLD_S + SQUAT_DOWN_S, self.center),
                (2 * bottom + SQUAT_HOLD_S, self.center),
            ]
        )

        def goals(time: float) -> Goals:
            target = track(time)
            depth = (self.center[UP] - target[UP]) / (self.center[UP] - low[UP])
            attitudes = (
                AttitudeGoal(self.anatomy.root, pitch_rotation(math.radians(depth * SQUAT_PELVIS_LEAN_DEG)), SOFT / 10),
                AttitudeGoal(self.anatomy.trunk, pitch_rotation(math.radians(depth * SQUAT_TRUNK_LEAN_DEG)), SOFT / 10),
            )
            return Goals(points=self._feet_goals(), attitudes=attitudes, center_of_mass=target)

        return self._assemble(
            key,
            name,
            description,
            level=Level.CORE,
            duration_s=track.end,
            goals_at=goals,
            supports_at=self._both_feet,
            arms_move=False,
            key_times=list(track.times),
        )

    def lean(self, key: str, name: str, description: str) -> Motion:
        """身体往前倾到重心快到脚尖，回来，再往后仰到重心快到脚跟，回来。脚不动。"""
        front = max(sole[0] for sole in self.soles.values()) + self.body.foot_length_m / 2 - LEAN_MARGIN_M
        back = min(sole[0] for sole in self.soles.values()) - self.body.foot_length_m / 2 + LEAN_MARGIN_M
        forward, backward = self.center.copy(), self.center.copy()
        forward[0], backward[0] = front, back
        forward[UP] = backward[UP] = NAN
        middle = self.center.copy()
        middle[UP] = NAN
        track = Track(
            [
                (0.0, middle),
                (1.2, forward),
                (1.7, forward),
                (2.9, middle),
                (4.1, backward),
                (4.6, backward),
                (5.8, middle),
            ]
        )

        def goals(time: float) -> Goals:
            return Goals(points=self._feet_goals(), attitudes=self._upright(), center_of_mass=track(time))

        return self._assemble(
            key,
            name,
            description,
            level=Level.CORE,
            duration_s=track.end,
            goals_at=goals,
            supports_at=self._both_feet,
            arms_move=False,
        )

    def jump(self, key: str, name: str, description: str) -> Motion:
        """原地往上跳：先蹲下，再蹬直腿。动作停在脚离地的那一刻（离地以后不用关节出力撑着）。"""
        crouch = JUMP_CROUCH_OF_LEG * self.leg_length
        takeoff_speed = math.sqrt(2 * GRAVITY_M_S2 * JUMP_HEIGHT_M)
        push_s = JUMP_PUSH_SLOWNESS * crouch / takeoff_speed
        down_s, pause_s = 0.6, 0.1
        start_z = float(self.center[UP])
        low_z = start_z - crouch

        def center_z(time: float) -> float:
            if time <= down_s:
                return start_z - crouch * smooth(time / down_s)
            if time <= down_s + pause_s:
                return low_z
            return _quintic(
                time - down_s - pause_s, push_s, low_z, start_z, end_speed=takeoff_speed, end_acceleration=-GRAVITY_M_S2
            )

        def goals(time: float) -> Goals:
            target = self.center.copy()
            target[UP] = center_z(time)
            return Goals(points=self._feet_goals(), attitudes=self._upright(weight=SOFT / 10), center_of_mass=target)

        return self._assemble(
            key,
            name,
            description,
            level=Level.REFERENCE,
            duration_s=down_s + pause_s + push_s,
            goals_at=goals,
            supports_at=self._both_feet,
            arms_move=False,
            ends_at_rest=False,
        )

    # 用手的动作 -------------------------------------------------------------------------------------

    def lift_box(self, key: str, name: str, description: str) -> Motion:
        """从地上搬起 10 kg 的箱子：弯下去抓住把手，慢慢把重量接过来，再站起来，端在身前。"""
        toe = max(toe[0] for toe in self._toe_positions())
        handles = {
            side: np.array([toe + BOX_FRONT_OF_TOES_M, _sign(side) * BOX_HALF_WIDTH_M, BOX_HANDLE_HEIGHT_M])
            for side in Side
        }
        carry = self._carry_positions()
        tracks = {
            side: Track(
                [
                    (0.0, self.palms[side]),
                    (0.3, self.palms[side]),
                    (2.1, handles[side]),
                    (2.5, handles[side]),
                    (4.3, carry[side]),
                    (4.8, carry[side]),
                ]
            )
            for side in Side
        }
        hold = Track([(0.0, 0.0), (2.1, 0.0), (2.5, 1.0), (4.8, 1.0)])
        return self._hand_motion(
            key, name, description, tracks, lambda time: BOX_KG * float(hold(time)), extra_keys=(hold,)
        )

    def shelf(self, key: str, name: str, description: str) -> Motion:
        """把 5 kg 的东西从身前举到 1.8 m 高的柜子上。"""
        carry = self._carry_positions()
        shelf = {
            side: np.array([self.center[0] + SHELF_FORWARD_M, _sign(side) * SHELF_HALF_WIDTH_M, SHELF_HEIGHT_M])
            for side in Side
        }
        tracks = {
            side: Track(
                [
                    (0.0, self.palms[side]),
                    (1.0, carry[side]),
                    (1.3, carry[side]),
                    (3.3, shelf[side]),
                    (3.8, shelf[side]),
                ]
            )
            for side in Side
        }
        return self._hand_motion(key, name, description, tracks, lambda _time: SHELF_KG)

    def pull_door(self, key: str, name: str, description: str) -> Motion:
        """右手抓住门把手，用 50 N 往后拉开 30 cm。门往前拉着手，所以身体要往后靠一点。"""
        handle = self.center + np.array(DOOR_HANDLE) - np.array([0.0, 0.0, self.center[UP]])
        pulled = handle - np.array([DOOR_PULL_BACK_M, 0.0, 0.0])
        # 拉力用 1 秒慢慢加上去：身体要跟着往后靠，靠得太快的话压力中心会一下子跑到脚尖外面。
        hand = Track([(0.0, self.palms[Side.RIGHT]), (1.0, handle), (2.0, handle), (3.0, pulled), (3.4, pulled)])
        pull = Track([(0.0, 0.0), (1.0, 0.0), (2.0, DOOR_PULL_N), (3.4, DOOR_PULL_N)])
        weight = self.ik.mass * GRAVITY_M_S2
        site = self.anatomy.palms[Side.RIGHT]

        def goals(time: float) -> Goals:
            # 门往前拉着手：要让压力中心还在脚的中间，重心得往后挪"拉力 x 把手的高度 ÷ 体重"这么多。
            target = self.center.copy()
            target[0] -= float(pull(time)) * handle[UP] / weight
            target[UP] = NAN
            return Goals(
                points=(*self._feet_goals(), PointGoal(site, hand(time))),
                attitudes=self._upright(weight=SOFT / 10),
                center_of_mass=target,
            )

        def loads(time: float):
            return (PushingForce(site, np.array([float(pull(time)), 0.0, 0.0])),)

        return self._assemble(
            key,
            name,
            description,
            level=Level.CORE,
            duration_s=hand.end,
            goals_at=goals,
            supports_at=self._both_feet,
            loads_at=loads,
        )

    def wipe_table(self, key: str, name: str, description: str) -> Motion:
        """右手按着抹布在桌上左右来回擦 3 下：往下压 20 N，抹布和桌子之间有摩擦。"""
        site = self.anatomy.palms[Side.RIGHT]
        start = np.array([self.center[0] + WIPE_START[0], WIPE_START[1], TABLE_HEIGHT_M])
        reach_s, ramp_s = 1.0, 0.5
        wipe_s = WIPE_CYCLES / WIPE_HZ
        end_s = reach_s + wipe_s + 0.3
        approach = Track([(0.0, self.palms[Side.RIGHT]), (reach_s, start)])
        press = Track(
            [
                (0.0, 0.0),
                (reach_s, 0.0),
                (reach_s + ramp_s, 1.0),
                (reach_s + wipe_s - ramp_s, 1.0),
                (reach_s + wipe_s, 0.0),
                (end_s, 0.0),
            ]
        )

        def sideways(time: float) -> tuple[float, float]:
            """手在左右方向上离起点多远，和它的速度。幅度先慢慢变大，最后慢慢变小。"""
            if not reach_s <= time <= reach_s + wipe_s:
                return 0.0, 0.0
            local = time - reach_s
            envelope = float(press(time))
            angle = 2 * math.pi * WIPE_HZ * local
            offset = WIPE_AMPLITUDE_M * envelope * math.sin(angle)
            # 速度只用来算摩擦的方向，包络变化的那一点可以不算。
            return offset, WIPE_AMPLITUDE_M * envelope * 2 * math.pi * WIPE_HZ * math.cos(angle)

        def goals(time: float) -> Goals:
            offset, _ = sideways(time)
            hand = approach(time) + np.array([0.0, offset, 0.0])
            middle = self.center.copy()
            middle[UP] = NAN
            return Goals(
                points=(*self._feet_goals(), PointGoal(site, hand)),
                attitudes=self._upright(weight=SOFT / 100),
                center_of_mass=middle,
            )

        def loads(time: float):
            _, speed = sideways(time)
            pressing = WIPE_PRESS_N * float(press(time))
            friction = -WIPE_FRICTION * pressing * math.tanh(speed / WIPE_FRICTION_SPEED_M_S)
            return (PushingForce(site, np.array([0.0, friction, pressing])),)

        return self._assemble(
            key,
            name,
            description,
            level=Level.CORE,
            duration_s=end_s,
            goals_at=goals,
            supports_at=self._both_feet,
            loads_at=loads,
        )

    # 跪着的动作 -------------------------------------------------------------------------------------

    def push_up_from_knees(self, key: str, name: str, description: str, start_qpos: np.ndarray) -> Motion:
        """跪着、两手撑地（像跪着做俯卧撑）：身体往下沉 12 cm，再撑起来。膝盖和手心不动。"""
        legs, palms = self.anatomy.legs, self.anatomy.palms
        data = mujoco.MjData(self.model)
        data.qpos[:] = start_qpos
        mujoco.mj_kinematics(self.model, data)
        mujoco.mj_comPos(self.model, data)
        knees = {side: _on_floor(data.site_xpos[self.model.site(leg.knee_front).id]) for side, leg in legs.items()}
        hands = {side: _on_floor(data.site_xpos[self.model.site(site).id]) for side, site in palms.items()}
        top = data.subtree_com[self.model.body(self.anatomy.root).id].copy()
        top[0] = top[1] = NAN
        bottom = top.copy()
        bottom[UP] -= PUSH_UP_DEPTH_M
        track = Track([(0.0, top), (0.4, top), (1.6, bottom), (1.9, bottom), (3.1, top), (3.5, top)])
        supports = tuple(
            [Support(f"{SIDE_NAMES[side]}膝", leg.knee_front, SupportKind.POINT) for side, leg in legs.items()]
            + [Support(f"{SIDE_NAMES[side]}手", site, SupportKind.POINT) for side, site in palms.items()]
        )

        def goals(_time: float) -> Goals:
            points = [PointGoal(legs[side].knee_front, knees[side]) for side in Side]
            points += [PointGoal(palms[side], hands[side]) for side in Side]
            return Goals(points=tuple(points), center_of_mass=track(_time))

        return self._assemble(
            key,
            name,
            description,
            level=Level.CORE,
            duration_s=track.end,
            goals_at=goals,
            supports_at=lambda _time: supports,
            start_qpos=start_qpos,
        )

    def all_fours(self) -> np.ndarray:
        """跪着、两手撑地的开始姿势：膝盖和手心都在地上，手臂伸直。"""
        guess = self._guess(NOVA_ALL_FOURS_DEG, NOVA_ALL_FOURS_PITCH_DEG)
        placed = self._placed(guess)
        legs, palms = self.anatomy.legs, self.anatomy.palms
        points = [PointGoal(legs[side].knee_front, _on_floor(placed.site(legs[side].knee_front))) for side in Side]
        points += [PointGoal(palms[side], _on_floor(placed.site(palms[side]))) for side in Side]
        return self._settle(Goals(points=tuple(points)), guess)

    def _guess(self, joint_degrees: dict[str, float], pitch_deg: float) -> np.ndarray:
        """按关节的角度（度）和骨盆往前倾的角度摆一个大概的姿势，再整个放到地面上（最低的那个点贴着地面）。"""
        qpos = self.stand.copy()
        root_joint = int(self.model.body_jntadr[self.model.body(self.anatomy.root).id])
        address = int(self.model.jnt_qposadr[root_joint])
        quaternion = np.zeros(4)
        mujoco.mju_mat2Quat(quaternion, pitch_rotation(math.radians(pitch_deg)).flatten())
        qpos[address + 3 : address + 7] = quaternion
        for joint, degrees in joint_degrees.items():
            qpos[self.model.joint(joint).qposadr[0]] = math.radians(degrees)
        placed = self._placed(qpos)
        qpos[address + UP] -= min(placed.site(site)[UP] for site in self._contact_sites())
        return qpos

    def _settle(self, goals: Goals, guess: np.ndarray, solver: WholeBodyIk | None = None) -> np.ndarray:
        """从大概的姿势出发，多解几遍逆运动学，直到满足要求。"""
        solver = solver or self.ik
        qpos = guess
        for _ in range(SETTLE_ROUNDS):
            qpos = solver.solve(goals, qpos).qpos
        return qpos

    def _contact_sites(self) -> list[str]:
        sites = [site for leg in self.anatomy.legs.values() for site in (leg.sole, leg.knee_front, leg.toe) if site]
        return sites + list(self.anatomy.palms.values())

    def _placed(self, qpos: np.ndarray) -> "_Placed":
        return _Placed(self.model, self.anatomy.root, qpos)

    # 拼起来 -----------------------------------------------------------------------------------------

    def _assemble(
        self,
        key: str,
        name: str,
        description: str,
        *,
        level: Level,
        duration_s: float,
        goals_at: Callable[[float], Goals],
        supports_at: Callable[[float], tuple[Support, ...]],
        loads_at: Callable[[float], tuple] = lambda _time: (),
        start_qpos: np.ndarray | None = None,
        key_times: list[float] | None = None,
        ends_at_rest: bool = True,
        arms_move: bool = True,
    ) -> Motion:
        """一帧一帧地解逆运动学，配上每一帧撑着的地方和外面的力。

        key_times 是动作的几个关键时刻（每一段都从停着平滑地变到停着）。给了的话，先解出这几个时刻的姿势，
        每一帧再拉向它们之间平滑插出来的姿势：所有关节一起慢慢变。不这样的话，逆运动学会先只动最省事的关节
        （比如蹲的时候只弯踝和膝），它快转到头了，别的关节再在零点几秒里突然去补，算出来的加速度和力矩是假的。
        arms_move 是 False 的话手臂和头不动（只用腿的动作）。
        """
        solver = self.ik if arms_move else self.leg_ik
        times = np.arange(round(duration_s / DT) + 1) * DT
        # 开始的姿势先摆准（动作开始时是停着的，第一帧和第二帧之间不能有一下子的变化）。
        qpos = self._settle(goals_at(0.0), self.stand if start_qpos is None else np.array(start_qpos), solver)
        posture = None if key_times is None else self._key_posture(goals_at, key_times, qpos, solver)
        frames, reach, balance = [], 0.0, 0.0
        for time in times:
            goals = replace(goals_at(float(time)), near=qpos)
            if posture is not None:
                goals = replace(goals, posture=posture(float(time)), posture_weight=KEY_POSTURE_WEIGHT)
            result = solver.solve(goals, qpos)
            qpos = result.qpos
            reach = max(reach, result.point_error_m)
            balance = max(balance, result.center_of_mass_error_m)
            frames.append(Frame(qpos.copy(), tuple(supports_at(float(time))), tuple(loads_at(float(time)))))
        return Motion(key, name, description, level, DT, frames, reach, balance, ends_at_rest)

    def _key_posture(
        self, goals_at: Callable[[float], Goals], key_times: list[float], start: np.ndarray, solver: WholeBodyIk
    ) -> Track:
        """动作在几个关键时刻的姿势：从上一个时刻的姿势出发，按动作的要求一点点走到这一个时刻解出来。"""
        qpos = np.array(start)
        poses = [(key_times[0], qpos.copy())]
        for previous, current in itertools.pairwise(key_times):
            for share in np.linspace(0.0, 1.0, KEY_STEPS)[1:]:
                time = previous + share * (current - previous)
                qpos = solver.solve(replace(goals_at(time), near=qpos), qpos).qpos
            poses.append((current, qpos.copy()))
        return Track(poses)

    def _hand_motion(
        self,
        key,
        name,
        description,
        tracks: dict[Side, Track],
        held_kg: Callable[[float], float],
        *,
        extra_keys: tuple[Track, ...] = (),
    ) -> Motion:
        """两只手跟着轨迹走、手里拿着东西的动作。重心（算上手里的东西）一直在两只脚中间的上面。"""
        palms = self.anatomy.palms
        middle = self.center.copy()
        middle[UP] = NAN
        end = max(track.end for track in tracks.values())

        def goals(time: float) -> Goals:
            mass = held_kg(time) / len(Side)
            carried = tuple(CarriedMass(palms[side], mass) for side in Side) if mass > 0 else ()
            points = (*self._feet_goals(), *(PointGoal(palms[side], tracks[side](time)) for side in Side))
            return Goals(
                points=points, attitudes=self._upright(weight=SOFT / 100), center_of_mass=middle, carried=carried
            )

        def loads(time: float):
            mass = held_kg(time) / len(Side)
            return tuple(CarriedLoad(palms[side], mass) for side in Side) if mass > 0 else ()

        keys = sorted({float(time) for track in (*tracks.values(), *extra_keys) for time in track.times})
        return self._assemble(
            key,
            name,
            description,
            level=Level.CORE,
            duration_s=end,
            goals_at=goals,
            supports_at=self._both_feet,
            loads_at=loads,
            key_times=keys,
        )

    def _gait_motion(
        self,
        key: str,
        name: str,
        description: str,
        plan: GaitPlan,
        *,
        hands: Callable[[float, np.ndarray], tuple[PointGoal, ...]] | None = None,
        carried: tuple[CarriedMass, ...] = (),
        upright: float = SOFT / 10,
    ) -> Motion:
        """按走路的计划解出每一帧，再按算出来的压力中心修正重心的路，修正几遍。

        重心的高低：每一遍先不定高低解一遍（两只脚踩在那里时，姿势尽量像站着），那条线在换脚时跳得太急，
        就取一条处处不比它高的平滑的线（只会更低，腿弯一点总做得到），再按这条线解。
        """
        start = self.center[:2]
        final = (plan.feet[Side.LEFT][-1] + plan.feet[Side.RIGHT][-1]) / 2
        end = final[:2] + (self.center[:2] - np.mean([sole[:2] for sole in self.soles.values()], axis=0))
        reference = plan.zmp.copy()
        steps = _GaitSteps(plan, hands, carried, upright)
        height = np.full(plan.frames, self.stand_height)
        motion = None
        for _ in range(BALANCE_PASSES):
            path = center_of_mass_path(reference, height, DT, start, end)
            _, free_heights, _, _ = self._solve_gait(steps, path, None)
            center_z = lower_envelope(np.minimum(free_heights, self._steady_rise(plan)), round(HEIGHT_SMOOTHING_S / DT))
            height = center_z - plan.surface
            frames, _, reach, balance = self._solve_gait(steps, path, center_z)
            motion = Motion(key, name, description, Level.CORE, DT, frames, reach, balance)
            if not motion.feasible:
                break
            actual = self.dynamics.zero_moment_points(frames, DT, plan.surface)
            error = np.clip(np.nan_to_num(actual - plan.zmp), -MAX_ZMP_CORRECTION_M, MAX_ZMP_CORRECTION_M)
            reference = reference - error
        return motion

    def _solve_gait(
        self, steps: "_GaitSteps", path: np.ndarray, center_z: np.ndarray | None
    ) -> tuple[list[Frame], np.ndarray, float, float]:
        """按重心的路（x、y）和高低（None 是不定高低）一帧一帧解逆运动学。

        返回每一帧、每一帧重心的高度、脚和手最多差多少、重心最多差多少。
        """
        plan = steps.plan
        solver = self.leg_ik if steps.hands is None else self.ik
        loads = tuple(CarriedLoad(item.site, item.mass_kg) for item in steps.carried)
        qpos = self.stand
        frames, heights, reach, balance = [], [], 0.0, 0.0
        for index in range(plan.frames):
            time = index * DT
            target = np.array([path[index, 0], path[index, 1], NAN if center_z is None else center_z[index]])
            points = tuple(
                PointGoal(
                    self.anatomy.legs[side].sole,
                    plan.feet[side][index],
                    pitch_rotation(plan.pitches[side][index]),
                    rotation_weight=_foot_turn_weight(float(plan.swings[side][index])),
                )
                for side in Side
            )
            if steps.hands is not None:
                points += steps.hands(time, target)
            goals = Goals(
                points=points, attitudes=self._upright(steps.upright), center_of_mass=target, carried=steps.carried
            )
            if index == 0:
                qpos = self._settle(goals, qpos, solver)
            result = solver.solve(replace(goals, near=qpos), qpos)
            qpos = result.qpos
            reach = max(reach, result.point_error_m)
            balance = max(balance, result.center_of_mass_error_m)
            heights.append(solver.center_of_mass(steps.carried)[UP])
            supports = tuple(
                self._foot_patch(side, plan.patches[side][index]) for side in Side if side in plan.supports[index]
            )
            frames.append(Frame(qpos.copy(), supports, loads))
        return frames, np.array(heights), reach, balance

    # 小零件 -----------------------------------------------------------------------------------------

    def _gait_size(self, speed: float) -> tuple[float, float]:
        """按速度定一步多长、多少秒。

        步子按人的习惯定（腿短的身体走得碎一点）。两只脚都着地时髋要够得着两只脚，髋又只能降
        "脚放平、上身直着时能降的"那么多，所以步子有个最长；到了最长，就靠迈得更快来走得更快。
        """
        preferred = self._step_period(speed)
        lowest = self.hip_over_ankle - CROUCH_USE * self.crouch
        longest = 2 * math.sqrt(max(self.leg_reach**2 - lowest**2, 0.0))
        length = min(speed * preferred, longest)
        return length, max(length / speed, MIN_STEP_PERIOD_S)

    def _steady_rise(self, plan: GaitPlan) -> np.ndarray:
        """重心高低的另一条上限：从第一只脚抬起到最后一只脚落下，按起点和终点的地面高低匀匀地升（降）。

        上楼时人也是一直匀匀地往上走，不是每一步一开始就把撑着的腿一下子蹬直。平地上就是站着时的高度。
        """
        moving = np.flatnonzero(np.any([~np.isnan(plan.swings[side]) for side in Side], axis=0))
        start_level = float(np.mean([sole[UP] for sole in self.soles.values()]))
        end_level = float(np.mean([plan.feet[side][-1][UP] for side in Side]))
        share = np.clip((np.arange(plan.frames) - moving[0]) / max(moving[-1] - moving[0], 1), 0.0, 1.0)
        return self.stand_height + start_level + share * (end_level - start_level)

    def _hip_to_ankle(self, qpos: np.ndarray) -> float:
        """这个姿势下，髋关节到踝关节的距离（两条腿的平均）。"""
        placed = self._placed(qpos)
        distances = [
            np.linalg.norm(
                placed.data.xanchor[self.model.joint(leg.hip_pitch).id]
                - placed.data.xanchor[self.model.joint(leg.ankle_pitch).id]
            )
            for leg in self.anatomy.legs.values()
        ]
        return float(np.mean(distances))

    def _step_period(self, speed: float) -> float:
        return (STEP_PERIOD_AT_REST_S - STEP_PERIOD_PER_SPEED_S * speed) * math.sqrt(self.leg_length / REFERENCE_LEG_M)

    def _straight_steps(self, length: float, steps: int) -> list[Foothold]:
        """直着走：左脚先迈，每步 length；最后一步把后面那只脚收到前面那只脚旁边。至少 2 步。"""
        if steps < MIN_WALK_STEPS:
            raise ValueError(f"至少走 {MIN_WALK_STEPS} 步（迈一步、再把另一只脚收过来），收到的是 {steps}")
        footholds = []
        for number in range(1, steps):
            side = Side.LEFT if number % 2 else Side.RIGHT
            footholds.append(Foothold(side, self.soles[side] + np.array([number * length, 0.0, 0.0])))
        joining = Side.RIGHT if footholds[-1].side is Side.LEFT else Side.LEFT
        footholds.append(Foothold(joining, self.soles[joining] + np.array([(steps - 1) * length, 0.0, 0.0])))
        return footholds

    def _stair_foothold(self, side: Side, tread_start: float, height: float, *, up: bool) -> Foothold:
        """踩到一级台阶上：上楼时脚尖往前顶到离竖板 1 cm，下楼时脚跟往后靠到离竖板 1 cm。
        脚比踏面长的话，只有踏面上的那一块撑着：记下那一块有多长、中间在哪。
        """
        length = self.body.foot_length_m
        tread_end = tread_start + STAIR_TREAD_M
        center = tread_end - STAIR_TOE_GAP_M - length / 2 if up else tread_start + STAIR_TOE_GAP_M + length / 2
        back, front = max(center - length / 2, tread_start), min(center + length / 2, tread_end)
        position = self.soles[side].copy()
        position[0], position[2] = center, height
        return Foothold(side, position, (front - back, (back + front) / 2 - center))

    def _toe_positions(self) -> list[np.ndarray]:
        return [sole + np.array([self.body.foot_length_m / 2, 0.0, 0.0]) for sole in self.soles.values()]

    def _carry_positions(self) -> dict[Side, np.ndarray]:
        height = CARRY_HEIGHT_OF_BODY * self.body.height_m
        return {
            side: np.array([self.center[0] + CARRY_FORWARD_M, _sign(side) * BOX_HALF_WIDTH_M, height]) for side in Side
        }

    def _foot_patch(self, side: Side, patch: tuple[float, float]) -> Support:
        """一只脚踩着的那一块：(长度, 中间在脚底正中间前面多远)。"""
        length, offset = patch
        whole = self.feet_support[side]
        return Support(whole.label, whole.site, SupportKind.FOOT, length / 2, whole.half_width, offset)

    def _feet_goals(self) -> tuple[PointGoal, ...]:
        return tuple(PointGoal(self.anatomy.legs[side].sole, self.soles[side], FLAT) for side in Side)

    def _both_feet(self, _time: float) -> tuple[Support, ...]:
        return tuple(self.feet_support[side] for side in Side)

    def _upright(self, weight: float = SOFT) -> tuple[AttitudeGoal, ...]:
        return (AttitudeGoal(self.anatomy.root, FLAT, weight), AttitudeGoal(self.anatomy.trunk, FLAT, weight))


@dataclass(frozen=True)
class _GaitSteps:
    """走路时每一帧都一样的要求：脚步的计划、手要去哪、手里拿着什么、上身要多直。"""

    plan: GaitPlan
    hands: Callable[[float, np.ndarray], tuple[PointGoal, ...]] | None
    carried: tuple[CarriedMass, ...]
    upright: float


class _Placed:
    """摆在一个姿势上的身体：各个点在世界里的位置，和重心。"""

    def __init__(self, model: mujoco.MjModel, root: str, qpos: np.ndarray) -> None:
        self.model = model
        self.data = mujoco.MjData(model)
        self.data.qpos[:] = qpos
        mujoco.mj_kinematics(model, self.data)
        mujoco.mj_comPos(model, self.data)
        self.center = self.data.subtree_com[model.body(root).id].copy()

    def site(self, name: str) -> np.ndarray:
        return self.data.site_xpos[self.model.site(name).id].copy()


def _foot_turn_weight(phase: float) -> float:
    """一只脚的朝向这一项的权重：着地时（phase 是 nan）是 HARD；抬起来以后平滑地降到 SOFT，快落地时再升回 HARD。"""
    if math.isnan(phase):
        return HARD
    soft = smooth((phase - SWING_HOLD_SHARE) / SWING_RELEASE_SHARE) * smooth(
        (1 - SWING_HOLD_SHARE - phase) / SWING_RELEASE_SHARE
    )
    return HARD ** (1 - soft) * SOFT**soft


def _quintic(
    time: float, duration: float, start: float, end: float, *, end_speed: float, end_acceleration: float
) -> float:
    """五次多项式：从 start 停着、不加速，到 duration 时到 end，速度 end_speed，加速度 end_acceleration。"""
    share = min(max(time / duration, 0.0), 1.0)
    distance = end - start
    speed = end_speed * duration
    acceleration = end_acceleration * duration**2
    # 系数由 p(1) = distance、p'(1) = speed、p''(1) = acceleration，p(0) = p'(0) = p''(0) = 0 解出来。
    a3 = 10 * distance - 4 * speed + acceleration / 2
    a4 = -15 * distance + 7 * speed - acceleration
    a5 = 6 * distance - 3 * speed + acceleration / 2
    return start + a3 * share**3 + a4 * share**4 + a5 * share**5


def _on_floor(point: np.ndarray) -> np.ndarray:
    placed = np.array(point, dtype=float)
    placed[UP] = 0.0
    return placed


def _sign(side: Side) -> float:
    return 1.0 if side is Side.LEFT else -1.0
