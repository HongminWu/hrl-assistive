#!/bin/bash

# Generate dae from URDF
#rosrun collada_urdf urdf_to_collada ./urdf/bed_and_body_v2/robots/bed_and_body_v2_low_res.URDF ./collada/bed_and_body_v2_low_res.dae 

# If joint axes/anchors have pretty big decmials, round off those (using moveit_ikfast's script).
#rosrun hrl_gazebo_darci round_collada_numbers.py ./collada/bed_and_body_v2_low_res.dae ./collada/bed_and_body_v2_low_res_rounded.dae 3

# Generate dae from URDF
#rosrun collada_urdf urdf_to_collada ./urdf/wheelchair_and_body_assembly/robots/wheelchair_and_body_assembly.URDF ./collada/wheelchair_and_body_assembly.dae 
#rosrun collada_urdf urdf_to_collada ./urdf/bed_and_body_v3/robots/bed_and_body_v3.URDF ./collada/bed_and_body_v3.dae 
rosrun collada_urdf urdf_to_collada ./urdf/bed_and_body_v3_nowall/robots/bed_and_body_v3_nowall.URDF ./collada/bed_and_body_v3_nowall.dae 

# If joint axes/anchors have pretty big decmials, round off those (using moveit_ikfast's script).
#rosrun hrl_gazebo_darci round_collada_numbers.py ./collada/wheelchair_and_body_assembly.dae ./collada/wheelchair_and_body_assembly.dae 3
#rosrun hrl_gazebo_darci round_collada_numbers.py ./collada/bed_and_body_v3.dae ./collada/bed_and_body_v3_rounded.dae 3
rosrun hrl_gazebo_darci round_collada_numbers.py ./collada/bed_and_body_v3_nowall.dae ./collada/bed_and_body_v3_nowall_rounded.dae 3


# Generate dae from URDF
#rosrun collada_urdf urdf_to_collada ./urdf/wheelchair_best/robots/wheelchair_best.URDF ./collada/wheelchair.dae 

# If joint axes/anchors have pretty big decmials, round off those (using moveit_ikfast's script).
#rosrun hrl_gazebo_darci round_collada_numbers.py ./collada/wheelchair.dae ./collada/wheelchair_rounded.dae 3
