// 状态估计（带接触的 InEKF）的测试：用造出来的 IMU 读数和腿的运动学（知道真的状态），看估出来的对不对。

#include <gtest/gtest.h>

#include <chrono>
#include <cmath>
#include <numbers>
#include <iostream>
#include <stdexcept>
#include <vector>

#include "nova_rt/estimator.hpp"
#include "nova_rt/lie.hpp"

namespace nova::rt {
namespace {

constexpr double kStep = 0.001;
constexpr double kGravity = 9.81;
const Eigen::Vector3d kLeftFoot(0.0, 0.1, -0.8);
const Eigen::Vector3d kRightFoot(0.0, -0.1, -0.8);

EstimatorConfig config() {
  EstimatorConfig config;
  config.gyro_noise = 1e-3;
  config.accel_noise = 1e-2;
  config.gyro_bias_walk = 1e-4;
  config.accel_bias_walk = 1e-3;
  config.contact_noise = 1e-2;
  config.kinematics_noise_m = 2e-3;
  config.initial_rotation_rad = 0.2;
  config.initial_velocity_m_s = 1.0;
  config.initial_position_m = 1e-3;
  config.initial_gyro_bias_rad_s = 0.02;
  config.initial_accel_bias_m_s2 = 0.1;
  return config;
}

// 真的身体：转动 R、位置 p，两只脚在世界里不动。IMU 读到的比力 = Rᵀ (a - g)。
std::vector<ContactMeasurement> feet_seen(const Eigen::Matrix3d& rotation, const Eigen::Vector3d& position,
                                          const std::vector<Eigen::Vector3d>& feet_world) {
  std::vector<ContactMeasurement> seen;
  for (const auto& foot : feet_world) seen.push_back({true, rotation.transpose() * (foot - position)});
  return seen;
}

double tilt_error_deg(const Eigen::Matrix3d& estimated, const Eigen::Matrix3d& actual) {
  // 只看重力方向（横滚、俯仰）差多少：偏航本来就看不出来。
  const Eigen::Vector3d up_estimated = estimated.transpose() * Eigen::Vector3d::UnitZ();
  const Eigen::Vector3d up_actual = actual.transpose() * Eigen::Vector3d::UnitZ();
  return std::acos(std::clamp(up_estimated.dot(up_actual), -1.0, 1.0)) * 180.0 / std::numbers::pi;
}

// 说明：站着不动、IMU 没有噪声：估出来的一直不动，转动、速度、位置都对。
TEST(Estimator, StandingStillStaysStill) {
  Estimator estimator(config());
  const std::vector<Eigen::Vector3d> feet = {kLeftFoot, kRightFoot};
  for (int step = 0; step < 2000; ++step) {
    estimator.propagate(Eigen::Vector3d::Zero(), Eigen::Vector3d(0.0, 0.0, kGravity), kStep);
    estimator.correct(feet_seen(Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero(), feet));
  }
  EXPECT_LT(estimator.velocity().norm(), 1e-6);
  EXPECT_LT(estimator.position().norm(), 1e-6);
  EXPECT_TRUE(estimator.rotation().isApprox(Eigen::Matrix3d::Identity(), 1e-9));
}

// 说明：一开始以为不动，其实以 0.5 m/s 往前走（两只脚都踩在地上，身体在动）：1 秒以后估出来的速度差不到 1 cm/s。
TEST(Estimator, ContactsCorrectAWrongStartingVelocity) {
  Estimator estimator(config());
  const Eigen::Vector3d velocity(0.5, 0.0, 0.0);
  const std::vector<Eigen::Vector3d> feet = {kLeftFoot, kRightFoot};
  Eigen::Vector3d position = Eigen::Vector3d::Zero();
  for (int step = 0; step < 1000; ++step) {
    estimator.propagate(Eigen::Vector3d::Zero(), Eigen::Vector3d(0.0, 0.0, kGravity), kStep);
    position += velocity * kStep;
    estimator.correct(feet_seen(Eigen::Matrix3d::Identity(), position, feet));
  }
  EXPECT_LT((estimator.velocity() - velocity).norm(), 0.01);
  EXPECT_LT((estimator.position() - position).norm(), 0.01);
}

// 说明：一开始以为身体歪着 5°（其实是直的）：站 5 秒，重力和着地的脚把横滚、俯仰纠正过来（差不到 0.5°）。
TEST(Estimator, GravityAndContactsCorrectAWrongTilt) {
  Estimator estimator(config());
  estimator.reset(exp_so3(Eigen::Vector3d(5.0 * std::numbers::pi / 180.0, -3.0 * std::numbers::pi / 180.0, 0.0)), Eigen::Vector3d::Zero(),
                  Eigen::Vector3d::Zero());
  const std::vector<Eigen::Vector3d> feet = {kLeftFoot, kRightFoot};
  for (int step = 0; step < 5000; ++step) {
    estimator.propagate(Eigen::Vector3d::Zero(), Eigen::Vector3d(0.0, 0.0, kGravity), kStep);
    estimator.correct(feet_seen(Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero(), feet));
  }
  EXPECT_LT(tilt_error_deg(estimator.rotation(), Eigen::Matrix3d::Identity()), 0.5);
}

// 说明：角速度计有零偏（横滚、俯仰各 0.01 rad/s）：站 20 秒，估出零偏，身体的歪斜也不跟着漂。
TEST(Estimator, StandingRevealsTheRollAndPitchGyroBias) {
  Estimator estimator(config());
  const Eigen::Vector3d bias(0.01, -0.01, 0.0);
  const std::vector<Eigen::Vector3d> feet = {kLeftFoot, kRightFoot};
  for (int step = 0; step < 20000; ++step) {
    estimator.propagate(bias, Eigen::Vector3d(0.0, 0.0, kGravity), kStep);
    estimator.correct(feet_seen(Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero(), feet));
  }
  EXPECT_NEAR(estimator.gyro_bias().x(), bias.x(), 0.003);
  EXPECT_NEAR(estimator.gyro_bias().y(), bias.y(), 0.003);
  EXPECT_LT(tilt_error_deg(estimator.rotation(), Eigen::Matrix3d::Identity()), 0.3);
}

// 说明：转着身体（绕竖轴 0.5 rad/s）站着：转动跟得上，速度一直是 0。
TEST(Estimator, TurningInPlaceIsTracked) {
  Estimator estimator(config());
  const Eigen::Vector3d spin(0.0, 0.0, 0.5);
  const std::vector<Eigen::Vector3d> feet = {kLeftFoot, kRightFoot};
  Eigen::Matrix3d rotation = Eigen::Matrix3d::Identity();
  for (int step = 0; step < 3000; ++step) {
    estimator.propagate(spin, rotation.transpose() * Eigen::Vector3d(0.0, 0.0, kGravity), kStep);
    rotation = rotation * exp_so3(spin * kStep);
    estimator.correct(feet_seen(rotation, Eigen::Vector3d::Zero(), feet));
  }
  EXPECT_LT(log_so3(estimator.rotation().transpose() * rotation).norm(), 1e-3);
  EXPECT_LT(estimator.velocity().norm(), 1e-3);
}

// 说明：脚刚着地时记下它在世界里的位置（p + R y）；抬起来就不用了；再着地重新记。
TEST(Estimator, ContactsAreAddedAndDroppedAsFeetTouchAndLift) {
  Estimator estimator(config());
  estimator.reset(Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero(), Eigen::Vector3d(1.0, 2.0, 0.9));
  EXPECT_FALSE(estimator.contact_active(0));
  estimator.correct({{true, kLeftFoot}, {false, kRightFoot}});
  EXPECT_TRUE(estimator.contact_active(0));
  EXPECT_FALSE(estimator.contact_active(1));
  EXPECT_TRUE(estimator.contact_position(0).isApprox(Eigen::Vector3d(1.0, 2.1, 0.1), 1e-12));
  estimator.correct({{false, kLeftFoot}, {true, kRightFoot}});
  EXPECT_FALSE(estimator.contact_active(0));
  EXPECT_TRUE(estimator.contact_active(1));
  EXPECT_TRUE(estimator.contact_position(1).isApprox(Eigen::Vector3d(1.0, 1.9, 0.1), 1e-12));
}

// 说明：走了很多步（脚一会儿着地一会儿抬起，读数有噪声）以后，协方差还是对称的、没有负的特征值。
TEST(Estimator, CovarianceStaysSymmetricAndPositive) {
  Estimator estimator(config());
  for (int step = 0; step < 4000; ++step) {
    const bool left = (step / 400) % 2 == 0;
    const double wobble = 0.01 * std::sin(step * 0.01);
    estimator.propagate(Eigen::Vector3d(wobble, -wobble, 0.2 * wobble), Eigen::Vector3d(wobble, 0.0, kGravity), kStep);
    estimator.correct({{left, kLeftFoot}, {!left || step % 3 == 0, kRightFoot}});
  }
  const Eigen::MatrixXd& covariance = estimator.covariance();
  EXPECT_LT((covariance - covariance.transpose()).cwiseAbs().maxCoeff(), 1e-12);
  const Eigen::SelfAdjointEigenSolver<Eigen::MatrixXd> solver(covariance);
  EXPECT_GT(solver.eigenvalues().minCoeff(), -1e-12);
}

// 说明：不对的输入都拒绝：时间不是正数、读数不是数、着地点的个数不对、开始的转动不是转动矩阵、配置里有负的噪声。
TEST(Estimator, BadInputsAreRefused) {
  Estimator estimator(config());
  EXPECT_THROW(estimator.propagate(Eigen::Vector3d::Zero(), Eigen::Vector3d::Zero(), 0.0), std::invalid_argument);
  EXPECT_THROW(estimator.propagate(Eigen::Vector3d(std::nan(""), 0.0, 0.0), Eigen::Vector3d::Zero(), kStep),
               std::invalid_argument);
  EXPECT_THROW(estimator.correct({{true, kLeftFoot}}), std::invalid_argument);
  EXPECT_THROW(estimator.reset(2.0 * Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero(), Eigen::Vector3d::Zero()),
               std::invalid_argument);
  auto negative = config();
  negative.accel_noise = -1.0;
  EXPECT_THROW(Estimator{negative}, std::invalid_argument);
  EXPECT_THROW(estimator.contact_position(2), std::invalid_argument);
}

// 说明：一步（往前推 + 两只脚纠正）要算得比 1 毫秒快得多。
TEST(Estimator, AStepIsFarFasterThanOneMillisecond) {
  Estimator estimator(config());
  const std::vector<ContactMeasurement> feet = {{true, kLeftFoot}, {true, kRightFoot}};
  constexpr int kSteps = 20000;
  const auto begin = std::chrono::steady_clock::now();
  for (int step = 0; step < kSteps; ++step) {
    estimator.propagate(Eigen::Vector3d::Zero(), Eigen::Vector3d(0.0, 0.0, kGravity), kStep);
    estimator.correct(feet);
  }
  const std::chrono::duration<double, std::micro> elapsed = std::chrono::steady_clock::now() - begin;
  const double per_step_us = elapsed.count() / kSteps;
  std::cout << "  状态估计的一步（两只脚）：" << per_step_us << " 微秒\n";
  EXPECT_LT(per_step_us, 100.0);
}

}  // namespace
}  // namespace nova::rt
