"""몸 드라이버 노드: ROS 2 서비스로 받은 명령을 몸에 보내고 답을 돌려주며, 몸의 상태·사건을 토픽으로 낸다 (rclpy를 실제로 돌린다)"""

import threading
import time

import pytest
import rclpy
from bl01_msgs.msg import CombatEvent, State
from bl01_msgs.srv import Aim, GetScene, Guard, Reset, SetVelocity
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool

from bl01_driver.driver_node import UNSUPPORTED_ROTATION, DriverNode
from bl01_driver.sim_link import Outcome

from .samples import SHOT_HIT, STATE

WAIT_S = 5.0
RELIABLE = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)


class FakeLink:
    def __init__(self) -> None:
        self.commands: list[dict] = []
        self.outcome = Outcome(True)

    def send(self, command: dict) -> Outcome:
        self.commands.append(command)
        return self.outcome


def wait_until(condition, timeout: float = WAIT_S) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "기다린 일이 일어나지 않았다"
        time.sleep(0.01)


@pytest.fixture
def ros():
    rclpy.init()
    link = FakeLink()
    driver = DriverNode(link)
    client = Node("test_client")
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(driver)
    executor.add_node(client)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    yield driver, client, link
    executor.shutdown()
    driver.destroy_node()
    client.destroy_node()
    rclpy.try_shutdown()


def call(client: Node, service_type, name: str, request):
    service = client.create_client(service_type, name)
    assert service.wait_for_service(timeout_sec=WAIT_S)
    future = service.call_async(request)
    wait_until(future.done)
    return future.result()


def collect(client: Node, message_type, topic: str, qos=RELIABLE) -> list:
    received: list = []
    client.create_subscription(message_type, topic, received.append, qos)
    return received


def test_service_sends_command_and_returns_acceptance(ros):
    """서비스로 받은 명령을 몸의 명령으로 바꿔 보내고, 몸의 답(받음)을 돌려준다"""
    _driver, client, link = ros

    response = call(client, Aim, "/bl01/aim", Aim.Request(unit="drone-1"))

    assert (response.accepted, response.reason) == (True, "")
    assert link.commands == [{"type": "aim", "unit": "drone-1"}]


def test_rejection_reason_comes_back(ros):
    """실패: 몸이 거절하면 까닭을 서비스 답에 담는다"""
    _driver, client, link = ros
    link.outcome = Outcome(False, "그런 표적이 없습니다: drone-9")

    response = call(client, Guard, "/bl01/guard", Guard.Request(raised=True, unit="drone-9"))

    assert (response.accepted, response.reason) == (False, "그런 표적이 없습니다: drone-9")
    assert link.commands == [{"type": "guard", "raised": True, "unit": "drone-9"}]


def test_velocity_with_roll_or_pitch_is_rejected_without_reaching_body(ros):
    """실패: 기체가 할 수 없는 회전(x·y축)은 잘라 쓰지 않고 몸에 보내기 전에 거절한다"""
    _driver, client, link = ros
    velocity = Twist()
    velocity.linear.x, velocity.angular.x = 10.0, 0.5

    response = call(client, SetVelocity, "/bl01/set_velocity", SetVelocity.Request(velocity=velocity))

    assert (response.accepted, response.reason) == (False, UNSUPPORTED_ROTATION)
    assert link.commands == []


def test_reset_without_scenario_keeps_current_scene(ros):
    """경계값: 장면 이름이 빈 글이면 지금 장면으로 되돌린다"""
    _driver, client, link = ros

    call(client, Reset, "/bl01/reset", Reset.Request(scenario=""))

    assert link.commands == [{"type": "reset"}]


def test_scene_is_available_only_while_connected_to_body(ros):
    """장면 설명은 몸에서 받고 몸과 붙어 있는 동안만 준다 (끊기면 available=false라 두뇌가 붙은 줄로 알지 않는다)"""
    driver, client, _link = ros
    scene = '{"robot": {"name": "BL-01"}}'

    before = call(client, GetScene, "/bl01/get_scene", GetScene.Request())
    driver.set_scene(scene)
    not_linked = call(client, GetScene, "/bl01/get_scene", GetScene.Request())
    driver.set_link(connected=True)
    linked = call(client, GetScene, "/bl01/get_scene", GetScene.Request())
    driver.set_link(connected=False)
    dropped = call(client, GetScene, "/bl01/get_scene", GetScene.Request())

    assert (before.available, before.scene_json) == (False, "")
    assert not_linked.available is False
    assert (linked.available, linked.scene_json) == (True, scene)
    assert dropped.available is False


def test_state_is_published_with_standard_odometry(ros):
    """몸의 상태를 /bl01/state 한 장으로, 위치·속도는 표준 /odom으로도 낸다"""
    driver, client, _link = ros
    states = collect(client, State, "/bl01/state")
    odoms = collect(client, Odometry, "/odom")
    time.sleep(0.3)

    wait_until(lambda: (driver.publish_state(STATE), bool(states and odoms))[1])

    assert (states[0].seq, states[0].episode, states[0].scenario) == (41, 3, "skirmish")
    assert odoms[0].pose.pose.position.z == 30.5


def test_combat_events_are_published(ros):
    """사격·격파 사건을 /bl01/combat으로 낸다"""
    driver, client, _link = ros
    events = collect(client, CombatEvent, "/bl01/combat")
    time.sleep(0.3)

    wait_until(lambda: (driver.publish_event(SHOT_HIT), bool(events))[1])

    assert (events[0].kind, events[0].hit_unit) == ("shot", "drone-1")


def test_malformed_state_is_dropped_without_stopping_the_node(ros):
    """실패: 규약과 다른 상태는 버리고(기록), 다음 상태는 그대로 낸다"""
    driver, client, _link = ros
    states = collect(client, State, "/bl01/state")
    time.sleep(0.3)

    driver.publish_state({"type": "state"})
    wait_until(lambda: (driver.publish_state(STATE), bool(states))[1])

    assert all(state.seq == 41 for state in states)


def test_link_state_reaches_late_subscribers(ros):
    """몸과 붙었는지는 늦게 붙은 쪽도 바로 받는다 (마지막 값을 남겨 둔다)"""
    driver, client, _link = ros
    driver.set_link(connected=True)
    time.sleep(0.2)

    links = collect(client, Bool, "/bl01/link", LATCHED)

    wait_until(lambda: bool(links))
    assert links[-1].data is True


def test_cmd_vel_drives_the_body(ros):
    """표준 /cmd_vel(teleop 도구)로도 몰 수 있다 (답이 없어 두뇌는 서비스를 쓴다)"""
    _driver, client, link = ros
    publisher = client.create_publisher(Twist, "/cmd_vel", RELIABLE)
    velocity = Twist()
    velocity.linear.x, velocity.angular.z = 5.0, 0.2
    time.sleep(0.3)

    wait_until(lambda: (publisher.publish(velocity), bool(link.commands))[1])

    assert link.commands[0] == {"type": "velocity", "forward": 5.0, "sideways": 0.0, "up": 0.0, "turn": 0.2}
