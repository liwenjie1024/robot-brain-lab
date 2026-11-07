# 소총 상태 (contracts/sim의 WeaponStatus). 값이 없는 것은 has_* 로 알린다.
bool ready
# 다시 쏠 수 있기까지 남은 초
float64 cooldown
# 겨누는 유닛 id (겨누지 않으면 빈 글)
string aim_target
# 총열 방향과 겨눈 방향의 어긋난 각(도). 겨누고 있을 때만 뜻이 있다
bool has_aim_error
float64 aim_error
# 점을 겨누고 있으면 그 점 [x, y, z] m
bool has_aim_point
float64[3] aim_point
