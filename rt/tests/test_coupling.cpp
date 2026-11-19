// 驱动器和关节之间的换算的测试。

#include <gtest/gtest.h>

#include <stdexcept>

#include "nova_rt/coupling.hpp"

namespace nova::rt {
namespace {

using Transmissions = std::vector<std::vector<Transmission>>;

// 三个关节：0 自己一个驱动器；1、2 是并联的一对（和、差），驱动器的顺序故意和关节的不一样。
Coupling mixed() {
  return Coupling(3, Transmissions{
                         {{1, 1.0}, {2, -1.0}},  // 差
                         {{0, 1.0}},
                         {{1, 1.0}, {2, 1.0}},  // 和
                     });
}

// 说明：一个驱动器带一个关节、系数 1：驱动器的读数就是关节的角度，两个方向都对。
TEST(Coupling, OneJointPerActuatorIsTheIdentity) {
  const Coupling coupling(2, Transmissions{{{0, 1.0}}, {{1, 1.0}}});
  Eigen::VectorXd joints(2);
  coupling.joints_from_actuators(Eigen::Vector2d(0.3, -0.2), joints);
  EXPECT_DOUBLE_EQ(joints(0), 0.3);
  EXPECT_DOUBLE_EQ(joints(1), -0.2);
  EXPECT_EQ(coupling.groups().size(), 2U);
}

// 说明：并联的一对：和 = q1 + q2、差 = q1 - q2，从读数算回关节的角度。
TEST(Coupling, SumAndDifferencePairIsInverted) {
  const auto coupling = mixed();
  Eigen::VectorXd actuators(3);
  coupling.actuators_from_joints(Eigen::Vector3d(0.5, 0.2, -0.1), actuators);
  EXPECT_DOUBLE_EQ(actuators(0), 0.3);   // 差：0.2 - (-0.1)
  EXPECT_DOUBLE_EQ(actuators(1), 0.5);
  EXPECT_DOUBLE_EQ(actuators(2), 0.1);   // 和：0.2 + (-0.1)
  Eigen::VectorXd joints(3);
  coupling.joints_from_actuators(actuators, joints);
  EXPECT_NEAR(joints(0), 0.5, 1e-15);
  EXPECT_NEAR(joints(1), 0.2, 1e-15);
  EXPECT_NEAR(joints(2), -0.1, 1e-15);
}

// 说明：力和力矩：τ = Cᵀ f，f = C⁻ᵀ τ，来回一遍还是原来的数。
TEST(Coupling, ForcesAndTorquesRoundTrip) {
  const auto coupling = mixed();
  Eigen::VectorXd torques(3);
  coupling.joint_torques_from_forces(Eigen::Vector3d(10.0, 4.0, 30.0), torques);
  EXPECT_DOUBLE_EQ(torques(0), 4.0);
  EXPECT_DOUBLE_EQ(torques(1), 40.0);  // 两个驱动器一起往一个方向：10 + 30
  EXPECT_DOUBLE_EQ(torques(2), 20.0);  // -10 + 30
  Eigen::VectorXd forces(3);
  coupling.forces_from_joint_torques(torques, forces);
  EXPECT_NEAR(forces(0), 10.0, 1e-12);
  EXPECT_NEAR(forces(1), 4.0, 1e-12);
  EXPECT_NEAR(forces(2), 30.0, 1e-12);
}

// 说明：一个关节单独用力时，并联的两个驱动器各出一半。
TEST(Coupling, OneJointAloneSplitsEvenlyOverThePair) {
  const auto coupling = mixed();
  Eigen::VectorXd forces(3);
  coupling.forces_from_joint_torques(Eigen::Vector3d(0.0, 50.0, 0.0), forces);
  EXPECT_NEAR(forces(0), 25.0, 1e-12);
  EXPECT_NEAR(forces(2), 25.0, 1e-12);
}

// 说明：系数不是 1（减速比、连杆）的也能换算。
TEST(Coupling, CoefficientsOtherThanOneAreHonoured) {
  const Coupling coupling(1, Transmissions{{{0, 2.0}}});
  Eigen::VectorXd joints(1);
  coupling.joints_from_actuators(Eigen::VectorXd::Constant(1, 1.0), joints);
  EXPECT_DOUBLE_EQ(joints(0), 0.5);
  Eigen::VectorXd forces(1);
  coupling.forces_from_joint_torques(Eigen::VectorXd::Constant(1, 10.0), forces);
  EXPECT_DOUBLE_EQ(forces(0), 5.0);
}

// 说明：两个驱动器都只带着同一个关节（驱动器比关节多）就拒绝：算不出每个驱动器该出多少。
TEST(Coupling, MoreActuatorsThanJointsInAGroupIsRefused) {
  EXPECT_THROW(Coupling(1, Transmissions{{{0, 1.0}}, {{0, 1.0}}}), std::invalid_argument);
}

// 说明：两个驱动器带关节的样子一样（换算求不了逆）就拒绝。
TEST(Coupling, ASingularPairIsRefused) {
  EXPECT_THROW(Coupling(2, Transmissions{{{0, 1.0}, {1, 1.0}}, {{0, 2.0}, {1, 2.0}}}), std::invalid_argument);
}

// 说明：有关节没有驱动器带着、编号超出范围、系数是 0、同一个关节写两次，都拒绝。
TEST(Coupling, BadTransmissionsAreRefused) {
  EXPECT_THROW(Coupling(2, Transmissions{{{0, 1.0}}}), std::invalid_argument);
  EXPECT_THROW(Coupling(1, Transmissions{{{1, 1.0}}}), std::invalid_argument);
  EXPECT_THROW(Coupling(1, Transmissions{{{0, 0.0}}}), std::invalid_argument);
  EXPECT_THROW(Coupling(1, Transmissions{{{0, 1.0}, {0, 1.0}}}), std::invalid_argument);
  EXPECT_THROW(Coupling(1, Transmissions{{}}), std::invalid_argument);
}

// 说明：给的数组长度不对就拒绝，不读、不写别处的内存。
TEST(Coupling, WrongLengthsAreRefused) {
  const auto coupling = mixed();
  Eigen::VectorXd joints(2);
  EXPECT_THROW(coupling.joints_from_actuators(Eigen::Vector3d::Zero(), joints), std::invalid_argument);
}

}  // namespace
}  // namespace nova::rt
