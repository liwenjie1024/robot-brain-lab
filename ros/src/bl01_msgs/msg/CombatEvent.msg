# 사격·격파 사건 (contracts/sim의 ShotMessage·DestroyedMessage). 빠짐없이 보낸다.
string KIND_SHOT=shot
string KIND_DESTROYED=destroyed

string kind
float64 sim_time
# kind가 shot일 때: 쏜 유닛, 광선의 시작·끝 [x, y, z] m, 맞힌 것
string shooter
float64[3] origin
float64[3] end
bool has_hit
string hit_unit
float64 hit_damage
bool hit_blocked
# kind가 destroyed일 때: 파괴된 유닛
string unit
