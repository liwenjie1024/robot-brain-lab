#pragma once

// 关节空间的硬限制（运动的安全过滤的第二道，系统结构第 2 节）：小脑层是学出来的，遇到没见过的情况
// 也可能给出不对的目标。脊髓层每 1 毫秒查一遍，超了就改小，并且记下是哪一种限制改的，告诉小脑层。

#include <cstdint>
#include <limits>

namespace nova::rt {

// 每种限制一位：一个关节这一步被哪几种限制改过。
enum LimitFlag : std::uint8_t {
  kLimitAngle = 1U << 0U,          // 目标超出了关节的范围
  kLimitTorque = 1U << 1U,         // 要的力矩超过了这个关节最多能出的
  kLimitSpeed = 1U << 2U,          // 已经转到了最快，不再往这个方向推
  kLimitPower = 1U << 3U,          // 往转的方向推的功率超过了上限
  kLimitActuatorForce = 1U << 4U,  // 带着它的驱动器出到了顶（并联的一对两个关节分着用）
};

// 一个关节的上限。不知道的（基线的身体没有驱动器的模型）是无穷大。
struct JointLimits {
  double lower_rad = -std::numeric_limits<double>::infinity();
  double upper_rad = std::numeric_limits<double>::infinity();
  double peak_torque_nm = std::numeric_limits<double>::infinity();
  double max_speed_rad_s = std::numeric_limits<double>::infinity();
  double max_power_w = std::numeric_limits<double>::infinity();
};

struct LimitedValue {
  double value = 0.0;
  std::uint8_t flags = 0;
};

// 目标的角度留在关节的范围里（两头各让出 margin_rad）。范围比 2 x margin 还窄时放在正中间。
LimitedValue limit_target(double target_rad, const JointLimits& limits, double margin_rad);

// 要的力矩按顺序过三道：不超过峰值；已经转到最快时不再往这个方向推；往转的方向推的功率不超过上限。
// 往反方向刹（收功）不限功率：刹车的力只受峰值限。
LimitedValue limit_torque(double torque_nm, double speed_rad_s, const JointLimits& limits);

}  // namespace nova::rt
