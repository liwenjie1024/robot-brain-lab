// 关节空间的硬限制的测试：正常的不动；正好在边上的不动；超了就改小并且标出来。

#include <gtest/gtest.h>

#include "nova_rt/limits.hpp"

namespace nova::rt {
namespace {

JointLimits knee() {
  JointLimits limits;
  limits.lower_rad = 0.0;
  limits.upper_rad = 2.0;
  limits.peak_torque_nm = 100.0;
  limits.max_speed_rad_s = 10.0;
  limits.max_power_w = 500.0;
  return limits;
}

// 说明：范围里的目标照旧；超出的放回范围里（离两头留出余量），标"角度"。
TEST(LimitTarget, KeepsTargetsInsideTheRangeWithMargin) {
  const auto inside = limit_target(1.0, knee(), 0.05);
  EXPECT_DOUBLE_EQ(inside.value, 1.0);
  EXPECT_EQ(inside.flags, 0);
  const auto above = limit_target(2.5, knee(), 0.05);
  EXPECT_DOUBLE_EQ(above.value, 1.95);
  EXPECT_EQ(above.flags, kLimitAngle);
  const auto below = limit_target(-1.0, knee(), 0.05);
  EXPECT_DOUBLE_EQ(below.value, 0.05);
  EXPECT_EQ(below.flags, kLimitAngle);
}

// 说明：正好在余量的边上不算超。
TEST(LimitTarget, ExactlyAtTheMarginIsNotLimited) {
  const auto edge = limit_target(1.95, knee(), 0.05);
  EXPECT_DOUBLE_EQ(edge.value, 1.95);
  EXPECT_EQ(edge.flags, 0);
}

// 说明：范围比两头的余量还窄时，目标放在正中间。
TEST(LimitTarget, ARangeNarrowerThanTheMarginsUsesTheMiddle) {
  JointLimits narrow = knee();
  narrow.upper_rad = 0.06;
  const auto result = limit_target(0.06, narrow, 0.05);
  EXPECT_DOUBLE_EQ(result.value, 0.03);
}

// 说明：峰值以内、慢的时候，力矩照旧。
TEST(LimitTorque, NormalTorqueIsUntouched) {
  const auto result = limit_torque(60.0, 1.0, knee());
  EXPECT_DOUBLE_EQ(result.value, 60.0);
  EXPECT_EQ(result.flags, 0);
}

// 说明：超过峰值就剪到峰值（两个方向都是），标"力矩"；正好是峰值不算超。
TEST(LimitTorque, TorqueAbovePeakIsClampedBothWays) {
  EXPECT_DOUBLE_EQ(limit_torque(150.0, 0.0, knee()).value, 100.0);
  EXPECT_DOUBLE_EQ(limit_torque(-150.0, 0.0, knee()).value, -100.0);
  EXPECT_EQ(limit_torque(-150.0, 0.0, knee()).flags, kLimitTorque);
  EXPECT_EQ(limit_torque(100.0, 0.0, knee()).flags, 0);
}

// 说明：转到最快时不再往这个方向推（力矩变 0），往回刹照旧。
TEST(LimitTorque, AtMaxSpeedItStopsPushingButMayBrake) {
  const auto pushing = limit_torque(40.0, 10.0, knee());
  EXPECT_DOUBLE_EQ(pushing.value, 0.0);
  EXPECT_EQ(pushing.flags, kLimitSpeed);
  const auto braking = limit_torque(-40.0, 10.0, knee());
  EXPECT_DOUBLE_EQ(braking.value, -40.0);
  EXPECT_EQ(braking.flags, 0);
}

// 说明：往转的方向推的功率超过上限（80 N·m x 8 rad/s = 640 W > 500 W），力矩改成 500 / 8；往回刹不限功率。
TEST(LimitTorque, PushingPowerIsCappedButBrakingIsNot) {
  const auto pushing = limit_torque(80.0, 8.0, knee());
  EXPECT_DOUBLE_EQ(pushing.value, 62.5);
  EXPECT_EQ(pushing.flags, kLimitPower);
  const auto braking = limit_torque(-80.0, 8.0, knee());
  EXPECT_DOUBLE_EQ(braking.value, -80.0);
  EXPECT_EQ(braking.flags, 0);
}

// 说明：几种一起超：先剪到峰值，再按功率改小，两种都标出来。
TEST(LimitTorque, SeveralLimitsAreAllReported) {
  const auto result = limit_torque(300.0, 9.0, knee());
  EXPECT_NEAR(result.value, 500.0 / 9.0, 1e-12);
  EXPECT_EQ(result.flags, kLimitTorque | kLimitPower);
}

// 说明：不知道的上限（无穷大）不限。
TEST(LimitTorque, UnknownLimitsDoNotLimit) {
  const JointLimits unknown;
  const auto result = limit_torque(1e6, 1e3, unknown);
  EXPECT_DOUBLE_EQ(result.value, 1e6);
  EXPECT_EQ(result.flags, 0);
}

}  // namespace
}  // namespace nova::rt
