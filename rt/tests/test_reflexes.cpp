// 脊髓层的反射的测试：保护（热了降力）、碰撞（变软、等一会儿、慢慢恢复）、跌倒（救不回来就变软、顶住）、
// 停止（0 类断力只留刹车，2 类标出来交给小脑层），一直留着直到重新开始；不对的输入、配置拒绝。

#include <gtest/gtest.h>

#include <cmath>
#include <limits>
#include <stdexcept>
#include <vector>

#include "nova_rt/reflexes.hpp"

namespace nova::rt {
namespace {

constexpr double kStep = 0.001;

// 三个关节：驱动器 0 带关节 0；驱动器 1、2 是并联的一对，带关节 1、2。
ReflexConfig config() {
  ReflexConfig config;
  config.joint_count = 3;
  config.actuator_joints = {{0}, {1, 2}, {1, 2}};
  config.brake_damping = {4.0, 5.0, 6.0};
  return config;
}

JointCommand command() {
  return JointCommand{Eigen::Vector3d(0.1, 0.2, 0.3), Eigen::Vector3d(0.5, 0.0, -0.5), Eigen::Vector3d(100.0, 200.0, 300.0),
                      Eigen::Vector3d(2.0, 3.0, 4.0), Eigen::Vector3d(10.0, -20.0, 30.0)};
}

ReflexInput quiet() {
  ReflexInput input;
  input.tilt_rad = 0.0;
  input.actuator_temperature_c = Eigen::Vector3d(40.0, 40.0, 40.0);
  input.joint_contact = {false, false, false};
  return input;
}

const Eigen::Vector3d kPosition(0.05, 0.15, 0.25);

// 说明：什么都没发生：命令原样过去，没有标记，力的比例都是 1。
TEST(Reflexes, NothingHappeningPassesTheCommandThrough) {
  Reflexes reflexes(config());
  const auto& output = reflexes.step(command(), kPosition, quiet(), kStep);
  EXPECT_EQ(output.command.stiffness_nm_per_rad, command().stiffness_nm_per_rad);
  EXPECT_EQ(output.command.position_rad, command().position_rad);
  EXPECT_TRUE(output.actuator_force_scale.isOnes());
  for (const auto flag : output.flags) EXPECT_EQ(flag, 0);
  EXPECT_EQ(output.mode, ReflexMode::kNormal);
}

// 说明：绕组 80 °C 不降；100 °C 降到 75%；120 °C 降到 50%（不再往下）；不知道的温度不降；标在它带着的关节上。
TEST(Reflexes, HotDrivesAreDeratedAheadOfTime) {
  Reflexes reflexes(config());
  auto input = quiet();
  input.actuator_temperature_c = Eigen::Vector3d(80.0, 100.0, std::numeric_limits<double>::quiet_NaN());
  auto output = reflexes.step(command(), kPosition, input, kStep);
  EXPECT_DOUBLE_EQ(output.actuator_force_scale(0), 1.0);
  EXPECT_DOUBLE_EQ(output.actuator_force_scale(1), 0.75);
  EXPECT_DOUBLE_EQ(output.actuator_force_scale(2), 1.0);
  EXPECT_EQ(output.flags[0], 0);
  EXPECT_EQ(output.flags[1], kReflexProtect);
  EXPECT_EQ(output.flags[2], kReflexProtect);
  input.actuator_temperature_c = Eigen::Vector3d(120.0, 40.0, 40.0);
  output = reflexes.step(command(), kPosition, input, kStep);
  EXPECT_DOUBLE_EQ(output.actuator_force_scale(0), 0.5);
  EXPECT_EQ(output.flags[0], kReflexProtect);
}

// 说明：被碰到：刚度、前馈变成 20%，阻尼照旧；碰完先等 0.5 秒，再用 0.5 秒慢慢恢复（一半的时候是 60%），然后就不标了。
TEST(Reflexes, ACollisionSoftensThenRecoversSlowly) {
  Reflexes reflexes(config());
  auto touched = quiet();
  touched.joint_contact = {false, true, false};
  auto output = reflexes.step(command(), kPosition, touched, kStep);
  EXPECT_DOUBLE_EQ(output.command.stiffness_nm_per_rad(1), 40.0);
  EXPECT_DOUBLE_EQ(output.command.torque_nm(1), -4.0);
  EXPECT_DOUBLE_EQ(output.command.damping_nms_per_rad(1), 3.0);
  EXPECT_DOUBLE_EQ(output.command.stiffness_nm_per_rad(0), 100.0);
  EXPECT_EQ(output.flags[1], kReflexCollision);
  for (int step = 0; step < 500; ++step) output = reflexes.step(command(), kPosition, quiet(), kStep);
  EXPECT_NEAR(output.command.stiffness_nm_per_rad(1), 40.0, 1e-9);
  for (int step = 0; step < 250; ++step) output = reflexes.step(command(), kPosition, quiet(), kStep);
  EXPECT_NEAR(output.command.stiffness_nm_per_rad(1), 200.0 * 0.6, 1.0);
  for (int step = 0; step < 300; ++step) output = reflexes.step(command(), kPosition, quiet(), kStep);
  EXPECT_DOUBLE_EQ(output.command.stiffness_nm_per_rad(1), 200.0);
  EXPECT_EQ(output.flags[1], 0);
}

// 说明：恢复到一半又被碰到：马上又变软，重新等。
TEST(Reflexes, ATouchDuringRecoveryStartsOver) {
  Reflexes reflexes(config());
  auto touched = quiet();
  touched.joint_contact = {true, false, false};
  reflexes.step(command(), kPosition, touched, kStep);
  for (int step = 0; step < 700; ++step) reflexes.step(command(), kPosition, quiet(), kStep);
  const auto& output = reflexes.step(command(), kPosition, touched, kStep);
  EXPECT_DOUBLE_EQ(output.command.stiffness_nm_per_rad(0), 20.0);
}

// 说明：歪过 40°：救不回来了。全身变软（30%），顶住开始倒的那一刻的姿势；之后站直了也一直是"在摔倒"，直到重新开始。
TEST(Reflexes, ABigTiltMeansFallingUntilReset) {
  Reflexes reflexes(config());
  auto tilted = quiet();
  tilted.tilt_rad = 0.75;
  auto output = reflexes.step(command(), kPosition, tilted, kStep);
  EXPECT_EQ(output.mode, ReflexMode::kFalling);
  EXPECT_EQ(output.command.position_rad, kPosition);
  EXPECT_DOUBLE_EQ(output.command.stiffness_nm_per_rad(2), 90.0);
  EXPECT_EQ(output.flags[0] & kReflexFall, kReflexFall);
  output = reflexes.step(command(), Eigen::Vector3d::Zero(), quiet(), kStep);
  EXPECT_EQ(output.mode, ReflexMode::kFalling);
  EXPECT_EQ(output.command.position_rad, kPosition);
  reflexes.reset();
  output = reflexes.step(command(), kPosition, quiet(), kStep);
  EXPECT_EQ(output.mode, ReflexMode::kNormal);
}

// 说明：歪过 25° 又在快速地往下倒（每秒 2 弧度）也算摔倒；慢慢歪到 34°（每秒 0.5 弧度）不算。
TEST(Reflexes, FastTippingPastTheWarningIsAFall) {
  Reflexes fast(config());
  Reflexes slow(config());
  auto input = quiet();
  ReflexMode fast_mode = ReflexMode::kNormal;
  for (int step = 0; step <= 250; ++step) {
    input.tilt_rad = 0.002 * step;  // 每秒 2 弧度，到 0.5
    fast_mode = fast.step(command(), kPosition, input, kStep).mode;
  }
  EXPECT_EQ(fast_mode, ReflexMode::kFalling);
  ReflexMode slow_mode = ReflexMode::kNormal;
  for (int step = 0; step <= 1200; ++step) {
    input.tilt_rad = 0.0005 * step;  // 每秒 0.5 弧度，到 0.6
    slow_mode = slow.step(command(), kPosition, input, kStep).mode;
  }
  EXPECT_EQ(slow_mode, ReflexMode::kNormal);
}

// 说明：0 类停止：不出力、不顶着，只剩刹车的阻尼；之后不再要停也一直断着，盖过摔倒；直到重新开始。
TEST(Reflexes, CategoryZeroCutsPowerAndStays) {
  Reflexes reflexes(config());
  auto stop = quiet();
  stop.stop = StopCategory::kCategory0;
  stop.tilt_rad = 0.9;
  auto output = reflexes.step(command(), kPosition, stop, kStep);
  EXPECT_EQ(output.mode, ReflexMode::kPowerOff);
  EXPECT_TRUE(output.command.stiffness_nm_per_rad.isZero());
  EXPECT_TRUE(output.command.torque_nm.isZero());
  EXPECT_EQ(output.command.damping_nms_per_rad, Eigen::Vector3d(4.0, 5.0, 6.0));
  EXPECT_EQ(output.flags[2] & kReflexStop, kReflexStop);
  output = reflexes.step(command(), kPosition, quiet(), kStep);
  EXPECT_EQ(output.mode, ReflexMode::kPowerOff);
  reflexes.reset();
  EXPECT_EQ(reflexes.step(command(), kPosition, quiet(), kStep).mode, ReflexMode::kNormal);
}

// 说明：2 类停止：命令照旧（由小脑层停下来站住），标出"在停止"；后来要 0 类就升成断力；再要 2 类不会降回去。
TEST(Reflexes, CategoryTwoIsReportedAndOnlyEscalates) {
  Reflexes reflexes(config());
  auto stop = quiet();
  stop.stop = StopCategory::kCategory2;
  auto output = reflexes.step(command(), kPosition, stop, kStep);
  EXPECT_EQ(output.mode, ReflexMode::kStopping);
  EXPECT_EQ(output.command.stiffness_nm_per_rad, command().stiffness_nm_per_rad);
  EXPECT_EQ(output.flags[0], kReflexStop);
  stop.stop = StopCategory::kCategory0;
  EXPECT_EQ(reflexes.step(command(), kPosition, stop, kStep).mode, ReflexMode::kPowerOff);
  stop.stop = StopCategory::kCategory2;
  EXPECT_EQ(reflexes.step(command(), kPosition, stop, kStep).mode, ReflexMode::kPowerOff);
}

// 说明：不对的输入（长度、负的歪斜、时间不是正数）和配置（比例不在 0~1、温度反了、刹车的阻尼个数不对）都拒绝。
TEST(Reflexes, BadInputsAndConfigurationsAreRefused) {
  Reflexes reflexes(config());
  auto short_contacts = quiet();
  short_contacts.joint_contact = {false};
  EXPECT_THROW(reflexes.step(command(), kPosition, short_contacts, kStep), std::invalid_argument);
  auto negative_tilt = quiet();
  negative_tilt.tilt_rad = -0.1;
  EXPECT_THROW(reflexes.step(command(), kPosition, negative_tilt, kStep), std::invalid_argument);
  EXPECT_THROW(reflexes.step(command(), kPosition, quiet(), 0.0), std::invalid_argument);
  auto share = config();
  share.collision_stiffness_share = 1.5;
  EXPECT_THROW(Reflexes{share}, std::invalid_argument);
  auto temperatures = config();
  temperatures.warn_temperature_c = 120.0;
  EXPECT_THROW(Reflexes{temperatures}, std::invalid_argument);
  auto brakes = config();
  brakes.brake_damping.pop_back();
  EXPECT_THROW(Reflexes{brakes}, std::invalid_argument);
}

}  // namespace
}  // namespace nova::rt
