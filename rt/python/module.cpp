// 脊髓层给 Python（测试台）用的样子。测试台每 1 毫秒调用一次 step。
// 给出去的都是复制的数组：下一步算的时候不会改掉上一步拿到的。

#include <nanobind/eigen/dense.h>
#include <nanobind/nanobind.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <cstdint>
#include <limits>
#include <string>
#include <utility>
#include <vector>

#include "nova_rt/spine.hpp"

namespace nb = nanobind;
using namespace nb::literals;
using nova::rt::JointLimits;
using nova::rt::Spine;

namespace {

constexpr double kInfinity = std::numeric_limits<double>::infinity();

using Flags = Eigen::Matrix<std::uint8_t, Eigen::Dynamic, 1>;

struct StepResult {
  Eigen::VectorXd actuator_position;
  Eigen::VectorXd actuator_stiffness;
  Eigen::VectorXd actuator_damping;
  Eigen::VectorXd actuator_force;
  Eigen::VectorXd joint_position;
  Eigen::VectorXd joint_velocity;
  Eigen::VectorXd joint_torque;
  Flags limited;
};

nova::rt::SpineConfig make_config(std::vector<std::string> joint_names, std::vector<JointLimits> joint_limits,
                                  std::vector<std::string> actuator_names,
                                  const std::vector<std::vector<std::pair<int, double>>>& transmissions,
                                  std::vector<double> actuator_peak_forces, double angle_margin_rad) {
  nova::rt::SpineConfig config;
  config.joint_names = std::move(joint_names);
  config.joint_limits = std::move(joint_limits);
  config.actuator_names = std::move(actuator_names);
  for (const auto& actuator : transmissions) {
    std::vector<nova::rt::Transmission> converted;
    for (const auto& [joint, coefficient] : actuator) converted.push_back({joint, coefficient});
    config.transmissions.push_back(std::move(converted));
  }
  config.actuator_peak_forces = std::move(actuator_peak_forces);
  config.angle_margin_rad = angle_margin_rad;
  return config;
}

StepResult step(Spine& spine, const Eigen::VectorXd& actuator_position, const Eigen::VectorXd& actuator_velocity,
                const Eigen::VectorXd& position_rad, const Eigen::VectorXd& velocity_rad_s,
                const Eigen::VectorXd& stiffness, const Eigen::VectorXd& damping, const Eigen::VectorXd& torque_nm) {
  const nova::rt::ActuatorState state{actuator_position, actuator_velocity};
  const nova::rt::JointCommand command{position_rad, velocity_rad_s, stiffness, damping, torque_nm};
  const auto& output = spine.step(state, command);
  StepResult result{output.actuators.position, output.actuators.stiffness, output.actuators.damping,
                    output.actuators.force,    output.joint_position_rad,   output.joint_velocity_rad_s,
                    output.joint_torque_nm,    Flags(static_cast<Eigen::Index>(output.limited.size()))};
  for (std::size_t joint = 0; joint < output.limited.size(); ++joint) {
    result.limited(static_cast<Eigen::Index>(joint)) = output.limited[joint];
  }
  return result;
}

template <void (nova::rt::Coupling::*Convert)(const Eigen::Ref<const Eigen::VectorXd>&, Eigen::Ref<Eigen::VectorXd>) const>
Eigen::VectorXd convert(const Spine& spine, const Eigen::VectorXd& values, int output_size) {
  Eigen::VectorXd output(output_size);
  (spine.coupling().*Convert)(values, output);
  return output;
}

}  // namespace

NB_MODULE(_core, module) {
  module.doc() = "实时分区（C++）：脊髓层（第一版）";
  module.attr("LIMIT_ANGLE") = static_cast<int>(nova::rt::kLimitAngle);
  module.attr("LIMIT_TORQUE") = static_cast<int>(nova::rt::kLimitTorque);
  module.attr("LIMIT_SPEED") = static_cast<int>(nova::rt::kLimitSpeed);
  module.attr("LIMIT_POWER") = static_cast<int>(nova::rt::kLimitPower);
  module.attr("LIMIT_ACTUATOR_FORCE") = static_cast<int>(nova::rt::kLimitActuatorForce);

  nb::class_<JointLimits>(module, "JointLimits", "一个关节的上限。不知道的是无穷大。")
      .def(
          "__init__",
          [](JointLimits* self, double lower_rad, double upper_rad, double peak_torque_nm, double max_speed_rad_s,
             double max_power_w) {
            new (self) JointLimits{lower_rad, upper_rad, peak_torque_nm, max_speed_rad_s, max_power_w};
          },
          "lower_rad"_a, "upper_rad"_a, "peak_torque_nm"_a, "max_speed_rad_s"_a = kInfinity,
          "max_power_w"_a = kInfinity)
      .def_ro("lower_rad", &JointLimits::lower_rad)
      .def_ro("upper_rad", &JointLimits::upper_rad)
      .def_ro("peak_torque_nm", &JointLimits::peak_torque_nm)
      .def_ro("max_speed_rad_s", &JointLimits::max_speed_rad_s)
      .def_ro("max_power_w", &JointLimits::max_power_w);

  nb::class_<StepResult>(module, "StepResult", "脊髓层一步的结果（都是复制的）。")
      .def_ro("actuator_position", &StepResult::actuator_position)
      .def_ro("actuator_stiffness", &StepResult::actuator_stiffness)
      .def_ro("actuator_damping", &StepResult::actuator_damping)
      .def_ro("actuator_force", &StepResult::actuator_force)
      .def_ro("joint_position", &StepResult::joint_position)
      .def_ro("joint_velocity", &StepResult::joint_velocity)
      .def_ro("joint_torque", &StepResult::joint_torque)
      .def_ro("limited", &StepResult::limited);

  nb::class_<Spine>(module, "Spine", "脊髓层：关节的目标和软硬 → 驱动器的命令，中间守住硬限制。")
      .def(
          "__init__",
          [](Spine* self, std::vector<std::string> joint_names, std::vector<JointLimits> joint_limits,
             std::vector<std::string> actuator_names,
             const std::vector<std::vector<std::pair<int, double>>>& transmissions,
             std::vector<double> actuator_peak_forces, double angle_margin_rad) {
            new (self) Spine(make_config(std::move(joint_names), std::move(joint_limits), std::move(actuator_names),
                                         transmissions, std::move(actuator_peak_forces), angle_margin_rad));
          },
          "joint_names"_a, "joint_limits"_a, "actuator_names"_a, "transmissions"_a, "actuator_peak_forces"_a,
          "angle_margin_rad"_a = 0.0)
      .def("step", &step, "actuator_position"_a, "actuator_velocity"_a, "position_rad"_a, "velocity_rad_s"_a,
           "stiffness"_a, "damping"_a, "torque_nm"_a)
      .def("joints_from_actuators",
           [](const Spine& spine, const Eigen::VectorXd& values) {
             return convert<&nova::rt::Coupling::joints_from_actuators>(spine, values, spine.joint_count());
           })
      .def("actuators_from_joints",
           [](const Spine& spine, const Eigen::VectorXd& values) {
             return convert<&nova::rt::Coupling::actuators_from_joints>(spine, values, spine.actuator_count());
           })
      .def("joint_torques_from_forces",
           [](const Spine& spine, const Eigen::VectorXd& values) {
             return convert<&nova::rt::Coupling::joint_torques_from_forces>(spine, values, spine.joint_count());
           })
      .def("forces_from_joint_torques",
           [](const Spine& spine, const Eigen::VectorXd& values) {
             return convert<&nova::rt::Coupling::forces_from_joint_torques>(spine, values, spine.actuator_count());
           })
      .def_prop_ro("joint_names", [](const Spine& spine) { return spine.config().joint_names; })
      .def_prop_ro("actuator_names", [](const Spine& spine) { return spine.config().actuator_names; })
      .def_prop_ro("joint_count", &Spine::joint_count)
      .def_prop_ro("actuator_count", &Spine::actuator_count)
      .def_prop_ro("groups", [](const Spine& spine) {
        std::vector<std::pair<std::vector<int>, std::vector<int>>> groups;
        for (const auto& group : spine.coupling().groups()) groups.emplace_back(group.actuators, group.joints);
        return groups;
      });
}
