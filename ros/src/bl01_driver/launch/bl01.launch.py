"""BL-01 몸 드라이버와 rosbridge를 함께 띄운다. 두뇌·화면은 rosbridge(WebSocket, :9090)로 붙는다."""

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

ROSBRIDGE_PORT = "9090"


def generate_launch_description() -> LaunchDescription:
    driver = Node(package="bl01_driver", executable="driver", name="bl01_driver", output="screen")
    rosbridge = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare("rosbridge_server"), "launch", "rosbridge_websocket_launch.xml"])
        ),
        # 서비스는 따로 스레드에서 불러, 몸의 답을 기다리는 동안에도 다른 요청과 토픽을 처리한다
        launch_arguments={"port": ROSBRIDGE_PORT, "call_services_in_new_thread": "true"}.items(),
    )
    return LaunchDescription([driver, rosbridge])
