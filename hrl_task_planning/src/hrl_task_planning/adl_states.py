#!/usr/bin/env python

from collections import deque

import rospy, rosparam, rospkg, roslib
import actionlib
from threading import RLock
import math as m
import rospy, rosparam, rospkg, roslib
from hrl_msgs.msg import FloatArrayBare
from std_msgs.msg import String, Int32, Int8, Bool
from actionlib_msgs.msg import GoalStatus
# from actionlib_msgs.msg import GoalStatus as GS
from geometry_msgs.msg import PoseStamped
import tf
import numpy as np
from hrl_task_planning.msg import PDDLState
from hrl_pr2_ar_servo.msg import ARServoGoalData
from hrl_base_selection.srv import BaseMove
from hrl_srvs.srv import None_Bool, None_BoolResponse
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from pr2_controllers_msgs.msg import SingleJointPositionActionGoal, SingleJointPositionAction, SingleJointPositionGoal
from hrl_haptic_manipulation_in_clutter_srvs.srv import EnableHapticMPC
roslib.load_manifest('hrl_lib')
import hrl_lib.util as utils
# pylint: disable=W0102
from task_smacher import PDDLSmachState
from hrl_task_planning.pddl_utils import PlanStep, State, GoalState, Predicate

SPA = ["succeeded", "preempted", "aborted"]


def get_action_state(domain, problem, action, args, init_state, goal_state):
    if action == 'FIND_TAG':
        return FindTagState(domain=domain, model=args[0], problem=problem,
                            action=action, action_args=args,
                            init_state=init_state, goal_state=goal_state,
                            outcomes=SPA)
    if action == 'TRACK_TAG':
        return TrackTagState(domain=domain, model=args[0], problem=problem,
                             action=action, action_args=args,
                             init_state=init_state, goal_state=goal_state,
                             outcomes=SPA)
    elif action == 'CONFIGURE_MODEL_ROBOT':
        return ConfigureModelRobotState(domain=domain, task=args[0], model=args[1], problem=problem,
                                        action=action, action_args=args,
                                        init_state=init_state, goal_state=goal_state,
                                        outcomes=SPA)
    elif action == 'CHECK_OCCUPANCY':
        return CheckOccupancyState(domain=domain, model=args[0], problem=problem,
                                   action=action, action_args=args, init_state=init_state,
                                   goal_state=goal_state, outcomes=SPA)
    elif action == 'REGISTER_HEAD':
        return RegisterHeadState(domain=domain, model=args[0], problem=problem,
                                 action=action, action_args=args, init_state=init_state,
                                 goal_state=goal_state, outcomes=SPA)
    elif action == 'CALL_BASE_SELECTION':
        return CallBaseSelectionState(task=args[0], model=args[1], domain=domain, problem=problem,
                                      action=action, action_args=args, init_state=init_state,
                                      goal_state=goal_state, outcomes=SPA)
    elif action == 'MOVE_ROBOT':
        return MoveRobotState(domain=domain, task=args[0], model=args[1], problem=problem, action=action, action_args=args, init_state=init_state, goal_state=goal_state, outcomes=SPA)
    elif action == 'STOP_TRACKING':
        return StopTrackingState(domain=domain, problem=problem, action=action, action_args=args, init_state=init_state, goal_state=goal_state, outcomes=SPA)
    elif action == 'MOVE_ARM':
        return MoveArmState(task=args[0], model=args[1], domain=domain, problem=problem, action=action, action_args=args, init_state=init_state, goal_state=goal_state, outcomes=SPA)
    elif action == 'MOVE_BACK':
        return PDDLSmachState(domain=domain, problem=problem, action=action, action_args=args, init_state=init_state, goal_state=goal_state, outcomes=SPA)
    elif action == 'DO_TASK':
        return PDDLSmachState(domain=domain, problem=problem, action=action, action_args=args, init_state=init_state, goal_state=goal_state, outcomes=SPA)


class FindTagState(PDDLSmachState):
    def __init__(self, model, domain, *args, **kwargs):
        super(FindTagState, self).__init__(domain=domain, *args, **kwargs)
        self.start_finding_AR_publisher = rospy.Publisher('find_AR_now', Bool, queue_size=1)
        self.state_pub = rospy.Publisher('/pddl_tasks/state_updates', PDDLState, queue_size=10)
        self.domain = domain
        self.ar_tag_found = False
        rospy.Subscriber('AR_acquired', Bool, self.found_ar_tag_cb)
        self.model = model

    def on_execute(self, ud):
        rospy.sleep(1.)
        rospy.loginfo("[%s] Start Looking For Tag" % rospy.get_name())
        self.start_finding_AR_publisher.publish(True)
        rospy.sleep(1.)
        rospy.loginfo("[%s] Waiting to see if tag found" % rospy.get_name())
        while not rospy.is_shutdown() and not self.ar_tag_found:
            if self.preempt_requested():
                rospy.loginfo("[%s] Cancelling action." % rospy.get_name())
                return 
            rospy.sleep(1)

        if self.ar_tag_found:
            print "Tag FOUND"
            rospy.loginfo("AR Tag Found")
            state_update = PDDLState()
            state_update.domain = self.domain
            state_update.predicates = ['(FOUND-TAG %s)' % self.model]
            print "Publishing (FOUND-TAG) update"
            self.state_pub.publish(state_update)
        else:
            rospy.logwarn('[%s] Something went wrong in finding AR Tag. Tag not found' % rospy.get_name())
            return 'aborted'
        return

    def found_ar_tag_cb(self, msg):
        if msg.data:
            self.ar_tag_found = True
        else:
            self.ar_tag_found = False


class TrackTagState(PDDLSmachState):
    def __init__(self, model, domain, *args, **kwargs):
        super(TrackTagState, self).__init__(domain=domain, *args, **kwargs)
        self.start_tracking_AR_publisher = rospy.Publisher('track_AR_now', Bool, queue_size=1)
        self.model = model

    def on_execute(self, ud):
        rospy.sleep(1.)
        rospy.loginfo('[%s] Starting AR Tag Tracking' % rospy.get_name())
        self.start_tracking_AR_publisher.publish(True)


class StopTrackingState(PDDLSmachState):
    def __init__(self, domain, *args, **kwargs):
        super(StopTrackingState, self).__init__(domain=domain, *args, **kwargs)
        self.stop_tracking_AR_publisher = rospy.Publisher('track_AR_now', Bool, queue_size=1)

    def on_execute(self, ud):
        rospy.sleep(1.)
        rospy.loginfo('[%s] Stopping AR Tag Tracking' % rospy.get_name())
        self.stop_tracking_AR_publisher.publish(False)


class RegisterHeadState(PDDLSmachState):
    def __init__(self, model, domain, *args, **kwargs):
        super(RegisterHeadState, self).__init__(domain=domain, *args, **kwargs)
        self.listener = tf.TransformListener()
        self.state_pub = rospy.Publisher('/pddl_tasks/state_updates', PDDLState, queue_size=10)
        self.model = model
        print "Looking for head of person on: %s" % model

    def on_execute(self, ud):
        rospy.sleep(1.)
        print 'Trying to find head now'
        if self.model.upper() == "AUTOBED":
            #print 'model is autobed'
            head_registered = self.get_head_pose()
            #print 'head registered is', head_registered
        elif self.model.upper() == "WHEELCHAIR":
            head_registered = True
        if head_registered:
            print "Head Found."
            state_update = PDDLState()
            state_update.domain = self.domain
            state_update.predicates = ['(HEAD-REGISTERED %s)' % self.model]
            print "Publishing (HEAD-REGISTERED) update"
            self.state_pub.publish(state_update)
        else:
            print "Head NOT Found"
            return 'aborted'

    def get_head_pose(self, head_frame="/user_head_link"):
        try:
            #now = rospy.Time.now()
            print "[%s] Register Head State trying to get Head Transform" % rospy.get_name()
            # self.listener.waitForTransform("/base_link", head_frame, rospy.Time(0), rospy.Duration(5))
            pos, quat = self.listener.lookupTransform("/autobed/base_link", head_frame, rospy.Time(0))
            return True
        except Exception as e:
            rospy.loginfo("TF Exception:\r\n%s" %e)
            return False


class CheckOccupancyState(PDDLSmachState):
    def __init__(self, model, domain, *args, **kwargs):
        super(CheckOccupancyState, self).__init__(domain=domain, *args, **kwargs)
        self.model = model
        self.state_pub = rospy.Publisher('/pddl_tasks/state_updates', PDDLState, queue_size=1)
#        print "Check Occupancy of Model: %s" % model
        if model.upper() == 'AUTOBED':
            self.autobed_occupied_status = False
            print "[%s] Check Occupancy Waiting for Service to exist" % rospy.get_name()
            try:
                rospy.wait_for_service('autobed_occ_status', timeout=5)
                self.AutobedOcc = rospy.ServiceProxy('autobed_occ_status', None_Bool)
            except:
                rospy.logwarn('[%s] Pressure Mat Not Running On the Autobed' % rospy.get_name())
                return 'aborted'
        else:
            self.autobed_occupied_status = True

    def on_execute(self, ud):
        rospy.sleep(1.)
        if self.model.upper() == 'AUTOBED':
            # print "[%s] Check Occupancy State Waiting for Service" % rospy.get_name()
            # try:
            #     rospy.wait_for_service('autobed_occ_status', timeout=5)
            # except:
            #     rospy.logwarn('[%s] Pressure Mat Not Running On the Autobed' % rospy.get_name())
            #     return 'aborted'
            try:
                # self.AutobedOcc = rospy.ServiceProxy('autobed_occ_status', None_Bool)
                self.autobed_occupied_status = self.AutobedOcc().data
            except rospy.ServiceException, e:
                print "Check Occupancy Service call failed: %s" % e
                return 'aborted'

            if self.autobed_occupied_status:
                state_update = PDDLState()
                state_update.domain = self.domain
                state_update.predicates = ['(OCCUPIED %s)' % self.model]
                self.state_pub.publish(state_update)
                # self.goal_reached = False
            else:
                # self.goal_reached = False
                return 'aborted'
        else:
            state_update = PDDLState()
            state_update.domain = self.domain
            state_update.predicates = ['(OCCUPIED %s)' % self.model]
            self.state_pub.publish(state_update)
            # self.goal_reached = False


class MoveArmState(PDDLSmachState):
    def __init__(self, task, model, domain, *args, **kwargs):
        super(MoveArmState, self).__init__(domain=domain, *args, **kwargs)
        rospy.wait_for_service('/left_arm/haptic_mpc/enable_mpc')
        self.mpc_enabled_service = rospy.ServiceProxy("/left_arm/haptic_mpc/enable_mpc", EnableHapticMPC)
        self.listener = tf.TransformListener()
        self.goal_position = None
        self.goal_orientation = None
        self.reference_frame = None
        self.l_arm_pose_pub = rospy.Publisher('/left_arm/haptic_mpc/goal_pose', PoseStamped, queue_size=1)
        rospy.Subscriber('/left_arm/haptic_mpc/goal_pose', PoseStamped, self.goal_pose_cb)
        self.ignore_next_goal_pose = False
        self.domain = domain
        self.task = task
        self.model = model
        self.goal_reached = False
        self.skip_arm_movement = False
        self.state_pub = rospy.Publisher('/pddl_tasks/state_updates', PDDLState, queue_size=10)
        rospy.Subscriber("/left_arm/haptic_mpc/in_deadzone", Bool, self.arm_reach_goal_cb)
        self.stop_tracking_AR_publisher = rospy.Publisher('track_AR_now', Bool, queue_size=1)

    def goal_pose_cb(self, msg):
        if not self.ignore_next_goal_pose:
            self.goal_reached = True
        else:
            self.ignore_next_goal_pose = False
    
    def arm_reach_goal_cb(self, msg):
        self.goal_reached = msg.data

    def publish_goal(self):
        goal = PoseStamped()
        if self.model.upper() == 'AUTOBED':
            if self.task.upper() == 'SCRATCHING' or self.task.upper() == 'BLANKET' or self.task.upper() == 'BATHING':
                self.goal_position = [0.28, 0, -0.1]
                self.goal_orientation = [0.,   0.,   1., 0.]
                self.reference_frame = '/'+str(self.model.lower())+'/knee_left_link'
                goal.pose.position.x = self.goal_position[0]
                goal.pose.position.y = self.goal_position[1]
                goal.pose.position.z = self.goal_position[2]
                goal.pose.orientation.x = self.goal_orientation[0]
                goal.pose.orientation.y = self.goal_orientation[1]
                goal.pose.orientation.z = self.goal_orientation[2]
                goal.pose.orientation.w = self.goal_orientation[3]
                goal.header.frame_id = self.reference_frame
                rospy.loginfo('[%s] Reaching to left knee.' % rospy.get_name())
                self.ignore_next_goal_pose = True
                self.l_arm_pose_pub.publish(goal)
            elif self.task.upper() == 'FEEDING' or self.task.upper() == 'SHAVING':
                self.goal_position = [0.25, 0., -0.1]
                self.goal_orientation = [0., 0., 1., 0.]
                self.reference_frame = '/'+str(self.model.lower())+'/head_link'
                goal.pose.position.x = self.goal_position[0]
                goal.pose.position.y = self.goal_position[1]
                goal.pose.position.z = self.goal_position[2]
                goal.pose.orientation.x = self.goal_orientation[0]
                goal.pose.orientation.y = self.goal_orientation[1]
                goal.pose.orientation.z = self.goal_orientation[2]
                goal.pose.orientation.w = self.goal_orientation[3]
                goal.header.frame_id = self.reference_frame
                rospy.loginfo('[%s] Reaching to head.' % rospy.get_name())
                self.ignore_next_goal_pose = True
                self.l_arm_pose_pub.publish(goal)
            elif self.task.upper() == 'DRESSING':
                current_position, current_orientation = self.listener.lookupTransform('/autobed/base_link',
                                                                                      '/base_link',
                                                                                      rospy.Time(0))
                if current_position[1] > 0:
                    self.reference_frame = '/' + str(self.model.lower()) + '/upper_arm_right_link'
                else:
                    self.reference_frame = '/' + str(self.model.lower()) + '/upper_arm_left_link'
                self.goal_position = [0.15, 0., -0.19]
                self.goal_orientation = [0., 0., 1., 0.]
                goal.pose.position.x = self.goal_position[0]
                goal.pose.position.y = self.goal_position[1]
                goal.pose.position.z = self.goal_position[2]
                goal.pose.orientation.x = self.goal_orientation[0]
                goal.pose.orientation.y = self.goal_orientation[1]
                goal.pose.orientation.z = self.goal_orientation[2]
                goal.pose.orientation.w = self.goal_orientation[3]
                goal.header.frame_id = self.reference_frame
                rospy.loginfo('[%s] Reaching to arm.' % rospy.get_name())
                self.ignore_next_goal_pose = True
                self.l_arm_pose_pub.publish(goal)
            elif self.task.upper() == 'WIPING_MOUTH' or self.task.upper() == 'FOREHEAD':
                # self.goal_position = [0.25, 0., -0.1]
                # self.goal_orientation = [0., 0., 1., 0.]
                # self.reference_frame = '/'+str(self.model.lower())+'/head_link'
                # goal.pose.position.x = self.goal_position[0]
                # goal.pose.position.y = self.goal_position[1]
                # goal.pose.position.z = self.goal_position[2]
                # goal.pose.orientation.x = self.goal_orientation[0]
                # goal.pose.orientation.y = self.goal_orientation[1]
                # goal.pose.orientation.z = self.goal_orientation[2]
                # goal.pose.orientation.w = self.goal_orientation[3]
                # goal.header.frame_id = self.reference_frame
                self.skip_arm_movement = True
                rospy.loginfo('[%s] Because of the complexity around the head, leaving all arm movement to the user.' % rospy.get_name())
            else:
                rospy.logwarn('[%s] Cannot Find ARM GOAL to reach. Have you specified the right task? [%s]' % (rospy.get_name(), self.task))
                return False
        elif self.model.upper() == 'WHEELCHAIR':
            if self.task.upper() == 'SCRATCHING':
                # THESE ARE NOT UPDATED to match self to the desired ones. self is copied from autobed values.
                self.goal_position = [0.45, 0., -0.07-0.05]
                self.goal_orientation = [0., 0., 1., 0.]
                self.reference_frame = '/'+str(self.model.lower())+'/calf_left_link'
                goal.pose.position.x = -0.06310556 - 0.02
                goal.pose.position.y = 0.07347758+0.05+0.03
                goal.pose.position.z = 0.00485197
                goal.pose.orientation.x = 0.48790861
                goal.pose.orientation.y = -0.50380292
                goal.pose.orientation.z = 0.51703901
                goal.pose.orientation.w = -0.4907122
                goal.header.frame_id = '/'+str(self.model.lower())+'/calf_left_link'
                rospy.loginfo('[%s] Reaching to left knee.' % rospy.get_name())
                self.ignore_next_goal_pose = True
                self.l_arm_pose_pub.publish(goal)
            elif self.task.upper() == 'WIPING_MOUTH':
                # THESE ARE NOT UPDATED
                self.goal_position = [0.45, 0., -0.07-0.05]
                self.goal_orientation = [0., 0., 1., 0.]
                self.reference_frame = '/'+str(self.model.lower())+'/head_link'
                goal.pose.position.x = 0.2
                goal.pose.position.y = 0.
                goal.pose.position.z = -0.0
                goal.pose.orientation.x = 0.
                goal.pose.orientation.y = 0.
                goal.pose.orientation.z = 1.
                goal.pose.orientation.w = 0.
                goal.header.frame_id = '/'+str(self.model.lower())+'/head_link'
                rospy.loginfo('[%s] Reaching to mouth.' % rospy.get_name())
                self.ignore_next_goal_pose = True
                self.l_arm_pose_pub.publish(goal)
            else:
                rospy.logwarn('[%s] Cannot Find ARM GOAL to reach. Have you specified the right task? [%s]' % (rospy.get_name(), self.task))
                return False
        return True

    def on_execute(self, ud):
        self.goal_reached = False
        self.skip_arm_movement = False
        rospy.sleep(1.)
        print 'Starting to execute arm movement'
        resp = self.mpc_enabled_service('enabled')
        rospy.sleep(0.5)
        publish_stat = self.publish_goal()
        self.goal_reached = False
        if not publish_stat:
            return 'aborted'
        #Now that goal is published, we wait until goal is reached
        movement_timer = rospy.Time.now()
        repeat_movement_timer = rospy.Time.now()
        while not rospy.is_shutdown() and not self.goal_reached and not self.skip_arm_movement:
            if self.preempt_requested():
                self.stop_tracking_AR_publisher.publish(False)
                rospy.loginfo("[%s] Cancelling action.", rospy.get_name())
                return
            current_position, current_orientation = self.listener.lookupTransform(self.reference_frame,'/l_gripper_tool_frame', rospy.Time(0))
            print 'distance to goal', np.linalg.norm(np.array(current_position) - np.array(self.goal_position))
            print 'angle to goal', utils.quat_angle(current_position, self.goal_orientation)
            if np.linalg.norm(np.array(current_position) - np.array(self.goal_position)) < 0.05 and utils.quat_angle(current_position, self.goal_orientation) < 10.0:
                self.goal_reached = True
            recent_movement_elapsed_time = rospy.Time.now() - repeat_movement_timer
            total_movement_elapsed_time = rospy.Time.now() - movement_timer
            if not self.goal_reached and recent_movement_elapsed_time.to_sec() > 3.0:
                repeat_movement_timer = rospy.Time.now()
                self.publish_goal()
            if total_movement_elapsed_time.to_sec() > 15.0:
                self.goal_reached = True
            rospy.sleep(1)
        if self.skip_arm_movement:
            rospy.loginfo("[%s] Arm Movement is being Skipped" % rospy.get_name())
            state_update = PDDLState()
            state_update.domain = self.domain
            state_update.predicates = ['(ARM-REACHED %s %s)' % (self.task, self.model)]
            print "Publishing (ARM-REACHED) update"
            self.state_pub.publish(state_update)
            return
        elif self.goal_reached:
            rospy.loginfo("[%s] Arm Goal Reached" % rospy.get_name())
            state_update = PDDLState()
            state_update.domain = self.domain
            state_update.predicates = ['(ARM-REACHED %s %s)' % (self.task, self.model)]
            print "Publishing (ARM-REACHED) update"
            self.state_pub.publish(state_update)
            return


class MoveBackState(PDDLSmachState):
    def __init__(self, model, domain, *args, **kwargs):
        super(MoveBackState, self).__init__(domain=domain, *args, **kwargs)
        self.model = model
        #self.domain_state_sub = rospy.Subscriber("/pddl_tasks/%s/state" % self.domain, PDDLState, self.domain_state_cb)
        self.stop_tracking_AR_publisher = rospy.Publisher('track_AR_now', Bool, queue_size=1)

    def domain_state_cb(self, state_msg):
        self.current_state = State(map(Predicate.from_string, state_msg.predicates))
        print "Init State: %s" % self.init_state
        print "Current State: %s" % self.current_state
        print "Goal State: %s" % self.goal_state
        print "\n\n"

    def _check_pddl_status(self):
        if self.preempt_requested():
            rospy.loginfo("[%s] Preempted requested for %s(%s).", rospy.get_name(), self.action, ' '.join(self.action_args))
            self.stop_tracking_AR_publisher.publish(False)
            return 'preempted'
        if self.goal_state.is_satisfied(self.current_state):
            return 'succeeded'
        progress = self.init_state.difference(self.current_state)
        for pred in progress:
            if pred not in self.state_delta:
                print "aborted - bad transition"
                return 'aborted'
        return None  # Adding explicitly for clarity

class MoveRobotState(PDDLSmachState):
    def __init__(self, task, model, domain, *args, **kwargs):
        super(MoveRobotState, self).__init__(domain=domain, *args, **kwargs)
        self.model = model
        self.task = task
        self.domain = domain
        self.goal_reached = False
        self.state_pub = rospy.Publisher('/pddl_tasks/state_updates', PDDLState, queue_size=10)
        self.servo_goal_pub = rospy.Publisher("ar_servo_goal_data", ARServoGoalData, queue_size=1)
        self.start_servoing = rospy.Publisher("/pr2_ar_servo/tag_confirm", Bool, queue_size=1)
        rospy.loginfo('[%s] Remember: The AR tag must be tracked before moving!' % rospy.get_name())
        self.stop_tracking_AR_publisher = rospy.Publisher('track_AR_now', Bool, queue_size=1)
        rospy.Subscriber('/pr2_ar_servo/state_feedback', Int8, self.base_servoing_cb)

    def base_servoing_cb(self, msg):
        if msg.data == 5:
            print 'Servo says it has reached the goal'
            self.goal_reached = True

    def on_execute(self, ud):
        rospy.sleep(1.)
        # Skip everything. Just say it is there. Do nothing else.
        self.stop_tracking_AR_publisher.publish(False)
        rospy.loginfo("[%s] Base Goal Reached" % rospy.get_name())
        state_update = PDDLState()
        state_update.domain = self.domain
        state_update.predicates = ['(BASE-REACHED %s %s)' % (self.task, self.model)]
        self.state_pub.publish(state_update)
        return

class CallBaseSelectionState(PDDLSmachState):
    def __init__(self, task, model, domain, *args, **kwargs):
        super(CallBaseSelectionState, self).__init__(domain=domain, *args, **kwargs)
        self.state_pub = rospy.Publisher('/pddl_tasks/state_updates', PDDLState, queue_size=10)
        print "Base Selection Called for task: %s and Model: %s" %(task, model)
        rospy.loginfo("[%s] Checking for base selection service. May wait up to 5 seconds." %rospy.get_name())

        self.domain = domain
        self.task = task
        self.model = model

    def call_base_selection(self):
        rospy.loginfo("[%s] Calling base selection. Please wait." %rospy.get_name())
        # try:
        #     rospy.wait_for_service("select_base_position", timeout=5)
        # except:
        #     rospy.logwarn("[%s] Is Base Selection Service Running?" % rospy.get_name())
        #     return 'aborted'
        # self.base_selection_client = rospy.ServiceProxy("select_base_position", BaseMove)

        if self.task.upper() == 'WIPING_MOUTH':
            local_task_name = 'wiping_mouth'
        elif self.task.upper() == 'SCRATCHING':
            local_task_name = 'scratching_knee_left'
        elif self.task.upper() == 'BLANKET':
            local_task_name = 'blanket_feet_knees'
        elif self.task.upper() == 'FOREHEAD':
            local_task_name = 'wiping_forehead'
        elif self.task.upper() == 'FEEDING':
            local_task_name = 'feeding_trajectory'
        elif self.task.upper() == 'BATHING':
            local_task_name = 'bathe_legs'
        elif self.task.upper() == 'DRESSING':
            local_task_name = 'arm_cuffs'
        elif self.task.upper() == 'SHAVING':
            local_task_name = 'shaving'

        if self.model.upper() == 'AUTOBED':
            try:
                self.model = 'autobed'
                resp = self.base_selection_client(local_task_name, self.model)
            except rospy.ServiceException as se:
                rospy.logerr(se)
                return [None, None]
        else:
            try:
                model = 'chair'
                resp = self.base_selection_client(local_task_name, model)
            except rospy.ServiceException as se:
                rospy.logerr(se)
                return [None, None]
        return resp.base_goal, resp.configuration_goal, resp.distance_to_goal

    def on_execute(self, ud):
        rospy.sleep(1.)

        state_update = PDDLState()
        state_update.domain = self.domain
        state_update.predicates = ['(BASE-SELECTED %s %s)' % (self.task, self.model.upper())]

        print "Publishing (BASE-SELECTED) update"
        self.state_pub.publish(state_update)
        return

        base_goals = []
        configuration_goals = []
        goal_array, config_array, distance_array = self.call_base_selection()
        if goal_array == None or config_array == None:
            print "Base Selection Returned None"
            return 'aborted'
        # if len(distance_array) == 1:
        #     for item in goal_array[:7]:
        #         base_goals.append(item)
        #     for item in config_array[:3]:
        #         configuration_goals.append(item)
        # elif len(distance_array) == 2:
        config_num_closest = np.argmin(distance_array)
        for item in goal_array[config_num_closest*7:(config_num_closest*7+7)]:
            base_goals.append(item)
        for item in config_array[config_num_closest*3:(config_num_closest*3+3)]:
            configuration_goals.append(item)
        print "Base Goals returned:\r\n", base_goals
        print "Configuration Goals returned:\r\n", configuration_goals
        try:
            rospy.set_param('/pddl_tasks/%s/base_goals' % self.domain, base_goals)
        except:
            rospy.logwarn("[%s] CallBaseSelectionState - Cannot place base goal on parameter server", rospy.get_name())
            return 'aborted'
        try:
            rospy.set_param('/pddl_tasks/%s/configuration_goals' % self.domain, configuration_goals)
        except:
            rospy.logwarn("[%s] CallBaseSelectionState - Cannot place autobed and torso height config on parameter server", rospy.get_name())
            return 'aborted'
        state_update = PDDLState()
        state_update.domain = self.domain
        state_update.predicates = ['(BASE-SELECTED %s %s)' % (self.task, self.model.upper())]

        print "Publishing (BASE-SELECTED) update"
        self.state_pub.publish(state_update)


class ConfigureModelRobotState(PDDLSmachState):
    def __init__(self, task, model, domain, *args, **kwargs):
        super(ConfigureModelRobotState, self).__init__(domain=domain, *args, **kwargs)
        try:
            rospy.wait_for_service('/left_arm/haptic_mpc/enable_mpc', timeout=5)
            self.mpc_left_enabled_service = rospy.ServiceProxy("/left_arm/haptic_mpc/enable_mpc", EnableHapticMPC)
            self.mpc_right_enabled_service = rospy.ServiceProxy("/right_arm/haptic_mpc/enable_mpc", EnableHapticMPC)
        except:
            rospy.logwarn("[%s] Enable Haptic MPC Service is not running!" % rospy.get_name())
            return 'aborted'
        self.domain = domain
        self.task = task
        self.model = model
        print "Configuring Model and Robot for task: %s and Model: %s" %(task, model)
        self.stop_tracking_AR_publisher = rospy.Publisher('track_AR_now', Bool, queue_size=1)
        if self.model.upper() == 'AUTOBED':
            self.model_reached = False
        else:
            self.model_reached = True
        self.torso_reached = False
        self.state_pub = rospy.Publisher('/pddl_tasks/state_updates', PDDLState, queue_size=10)
        self.torso_client = actionlib.SimpleActionClient('torso_controller/position_joint_action',
                                                         SingleJointPositionAction)
        self.l_reset_traj = None
        self.r_reset_traj = None
        self.define_reset()
        self.goal_reached = False
        self.r_arm_pub = rospy.Publisher('/right_arm/haptic_mpc/joint_trajectory',
                                         JointTrajectory,
                                         queue_size=1)
        self.l_arm_pub = rospy.Publisher('/left_arm/haptic_mpc/joint_trajectory',
                                          JointTrajectory,
                                          queue_size=1)

        if self.model.upper() == 'AUTOBED':
            self.bed_state_leg_theta = None
            self.autobed_pub = rospy.Publisher('/abdin0', FloatArrayBare, queue_size=1)
            self.model_reached = False
            #self.autobed_sub = rospy.Subscriber('/abdout0', FloatArrayBare, self.bed_state_cb)
            self.status_sub = rospy.Subscriber('abdstatus0', Bool, self.bed_status_cb)


    def bed_state_cb(self, data):
        self.bed_state_leg_theta = data.data[2]

    def bed_status_cb(self, data):
        self.model_reached = data.data

    def define_reset(self):
        r_reset_traj_point = JointTrajectoryPoint()
        # r_reset_traj_point.positions = [-3.14/2, -0.6, 0.00, m.radians(-100), 0., m.radians(-90), 0.0]
        r_reset_traj_point.positions = [-1.8, 2.45, -1.9, -2.0, 3.5, -1.5, 0.0]

        r_reset_traj_point.velocities = [0.0]*7
        r_reset_traj_point.accelerations = [0.0]*7
        r_reset_traj_point.time_from_start = rospy.Duration(2)
        self.r_reset_traj = JointTrajectory()
        self.r_reset_traj.joint_names = ['r_shoulder_pan_joint',
                                         'r_shoulder_lift_joint',
                                         'r_upper_arm_roll_joint',
                                         'r_elbow_flex_joint',
                                         'r_forearm_roll_joint',
                                         'r_wrist_flex_joint',
                                         'r_wrist_roll_joint']
        self.r_reset_traj.points.append(r_reset_traj_point)
        l_reset_traj_point = JointTrajectoryPoint()

        # l_reset_traj_point.positions = [(3.14/2 + 3.14/4), -0.6, m.radians(0), m.radians(-150.), m.radians(150.), m.radians(-110.), 0.0]
        if self.task.upper() == 'SCRATCHING' or self.task.upper() == 'BLANKET' or True:
            l_reset_traj_point.positions = [(3.14/2 + 3.14/4), -0.6, m.radians(20), m.radians(-150.), m.radians(150.), m.radians(-110.), 0.0]
        else:
            l_reset_traj_point.positions = [1.8, 0.4, 1.9, -3.0, -3.5, -0.5, 0.0]
            # l_reset_traj_point.positions = [0.8, 0.0, 1.57, -2.9, 3.0, -1.0, 1.57]
        # l_reset_traj_point.positions = [0.0, 1.35, 0.00, -1.60, -3.14, -0.3, 0.0]
        #l_reset_traj_point.positions = [0.7629304700932569, -0.3365186041095207, 0.5240000202473829,
        #                                        -2.003310310963515, 0.9459734129025158, -1.7128778450423763, 0.6123854412633384]
        l_reset_traj_point.velocities = [0.0]*7
        l_reset_traj_point.accelerations = [0.0]*7
        l_reset_traj_point.time_from_start = rospy.Duration(2)
        self.l_reset_traj = JointTrajectory()
        self.l_reset_traj.joint_names = ['l_shoulder_pan_joint',
                                         'l_shoulder_lift_joint',
                                         'l_upper_arm_roll_joint',
                                         'l_elbow_flex_joint',
                                         'l_forearm_roll_joint',
                                         'l_wrist_flex_joint',
                                         'l_wrist_roll_joint']
        self.l_reset_traj.points.append(l_reset_traj_point)

    def arm_reach_goal_cb(self, msg):
        self.goal_reached = msg.data

    def on_execute(self, ud):
        rospy.sleep(1.)
        resp = self.mpc_left_enabled_service('enabled')
        resp = self.mpc_right_enabled_service('enabled')

        rospy.loginfo("[%s] Moving Arms to Home Position" % rospy.get_name())
        self.r_arm_pub.publish(self.r_reset_traj)
        self.l_arm_pub.publish(self.l_reset_traj)

        rospy.loginfo("[%s] Waiting for torso_controller/position_joint_action server" % rospy.get_name())
        if self.torso_client.wait_for_server(rospy.Duration(5)):
            rospy.loginfo("[%s] Found torso_controller/position_joint_action server" % rospy.get_name())
        else:
            rospy.logwarn("[%s] Cannot find torso_controller/position_joint_action server" % rospy.get_name())
            return 'aborted'

        if True:
            torso_lift_msg = SingleJointPositionGoal()
            torso_lift_msg.position = 0.3
            self.torso_client.send_goal(torso_lift_msg)
        else:
            rospy.logwarn("[%s] Some problem in getting TORSO HEIGHT from base selection" % rospy.get_name())
            return 'aborted'

        rospy.loginfo("[%s] Waiting For Torso to be moved" % rospy.get_name())
        self.torso_client.wait_for_result()
        torso_status = self.torso_client.get_state()
        if torso_status == GoalStatus.SUCCEEDED:
            rospy.loginfo("[%s] TORSO Actionlib Client has SUCCEEDED" % rospy.get_name())
            state_update = PDDLState()
            state_update.domain = self.domain
            state_update.predicates = ['(CONFIGURED SPINE %s %s)' % (self.task, self.model)]
            print "Publishing (CONFIGURED SPINE) update"
            self.state_pub.publish(state_update)
        else:
            rospy.logwarn("[%s] Torso Actionlib Client has NOT succeeded" % rospy.get_name())
            return 'aborted'

        rospy.loginfo("[%s] Bed Goal Reached" % rospy.get_name())
        state_update = PDDLState()
        state_update.domain = self.domain
        state_update.predicates = ['(CONFIGURED BED %s %s)' % (self.task, self.model)]
        print "Publishing (CONFIGURED BED) update"
        self.state_pub.publish(state_update)

        rospy.sleep(2)
        rospy.loginfo("[%s] Arm Goal Reached" % rospy.get_name())
        state_update = PDDLState()
        state_update.domain = self.domain
        state_update.predicates = ['(ARM-HOME %s %s)' % (self.task, self.model)]
        print "Publishing (ARM-HOME) update"
        self.state_pub.publish(state_update)
