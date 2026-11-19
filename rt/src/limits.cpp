#include "nova_rt/limits.hpp"

#include <algorithm>
#include <cmath>

namespace nova::rt {

LimitedValue limit_target(double target_rad, const JointLimits& limits, double margin_rad) {
  double lower = limits.lower_rad + margin_rad;
  double upper = limits.upper_rad - margin_rad;
  if (lower > upper) {
    lower = upper = 0.5 * (limits.lower_rad + limits.upper_rad);
  }
  const double clamped = std::clamp(target_rad, lower, upper);
  return {clamped, clamped == target_rad ? std::uint8_t{0} : std::uint8_t{kLimitAngle}};
}

LimitedValue limit_torque(double torque_nm, double speed_rad_s, const JointLimits& limits) {
  LimitedValue result{torque_nm, 0};
  if (std::abs(result.value) > limits.peak_torque_nm) {
    result.value = std::copysign(limits.peak_torque_nm, result.value);
    result.flags |= kLimitTorque;
  }
  const bool pushing = result.value * speed_rad_s > 0.0;
  if (pushing && std::abs(speed_rad_s) >= limits.max_speed_rad_s) {
    result.value = 0.0;
    result.flags |= kLimitSpeed;
    return result;
  }
  if (pushing && result.value * speed_rad_s > limits.max_power_w) {
    result.value = limits.max_power_w / speed_rad_s;
    result.flags |= kLimitPower;
  }
  return result;
}

}  // namespace nova::rt
