cmake_minimum_required(VERSION 2.8.3)
project(hrl_pose_estimation)

find_package(catkin REQUIRED COMPONENTS rospy roscpp std_msgs geometry_msgs tf tf_conversions hrl_lib hrl_msgs sensor_msgs visualization_msgs trajectory_msgs message_generation)

catkin_python_setup()

generate_messages(
    DEPENDENCIES geometry_msgs std_msgs sensor_msgs
)

catkin_package(
    DEPENDS 
    CATKIN_DEPENDS rospy roscpp std_msgs geometry_msgs tf tf_conversions hrl_lib hrl_msgs sensor_msgs visualization_msgs trajectory_msgs message_runtime
    INCLUDE_DIRS # TODO include
    LIBRARIES # TODO
)

#catkin_install_python(PROGRAMS scripts/executable1 
#    DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}) 

