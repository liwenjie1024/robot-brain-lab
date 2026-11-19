#pragma once

// 转动（SO(3)）要用的几样小东西：叉乘矩阵、指数映射、左雅可比。状态估计用它们。

#include <Eigen/Dense>
#include <algorithm>
#include <cmath>

namespace nova::rt {

// 小于这个角（弧度）就用泰勒展开，免得除以接近 0 的数。
inline constexpr double kSmallAngleRad = 1e-8;

// 叉乘矩阵：hat(a) * b = a × b。
inline Eigen::Matrix3d hat(const Eigen::Vector3d& vector) {
  Eigen::Matrix3d matrix;
  matrix << 0.0, -vector.z(), vector.y(), vector.z(), 0.0, -vector.x(), -vector.y(), vector.x(), 0.0;
  return matrix;
}

// 绕 axis 方向转 |angle| 弧度的转动矩阵（罗德里格斯公式）。
inline Eigen::Matrix3d exp_so3(const Eigen::Vector3d& angle) {
  const double theta = angle.norm();
  const Eigen::Matrix3d skew = hat(angle);
  if (theta < kSmallAngleRad) return Eigen::Matrix3d::Identity() + skew + 0.5 * skew * skew;
  return Eigen::Matrix3d::Identity() + std::sin(theta) / theta * skew +
         (1.0 - std::cos(theta)) / (theta * theta) * skew * skew;
}

// SO(3) 的左雅可比：exp 在 SE_K(3) 里把速度、位置那几列也带上时用。
inline Eigen::Matrix3d left_jacobian_so3(const Eigen::Vector3d& angle) {
  const double theta = angle.norm();
  const Eigen::Matrix3d skew = hat(angle);
  if (theta < kSmallAngleRad) return Eigen::Matrix3d::Identity() + 0.5 * skew;
  return Eigen::Matrix3d::Identity() + (1.0 - std::cos(theta)) / (theta * theta) * skew +
         (theta - std::sin(theta)) / (theta * theta * theta) * skew * skew;
}

// 转动矩阵 → 转角向量（exp_so3 的反过来）。只在测试和报告里用。
inline Eigen::Vector3d log_so3(const Eigen::Matrix3d& rotation) {
  const double cosine = std::clamp(0.5 * (rotation.trace() - 1.0), -1.0, 1.0);
  const double theta = std::acos(cosine);
  const Eigen::Vector3d vee(rotation(2, 1) - rotation(1, 2), rotation(0, 2) - rotation(2, 0),
                            rotation(1, 0) - rotation(0, 1));
  if (theta < kSmallAngleRad) return 0.5 * vee;
  return theta / (2.0 * std::sin(theta)) * vee;
}

}  // namespace nova::rt
