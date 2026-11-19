#pragma once

// 脊髓层（第一版）：每 1 毫秒一次，把小脑层给每个关节的目标和软硬换成每个驱动器的命令，
// 中间守住关节空间的硬限制。不用 AI（系统结构第 2 节、AI 模型第 1 节）。

#include <Eigen/Dense>
#include <cstdint>
#include <string>
#include <vector>

#include "nova_rt/coupling.hpp"
#include "nova_rt/limits.hpp"

namespace nova::rt {

// 小脑层给每个关节的（顺序和 SpineConfig 的关节一样）。关节要的力矩是
// 刚度 x (目标 - 角度) + 阻尼 x (目标转速 - 转速) + 前馈力矩。
struct JointCommand {
  Eigen::VectorXd position_rad;
  Eigen::VectorXd velocity_rad_s;
  Eigen::VectorXd stiffness_nm_per_rad;
  Eigen::VectorXd damping_nms_per_rad;
  Eigen::VectorXd torque_nm;
};

// 每 1 毫秒从驱动器读到的（真机上是驱动器上的编码器）：驱动器"转"的量和转速。
struct ActuatorState {
  Eigen::VectorXd position;
  Eigen::VectorXd velocity;
};

// 给每个驱动器的命令：驱动器自己的阻抗环（每秒 1 万~4 万次）照它出力：
// 力 = 刚度 x (目标 - 位置) - 阻尼 x 转速 + 前馈力。目标转速已经折进前馈力里。
struct ActuatorCommand {
  Eigen::VectorXd position;
  Eigen::VectorXd stiffness;
  Eigen::VectorXd damping;
  Eigen::VectorXd force;
};

struct SpineConfig {
  std::vector<std::string> joint_names;
  std::vector<JointLimits> joint_limits;
  std::vector<std::string> actuator_names;
  std::vector<std::vector<Transmission>> transmissions;
  std::vector<double> actuator_peak_forces;
  // 目标离关节的范围的两头至少这么远（不让关节撞到头）。
  double angle_margin_rad = 0.0;
};

struct SpineOutput {
  ActuatorCommand actuators;
  Eigen::VectorXd joint_position_rad;   // 从驱动器的读数算出来的
  Eigen::VectorXd joint_velocity_rad_s;
  Eigen::VectorXd joint_torque_nm;      // 这一步关节会得到的力矩（限过以后，按驱动器的力算回来）
  std::vector<std::uint8_t> limited;    // 每个关节这一步被哪几种限制改过（LimitFlag 的位）
};

class Spine {
 public:
  // 配置对不上（个数、范围、换算求不了逆……）就抛 std::invalid_argument，说清楚是哪里。
  explicit Spine(SpineConfig config);

  // 一步。命令和读数的长度不对、有不是数的、刚度阻尼是负的，抛 std::invalid_argument。
  const SpineOutput& step(const ActuatorState& state, const JointCommand& command);

  const SpineConfig& config() const { return config_; }
  const Coupling& coupling() const { return coupling_; }
  int joint_count() const { return coupling_.joint_count(); }
  int actuator_count() const { return coupling_.actuator_count(); }

 private:
  void check(const ActuatorState& state, const JointCommand& command) const;
  void limit_joints(const JointCommand& command);
  void map_group(const Coupling::Group& group, const ActuatorState& state, const JointCommand& command);
  void limit_actuators(const ActuatorState& state);

  SpineConfig config_;
  Coupling coupling_;
  SpineOutput output_;
  // 每一步都要用的，先分配好（一步里不再分配内存）。
  Eigen::VectorXd target_rad_;
  Eigen::VectorXd feedforward_nm_;
  Eigen::VectorXd actuator_force_;
  Eigen::MatrixXd group_stiffness_;
  Eigen::MatrixXd group_damping_;
};

}  // namespace nova::rt
