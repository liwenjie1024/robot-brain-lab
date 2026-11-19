// 转动的几样小东西的测试。

#include <gtest/gtest.h>

#include <cmath>
#include <numbers>

#include "nova_rt/lie.hpp"

namespace nova::rt {
namespace {

// 说明：叉乘矩阵乘一个向量就是叉乘。
TEST(Lie, HatIsTheCrossProduct) {
  const Eigen::Vector3d a(1.0, -2.0, 0.5);
  const Eigen::Vector3d b(0.3, 0.7, -1.1);
  EXPECT_TRUE((hat(a) * b).isApprox(a.cross(b), 1e-15));
}

// 说明：绕竖轴转 90°：x 轴转到 y 轴。
TEST(Lie, ExpTurnsAboutTheAxis) {
  const Eigen::Matrix3d turn = exp_so3(Eigen::Vector3d(0.0, 0.0, std::numbers::pi / 2));
  EXPECT_TRUE((turn * Eigen::Vector3d::UnitX()).isApprox(Eigen::Vector3d::UnitY(), 1e-12));
  EXPECT_NEAR(turn.determinant(), 1.0, 1e-12);
}

// 说明：exp 和 log 来回一遍还是原来的转角（大的、小的、几乎是 0 的）。
TEST(Lie, ExpAndLogRoundTrip) {
  for (const Eigen::Vector3d& angle : {Eigen::Vector3d(0.3, -0.2, 1.1), Eigen::Vector3d(1e-5, 2e-5, -1e-5),
                                       Eigen::Vector3d(1e-10, 0.0, 0.0)}) {
    EXPECT_TRUE(log_so3(exp_so3(angle)).isApprox(angle, 1e-9)) << angle.transpose();
  }
}

// 说明：左雅可比：exp 的微分（数值上差一点点的转角，转动差多少）。
TEST(Lie, LeftJacobianMatchesTheDerivative) {
  const Eigen::Vector3d angle(0.4, -0.3, 0.8);
  const Eigen::Vector3d step(1e-7, -2e-7, 1.5e-7);
  // exp(θ + δ) ≈ exp(J_l(θ) δ) exp(θ)
  const Eigen::Matrix3d left = exp_so3(angle + step) * exp_so3(angle).transpose();
  EXPECT_TRUE(log_so3(left).isApprox(left_jacobian_so3(angle) * step, 1e-6));
}

}  // namespace
}  // namespace nova::rt
