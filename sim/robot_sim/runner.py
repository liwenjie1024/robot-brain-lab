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

from .commands import Command, CommandRejectedError
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
    def __init__(
        self,
        simulation: Simulation,
        bodies: np.ndarray,
        publish_state: Callable[[dict], None],
        publish_event: Callable[[dict], None],
    ) -> None:
        self._simulation = simulation
        self._bodies = bodies
        self._publish_state = publish_state
        self._publish_event = publish_event
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
        tick = self._simulation.control_dt
        next_tick = time.perf_counter()
        while not self._stopping.is_set():
            self.tick()
            next_tick += tick
            delay = next_tick - time.perf_counter()
            if delay > 0:
                self._stopping.wait(delay)
            elif delay < -MAX_LAG_SECONDS:
                log.warning("시뮬레이션이 실제 시간보다 %.2f초 늦어 다시 맞춘다", -delay)
                next_tick = time.perf_counter()

    def tick(self) -> None:
        """밀린 명령 적용 → 한 제어 주기 진행 → 사건과 상태 알리기 (시험에서 직접 부른다)."""
        self._apply_pending()
        self._simulation.step_control_tick()
        for event in self._simulation.drain_events():
            self._publish_event(event)
        self._publish_state(self.state_message())

    def _apply_pending(self) -> None:
        while True:
            try:
                pending = self._commands.get_nowait()
            except queue.Empty:
                return
            command = pending.command
            try:
                self._simulation.apply(command)
            except CommandRejectedError as error:
                pending.reply(rejected_message(error.reason, command.id))
                continue
            ack = {"type": "ack", "commandType": command.type, "simTime": self._simulation.sim_time}
            if command.id is not None:
                ack["id"] = command.id
            pending.reply(ack)
            # 사격처럼 바로 사건이 생기는 명령은 답 바로 뒤에 사건을 보낸다 (답 → 사건 → 상태 순서).
            for event in self._simulation.drain_events():
                self._publish_event(event)

    def state_message(self) -> dict:
        self._seq += 1
        simulation = self._simulation
        return {
            "type": "state",
            "seq": self._seq,
            "episode": simulation.episode,
            "simTime": round(simulation.sim_time, 4),
            "scenario": simulation.scenario.name,
            "bodies": np.round(simulation.body_poses(self._bodies), 4).ravel().tolist(),
            "mecha": simulation.mecha_status(),
            "units": simulation.units_status(),
            "threats": simulation.threats(),
        }


def rejected_message(reason: str, command_id: str | None) -> dict:
    message = {"type": "rejected", "reason": reason}
    if command_id is not None:
        message["id"] = command_id
    return message
