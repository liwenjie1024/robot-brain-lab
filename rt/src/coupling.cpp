#include "nova_rt/coupling.hpp"

#include <cmath>
#include <map>
#include <numeric>
#include <stdexcept>
#include <string>

namespace nova::rt {
namespace {

// 组的换算矩阵最大、最小奇异值之比超过这个就当作求不了逆：并联的一对差不多重合时，
// 从驱动器的读数算出来的关节角度会被一点点读数的误差放大很多倍。
constexpr double kMaxConditionNumber = 1e6;

[[noreturn]] void fail(const std::string& message) { throw std::invalid_argument(message); }

class DisjointSets {
 public:
  explicit DisjointSets(int size) : parent_(static_cast<std::size_t>(size)) {
    std::iota(parent_.begin(), parent_.end(), 0);
  }

  int find(int item) {
    while (parent_[static_cast<std::size_t>(item)] != item) {
      auto& parent = parent_[static_cast<std::size_t>(item)];
      parent = parent_[static_cast<std::size_t>(parent)];
      item = parent;
    }
    return item;
  }

  void unite(int first, int second) { parent_[static_cast<std::size_t>(find(first))] = find(second); }

 private:
  std::vector<int> parent_;
};

std::string list(const std::vector<int>& items) {
  std::string text;
  for (std::size_t i = 0; i < items.size(); ++i) {
    text += (i == 0 ? "" : "、") + std::to_string(items[i]);
  }
  return text;
}

void check_size(Eigen::Index actual, int expected, const char* what) {
  if (actual != expected) {
    fail(std::string(what) + "的长度是 " + std::to_string(actual) + "，应该是 " + std::to_string(expected));
  }
}

}  // namespace

Coupling::Coupling(int joint_count, const std::vector<std::vector<Transmission>>& actuators)
    : joint_count_(joint_count), actuator_count_(static_cast<int>(actuators.size())) {
  if (joint_count <= 0) fail("关节的个数要大于 0");
  if (actuator_count_ == 0) fail("没有驱动器");

  // 驱动器是 0..A-1，关节是 A..A+J-1：带着同一个关节的驱动器连在一起，就是一组。
  DisjointSets sets(actuator_count_ + joint_count_);
  std::vector<bool> driven(static_cast<std::size_t>(joint_count), false);
  for (int actuator = 0; actuator < actuator_count_; ++actuator) {
    const auto& transmissions = actuators[static_cast<std::size_t>(actuator)];
    if (transmissions.empty()) fail("第 " + std::to_string(actuator) + " 个驱动器没有带着关节");
    std::vector<bool> seen(static_cast<std::size_t>(joint_count), false);
    for (const auto& transmission : transmissions) {
      if (transmission.joint < 0 || transmission.joint >= joint_count) {
        fail("第 " + std::to_string(actuator) + " 个驱动器带着的关节编号 " + std::to_string(transmission.joint) +
             " 不在 0~" + std::to_string(joint_count - 1) + " 里");
      }
      if (transmission.coefficient == 0.0 || !std::isfinite(transmission.coefficient)) {
        fail("第 " + std::to_string(actuator) + " 个驱动器带着关节 " + std::to_string(transmission.joint) +
             " 的系数不能是 0 或者不是数");
      }
      if (seen[static_cast<std::size_t>(transmission.joint)]) {
        fail("第 " + std::to_string(actuator) + " 个驱动器把关节 " + std::to_string(transmission.joint) + " 写了两次");
      }
      seen[static_cast<std::size_t>(transmission.joint)] = true;
      driven[static_cast<std::size_t>(transmission.joint)] = true;
      sets.unite(actuator, actuator_count_ + transmission.joint);
    }
  }
  for (int joint = 0; joint < joint_count; ++joint) {
    if (!driven[static_cast<std::size_t>(joint)]) fail("第 " + std::to_string(joint) + " 个关节没有驱动器带着");
  }

  std::map<int, std::size_t> group_of_root;
  for (int actuator = 0; actuator < actuator_count_; ++actuator) {
    const int root = sets.find(actuator);
    auto [found, inserted] = group_of_root.try_emplace(root, groups_.size());
    if (inserted) groups_.emplace_back();
    groups_[found->second].actuators.push_back(actuator);
  }
  for (int joint = 0; joint < joint_count; ++joint) {
    groups_[group_of_root.at(sets.find(actuator_count_ + joint))].joints.push_back(joint);
  }

  for (auto& group : groups_) {
    if (group.actuators.size() != group.joints.size()) {
      fail("驱动器 " + list(group.actuators) + " 一起带着关节 " + list(group.joints) +
           "：驱动器和关节要一样多，才能从驱动器的读数算出关节的角度");
    }
    const auto size = static_cast<Eigen::Index>(group.joints.size());
    group.forward = Eigen::MatrixXd::Zero(size, size);
    for (Eigen::Index row = 0; row < size; ++row) {
      const auto actuator = group.actuators[static_cast<std::size_t>(row)];
      for (const auto& transmission : actuators[static_cast<std::size_t>(actuator)]) {
        Eigen::Index column = 0;
        while (group.joints[static_cast<std::size_t>(column)] != transmission.joint) ++column;
        group.forward(row, column) = transmission.coefficient;
      }
    }
    const Eigen::JacobiSVD<Eigen::MatrixXd> svd(group.forward);
    const auto& singular = svd.singularValues();
    const double smallest = singular(size - 1);
    if (smallest == 0.0 || singular(0) / smallest > kMaxConditionNumber) {
      fail("驱动器 " + list(group.actuators) + " 带着关节 " + list(group.joints) +
           " 的换算求不了逆（两个驱动器带关节的样子差不多一样）");
    }
    group.inverse = group.forward.inverse();
  }
}

void Coupling::actuators_from_joints(const Eigen::Ref<const Eigen::VectorXd>& joints,
                                     Eigen::Ref<Eigen::VectorXd> actuators) const {
  check_size(joints.size(), joint_count_, "关节的角度");
  check_size(actuators.size(), actuator_count_, "驱动器的读数");
  for (const auto& group : groups_) {
    const auto size = static_cast<Eigen::Index>(group.joints.size());
    for (Eigen::Index row = 0; row < size; ++row) {
      double sum = 0.0;
      for (Eigen::Index column = 0; column < size; ++column) {
        sum += group.forward(row, column) * joints(group.joints[static_cast<std::size_t>(column)]);
      }
      actuators(group.actuators[static_cast<std::size_t>(row)]) = sum;
    }
  }
}

void Coupling::joints_from_actuators(const Eigen::Ref<const Eigen::VectorXd>& actuators,
                                     Eigen::Ref<Eigen::VectorXd> joints) const {
  check_size(actuators.size(), actuator_count_, "驱动器的读数");
  check_size(joints.size(), joint_count_, "关节的角度");
  for (const auto& group : groups_) {
    const auto size = static_cast<Eigen::Index>(group.joints.size());
    for (Eigen::Index column = 0; column < size; ++column) {
      double sum = 0.0;
      for (Eigen::Index row = 0; row < size; ++row) {
        sum += group.inverse(column, row) * actuators(group.actuators[static_cast<std::size_t>(row)]);
      }
      joints(group.joints[static_cast<std::size_t>(column)]) = sum;
    }
  }
}

void Coupling::joint_torques_from_forces(const Eigen::Ref<const Eigen::VectorXd>& forces,
                                         Eigen::Ref<Eigen::VectorXd> torques) const {
  check_size(forces.size(), actuator_count_, "驱动器的力");
  check_size(torques.size(), joint_count_, "关节的力矩");
  for (const auto& group : groups_) {
    const auto size = static_cast<Eigen::Index>(group.joints.size());
    for (Eigen::Index column = 0; column < size; ++column) {
      double sum = 0.0;
      for (Eigen::Index row = 0; row < size; ++row) {
        sum += group.forward(row, column) * forces(group.actuators[static_cast<std::size_t>(row)]);
      }
      torques(group.joints[static_cast<std::size_t>(column)]) = sum;
    }
  }
}

void Coupling::forces_from_joint_torques(const Eigen::Ref<const Eigen::VectorXd>& torques,
                                         Eigen::Ref<Eigen::VectorXd> forces) const {
  check_size(torques.size(), joint_count_, "关节的力矩");
  check_size(forces.size(), actuator_count_, "驱动器的力");
  for (const auto& group : groups_) {
    const auto size = static_cast<Eigen::Index>(group.joints.size());
    for (Eigen::Index row = 0; row < size; ++row) {
      double sum = 0.0;
      for (Eigen::Index column = 0; column < size; ++column) {
        sum += group.inverse(column, row) * torques(group.joints[static_cast<std::size_t>(column)]);
      }
      forces(group.actuators[static_cast<std::size_t>(row)]) = sum;
    }
  }
}

}  // namespace nova::rt
