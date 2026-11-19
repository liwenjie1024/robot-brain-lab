#include "nova_rt/spine.hpp"

#include <algorithm>
#include <cmath>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>

namespace nova::rt {
namespace {

[[noreturn]] void fail(const std::string& message) { throw std::invalid_argument(message); }

void check_length(Eigen::Index actual, int expected, const std::string& what) {
  if (actual != expected) {
    fail(what + "的长度是 " + std::to_string(actual) + "，应该是 " + std::to_string(expected));
  }
}

void check_finite(const Eigen::VectorXd& values, const std::string& what) {
  if (!values.allFinite()) fail(what + "里有不是数的值（NaN 或无穷大）");
}

void check_unique(const std::vector<std::string>& names, const std::string& what) {
  std::set<std::string> seen;
  for (const auto& name : names) {
    if (!seen.insert(name).second) fail(what + "重名：" + name);
  }
}

SpineConfig validated(SpineConfig config) {
  if (config.joint_limits.size() != config.joint_names.size()) {
    fail("关节有 " + std::to_string(config.joint_names.size()) + " 个，上限却给了 " +
         std::to_string(config.joint_limits.size()) + " 个");
  }
  if (config.transmissions.size() != config.actuator_names.size() ||
      config.actuator_peak_forces.size() != config.actuator_names.size()) {
    fail("驱动器的名字、带着的关节、力的上限，个数要一样");
  }
  check_unique(config.joint_names, "关节");
  check_unique(config.actuator_names, "驱动器");
  for (std::size_t joint = 0; joint < config.joint_limits.size(); ++joint) {
    const auto& limits = config.joint_limits[joint];
    const auto& name = config.joint_names[joint];
    if (!(limits.lower_rad <= limits.upper_rad)) fail("关节 " + name + " 的范围反了或者不是数");
    if (!(limits.peak_torque_nm > 0.0)) fail("关节 " + name + " 的峰值力矩要大于 0");
    if (!(limits.max_speed_rad_s > 0.0)) fail("关节 " + name + " 的转速上限要大于 0");
    if (!(limits.max_power_w > 0.0)) fail("关节 " + name + " 的功率上限要大于 0");
  }
  for (std::size_t actuator = 0; actuator < config.actuator_peak_forces.size(); ++actuator) {
    if (!(config.actuator_peak_forces[actuator] > 0.0)) {
      fail("驱动器 " + config.actuator_names[actuator] + " 的力的上限要大于 0");
    }
  }
  if (!(config.angle_margin_rad >= 0.0) || !std::isfinite(config.angle_margin_rad)) {
    fail("离关节范围两头的余量要是 0 或者正数");
  }
  return config;
}

std::size_t largest_group(const Coupling& coupling) {
  std::size_t largest = 0;
  for (const auto& group : coupling.groups()) largest = std::max(largest, group.joints.size());
  return largest;
}

}  // namespace

Spine::Spine(SpineConfig config)
    : config_(validated(std::move(config))),
      coupling_(static_cast<int>(config_.joint_names.size()), config_.transmissions) {
  const auto joints = static_cast<Eigen::Index>(joint_count());
  const auto actuators = static_cast<Eigen::Index>(actuator_count());
  output_.actuators.position = Eigen::VectorXd::Zero(actuators);
  output_.actuators.stiffness = Eigen::VectorXd::Zero(actuators);
  output_.actuators.damping = Eigen::VectorXd::Zero(actuators);
  output_.actuators.force = Eigen::VectorXd::Zero(actuators);
  output_.joint_position_rad = Eigen::VectorXd::Zero(joints);
  output_.joint_velocity_rad_s = Eigen::VectorXd::Zero(joints);
  output_.joint_torque_nm = Eigen::VectorXd::Zero(joints);
  output_.limited.assign(static_cast<std::size_t>(joints), 0);
  target_rad_ = Eigen::VectorXd::Zero(joints);
  feedforward_nm_ = Eigen::VectorXd::Zero(joints);
  actuator_force_ = Eigen::VectorXd::Zero(actuators);
  const auto size = static_cast<Eigen::Index>(largest_group(coupling_));
  group_stiffness_ = Eigen::MatrixXd::Zero(size, size);
  group_damping_ = Eigen::MatrixXd::Zero(size, size);
}

const SpineOutput& Spine::step(const ActuatorState& state, const JointCommand& command) {
  check(state, command);
  coupling_.joints_from_actuators(state.position, output_.joint_position_rad);
  coupling_.joints_from_actuators(state.velocity, output_.joint_velocity_rad_s);
  limit_joints(command);
  for (const auto& group : coupling_.groups()) map_group(group, state, command);
  limit_actuators(state);
  return output_;
}

void Spine::check(const ActuatorState& state, const JointCommand& command) const {
  check_length(state.position.size(), actuator_count(), "驱动器的位置");
  check_length(state.velocity.size(), actuator_count(), "驱动器的转速");
  check_length(command.position_rad.size(), joint_count(), "关节的目标");
  check_length(command.velocity_rad_s.size(), joint_count(), "关节的目标转速");
  check_length(command.stiffness_nm_per_rad.size(), joint_count(), "关节的刚度");
  check_length(command.damping_nms_per_rad.size(), joint_count(), "关节的阻尼");
  check_length(command.torque_nm.size(), joint_count(), "关节的前馈力矩");
  check_finite(state.position, "驱动器的位置");
  check_finite(state.velocity, "驱动器的转速");
  check_finite(command.position_rad, "关节的目标");
  check_finite(command.velocity_rad_s, "关节的目标转速");
  check_finite(command.stiffness_nm_per_rad, "关节的刚度");
  check_finite(command.damping_nms_per_rad, "关节的阻尼");
  check_finite(command.torque_nm, "关节的前馈力矩");
  if ((command.stiffness_nm_per_rad.array() < 0.0).any()) fail("关节的刚度不能是负的");
  if ((command.damping_nms_per_rad.array() < 0.0).any()) fail("关节的阻尼不能是负的");
}

void Spine::limit_joints(const JointCommand& command) {
  for (Eigen::Index joint = 0; joint < joint_count(); ++joint) {
    const auto& limits = config_.joint_limits[static_cast<std::size_t>(joint)];
    const auto target = limit_target(command.position_rad(joint), limits, config_.angle_margin_rad);
    target_rad_(joint) = target.value;
    const double speed = output_.joint_velocity_rad_s(joint);
    const double desired = command.stiffness_nm_per_rad(joint) * (target.value - output_.joint_position_rad(joint)) +
                           command.damping_nms_per_rad(joint) * (command.velocity_rad_s(joint) - speed) +
                           command.torque_nm(joint);
    const auto torque = limit_torque(desired, speed, limits);
    // 限过的部分从前馈力矩里扣：刚度、阻尼、目标照小脑层给的（驱动器的阻抗环照旧），只是这一步不推那么多。
    feedforward_nm_(joint) = command.torque_nm(joint) + (torque.value - desired);
    output_.limited[static_cast<std::size_t>(joint)] = static_cast<std::uint8_t>(target.flags | torque.flags);
  }
}

void Spine::map_group(const Coupling::Group& group, const ActuatorState& state, const JointCommand& command) {
  const auto size = static_cast<Eigen::Index>(group.joints.size());
  const auto joint = [&](Eigen::Index column) { return static_cast<Eigen::Index>(group.joints[static_cast<std::size_t>(column)]); };
  const auto actuator = [&](Eigen::Index row) {
    return static_cast<Eigen::Index>(group.actuators[static_cast<std::size_t>(row)]);
  };
  // 关节的刚度、阻尼（对角的）换到驱动器那边：K_a = C⁻ᵀ K C⁻¹。并联的一对两个关节软硬不一样时它不是对角的，
  // 驱动器自己的阻抗环只管对角那一项，别的由脊髓层每 1 毫秒按读数算成前馈力。
  for (Eigen::Index row = 0; row < size; ++row) {
    for (Eigen::Index other = 0; other < size; ++other) {
      double stiffness = 0.0;
      double damping = 0.0;
      for (Eigen::Index column = 0; column < size; ++column) {
        const double product = group.inverse(column, row) * group.inverse(column, other);
        stiffness += product * command.stiffness_nm_per_rad(joint(column));
        damping += product * command.damping_nms_per_rad(joint(column));
      }
      group_stiffness_(row, other) = stiffness;
      group_damping_(row, other) = damping;
    }
  }
  for (Eigen::Index row = 0; row < size; ++row) {
    double target = 0.0;
    double target_speed = 0.0;
    double force = 0.0;
    for (Eigen::Index column = 0; column < size; ++column) {
      target += group.forward(row, column) * target_rad_(joint(column));
      target_speed += group.forward(row, column) * command.velocity_rad_s(joint(column));
      force += group.inverse(column, row) * feedforward_nm_(joint(column));
    }
    output_.actuators.position(actuator(row)) = target;
    output_.actuators.stiffness(actuator(row)) = group_stiffness_(row, row);
    output_.actuators.damping(actuator(row)) = group_damping_(row, row);
    // 目标转速折进前馈力：驱动器的阻尼只对着 0 转速。
    output_.actuators.force(actuator(row)) = force + group_damping_(row, row) * target_speed;
  }
  for (Eigen::Index row = 0; row < size; ++row) {
    double coupled = 0.0;
    for (Eigen::Index other = 0; other < size; ++other) {
      if (other == row) continue;
      double other_target_speed = 0.0;
      for (Eigen::Index column = 0; column < size; ++column) {
        other_target_speed += group.forward(other, column) * command.velocity_rad_s(joint(column));
      }
      coupled += group_stiffness_(row, other) * (output_.actuators.position(actuator(other)) - state.position(actuator(other))) +
                 group_damping_(row, other) * (other_target_speed - state.velocity(actuator(other)));
    }
    output_.actuators.force(actuator(row)) += coupled;
  }
}

void Spine::limit_actuators(const ActuatorState& state) {
  auto& command = output_.actuators;
  for (Eigen::Index actuator = 0; actuator < actuator_count(); ++actuator) {
    double force = command.stiffness(actuator) * (command.position(actuator) - state.position(actuator)) -
                   command.damping(actuator) * state.velocity(actuator) + command.force(actuator);
    const double peak = config_.actuator_peak_forces[static_cast<std::size_t>(actuator)];
    if (std::abs(force) > peak) {
      const double limited = std::copysign(peak, force);
      command.force(actuator) -= force - limited;
      force = limited;
      for (const auto& transmission : config_.transmissions[static_cast<std::size_t>(actuator)]) {
        output_.limited[static_cast<std::size_t>(transmission.joint)] |= kLimitActuatorForce;
      }
    }
    actuator_force_(actuator) = force;
  }
  coupling_.joint_torques_from_forces(actuator_force_, output_.joint_torque_nm);
}

}  // namespace nova::rt
