# ROS 2 쪽 몸: 몸(시뮬레이터)의 WebSocket을 ROS 2 토픽·서비스로 내는 드라이버 노드와 rosbridge.
# 두뇌·화면은 rosbridge(WebSocket, :9090)로, ROS 2 도구(rviz2·rosbag2)는 이 컨테이너 안에서 붙는다.
# 빌드 위치는 저장소 맨 위다: docker compose build ros
# ROS 2 Lyrical Luth (장기 지원 2031년까지). 이미지는 digest로, 패키지는 판으로 고정한다 (2026-09-15 ROS 동기화).
FROM ros:lyrical-ros-base@sha256:3224ee150cb02eb89a5e0811bc267b57ed3a91b9c10191df57810726a7e916d7

# 메시지 정의의 한국어 주석을 읽으려면 UTF-8이어야 한다. ROS 2 통신은 이 컨테이너 안에서만 찾는다.
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ros-lyrical-rosbridge-suite=4.2.1-1resolute.20260915.090224 \
      python3-websockets=15.0.1-1build2 \
      python3-pytest=9.0.2-4 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /ws
COPY ros/src src
RUN source /opt/ros/lyrical/setup.bash && colcon build --event-handlers console_direct-
COPY --chmod=755 ros/scripts/record-bag.sh /usr/local/bin/bl01-record

EXPOSE 9090
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s CMD bash -c 'echo > /dev/tcp/127.0.0.1/9090'
CMD ["bash", "-c", "source /ws/install/setup.bash && exec ros2 launch bl01_driver bl01.launch.py"]
