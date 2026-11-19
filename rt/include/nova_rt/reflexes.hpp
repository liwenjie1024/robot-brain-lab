#pragma once

// 脊髓层的反射（系统结构第 2 节"脊髓层的反射"，全部每 1 毫秒，不经过 AI）。核心里的四种：
// - 保护：驱动器的绕组热了，先把它能出的力降下来（比驱动器自己降额早），并且告诉小脑层；
// - 碰撞：身体的一段被碰到（皮肤受力），带着它的关节变软，碰完了等一会儿再慢慢恢复；
// - 跌倒：身体歪到救不回来，全身变软、顶住现在的姿势（以后换成学出来的保护性摔倒，P2 的 2.6 步）；
// - 停止：0 类（马上断力，只留刹车的阻尼）、2 类（受控停下、不断电：交给小脑层停下来站住，这里只标出来），
//   1 类（受控停下再断电：先像 2 类，"慢慢坐下"等 2.6 步）。停止一直留着，直到重新开始。
// 反射放在小脑层的命令和硬限制之间：先改命令，再由 Spine 守住硬限制。

#include <Eigen/Dense>
#include <cstdint>
#include <vector>

#include "nova_rt/spine.hpp"

namespace nova::rt {

enum ReflexFlag : std::uint8_t {
  kReflexProtect = 1U << 0U,    // 带着它的驱动器热了，能出的力降下来了
  kReflexCollision = 1U << 1U,  // 被碰到，变软了
  kReflexFall = 1U << 2U,       // 在摔倒
  kReflexStop = 1U << 3U,       // 在停止
};

enum class StopCategory : int { kNone = -1, kCategory0 = 0, kCategory1 = 1, kCategory2 = 2 };

enum class ReflexMode : int { kNormal = 0, kFalling = 1, kStopping = 2, kPowerOff = 3 };

struct ReflexConfig {
  int joint_count = 0;
  // 每个驱动器带着哪几个关节（降额的标记要标到这些关节上）。
  std::vector<std::vector<int>> actuator_joints;
  // 保护：绕组到 warn 开始降，到 hot 降到 hot_force_share，再热也不再往下降（驱动器自己的降额兜底）。
  double warn_temperature_c = 90.0;
  double hot_temperature_c = 110.0;
  double hot_force_share = 0.5;
  // 碰撞：变软到这么多；碰完以后先等 hold，再用 recovery 慢慢恢复。
  double collision_stiffness_share = 0.2;
  double collision_hold_s = 0.5;
  double collision_recovery_s = 0.5;
  // 跌倒：歪过 fall_tilt，或者歪过 warning_tilt 并且还在以 fall_tilt_rate 往下倒，就算救不回来了。
  double fall_tilt_rad = 0.70;
  double fall_warning_tilt_rad = 0.44;
  double fall_tilt_rate_rad_s = 1.5;
  double fall_stiffness_share = 0.3;
  // 歪斜的变化率先低通滤一下（时间常数），免得一下读数的抖动就当成在倒。
  double tilt_rate_filter_s = 0.02;
  // 0 类停止时每个关节的刹车阻尼（驱动器短路制动，N·m·s/rad）。
  std::vector<double> brake_damping;
};

struct ReflexInput {
  double tilt_rad = 0.0;                     // 身体歪了多少（状态估计给的）
  Eigen::VectorXd actuator_temperature_c;    // 每个驱动器的绕组温度；不知道的给 NaN（不降额）
  std::vector<bool> joint_contact;           // 每个关节带着的那一段被碰到没有
  StopCategory stop = StopCategory::kNone;
};

struct ReflexOutput {
  JointCommand command;
  Eigen::VectorXd actuator_force_scale;  // 每个驱动器能出的力的比例（交给 Spine 的力的上限）
  std::vector<std::uint8_t> flags;       // 每个关节被哪几种反射改过（ReflexFlag 的位）
  ReflexMode mode = ReflexMode::kNormal;
  double tilt_rate_rad_s = 0.0;          // 滤过的歪斜的变化率
};

class Reflexes {
 public:
  // 配置不对（个数、比例不在 0~1、温度反了……）抛 std::invalid_argument。
  explicit Reflexes(ReflexConfig config);

  // 一步（dt 秒）：改命令、算每个驱动器的力的比例、报告模式。joint_position 是现在关节的角度（停止、跌倒时顶住它）。
  const ReflexOutput& step(const JointCommand& command, const Eigen::VectorXd& joint_position,
                           const ReflexInput& input, double dt);

  // 重新开始：跌倒、停止都清掉，碰撞的计时也清零。
  void reset();

  ReflexMode mode() const { return output_.mode; }

 private:
  void check(const JointCommand& command, const Eigen::VectorXd& joint_position, const ReflexInput& input,
             double dt) const;
  void protect(const ReflexInput& input);
  void soften_collisions(const ReflexInput& input, double dt);
  void update_fall(double tilt_rad, double dt);
  void latch(const Eigen::VectorXd& joint_position);
  void apply_mode(const Eigen::VectorXd& joint_position);

  ReflexConfig config_;
  int actuator_count_ = 0;
  ReflexOutput output_;
  Eigen::VectorXd since_contact_s_;   // 每个关节离上一次被碰到多久了（没碰过是无穷大）
  Eigen::VectorXd held_position_rad_; // 停止、跌倒那一刻的角度
  StopCategory latched_stop_ = StopCategory::kNone;
  bool falling_ = false;
  bool has_tilt_ = false;
  double last_tilt_rad_ = 0.0;
};

}  // namespace nova::rt
