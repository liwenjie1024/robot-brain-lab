#!/usr/bin/env bash
# 몸이 ROS 2로 내는 것을 rosbag2(MCAP)로 남긴다. 시험 한 묶음을 돌리기 전에 띄우고, 끝나면 Ctrl+C로 멈춘다.
#   docker compose exec ros bl01-record [이름]     → 이 PC의 results/bags/<이름> (git에 넣지 않는다)
# 남긴 것은 ros2 bag info·play, Foxglove(MCAP 파일 열기)로 본다.
set -eo pipefail
# ROS 설정 스크립트는 정하지 않은 변수를 읽으므로 -u는 그 뒤에 켠다
source /ws/install/setup.bash
set -u

BAG_ROOT=/bags
TOPICS=(/bl01/state /bl01/combat /bl01/link /odom /tf /clock)
name="${1:-$(date -u +%Y-%m-%dT%H-%M-%SZ)}"

exec ros2 bag record --storage mcap --output "${BAG_ROOT}/${name}" --topics "${TOPICS[@]}"
