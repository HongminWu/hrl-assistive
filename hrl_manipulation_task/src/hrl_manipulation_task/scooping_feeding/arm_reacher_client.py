#!/usr/bin/env python

# system library
import time
import datetime

# ROS library
import rospy
import roslib
roslib.load_manifest('hrl_manipulation_task')

# HRL library
## from hrl_srvs.srv import None_Bool, None_BoolResponse
from hrl_srvs.srv import String_String
import hrl_lib.util as ut


if __name__ == '__main__':

    rospy.init_node('feed_client')

    rospy.wait_for_service("/arm_reach_enable")
    armReachActionLeft  = rospy.ServiceProxy("/arm_reach_enable", String_String)
    armReachActionRight = rospy.ServiceProxy("/right/arm_reach_enable", String_String)
    #armMovements = rospy.ServiceProxy("/arm_reach_enable", None_Bool)

    ## TEST -----------------------------------    
    # TODO: this code should be run in parallel.
    #print armReachActionLeft("getBowlPos")
    ## print armReachActionLeft("test_debug")
    ## print armReachActionLeft("test_orient")
    ## print armReachActionRight("test_orient")

    ## Testing ------------------------------------
    # This setcion is sued to test the new end effector.
    ## print armReachActionLeft("test_pos")
    ## print armReachActionRight("test_pos")

    ## print armReachActionLeft("testingMotion")
    ## print armReachActionRight("testingMotion")
    ## Scooping -----------------------------------    
    ## print "Initializing left arm for scooping"
    ## print armReachActionLeft("initScooping")
    ## print armReachActionRight("initScooping")
    ## print armReachAction("getBowlPos")
    #ut.get_keystroke('Hit a key to proceed next')        

    ##print "Running scooping!"
    ## print armReachActionLeft("runScooping")
    
    ## time.sleep(2.0)    


    ## ## Feeding -----------------------------------
    ## print "Initializing left arm for feeding"
    ## print armReachActionLeft("initFeeding")
    print armReachActionLeft("getHeadPos")
    print armReachActionLeft("runFeeding")

    ## print armReachAction("chooseManualHeadPos")

    ## print 'Initializing feeding'
    ## print armReachAction('initArmFeeding')
    ## time.sleep(2.0)    
    ## ## ut.get_keystroke('Hit a key to proceed next')        

    ## print "Running feeding!"
    ## print armReachAction("runFeeding")
    







    ## t1 = datetime.datetime.now()
    ## t2 = datetime.datetime.now()
    ## t  = t2-t1
    ## print "time delay: ", t.seconds
    
