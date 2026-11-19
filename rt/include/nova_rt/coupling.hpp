#pragma once

// 驱动器和关节之间的换算（脊髓层的第一件事）。

#include <Eigen/Dense>
#include <vector>

namespace nova::rt {

// 一个驱动器带着的一个关节：驱动器"转"的量 = 每个关节的角度 × 系数加起来；
// 关节得到的力矩 = 驱动器的力 × 系数（每个带着它的驱动器加起来）。
struct Transmission {
  int joint = 0;
  double coefficient = 1.0;
};

// 驱动器和关节之间的换算矩阵 C（驱动器 × 关节）：a = C q，τ = Cᵀ f。
//
// 驱动器按"带着同一些关节"分成组。每一组要是方的、能求逆：一个驱动器带一个关节，
// 或者并联的一对按和、差带两个关节。这样关节的角度、转速能从驱动器的读数算出来（真机上编码器在驱动器上），
// 关节的力矩也能换成每个驱动器的力。
class Coupling {
 public:
  struct Group {
    std::vector<int> actuators;  // 这一组的驱动器（全部驱动器里的编号）
    std::vector<int> joints;     // 这一组的关节（全部关节里的编号）
    Eigen::MatrixXd forward;     // C_g：驱动器 × 关节
    Eigen::MatrixXd inverse;     // C_g⁻¹：关节 × 驱动器
  };

  // actuators[i] 是第 i 个驱动器带着的关节。对不上（关节编号不对、系数是 0、组不是方的、求不了逆、
  // 有关节没有驱动器带着）就抛 std::invalid_argument，说清楚是哪里。
  Coupling(int joint_count, const std::vector<std::vector<Transmission>>& actuators);

  int joint_count() const { return joint_count_; }
  int actuator_count() const { return actuator_count_; }
  const std::vector<Group>& groups() const { return groups_; }

  // a = C q
  void actuators_from_joints(const Eigen::Ref<const Eigen::VectorXd>& joints,
                             Eigen::Ref<Eigen::VectorXd> actuators) const;
  // q = C⁻¹ a
  void joints_from_actuators(const Eigen::Ref<const Eigen::VectorXd>& actuators,
                             Eigen::Ref<Eigen::VectorXd> joints) const;
  // τ = Cᵀ f
  void joint_torques_from_forces(const Eigen::Ref<const Eigen::VectorXd>& forces,
                                 Eigen::Ref<Eigen::VectorXd> torques) const;
  // f = C⁻ᵀ τ
  void forces_from_joint_torques(const Eigen::Ref<const Eigen::VectorXd>& torques,
                                 Eigen::Ref<Eigen::VectorXd> forces) const;

 private:
  int joint_count_ = 0;
  int actuator_count_ = 0;
  std::vector<Group> groups_;
};

}  // namespace nova::rt
