"""시험장을 제어 주기 단위로 진행한다: 드론 움직임, 기체의 팔·비행 제어, 물리, 무장."""

from __future__ import annotations

import math

import mujoco
import numpy as np

from .arena import PHYSICS_DT, build_arena
from .arms import READY_POSES, build_arms
from .combat import Event, Units
from .commands import AimPoint, AimUnit, Command, CommandRejectedError, Fire, Fly, Guard, LowerAim, Push, Reset
from .drones import DronePilot, drone_id
from .flight import HOLD, FlightController, heading_of
from .mecha import ROOT_BODY, STAND_HEIGHT_M
from .scenarios import DEFAULT_SCENARIO, SCENARIOS, Scenario
from .weapons import DroneGunner, NotReadyError, Rifle

CONTROL_DECIMATION = 10
# 방패를 몸통 중심에서 이만큼 떨어진 사격 길 위에 든다 (팔 길이 안쪽).
GUARD_REACH_M = 6.5
# 땅에 닿아 있고 이보다 느리며 멈춤·내려가기 명령이면 추진기를 끄고 선다.
LANDED_SPEED_MPS = 0.5
# 발이 바닥에서 이만큼 안이면 닿은 것으로 본다. 발바닥이 바닥에 딱 맞으면(처음 자세) 접촉이 생기지 않아서다.
# 시험장 바닥이 평평하다는 것을 전제로 한다 (높이 = 몸통 높이 - 선 키).
GROUND_TOLERANCE_M = 0.05
FLOOR_GEOM = "floor"


class Simulation:
    """한 스레드에서만 부른다 (명령 적용 apply와 진행 step_control_tick 모두)."""

    def __init__(self, scenario: str = DEFAULT_SCENARIO) -> None:
        self.model, self.mass = build_arena()
        self.data = mujoco.MjData(self.model)
        self.flight = FlightController(self.model, self.mass)
        self.arms = build_arms(self.model)
        self.rifle = Rifle(self.model)
        self.gunner = DroneGunner(self.model)
        self.units = Units(self.model)
        self.pilots = [DronePilot(self.model, index) for index in range(len(self.units.drones()))]
        self._root = self.model.body(ROOT_BODY).id
        joint = self.model.body_jntadr[self._root]
        self._root_qpos = self.model.jnt_qposadr[joint]
        self._root_dof = self.model.jnt_dofadr[joint]
        self._floor = self.model.geom(FLOOR_GEOM).id
        self._scenario: Scenario = SCENARIOS[scenario]
        self._command = HOLD
        self._aim: str | np.ndarray | None = None
        self._guard = False
        self._guard_unit: str | None = None
        self._push_until = 0.0
        self._events: list[Event] = []
        self._episode = -1
        self.reset(scenario)

    @property
    def sim_time(self) -> float:
        return float(self.data.time)

    @property
    def control_dt(self) -> float:
        return PHYSICS_DT * CONTROL_DECIMATION

    @property
    def episode(self) -> int:
        """처음으로 되돌린 횟수 (띄울 때 0).

        명령의 답과 상태가 다른 길로 오는 연결(ROS 2)에서도 되돌린 뒤의 상태를 알아보게.
        """
        return self._episode

    @property
    def scenario(self) -> Scenario:
        return self._scenario

    @property
    def root_body(self) -> int:
        return self._root

    def reset(self, scenario: str | None = None) -> None:
        if scenario is not None:
            self._scenario = SCENARIOS[scenario]
        mujoco.mj_resetData(self.model, self.data)
        self._episode += 1
        for index, pilot in enumerate(self.pilots):
            plan = self._plan(index)
            if plan is not None:
                joint = self.model.body_jntadr[pilot.body]
                address = self.model.jnt_qposadr[joint]
                self.data.qpos[address : address + 3] = plan.target_at(0.0)[0]
        self.units.reset({drone_id(index) for index in range(len(self._scenario.drones))})
        self.rifle.reset()
        self.gunner.reset()
        for side, arm in self.arms.items():
            arm.hold(READY_POSES[side])
        self._command = HOLD
        self._aim = None
        self._guard = False
        self._guard_unit = None
        self._push_until = 0.0
        self._events.clear()
        mujoco.mj_forward(self.model, self.data)

    def apply(self, command: Command) -> None:
        """명령을 적용한다. 지금 할 수 없는 명령은 CommandRejectedError로 까닭을 알린다."""
        match command:
            case Fly(flight=flight):
                self._require_operational(command)
                self._command = flight
            case AimUnit(unit=unit_id):
                self._require_drone(unit_id, command)
                self._aim = unit_id
            case AimPoint(point=point):
                self._aim = np.array(point, dtype=float)
            case LowerAim():
                self._aim = None
            case Guard(raised=raised, unit=unit_id):
                if unit_id is not None:
                    self._require_drone(unit_id, command)
                self._guard = raised
                self._guard_unit = unit_id if raised else None
            case Fire():
                self._require_operational(command)
                try:
                    self._events.extend(self.rifle.fire(self.model, self.data, self.units, self.sim_time))
                except NotReadyError as error:
                    raise CommandRejectedError(str(error), command.id) from error
            case Push(force=force, duration_s=duration):
                self.data.xfrc_applied[self._root, :3] = force
                self._push_until = self.sim_time + duration
            case Reset(scenario=scenario):
                self.reset(scenario)

    def step_control_tick(self) -> None:
        operational = self.units.mecha.alive
        for _ in range(CONTROL_DECIMATION):
            now = self.sim_time
            if self._push_until and now >= self._push_until:
                self.data.xfrc_applied[self._root, :] = 0
                self._push_until = 0.0
            for index, pilot in enumerate(self.pilots):
                unit = self.units.get(drone_id(index))
                pilot.apply(self.data, self._plan(index), unit is not None and (unit.alive or not unit.active), now)
            self._drive_arms(operational)
            self.flight.apply(self.data, self._command, idle=self._is_idle())
            mujoco.mj_step(self.model, self.data)
        self.rifle.recharge(self.control_dt)
        armed = {drone_id(index) for index, plan in enumerate(self._scenario.drones) if plan.armed}
        self._events.extend(self.gunner.step(self.data, self.units, armed, self.sim_time))

    def drain_events(self) -> list[dict]:
        events = [event.as_message() for event in self._events]
        self._events.clear()
        return events

    def body_poses(self, bodies: np.ndarray) -> np.ndarray:
        """bodies마다 [x, y, z, qw, qx, qy, qz]"""
        return np.hstack([self.data.xpos[bodies], self.data.xquat[bodies]])

    def mecha_status(self) -> dict:
        data = self.data
        rotation = data.xmat[self._root].reshape(3, 3)
        heading = heading_of(rotation)
        world_velocity = data.qvel[self._root_dof : self._root_dof + 3]
        world_spin = rotation @ data.qvel[self._root_dof + 3 : self._root_dof + 6]
        cos_h, sin_h = math.cos(heading), math.sin(heading)
        position = data.xpos[self._root]
        mecha = self.units.mecha
        return {
            "position": _rounded(position),
            "heading": round(heading, 4),
            "altitude": round(max(0.0, float(position[2]) - STAND_HEIGHT_M), 2),
            "velocity": {
                "forward": round(float(cos_h * world_velocity[0] + sin_h * world_velocity[1]), 3),
                "sideways": round(float(-sin_h * world_velocity[0] + cos_h * world_velocity[1]), 3),
                "up": round(float(world_velocity[2]), 3),
                "turn": round(float(world_spin[2]), 3),
            },
            "command": self._command.as_dict(),
            "mode": self._mode(),
            "hp": mecha.hp,
            "maxHp": mecha.max_hp,
            "energy": round(self.rifle.energy, 1),
            "weapon": self._weapon_status(),
            "guard": {"raised": self._guard, "unit": self._guard_unit},
            "pushing": self._push_until > 0,
        }

    def units_status(self) -> list[dict]:
        statuses = []
        for index, unit in enumerate(self.units.drones()):
            if not unit.active:
                continue
            velocity = self.data.cvel[unit.body][3:]
            statuses.append(
                {
                    "id": unit.id,
                    "kind": unit.kind,
                    "name": unit.name,
                    "position": _rounded(self.data.xpos[unit.body]),
                    "velocity": _rounded(velocity),
                    "hp": unit.hp,
                    "maxHp": unit.max_hp,
                    "alive": unit.alive,
                    "armed": self._scenario.drones[index].armed,
                }
            )
        return statuses

    def threats(self) -> list[dict]:
        return self.gunner.threats(self.sim_time)

    def is_grounded(self) -> bool:
        if self.data.xpos[self._root][2] - STAND_HEIGHT_M < GROUND_TOLERANCE_M:
            return True
        for contact in self.data.contact[: self.data.ncon]:
            geoms = (int(contact.geom1), int(contact.geom2))
            if self._floor in geoms:
                other = geoms[1] if geoms[0] == self._floor else geoms[0]
                if self.model.body_rootid[self.model.geom_bodyid[other]] == self._root:
                    return True
        return False

    def aim_point(self) -> np.ndarray | None:
        if isinstance(self._aim, str):
            unit = self.units.get(self._aim)
            return self.data.xpos[unit.body].copy() if unit else None
        return self._aim

    def _plan(self, index: int):
        drones = self._scenario.drones
        return drones[index] if index < len(drones) else None

    def _drive_arms(self, operational: bool) -> None:
        right, left = self.arms["right"], self.arms["left"]
        if not operational:
            right.relax(self.data)
            left.relax(self.data)
            return
        point = self.aim_point()
        if point is not None:
            right.point_at(self.data, point)
        else:
            right.hold(READY_POSES["right"])
        if self._guard:
            left.point_at(self.data, self._guard_point())
        else:
            left.hold(READY_POSES["left"])
        right.apply(self.data)
        left.apply(self.data)

    def _guard_point(self) -> np.ndarray:
        """방패를 들 곳: 막을 유닛에서 몸통으로 오는 길 위, 없으면 기수 방향 앞"""
        torso = self.data.xpos[self._root]
        unit = self.units.get(self._guard_unit) if self._guard_unit else None
        if unit is not None and unit.alive:
            toward = self.data.xpos[unit.body] - torso
        else:
            heading = heading_of(self.data.xmat[self._root].reshape(3, 3))
            toward = np.array([math.cos(heading), math.sin(heading), 0.0])
        return torso + toward / np.linalg.norm(toward) * GUARD_REACH_M

    def _is_idle(self) -> bool:
        if not self.units.mecha.alive:
            return True
        command = self._command
        resting = command.up <= 0 and command.forward == 0 and command.sideways == 0 and command.turn == 0
        speed = float(np.linalg.norm(self.data.qvel[self._root_dof : self._root_dof + 3]))
        return resting and speed < LANDED_SPEED_MPS and self.is_grounded()

    def _mode(self) -> str:
        if not self.units.mecha.alive:
            return "destroyed"
        return "landed" if self._is_idle() else "flying"

    def _weapon_status(self) -> dict:
        now = self.sim_time
        status = {
            "ready": self.rifle.not_ready_reason(now) is None,
            "cooldown": round(self.rifle.cooldown_left(now), 2),
            "aimTarget": self._aim if isinstance(self._aim, str) else None,
        }
        point = self.aim_point()
        if point is not None:
            muzzle, barrel = self.rifle.barrel(self.data)
            toward = point - muzzle
            cosine = float(np.dot(barrel, toward) / max(np.linalg.norm(toward), 1e-9))
            status["aimError"] = round(math.degrees(math.acos(float(np.clip(cosine, -1.0, 1.0)))), 2)
            status["aimPoint"] = _rounded(point)
        return status

    def _require_drone(self, unit_id: str, command: Command) -> None:
        unit = self.units.get(unit_id)
        if unit is None or not unit.active or unit.kind != "drone":
            raise CommandRejectedError(f"그런 표적이 없습니다: {unit_id}", command.id)

    def _require_operational(self, command: Command) -> None:
        if not self.units.mecha.alive:
            raise CommandRejectedError("기체가 파괴되었습니다. 처음으로 되돌려 주세요", command.id)


def _rounded(vector: np.ndarray) -> list[float]:
    return [round(float(value), 3) for value in vector]
