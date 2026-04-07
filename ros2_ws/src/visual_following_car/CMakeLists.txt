cmake_minimum_required(VERSION 3.8)
project(visual_following_car)

#
# 这个包当前使用 ament_python 作为主要构建方式，
# 因此 CMakeLists.txt 只保留一个极简版本即可。
#
# 它的作用主要是：
# 1. 让 ROS 2 / colcon 能识别这是一个标准 ament 包。
# 2. 为未来扩展 C++ 节点、原生扩展模块或自定义消息预留入口。
#

find_package(ament_cmake REQUIRED)

ament_package()