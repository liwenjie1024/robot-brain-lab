# 기체 상태 (contracts/sim의 MechaStatus)
string MODE_LANDED=landed
string MODE_FLYING=flying
string MODE_DESTROYED=destroyed

# 세계 기준 [x, y, z] m
float64[3] position
# 기수 방향 rad (x축에서 왼쪽으로 +)
float64 heading
# 발바닥 기준 높이 m
float64 altitude
# 몸 기준 실제 속도와 명령한 속도 (REP 103: linear.x 앞, linear.y 왼쪽, linear.z 위, angular.z 왼쪽으로 돌기)
geometry_msgs/Twist velocity
geometry_msgs/Twist command
string mode
float64 hp
float64 max_hp
float64 energy
WeaponStatus weapon
GuardStatus guard
bool pushing
