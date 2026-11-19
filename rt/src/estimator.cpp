#include "nova_rt/estimator.hpp"

#include <cmath>
#include <stdexcept>
#include <string>
#include <utility>

#include "nova_rt/lie.hpp"

namespace nova::rt {
namespace {

constexpr int kMaxContacts = 8;
// 没着地的点：和别的都不相关，方差随便放一个正数（着地的那一刻会重新定）。
constexpr double kInactiveVariance = 1.0;
// 转动矩阵离正交差这么多就不当它是转动。
constexpr double kOrthonormalTolerance = 1e-6;
constexpr int kRotation = 0;
constexpr int kVelocity = 3;
constexpr int kPosition = 6;

[[noreturn]] void fail(const std::string& message) { throw std::invalid_argument(message); }

void check_non_negative(double value, const std::string& what) {
  if (!(value >= 0.0) || !std::isfinite(value)) fail(what + "要是 0 或者正数");
}

Eigen::Matrix3d orthonormalized(const Eigen::Matrix3d& rotation) {
  Eigen::Quaterniond quaternion(rotation);
  quaternion.normalize();
  return quaternion.toRotationMatrix();
}

}  // namespace

Estimator::Estimator(EstimatorConfig config) : config_(std::move(config)) {
  if (config_.contact_count < 0 || config_.contact_count > kMaxContacts) {
    fail("能着地的点要有 0~" + std::to_string(kMaxContacts) + " 个");
  }
  check_non_negative(config_.gyro_noise, "角速度的噪声");
  check_non_negative(config_.accel_noise, "加速度的噪声");
  check_non_negative(config_.gyro_bias_walk, "角速度零偏的变化");
  check_non_negative(config_.accel_bias_walk, "加速度零偏的变化");
  check_non_negative(config_.contact_noise, "着地点的滑动");
  check_non_negative(config_.kinematics_noise_m, "腿的运动学的误差");
  check_non_negative(config_.initial_rotation_rad, "一开始转动的不确定");
  check_non_negative(config_.initial_velocity_m_s, "一开始速度的不确定");
  check_non_negative(config_.initial_position_m, "一开始位置的不确定");
  check_non_negative(config_.initial_gyro_bias_rad_s, "一开始角速度零偏的不确定");
  check_non_negative(config_.initial_accel_bias_m_s2, "一开始加速度零偏的不确定");
  if (!config_.gravity.allFinite()) fail("重力不是数");
  size_ = 15 + 3 * config_.contact_count;
  const auto size = static_cast<Eigen::Index>(size_);
  contacts_.assign(static_cast<std::size_t>(config_.contact_count), Eigen::Vector3d::Zero());
  active_.assign(static_cast<std::size_t>(config_.contact_count), false);
  covariance_ = Eigen::MatrixXd::Zero(size, size);
  transition_ = Eigen::MatrixXd::Zero(size, size);
  noise_map_ = Eigen::MatrixXd::Zero(size, size);
  noise_ = Eigen::MatrixXd::Zero(size, size);
  scratch_ = Eigen::MatrixXd::Zero(size, size);
  gain_ = Eigen::MatrixXd::Zero(size, 3);
  gain_transpose_scratch_ = Eigen::MatrixXd::Zero(3, size);
  correction_ = Eigen::VectorXd::Zero(size);
  reset(Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero(), Eigen::Vector3d::Zero());
}

void Estimator::reset(const Eigen::Matrix3d& rotation, const Eigen::Vector3d& velocity,
                      const Eigen::Vector3d& position) {
  if (!rotation.allFinite() || !velocity.allFinite() || !position.allFinite()) fail("开始的状态里有不是数的值");
  if ((rotation.transpose() * rotation - Eigen::Matrix3d::Identity()).cwiseAbs().maxCoeff() > kOrthonormalTolerance ||
      rotation.determinant() <= 0.0) {
    fail("开始的转动不是转动矩阵");
  }
  rotation_ = orthonormalized(rotation);
  velocity_ = velocity;
  position_ = position;
  gyro_bias_.setZero();
  accel_bias_.setZero();
  for (auto& contact : contacts_) contact.setZero();
  active_.assign(active_.size(), false);
  covariance_.setZero();
  const auto square = [](double value) { return value * value; };
  covariance_.diagonal().segment<3>(kRotation).setConstant(square(config_.initial_rotation_rad));
  covariance_.diagonal().segment<3>(kVelocity).setConstant(square(config_.initial_velocity_m_s));
  covariance_.diagonal().segment<3>(kPosition).setConstant(square(config_.initial_position_m));
  for (int contact = 0; contact < config_.contact_count; ++contact) {
    covariance_.diagonal().segment<3>(contact_index(contact)).setConstant(kInactiveVariance);
  }
  covariance_.diagonal().segment<3>(gyro_bias_index()).setConstant(square(config_.initial_gyro_bias_rad_s));
  covariance_.diagonal().segment<3>(accel_bias_index()).setConstant(square(config_.initial_accel_bias_m_s2));
}

void Estimator::propagate(const Eigen::Vector3d& gyro, const Eigen::Vector3d& accel, double dt) {
  if (!(dt > 0.0) || !std::isfinite(dt)) fail("往前推的时间要是正数");
  if (!gyro.allFinite() || !accel.allFinite()) fail("IMU 的读数里有不是数的值");
  const Eigen::Matrix3d rotation = rotation_;
  const Eigen::Vector3d velocity = velocity_;
  const Eigen::Vector3d position = position_;
  const Eigen::Vector3d acceleration = rotation * (accel - accel_bias_) + config_.gravity;
  rotation_ = orthonormalized(rotation * exp_so3((gyro - gyro_bias_) * dt));
  position_ = position + velocity * dt + 0.5 * acceleration * dt * dt;
  velocity_ = velocity + acceleration * dt;

  // 误差方程 dξ/dt = A ξ + G w。转移矩阵 Φ = I + A dt + (A dt)² / 2（1 毫秒一步，足够准）。
  const int gyro_bias = gyro_bias_index();
  const int accel_bias = accel_bias_index();
  scratch_.setZero();
  scratch_.block<3, 3>(kVelocity, kRotation) = hat(config_.gravity) * dt;
  scratch_.block<3, 3>(kPosition, kVelocity) = Eigen::Matrix3d::Identity() * dt;
  scratch_.block<3, 3>(kRotation, gyro_bias) = -rotation * dt;
  scratch_.block<3, 3>(kVelocity, gyro_bias) = -hat(velocity) * rotation * dt;
  scratch_.block<3, 3>(kVelocity, accel_bias) = -rotation * dt;
  scratch_.block<3, 3>(kPosition, gyro_bias) = -hat(position) * rotation * dt;
  for (int contact = 0; contact < config_.contact_count; ++contact) {
    if (!active_[static_cast<std::size_t>(contact)]) continue;
    scratch_.block<3, 3>(contact_index(contact), gyro_bias) =
        -hat(contacts_[static_cast<std::size_t>(contact)]) * rotation * dt;
  }
  transition_.noalias() = scratch_ * scratch_;
  transition_ *= 0.5;
  transition_ += scratch_;
  transition_.diagonal().array() += 1.0;

  // 噪声：IMU 的噪声在 IMU 的坐标里，经过伴随矩阵 Ad_X 换到误差上；零偏的变化直接加。
  noise_map_.setZero();
  noise_map_.block<3, 3>(kRotation, kRotation) = rotation;
  noise_map_.block<3, 3>(kVelocity, kRotation) = hat(velocity) * rotation;
  noise_map_.block<3, 3>(kVelocity, kVelocity) = rotation;
  noise_map_.block<3, 3>(kPosition, kRotation) = hat(position) * rotation;
  noise_map_.block<3, 3>(kPosition, kPosition) = rotation;
  for (int contact = 0; contact < config_.contact_count; ++contact) {
    const int index = contact_index(contact);
    noise_map_.block<3, 3>(index, kRotation) = hat(contacts_[static_cast<std::size_t>(contact)]) * rotation;
    noise_map_.block<3, 3>(index, index) = rotation;
  }
  noise_map_.block<3, 3>(gyro_bias, gyro_bias).setIdentity();
  noise_map_.block<3, 3>(accel_bias, accel_bias).setIdentity();
  noise_.setZero();
  const auto square = [](double value) { return value * value; };
  noise_.diagonal().segment<3>(kRotation).setConstant(square(config_.gyro_noise));
  noise_.diagonal().segment<3>(kVelocity).setConstant(square(config_.accel_noise));
  for (int contact = 0; contact < config_.contact_count; ++contact) {
    if (active_[static_cast<std::size_t>(contact)]) {
      noise_.diagonal().segment<3>(contact_index(contact)).setConstant(square(config_.contact_noise));
    }
  }
  noise_.diagonal().segment<3>(gyro_bias).setConstant(square(config_.gyro_bias_walk));
  noise_.diagonal().segment<3>(accel_bias).setConstant(square(config_.accel_bias_walk));
  scratch_.noalias() = noise_map_ * noise_;
  noise_.noalias() = scratch_ * noise_map_.transpose();
  covariance_ += noise_ * dt;
  scratch_.noalias() = transition_ * covariance_;
  covariance_.noalias() = scratch_ * transition_.transpose();
  scratch_ = covariance_.transpose();
  covariance_ += scratch_;
  covariance_ *= 0.5;
}

void Estimator::correct(const std::vector<ContactMeasurement>& contacts) {
  if (static_cast<int>(contacts.size()) != config_.contact_count) {
    fail("着地点的读数有 " + std::to_string(contacts.size()) + " 个，应该是 " + std::to_string(config_.contact_count));
  }
  for (const auto& contact : contacts) {
    if (!contact.position_m.allFinite()) fail("着地点的位置里有不是数的值");
  }
  for (int contact = 0; contact < config_.contact_count; ++contact) {
    const auto& measurement = contacts[static_cast<std::size_t>(contact)];
    const bool active = active_[static_cast<std::size_t>(contact)];
    if (!measurement.in_contact) {
      if (active) deactivate(contact);
    } else if (!active) {
      activate(contact, measurement.position_m);
    } else {
      update(contact, measurement.position_m);
    }
  }
}

const Eigen::Vector3d& Estimator::contact_position(int contact) const {
  if (contact < 0 || contact >= config_.contact_count) fail("没有第 " + std::to_string(contact) + " 个着地点");
  return contacts_[static_cast<std::size_t>(contact)];
}

bool Estimator::contact_active(int contact) const {
  if (contact < 0 || contact >= config_.contact_count) fail("没有第 " + std::to_string(contact) + " 个着地点");
  return active_[static_cast<std::size_t>(contact)];
}

void Estimator::activate(int contact, const Eigen::Vector3d& measured) {
  // 刚着地：着地点 d = p + R y。右不变的误差里 ξ_d = ξ_p - R n，所以照着 p 的那几行、几列抄，再加上运动学的误差。
  const int index = contact_index(contact);
  contacts_[static_cast<std::size_t>(contact)] = position_ + rotation_ * measured;
  covariance_.middleRows(index, 3) = covariance_.middleRows(kPosition, 3);
  covariance_.middleCols(index, 3) = covariance_.middleCols(kPosition, 3);
  covariance_.block<3, 3>(index, index) = covariance_.block<3, 3>(kPosition, kPosition) +
                                          config_.kinematics_noise_m * config_.kinematics_noise_m *
                                              Eigen::Matrix3d::Identity();
  active_[static_cast<std::size_t>(contact)] = true;
}

void Estimator::deactivate(int contact) {
  const int index = contact_index(contact);
  covariance_.middleRows(index, 3).setZero();
  covariance_.middleCols(index, 3).setZero();
  covariance_.block<3, 3>(index, index) = kInactiveVariance * Eigen::Matrix3d::Identity();
  active_[static_cast<std::size_t>(contact)] = false;
}

void Estimator::update(int contact, const Eigen::Vector3d& measured) {
  // 量到的 y = Rᵀ (d - p)。新息 z = R y - (d - p) = H ξ + R n，H 在 p 那几列是 -I、在 d 那几列是 I（和状态无关）。
  const int index = contact_index(contact);
  const double variance = config_.kinematics_noise_m * config_.kinematics_noise_m;
  const Eigen::Vector3d innovation =
      rotation_ * measured - (contacts_[static_cast<std::size_t>(contact)] - position_);
  gain_ = covariance_.middleCols(index, 3) - covariance_.middleCols(kPosition, 3);  // 先放 P Hᵀ
  const Eigen::Matrix3d innovation_covariance = gain_.middleRows(index, 3) - gain_.middleRows(kPosition, 3) +
                                                variance * Eigen::Matrix3d::Identity();
  const Eigen::LLT<Eigen::Matrix3d> factor(innovation_covariance);
  if (factor.info() != Eigen::Success) fail("新息的协方差不是正定的（状态估计坏了）");
  gain_transpose_scratch_ = gain_.transpose();
  factor.solveInPlace(gain_transpose_scratch_);
  gain_ = gain_transpose_scratch_.transpose();  // K = P Hᵀ S⁻¹
  correction_.noalias() = gain_ * innovation;
  apply_correction(correction_);
  // Joseph 形式：P = (I - K H) P (I - K H)ᵀ + K N Kᵀ，数值上更稳，一直是对称、半正定的。
  transition_.setIdentity();
  transition_.middleCols(kPosition, 3) += gain_;
  transition_.middleCols(index, 3) -= gain_;
  scratch_.noalias() = transition_ * covariance_;
  covariance_.noalias() = scratch_ * transition_.transpose();
  covariance_.noalias() += variance * gain_ * gain_.transpose();
  scratch_ = covariance_.transpose();
  covariance_ += scratch_;
  covariance_ *= 0.5;
}

void Estimator::apply_correction(const Eigen::VectorXd& correction) {
  // X ← exp(δξ) X：转动、速度、位置、着地点一起改；零偏直接加。
  const Eigen::Vector3d angle = correction.segment<3>(kRotation);
  const Eigen::Matrix3d turn = exp_so3(angle);
  const Eigen::Matrix3d jacobian = left_jacobian_so3(angle);
  rotation_ = orthonormalized(turn * rotation_);
  velocity_ = turn * velocity_ + jacobian * correction.segment<3>(kVelocity);
  position_ = turn * position_ + jacobian * correction.segment<3>(kPosition);
  for (int contact = 0; contact < config_.contact_count; ++contact) {
    auto& point = contacts_[static_cast<std::size_t>(contact)];
    point = turn * point + jacobian * correction.segment<3>(contact_index(contact));
  }
  gyro_bias_ += correction.segment<3>(gyro_bias_index());
  accel_bias_ += correction.segment<3>(accel_bias_index());
}

}  // namespace nova::rt
