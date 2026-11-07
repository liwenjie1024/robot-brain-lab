"""BL-01 몸 드라이버 노드: 몸(시뮬레이터)을 ROS 2 표준 방식으로 보이게 한다.

- 토픽: /bl01/state(상태 한 장, 50Hz), /bl01/combat(사격·격파), /bl01/link(몸과 붙었는지),
  표준 /odom·/tf·/clock (rviz2·Foxglove·rosbag2가 읽는다)
- 서비스: /bl01/set_velocity·stop·aim·aim_point·lower_aim·guard·fire·push·reset (답: 받았는지·까닭), /bl01/get_scene
- 받는 토픽: 표준 /cmd_vel (teleop 같은 도구로 몰 때. 답이 없어 두뇌는 서비스를 쓴다)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Protocol

import rclpy
from bl01_msgs.msg import CombatEvent, State
from bl01_msgs.srv import Aim, AimPoint, Fire, GetScene, Guard, LowerAim, Push, Reset, SetVelocity, Stop
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rosgraph_msgs.msg import Clock
from std_msgs.msg import Bool
from tf2_ros import TransformBroadcaster

from . import convert
from .sim_link import Outcome, SimLink

NAMESPACE = "/bl01"
DEFAULT_SIM_URL = "ws://sim:8765/ws"
STATE_DEPTH = 10
# 사건은 빠짐없이 보내야 하므로 넉넉히 쌓아 둔다
COMBAT_DEPTH = 200
# 서비스가 몸의 답을 기다리는 동안 다른 서비스·토픽도 처리하게
EXECUTOR_THREADS = 8
UNSUPPORTED_ROTATION = "기체는 z축으로만 돕니다 (angular.x·angular.y는 0이어야 합니다)"


class CommandLink(Protocol):
    def send(self, command: dict) -> Outcome: ...


class DriverNode(Node):
    def __init__(self, link: CommandLink) -> None:
        super().__init__("bl01_driver")
        self._link = link
        self._scene_json = ""
        self._connected = False
        self._group = ReentrantCallbackGroup()
        reliable = QoSProfile(depth=STATE_DEPTH, reliability=ReliabilityPolicy.RELIABLE)
        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self._state_pub = self.create_publisher(State, f"{NAMESPACE}/state", reliable)
        self._combat_pub = self.create_publisher(
            CombatEvent, f"{NAMESPACE}/combat", QoSProfile(depth=COMBAT_DEPTH, reliability=ReliabilityPolicy.RELIABLE)
        )
        self._link_pub = self.create_publisher(Bool, f"{NAMESPACE}/link", latched)
        self._odom_pub = self.create_publisher(Odometry, "/odom", reliable)
        self._clock_pub = self.create_publisher(Clock, "/clock", reliable)
        self._tf = TransformBroadcaster(self)
        self._serve(SetVelocity, "set_velocity", self._velocity_request)
        self._serve(Stop, "stop", lambda _request: {"type": "stop"})
        self._serve(Aim, "aim", lambda request: {"type": "aim", "unit": request.unit})
        self._serve(AimPoint, "aim_point", lambda request: {"type": "aimPoint", "point": convert.vector(request.point)})
        self._serve(LowerAim, "lower_aim", lambda _request: {"type": "lowerAim"})
        self._serve(Guard, "guard", lambda request: convert.guard_command(request.raised, request.unit))
        self._serve(Fire, "fire", lambda _request: {"type": "fire"})
        self._serve(Push, "push", lambda request: convert.push_command(request.force, request.duration_ms))
        self._serve(Reset, "reset", lambda request: convert.reset_command(request.scenario))
        self.create_service(GetScene, f"{NAMESPACE}/get_scene", self._get_scene, callback_group=self._group)
        self.create_subscription(Twist, "/cmd_vel", self._on_cmd_vel, reliable, callback_group=self._group)
        self.set_link(connected=False)

    # 몸 연결(SimLink)이 부른다 (그 연결의 스레드에서)

    def publish_state(self, state: dict) -> None:
        try:
            message = convert.state_message(state)
            odom, transform = convert.odometry(state)
        except (KeyError, TypeError, ValueError) as error:
            self.get_logger().warning(f"몸의 상태를 바꾸지 못해 버렸다: {error!r}")
            return
        self._state_pub.publish(message)
        self._odom_pub.publish(odom)
        self._tf.sendTransform(transform)
        self._clock_pub.publish(Clock(clock=message.header.stamp))

    def publish_event(self, event: dict) -> None:
        try:
            message = convert.combat_event(event)
        except (KeyError, TypeError, ValueError) as error:
            self.get_logger().warning(f"몸의 사건을 바꾸지 못해 버렸다: {error!r}")
            return
        self._combat_pub.publish(message)

    def set_link(self, *, connected: bool) -> None:
        self._connected = connected
        self._link_pub.publish(Bool(data=connected))

    def set_scene(self, scene_json: str) -> None:
        self._scene_json = scene_json

    # 서비스

    def _serve(self, service_type: type, name: str, to_command: Callable[[object], dict | str]) -> None:
        """서비스 하나: 요청을 몸의 명령으로 바꿔 보내고 몸의 답을 그대로 돌려준다 (요청이 맞지 않으면 까닭이 담긴 글)."""

        def handle(request: object, response: object) -> object:
            command = to_command(request)
            outcome = Outcome(False, command) if isinstance(command, str) else self._link.send(command)
            response.accepted = outcome.accepted  # type: ignore[attr-defined]
            response.reason = outcome.reason  # type: ignore[attr-defined]
            return response

        self.create_service(service_type, f"{NAMESPACE}/{name}", handle, callback_group=self._group)

    def _velocity_request(self, request: SetVelocity.Request) -> dict | str:
        return UNSUPPORTED_ROTATION if has_unsupported_rotation(request.velocity) else convert.velocity_command(request.velocity)

    def _get_scene(self, _request: GetScene.Request, response: GetScene.Response) -> GetScene.Response:
        """몸과 붙어 있을 때만 준다: 끊긴 뒤 남은 설명을 주면 두뇌가 몸과 붙은 줄로 안다"""
        response.available = self._connected and bool(self._scene_json)
        response.scene_json = self._scene_json if response.available else ""
        return response

    def _on_cmd_vel(self, velocity: Twist) -> None:
        if has_unsupported_rotation(velocity):
            self.get_logger().warning(UNSUPPORTED_ROTATION)
            return
        outcome = self._link.send(convert.velocity_command(velocity))
        if not outcome.accepted:
            self.get_logger().warning(f"/cmd_vel을 몸이 받지 않았다: {outcome.reason}")


def has_unsupported_rotation(velocity: Twist) -> bool:
    return velocity.angular.x != 0.0 or velocity.angular.y != 0.0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    rclpy.init()
    link = SimLink(os.environ.get("SIM_WS_URL", DEFAULT_SIM_URL))
    node = DriverNode(link)
    link.on_state = node.publish_state
    link.on_event = node.publish_event
    link.on_scene = node.set_scene
    link.on_connection = lambda connected: node.set_link(connected=connected)
    link.start()
    executor = MultiThreadedExecutor(num_threads=EXECUTOR_THREADS)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt, ExternalShutdownException:
        pass
    finally:
        link.stop()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
