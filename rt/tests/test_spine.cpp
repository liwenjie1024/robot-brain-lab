// 脊髓层一步的测试：驱动器照命令出的力换回关节，正好是小脑层要的力矩；超了限制改小并且标出来；
// 同样的输入同样的输出；不对的输入拒绝；一步算多久。

#include <gtest/gtest.h>

#include <chrono>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>

#include "nova_rt/spine.hpp"

namespace nova::rt {
namespace {

constexpr double kInfinity = std::numeric_limits<double>::infinity();

JointLimits loose() {
  JointLimits limits;
  limits.lower_rad = -2.0;
  limits.upper_rad = 2.0;
  limits.peak_torque_nm = 1000.0;
  return limits;
}

// 关节 0 自己一个驱动器；关节 1、2 是并联的一对（驱动器 1 是和、2 是差）。
SpineConfig mixed_config() {
  SpineConfig config;
  config.joint_names = {"hip", "ankle_pitch", "ankle_roll"};
  config.joint_limits = {loose(), loose(), loose()};
  config.actuator_names = {"hip", "ankle_a", "ankle_b"};
  config.transmissions = {{{0, 1.0}}, {{1, 1.0}, {2, 1.0}}, {{1, 1.0}, {2, -1.0}}};
  config.actuator_peak_forces = {1000.0, 1000.0, 1000.0};
  return config;
}

JointCommand command_of(const Eigen::Vector3d& position, const Eigen::Vector3d& stiffness) {
  JointCommand command;
  command.position_rad = position;
  command.velocity_rad_s = Eigen::Vector3d(0.1, -0.2, 0.3);
  command.stiffness_nm_per_rad = stiffness;
  command.damping_nms_per_rad = Eigen::Vector3d(2.0, 3.0, 0.5);
  command.torque_nm = Eigen::Vector3d(1.0, -2.0, 4.0);
  return command;
}

ActuatorState state_of(const Spine& spine, const Eigen::Vector3d& joints, const Eigen::Vector3d& speeds) {
  ActuatorState state;
  state.position = Eigen::VectorXd(3);
  state.velocity = Eigen::VectorXd(3);
  spine.coupling().actuators_from_joints(joints, state.position);
  spine.coupling().actuators_from_joints(speeds, state.velocity);
  return state;
}

// 驱动器照命令出的力（驱动器自己的阻抗环），换回关节的力矩。
Eigen::VectorXd joint_torques_of(const Spine& spine, const SpineOutput& output, const ActuatorState& state) {
  const auto& command = output.actuators;
  const Eigen::VectorXd forces = command.stiffness.cwiseProduct(command.position - state.position) -
                                 command.damping.cwiseProduct(state.velocity) + command.force;
  Eigen::VectorXd torques(spine.joint_count());
  spine.coupling().joint_torques_from_forces(forces, torques);
  return torques;
}

Eigen::VectorXd wanted_torques(const JointCommand& command, const Eigen::Vector3d& joints,
                               const Eigen::Vector3d& speeds) {
  return command.stiffness_nm_per_rad.cwiseProduct(command.position_rad - joints) +
         command.damping_nms_per_rad.cwiseProduct(command.velocity_rad_s - speeds) + command.torque_nm;
}

// 说明：关节的角度、转速从驱动器的读数算出来。
TEST(Spine, JointStateComesFromTheActuators) {
  Spine spine(mixed_config());
  const Eigen::Vector3d joints(0.4, -0.3, 0.2);
  const Eigen::Vector3d speeds(1.0, 0.5, -0.5);
  const auto& output = spine.step(state_of(spine, joints, speeds), command_of(joints, Eigen::Vector3d::Ones()));
  EXPECT_TRUE(output.joint_position_rad.isApprox(joints, 1e-14));
  EXPECT_TRUE(output.joint_velocity_rad_s.isApprox(speeds, 1e-14));
}

// 说明：驱动器照命令出力，换回关节正好是小脑层要的：并联的一对两个关节软硬不一样也一样（不对角的那部分在前馈里）。
TEST(Spine, ActuatorCommandsReproduceTheWantedJointTorques) {
  Spine spine(mixed_config());
  const Eigen::Vector3d joints(0.4, -0.3, 0.2);
  const Eigen::Vector3d speeds(1.0, 0.5, -0.5);
  const auto command = command_of(Eigen::Vector3d(0.5, -0.1, 0.0), Eigen::Vector3d(50.0, 300.0, 40.0));
  const auto state = state_of(spine, joints, speeds);
  const auto& output = spine.step(state, command);
  const Eigen::VectorXd wanted = wanted_torques(command, joints, speeds);
  EXPECT_TRUE(joint_torques_of(spine, output, state).isApprox(wanted, 1e-12));
  EXPECT_TRUE(output.joint_torque_nm.isApprox(wanted, 1e-12));
  for (const auto flags : output.limited) EXPECT_EQ(flags, 0);
}

// 说明：一个驱动器带一个关节时，命令原样给驱动器（目标转速折进前馈力）。
TEST(Spine, SingleJointActuatorsPassTheCommandThrough) {
  Spine spine(mixed_config());
  const Eigen::Vector3d joints = Eigen::Vector3d::Zero();
  const auto command = command_of(Eigen::Vector3d(0.5, 0.0, 0.0), Eigen::Vector3d(50.0, 10.0, 10.0));
  const auto& output = spine.step(state_of(spine, joints, joints), command);
  EXPECT_DOUBLE_EQ(output.actuators.position(0), 0.5);
  EXPECT_DOUBLE_EQ(output.actuators.stiffness(0), 50.0);
  EXPECT_DOUBLE_EQ(output.actuators.damping(0), 2.0);
  EXPECT_DOUBLE_EQ(output.actuators.force(0), 1.0 + 2.0 * 0.1);
}

// 说明：要的力矩超过关节的峰值：关节得到的正好是峰值，标"力矩"；目标、软硬照旧。
TEST(Spine, TorqueAbovePeakIsCutToThePeak) {
  auto config = mixed_config();
  config.joint_limits[0].peak_torque_nm = 20.0;
  Spine spine(config);
  const Eigen::Vector3d joints = Eigen::Vector3d::Zero();
  const auto command = command_of(Eigen::Vector3d(1.0, 0.0, 0.0), Eigen::Vector3d(100.0, 10.0, 10.0));
  const auto state = state_of(spine, joints, joints);
  const auto& output = spine.step(state, command);
  EXPECT_NEAR(joint_torques_of(spine, output, state)(0), 20.0, 1e-12);
  EXPECT_EQ(output.limited[0], kLimitTorque);
  EXPECT_DOUBLE_EQ(output.actuators.position(0), 1.0);
  EXPECT_EQ(output.limited[1], 0);
}

// 说明：目标超出关节的范围：放回范围里（离边留出余量），标"角度"。
TEST(Spine, TargetsOutsideTheRangeAreBroughtBack) {
  auto config = mixed_config();
  config.angle_margin_rad = 0.1;
  Spine spine(config);
  const Eigen::Vector3d joints = Eigen::Vector3d::Zero();
  const auto& output = spine.step(state_of(spine, joints, joints),
                                  command_of(Eigen::Vector3d(3.0, 0.0, 0.0), Eigen::Vector3d::Ones()));
  EXPECT_DOUBLE_EQ(output.actuators.position(0), 1.9);
  EXPECT_EQ(output.limited[0], kLimitAngle);
}

// 说明：并联的一对两个关节同时用力，一个驱动器出到了顶：它正好出峰值，两个关节都标"驱动器出到顶"。
TEST(Spine, ASaturatedPairActuatorFlagsBothJoints) {
  auto config = mixed_config();
  config.actuator_peak_forces = {1000.0, 60.0, 60.0};
  Spine spine(config);
  const Eigen::Vector3d joints = Eigen::Vector3d::Zero();
  JointCommand command = command_of(Eigen::Vector3d::Zero(), Eigen::Vector3d::Zero());
  command.velocity_rad_s.setZero();
  command.torque_nm = Eigen::Vector3d(0.0, 100.0, 40.0);  // 和那个要 (100 + 40) / 2 = 70 > 60
  const auto state = state_of(spine, joints, joints);
  const auto& output = spine.step(state, command);
  const auto& actuators = output.actuators;
  const Eigen::VectorXd forces = actuators.stiffness.cwiseProduct(actuators.position - state.position) -
                                 actuators.damping.cwiseProduct(state.velocity) + actuators.force;
  EXPECT_NEAR(forces(1), 60.0, 1e-12);
  EXPECT_NEAR(forces(2), 30.0, 1e-12);  // 差那个要 (100 - 40) / 2 = 30，没到顶
  EXPECT_EQ(output.limited[1], kLimitActuatorForce);
  EXPECT_EQ(output.limited[2], kLimitActuatorForce);
  EXPECT_EQ(output.limited[0], 0);
  EXPECT_NEAR(output.joint_torque_nm(1), 90.0, 1e-12);  // 关节真的得到的：60 + 30
}

// 说明：保护的反射把一个驱动器能出的力降到 5%（1000 → 50）：要 100 的那一下只出 50，标"驱动器出到顶"；比例不在 0~1 就拒绝。
TEST(Spine, AForceScaleLowersTheActuatorLimit) {
  Spine spine(mixed_config());
  const Eigen::Vector3d joints = Eigen::Vector3d::Zero();
  JointCommand command = command_of(Eigen::Vector3d::Zero(), Eigen::Vector3d::Zero());
  command.velocity_rad_s.setZero();
  command.torque_nm = Eigen::Vector3d(100.0, 0.0, 0.0);
  const auto state = state_of(spine, joints, joints);
  const auto& output = spine.step(state, command, Eigen::Vector3d(0.05, 1.0, 1.0));
  EXPECT_NEAR(output.joint_torque_nm(0), 50.0, 1e-12);
  EXPECT_EQ(output.limited[0], kLimitActuatorForce);
  EXPECT_THROW(spine.step(state, command, Eigen::Vector3d(0.0, 1.0, 1.0)), std::invalid_argument);
  EXPECT_THROW(spine.step(state, command, Eigen::Vector3d(1.5, 1.0, 1.0)), std::invalid_argument);
}

// 说明：同样的输入算两遍，结果一样；中间夹一步别的输入也一样（一步和一步之间不留东西）。
TEST(Spine, TheSameInputGivesTheSameOutput) {
  Spine spine(mixed_config());
  const Eigen::Vector3d joints(0.1, 0.2, 0.3);
  const auto state = state_of(spine, joints, joints);
  const auto command = command_of(Eigen::Vector3d(0.3, 0.1, -0.2), Eigen::Vector3d(30.0, 60.0, 90.0));
  const Eigen::VectorXd first = spine.step(state, command).actuators.force;
  spine.step(state_of(spine, -joints, joints), command_of(Eigen::Vector3d::Zero(), Eigen::Vector3d::Ones()));
  const Eigen::VectorXd again = spine.step(state, command).actuators.force;
  EXPECT_EQ(first, again);
}

// 说明：长度不对、有不是数的、刚度或阻尼是负的，都拒绝。
TEST(Spine, BadInputsAreRefused) {
  Spine spine(mixed_config());
  const Eigen::Vector3d joints = Eigen::Vector3d::Zero();
  const auto state = state_of(spine, joints, joints);
  auto short_command = command_of(joints, Eigen::Vector3d::Ones());
  short_command.torque_nm = Eigen::VectorXd::Zero(2);
  EXPECT_THROW(spine.step(state, short_command), std::invalid_argument);
  auto nan_command = command_of(joints, Eigen::Vector3d::Ones());
  nan_command.position_rad(1) = std::nan("");
  EXPECT_THROW(spine.step(state, nan_command), std::invalid_argument);
  auto negative = command_of(joints, Eigen::Vector3d(1.0, -1.0, 1.0));
  EXPECT_THROW(spine.step(state, negative), std::invalid_argument);
}

// 说明：配置对不上（重名、个数不一样、范围反了、上限不是正的）都拒绝。
TEST(Spine, BadConfigurationsAreRefused) {
  auto repeated = mixed_config();
  repeated.joint_names[2] = "hip";
  EXPECT_THROW(Spine{repeated}, std::invalid_argument);
  auto missing = mixed_config();
  missing.joint_limits.pop_back();
  EXPECT_THROW(Spine{missing}, std::invalid_argument);
  auto reversed = mixed_config();
  reversed.joint_limits[0].lower_rad = 3.0;
  EXPECT_THROW(Spine{reversed}, std::invalid_argument);
  auto zero_force = mixed_config();
  zero_force.actuator_peak_forces[1] = 0.0;
  EXPECT_THROW(Spine{zero_force}, std::invalid_argument);
}

// 说明：像 Nova 那么大（67 个关节：57 个单独的、5 对并联的），一步要算得比 1 毫秒快得多。
TEST(Spine, ANovaSizedStepIsFarFasterThanOneMillisecond) {
  SpineConfig config;
  constexpr int kSingles = 57;
  constexpr int kPairs = 5;
  for (int joint = 0; joint < kSingles + 2 * kPairs; ++joint) {
    config.joint_names.push_back("joint_" + std::to_string(joint));
    config.joint_limits.push_back(loose());
  }
  for (int joint = 0; joint < kSingles; ++joint) {
    config.actuator_names.push_back("single_" + std::to_string(joint));
    config.transmissions.push_back({{joint, 1.0}});
    config.actuator_peak_forces.push_back(kInfinity);
  }
  for (int pair = 0; pair < kPairs; ++pair) {
    const int first = kSingles + 2 * pair;
    config.actuator_names.push_back("pair_a_" + std::to_string(pair));
    config.transmissions.push_back({{first, 1.0}, {first + 1, 1.0}});
    config.actuator_names.push_back("pair_b_" + std::to_string(pair));
    config.transmissions.push_back({{first, 1.0}, {first + 1, -1.0}});
    config.actuator_peak_forces.push_back(100.0);
    config.actuator_peak_forces.push_back(100.0);
  }
  Spine spine(config);
  const auto size = static_cast<Eigen::Index>(spine.joint_count());
  ActuatorState state{Eigen::VectorXd::Constant(size, 0.1), Eigen::VectorXd::Constant(size, 0.2)};
  JointCommand command{Eigen::VectorXd::Constant(size, 0.3), Eigen::VectorXd::Zero(size),
                       Eigen::VectorXd::Constant(size, 50.0), Eigen::VectorXd::Constant(size, 2.0),
                       Eigen::VectorXd::Zero(size)};
  constexpr int kSteps = 20000;
  const auto begin = std::chrono::steady_clock::now();
  double checksum = 0.0;
  for (int step = 0; step < kSteps; ++step) {
    command.torque_nm(0) = 1e-6 * step;
    checksum += spine.step(state, command).actuators.force(0);
  }
  const std::chrono::duration<double, std::micro> elapsed = std::chrono::steady_clock::now() - begin;
  const double per_step_us = elapsed.count() / kSteps;
  std::cout << "  67 个关节的一步：" << per_step_us << " 微秒（核对值 " << checksum << "）\n";
  EXPECT_LT(per_step_us, 50.0);
}

}  // namespace
}  // namespace nova::rt
