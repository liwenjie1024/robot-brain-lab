cmake_minimum_required(VERSION 3.20)
project(bl01_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/WeaponStatus.msg"
  "msg/GuardStatus.msg"
  "msg/MechaStatus.msg"
  "msg/UnitStatus.msg"
  "msg/Threat.msg"
  "msg/State.msg"
  "msg/CombatEvent.msg"
  "srv/SetVelocity.srv"
  "srv/Stop.srv"
  "srv/Aim.srv"
  "srv/AimPoint.srv"
  "srv/LowerAim.srv"
  "srv/Guard.srv"
  "srv/Fire.srv"
  "srv/Push.srv"
  "srv/Reset.srv"
  "srv/GetScene.srv"
  DEPENDENCIES geometry_msgs std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
