"""무장: 기체의 빔 소총과 드론의 반격.

사격은 총구에서 실제 총열 방향으로 광선을 쏘아 처음 닿는 것을 맞힌다. 겨눈 방향이 아니라 팔이 실제로 가리키는
방향이라, 팔이 덜 돌아갔거나 기체가 흔들리면 빗나간다 (두뇌가 조준을 기다려야 하는 까닭).
"""

from __future__ import annotations

from dataclasses import dataclass

import mujoco
import numpy as np

from .combat import DestroyedEvent, Event, Hit, ShotEvent, Units, cast, ray_groups
from .drones import DRONE_RADIUS_M
from .mecha import DRONE_GROUP, MECHA_GROUP, MUZZLE_SITE, WORLD_GROUP

RIFLE_RANGE_M = 1500.0
RIFLE_DAMAGE = 30.0
RIFLE_COOLDOWN_S = 0.5
RIFLE_MAX_ENERGY = 100.0
RIFLE_SHOT_ENERGY = 20.0
RIFLE_RECHARGE_PER_S = 8.0

DRONE_RANGE_M = 600.0
DRONE_DAMAGE = 40.0
# 조준(경고)부터 사격까지. 두뇌가 경고를 보고 피하거나 방패를 들 시간이다.
DRONE_LOCK_S = 1.2
DRONE_COOLDOWN_S = 3.0
# 드론마다 처음 쏠 수 있는 때를 이만큼씩 벌린다 (경고가 한꺼번에 오지 않고 하나씩 막아 볼 수 있게).
DRONE_STAGGER_S = 1.0
# 드론 사격의 흩어짐 (조준점 둘레 m, 표준편차). 기체 몸통 폭(약 4m)보다 작게.
DRONE_SPREAD_M = 0.8
DRONE_RNG_SEED = 7
# 시뮬레이션 시각은 물리 주기를 더해 가는 실수라 정확히 같은 때가 조금 모자랄 수 있다.
# 이보다 적게 남았으면 끝난 것으로 본다 ("0.0초 남음"으로 거절하지 않게).
TIME_EPSILON_S = 1e-6


class NotReadyError(RuntimeError):
    """지금은 쏠 수 없다 (메시지는 그대로 보낸 쪽에 알린다)."""


class Rifle:
    def __init__(self, model: mujoco.MjModel) -> None:
        self._muzzle = model.site(MUZZLE_SITE).id
        self._groups = ray_groups(WORLD_GROUP, DRONE_GROUP)
        self.energy = RIFLE_MAX_ENERGY
        self._ready_at = 0.0

    def reset(self) -> None:
        self.energy = RIFLE_MAX_ENERGY
        self._ready_at = 0.0

    def recharge(self, seconds: float) -> None:
        self.energy = min(RIFLE_MAX_ENERGY, self.energy + RIFLE_RECHARGE_PER_S * seconds)

    def cooldown_left(self, now: float) -> float:
        remaining = self._ready_at - now
        return remaining if remaining > TIME_EPSILON_S else 0.0

    def not_ready_reason(self, now: float) -> str | None:
        if self.cooldown_left(now) > 0:
            return f"소총이 아직 식는 중입니다 ({self.cooldown_left(now):.1f}초 남음)"
        if self.energy < RIFLE_SHOT_ENERGY:
            return f"에너지가 모자랍니다 ({self.energy:.0f}/{RIFLE_SHOT_ENERGY:.0f})"
        return None

    def barrel(self, data: mujoco.MjData) -> tuple[np.ndarray, np.ndarray]:
        """총구 위치와 실제 총열 방향(단위 벡터)"""
        return data.site_xpos[self._muzzle].copy(), data.site_xmat[self._muzzle].reshape(3, 3)[:, 2].copy()

    def fire(self, model: mujoco.MjModel, data: mujoco.MjData, units: Units, now: float) -> list[Event]:
        reason = self.not_ready_reason(now)
        if reason:
            raise NotReadyError(reason)
        self.energy -= RIFLE_SHOT_ENERGY
        self._ready_at = now + RIFLE_COOLDOWN_S
        start, direction = self.barrel(data)
        end, geom = cast(model, data, start, direction, groups=self._groups, max_range=RIFLE_RANGE_M)
        target = units.of_geom(geom) if geom is not None else None
        events: list[Event] = []
        hit = None
        if target is not None and target.alive:
            hit = Hit(target.id, RIFLE_DAMAGE, blocked=False)
            if units.damage(target, RIFLE_DAMAGE):
                events.append(DestroyedEvent(target.id, now))
        events.insert(0, ShotEvent(units.mecha.id, _tuple(start), _tuple(end), hit, now))
        return events


@dataclass
class _Lock:
    started: float


class DroneGunner:
    """무장한 드론의 반격: 기체가 사거리 안에 보이면 조준(경고)하고, 정한 시간 뒤 쏜다."""

    def __init__(self, model: mujoco.MjModel) -> None:
        self._model = model
        self._groups = ray_groups(WORLD_GROUP, MECHA_GROUP)
        self._locks: dict[str, _Lock] = {}
        self._ready_at: dict[str, float] = {}
        self._rng = np.random.default_rng(DRONE_RNG_SEED)

    def reset(self) -> None:
        self._locks.clear()
        self._ready_at.clear()
        self._rng = np.random.default_rng(DRONE_RNG_SEED)

    def threats(self, now: float) -> list[dict]:
        return [
            {"from": drone, "secondsToFire": round(max(0.0, DRONE_LOCK_S - (now - lock.started)), 2)}
            for drone, lock in sorted(self._locks.items())
        ]

    def step(self, data: mujoco.MjData, units: Units, armed: set[str], now: float) -> list[Event]:
        mecha = units.mecha
        events: list[Event] = []
        for index, drone in enumerate(units.drones()):
            if drone.id not in armed or not drone.alive or not mecha.alive:
                self._locks.pop(drone.id, None)
                continue
            if not self._sees_mecha(data, units, drone.body):
                self._locks.pop(drone.id, None)
                continue
            lock = self._locks.get(drone.id)
            if lock is None:
                if now >= self._ready_at.get(drone.id, index * DRONE_STAGGER_S):
                    self._locks[drone.id] = _Lock(now)
                continue
            if now - lock.started >= DRONE_LOCK_S:
                del self._locks[drone.id]
                self._ready_at[drone.id] = now + DRONE_COOLDOWN_S
                events.extend(self._fire(data, units, drone.id, drone.body, now))
        return events

    def _sees_mecha(self, data: mujoco.MjData, units: Units, drone_body: int) -> bool:
        start, toward = self._aim_line(data, units, drone_body)
        if np.linalg.norm(toward) > DRONE_RANGE_M:
            return False
        _, geom = cast(self._model, data, start, toward, groups=self._groups, max_range=DRONE_RANGE_M)
        return geom is not None and units.of_geom(geom) is units.mecha

    def _aim_line(self, data: mujoco.MjData, units: Units, drone_body: int) -> tuple[np.ndarray, np.ndarray]:
        center = data.xpos[drone_body]
        target = data.xpos[units.mecha.body]
        toward = target - center
        # 드론 자신의 겉면 밖에서 쏜다 (광선은 드론 묶음을 보지 않지만, 거리를 겉면 기준으로 맞춘다).
        start = center + toward / np.linalg.norm(toward) * DRONE_RADIUS_M
        return start, target - start

    def _fire(self, data: mujoco.MjData, units: Units, drone: str, drone_body: int, now: float) -> list[Event]:
        start, toward = self._aim_line(data, units, drone_body)
        aim = start + toward + self._rng.normal(0.0, DRONE_SPREAD_M, 3)
        end, geom = cast(self._model, data, start, aim - start, groups=self._groups, max_range=DRONE_RANGE_M)
        hit_unit = units.of_geom(geom) if geom is not None else None
        events: list[Event] = []
        hit = None
        if hit_unit is units.mecha and geom is not None:
            blocked = units.is_shield(geom)
            damage = 0.0 if blocked else DRONE_DAMAGE
            hit = Hit(units.mecha.id, damage, blocked)
            if damage and units.damage(units.mecha, damage):
                events.append(DestroyedEvent(units.mecha.id, now))
        events.insert(0, ShotEvent(drone, _tuple(start), _tuple(end), hit, now))
        return events


def _tuple(vector: np.ndarray) -> tuple[float, float, float]:
    return (round(float(vector[0]), 3), round(float(vector[1]), 3), round(float(vector[2]), 3))
