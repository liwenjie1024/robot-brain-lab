#pragma once

// 状态估计（脊髓层的一部分，AI 模型第 1 节）：身体（骨盆上那个 IMU）在哪、多快、朝哪。
//
// 用的是带接触的右不变扩展卡尔曼滤波（contact-aided InEKF，Hartley 等，2018/2020）：
// - 每 1 毫秒用 IMU 的角速度、加速度往前推（扣掉估出来的零偏）；
// - 着地的脚上的一点当作在地上不动：腿的运动学（关节的角度）给出它在 IMU 坐标里的位置，拿来纠正。
// 误差用右不变的定义：转动、速度、位置、着地点这几样的误差方程和现在的状态无关（零偏那几列除外），
// 所以比一般的 EKF 稳，转得多、走得久也不容易发散。
// 绝对的位置和朝向（偏航）看不出来，会慢慢漂；以后由视觉惯性里程计纠正。

#include <Eigen/Dense>
#include <vector>

namespace nova::rt {

struct EstimatorConfig {
  int contact_count = 2;  // 能着地的点有几个（两只脚）
  // 噪声（连续时间的密度）。
  double gyro_noise = 0.0;           // rad/s/√Hz
  double accel_noise = 0.0;          // m/s²/√Hz
  double gyro_bias_walk = 0.0;       // rad/s²/√Hz：零偏慢慢变
  double accel_bias_walk = 0.0;      // m/s³/√Hz
  double contact_noise = 0.0;        // m/s/√Hz：着地的点也会稍微滑一点
  double kinematics_noise_m = 0.0;   // 腿的运动学算出来的脚的位置差多少（标准差）
  Eigen::Vector3d gravity{0.0, 0.0, -9.81};
  // 一开始有多不确定（标准差）。
  double initial_rotation_rad = 0.0;
  double initial_velocity_m_s = 0.0;
  double initial_position_m = 0.0;
  double initial_gyro_bias_rad_s = 0.0;
  double initial_accel_bias_m_s2 = 0.0;
};

// 一个能着地的点这一刻的样子：着没着地，在 IMU 坐标里在哪（腿的运动学算的）。
struct ContactMeasurement {
  bool in_contact = false;
  Eigen::Vector3d position_m = Eigen::Vector3d::Zero();
};

class Estimator {
 public:
  // 配置不对（噪声是负的或者不是数、着地点的个数不对）抛 std::invalid_argument。
  explicit Estimator(EstimatorConfig config);

  // 从一个已知的状态开始（真机上：开机时站着不动，转动按重力定，位置、偏航定成 0）。零偏从 0 开始。
  void reset(const Eigen::Matrix3d& rotation, const Eigen::Vector3d& velocity, const Eigen::Vector3d& position);

  // 往前推 dt 秒：gyro 是 IMU 量到的角速度（rad/s），accel 是量到的比力（m/s²，站着不动时是向上的 9.81）。
  void propagate(const Eigen::Vector3d& gyro, const Eigen::Vector3d& accel, double dt);

  // 每个能着地的点这一刻的样子（个数要等于 contact_count）。刚着地的点记下它在世界里的位置；
  // 一直着地的拿来纠正；抬起来的不再用。
  void correct(const std::vector<ContactMeasurement>& contacts);

  const Eigen::Matrix3d& rotation() const { return rotation_; }
  const Eigen::Vector3d& velocity() const { return velocity_; }
  const Eigen::Vector3d& position() const { return position_; }
  const Eigen::Vector3d& gyro_bias() const { return gyro_bias_; }
  const Eigen::Vector3d& accel_bias() const { return accel_bias_; }
  const Eigen::Vector3d& contact_position(int contact) const;
  bool contact_active(int contact) const;
  const Eigen::MatrixXd& covariance() const { return covariance_; }
  int state_size() const { return size_; }

 private:
  int contact_index(int contact) const { return 9 + 3 * contact; }
  int gyro_bias_index() const { return 9 + 3 * config_.contact_count; }
  int accel_bias_index() const { return 12 + 3 * config_.contact_count; }
  void activate(int contact, const Eigen::Vector3d& measured);
  void deactivate(int contact);
  void update(int contact, const Eigen::Vector3d& measured);
  void apply_correction(const Eigen::VectorXd& correction);

  EstimatorConfig config_;
  int size_ = 0;
  Eigen::Matrix3d rotation_ = Eigen::Matrix3d::Identity();
  Eigen::Vector3d velocity_ = Eigen::Vector3d::Zero();
  Eigen::Vector3d position_ = Eigen::Vector3d::Zero();
  Eigen::Vector3d gyro_bias_ = Eigen::Vector3d::Zero();
  Eigen::Vector3d accel_bias_ = Eigen::Vector3d::Zero();
  std::vector<Eigen::Vector3d> contacts_;
  std::vector<bool> active_;
  Eigen::MatrixXd covariance_;
  // 每一步都要用的，先分配好。
  Eigen::MatrixXd transition_;
  Eigen::MatrixXd noise_map_;
  Eigen::MatrixXd noise_;
  Eigen::MatrixXd scratch_;
  Eigen::MatrixXd gain_;
  Eigen::MatrixXd gain_transpose_scratch_;
  Eigen::VectorXd correction_;
};

}  // namespace nova::rt
