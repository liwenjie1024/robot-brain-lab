# 몸의 상태 한 장 (contracts/sim의 StateMessage와 같은 내용). 제어 주기마다(50Hz).
# 두뇌가 한 번에 판단할 수 있게 나누지 않고 한 메시지로 보낸다 (표준 /odom·/tf도 따로 낸다).
# header.stamp는 시뮬레이션 시각, frame_id는 odom
std_msgs/Header header
# 보낸 순서
uint64 seq
# 처음으로 되돌린 횟수 (서비스 답과 이 토픽은 다른 길로 오므로 되돌린 뒤의 상태를 이것으로 알아본다)
uint32 episode
float64 sim_time
string scenario
# 움직이는 몸체마다 [x, y, z, qw, qx, qy, qz] 7개씩 (순서는 장면 설명의 movingBodies)
float64[] bodies
MechaStatus mecha
UnitStatus[] units
Threat[] threats
