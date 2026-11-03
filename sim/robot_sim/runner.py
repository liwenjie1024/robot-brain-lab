"""시뮬레이션을 실제 시간에 맞춰 돌리는 스레드. 명령은 큐로 받아 제어 주기 사이에만 적용한다
(물리 계산 중간에 값이 바뀌지 않게, 그리고 시뮬레이션은 이 스레드 하나만 만지게)."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .commands import Command, Push, Reset, SetVelocity
from .simulation import Simulation

log = logging.getLogger(__name__)

# 이보다 많이 뒤처지면(디버거로 멈췄다 풀었을 때 등) 몰아서 따라잡지 않고 지금부터 다시 센다.
MAX_LAG_SECONDS = 0.25

Reply = Callable[[dict], None]


@dataclass(frozen=True)
class PendingCommand:
    command: Command
    reply: Reply


class RealtimeRunner:
    def __init__(self, simulation: Simulation, bodies: np.ndarray, publish_state: Callable[[dict], None]) -> None:
        self._simulation = simulation
        self._bodies = bodies
        self._publish_state = publish_state
        self._commands: queue.SimpleQueue[PendingCommand] = queue.SimpleQueue()
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name="simulation", daemon=True)
        self._seq = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._thread.join()

    def submit(self, command: Command, reply: Reply) -> None:
        self._commands.put(PendingCommand(command, reply))

    def _run(self) -> None:
        tick = self._simulation.controller.config.control_dt
        next_tick = time.perf_counter()
        while not self._stopping.is_set():
            self._apply_pending()
            self._simulation.step_control_tick()
            self._publish_state(self.state_message())
            next_tick += tick
            delay = next_tick - time.perf_counter()
            if delay > 0:
                self._stopping.wait(delay)
            elif delay < -MAX_LAG_SECONDS:
                log.warning("시뮬레이션이 실제 시간보다 %.2f초 늦어 다시 맞춥니다", -delay)
                next_tick = time.perf_counter()

    def _apply_pending(self) -> None:
        while True:
            try:
                pending = self._commands.get_nowait()
            except queue.Empty:
                return
            apply_command(self._simulation, pending.command)
            ack = {"type": "ack", "commandType": pending.command.type, "simTime": self._simulation.sim_time}
            if pending.command.id is not None:
                ack["id"] = pending.command.id
            pending.reply(ack)

    def state_message(self) -> dict:
        self._seq += 1
        return {
            "type": "state",
            "seq": self._seq,
            "simTime": self._simulation.sim_time,
            "bodies": np.round(self._simulation.body_poses(self._bodies), 5).ravel().tolist(),
            "robot": self._simulation.status().as_dict(),
        }


def apply_command(simulation: Simulation, command: Command) -> None:
    match command:
        case SetVelocity(velocity=velocity):
            simulation.set_command(velocity)
        case Push(force=force, duration_s=duration):
            simulation.push(force, duration)
        case Reset():
            simulation.reset()
