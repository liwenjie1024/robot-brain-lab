# 实时分区（C++）：脊髓层。测试台（Python）经 nanobind 每 1 毫秒调用一次；以后在实时分区里直接跑。
# 在容器里编译、测试：docker compose run --rm rt
cmake_minimum_required(VERSION 3.26)
project(nova_rt LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(NOVA_RT_TESTS "编译 C++ 的测试（GoogleTest）" OFF)
option(NOVA_RT_PYTHON "编译给 Python 用的模块（nanobind）" OFF)

find_package(Eigen3 3.4 REQUIRED NO_MODULE)

add_library(nova_rt STATIC src/coupling.cpp src/limits.cpp src/spine.cpp)
target_include_directories(nova_rt PUBLIC include)
target_link_libraries(nova_rt PUBLIC Eigen3::Eigen)
target_compile_options(nova_rt PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Werror)

if(NOVA_RT_TESTS)
  enable_testing()
  find_package(GTest REQUIRED)
  add_executable(nova_rt_tests tests/test_coupling.cpp tests/test_limits.cpp tests/test_spine.cpp)
  target_link_libraries(nova_rt_tests PRIVATE nova_rt GTest::gtest_main)
  target_compile_options(nova_rt_tests PRIVATE -Wall -Wextra -Werror)
  include(GoogleTest)
  gtest_discover_tests(nova_rt_tests)
endif()

if(NOVA_RT_PYTHON)
  find_package(Python 3.13 COMPONENTS Interpreter Development.Module REQUIRED)
  execute_process(
    COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
    OUTPUT_STRIP_TRAILING_WHITESPACE
    OUTPUT_VARIABLE nanobind_ROOT
    COMMAND_ERROR_IS_FATAL ANY
  )
  find_package(nanobind CONFIG REQUIRED)
  nanobind_add_module(_core NB_STATIC python/module.cpp)
  target_link_libraries(_core PRIVATE nova_rt)
  install(TARGETS _core LIBRARY DESTINATION nova_rt)
endif()
