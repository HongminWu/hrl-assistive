#!/usr/bin/env python
#
# Copyright (c) 2014, Georgia Tech Research Corporation
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the Georgia Tech Research Corporation nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY GEORGIA TECH RESEARCH CORPORATION ''AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL GEORGIA TECH BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

#  \author Daehyung Park (Healthcare Robotics Lab, Georgia Tech.)

# system library
import time
import datetime

# ROS library
import rospy, roslib
roslib.load_manifest('hrl_manipulation_task')

# HRL library
from hrl_srvs.srv import String_String
import hrl_lib.util as ut

from hrl_manipulation_task.record_data import logger


def scooping(armReachActionLeft, armReachActionRight, log, detection_flag):

    log.task = 'scooping'
    log.initParams()
    
    ## Scooping -----------------------------------    
    print "Initializing left arm for scooping"
    print armReachActionRight("initScooping")
    
    #ut.get_keystroke('Hit a key to proceed next')        
    print armReachActionLeft("getBowlPos")
    print armReachActionLeft('lookAtBowl')
    print armReachActionLeft("initScooping")
        
    print "Start to log!"    
    log.log_start()
    if detection_flag: log.enableDetector(True)
    
    print "Running scooping!"
    print armReachActionLeft("runScooping")

    if detection_flag: log.enableDetector(False)
    print "Finish to log!"    
    log.close_log_file()

    
def feeding(armReachActionLeft, armReachActionRight, log, detection_flag):

    log.task = 'feeding'
    log.initParams()
    
    ## Feeding -----------------------------------
    print "Initializing left arm for feeding"
    #print armReachActionRight("initFeeding")
    print armReachActionLeft("initFeeding")

    print "Detect ar tag on the head"
    print armReachActionLeft('lookAtMouth')
    print armReachActionLeft("getHeadPos")
    #ut.get_keystroke('Hit a key to proceed next')        

    print "Running feeding1"    
    print armReachActionLeft("runFeeding1")
    
    print "Start to log!"    
    log.log_start()
    if detection_flag: log.enableDetector(True)
    
    print "Running feeding2"    
    print armReachActionLeft("runFeeding2")

    if detection_flag: log.enableDetector(False)
    print "Finish to log!"    
    log.close_log_file()
    
    
if __name__ == '__main__':
    
    import optparse
    p = optparse.OptionParser()
    p.add_option('--data_pub', '--dp', action='store_true', dest='bDataPub',
                 default=False, help='Continuously publish data.')
    opt, args = p.parse_args()

    rospy.init_node('arm_reach_client')

    rospy.wait_for_service("/arm_reach_enable")
    armReachActionLeft  = rospy.ServiceProxy("/arm_reach_enable", String_String)
    armReachActionRight = rospy.ServiceProxy("/right/arm_reach_enable", String_String)

    log = logger(ft=True, audio=True, kinematics=True, vision=True, pps=True, skin=True, \
                 subject="gatsbii", task='feeding', data_pub=opt.bDataPub, verbose=False)

    last_trial  = '4'
    last_detect = '2'
                 
    while not rospy.is_shutdown():

        detection_flag = False
        
        trial  = raw_input('Enter trial\'s status (e.g. 1:scooping, 2:feeding, 3: both else: exit): ')
        if trial=='': trial=last_trial
            
        if trial is '1' or trial is '2' or trial is '3':
            detect = raw_input('Enable anomaly detection? (e.g. 1:enable else: disable): ')
            if detect == '': detect=last_detect
            if detect == '1': detection_flag = True
            
            if trial == '1':
                scooping(armReachActionLeft, armReachActionRight, log, detection_flag)
            elif trial == '2':
                feeding(armReachActionLeft, armReachActionRight, log, detection_flag)
            else:
                scooping(armReachActionLeft, armReachActionRight, log, detection_flag)
                feeding(armReachActionLeft, armReachActionRight, log, detection_flag)
        else:
            break

        last_trial  = trial
        last_detect = detect
    
    ## t1 = datetime.datetime.now()
    ## t2 = datetime.datetime.now()
    ## t  = t2-t1
    ## print "time delay: ", t.seconds
    
