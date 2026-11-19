#include "nova_rt/reflexes.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>

namespace nova::rt {
namespace {

[[noreturn]] void fail(const std::string& message) { throw std::invalid_argument(message); }

void check_share(double value, const std::string& what) {
  if (!(value > 0.0 && value <= 1.0)) fail(what + "要在 0（不含）到 1 之间");
}

void check_positive(double value, const std::string& what) {
  if (!(value > 0.0) || !std::isfinite(value)) fail(what + "要是正数");
}

ReflexConfig validated(ReflexConfig config) {
  if (config.joint_count <= 0) fail("关节的个数要大于 0");
  for (std::size_t actuator = 0; actuator < config.actuator_joints.size(); ++actuator) {
    for (const int joint : config.actuator_joints[actuator]) {
      if (joint < 0 || joint >= config.joint_count) {
        fail("第 " + std::to_string(actuator) + " 个驱动器带着的关节编号 " + std::to_string(joint) + " 不对");
      }
    }
  }
  if (static_cast<int>(config.brake_damping.size()) != config.joint_count) fail("刹车的阻尼要每个关节一个");
  for (const double damping : config.brake_damping) {
    if (!(damping >= 0.0) || !std::isfinite(damping)) fail("刹车的阻尼要是 0 或者正数");
  }
  if (!(config.warn_temperature_c < config.hot_temperature_c)) fail("开始降额的温度要比降到底的低");
  check_share(config.hot_force_share, "热了以后能出的力的比例");
  check_share(config.collision_stiffness_share, "被碰到时的软硬比例");
  check_share(config.fall_stiffness_share, "摔倒时的软硬比例");
  check_positive(config.collision_hold_s, "碰完以后等多久");
  check_positive(config.collision_recovery_s, "碰完以后恢复多久");
  check_positive(config.fall_tilt_rad, "摔倒的歪斜");
  check_positive(config.fall_warning_tilt_rad, "快要摔倒的歪斜");
  check_positive(config.fall_tilt_rate_rad_s, "摔倒的歪斜变化率");
  check_positive(config.tilt_rate_filter_s, "歪斜变化率的滤波时间");
  if (config.fall_warning_tilt_rad > config.fall_tilt_rad) fail("快要摔倒的歪斜要比摔倒的小");
  return config;
}

int severity(StopCategory stop) {
  switch (stop) {
    case StopCategory::kCategory0:
      return 3;
    case StopCategory::kCategory1:
      return 2;
    case StopCategory::kCategory2:
      return 1;
    case StopCategory::kNone:
      break;
  }
  return 0;
}

}  // namespace

Reflexes::Reflexes(ReflexConfig config)
    : config_(validated(std::move(config))), actuator_count_(static_cast<int>(config_.actuator_joints.size())) {
  const auto joints = static_cast<Eigen::Index>(config_.joint_count);
  output_.command = JointCommand{Eigen::VectorXd::Zero(joints), Eigen::VectorXd::Zero(joints),
                                 Eigen::VectorXd::Zero(joints), Eigen::VectorXd::Zero(joints),
                                 Eigen::VectorXd::Zero(joints)};
  output_.actuator_force_scale = Eigen::VectorXd::Ones(static_cast<Eigen::Index>(actuator_count_));
  output_.flags.assign(static_cast<std::size_t>(config_.joint_count), 0);
  since_contact_s_ = Eigen::VectorXd::Constant(joints, std::numeric_limits<double>::infinity());
  held_position_rad_ = Eigen::VectorXd::Zero(joints);
}

void Reflexes::reset() {
  latched_stop_ = StopCategory::kNone;
  falling_ = false;
  has_tilt_ = false;
  last_tilt_rad_ = 0.0;
  output_.tilt_rate_rad_s = 0.0;
  output_.mode = ReflexMode::kNormal;
  since_contact_s_.setConstant(std::numeric_limits<double>::infinity());
}

const ReflexOutput& Reflexes::step(const JointCommand& command, const Eigen::VectorXd& joint_position,
                                   const ReflexInput& input, double dt) {
  check(command, joint_position, input, dt);
  output_.command.position_rad = command.position_rad;
  output_.command.velocity_rad_s = command.velocity_rad_s;
  output_.command.stiffness_nm_per_rad = command.stiffness_nm_per_rad;
  output_.command.damping_nms_per_rad = command.damping_nms_per_rad;
  output_.command.torque_nm = command.torque_nm;
  output_.flags.assign(output_.flags.size(), 0);
  const bool was_falling = falling_;
  const int before = severity(latched_stop_);
  update_fall(input.tilt_rad, dt);
  if (severity(input.stop) > before) latched_stop_ = input.stop;
  if ((falling_ && !was_falling) || severity(latched_stop_) > before) latch(joint_position);
  protect(input);
  soften_collisions(input, dt);
  apply_mode(joint_position);
  return output_;
}

void Reflexes::check(const JointCommand& command, const Eigen::VectorXd& joint_position, const ReflexInput& input,
                     double dt) const {
  const auto joints = static_cast<Eigen::Index>(config_.joint_count);
  if (command.position_rad.size() != joints || command.velocity_rad_s.size() != joints ||
      command.stiffness_nm_per_rad.size() != joints || command.damping_nms_per_rad.size() != joints ||
      command.torque_nm.size() != joints || joint_position.size() != joints) {
    fail("关节的命令、角度要每个关节一个");
  }
  if (input.actuator_temperature_c.size() != static_cast<Eigen::Index>(actuator_count_)) {
    fail("驱动器的温度要每个驱动器一个（不知道的给 NaN）");
  }
  if (static_cast<int>(input.joint_contact.size()) != config_.joint_count) fail("被碰到没有要每个关节一个");
  if (!std::isfinite(input.tilt_rad) || input.tilt_rad < 0.0) fail("歪斜要是 0 或者正数");
  if (!(dt > 0.0) || !std::isfinite(dt)) fail("时间要是正数");
}

void Reflexes::update_fall(double tilt_rad, double dt) {
  if (has_tilt_) {
    const double raw = (tilt_rad - last_tilt_rad_) / dt;
    const double alpha = dt / (config_.tilt_rate_filter_s + dt);
    output_.tilt_rate_rad_s += alpha * (raw - output_.tilt_rate_rad_s);
  }
  has_tilt_ = true;
  last_tilt_rad_ = tilt_rad;
  if (!falling_) {
    falling_ = tilt_rad > config_.fall_tilt_rad ||
               (tilt_rad > config_.fall_warning_tilt_rad && output_.tilt_rate_rad_s > config_.fall_tilt_rate_rad_s);
  }
}

void Reflexes::latch(const Eigen::VectorXd& joint_position) { held_position_rad_ = joint_position; }

void Reflexes::protect(const ReflexInput& input) {
  const double span = config_.hot_temperature_c - config_.warn_temperature_c;
  for (int actuator = 0; actuator < actuator_count_; ++actuator) {
    const double temperature = input.actuator_temperature_c(actuator);
    double scale = 1.0;
    if (!std::isnan(temperature) && temperature > config_.warn_temperature_c) {
      const double heat = std::min(1.0, (temperature - config_.warn_temperature_c) / span);
      scale = 1.0 - (1.0 - config_.hot_force_share) * heat;
    }
    output_.actuator_force_scale(actuator) = scale;
    if (scale < 1.0) {
      for (const int joint : config_.actuator_joints[static_cast<std::size_t>(actuator)]) {
        output_.flags[static_cast<std::size_t>(joint)] |= kReflexProtect;
      }
    }
  }
}

void Reflexes::soften_collisions(const ReflexInput& input, double dt) {
  for (Eigen::Index joint = 0; joint < static_cast<Eigen::Index>(config_.joint_count); ++joint) {
    double& since = since_contact_s_(joint);
    since = input.joint_contact[static_cast<std::size_t>(joint)] ? 0.0 : since + dt;
    double factor = 1.0;
    if (since <= config_.collision_hold_s) {
      factor = config_.collision_stiffness_share;
    } else if (since < config_.collision_hold_s + config_.collision_recovery_s) {
      const double recovered = (since - config_.collision_hold_s) / config_.collision_recovery_s;
      factor = config_.collision_stiffness_share + (1.0 - config_.collision_stiffness_share) * recovered;
    }
    if (factor < 1.0) {
      output_.command.stiffness_nm_per_rad(joint) *= factor;
      output_.command.torque_nm(joint) *= factor;
      output_.flags[static_cast<std::size_t>(joint)] |= kReflexCollision;
    }
  }
}

void Reflexes::apply_mode(const Eigen::VectorXd& joint_position) {
  auto& command = output_.command;
  if (latched_stop_ == StopCategory::kCategory0) {
    // 马上断力：不出力、不顶着，只剩驱动器短路制动的阻尼。
    command.position_rad = joint_position;
    command.velocity_rad_s.setZero();
    command.stiffness_nm_per_rad.setZero();
    command.torque_nm.setZero();
    for (Eigen::Index joint = 0; joint < command.damping_nms_per_rad.size(); ++joint) {
      command.damping_nms_per_rad(joint) = config_.brake_damping[static_cast<std::size_t>(joint)];
    }
    for (auto& flag : output_.flags) flag |= kReflexStop;
    output_.mode = ReflexMode::kPowerOff;
    return;
  }
  output_.mode = latched_stop_ == StopCategory::kNone ? ReflexMode::kNormal : ReflexMode::kStopping;
  if (latched_stop_ != StopCategory::kNone) {
    for (auto& flag : output_.flags) flag |= kReflexStop;
  }
  if (falling_) {
    // 救不回来了：全身变软，顶住开始倒的那一刻的姿势（不再听小脑层的目标）。
    command.position_rad = held_position_rad_;
    command.velocity_rad_s.setZero();
    command.stiffness_nm_per_rad *= config_.fall_stiffness_share;
    command.torque_nm *= config_.fall_stiffness_share;
    for (auto& flag : output_.flags) flag |= kReflexFall;
    output_.mode = ReflexMode::kFalling;
  }
}

}  // namespace nova::rt
