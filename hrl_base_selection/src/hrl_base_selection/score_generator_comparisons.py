#!/usr/bin/env python

import numpy as np
import math as m
import openravepy as op
from openravepy.misc import InitOpenRAVELogging
import copy

import time
import roslib
roslib.load_manifest('hrl_base_selection')
roslib.load_manifest('hrl_haptic_mpc')
import rospy, rospkg
import tf
from geometry_msgs.msg import PoseStamped
from mpl_toolkits.mplot3d import Axes3D
from matplotlib import cm
from matplotlib.ticker import LinearLocator, FormatStrFormatter
import matplotlib.pyplot as plt
from matplotlib.path import Path
import matplotlib.patches as patches
from matplotlib.cbook import flatten
from itertools import combinations as comb
from operator import itemgetter

from sensor_msgs.msg import JointState
from std_msgs.msg import String
# import hrl_lib.transforms as tr
from hrl_base_selection.srv import BaseMove#, BaseMove_multi
from visualization_msgs.msg import Marker, MarkerArray
from helper_functions import createBMatrix, Bmat_to_pos_quat
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
import random

import pickle as pkl
roslib.load_manifest('hrl_lib')
from hrl_lib.util import save_pickle, load_pickle
from random import gauss
# import hrl_haptic_mpc.haptic_mpc_util
# from hrl_haptic_mpc.robot_haptic_state_node import RobotHapticStateServer
from hrl_base_selection.inverse_reachability_setup import InverseReachabilitySetup
import hrl_lib.util as ut

import sensor_msgs.point_cloud2 as pc2

import cma

# from joblib import Parallel, delayed


class ScoreGenerator(object):

    def __init__(self, visualize=False, targets='all_goals', reference_names=['head'], goals=None, model='autobed',
                 tf_listener=None, task='shaving', training=True):
        # if tf_listener is None:
        #     self.tf_listener = tf.TransformListener()
        # else:
        #     self.tf_listener = tf_listener
        self.visualize = visualize
        self.model = model

        self.training = training

        self.arm = 'leftarm'
        self.opposite_arm = 'rightarm'

        self.ir_and_collision = False

        self.a_model_is_loaded = False
        self.goals = goals
        self.pr2_B_reference = []
        self.task = task

        self.reference_names = reference_names

        self.head_angles = []

        self.reachable = {}
        self.manipulable = {}
        self.scores = {}
        self.headx = 0.
        self.heady = 0.
        self.distance = 0.
        self.score_length = {}
        self.sorted_scores = {}
        self.environment_model = None
        self.setup_openrave()
        # The reference frame for the pr2 base link
        origin_B_pr2 = np.matrix([[       1.,        0.,   0.,         0.0],
                                  [       0.,        1.,   0.,         0.0],
                                  [       0.,        0.,   1.,         0.0],
                                  [       0.,        0.,   0.,         1.0]])
        pr2_B_head = []
        # Sets the wheelchair location based on the location of the head using a few homogeneous transforms.
        # This is only used to visualize in rviz, because the visualization is done before initializing openrave
        self.origin_B_references = []
        if self.model == 'chair':
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')
            ual = self.wheelchair.GetLink('wheelchair/arm_left_link')
            uar = self.wheelchair.GetLink('wheelchair/arm_right_link')
            fal = self.wheelchair.GetLink('wheelchair/forearm_left_link')
            far = self.wheelchair.GetLink('wheelchair/forearm_right_link')
            thl = self.wheelchair.GetLink('wheelchair/quad_left_link')
            thr = self.wheelchair.GetLink('wheelchair/quad_right_link')
            kneel = self.wheelchair.GetLink('wheelchair/calf_left_link')
            kneer = self.wheelchair.GetLink('wheelchair/calf_right_link')
            footl = self.wheelchair.GetLink('wheelchair/foot_left_link')
            footr = self.wheelchair.GetLink('wheelchair/foot_right_link')
            ch = self.wheelchair.GetLink('wheelchair/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
        elif self.model == 'autobed':
            headmodel = self.autobed.GetLink('autobed/head_link')
            ual = self.autobed.GetLink('autobed/arm_left_link')
            uar = self.autobed.GetLink('autobed/arm_right_link')
            fal = self.autobed.GetLink('autobed/forearm_left_link')
            far = self.autobed.GetLink('autobed/forearm_right_link')
            thl = self.autobed.GetLink('autobed/quad_left_link')
            thr = self.autobed.GetLink('autobed/quad_right_link')
            kneel = self.autobed.GetLink('autobed/calf_left_link')
            kneer = self.autobed.GetLink('autobed/calf_right_link')
            footl = self.autobed.GetLink('autobed/foot_left_link')
            footr = self.autobed.GetLink('autobed/foot_right_link')
            ch = self.autobed.GetLink('autobed/upper_body_link')
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            origin_B_head = np.matrix(headmodel.GetTransform())
        elif self.model == None:
            print 'Running score generator in real-time mode!'
        else:
            print 'I GOT A BAD MODEL. NOT SURE WHAT TO DO NOW!'
        # origin_B_head = np.matrix(headmodel.GetTransform())

        for y in self.reference_names:
            if y == 'head':
                self.origin_B_references.append(origin_B_head)
            elif y == 'base_link':
                self.origin_B_references.append(origin_B_pr2)
            elif y == 'upper_arm_left':
                self.origin_B_references.append(origin_B_ual)
            elif y == 'upper_arm_right':
                self.origin_B_references.append(origin_B_uar)
            elif y == 'forearm_left':
                self.origin_B_references.append(origin_B_fal)
            elif y == 'forearm_right':
                self.origin_B_references.append(origin_B_far)
            elif y == 'thigh_left':
                self.origin_B_references.append(origin_B_thl)
            elif y == 'thigh_right':
                self.origin_B_references.append(origin_B_thr)
            elif y == 'knee_left':
                self.origin_B_references.append(origin_B_kneel)
            elif y == 'knee_right':
                self.origin_B_references.append(origin_B_kneer)
            elif y == 'foot_left':
                self.origin_B_references.append(origin_B_footl)
            elif y == 'foot_right':
                self.origin_B_references.append(origin_B_footr)
            elif y == 'chest':
                self.origin_B_references.append(origin_B_ch)
            elif y is None:
                self.origin_B_references.append(np.matrix(np.eye(4)))
        # Sets the wheelchair location based on the location of the head using a few homogeneous transforms.
        self.pr2_B_headfloor = np.matrix([[       1.,        0.,   0.,         0.],
                                          [       0.,        1.,   0.,         0.],
                                          [       0.,        0.,   1.,         0.],
                                          [       0.,        0.,   0.,         1.]])

        # Gripper coordinate system has z in direction of the gripper, x is the axis of the gripper opening and closing.
        # This transform corrects that to make x in the direction of the gripper, z the axis of the gripper open.
        # Centered at the very tip of the gripper.
        self.goal_B_gripper = np.matrix([[0.,  0.,   1.,   0.0],
                                         [0.,  1.,   0.,   0.0],
                                         [-1.,  0.,   0.,  0.0],
                                         [0.,  0.,   0.,   1.0]])

        self.selection_mat = []
        self.reference_mat = []
        self.origin_B_grasps = []
        self.weights = []
        self.goal_list = []
        # print self.goals
        # print len(self.origin_B_references)
        if self.goals is not None:
            self.number_goals = len(self.goals)
            print 'Score generator received a list of desired goal locations on initialization. ' \
                  'It contains ', len(goals), ' goal locations.'
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            self.reference_mat = np.zeros(len(self.goals))
            for it in xrange(len(self.goals)):
                # self.goal_list.append(pr2_B_head*np.matrix(target[0])*goal_B_gripper)
                self.reference_mat[it] = int(self.goals[it, 2])

                # goal_list is origin_B_goal
                self.goal_list[it] = copy.copy(
                    self.origin_B_references[int(self.reference_mat[it])] * np.matrix(self.goals[it, 0]))
                self.selection_mat[it] = self.goals[it, 1]
            self.set_goals()

    def receive_new_goals(self, goals, reference_options=None, model=None):
        if  model is not None:
            if not model == self.model:
                self.env.Remove(self.env.GetRobots()[1])
                self.model = model
                self.setup_human_model()
        if (self.task == 'wiping_mouth' or self.task == 'shaving' or self.task == 'feeding_trajectory' or self.task == 'brushing') and self.model == 'chair':
            self.head_angles = np.array([[68, 10], [68, 0], [68, -10], [0, 0], [-68, 10], [68, 0], [-68, -10]])
            self.head_angles = np.array([[60., 0.], [0., 0.], [-60., 0.]])
        else:
            self.head_angles = np.array([[0., 0.]])
        origin_B_pr2 = np.matrix([[       1.,        0.,   0.,         0.0],
                                  [       0.,        1.,   0.,         0.0],
                                  [       0.,        0.,   1.,         0.0],
                                  [       0.,        0.,   0.,         1.0]])
        if reference_options is not None:
            self.reference_names = reference_options
            self.origin_B_references = []
            if self.model == 'chair':
                headmodel = self.wheelchair.GetLink('wheelchair/head_link')
                ual = self.wheelchair.GetLink('wheelchair/arm_left_link')
                uar = self.wheelchair.GetLink('wheelchair/arm_right_link')
                fal = self.wheelchair.GetLink('wheelchair/forearm_left_link')
                far = self.wheelchair.GetLink('wheelchair/forearm_right_link')
                thl = self.wheelchair.GetLink('wheelchair/quad_left_link')
                thr = self.wheelchair.GetLink('wheelchair/quad_right_link')
                kneel = self.wheelchair.GetLink('wheelchair/calf_left_link')
                kneer = self.wheelchair.GetLink('wheelchair/calf_right_link')
                footl = self.wheelchair.GetLink('wheelchair/foot_left_link')
                footr = self.wheelchair.GetLink('wheelchair/foot_right_link')
                ch = self.wheelchair.GetLink('wheelchair/upper_body_link')
                origin_B_head = np.matrix(headmodel.GetTransform())
                origin_B_ual = np.matrix(ual.GetTransform())
                origin_B_uar = np.matrix(uar.GetTransform())
                origin_B_fal = np.matrix(fal.GetTransform())
                origin_B_far = np.matrix(far.GetTransform())
                origin_B_thl = np.matrix(thl.GetTransform())
                origin_B_thr = np.matrix(thr.GetTransform())
                origin_B_kneel = np.matrix(kneel.GetTransform())
                origin_B_kneer = np.matrix(kneer.GetTransform())
                origin_B_footl = np.matrix(footl.GetTransform())
                origin_B_footr = np.matrix(footr.GetTransform())
                origin_B_ch = np.matrix(ch.GetTransform())
                origin_B_head = np.matrix(headmodel.GetTransform())
            elif self.model == 'autobed':
                headmodel = self.autobed.GetLink('autobed/head_link')
                ual = self.autobed.GetLink('autobed/arm_left_link')
                uar = self.autobed.GetLink('autobed/arm_right_link')
                fal = self.autobed.GetLink('autobed/forearm_left_link')
                far = self.autobed.GetLink('autobed/forearm_right_link')
                thl = self.autobed.GetLink('autobed/quad_left_link')
                thr = self.autobed.GetLink('autobed/quad_right_link')
                kneel = self.autobed.GetLink('autobed/calf_left_link')
                kneer = self.autobed.GetLink('autobed/calf_right_link')
                footl = self.autobed.GetLink('autobed/foot_left_link')
                footr = self.autobed.GetLink('autobed/foot_right_link')
                ch = self.autobed.GetLink('autobed/upper_body_link')
                origin_B_ual = np.matrix(ual.GetTransform())
                origin_B_uar = np.matrix(uar.GetTransform())
                origin_B_fal = np.matrix(fal.GetTransform())
                origin_B_far = np.matrix(far.GetTransform())
                origin_B_thl = np.matrix(thl.GetTransform())
                origin_B_thr = np.matrix(thr.GetTransform())
                origin_B_kneel = np.matrix(kneel.GetTransform())
                origin_B_kneer = np.matrix(kneer.GetTransform())
                origin_B_footl = np.matrix(footl.GetTransform())
                origin_B_footr = np.matrix(footr.GetTransform())
                origin_B_ch = np.matrix(ch.GetTransform())
                origin_B_head = np.matrix(headmodel.GetTransform())
            elif self.model is None:
                origin_B_pr2 = np.matrix(np.eye(4))
            else:
                print 'I GOT A BAD MODEL. NOT SURE WHAT TO DO NOW!'

            for y in self.reference_names:
                if y == 'head':
                    self.origin_B_references.append(origin_B_head)
                elif y == 'base_link':
                    self.origin_B_references.append(origin_B_pr2)
                elif y == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif y == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif y == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif y == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif y == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif y == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif y == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif y == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif y == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif y == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif y == 'chest':
                    self.origin_B_references.append(origin_B_ch)
                else:
                    print 'The refence options is bogus! I dont know what to do!'
                    return
            self.goals = goals
        # print 'Score generator received a new list of desired goal locations. It contains ', len(goals), ' goal ' \
        #                                                                                                  'locations.'
        self.selection_mat = np.zeros(len(self.goals))
        self.goal_list = np.zeros([len(self.goals), 4, 4])
        self.reference_mat = np.zeros(len(self.goals))
        for w in xrange(len(self.goals)):
            #self.goal_list.append(pr2_B_head*np.matrix(target[0])*goal_B_gripper)
            self.reference_mat[w] = int(self.goals[w, 2])
            self.goal_list[w] = copy.copy(self.origin_B_references[int(self.reference_mat[w])] *
                                          np.matrix(self.goals[w, 0]))
            self.selection_mat[w] = self.goals[w, 1]

        self.set_goals()

    def set_goals(self, single_goal=False):
        if single_goal is False:
            self.origin_B_grasps = []
            self.weights = []
            for num in xrange(len(self.selection_mat)):
                if self.selection_mat[num] != 0:
                    #self.origin_B_grasps.append(np.array(self.goal_list[num]))
                    self.origin_B_grasps.append(np.array(np.matrix(self.goal_list[num])*self.goal_B_gripper))
                    self.weights.append(self.selection_mat[num])
        else:
            self.origin_B_grasps = []
            self.weights = []
            if self.selection_mat[0] != 0:
                self.origin_B_grasps.append(np.array(np.matrix(self.goal_list[0])*self.goal_B_gripper))
                self.weights.append(self.selection_mat[0])

    def choose_task(self, task):
        if task == 'all_goals':
            self.selection_mat = np.ones(len(self.goal_list))
        elif task == 'wipe_face':
            self.selection_mat = np.array([1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
        elif task == 'shoulder':
            self.selection_mat = np.array([0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0])
        elif task == 'knee':
            self.selection_mat = np.array([0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0])
        elif task == 'arm':
            self.selection_mat = np.array([0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 1])
        else:
            print 'Somehow I got a bogus task!? \n'
            return None
        self.set_goals()
        print 'The task was just set. The set of goals selected was: ',task
        return self.selection_mat

    def set_arm(self, arm):
        ## Set robot manipulators, ik, planner
        print 'Setting the arm being used by base selection to ', arm
        self.arm = arm
        if arm == 'leftarm':
            self.opposite_arm = 'rightarm'
        elif arm == 'rightarm':
            self.opposite_arm = 'leftarm'
        else:
            print 'ERROR'
            print 'I do not know what arm to be using'
            return None
        self.robot.SetActiveManipulator(arm)
        self.manip = self.robot.GetActiveManipulator()
        ikmodel = op.databases.inversekinematics.InverseKinematicsModel(self.robot, iktype=op.IkParameterization.Type.Transform6D)
        if not ikmodel.load():
            print 'IK model not found. Will now generate an IK model. This will take a while!'
            ikmodel.autogenerate()
        self.manipprob = op.interfaces.BaseManipulation(self.robot)

    def real_time_scoring(self):
        if not self.a_model_is_loaded:
            print 'Somehow a model has not been loaded. This is bad!'
            return None
        param_min = np.array([-0.25, -1.5, -m.pi/3., 0.])
        param_max = np.array([1.75, 1.5, m.pi/3., 0.3])
        param_initialization = (param_max+param_min)/2.
        param_scaling = (param_max - param_min)/4.
        maxiter = 3
        popsize = m.pow(1, 1)*10
        opts1 = {'seed': 1234, 'ftarget': -1., 'popsize': popsize, 'maxiter': maxiter, 'maxfevals': 1e8, 'CMA_cmean': 0.5,
                 'scaling_of_variables': list(param_scaling),
                 'bounds': [list(param_min), list(param_max)]}

        optimization_results = cma.fmin(self.objective_function_real_time,
                                        list(param_initialization),
                                        1.,
                                        options=opts1)
        config = optimization_results[0]
        score = optimization_results[1]
        print 'Config: ', config
        print 'Score: ', score
        return config, score

    def initialize_environment_model(self, myCloud):
            # print " x : %f  y: %f  z: %f" %(p[0],p[1],p[2])
        with self.env:
            self.env.Remove(self.environment_model)
            # num_points = int(myCloud.height * myCloud.width)
            # num_points = len(pc2.read_points(myCloud, field_names=("x", "y", "z"), skip_nans=True))
            # environment_voxels = np.zeros([num_points, 6])
            # environment_voxels = []
            # i = 0
            # for p in pc2.read_points(myCloud, field_names=("x", "y", "z"), skip_nans=True):
            # for p in pc2.read_points(myCloud, field_names=("x", "y", "z"), skip_nans=True):
            #     if p[2] > 0.1:
            #         environment_voxels.append([p[0], p[1], p[2], 0.005, 0.005, 0.005])
                    # environment_voxels[i] = [p[0], p[1], p[2], 0.005, 0.005, 0.005]
                    # i += 1
            # environment_voxels = np.array(environment_voxels)
            # print 'number of voxels: ', len(environment_voxels)

            environment_voxels = np.array([t for t in (([p[0], p[1], p[2], 0.025, 0.025, 0.025])
                                                       for p in pc2.read_points(myCloud, field_names=("x", "y", "z"), skip_nans=True))
                                           if (t[2] > 0.05)
                                           ])

            self.environment_model.InitFromBoxes(environment_voxels, True)  # set geometry as many boxes
            self.env.AddKinBody(self.environment_model)
        self.a_model_is_loaded = True
        return True

    def handle_score_generation(self, plot=False, method='toc', sampling='cma', seed=None):
        if seed is None:
            seed = int(time.time())
        scoring_start_time = rospy.Time.now()
        if not self.a_model_is_loaded:
            print 'Somehow a model has not been loaded. This is bad!'
            return None
        print 'Starting to generate the score. This is going to take a while.'
        # Results are stored in the following format:
        # optimization_results[<task>, <method>, <sampling>, <model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
        # Negative head read angle means head rest angle is a free DoF.
        self.ir_and_collision = False
        if method == 'inverse_reachability' or method == 'inverse_reachability_collision':
            if method == 'inverse_reachability_collision':
                self.ir_and_collision = True
            else:
                self.ir_and_collision = False
            self.ireach = InverseReachabilitySetup(visualize=False, redo_ik=False,
                                                   redo_reachability=False, redo_ir=False, manip='leftarm')

        head_x_range = [0.]
#        self.head_angles = np.array([[58, 18], [58, 0], [58, -18], [0, 0], [-58, 18], [-58, 0], [-58, -18]])
        self.head_angles = np.array([[68, 10], [68, 0], [68, -10], [0, 0], [-68, 10], [68, 0], [-68, -10]])
#        if self.task == 'scratching_knee_left':
        self.head_angles = np.array([[0., 0.]])
        head_y_range = (np.arange(11)-5)*.03
        head_y_range = np.array([0.])
        head_rest_range = np.arange(-10, 80.1, 10.)
        head_rest_range = [-10]
        # bed_height = 'fixed'
        # score_parameters = []
        # score_parameters.append([self.model, ])
        if self.model == 'autobed':
            score_parameters = ([t for t in ((tuple([self.task, method, sampling, self.model, num_configs, head_rest_angle, headx, heady, allow_bed_movement]))
                                             for num_configs in [1, 2]
                                             for head_rest_angle in head_rest_range
                                             for headx in head_x_range
                                             for heady in head_y_range
                                             for allow_bed_movement in [1]
                                             )
                                 ])
        elif self.model == 'chair':
            if self.task == 'wiping_mouth' or self.task == 'shaving' or self.task == 'feeding_trajectory' or self.task == 'brushing':
                self.head_angles = np.array([[68, 10], [68, 0], [68, -10], [0, 0], [-68, 10], [68, 0], [-68, -10]])
                self.head_angles = np.array([[60., 0.], [0., 0.], [-60., 0.]])
            score_parameters = ([t for t in ((tuple([self.task, method, sampling, self.model, num_configs, 0, 0, 0, 0]))
                                             for num_configs in [1,2]
                                             )
                                 ])
        else:
            print 'ERROR'
            print 'I do not know what model to use!'
            return

        start_time = rospy.Time.now()
        # headx_min = 0.
        # headx_max = 0.0+.01
        # headx_int = 0.05
        # heady_min = -0.1
        # heady_min = -0.1
        # heady_max = 0.1+.01
        # heady_int = 0.1
        # # heady_int = 1.05
        # # start_x_min = -1.0
        # start_x_min = 0.0
        # start_x_max = 3.0+.01
        # start_x_int = 10.
        # # start_y_min = -2.0
        # start_y_min = 0.0
        # start_y_max = 2.0+.01
        # start_y_int = 10.
        # #head_y_range = (np.arange(5)-2)*.05  #[0]
        # head_y_range = (np.arange(11)-5)*.03
        # #head_y_range = np.array([0])
        # if self.model == 'chair':
        #     bedz_min = 0.
        #     bedtheta_min = 0.
        #     headx_min = 0.
        #     heady_min = 0.
        #     bedz_int = 100.
        #     bedtheta_int = 100.
        #     headx_int = 100.
        #     heady_int = 100.
        #

        optimization_results = dict.fromkeys(score_parameters)
        score_stuff = dict.fromkeys(score_parameters)
        # optimization_results[<task>, <method>, <sampling> ,<model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
        for parameters in score_parameters:
            parameter_start_time = rospy.Time.now()
            print 'Generating score for the following parameters: '
            print '[<task>, <method>, <sampling>,  <model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]'
            print parameters

            if parameters[1] != 'toc' and parameters[4] ==2:
                score_stuff[parameters] = [np.zeros([6, 1]), 10.,
                                           (rospy.Time.now() - parameter_start_time).to_sec()]
            else:
                self.best_config = None
                self.best_score = 1000.

                num_config = parameters[4]
                self.head_rest_angle = parameters[5]
                self.headx = parameters[6]
                self.heady = parameters[7]
                self.allow_bed_movement = parameters[8]
    #            self.heady=0.03

                maxiter = 20
                popsize = 4000
                if num_config == 1:
                    if self.model == 'chair':
                        # maxiter = 15
                        # popsize = 1000
                        # popsize = m.pow(4, 2)*100
                        parameters_min = np.array([0.0, -2.3,  m.radians(-270.) - 0.0001, 0.])
                        parameters_max = np.array([3., 2.3,  m.radians(270.) + 0.0001, 0.3])
                        parameters_scaling = (parameters_max-parameters_min)/4.
                        parameters_initialization = (parameters_max+parameters_min)/2.

                        if sampling == 'cma':
                            opts1 = {'seed': seed, 'ftarget': -1., 'popsize': popsize, 'maxiter': maxiter, 'maxfevals': 1e8, 'CMA_cmean': 0.25,
                                     'scaling_of_variables': list(parameters_scaling),
                                     'bounds': [list(parameters_min), list(parameters_max)]}

                            if method == 'toc':
                                # optimization_results[<method>, <sampling>, <model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
                                optimization_results[parameters] = cma.fmin(self.objective_function_one_config_toc_sample,
                                                                                        list(parameters_initialization),
                                                                                        1.,
                                                                                        options=opts1)
                            elif method == 'inverse_reachability' or method == 'inverse_reachability_collision':
                                # optimization_results[<method>, <sampling>, <model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
                                optimization_results[parameters] = cma.fmin(self.objective_function_one_config_ireach_sample,
                                                                            list(parameters_initialization),
                                                                            1.,
                                                                            options=opts1)
                            elif method == 'ik':
                                opts1 = {'seed': seed, 'ftarget': 0., 'popsize': popsize, 'maxiter': maxiter,
                                         'maxfevals': 1e8, 'CMA_cmean': 0.25,
                                         'scaling_of_variables': list(parameters_scaling),
                                         'bounds': [list(parameters_min), list(parameters_max)]}
                                # optimization_results[<method>, <sampling>, <model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
                                optimization_results[parameters] = cma.fmin(
                                    self.objective_function_one_config_ik_sample,
                                    list(parameters_initialization),
                                    1.,
                                    options=opts1)
                            else:
                                print 'Unknown method!'
                                return False
                            config = optimization_results[parameters][0]
                            score = optimization_results[parameters][1]
                        elif sampling == 'uniform':
                            self.best_config = None
                            self.best_score = 1000.
                            random_state = np.random.RandomState(seed=seed)
                            samples = random_state.uniform(parameters_min, parameters_max,
                                                           [maxiter*popsize,len(parameters_min)])
                            if method == 'toc':
                                for sample in samples:
                                    self.objective_function_one_config_toc_sample(sample)
                            elif method == 'inverse_reachability' or method == 'inverse_reachability_collision':
                                for sample in samples:
                                    self.objective_function_one_config_ireach_sample(sample)
                            elif method == 'ik':
                                for sample in samples:
                                    self.objective_function_one_config_ik_sample(sample)
                                    if self.best_score < 0.0001 or self.best_score == 0.:
                                        break
                            config = self.best_config
                            score = self.best_score
                        elif sampling == 'gaussian':
                            self.best_config = None
                            self.best_score = 1000.
                            random_state = np.random.RandomState(seed=seed)
                            samples = random_state.normal(parameters_initialization, parameters_scaling,
                                                          [maxiter * popsize, len(parameters_scaling)])
                            if method == 'toc':
                                for sample in samples:
                                    self.objective_function_one_config_toc_sample(sample)
                            elif method == 'inverse_reachability' or method == 'inverse_reachability_collision':
                                for sample in samples:
                                    self.objective_function_one_config_ireach_sample(sample)
                            elif method == 'ik':
                                for sample in samples:
                                    self.objective_function_one_config_ik_sample(sample)
                                    if self.best_score < 0.0001 or self.best_score == 0.:
                                        break
                            config = self.best_config
                            score = self.best_score
                        print 'Config: ', config
                        print 'Score: ', score
                        #score_stuff = dict()
                        # optimization_results[<method>, <sampling>, <model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
                        config = np.resize(config, [6, 1])
                        score_stuff[parameters] = [config, score, (rospy.Time.now() - parameter_start_time).to_sec()]


                    elif self.model == 'autobed':
                        # maxiter = 10
                        # popsize = 100
        #                popsize = m.pow(6, 2)*100
        #                 popsize = 1500
                        parameters_min = np.array([0.3, -2.3, m.radians(-270.)-0.0001, 0., 0., 0.*m.pi/180.])
                        parameters_max = np.array([3.0, 2.3, m.radians(270.)+.0001, 0.3, 0.25, 75.*m.pi/180.])
                        parameters_scaling = (parameters_max-parameters_min)/4.
                        parameters_scaling[5] = (parameters_max[5]-parameters_min[5])/2.
                        parameters_initialization = (parameters_max+parameters_min)/2.

                        if sampling == 'cma':
                            opts1 = {'seed': 1234, 'ftarget': -1., 'popsize': popsize, 'maxiter': maxiter, 'maxfevals': 1e8, 'CMA_cmean': 0.25,
                                     'scaling_of_variables': list(parameters_scaling),
                                     'bounds': [list(parameters_min),
                                                list(parameters_max)]}
                            if method == 'toc':
                                # optimization_results[<method>, <sampling>, <model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
                                optimization_results[parameters] = cma.fmin(self.objective_function_one_config_toc_sample,
                                                                            list(parameters_initialization),
                                                                            1.,
                                                                            options=opts1)
                            elif method == 'inverse_reachability' or method == 'inverse_reachability_collision':
                                # optimization_results[<method>, <sampling>, <model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
                                optimization_results[parameters] = cma.fmin(self.objective_function_one_config_ireach_sample,
                                                                            list(parameters_initialization),
                                                                            1.,
                                                                            options=opts1)
                            elif method == 'ik':
                                opts1 = {'seed': 1234, 'ftarget': 0., 'popsize': popsize, 'maxiter': maxiter,
                                         'maxfevals': 1e8, 'CMA_cmean': 0.25,
                                         'scaling_of_variables': list(parameters_scaling),
                                         'bounds': [list(parameters_min), list(parameters_max)]}
                                # optimization_results[<method>, <sampling>, <model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
                                optimization_results[parameters] = cma.fmin(
                                    self.objective_function_one_config_ik_sample,
                                    list(parameters_initialization),
                                    1.,
                                    options=opts1)
                            else:
                                print 'Unknown method!'
                                return False
                            config = optimization_results[parameters][0]
                            score = optimization_results[parameters][1]
                        elif sampling == 'uniform':
                            self.best_config = None
                            self.best_score = 1000.
                            random_state = np.random.RandomState(seed=seed)
                            samples = random_state.uniform(parameters_min, parameters_max,
                                                           [maxiter*popsize,len(parameters_min)])
                            if method == 'toc':
                                for sample in samples:
                                    self.objective_function_one_config_toc_sample(sample)
                            elif method == 'inverse_reachability' or method == 'inverse_reachability_collision':
                                for sample in samples:
                                    self.objective_function_one_config_ireach_sample(sample)
                            elif method == 'ik':
                                for sample in samples:
                                    self.objective_function_one_config_ik_sample(sample)
                                    if self.best_score < 0.0001 or self.best_score ==0.:
                                        break
                            else:
                                print 'Unknown method!'
                                return False
                            config = self.best_config
                            score = self.best_score
                        elif sampling == 'gaussian':
                            self.best_config = None
                            self.best_score = 1000.
                            random_state = np.random.RandomState(seed=seed)
                            samples = random_state.normal(parameters_initialization, parameters_scaling,
                                                          [maxiter * popsize, len(parameters_scaling)])
                            if method == 'toc':
                                for sample in samples:
                                    self.objective_function_one_config_toc_sample(sample)
                            elif method == 'inverse_reachability' or method == 'inverse_reachability_collision':
                                for sample in samples:
                                    self.objective_function_one_config_ireach_sample(sample)
                            elif method == 'ik':
                                for sample in samples:
                                    self.objective_function_one_config_ik_sample(sample)
                                    if self.best_score < 0.0001 or self.best_score == 0.:
                                        break
                            else:
                                print 'Unknown method!'
                                return False
                            config = self.best_config
                            score = self.best_score
                        print 'Config: ', config
                        print 'Score: ', score
                        print 'Time to find scores for this set of parameters: %fs' % ((rospy.Time.now()-parameter_start_time).to_sec())
                        #score_stuff = dict()
                        # optimization_results[<method>, <sampling>, <model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
                        score_stuff[parameters] = [config, score, (rospy.Time.now() - parameter_start_time).to_sec()]

                elif num_config == 2:
                    self.best_scores = np.array([1000., 1000., 1000.])
                    # maxiter = 10
                    # popsize = m.pow(4, 2)*100
                    if self.allow_bed_movement == 0 and self.model == 'autobed':
                        parameters_min = np.array([0.3, -2.3, m.radians(-270.) - 0.0001, 0.,
                                                   0.3, -2.3, m.radians(-270.) - 0.0001, 0.])
                        parameters_max = np.array([3.0, 2.3, m.radians(270.) + .0001, 0.3,
                                                   3.0, 2.3, m.radians(270.) + .0001, 0.3])
                    if self.model == 'chair':
                        parameters_min = np.array([0., -2.3, m.radians(-270.) - 0.0001, 0.,
                                                   0., -2.3, m.radians(-270.) - 0.0001, 0.])
                        parameters_max = np.array([3., 2.3, m.radians(270.) + 0.0001, 0.3,
                                                   3., 2.3, m.radians(270.) + 0.0001, 0.3])
                    if (self.allow_bed_movement == 0 and self.model == 'autobed') or self.model == 'chair':
                        parameters_scaling = (parameters_max-parameters_min)/4.
                        parameters_initialization = (parameters_max+parameters_min)/2.
                        parameters_initialization[1] = 1.0
                        parameters_initialization[5] = -1.0
                        if sampling == 'cma':
                            opts2 = {'seed': seed, 'ftarget': -1., 'popsize': popsize, 'maxiter': maxiter, 'maxfevals': 1e8, 'CMA_cmean': 0.25,
                                     'scaling_of_variables': list(parameters_scaling),
                                     'bounds': [list(parameters_min),
                                                list(parameters_max)]}
                            if method == 'toc':
                                # optimization_results[2, self.heady, self.start_x, self.start_y] = [t for t in ((cma.fmin(self.objective_function_two_config_toc_sample,
                                print 'Working on heady location:', self.heady
                                # optimization_results[<model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
                                optimization_results[parameters] = cma.fmin(self.objective_function_two_config_toc_sample,
                                                                            # [0.75, 0.75, 0., 0.15, 0.75, -0.75, 0., 0.15],
                                                                            list(parameters_initialization),
                                                                            # [0., 0., 0., 0.15, 0.1, 35*m.pi/180, 0., 0., 0., 0.15, 0.1, 35*m.pi/180],
                                                                            1.,
                                                                            options=opts2)
                            # print optimization_results[2, self.heady, self.start_x, self.start_y][0]
                            config = optimization_results[parameters][0]
                            score = optimization_results[parameters][1]
                            scores = self.best_scores
                        elif sampling == 'uniform':
                            self.best_config = None
                            self.best_score = 1000.
                            random_state = np.random.RandomState(seed=seed)
                            samples = np.hstack([random_state.uniform(parameters_min[0:(len(parameters_min) / 2)],
                                                                      parameters_max[0:(len(parameters_min) / 2)],
                                                                      [maxiter*popsize,len(parameters_min)/2]),
                                                 random_state.uniform(parameters_min[0:(len(parameters_min) / 2)],
                                                                      parameters_max[0:(len(parameters_min) / 2)],
                                                                      [maxiter * popsize, len(parameters_min) / 2])])
                            if method == 'toc':
                                for sample in samples:
                                    self.objective_function_two_config_toc_sample(sample)
                            else:
                                print 'Unknown method to do multiple base configurations!'
                                return False
                            config = self.best_config
                            score = self.best_score
                            scores = self.best_scores
                        elif sampling == 'gaussian':
                            self.best_config = None
                            self.best_score = 1000.
                            random_state = np.random.RandomState(seed=seed)
                            samples = np.hstack([random_state.normal(parameters_initialization[0:(len(parameters_scaling) / 2)],
                                                                     parameters_scaling[0:(len(parameters_scaling) / 2)],
                                                                     [maxiter * popsize, len(parameters_scaling) / 2]),
                                                 random_state.normal(parameters_initialization[0:(len(parameters_scaling) / 2)],
                                                                     parameters_scaling[0:(len(parameters_scaling) / 2)],
                                                                     [maxiter * popsize, len(parameters_scaling) / 2])])
                            if method == 'toc':
                                for sample in samples:
                                    self.objective_function_two_config_toc_sample(sample)
                            else:
                                print 'Unknown method to do multiple base configurations!'
                                return False
                            config = self.best_config
                            score = self.best_score
                            scores = self.best_scores
                        print 'Config: ', config
                        print 'Score: ', score
                        print 'Time to find scores for this set of parameters: %fs' % ((rospy.Time.now()-parameter_start_time).to_sec())
                        config = np.insert(config, 4, 0.)
                        config = np.insert(config, 4, 0.)
                        config = np.insert(config, 10, 0.)
                        config = np.insert(config, 10, 0.)
                        optimization_results[parameters] = [config, score]
                        # optimization_results[2, self.heady, self.start_x, self.start_y][0] = np.insert(optimization_results[2, self.heady, self.start_x, self.start_y][0], 4, 0.)
                        # optimization_results[2, self.heady, self.start_x, self.start_y][0] = np.insert(optimization_results[2, self.heady, self.start_x, self.start_y][0], 10, 0.)
                        # optimization_results[2, self.heady, self.start_x, self.start_y][0] = np.insert(optimization_results[2, self.heady, self.start_x, self.start_y][0], 10, 0.)
                    elif self.head_rest_angle > -1.:
                        # Deactivated head rest angle
                        # Parameters are: [x, y, th, z, bz, bth]
                        # maxiter = 10
                        # popsize = m.pow(5, 2)*100
                        parameters_min = np.array([0.2, -3., -m.pi-.001, 0., 0., 0.2, -3., -m.pi-.001, 0., 0.])
                        # parameters_max = np.array([3., 3., m.pi+.001, 0.3, 0.2, 3., 3., m.pi+.001, 0.3, 0.2])
                        # At Henry's the bed can only range a few centimeters because of the overbed table
                        parameters_max = np.array([3., 3., m.pi+.001, 0.3, 0.08, 3., 3., m.pi+.001, 0.3, 0.08])
                        parameters_scaling = (parameters_max-parameters_min)/4.
                        parameters_initialization = (parameters_max+parameters_min)/2.
                        parameters_initialization[1] = 1.0
                        parameters_initialization[6] = -1.0
                        opts2 = {'seed': 1234, 'ftarget': -1., 'popsize': popsize, 'maxiter': maxiter, 'maxfevals': 1e8, 'CMA_cmean': 0.25,
                                 'scaling_of_variables': list(parameters_scaling),
                                 'bounds': [list(parameters_min),
                                            list(parameters_max)]}

                        # optimization_results[2, self.heady, self.start_x, self.start_y] = [t for t in ((cma.fmin(self.objective_function_two_config_toc_sample,
                        print 'Working on heady location:', self.heady
                        optimization_results[parameters] = cma.fmin(self.objective_function_two_config_toc_sample,
                                                                    list(parameters_initialization),
                                                                    # [0.75, 0.75, 0., 0.15, 0., 0.75, -0.75, 0., 0.15, 0.],
                                                                    # [0., 0., 0., 0.15, 0.1, 35*m.pi/180, 0., 0., 0., 0.15, 0.1, 35*m.pi/180],
                                                                    1.,
                                                                    options=opts2)
                        # for self.start_x in np.arange(start_x_min, start_x_max, start_x_int)
                        # for self.start_y in np.arange(start_y_min, start_y_max, start_y_int)
                        # for self.heady in np.arange(heady_min, heady_max, heady_int)
                        config = optimization_results[parameters][0]
                        score = optimization_results[parameters][1]
                        config = np.insert(config, 5, np.radians(self.head_rest_angle))
                        config = np.insert(config, 11, np.radians(self.head_rest_angle))
                        optimization_results[parameters] = [config, score]
                    else:
                        # maxiter = 10
                        # popsize = m.pow(6, 2)*100
                        parameters_min = np.array([0.3, -2.3, m.radians(-270.) - 0.0001, 0., 0., 0.*m.pi/180.,
                                                   0.3, -2.3, m.radians(-270.) - 0.0001, 0., 0., 0.*m.pi/180.])
                         # parameters_max = np.array([ 3.,  3.,  m.pi+.001, 0.3, 0.2, 80.*m.pi/180.,  3.,  3.,  m.pi+.001, 0.3, 0.2, 80.*m.pi/180.])
                        # Henry's bed can only rise a few centimeters because of the overbed table
                        parameters_max = np.array([3.0, 2.3, m.radians(270.) + .0001, 0.3, 0.25, 75.*m.pi/180.,
                                                   3.0, 2.3, m.radians(270.) + .0001, 0.3, 0.25, 75.*m.pi/180.])
                        parameters_scaling = (parameters_max-parameters_min)/4.
                        parameters_initialization = (parameters_max+parameters_min)/2.
                        parameters_initialization[1] = 1.0
                        parameters_initialization[7] = -1.0
                        # Parameters are: [x, y, th, z, bz, bth]
                        if sampling == 'cma':
                            opts2 = {'seed': seed, 'ftarget': -1., 'popsize': popsize, 'maxiter': maxiter, 'maxfevals': 1e8, 'CMA_cmean': 0.25,
                                     'scaling_of_variables': list(parameters_scaling),
                                     'bounds': [list(parameters_min),
                                                list(parameters_max)]}

                            # optimization_results[2, self.heady, self.start_x, self.start_y] = [t for t in ((cma.fmin(self.objective_function_two_config_toc_sample,
                            print 'Working on heady location:', self.heady
                            if method == 'toc':
                                optimization_results[parameters] = cma.fmin(self.objective_function_two_config_toc_sample,
                                                                            list(parameters_initialization),
                                                                            # [0.5, 0.75, 0., 0.15, 0., 35*m.pi/180, 0.5, -0.75, 0., 0.15, 0., 35*m.pi/180],
                                                                            # [0., 0., 0., 0.15, 0.1, 35*m.pi/180, 0., 0., 0., 0.15, 0.1, 35*m.pi/180],
                                                                            1.,
                                                                            options=opts2)
                            # for self.start_x in np.arange(start_x_min, start_x_max, start_x_int)
                            # for self.start_y in np.arange(start_y_min, start_y_max, start_y_int)
                            # for self.heady in np.arange(heady_min, heady_max, heady_int)
                            config = optimization_results[parameters][0]
                            score = optimization_results[parameters][1]
                            scores = self.best_scores
                            if score != self.best_score:
                                print 'There is something weird. The best score from cma optimization output' \
                                      'differs from what I extracted from it.'
                                print 'config:\n',config
                                print 'score:\n',score
                                config = self.best_config
                                score = self.best_score
                                print 'config:\n', config
                                print 'score:\n', score
                        elif sampling == 'uniform':
                            self.best_config = None
                            self.best_score = 1000.
                            random_state = np.random.RandomState(seed=seed)
                            samples = np.hstack([random_state.uniform(parameters_min[0:(len(parameters_min) / 2)],
                                                                      parameters_max[0:(len(parameters_min) / 2)],
                                                                      [maxiter * popsize, len(parameters_min) / 2]),
                                                 random_state.uniform(parameters_min[0:(len(parameters_min) / 2)],
                                                                      parameters_max[0:(len(parameters_min) / 2)],
                                                                      [maxiter * popsize, len(parameters_min) / 2])])
                            if method == 'toc':
                                for sample in samples:
                                    self.objective_function_two_config_toc_sample(sample)
                            else:
                                print 'Unknown method to do multiple base configurations!'
                                return False
                            config = self.best_config
                            score = self.best_score
                            scores = self.best_scores
                        elif sampling == 'gaussian':
                            self.best_config = None
                            self.best_score = 1000.
                            random_state = np.random.RandomState(seed=seed)
                            samples = np.hstack(
                                [random_state.normal(parameters_initialization[0:(len(parameters_scaling) / 2)],
                                                     parameters_scaling[0:(len(parameters_scaling) / 2)],
                                                     [maxiter * popsize, len(parameters_scaling) / 2]),
                                 random_state.normal(parameters_initialization[0:(len(parameters_scaling) / 2)],
                                                     parameters_scaling[0:(len(parameters_scaling) / 2)],
                                                     [maxiter * popsize, len(parameters_scaling) / 2])])
                            if method == 'toc':
                                for sample in samples:
                                    self.objective_function_two_config_toc_sample(sample)
                            else:
                                print 'Unknown method to do multiple base configurations!'
                                return False
                            config = self.best_config
                            score = self.best_score
                            scores = self.best_scores
                        # optimization_results[parameters] = [config, score]
                    # optimization_results[parameters].append((rospy.Time.now()-parameter_start_time).to_sec())
                    print 'Config:', config
                    print 'Score:',score
                    print 'Scores:',scores

                    # score_stuff[self.heady, self.distance] = self.compare_results_one_vs_two_configs(optimization_results[1, self.heady, self.distance], optimization_results[2, self.heady, self.distance])
                    config, score = self.check_which_num_base_is_better(config, scores)
                    score_stuff[parameters] = [config, score, (rospy.Time.now()-parameter_start_time).to_sec()]
                    print 'Time to find scores for this set of parameters: %fs' % ((rospy.Time.now()-parameter_start_time).to_sec())
                    print 'Time elapsed so far for parameters: %fs' % ((rospy.Time.now()-scoring_start_time).to_sec())

        # score_stuff = []  # np.zeros([len(optimization_results), 9])
        #
        #     score_stuff[num] = list(flatten([optimization_results[num][0], optimization_results[num][1], optimization_results[num][2][0], optimization_results[num][2][1]]))

        print 'SCORE RESULTS:'
        for item in score_stuff:
            print '(<model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>):\n', item
            print '[[[x], [y], [th], [z], [bz], [bth]], score, time]'
            print 'Or, if there are two configurations:'
            print '[[[x1, x2], [y1, y2], [th1, th2], [z1, z2], [bz1, bz2], [bth1, bth2]], score, time]'
            print score_stuff[item]

        print 'Time to generate all scores for individual base locations: %fs' % ((rospy.Time.now()-start_time).to_sec())
        print 'Number of configurations that were evaluated: ', len(score_stuff)
        # start_time = time.time()

        return score_stuff

    def check_which_num_base_is_better(self, configs, scores):
        result_bases = configs
        # score = results[1]
        # time = results[2]
        base1 = np.reshape(result_bases[0:6], [6, 1])
        base2 = np.reshape(result_bases[6:12], [6, 1])
        double_base = np.hstack([base1, base2])
        bases = []
        bases.append(base1)
        bases.append(base2)
        bases.append(double_base)
        # scores = []
        # for base in bases:
        # self.visualize = True
        # scores = self.score_two_configs(double_base)
        print 'Scores are: ', scores
        ind = scores.argmin()
        if ind == 2:
            print 'Two bases was better'
        else:
            print 'One base was better. It was base (0 or 1) from the two base config solution:', ind
        # output = bases[ind], scores[ind]
        # if 10.-scores[ind] < 0.95*(10.-score):
        #     print 'Somehow the best score when comparing the single and double base configurations was less than the' \
        #           'score given earlier, even given the discount on two configs'
        return bases[ind], scores[ind]

    def objective_function_one_config_toc_cma(self, current_parameters):
        # current_parameters = [  1.21497982,  0.97523797, -3.14114645,  0.29979307,  0.07958062,
        # 0.95115451]
        # self.heady = 0.09
        if not self.a_model_is_loaded:
            print 'Somehow a model has not been loaded. This is bad!'
            return None
        if len(current_parameters) == 6:
            x = current_parameters[0]
            y = current_parameters[1]
            th = current_parameters[2]
            z = current_parameters[3]
            bz = current_parameters[4]
            bth = current_parameters[5]
        else:
            x = current_parameters[0]
            y = current_parameters[1]
            th = current_parameters[2]
            z = current_parameters[3]
            bz = 0.
            bth = 0.

        #print 'Calculating new score'
        #starttime = time.time()
        origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0.,         x],
                                  [ m.sin(th),  m.cos(th),     0.,         y],
                                  [        0.,         0.,     1.,        0.],
                                  [        0.,         0.,     0.,        1.]])
        self.robot.SetTransform(np.array(origin_B_pr2))
        v = self.robot.GetActiveDOFValues()
        v[self.robot.GetJoint('torso_lift_joint').GetDOFIndex()] = z
        self.robot.SetActiveDOFValues(v, 2)

        if self.model == 'chair':
            self.env.UpdatePublishedBodies()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')
            ual = self.wheelchair.GetLink('wheelchair/arm_left_link')
            uar = self.wheelchair.GetLink('wheelchair/arm_right_link')
            fal = self.wheelchair.GetLink('wheelchair/forearm_left_link')
            far = self.wheelchair.GetLink('wheelchair/forearm_right_link')
            thl = self.wheelchair.GetLink('wheelchair/quad_left_link')
            thr = self.wheelchair.GetLink('wheelchair/quad_right_link')
            kneel = self.wheelchair.GetLink('wheelchair/calf_left_link')
            kneer = self.wheelchair.GetLink('wheelchair/calf_right_link')
            footl = self.wheelchair.GetLink('wheelchair/foot_left_link')
            footr = self.wheelchair.GetLink('wheelchair/foot_right_link')
            ch = self.wheelchair.GetLink('wheelchair/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references[thing] = origin_B_head
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references[thing] = origin_B_pr2
                    # self.origin_B_references[thing] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)
            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(self.origin_B_references[int(self.reference_mat[thing])]*np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
#            for target in self.goals:
#                self.goal_list.append(pr2_B_head*np.matrix(target[0]))
#                self.selection_mat.append(target[1])
            self.set_goals()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')

        elif self.model == 'autobed':
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            self.set_autobed(bz, bth, self.headx, self.heady)
            self.env.UpdatePublishedBodies()

            headmodel = self.autobed.GetLink('autobed/head_link')
            ual = self.autobed.GetLink('autobed/arm_left_link')
            uar = self.autobed.GetLink('autobed/arm_right_link')
            fal = self.autobed.GetLink('autobed/forearm_left_link')
            far = self.autobed.GetLink('autobed/forearm_right_link')
            thl = self.autobed.GetLink('autobed/quad_left_link')
            thr = self.autobed.GetLink('autobed/quad_right_link')
            kneel = self.autobed.GetLink('autobed/calf_left_link')
            kneer = self.autobed.GetLink('autobed/calf_right_link')
            footl = self.autobed.GetLink('autobed/foot_left_link')
            footr = self.autobed.GetLink('autobed/foot_right_link')
            ch = self.autobed.GetLink('autobed/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.origin_B_references = []
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references.append(origin_B_head)
                    # self.origin_B_references.append(np.matrix(headmodel.GetTransform())
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references.append(origin_B_pr2)
                    # self.origin_B_references[i] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)

            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(self.origin_B_references[int(self.reference_mat[thing])]*np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
            # for target in self.goals:
            #     self.goal_list.append(pr2_B_head*np.matrix(target[0]))
            #     self.selection_mat.append(target[1])
            self.set_goals()
        elif self.model is None:
            self.env.UpdatePublishedBodies()
        else:
            print 'I GOT A BAD MODEL. NOT SURE WHAT TO DO NOW!'
        distance = 10000000.
        out_of_reach = True

        for origin_B_grasp in self.origin_B_grasps:
            pr2_B_goal = origin_B_pr2.I*origin_B_grasp
            distance = np.min([np.linalg.norm(pr2_B_goal[:2, 3]), distance])

            if distance <= 1.25:
                out_of_reach = False
                # print 'not out of reach'
                break
        if out_of_reach:
            # print 'location is out of reach'
            return 10. +1.+ 20.*(distance - 1.25)

        #print 'Time to update autobed things: %fs'%(time.time()-starttime)
        reach_score = 0.
        manip_score = 0.
        goal_scores = []
        # std = 1.
        # mean = 0.
        # allmanip = []
        manip = 0.
        reached = 0.

        #allmanip2=[]
        # space_score = (1./(std*(m.pow((2.*m.pi), 0.5))))*m.exp(-(m.pow(np.linalg.norm([x, y])-mean, 2.)) /
        #                                                        (2.*m.pow(std, 2.)))
        #print space_score
        with self.robot:
            v = self.robot.GetActiveDOFValues()
            if self.arm[0] == 'l':
                arm_sign = 1
            else:
                arm_sign = -1
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 0.4
            v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
            v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.0
            v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (-3.5)
            v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -0.5
            v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
            v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()]
            self.robot.SetActiveDOFValues(v, 2)
            self.env.UpdatePublishedBodies()
            not_close_to_collision = True
            if self.env.CheckCollision(self.robot):
                not_close_to_collision = False
            '''
            origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0., x+.02],
                                      [ m.sin(th),  m.cos(th),     0., y+.02],
                                      [        0.,         0.,     1.,        0.],
                                      [        0.,         0.,     0.,        1.]])
            self.robot.SetTransform(np.array(origin_B_pr2))
            self.env.UpdatePublishedBodies()
            if self.manip.CheckIndependentCollision(op.CollisionReport()):
                not_close_to_collision = False

            origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0., x-.02],
                                      [ m.sin(th),  m.cos(th),     0., y+.02],
                                      [        0.,         0.,     1.,        0.],
                                      [        0.,         0.,     0.,        1.]])
            self.robot.SetTransform(np.array(origin_B_pr2))
            self.env.UpdatePublishedBodies()
            if self.manip.CheckIndependentCollision(op.CollisionReport()):
                not_close_to_collision = False

            origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0., x-.02],
                                      [ m.sin(th),  m.cos(th),     0., y-.02],
                                      [        0.,         0.,     1.,        0.],
                                      [        0.,         0.,     0.,        1.]])
            self.robot.SetTransform(np.array(origin_B_pr2))
            self.env.UpdatePublishedBodies()
            if self.manip.CheckIndependentCollision(op.CollisionReport()):
                not_close_to_collision = False

            origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0., x+.02],
                                      [ m.sin(th),  m.cos(th),     0., y-.02],
                                      [        0.,         0.,     1.,        0.],
                                      [        0.,         0.,     0.,        1.]])
            self.robot.SetTransform(np.array(origin_B_pr2))
            self.env.UpdatePublishedBodies()
            if self.manip.CheckIndependentCollision(op.CollisionReport()):
                not_close_to_collision = False

            origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0., x],
                                      [ m.sin(th),  m.cos(th),     0., y],
                                      [        0.,         0.,     1.,        0.],
                                      [        0.,         0.,     0.,        1.]])
            self.robot.SetTransform(np.array(origin_B_pr2))
            self.env.UpdatePublishedBodies()
            '''
            if not_close_to_collision:
                # print 'No base collision! single config distance: ', distance
                reached = np.zeros(len(self.origin_B_grasps))
                manip = np.zeros(len(self.origin_B_grasps))
                for head_angle in self.head_angles:
                    self.rotate_head_and_update_goals(head_angle[0], head_angle[1], origin_B_pr2)
                    for num, Tgrasp in enumerate(self.origin_B_grasps):
                        sols = []
                        sols = self.manip.FindIKSolutions(Tgrasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)
                        # if not list(sols):
                        #     v = self.robot.GetActiveDOFValues()
                        #     v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_pan_joint').GetDOFIndex()] = -0.023593
                        #     v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_lift_joint').GetDOFIndex()] = 1.1072800
                        #     v[self.robot.GetJoint(self.opposite_arm[0]+'_upper_arm_roll_joint').GetDOFIndex()] = -1.5566882
                        #     v[self.robot.GetJoint(self.opposite_arm[0]+'_elbow_flex_joint').GetDOFIndex()] = -2.124408
                        #     v[self.robot.GetJoint(self.opposite_arm[0]+'_forearm_roll_joint').GetDOFIndex()] = -1.4175
                        #     v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_flex_joint').GetDOFIndex()] = -1.8417
                        #     v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_roll_joint').GetDOFIndex()] = 0.21436
                        #     self.robot.SetActiveDOFValues(v, 2)
                        #     self.env.UpdatePublishedBodies()
                        #     sols = self.manip.FindIKSolutions(Tgrasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)

                        # manip[num] = 0.
                        # reached[num] = 0.
                        if list(sols):  # not None:
                            
                            for solution in sols:
                                 
                                # if m.degrees(solution[3])<-45:
                                #     continue
                                # else:
                                reached[num] = 1.
                                self.robot.SetDOFValues(solution, self.manip.GetArmIndices())
                                self.env.UpdatePublishedBodies()

                                J = np.matrix(np.vstack([self.manip.CalculateJacobian(), self.manip.CalculateAngularVelocityJacobian()]))
                                try:
                                    joint_limit_weight = self.gen_joint_limit_weight(solution)
                                    manip[num] = np.max([copy.copy((m.pow(np.linalg.det(J*joint_limit_weight*J.T), (1./6.)))/(np.trace(J*joint_limit_weight*J.T)/6.)), manip[num]])
                                except ValueError:
                                    print 'WARNING!!'
                                    print 'Jacobian may be singular or close to singular'
                                    print 'Determinant of J*JT is: ', np.linalg.det(J*J.T)
                                    manip[num] = np.max([0., manip[num]])
                                if self.visualize:
                                    rospy.sleep(1.0)
                for num in xrange(len(reached)):
                    manip_score += copy.copy(reached[num] * manip[num]*self.weights[num])
                    reach_score += copy.copy(reached[num] * self.weights[num])
            else:
                # print 'In base collision! single config distance: ', distance
                if distance < 2.0:
                    return 10. + 1. + (1.25 - distance)

        # Set the weights for the different scores.
        beta = 10.  # Weight on number of reachable goals
        gamma = 1.  # Weight on manipulability of arm at each reachable goal
        zeta = .0007  # Weight on distance to move to get to that goal location
        if reach_score == 0.:
            return 10. + 2*random.random()
        else:
            # print 'Reach score: ', reach_score
            # print 'Manip score: ', manip_score
            return 10.-beta*reach_score-gamma*manip_score  # +zeta*self.distance

    def objective_function_two_config_toc_sample(self, current_parameters):
        if not self.a_model_is_loaded:
            print 'Somehow a model has not been loaded. This is bad!'
            return None
        # print current_parameters
        # print len(current_parameters)
        # print 'head rest angle: ', self.head_rest_angle
        # current_parameters = list(flatten(np.reshape([[ 1.10995678,  0.47979084],
        #                                               [ 0.6339488 , -0.82258422],
        #                                               [-1.9750257 , -4.41014986],
        #                                               [ 0.27075026,  0.14017833],
        #                                               [ 0.17188331,  0.08067813],
        #                                               [ 0.93374424,  0.21362207]],[12,1],1)))
        if len(current_parameters) == 12:
            x = [current_parameters[0], current_parameters[6]]
            y = [current_parameters[1], current_parameters[7]]
            th = [current_parameters[2], current_parameters[8]]
            z = [current_parameters[3], current_parameters[9]]
            bz = [current_parameters[4], current_parameters[10]]
            bth = [current_parameters[5], current_parameters[11]]
        elif len(current_parameters) == 10:
            x = [current_parameters[0], current_parameters[5]]
            y = [current_parameters[1], current_parameters[6]]
            th = [current_parameters[2], current_parameters[7]]
            z = [current_parameters[3], current_parameters[8]]
            bz = [current_parameters[4], current_parameters[9]]
            bth = [np.radians(self.head_rest_angle), np.radians(self.head_rest_angle)]
        else:
            x = [current_parameters[0], current_parameters[4]]
            y = [current_parameters[1], current_parameters[5]]
            th = [current_parameters[2], current_parameters[6]]
            z = [current_parameters[3], current_parameters[7]]
            bz = [0., 0.]
            bth = [0., 0.]
        # print bth
        # print bz
        # x = [0.3, 0.3]

        # planar_difference = np.linalg.norm([x[0]-x[1], y[0]-y[1]])
        # if planar_difference < 0.2:
        #     return 10 + 10*(0.2 - planar_difference)

        # Cost on distanced moved.
        # travel = [np.linalg.norm([self.start_x - x[0], self.start_y - y[0]]),
        #           np.linalg.norm([self.start_x - x[1], self.start_y - y[1]])]
        # travel.append(travel[0]+travel[1])

        # distance = 10000000.
        out_of_reach = False

        reach_score = np.array([0., 0., 0.])
        manip_score = np.array([0., 0., 0.])
        reached = np.zeros([len(self.goals), 3])
        manip = np.zeros([len(self.goals), 3])

        # better_config = np.array([-1]*len(self.goals))
        best = None
        for num in xrange(len(self.goals)):
            fully_collided = 0
            # manip = [0., 0., 0.]
            # reached = [0., 0., 0.]
            distance = [100000., 100000.]
            for config_num in xrange(len(x)):
                origin_B_pr2 = np.matrix([[ m.cos(th[config_num]), -m.sin(th[config_num]),     0., x[config_num]],
                                          [ m.sin(th[config_num]),  m.cos(th[config_num]),     0., y[config_num]],
                                          [        0.,         0.,     1.,        0.],
                                          [        0.,         0.,     0.,        1.]])
                self.robot.SetTransform(np.array(origin_B_pr2))
                v = self.robot.GetActiveDOFValues()
                v[self.robot.GetJoint('torso_lift_joint').GetDOFIndex()] = z[config_num]
                self.robot.SetActiveDOFValues(v, 2)
                # self.env.UpdatePublishedBodies()

                for head_angle in self.head_angles:
                    self.rotate_head_only(head_angle[0], head_angle[1])
                    if self.model == 'chair':
                        self.selection_mat = np.zeros(1)
                        self.goal_list = np.zeros([1, 4, 4])

                        self.env.UpdatePublishedBodies()
                        headmodel = self.wheelchair.GetLink('wheelchair/head_link')
                        ual = self.wheelchair.GetLink('wheelchair/arm_left_link')
                        uar = self.wheelchair.GetLink('wheelchair/arm_right_link')
                        fal = self.wheelchair.GetLink('wheelchair/forearm_left_link')
                        far = self.wheelchair.GetLink('wheelchair/forearm_right_link')
                        thl = self.wheelchair.GetLink('wheelchair/quad_left_link')
                        thr = self.wheelchair.GetLink('wheelchair/quad_right_link')
                        kneel = self.wheelchair.GetLink('wheelchair/calf_left_link')
                        kneer = self.wheelchair.GetLink('wheelchair/calf_right_link')
                        footl = self.wheelchair.GetLink('wheelchair/foot_left_link')
                        footr = self.wheelchair.GetLink('wheelchair/foot_right_link')
                        ch = self.wheelchair.GetLink('wheelchair/upper_body_link')
                        origin_B_head = np.matrix(headmodel.GetTransform())
                        origin_B_ual = np.matrix(ual.GetTransform())
                        origin_B_uar = np.matrix(uar.GetTransform())
                        origin_B_fal = np.matrix(fal.GetTransform())
                        origin_B_far = np.matrix(far.GetTransform())
                        origin_B_thl = np.matrix(thl.GetTransform())
                        origin_B_thr = np.matrix(thr.GetTransform())
                        origin_B_kneel = np.matrix(kneel.GetTransform())
                        origin_B_kneer = np.matrix(kneer.GetTransform())
                        origin_B_footl = np.matrix(footl.GetTransform())
                        origin_B_footr = np.matrix(footr.GetTransform())
                        origin_B_ch = np.matrix(ch.GetTransform())
                        self.origin_B_references = []
                        # for thing in xrange(len(self.reference_names)):
                        thing = int(self.goals[num, 2])
                        if self.reference_names[thing] == 'head':
                            self.origin_B_references.append(origin_B_head)
                        elif self.reference_names[thing] == 'base_link':
                            self.origin_B_references.append(origin_B_pr2)
                        elif self.reference_names[thing] == 'upper_arm_left':
                            self.origin_B_references.append(origin_B_ual)
                        elif self.reference_names[thing] == 'upper_arm_right':
                            self.origin_B_references.append(origin_B_uar)
                        elif self.reference_names[thing] == 'forearm_left':
                            self.origin_B_references.append(origin_B_fal)
                        elif self.reference_names[thing] == 'forearm_right':
                            self.origin_B_references.append(origin_B_far)
                        elif self.reference_names[thing] == 'thigh_left':
                            self.origin_B_references.append(origin_B_thl)
                        elif self.reference_names[thing] == 'thigh_right':
                            self.origin_B_references.append(origin_B_thr)
                        elif self.reference_names[thing] == 'knee_left':
                            self.origin_B_references.append(origin_B_kneel)
                        elif self.reference_names[thing] == 'knee_right':
                            self.origin_B_references.append(origin_B_kneer)
                        elif self.reference_names[thing] == 'chest':
                            self.origin_B_references.append(origin_B_ch)
                        else:
                            print 'The refence options is bogus! I dont know what to do!'
                            return
                        self.goal_list[0] = copy.copy(self.origin_B_references[0] * np.matrix(self.goals[num, 0]))
                        self.selection_mat[0] = copy.copy(self.goals[num, 1])
                        self.set_goals(single_goal=True)

                    elif self.model == 'autobed':
                        self.selection_mat = np.zeros(1)
                        self.goal_list = np.zeros([1, 4, 4])

                        self.set_autobed(bz[config_num], bth[config_num], self.headx, self.heady)
                        self.env.UpdatePublishedBodies()
                        headmodel = self.autobed.GetLink('autobed/head_link')
                        ual = self.autobed.GetLink('autobed/arm_left_link')
                        uar = self.autobed.GetLink('autobed/arm_right_link')
                        fal = self.autobed.GetLink('autobed/forearm_left_link')
                        far = self.autobed.GetLink('autobed/forearm_right_link')
                        thl = self.autobed.GetLink('autobed/quad_left_link')
                        thr = self.autobed.GetLink('autobed/quad_right_link')
                        kneel = self.autobed.GetLink('autobed/calf_left_link')
                        kneer = self.autobed.GetLink('autobed/calf_right_link')
                        footl = self.autobed.GetLink('autobed/foot_left_link')
                        footr = self.autobed.GetLink('autobed/foot_right_link')
                        ch = self.autobed.GetLink('autobed/upper_body_link')
                        origin_B_head = np.matrix(headmodel.GetTransform())
                        origin_B_ual = np.matrix(ual.GetTransform())
                        origin_B_uar = np.matrix(uar.GetTransform())
                        origin_B_fal = np.matrix(fal.GetTransform())
                        origin_B_far = np.matrix(far.GetTransform())
                        origin_B_thl = np.matrix(thl.GetTransform())
                        origin_B_thr = np.matrix(thr.GetTransform())
                        origin_B_kneel = np.matrix(kneel.GetTransform())
                        origin_B_kneer = np.matrix(kneer.GetTransform())
                        origin_B_footl = np.matrix(footl.GetTransform())
                        origin_B_footr = np.matrix(footr.GetTransform())
                        origin_B_ch = np.matrix(ch.GetTransform())
                        self.origin_B_references = []
                        # for thing in xrange(len(self.reference_names)):
                        thing = int(self.goals[num, 2])
                        if self.reference_names[thing] == 'head':
                            self.origin_B_references.append(origin_B_head)
                        elif self.reference_names[thing] == 'base_link':
                            self.origin_B_references.append(origin_B_pr2)
                        elif self.reference_names[thing] == 'upper_arm_left':
                            self.origin_B_references.append(origin_B_ual)
                        elif self.reference_names[thing] == 'upper_arm_right':
                            self.origin_B_references.append(origin_B_uar)
                        elif self.reference_names[thing] == 'forearm_left':
                            self.origin_B_references.append(origin_B_fal)
                        elif self.reference_names[thing] == 'forearm_right':
                            self.origin_B_references.append(origin_B_far)
                        elif self.reference_names[thing] == 'thigh_left':
                            self.origin_B_references.append(origin_B_thl)
                        elif self.reference_names[thing] == 'thigh_right':
                            self.origin_B_references.append(origin_B_thr)
                        elif self.reference_names[thing] == 'knee_left':
                            self.origin_B_references.append(origin_B_kneel)
                        elif self.reference_names[thing] == 'knee_right':
                            self.origin_B_references.append(origin_B_kneer)
                        elif self.reference_names[thing] == 'foot_left':
                            self.origin_B_references.append(origin_B_footl)
                        elif self.reference_names[thing] == 'foot_right':
                            self.origin_B_references.append(origin_B_footr)
                        elif self.reference_names[thing] == 'chest':
                            self.origin_B_references.append(origin_B_ch)
                        else:
                            print 'The refence options is bogus! I dont know what to do!'
                            return

                        # for thing in xrange(len(self.goals)):
                        # thing = num
                        self.goal_list[0] = copy.copy(self.origin_B_references[0]*np.matrix(self.goals[num, 0]))
                        self.selection_mat[0] = copy.copy(self.goals[num, 1])
                        self.set_goals(single_goal=True)
                    else:
                        print 'I GOT A BAD MODEL. NOT SURE WHAT TO DO NOW!'

                    # for origin_B_goal in self.origin_B_grasps:
                    origin_B_grasp = self.origin_B_grasps[0]
                    pr2_B_goal = origin_B_pr2.I*origin_B_grasp
                    this_distance = np.linalg.norm(pr2_B_goal[:2, 3])
                    distance[config_num] = np.min([this_distance, distance[config_num]])
                    if this_distance < 1.25:
                        with self.robot:
                            v = self.robot.GetActiveDOFValues()
                            if self.arm[0] == 'l':
                                arm_sign = 1
                            else:
                                arm_sign = -1
                            in_collision = True
                            v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
                            v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                            v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (
                            1.9)
                            v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                            v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (
                            -3.5)
                            v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                            v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
                            v[self.robot.GetJoint(
                                self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
                            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                            v[self.robot.GetJoint(
                                self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
                            v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                            v[self.robot.GetJoint(
                                self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
                            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
                            self.robot.SetActiveDOFValues(v, 2)
                            self.env.UpdatePublishedBodies()
                            # rospy.sleep(10)
                            in_collision = self.env.CheckCollision(self.robot)
                            if in_collision:
                                v[self.robot.GetJoint(
                                    self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * 3.14 / 2
                                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                                v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.

                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = -3.14 / 2
                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                                v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.
                                self.robot.SetActiveDOFValues(v, 2)
                                self.env.UpdatePublishedBodies()
                                in_collision = self.env.CheckCollision(self.robot)
                                # rospy.sleep(10)
                            if in_collision:
                                v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (
                                1.8)
                                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                                v[self.robot.GetJoint(
                                    self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
                                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (
                                -3.5)
                                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0

                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = -3.14 / 2
                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                                v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.
                                self.robot.SetActiveDOFValues(v, 2)
                                self.env.UpdatePublishedBodies()
                                in_collision = self.env.CheckCollision(self.robot)
                                # rospy.sleep(10)
                            if in_collision:
                                v[self.robot.GetJoint(
                                    self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * 3.14 / 2
                                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                                v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.

                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
                                v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                                v[self.robot.GetJoint(
                                    self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
                                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
                                self.robot.SetActiveDOFValues(v, 2)
                                self.env.UpdatePublishedBodies()
                                in_collision = self.env.CheckCollision(self.robot)

                            if not in_collision:
                                Tgrasp = self.origin_B_grasps[0]

                                # print 'no collision!'
                                # for num, Tgrasp in enumerate(self.origin_B_grasps):
                                    # sol = None
                                    # sol = self.manip.FindIKSolution(Tgrasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)

                                    #sol = self.manip.FindIKSolution(Tgrasp,filteroptions=op.IkFilterOptions.IgnoreSelfCollisions)
                                sols = []
                                sols = self.manip.FindIKSolutions(Tgrasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)

                                if list(sols):  # not None:
                                    reached[num, config_num] = 1
                                    for solution in sols:
                                        self.robot.SetDOFValues(solution, self.manip.GetArmIndices())
                                        self.env.UpdatePublishedBodies()
                                        J = np.matrix(np.vstack([self.manip.CalculateJacobian(),
                                                                 self.manip.CalculateAngularVelocityJacobian()]))
                                        try:
                                            joint_limit_weight = self.gen_joint_limit_weight(solution)
                                            manip[num, config_num] = np.max([copy.copy(
                                                (m.pow(np.linalg.det(J*joint_limit_weight*J.T), (1./6.)))/(
                                                    np.trace(J*joint_limit_weight*J.T)/6.)),
                                                manip[num, config_num]])
                                        except ValueError:
                                            print 'WARNING!!'
                                            print 'Jacobian may be singular or close to singular'
                                            print 'Determinant of J*JT is: ', np.linalg.det(J*J.T)
                                            manip[num, config_num] = np.max([0., manip[num, config_num]])
                                    if self.visualize:
                                        rospy.sleep(1.0)
                            else:
                                # print 'Too close, robot base in collision with bed'
                                # print 10 + 1.25 - distance
                                fully_collided += 1
                                if this_distance > 3:
                                    print 'This shouldnt be possible. Distance is: ', this_distance
                                # if this_distance < 0.5:
                                #     return 10 + 2. - this_distance
                                # else:
                                #     return 10 + 2*random.random()
                if fully_collided == 2 and np.min(distance) < 2.:
                    this_score = 10. + 1. + (1.25 - np.min(distance))
                    if this_score < self.best_score:
                        self.best_config = current_parameters
                        self.best_score = this_score
                        self.best_scores = np.tile(this_score, 3)
                    return this_score
            reached[num, 2] = np.max(reached[num])
            manip[num, 2] = np.max(manip[num])
        # if np.sum(reached[:, 2]) > np.sum(reached[num, 0]) + 0.00001 and np.sum(reached[:, 2]) > np.sum(reached[num, 1]) + 0.00001:
        #     best = 2
        # elif np.sum(reached[num, 0]) > np.sum(reached[num, 1]) + 0.00001:
        #     best = 0
        # elif np.sum(reached[num, 1]) > np.sum(reached[num, 0]) + 0.00001:
        #     best = 1
        # elif np.sum(manip[:, 2])*0.95 > np.sum(manip[num, 0]) + 0.00001 and np.sum(manip[:, 2])*0.95 > np.sum(manip[num, 1]) + 0.00001:
        #     best = 2
        # elif np.sum(manip[num, 0]) > np.sum(manip[num, 1]) + 0.00001:
        #     best = 0
        # else:  # if np.sum(manip[num, 1]) > np.sum(manip[num, 0]) + 0.00001:
        #     best = 1

            # if manip[0] >= manip[1] and manip[0] > 0.:
            #     better_config[num] = 0
            # elif manip[0] < manip[1] and manip[1] > 0:
            #     better_config[num] = 1
        # print 'Manip score: ', manip_score
        # print 'Reach score: ', reach_score
        # print 'Distance: ', distance

        over_dist = 0.
        for dist in distance:
            if dist >= 1.25:
                over_dist += 2*(dist - 1.25)
        if over_dist > 0.001:
            this_score = 10 + 1 + 10*over_dist
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
                self.best_scores = np.tile(this_score, 3)
            return this_score

        reach_score[0] = np.sum(reached[:, 0] * self.weights[0])
        reach_score[1] = np.sum(reached[:, 1] * self.weights[0])
        reach_score[2] = np.sum(reached[:, 2] * self.weights[0])

        if np.max(reach_score) == 0:
            this_score = 10 + 2*random.random()
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
                self.best_scores = np.tile(this_score,3)
            return this_score

        manip_score[0] = np.sum(reached[:, 0]*manip[:, 0]*self.weights[0])
        manip_score[1] = np.sum(reached[:, 1]*manip[:, 1]*self.weights[0])
        manip_score[2] = np.sum(reached[:, 2]*manip[:, 2]*self.weights[0])*0.95



        # if reach_score == 0:
        #     if np.min(distance) >= 0.8:
        #         # output =
        #         # print output
        #         return 10 + 1 + 2*(np.min(distance) - 0.8)
        # if 0 not in better_config or 1 not in better_config:
        #     return 10. + 2*random.random()
        # else:
        ## Set the weights for the different scores.
        beta = 10.  # Weight on number of reachable goals
        gamma = 1.  # Weight on manipulability of arm at each reachable goal
        zeta = .05  # Weight on distance to move to get to that goal location
        # thisScore =
        # print 'Reach score: ', reach_score
        # print 'Manip score: ', manip_score
        # print 'Calculated score: ', 10.-beta*reach_score-gamma*manip_score
        best = None

        # Travel cost
        # travel_score = np.array([0., 0., 0.])
        # travel_score[0] = np.min([travel[0], 2.0])
        # travel_score[1] = np.min([travel[1], 2.0])
        # travel_score[2] = np.min([travel[2], 2.0])

        # 1. - m.pow(1.0, np.abs(2.0 - travel[0]))
        # print 'reach score', reach_score
        # print 'manip score', manip_score
        # print 'travel score', travel_score

        outputs = 10. - beta*reach_score - gamma*manip_score #+ zeta*travel_score
        # print 'outputs', outputs
        best = np.argmin(outputs)
        if np.min(outputs) < -1.0:
            print 'reach score', reach_score
            print 'manip score', manip_score
            #print 'travel score', travel_score
            print outputs
        if outputs[best] < -1.0:
            print 'reach score', reach_score
            print 'manip score', manip_score
            #print 'travel score', travel_score
            print outputs
        this_score = outputs[best]
        if this_score < self.best_score:
            self.best_config = current_parameters
            self.best_score = this_score
            self.best_scores = outputs

        #print self.best_scores
        return this_score
        # return 10.-beta*reach_score-gamma*manip_score  # +zeta*self.distance

    def score_two_configs(self, config):
        if self.visualize:
            self.env.SetViewer('qtcoin')
            rospy.sleep(5)
        x = config[0]
        y = config[1]
        th = config[2]
        z = config[3]
        bz = config[4]
        bth = config[5]
        reach_score = []
        manip_score = []

        # for num in xrange(len(x)+1):
        #     reach_score.append(0.)
        #     manip_score.append(0.)

        # Cost on distance traveled
        # travel = [np.linalg.norm([self.start_x - x[0], self.start_y - y[0]]),
        #           np.linalg.norm([self.start_x - x[1], self.start_y - y[1]])]
        # travel.append(travel[0]+travel[1])

        reach_score = np.array([0., 0., 0.])
        manip_score = np.array([0., 0., 0.])
        reached = np.zeros([len(self.goals), 3])
        manip = np.zeros([len(self.goals), 3])

        for num in xrange(len(self.goals)):
            fully_collided = 0
            # manip = [0., 0., 0.]
            # reached = [0., 0., 0.]
            distance = [100000., 100000.]
            for config_num in xrange(len(x)):
                origin_B_pr2 = np.matrix([[ m.cos(th[config_num]), -m.sin(th[config_num]),     0., x[config_num]],
                                          [ m.sin(th[config_num]),  m.cos(th[config_num]),     0., y[config_num]],
                                          [        0.,         0.,     1.,        0.],
                                          [        0.,         0.,     0.,        1.]])
                self.robot.SetTransform(np.array(origin_B_pr2))
                v = self.robot.GetActiveDOFValues()
                v[self.robot.GetJoint('torso_lift_joint').GetDOFIndex()] = z[config_num]
                self.robot.SetActiveDOFValues(v, 2)
                # self.env.UpdatePublishedBodies()

                for head_angle in self.head_angles:

                    self.rotate_head_only(head_angle[0], head_angle[1])

                    if self.model == 'chair':
                        self.env.UpdatePublishedBodies()
                        headmodel = self.wheelchair.GetLink('wheelchair/head_link')
                        ual = self.wheelchair.GetLink('wheelchair/arm_left_link')
                        uar = self.wheelchair.GetLink('wheelchair/arm_right_link')
                        fal = self.wheelchair.GetLink('wheelchair/forearm_left_link')
                        far = self.wheelchair.GetLink('wheelchair/forearm_right_link')
                        thl = self.wheelchair.GetLink('wheelchair/quad_left_link')
                        thr = self.wheelchair.GetLink('wheelchair/quad_right_link')
                        kneel = self.wheelchair.GetLink('wheelchair/calf_left_link')
                        kneer = self.wheelchair.GetLink('wheelchair/calf_right_link')
                        footl = self.wheelchair.GetLink('wheelchair/foot_left_link')
                        footr = self.wheelchair.GetLink('wheelchair/foot_right_link')
                        ch = self.wheelchair.GetLink('wheelchair/upper_body_link')
                        origin_B_head = np.matrix(headmodel.GetTransform())
                        origin_B_ual = np.matrix(ual.GetTransform())
                        origin_B_uar = np.matrix(uar.GetTransform())
                        origin_B_fal = np.matrix(fal.GetTransform())
                        origin_B_far = np.matrix(far.GetTransform())
                        origin_B_thl = np.matrix(thl.GetTransform())
                        origin_B_thr = np.matrix(thr.GetTransform())
                        origin_B_kneel = np.matrix(kneel.GetTransform())
                        origin_B_kneer = np.matrix(kneer.GetTransform())
                        origin_B_footl = np.matrix(footl.GetTransform())
                        origin_B_footr = np.matrix(footr.GetTransform())
                        origin_B_ch = np.matrix(ch.GetTransform())
                        self.selection_mat = np.zeros(len(self.goals))
                        self.goal_list = np.zeros([len(self.goals), 4, 4])
                        for thing in xrange(len(self.reference_names)):
                            if self.reference_names[thing] == 'head':
                                self.origin_B_references[thing] = origin_B_head
                            elif self.reference_names[thing] == 'base_link':
                                self.origin_B_references[thing] = origin_B_pr2
                                # self.origin_B_references[thing] = np.matrix(self.robot.GetTransform())
                            elif self.reference_names[thing] == 'upper_arm_left':
                                self.origin_B_references.append(origin_B_ual)
                            elif self.reference_names[thing] == 'upper_arm_right':
                                self.origin_B_references.append(origin_B_uar)
                            elif self.reference_names[thing] == 'forearm_left':
                                self.origin_B_references.append(origin_B_fal)
                            elif self.reference_names[thing] == 'forearm_right':
                                self.origin_B_references.append(origin_B_far)
                            elif self.reference_names[thing] == 'thigh_left':
                                self.origin_B_references.append(origin_B_thl)
                            elif self.reference_names[thing] == 'thigh_right':
                                self.origin_B_references.append(origin_B_thr)
                            elif self.reference_names[thing] == 'knee_left':
                                self.origin_B_references.append(origin_B_kneel)
                            elif self.reference_names[thing] == 'knee_right':
                                self.origin_B_references.append(origin_B_kneer)
                            elif self.reference_names[thing] == 'foot_left':
                                self.origin_B_references.append(origin_B_footl)
                            elif self.reference_names[thing] == 'foot_right':
                                self.origin_B_references.append(origin_B_footr)
                            elif self.reference_names[thing] == 'chest':
                                self.origin_B_references.append(origin_B_ch)

                        thing = num
                        self.goal_list[0] = copy.copy(self.origin_B_references[int(self.reference_mat[thing])]*np.matrix(self.goals[thing, 0]))
                        self.selection_mat[0] = copy.copy(self.goals[thing, 1])

                        self.set_goals()
                        headmodel = self.wheelchair.GetLink('wheelchair/head_link')

                    elif self.model == 'autobed':
                        self.selection_mat = np.zeros(1)
                        self.goal_list = np.zeros([1, 4, 4])
                        self.set_autobed(bz[config_num], bth[config_num], self.headx, self.heady)
                        self.env.UpdatePublishedBodies()

                        headmodel = self.autobed.GetLink('autobed/head_link')
                        ual = self.autobed.GetLink('autobed/arm_left_link')
                        uar = self.autobed.GetLink('autobed/arm_right_link')
                        fal = self.autobed.GetLink('autobed/forearm_left_link')
                        far = self.autobed.GetLink('autobed/forearm_right_link')
                        thl = self.autobed.GetLink('autobed/quad_left_link')
                        thr = self.autobed.GetLink('autobed/quad_right_link')
                        kneel = self.autobed.GetLink('autobed/calf_left_link')
                        kneer = self.autobed.GetLink('autobed/calf_right_link')
                        footl = self.autobed.GetLink('autobed/foot_left_link')
                        footr = self.autobed.GetLink('autobed/foot_right_link')
                        ch = self.autobed.GetLink('autobed/upper_body_link')
                        origin_B_head = np.matrix(headmodel.GetTransform())
                        origin_B_ual = np.matrix(ual.GetTransform())
                        origin_B_uar = np.matrix(uar.GetTransform())
                        origin_B_fal = np.matrix(fal.GetTransform())
                        origin_B_far = np.matrix(far.GetTransform())
                        origin_B_thl = np.matrix(thl.GetTransform())
                        origin_B_thr = np.matrix(thr.GetTransform())
                        origin_B_kneel = np.matrix(kneel.GetTransform())
                        origin_B_kneer = np.matrix(kneer.GetTransform())
                        origin_B_footl = np.matrix(footl.GetTransform())
                        origin_B_footr = np.matrix(footr.GetTransform())
                        origin_B_ch = np.matrix(ch.GetTransform())
                        self.origin_B_references = []
                        # for thing in xrange(len(self.reference_names)):
                        thing = int(self.goals[num, 2])
                        if self.reference_names[thing] == 'head':
                            self.origin_B_references.append(origin_B_head)
                        elif self.reference_names[thing] == 'base_link':
                            self.origin_B_references.append(origin_B_pr2)
                        elif self.reference_names[thing] == 'upper_arm_left':
                            self.origin_B_references.append(origin_B_ual)
                        elif self.reference_names[thing] == 'upper_arm_right':
                            self.origin_B_references.append(origin_B_uar)
                        elif self.reference_names[thing] == 'forearm_left':
                            self.origin_B_references.append(origin_B_fal)
                        elif self.reference_names[thing] == 'forearm_right':
                            self.origin_B_references.append(origin_B_far)
                        elif self.reference_names[thing] == 'thigh_left':
                            self.origin_B_references.append(origin_B_thl)
                        elif self.reference_names[thing] == 'thigh_right':
                            self.origin_B_references.append(origin_B_thr)
                        elif self.reference_names[thing] == 'knee_left':
                            self.origin_B_references.append(origin_B_kneel)
                        elif self.reference_names[thing] == 'knee_right':
                            self.origin_B_references.append(origin_B_kneer)
                        elif self.reference_names[thing] == 'foot_left':
                            self.origin_B_references.append(origin_B_footl)
                        elif self.reference_names[thing] == 'foot_right':
                            self.origin_B_references.append(origin_B_footr)
                        elif self.reference_names[thing] == 'chest':
                            self.origin_B_references.append(origin_B_ch)
                        else:
                            print 'The refence options is bogus! I dont know what to do!'
                            return

                        # for thing in xrange(len(self.goals)):
                        # thing = num
                        self.goal_list[0] = copy.copy(self.origin_B_references[0]*np.matrix(self.goals[num, 0]))
                        self.selection_mat[0] = copy.copy(self.goals[num, 1])
                        self.set_goals(single_goal=True)
                    else:
                        print 'I GOT A BAD MODEL. NOT SURE WHAT TO DO NOW!'

                    # for origin_B_goal in self.origin_B_grasps:
                    origin_B_grasp = self.origin_B_grasps[0]
                    pr2_B_goal = origin_B_pr2.I*origin_B_grasp
                    this_distance = np.linalg.norm(pr2_B_goal[:2, 3])
                    distance[config_num] = np.min([this_distance, distance[config_num]])
                    if this_distance < 1.25:
                        with self.robot:
                            v = self.robot.GetActiveDOFValues()
                            v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_pan_joint').GetDOFIndex()] = -3.14/2
                            v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_lift_joint').GetDOFIndex()] = -0.52
                            v[self.robot.GetJoint(self.opposite_arm[0]+'_upper_arm_roll_joint').GetDOFIndex()] = 0.
                            v[self.robot.GetJoint(self.opposite_arm[0]+'_elbow_flex_joint').GetDOFIndex()] = -3.14*2/3
                            v[self.robot.GetJoint(self.opposite_arm[0]+'_forearm_roll_joint').GetDOFIndex()] = 0.
                            v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_flex_joint').GetDOFIndex()] = 0.
                            v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_roll_joint').GetDOFIndex()] = 0.
                            self.robot.SetActiveDOFValues(v, 2)
                            if not self.manip.CheckIndependentCollision(op.CollisionReport()):
                                Tgrasp = self.origin_B_grasps[0]

                                # print 'no collision!'
                                # for num, Tgrasp in enumerate(self.origin_B_grasps):
                                    # sol = None
                                    # sol = self.manip.FindIKSolution(Tgrasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)

                                    #sol = self.manip.FindIKSolution(Tgrasp,filteroptions=op.IkFilterOptions.IgnoreSelfCollisions)
                                sols = []
                                sols = self.manip.FindIKSolutions(Tgrasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)
                                if not list(sols):
                                    v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_pan_joint').GetDOFIndex()] = -0.023593
                                    v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_lift_joint').GetDOFIndex()] = 1.1072800
                                    v[self.robot.GetJoint(self.opposite_arm[0]+'_upper_arm_roll_joint').GetDOFIndex()] = -1.5566882
                                    v[self.robot.GetJoint(self.opposite_arm[0]+'_elbow_flex_joint').GetDOFIndex()] = -2.124408
                                    v[self.robot.GetJoint(self.opposite_arm[0]+'_forearm_roll_joint').GetDOFIndex()] = -1.4175
                                    v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_flex_joint').GetDOFIndex()] = -1.8417
                                    v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_roll_joint').GetDOFIndex()] = 0.21436
                                    self.robot.SetActiveDOFValues(v, 2)
                                    sols = self.manip.FindIKSolutions(Tgrasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)

                                if list(sols):  # not None:
                                    # print 'I got a solution!!'
                                    # print 'sol is:', sol
                                    # print 'sols are: \n', sols
                                    #print 'I was able to find a grasp to this goal'
                                    reached[num, config_num] = 1.
                                    for solution in sols:
                                        self.robot.SetDOFValues(solution, self.manip.GetArmIndices())
                                        # Tee = self.manip.GetEndEffectorTransform()
                                        self.env.UpdatePublishedBodies()
                                        if self.visualize:
                                            rospy.sleep(0.2)


                                        J = np.matrix(np.vstack([self.manip.CalculateJacobian(), self.manip.CalculateAngularVelocityJacobian()]))
                                        try:
                                            joint_limit_weight = self.gen_joint_limit_weight(solution)
                                            manip[num, config_num] = np.max([copy.copy((m.pow(np.linalg.det(J*joint_limit_weight*J.T), (1./6.)))/(np.trace(J*joint_limit_weight*J.T)/6.)), manip[num, config_num]])
                                        except ValueError:
                                            print 'WARNING!!'
                                            print 'Jacobian may be singular or close to singular'
                                            print 'Determinant of J*JT is: ', np.linalg.det(J*J.T)
                                            manip[num, config_num] = np.max([0., manip[num, config_num]])
                            # else:
                            #     return 0.
                                # rospy.sleep(5)
                                # print np.degrees(solution)

            reached[num, 2] = np.max(reached[num])
            manip[num, 2] = np.max(manip[num])
            # manip_score[0] += reached[0]*manip[0]*self.weights[0]
            # manip_score[1] += reached[1]*manip[1]*self.weights[0]
            # manip_score[2] += reached[2]*0.95*manip[2]*self.weights[0]
            #
            # # np.max(reached)*np.max([manip[0], manip[1], 0.95*manip[2]])*self.weights[0]
            # reach_score[0] += reached[0] * self.weights[0]
            # reach_score[1] += reached[1] * self.weights[0]
            # reach_score[2] += reached[2] * self.weights[0]

        reach_score[0] = np.sum(reached[:, 0] * self.weights[0])
        reach_score[1] = np.sum(reached[:, 1] * self.weights[0])
        reach_score[2] = np.sum(reached[:, 2] * self.weights[0])

        manip_score[0] = np.sum(reached[:, 0]*manip[:, 0]*self.weights[0])
        manip_score[1] = np.sum(reached[:, 1]*manip[:, 1]*self.weights[0])
        manip_score[2] = np.sum(reached[:, 2]*manip[:, 2]*self.weights[0])*0.95

        ## Set the weights for the different scores.
        beta = 10.  # Weight on number of reachable goals
        gamma = 1.  # Weight on manipulability of arm at each reachable goal
        zeta = .05  # Weight on distance to move to get to that goal location
        # thisScore =
        # print 'Reach score: ', reach_score
        # print 'Manip score: ', manip_score
        # print 'Calculated score: ', 10.-beta*reach_score-gamma*manip_score
        best = None

        # Distance travel cost
        # travel_score = np.array([0., 0., 0.])
        # travel_score[0] = np.min([travel[0], 2.0])
        # travel_score[1] = np.min([travel[1], 2.0])
        # travel_score[2] = np.min([travel[2], 2.0])


        # 1. - m.pow(1.0, np.abs(2.0 - travel[0]))

        outputs = 10. - beta*reach_score - gamma*manip_score #- zeta*travel_score
        # best = np.argmin(outputs)
        return outputs

        # print manip_score
        # print reach_score
        # ## Set the weights for the different scores.
        # beta = 5.  # Weight on number of reachable goals
        # gamma = 1.  # Weight on manipulability of arm at each reachable goal
        # zeta = .0007  # Weight on distance to move to get to that goal location
        # # thisScore =
        # # print 'Reach score: ', reach_score
        # # print 'Manip score: ', manip_score
        # # print 'Calculated score: ', 10.-beta*reach_score-gamma*manip_score
        # output = []
        # for sco in xrange(len(manip_score)):
        #     output.append(beta*reach_score[sco]+gamma*manip_score[sco])
        # return output  # +zeta*self.distance

    def objective_function_one_config_toc_sample(self, current_parameters):
        # current_parameters = [  1.21497982,  0.97523797, -3.14114645,  0.29979307,  0.07958062,
        # 0.95115451]
        # self.heady = 0.09
        # print 'toc goals:\n', self.goals
        if not self.a_model_is_loaded:
            print 'Somehow a model has not been loaded. This is bad!'
            return None
        if len(current_parameters) == 6:
            x = current_parameters[0]
            y = current_parameters[1]
            th = current_parameters[2]
            z = current_parameters[3]
            bz = current_parameters[4]
            bth = current_parameters[5]
        else:
            x = current_parameters[0]
            y = current_parameters[1]
            th = current_parameters[2]
            z = current_parameters[3]
            bz = 0.
            bth = 0.

        this_score = 10000.

        # print 'Calculating new score'
        # starttime = time.time()
        origin_B_pr2 = np.matrix([[m.cos(th), -m.sin(th), 0., x],
                                  [m.sin(th), m.cos(th), 0., y],
                                  [0., 0., 1., 0.],
                                  [0., 0., 0., 1.]])
        self.robot.SetTransform(np.array(origin_B_pr2))
        v = self.robot.GetActiveDOFValues()
        v[self.robot.GetJoint('torso_lift_joint').GetDOFIndex()] = z
        self.robot.SetActiveDOFValues(v, 2)

        if self.model == 'chair':
            self.env.UpdatePublishedBodies()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')
            ual = self.wheelchair.GetLink('wheelchair/arm_left_link')
            uar = self.wheelchair.GetLink('wheelchair/arm_right_link')
            fal = self.wheelchair.GetLink('wheelchair/forearm_left_link')
            far = self.wheelchair.GetLink('wheelchair/forearm_right_link')
            thl = self.wheelchair.GetLink('wheelchair/quad_left_link')
            thr = self.wheelchair.GetLink('wheelchair/quad_right_link')
            kneel = self.wheelchair.GetLink('wheelchair/calf_left_link')
            kneer = self.wheelchair.GetLink('wheelchair/calf_right_link')
            footl = self.wheelchair.GetLink('wheelchair/foot_left_link')
            footr = self.wheelchair.GetLink('wheelchair/foot_right_link')
            ch = self.wheelchair.GetLink('wheelchair/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references[thing] = origin_B_head
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references[thing] = origin_B_pr2
                    # self.origin_B_references[thing] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)
            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(
                    self.origin_B_references[int(self.reference_mat[thing])] * np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
                #            for target in self.goals:
                #                self.goal_list.append(pr2_B_head*np.matrix(target[0]))
                #                self.selection_mat.append(target[1])
            self.set_goals()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')

        elif self.model == 'autobed':
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            self.set_autobed(bz, bth, self.headx, self.heady)
            self.env.UpdatePublishedBodies()

            headmodel = self.autobed.GetLink('autobed/head_link')
            ual = self.autobed.GetLink('autobed/arm_left_link')
            uar = self.autobed.GetLink('autobed/arm_right_link')
            fal = self.autobed.GetLink('autobed/forearm_left_link')
            far = self.autobed.GetLink('autobed/forearm_right_link')
            thl = self.autobed.GetLink('autobed/quad_left_link')
            thr = self.autobed.GetLink('autobed/quad_right_link')
            kneel = self.autobed.GetLink('autobed/calf_left_link')
            kneer = self.autobed.GetLink('autobed/calf_right_link')
            footl = self.autobed.GetLink('autobed/foot_left_link')
            footr = self.autobed.GetLink('autobed/foot_right_link')
            ch = self.autobed.GetLink('autobed/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.origin_B_references = []
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references.append(origin_B_head)
                    # self.origin_B_references.append(np.matrix(headmodel.GetTransform())
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references.append(origin_B_pr2)
                    # self.origin_B_references[i] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)

            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(
                    self.origin_B_references[int(self.reference_mat[thing])] * np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
            # for target in self.goals:
            #     self.goal_list.append(pr2_B_head*np.matrix(target[0]))
            #     self.selection_mat.append(target[1])
            self.set_goals()
        elif self.model is None:
            self.env.UpdatePublishedBodies()
        else:
            print 'I GOT A BAD MODEL. NOT SURE WHAT TO DO NOW!'
        distance = 10000000.
        out_of_reach = True

        for origin_B_grasp in self.origin_B_grasps:
            pr2_B_goal = origin_B_pr2.I * origin_B_grasp
            distance = np.min([np.linalg.norm(pr2_B_goal[:2, 3]), distance])

            if distance <= 1.25:
                out_of_reach = False
                # print 'not out of reach'
                break
        if out_of_reach:
            # print 'location is out of reach'
            this_score = 10. + 1. + 20. * (distance - 1.25)
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score

        # print 'Time to update autobed things: %fs'%(time.time()-starttime)
        reach_score = 0.
        manip_score = 0.
        goal_scores = []
        # std = 1.
        # mean = 0.
        # allmanip = []
        manip = 0.
        reached = 0.

        # allmanip2=[]
        # space_score = (1./(std*(m.pow((2.*m.pi), 0.5))))*m.exp(-(m.pow(np.linalg.norm([x, y])-mean, 2.)) /
        #                                                        (2.*m.pow(std, 2.)))
        # print space_score
        with self.robot:
            v = self.robot.GetActiveDOFValues()
            if self.arm[0] == 'l':
                arm_sign = 1
            else:
                arm_sign = -1
            in_collision = True
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
            v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
            v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
            v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (-3.5)
            v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
            v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
            v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
            self.robot.SetActiveDOFValues(v, 2)
            self.env.UpdatePublishedBodies()
            # rospy.sleep(10)
            in_collision = self.env.CheckCollision(self.robot)
            if in_collision:
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * 3.14 / 2
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.

                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = -3.14 / 2
                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.
                self.robot.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()
                in_collision = self.env.CheckCollision(self.robot)
                # rospy.sleep(10)
            if in_collision:
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (-3.5)
                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0

                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = -3.14 / 2
                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.
                self.robot.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()
                in_collision = self.env.CheckCollision(self.robot)
                # rospy.sleep(10)
            if in_collision:
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * 3.14 / 2
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.

                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
                v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
                self.robot.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()
                in_collision = self.env.CheckCollision(self.robot)
                # rospy.sleep(10)

            '''
            origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0., x+.02],
                                      [ m.sin(th),  m.cos(th),     0., y+.02],
                                      [        0.,         0.,     1.,        0.],
                                      [        0.,         0.,     0.,        1.]])
            self.robot.SetTransform(np.array(origin_B_pr2))
            self.env.UpdatePublishedBodies()
            if self.manip.CheckIndependentCollision(op.CollisionReport()):
                not_close_to_collision = False

            origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0., x-.02],
                                      [ m.sin(th),  m.cos(th),     0., y+.02],
                                      [        0.,         0.,     1.,        0.],
                                      [        0.,         0.,     0.,        1.]])
            self.robot.SetTransform(np.array(origin_B_pr2))
            self.env.UpdatePublishedBodies()
            if self.manip.CheckIndependentCollision(op.CollisionReport()):
                not_close_to_collision = False

            origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0., x-.02],
                                      [ m.sin(th),  m.cos(th),     0., y-.02],
                                      [        0.,         0.,     1.,        0.],
                                      [        0.,         0.,     0.,        1.]])
            self.robot.SetTransform(np.array(origin_B_pr2))
            self.env.UpdatePublishedBodies()
            if self.manip.CheckIndependentCollision(op.CollisionReport()):
                not_close_to_collision = False

            origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0., x+.02],
                                      [ m.sin(th),  m.cos(th),     0., y-.02],
                                      [        0.,         0.,     1.,        0.],
                                      [        0.,         0.,     0.,        1.]])
            self.robot.SetTransform(np.array(origin_B_pr2))
            self.env.UpdatePublishedBodies()
            if self.manip.CheckIndependentCollision(op.CollisionReport()):
                not_close_to_collision = False

            origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0., x],
                                      [ m.sin(th),  m.cos(th),     0., y],
                                      [        0.,         0.,     1.,        0.],
                                      [        0.,         0.,     0.,        1.]])
            self.robot.SetTransform(np.array(origin_B_pr2))
            self.env.UpdatePublishedBodies()
            '''
            if not in_collision:
                # print 'No base collision! single config distance: ', distance
                reached = np.zeros(len(self.origin_B_grasps))
                manip = np.zeros(len(self.origin_B_grasps))
                for head_angle in self.head_angles:
                    self.rotate_head_and_update_goals(head_angle[0], head_angle[1], origin_B_pr2)
                    for num, Tgrasp in enumerate(self.origin_B_grasps):
                        sols = []
                        sols = self.manip.FindIKSolutions(Tgrasp,
                                                          filteroptions=op.IkFilterOptions.CheckEnvCollisions)
                        # if not list(sols):
                        #     v = self.robot.GetActiveDOFValues()
                        #     v[self.robot.GetJoint(
                        #         self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = -0.023593
                        #     v[self.robot.GetJoint(
                        #         self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 1.1072800
                        #     v[self.robot.GetJoint(
                        #         self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = -1.5566882
                        #     v[self.robot.GetJoint(
                        #         self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.124408
                        #     v[self.robot.GetJoint(
                        #         self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = -1.4175
                        #     v[self.robot.GetJoint(
                        #         self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.8417
                        #     v[self.robot.GetJoint(
                        #         self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.21436
                        #     self.robot.SetActiveDOFValues(v, 2)
                        #     self.env.UpdatePublishedBodies()
                        #     sols = self.manip.FindIKSolutions(Tgrasp,
                        #                                       filteroptions=op.IkFilterOptions.CheckEnvCollisions)

                        # manip[num] = 0.
                        # reached[num] = 0.
                        if list(sols):  # not None:
                            reached[num] = 1.
                            for solution in sols:

                                # if m.degrees(solution[3])<-45:
                                #     continue
                                # else:

                                self.robot.SetDOFValues(solution, self.manip.GetArmIndices())
                                self.env.UpdatePublishedBodies()
                                J = np.matrix(np.vstack([self.manip.CalculateJacobian(),
                                                         self.manip.CalculateAngularVelocityJacobian()]))
                                try:
                                    joint_limit_weight = self.gen_joint_limit_weight(solution)
                                    manip[num] = np.max([copy.copy(
                                        (m.pow(np.linalg.det(J*joint_limit_weight*J.T), (1./6.))) / (
                                            np.trace(J*joint_limit_weight*J.T)/6.)),
                                        manip[num]])
                                except ValueError:
                                    print 'WARNING!!'
                                    print 'Jacobian may be singular or close to singular'
                                    print 'Determinant of J*JT is: ', np.linalg.det(J * J.T)
                                    manip[num] = np.max([0., manip[num]])
                            if self.visualize:
                                rospy.sleep(1.0)
                for num in xrange(len(reached)):
                    manip_score += copy.copy(reached[num] * manip[num] * self.weights[num])
                    reach_score += copy.copy(reached[num] * self.weights[num])
            else:
                # print 'In base collision! single config distance: ', distance
                if distance < 2.0:
                    this_score = 10. + 1. + (1.25 - distance)
                    if this_score < self.best_score:
                        self.best_config = current_parameters
                        self.best_score = this_score
                    return this_score

        # Set the weights for the different scores.
        beta = 10.  # Weight on number of reachable goals
        gamma = 1.  # Weight on manipulability of arm at each reachable goal
        zeta = .0007  # Weight on distance to move to get to that goal location
        if reach_score == 0.:
            this_score = 10. + 2 * random.random()
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score
        else:
            # print 'Reach score: ', reach_score
            # print 'Manip score: ', manip_score
            this_score = 10. - beta * reach_score - gamma * manip_score
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score

    def objective_function_one_config_ireach_sample(self, current_parameters):
        # current_parameters = [  1.21497982,  0.97523797, -3.14114645,  0.29979307,  0.07958062,
        # 0.95115451]
        # self.heady = 0.09
        # print 'ireach goals:\n', self.goals
        if not self.a_model_is_loaded:
            print 'Somehow a model has not been loaded. This is bad!'
            return None
        if len(current_parameters) == 6:
            x = current_parameters[0]
            y = current_parameters[1]
            th = current_parameters[2]
            z = current_parameters[3]
            bz = current_parameters[4]
            bth = current_parameters[5]
        else:
            x = current_parameters[0]
            y = current_parameters[1]
            th = current_parameters[2]
            z = current_parameters[3]
            bz = 0.
            bth = 0.

        this_score = 10000.

        # print 'Calculating new score'
        # starttime = time.time()
        origin_B_pr2 = np.matrix([[m.cos(th), -m.sin(th), 0., x],
                                  [m.sin(th), m.cos(th), 0., y],
                                  [0., 0., 1., 0.],
                                  [0., 0., 0., 1.]])
        self.robot.SetTransform(np.array(origin_B_pr2))
        v = self.robot.GetActiveDOFValues()
        v[self.robot.GetJoint('torso_lift_joint').GetDOFIndex()] = z
        self.robot.SetActiveDOFValues(v, 2)

        if self.model == 'chair':
            self.env.UpdatePublishedBodies()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')
            ual = self.wheelchair.GetLink('wheelchair/arm_left_link')
            uar = self.wheelchair.GetLink('wheelchair/arm_right_link')
            fal = self.wheelchair.GetLink('wheelchair/forearm_left_link')
            far = self.wheelchair.GetLink('wheelchair/forearm_right_link')
            thl = self.wheelchair.GetLink('wheelchair/quad_left_link')
            thr = self.wheelchair.GetLink('wheelchair/quad_right_link')
            kneel = self.wheelchair.GetLink('wheelchair/calf_left_link')
            kneer = self.wheelchair.GetLink('wheelchair/calf_right_link')
            footl = self.wheelchair.GetLink('wheelchair/foot_left_link')
            footr = self.wheelchair.GetLink('wheelchair/foot_right_link')
            ch = self.wheelchair.GetLink('wheelchair/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references[thing] = origin_B_head
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references[thing] = origin_B_pr2
                    # self.origin_B_references[thing] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)
            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(
                    self.origin_B_references[int(self.reference_mat[thing])] * np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
                #            for target in self.goals:
                #                self.goal_list.append(pr2_B_head*np.matrix(target[0]))
                #                self.selection_mat.append(target[1])
            self.set_goals()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')

        elif self.model == 'autobed':
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            self.set_autobed(bz, bth, self.headx, self.heady)
            self.env.UpdatePublishedBodies()

            headmodel = self.autobed.GetLink('autobed/head_link')
            ual = self.autobed.GetLink('autobed/arm_left_link')
            uar = self.autobed.GetLink('autobed/arm_right_link')
            fal = self.autobed.GetLink('autobed/forearm_left_link')
            far = self.autobed.GetLink('autobed/forearm_right_link')
            thl = self.autobed.GetLink('autobed/quad_left_link')
            thr = self.autobed.GetLink('autobed/quad_right_link')
            kneel = self.autobed.GetLink('autobed/calf_left_link')
            kneer = self.autobed.GetLink('autobed/calf_right_link')
            footl = self.autobed.GetLink('autobed/foot_left_link')
            footr = self.autobed.GetLink('autobed/foot_right_link')
            ch = self.autobed.GetLink('autobed/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.origin_B_references = []
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references.append(origin_B_head)
                    # self.origin_B_references.append(np.matrix(headmodel.GetTransform())
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references.append(origin_B_pr2)
                    # self.origin_B_references[i] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)

            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(
                    self.origin_B_references[int(self.reference_mat[thing])] * np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
            # for target in self.goals:
            #     self.goal_list.append(pr2_B_head*np.matrix(target[0]))
            #     self.selection_mat.append(target[1])
            self.set_goals()
        elif self.model is None:
            self.env.UpdatePublishedBodies()
        else:
            print 'I GOT A BAD MODEL. NOT SURE WHAT TO DO NOW!'
        distance = 10000000.
        out_of_reach = True

        for origin_B_grasp in self.origin_B_grasps:
            pr2_B_goal = origin_B_pr2.I * origin_B_grasp
            distance = np.min([np.linalg.norm(pr2_B_goal[:2, 3]), distance])

            if distance <= 1.25:
                out_of_reach = False
                # print 'not out of reach'
                break
        if out_of_reach:
            # print 'ireach location is out of reach'
            this_score = 10. + 1. + 20. * (distance - 1.25)
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score

        # print 'Time to update autobed things: %fs'%(time.time()-starttime)
        reach_score = 0.
        manip_score = 0.
        goal_scores = []
        # std = 1.
        # mean = 0.
        # allmanip = []
        manip = 0.
        reached = 0.

        # allmanip2=[]
        # space_score = (1./(std*(m.pow((2.*m.pi), 0.5))))*m.exp(-(m.pow(np.linalg.norm([x, y])-mean, 2.)) /
        #                                                        (2.*m.pow(std, 2.)))
        # print space_score
        with self.robot:
            v = self.robot.GetActiveDOFValues()
            if self.arm[0] == 'l':
                arm_sign = 1
            else:
                arm_sign = -1
            in_collision = True
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
            v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
            v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
            v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (-3.5)
            v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
            v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
            v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
            self.robot.SetActiveDOFValues(v, 2)
            self.env.UpdatePublishedBodies()
            # rospy.sleep(10)
            in_collision = self.env.CheckCollision(self.robot)
            if in_collision:
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * 3.14 / 2
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.

                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = -3.14 / 2
                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.
                self.robot.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()
                in_collision = self.env.CheckCollision(self.robot)
                # rospy.sleep(10)
            if in_collision:
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (-3.5)
                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0

                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = -3.14 / 2
                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.
                self.robot.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()
                in_collision = self.env.CheckCollision(self.robot)
                # rospy.sleep(10)
            if in_collision:
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * 3.14 / 2
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.

                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
                v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
                self.robot.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()
                in_collision = self.env.CheckCollision(self.robot)
                # rospy.sleep(10)

            if not in_collision:
                # print 'No base collision! single config distance: ', distance
                reachability = np.zeros(len(self.origin_B_grasps))
                for head_angle in self.head_angles:
                    self.rotate_head_and_update_goals(head_angle[0], head_angle[1], origin_B_pr2)
                    for num, Tgrasp in enumerate(self.origin_B_grasps):
                        # self.ireach.find_reachability_of_grasp_from_pose(Tgrasp, origin_B_pr2)
                        if not self.ir_and_collision:
                            reachability[num] = np.max([reachability[num],
                                                        self.ireach.find_reachability_of_grasp_from_pose(Tgrasp, [x,y,th,z])[0]])
                        else:
                            sol = None
                            sol = self.manip.FindIKSolution(Tgrasp,
                                                            filteroptions=op.IkFilterOptions.CheckEnvCollisions)
                            if sol is not None:
                                reachability[num] = np.max([reachability[num],
                                                            self.ireach.find_reachability_of_grasp_from_pose(Tgrasp,[x, y, th,z])[0]])
                                # if reachability[num] == 0.:
                                    # print 'There is an ik but reachability is zero, weirdly'
                        if self.visualize:
                            sol = None
                            sol = self.manip.FindIKSolution(Tgrasp,
                                                            filteroptions=op.IkFilterOptions.CheckEnvCollisions)
                            # print sol

                            if sol is not None:  # not None:
                                self.robot.SetDOFValues(sol, self.manip.GetArmIndices())
                                self.env.UpdatePublishedBodies()
                                rospy.sleep(1.0)

                reach_score = 10.*reachability.mean()
            else:
                # print 'ireach in base collision! single config distance: ', distance
                if distance < 2.0:
                    this_score = 10. + 1. + (1.25 - distance)
                    if this_score < self.best_score:
                        self.best_config = current_parameters
                        self.best_score = this_score
                    return this_score

        # Set the weights for the different scores.
        beta = 10.  # Weight on number of reachable goals
        gamma = 1.  # Weight on manipulability of arm at each reachable goal
        zeta = .0007  # Weight on distance to move to get to that goal location
        if reach_score == 0.:
            # print 'nothing was reachable'
            this_score = 10. + 2 * random.random()
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score
        else:
            # print 'Reach score: ', reach_score
            # print 'Manip score: ', manip_score
            this_score = 10. - reach_score
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score

    def objective_function_one_config_ik_sample(self, current_parameters):
        # current_parameters = [  1.21497982,  0.97523797, -3.14114645,  0.29979307,  0.07958062,
        # 0.95115451]
        # self.heady = 0.09
        if not self.a_model_is_loaded:
            print 'Somehow a model has not been loaded. This is bad!'
            return None
        if len(current_parameters) == 6:
            x = current_parameters[0]
            y = current_parameters[1]
            th = current_parameters[2]
            z = current_parameters[3]
            bz = current_parameters[4]
            bth = current_parameters[5]
        else:
            x = current_parameters[0]
            y = current_parameters[1]
            th = current_parameters[2]
            z = current_parameters[3]
            bz = 0.
            bth = 0.

        this_score = 10000.

        # print 'Calculating new score'
        # starttime = time.time()
        origin_B_pr2 = np.matrix([[m.cos(th), -m.sin(th), 0., x],
                                  [m.sin(th), m.cos(th), 0., y],
                                  [0., 0., 1., 0.],
                                  [0., 0., 0., 1.]])
        self.robot.SetTransform(np.array(origin_B_pr2))
        v = self.robot.GetActiveDOFValues()
        v[self.robot.GetJoint('torso_lift_joint').GetDOFIndex()] = z
        self.robot.SetActiveDOFValues(v, 2)

        if self.model == 'chair':
            self.env.UpdatePublishedBodies()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')
            ual = self.wheelchair.GetLink('wheelchair/arm_left_link')
            uar = self.wheelchair.GetLink('wheelchair/arm_right_link')
            fal = self.wheelchair.GetLink('wheelchair/forearm_left_link')
            far = self.wheelchair.GetLink('wheelchair/forearm_right_link')
            thl = self.wheelchair.GetLink('wheelchair/quad_left_link')
            thr = self.wheelchair.GetLink('wheelchair/quad_right_link')
            kneel = self.wheelchair.GetLink('wheelchair/calf_left_link')
            kneer = self.wheelchair.GetLink('wheelchair/calf_right_link')
            footl = self.wheelchair.GetLink('wheelchair/foot_left_link')
            footr = self.wheelchair.GetLink('wheelchair/foot_right_link')
            ch = self.wheelchair.GetLink('wheelchair/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references[thing] = origin_B_head
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references[thing] = origin_B_pr2
                    # self.origin_B_references[thing] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)
            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(
                    self.origin_B_references[int(self.reference_mat[thing])] * np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
                #            for target in self.goals:
                #                self.goal_list.append(pr2_B_head*np.matrix(target[0]))
                #                self.selection_mat.append(target[1])
            self.set_goals()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')

        elif self.model == 'autobed':
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            self.set_autobed(bz, bth, self.headx, self.heady)
            self.env.UpdatePublishedBodies()

            headmodel = self.autobed.GetLink('autobed/head_link')
            ual = self.autobed.GetLink('autobed/arm_left_link')
            uar = self.autobed.GetLink('autobed/arm_right_link')
            fal = self.autobed.GetLink('autobed/forearm_left_link')
            far = self.autobed.GetLink('autobed/forearm_right_link')
            thl = self.autobed.GetLink('autobed/quad_left_link')
            thr = self.autobed.GetLink('autobed/quad_right_link')
            kneel = self.autobed.GetLink('autobed/calf_left_link')
            kneer = self.autobed.GetLink('autobed/calf_right_link')
            footl = self.autobed.GetLink('autobed/foot_left_link')
            footr = self.autobed.GetLink('autobed/foot_right_link')
            ch = self.autobed.GetLink('autobed/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.origin_B_references = []
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references.append(origin_B_head)
                    # self.origin_B_references.append(np.matrix(headmodel.GetTransform())
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references.append(origin_B_pr2)
                    # self.origin_B_references[i] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)

            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(
                    self.origin_B_references[int(self.reference_mat[thing])] * np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
            # for target in self.goals:
            #     self.goal_list.append(pr2_B_head*np.matrix(target[0]))
            #     self.selection_mat.append(target[1])
            self.set_goals()
        elif self.model is None:
            self.env.UpdatePublishedBodies()
        else:
            print 'I GOT A BAD MODEL. NOT SURE WHAT TO DO NOW!'
        distance = 10000000.
        out_of_reach = True

        for origin_B_grasp in self.origin_B_grasps:
            pr2_B_goal = origin_B_pr2.I * origin_B_grasp
            distance = np.min([np.linalg.norm(pr2_B_goal[:2, 3]), distance])

            if distance <= 1.25:
                out_of_reach = False
                # print 'not out of reach'
                break
        if out_of_reach:
            # print 'location is out of reach'
            this_score = 10. + 1. + 20. * (distance - 1.25)
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score

        # print 'Time to update autobed things: %fs'%(time.time()-starttime)
        reach_score = 0.
        manip_score = 0.
        goal_scores = []
        # std = 1.
        # mean = 0.
        # allmanip = []
        manip = 0.
        reached = 0.

        # allmanip2=[]
        # space_score = (1./(std*(m.pow((2.*m.pi), 0.5))))*m.exp(-(m.pow(np.linalg.norm([x, y])-mean, 2.)) /
        #                                                        (2.*m.pow(std, 2.)))
        # print space_score
        with self.robot:
            v = self.robot.GetActiveDOFValues()
            if self.arm[0] == 'l':
                arm_sign = 1
            else:
                arm_sign = -1
            in_collision = True
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
            v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
            v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
            v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (-3.5)
            v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
            v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
            v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
            self.robot.SetActiveDOFValues(v, 2)
            self.env.UpdatePublishedBodies()
            # rospy.sleep(10)
            in_collision = self.env.CheckCollision(self.robot)
            if in_collision:
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * 3.14 / 2
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.

                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = -3.14 / 2
                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.
                self.robot.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()
                in_collision = self.env.CheckCollision(self.robot)
                # rospy.sleep(10)
            if in_collision:
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (-3.5)
                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0

                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = -3.14 / 2
                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.
                self.robot.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()
                in_collision = self.env.CheckCollision(self.robot)
                # rospy.sleep(10)
            if in_collision:
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * 3.14 / 2
                v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.

                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
                v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
                v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
                self.robot.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()
                in_collision = self.env.CheckCollision(self.robot)
                # rospy.sleep(10)

            if not in_collision:
                # print 'No base collision! single config distance: ', distance
                reachability = np.zeros(len(self.origin_B_grasps))
                for head_angle in self.head_angles:
                    self.rotate_head_and_update_goals(head_angle[0], head_angle[1], origin_B_pr2)
                    for num, Tgrasp in enumerate(self.origin_B_grasps):
                        # self.ireach.find_reachability_of_grasp_from_pose(Tgrasp, origin_B_pr2)
                        if reachability[num] != 1:
                            sol = None
                            sol = self.manip.FindIKSolution(Tgrasp,
                                                            filteroptions=op.IkFilterOptions.CheckEnvCollisions)
                            if sol is not None:
                                reachability[num] = 1
                                if self.visualize:
                                    self.robot.SetDOFValues(sol, self.manip.GetArmIndices())
                                    self.env.UpdatePublishedBodies()
                                    rospy.sleep(1.0)
                reach_score = 10.*reachability.mean()
            else:
                # print 'In base collision! single config distance: ', distance
                if distance < 2.0:
                    this_score = 10. + 1. + (1.25 - distance)
                    if this_score < self.best_score:
                        self.best_config = current_parameters
                        self.best_score = this_score
                    return this_score

        # Set the weights for the different scores.
        beta = 10.  # Weight on number of reachable goals
        gamma = 1.  # Weight on manipulability of arm at each reachable goal
        zeta = .0007  # Weight on distance to move to get to that goal location
        if reach_score == 0.:
            this_score = 10. + 2 * random.random()
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score
        else:
            # print 'Reach score: ', reach_score
            # print 'Manip score: ', manip_score
            this_score = 10. - reach_score
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score

    def objective_function_one_config_ireach_cma(self, current_parameters):
        # current_parameters = [  1.21497982,  0.97523797, -3.14114645,  0.29979307,  0.07958062,
        # 0.95115451]
        # self.heady = 0.09
        if not self.a_model_is_loaded:
            print 'Somehow a model has not been loaded. This is bad!'
            return None
        if len(current_parameters) == 6:
            x = current_parameters[0]
            y = current_parameters[1]
            th = current_parameters[2]
            z = current_parameters[3]
            bz = current_parameters[4]
            bth = current_parameters[5]
        else:
            x = current_parameters[0]
            y = current_parameters[1]
            th = current_parameters[2]
            z = current_parameters[3]
            bz = 0.
            bth = 0.

        this_score = 10000.

        # print 'Calculating new score'
        # starttime = time.time()
        origin_B_pr2 = np.matrix([[m.cos(th), -m.sin(th), 0., x],
                                  [m.sin(th), m.cos(th), 0., y],
                                  [0., 0., 1., 0.],
                                  [0., 0., 0., 1.]])
        self.robot.SetTransform(np.array(origin_B_pr2))
        v = self.robot.GetActiveDOFValues()
        v[self.robot.GetJoint('torso_lift_joint').GetDOFIndex()] = z
        self.robot.SetActiveDOFValues(v, 2)

        if self.model == 'chair':
            self.env.UpdatePublishedBodies()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')
            ual = self.wheelchair.GetLink('wheelchair/arm_left_link')
            uar = self.wheelchair.GetLink('wheelchair/arm_right_link')
            fal = self.wheelchair.GetLink('wheelchair/forearm_left_link')
            far = self.wheelchair.GetLink('wheelchair/forearm_right_link')
            thl = self.wheelchair.GetLink('wheelchair/quad_left_link')
            thr = self.wheelchair.GetLink('wheelchair/quad_right_link')
            kneel = self.wheelchair.GetLink('wheelchair/calf_left_link')
            kneer = self.wheelchair.GetLink('wheelchair/calf_right_link')
            footl = self.wheelchair.GetLink('wheelchair/foot_left_link')
            footr = self.wheelchair.GetLink('wheelchair/foot_right_link')
            ch = self.wheelchair.GetLink('wheelchair/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references[thing] = origin_B_head
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references[thing] = origin_B_pr2
                    # self.origin_B_references[thing] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)
            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(
                    self.origin_B_references[int(self.reference_mat[thing])] * np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
                #            for target in self.goals:
                #                self.goal_list.append(pr2_B_head*np.matrix(target[0]))
                #                self.selection_mat.append(target[1])
            self.set_goals()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')

        elif self.model == 'autobed':
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            self.set_autobed(bz, bth, self.headx, self.heady)
            self.env.UpdatePublishedBodies()

            headmodel = self.autobed.GetLink('autobed/head_link')
            ual = self.autobed.GetLink('autobed/arm_left_link')
            uar = self.autobed.GetLink('autobed/arm_right_link')
            fal = self.autobed.GetLink('autobed/forearm_left_link')
            far = self.autobed.GetLink('autobed/forearm_right_link')
            thl = self.autobed.GetLink('autobed/quad_left_link')
            thr = self.autobed.GetLink('autobed/quad_right_link')
            kneel = self.autobed.GetLink('autobed/calf_left_link')
            kneer = self.autobed.GetLink('autobed/calf_right_link')
            footl = self.autobed.GetLink('autobed/foot_left_link')
            footr = self.autobed.GetLink('autobed/foot_right_link')
            ch = self.autobed.GetLink('autobed/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.origin_B_references = []
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references.append(origin_B_head)
                    # self.origin_B_references.append(np.matrix(headmodel.GetTransform())
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references.append(origin_B_pr2)
                    # self.origin_B_references[i] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)

            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(
                    self.origin_B_references[int(self.reference_mat[thing])] * np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
            # for target in self.goals:
            #     self.goal_list.append(pr2_B_head*np.matrix(target[0]))
            #     self.selection_mat.append(target[1])
            self.set_goals()
        elif self.model is None:
            self.env.UpdatePublishedBodies()
        else:
            print 'I GOT A BAD MODEL. NOT SURE WHAT TO DO NOW!'
        distance = 10000000.
        out_of_reach = True

        for origin_B_grasp in self.origin_B_grasps:
            pr2_B_goal = origin_B_pr2.I * origin_B_grasp
            distance = np.min([np.linalg.norm(pr2_B_goal[:2, 3]), distance])

            if distance <= 1.25:
                out_of_reach = False
                # print 'not out of reach'
                break
        if out_of_reach:
            # print 'location is out of reach'
            this_score = 10. + 1. + 20. * (distance - 1.25)
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score

        # print 'Time to update autobed things: %fs'%(time.time()-starttime)
        reach_score = 0.
        manip_score = 0.
        goal_scores = []
        # std = 1.
        # mean = 0.
        # allmanip = []
        manip = 0.
        reached = 0.

        # allmanip2=[]
        # space_score = (1./(std*(m.pow((2.*m.pi), 0.5))))*m.exp(-(m.pow(np.linalg.norm([x, y])-mean, 2.)) /
        #                                                        (2.*m.pow(std, 2.)))
        # print space_score
        with self.robot:
            v = self.robot.GetActiveDOFValues()
            if self.arm[0] == 'l':
                arm_sign = 1
            else:
                arm_sign = -1
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 0.4
            v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
            v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.0
            v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (-3.5)
            v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -0.5
            v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
            v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
            self.robot.SetActiveDOFValues(v, 2)
            self.env.UpdatePublishedBodies()
            not_close_to_collision = True
            if self.env.CheckCollision(self.robot):
                not_close_to_collision = False

            if not_close_to_collision:
                # print 'No base collision! single config distance: ', distance
                reachability = np.zeros(len(self.origin_B_grasps))
                for head_angle in self.head_angles:
                    self.rotate_head_and_update_goals(head_angle[0], head_angle[1], origin_B_pr2)
                    for num, Tgrasp in enumerate(self.origin_B_grasps):
                        self.ireach.find_reachability_of_grasp_from_pose(Tgrasp, origin_B_pr2)
                        reachability[num] = np.max([reachability[num],
                                                     self.ireach.find_reachability_of_grasp_from_pose(Tgrasp, origin_B_pr2)])
                        if self.visualize:
                            sol = []
                            sol = self.manip.FindIKSolution(Tgrasp,
                                                            filteroptions=op.IkFilterOptions.CheckEnvCollisions)

                            if list(sol):  # not None:
                                self.robot.SetDOFValues(sol, self.manip.GetArmIndices())
                                self.env.UpdatePublishedBodies()
                                rospy.sleep(1.0)

                reach_score = 10.*reachability.mean()
            else:
                # print 'In base collision! single config distance: ', distance
                if distance < 2.0:
                    this_score = 10. + 1. + (1.25 - distance)
                    if this_score < self.best_score:
                        self.best_config = current_parameters
                        self.best_score = this_score
                    return this_score

        # Set the weights for the different scores.
        beta = 10.  # Weight on number of reachable goals
        gamma = 1.  # Weight on manipulability of arm at each reachable goal
        zeta = .0007  # Weight on distance to move to get to that goal location
        if reach_score == 0.:
            this_score = 10. + 2 * random.random()
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score
        else:
            # print 'Reach score: ', reach_score
            # print 'Manip score: ', manip_score
            this_score = 10. - reach_score
            if this_score < self.best_score:
                self.best_config = current_parameters
                self.best_score = this_score
            return this_score

    def objective_function_real_time(self, current_parameters):
        if not self.a_model_is_loaded:
            print 'Somehow a model has not been loaded. This is bad!'
            return None
        x = current_parameters[0]
        y = current_parameters[1]
        th = current_parameters[2]
        z = current_parameters[3]

        #print 'Calculating new score'
        #starttime = time.time()
        origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0.,         x],
                                  [ m.sin(th),  m.cos(th),     0.,         y],
                                  [        0.,         0.,     1.,        0.],
                                  [        0.,         0.,     0.,        1.]])
        self.robot.SetTransform(np.array(origin_B_pr2))
        v = self.robot.GetActiveDOFValues()
        v[self.robot.GetJoint('torso_lift_joint').GetDOFIndex()] = z
        self.robot.SetActiveDOFValues(v, 2)

        self.env.UpdatePublishedBodies()

        distance = 10000000.
        out_of_reach = True

        for origin_B_grasp in self.origin_B_grasps:
            pr2_B_goal = origin_B_pr2.I*origin_B_grasp
            distance = np.min([np.linalg.norm(pr2_B_goal[:2, 3]), distance])

            if distance <= 1.25:
                out_of_reach = False
                # print 'not out of reach'
                break
        if out_of_reach:
            # print 'location is out of reach'
            return 10. +1.+ 20.*(distance - 1.25)

        #print 'Time to update autobed things: %fs'%(time.time()-starttime)
        reach_score = 0.
        manip_score = 0.
        goal_scores = []
        # std = 1.
        # mean = 0.
        # allmanip = []
        manip = 0.
        reached = 0.

        #allmanip2=[]
        # space_score = (1./(std*(m.pow((2.*m.pi), 0.5))))*m.exp(-(m.pow(np.linalg.norm([x, y])-mean, 2.)) /
        #                                                        (2.*m.pow(std, 2.)))
        #print space_score
        with self.robot:
            v = self.robot.GetActiveDOFValues()
            v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_pan_joint').GetDOFIndex()] = -3.14/2
            v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_lift_joint').GetDOFIndex()] = -0.52
            v[self.robot.GetJoint(self.opposite_arm[0]+'_upper_arm_roll_joint').GetDOFIndex()] = 0.
            v[self.robot.GetJoint(self.opposite_arm[0]+'_elbow_flex_joint').GetDOFIndex()] = -3.14*2/3
            v[self.robot.GetJoint(self.opposite_arm[0]+'_forearm_roll_joint').GetDOFIndex()] = 0.
            v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_flex_joint').GetDOFIndex()] = 0.
            v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_roll_joint').GetDOFIndex()] = 0.
            self.robot.SetActiveDOFValues(v, 2)
            self.env.UpdatePublishedBodies()
            not_close_to_collision = True
            if self.manip.CheckIndependentCollision(op.CollisionReport()):
                not_close_to_collision = False

            if not_close_to_collision:
                # print 'No base collision! single config distance: ', distance
                # reached = np.zeros(len(self.origin_B_grasps))
                # manip = np.zeros(len(self.origin_B_grasps))

                for num, Tgrasp in enumerate(self.origin_B_grasps):
                    sols = []
                    sols = self.manip.FindIKSolutions(Tgrasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)
                    if not list(sols):
                        v = self.robot.GetActiveDOFValues()
                        v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_pan_joint').GetDOFIndex()] = -0.023593
                        v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_lift_joint').GetDOFIndex()] = 1.1072800
                        v[self.robot.GetJoint(self.opposite_arm[0]+'_upper_arm_roll_joint').GetDOFIndex()] = -1.5566882
                        v[self.robot.GetJoint(self.opposite_arm[0]+'_elbow_flex_joint').GetDOFIndex()] = -2.124408
                        v[self.robot.GetJoint(self.opposite_arm[0]+'_forearm_roll_joint').GetDOFIndex()] = -1.4175
                        v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_flex_joint').GetDOFIndex()] = -1.8417
                        v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_roll_joint').GetDOFIndex()] = 0.21436
                        self.robot.SetActiveDOFValues(v, 2)
                        self.env.UpdatePublishedBodies()
                        sols = self.manip.FindIKSolutions(Tgrasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)

                    # manip[num] = 0.
                    # reached[num] = 0.
                    if list(sols):  # not None:

                        reached = 1.
                        for solution in sols:
                            self.robot.SetDOFValues(solution, self.manip.GetArmIndices())
                            self.env.UpdatePublishedBodies()
                            if self.visualize:
                                rospy.sleep(0.5)
                            J = np.matrix(np.vstack([self.manip.CalculateJacobian(), self.manip.CalculateAngularVelocityJacobian()]))
                            try:
                                joint_limit_weight = self.gen_joint_limit_weight(solution)
                                manip = np.max([copy.copy((m.pow(np.linalg.det(J*joint_limit_weight*J.T), (1./6.)))/(np.trace(J*joint_limit_weight*J.T)/6.)), manip])
                            except ValueError:
                                print 'WARNING!!'
                                print 'Jacobian may be singular or close to singular'
                                print 'Determinant of J*JT is: ', np.linalg.det(J*J.T)
                                manip = np.max([0., manip])
                manip_score += copy.copy(reached * manip*self.weights[num])
                reach_score += copy.copy(reached * self.weights[num])
            else:
                # print 'In base collision! single config distance: ', distance
                if distance < 2.0:
                    return 10. + 1. + (1.25 - distance)

        # Set the weights for the different scores.
        beta = 10.  # Weight on number of reachable goals
        gamma = 1.  # Weight on manipulability of arm at each reachable goal
        zeta = .0007  # Weight on distance to move to get to that goal location
        if reach_score == 0.:
            return 10. + 2*random.random()
        else:
            # print 'Reach score: ', reach_score
            # print 'Manip score: ', manip_score
            return 10.-beta*reach_score-gamma*manip_score  # +zeta*self.distance

    def rotate_head_only(self, neck_rotation, head_rotation):
        if self.model == 'chair':
            v = self.wheelchair.GetActiveDOFValues()
            v[self.wheelchair.GetJoint('wheelchair/neck_twist_joint').GetDOFIndex()] = m.radians(neck_rotation)
            v[self.wheelchair.GetJoint('wheelchair/neck_head_rotz_joint').GetDOFIndex()] = m.radians(head_rotation)
            self.wheelchair.SetActiveDOFValues(v)
            self.env.UpdatePublishedBodies()
        elif self.model == 'autobed':
            v = self.autobed.GetActiveDOFValues()
            v[self.autobed.GetJoint('autobed/neck_twist_joint').GetDOFIndex()] = m.radians(neck_rotation)
            v[self.autobed.GetJoint('autobed/neck_head_rotz_joint').GetDOFIndex()] = m.radians(head_rotation)
            self.autobed.SetActiveDOFValues(v)
            self.env.UpdatePublishedBodies()

    def rotate_head_and_update_goals(self, neck_rotation, head_rotation, current_origin_B_pr2):
        origin_B_pr2 = current_origin_B_pr2
        if self.model == 'chair':
            v = self.wheelchair.GetActiveDOFValues()
            v[self.wheelchair.GetJoint('wheelchair/neck_twist_joint').GetDOFIndex()] = m.radians(neck_rotation)
            v[self.wheelchair.GetJoint('wheelchair/neck_head_rotz_joint').GetDOFIndex()] = m.radians(head_rotation)
            self.wheelchair.SetActiveDOFValues(v)
            self.env.UpdatePublishedBodies()

            self.env.UpdatePublishedBodies()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')
            ual = self.wheelchair.GetLink('wheelchair/arm_left_link')
            uar = self.wheelchair.GetLink('wheelchair/arm_right_link')
            fal = self.wheelchair.GetLink('wheelchair/forearm_left_link')
            far = self.wheelchair.GetLink('wheelchair/forearm_right_link')
            thl = self.wheelchair.GetLink('wheelchair/quad_left_link')
            thr = self.wheelchair.GetLink('wheelchair/quad_right_link')
            kneel = self.wheelchair.GetLink('wheelchair/calf_left_link')
            kneer = self.wheelchair.GetLink('wheelchair/calf_right_link')
            footl = self.wheelchair.GetLink('wheelchair/foot_left_link')
            footr = self.wheelchair.GetLink('wheelchair/foot_right_link')
            ch = self.wheelchair.GetLink('wheelchair/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references[thing] = origin_B_head
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references[thing] = origin_B_pr2
                    # self.origin_B_references[thing] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)
            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(self.origin_B_references[int(self.reference_mat[thing])]*np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
#            for target in self.goals:
#                self.goal_list.append(pr2_B_head*np.matrix(target[0]))
#                self.selection_mat.append(target[1])
            self.set_goals()
            headmodel = self.wheelchair.GetLink('wheelchair/head_link')

        elif self.model == 'autobed':
            self.selection_mat = np.zeros(len(self.goals))
            self.goal_list = np.zeros([len(self.goals), 4, 4])
            # self.set_autobed(bz, bth, self.headx, self.heady)
            v = self.autobed.GetActiveDOFValues()
            v[self.autobed.GetJoint('autobed/neck_twist_joint').GetDOFIndex()] = m.radians(neck_rotation)
            v[self.autobed.GetJoint('autobed/neck_head_rotz_joint').GetDOFIndex()] = m.radians(head_rotation)
            self.autobed.SetActiveDOFValues(v)
            self.env.UpdatePublishedBodies()

            headmodel = self.autobed.GetLink('autobed/head_link')
            ual = self.autobed.GetLink('autobed/arm_left_link')
            uar = self.autobed.GetLink('autobed/arm_right_link')
            fal = self.autobed.GetLink('autobed/forearm_left_link')
            far = self.autobed.GetLink('autobed/forearm_right_link')
            thl = self.autobed.GetLink('autobed/quad_left_link')
            thr = self.autobed.GetLink('autobed/quad_right_link')
            kneel = self.autobed.GetLink('autobed/calf_left_link')
            kneer = self.autobed.GetLink('autobed/calf_right_link')
            footl = self.autobed.GetLink('autobed/foot_left_link')
            footr = self.autobed.GetLink('autobed/foot_right_link')
            ch = self.autobed.GetLink('autobed/upper_body_link')
            origin_B_head = np.matrix(headmodel.GetTransform())
            origin_B_ual = np.matrix(ual.GetTransform())
            origin_B_uar = np.matrix(uar.GetTransform())
            origin_B_fal = np.matrix(fal.GetTransform())
            origin_B_far = np.matrix(far.GetTransform())
            origin_B_thl = np.matrix(thl.GetTransform())
            origin_B_thr = np.matrix(thr.GetTransform())
            origin_B_kneel = np.matrix(kneel.GetTransform())
            origin_B_kneer = np.matrix(kneer.GetTransform())
            origin_B_footl = np.matrix(footl.GetTransform())
            origin_B_footr = np.matrix(footr.GetTransform())
            origin_B_ch = np.matrix(ch.GetTransform())
            self.origin_B_references = []
            for thing in xrange(len(self.reference_names)):
                if self.reference_names[thing] == 'head':
                    self.origin_B_references.append(origin_B_head)
                    # self.origin_B_references.append(np.matrix(headmodel.GetTransform())
                elif self.reference_names[thing] == 'base_link':
                    self.origin_B_references.append(origin_B_pr2)
                    # self.origin_B_references[i] = np.matrix(self.robot.GetTransform())
                elif self.reference_names[thing] == 'upper_arm_left':
                    self.origin_B_references.append(origin_B_ual)
                elif self.reference_names[thing] == 'upper_arm_right':
                    self.origin_B_references.append(origin_B_uar)
                elif self.reference_names[thing] == 'forearm_left':
                    self.origin_B_references.append(origin_B_fal)
                elif self.reference_names[thing] == 'forearm_right':
                    self.origin_B_references.append(origin_B_far)
                elif self.reference_names[thing] == 'thigh_left':
                    self.origin_B_references.append(origin_B_thl)
                elif self.reference_names[thing] == 'thigh_right':
                    self.origin_B_references.append(origin_B_thr)
                elif self.reference_names[thing] == 'knee_left':
                    self.origin_B_references.append(origin_B_kneel)
                elif self.reference_names[thing] == 'knee_right':
                    self.origin_B_references.append(origin_B_kneer)
                elif self.reference_names[thing] == 'foot_left':
                    self.origin_B_references.append(origin_B_footl)
                elif self.reference_names[thing] == 'foot_right':
                    self.origin_B_references.append(origin_B_footr)
                elif self.reference_names[thing] == 'chest':
                    self.origin_B_references.append(origin_B_ch)

            for thing in xrange(len(self.goals)):
                self.goal_list[thing] = copy.copy(self.origin_B_references[int(self.reference_mat[thing])]*np.matrix(self.goals[thing, 0]))
                self.selection_mat[thing] = self.goals[thing, 1]
            # for target in self.goals:
            #     self.goal_list.append(pr2_B_head*np.matrix(target[0]))
            #     self.selection_mat.append(target[1])
            self.set_goals()
        else:
            print 'I GOT A BAD MODEL. NOT SURE WHAT TO DO NOW!'

    def eval_init_config(self, init_config, goal_data):
        start_time = time.time()
        reached = 0.
        mod_x_err_min = -.025
        mod_x_err_max = .025+.02
        mod_x_err_int = .025
        mod_y_err_min = -.025
        mod_y_err_max = .025+.02
        mod_y_err_int = .025
        mod_th_err_min = -m.pi/36.
        mod_th_err_max = m.pi/36.+.02
        mod_th_err_int = m.pi/36.
        x_err_min = -.05
        x_err_max = .05+.02
        x_err_int = .05
        y_err_min = -.05
        y_err_max = .05+.02
        y_err_int = .05
        th_err_min = -m.pi/36.
        th_err_max = m.pi/36.+.02
        th_err_int = m.pi/36.
        h_err_min = -m.pi/9.
        h_err_max = m.pi/9.+.02
        h_err_int = m.pi/9.
        if self.model == 'chair':
            modeling_error = np.array([err for err in ([x_e, y_e, th_e, h_e, m_x_e, m_y_e, m_th_e]
                                                       for x_e in np.arange(x_err_min, x_err_max, x_err_int)
                                                       for y_e in np.arange(y_err_min, y_err_max, y_err_int)
                                                       for th_e in np.arange(th_err_min, th_err_max, th_err_int)
                                                       for h_e in np.arange(h_err_min, h_err_max, h_err_int)
                                                       for m_x_e in np.arange(mod_x_err_min, mod_x_err_max, mod_x_err_int)
                                                       for m_y_e in np.arange(mod_y_err_min, mod_y_err_max, mod_y_err_int)
                                                       for m_th_e in np.arange(mod_th_err_min, mod_th_err_max, mod_th_err_int)
                                                       )
                                       ])
            # modeling_error = np.array([err for err in ([x_e, y_e, th_e, h_e, 0, 0, 0]
            #                                            for x_e in np.arange(x_err_min, x_err_max, x_err_int)
            #                                            for y_e in np.arange(y_err_min, y_err_max, y_err_int)
            #                                            for th_e in np.arange(th_err_min, th_err_max, th_err_int)
            #                                            for h_e in np.arange(h_err_min, h_err_max, h_err_int)
            #                                            # for m_x_e in np.arange(mod_x_err_min, mod_x_err_max, mod_x_err_int)
            #                                            # for m_y_e in np.arange(mod_y_err_min, mod_y_err_max, mod_y_err_int)
            #                                            # for m_th_e in np.arange(mod_th_err_min, mod_th_err_max, mod_th_err_int)
            #                                            )
            #                            ])
        elif self.model == 'autobed':
            modeling_error = np.array([err for err in ([x_e, y_e]
                                                       for x_e in np.arange(x_err_min, x_err_max, x_err_int)
                                                       for y_e in np.arange(y_err_min, y_err_max, y_err_int)
                                                       )
                                       ])
        # print len(modeling_error)
        # for error in modeling_error:
        #     print error

        total_length = copy.copy(len(self.goals)*len(modeling_error))
        for error in modeling_error:
            self.receive_new_goals(goal_data)
            # origin_B_wheelchair = np.matrix([[m.cos(error[2]), -m.sin(error[2]),     0.,  error[0]],
            #                                  [m.sin(error[2]),  m.cos(error[2]),     0.,  error[1]],
            #                                  [             0.,               0.,     1.,        0.],
            #                                  [             0.,               0.,     0.,        1.]])
            # self.wheelchair.SetTransform(np.array(origin_B_wheelchair))
            if self.model == 'chair':
                origin_B_wheelchair = np.matrix([[m.cos(error[6]), -m.sin(error[6]),     0.,  error[4]],
                                                 [m.sin(error[6]),  m.cos(error[6]),     0.,  error[5]],
                                                 [             0.,               0.,     1.,        0.],
                                                 [             0.,               0.,     0.,        1.]])
                self.wheelchair.SetTransform(np.array(origin_B_wheelchair))
                v = self.wheelchair.GetActiveDOFValues()
                v[self.wheelchair.GetJoint('wheelchair_body_x_joint').GetDOFIndex()] = error[0]
                v[self.wheelchair.GetJoint('wheelchair_body_y_joint').GetDOFIndex()] = error[1]
                v[self.wheelchair.GetJoint('wheelchair_body_rotation_joint').GetDOFIndex()] = error[2]
                v[self.wheelchair.GetJoint('head_neck_joint').GetDOFIndex()] = error[3]
                self.wheelchair.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()

            for ic in xrange(len(init_config[0][0])):
                delete_index = []
                x = init_config[0][0][ic]
                y = init_config[0][1][ic]
                th = init_config[0][2][ic]
                z = init_config[0][3][ic]
                bz = init_config[0][4][ic]
                bth = init_config[0][5][ic]
                # print 'bth: ', bth
                origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0.,         x],
                                          [ m.sin(th),  m.cos(th),     0.,         y],
                                          [        0.,         0.,     1.,        0.],
                                          [        0.,         0.,     0.,        1.]])
                self.robot.SetTransform(np.array(origin_B_pr2))
                v = self.robot.GetActiveDOFValues()
                v[self.robot.GetJoint('torso_lift_joint').GetDOFIndex()] = z
                self.robot.SetActiveDOFValues(v, 2)

                if self.model == 'chair':
                    self.env.UpdatePublishedBodies()
                    headmodel = self.wheelchair.GetLink('wheelchair/head_link')
                    origin_B_head = np.matrix(headmodel.GetTransform())
                    self.selection_mat = np.zeros(len(self.goals))
                    self.goal_list = np.zeros([len(self.goals), 4, 4])
                    for thing in xrange(len(self.reference_names)):
                        if self.reference_names[thing] == 'head':
                            self.origin_B_references[thing] = origin_B_head
                        elif self.reference_names[thing] == 'base_link':
                            self.origin_B_references[thing] = origin_B_pr2
                            # self.origin_B_references[j] = np.matrix(self.robot.GetTransform())

                    for thing in xrange(len(self.goals)):
                        self.goal_list[thing] = copy.copy(self.origin_B_references[int(self.reference_mat[thing])]*np.matrix(self.goals[thing, 0]))
                        self.selection_mat[thing] = copy.copy(self.goals[thing, 1])
        #            for target in self.goals:
        #                self.goal_list.append(pr2_B_head*np.matrix(target[0]))
        #                self.selection_mat.append(target[1])
                    self.set_goals()
                elif self.model == 'autobed':
                    self.set_autobed(bz, bth, error[0], error[1])
                    self.env.UpdatePublishedBodies()
                    self.selection_mat = np.zeros(len(self.goals))
                    self.goal_list = np.zeros([len(self.goals), 4, 4])
                    headmodel = self.autobed.GetLink('autobed/head_link')
                    ual = self.autobed.GetLink('autobed/arm_left_link')
                    uar = self.autobed.GetLink('autobed/arm_right_link')
                    fal = self.autobed.GetLink('autobed/forearm_left_link')
                    far = self.autobed.GetLink('autobed/forearm_right_link')
                    thl = self.autobed.GetLink('autobed/quad_left_link')
                    thr = self.autobed.GetLink('autobed/quad_right_link')
                    kneel = self.autobed.GetLink('autobed/calf_left_link')
                    kneer = self.autobed.GetLink('autobed/calf_right_link')
                    footl = self.autobed.GetLink('autobed/foot_left_link')
                    footr = self.autobed.GetLink('autobed/foot_right_link')
                    ch = self.autobed.GetLink('autobed/upper_body_link')
                    origin_B_head = np.matrix(headmodel.GetTransform())
                    origin_B_ual = np.matrix(ual.GetTransform())
                    origin_B_uar = np.matrix(uar.GetTransform())
                    origin_B_fal = np.matrix(fal.GetTransform())
                    origin_B_far = np.matrix(far.GetTransform())
                    origin_B_thl = np.matrix(thl.GetTransform())
                    origin_B_thr = np.matrix(thr.GetTransform())
                    origin_B_kneel = np.matrix(kneel.GetTransform())
                    origin_B_kneer = np.matrix(kneer.GetTransform())
                    origin_B_footl = np.matrix(footl.GetTransform())
                    origin_B_footr = np.matrix(footr.GetTransform())
                    origin_B_ch = np.matrix(ch.GetTransform())
                    for thing in xrange(len(self.reference_names)):
                        if self.reference_names[thing] == 'head':
                            self.origin_B_references[thing] = origin_B_head
                            # self.origin_B_references[thing] = np.matrix(headmodel.GetTransform())
                        elif self.reference_names[thing] == 'base_link':
                            self.origin_B_references[thing] = origin_B_pr2
                            # self.origin_B_references[i] = np.matrix(self.robot.GetTransform())
                        elif self.reference_names[thing] == 'upper_arm_left':
                            self.origin_B_references[thing] = origin_B_ual
                        elif self.reference_names[thing] == 'upper_arm_right':
                            self.origin_B_references[thing] = origin_B_uar
                        elif self.reference_names[thing] == 'forearm_left':
                            self.origin_B_references[thing] = origin_B_fal
                        elif self.reference_names[thing] == 'forearm_right':
                            self.origin_B_references[thing] = origin_B_far
                        elif self.reference_names[thing] == 'thigh_left':
                            self.origin_B_references[thing] = origin_B_thl
                        elif self.reference_names[thing] == 'thigh_right':
                            self.origin_B_references[thing] = origin_B_thr
                        elif self.reference_names[thing] == 'knee_left':
                            self.origin_B_references[thing] = origin_B_kneel
                        elif self.reference_names[thing] == 'knee_right':
                            self.origin_B_references[thing] = origin_B_kneer
                        elif self.reference_names[thing] == 'foot_left':
                            self.origin_B_references.append(origin_B_footl)
                        elif self.reference_names[thing] == 'foot_right':
                            self.origin_B_references.append(origin_B_footr)
                        elif self.reference_names[thing] == 'chest':
                            self.origin_B_references[thing] = origin_B_ch

                    for thing in xrange(len(self.goals)):
                        self.goal_list[thing] = copy.copy(self.origin_B_references[int(self.reference_mat[thing])]*np.matrix(self.goals[thing, 0]))
                        self.selection_mat[thing] = copy.copy(self.goals[thing, 1])
                    # for target in self.goals:
                    #     self.goal_list.append(pr2_B_head*np.matrix(target[0]))
                    #     self.selection_mat.append(target[1])
                    self.set_goals()
                # print 'self.goals length: ', len(self.goals)
                # print 'self.origin_B_grasps length: ', len(self.origin_B_grasps)
                with self.robot:
                    if True:
                    # if not self.manip.CheckIndependentCollision(op.CollisionReport()):
                        #print 'not colliding with environment'
                        for num, Tgrasp in enumerate(self.origin_B_grasps):
                            sol = None
                            sol = self.manip.FindIKSolution(Tgrasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)
                            # sol = self.manip.FindIKSolution(Tgrasp,filteroptions=op.IkFilterOptions.IgnoreSelfCollisions)
                            if sol is not None:
                                reached += 1.
                                delete_index.append(num)
                                if self.visualize:
                                    self.robot.SetDOFValues(sol, self.manip.GetArmIndices())
                                    self.env.UpdatePublishedBodies()
                                    rospy.sleep(2)

                # print 'goal list: ', self.goals
                # print 'delete list: ', delete_index
                if len(self.goals) > 0:
                    self.goals = np.delete(self.goals, delete_index, 0)
        score = reached/total_length
        print 'Score is (% of reached goals): ', score
        print 'Time to score this initial configuration: %fs' % (time.time()-start_time)
        return score

    def mc_eval_init_config(self, init_config, goal_data, reference_names, model=None, task=None, seed=None, error=None):
        # print init_config
        # init_config = np.array([[ 1.10995678,  0.47979084],
        #                         [ 0.6339488 , -0.82258422],
        #                         [-1.9750257 , -4.41014986],
        #                         [ 0.27075026,  0.14017833],
        #                         [ 0.17188331,  0.08067813],
        #                         [ 0.93374424,  0.21362207]])
        # print init_config
        self.receive_new_goals(goal_data, reference_options=reference_names, model=model)
        # print 'goal data\n',goal_data
        # print 'self.goals\n',self.goals
        # print 'self.reference_names', self.reference_names
        # print init_config
        if seed is None:
            seed = int(time.time())
        if task is not None:
            self.task = task
        if not model is None:
            if not model == self.model:
                self.env.Remove(self.env.GetRobots()[1])
                self.model = model
                self.setup_human_model()
                # rospy.sleep(0.1)
                if (self.task == 'wiping_mouth' or self.task == 'shaving' or self.task == 'feeding_trajectory' or self.task == 'brushing') and self.model == 'chair':
                    self.head_angles = np.array([[68, 10], [68, 0], [68, -10], [0, 0], [-68, 10], [68, 0], [-68, -10]])
                    self.head_angles = np.array([[60., 0.], [0., 0.],  [-60., 0.]])
                else:
                    self.head_angles = np.array([[0., 0.]])
        start_time = time.time()
        reached = 0.
        total_number_of_goals = len(goal_data)
        random_state = np.random.RandomState(seed=seed)
        pr2_x_e = random_state.normal(0., 0.01)
        pr2_y_e = random_state.normal(0., 0.01)
        pr2_th_e = random_state.normal(0., (m.pi/72.))
        x_e = random_state.normal(0., 0.025)
        y_e = random_state.normal(0., 0.05)
        th_e = random_state.normal(0., (m.pi/36))
        h_e = random_state.normal(0., (m.pi/18)/2)

        # self.reference_names = reference_options
        if error is None:
            if self.model == 'chair':
                error = np.array([x_e, y_e, th_e, pr2_x_e, pr2_y_e, pr2_th_e])
            elif self.model == 'autobed':
                # modeling_error = np.array([[x_e, y_e, m_x_e, m_y_e, m_th_e]])
                error = np.array([x_e, y_e, 0., pr2_x_e, pr2_y_e, pr2_th_e])
        # error = np.zeros(6)
        total_length = len(goal_data)
        # for error in modeling_error:
        # self.receive_new_goals(goal_data)
        # origin_B_wheelchair = np.matrix([[m.cos(error[2]), -m.sin(error[2]),     0.,  error[0]],
        #                                  [m.sin(error[2]),  m.cos(error[2]),     0.,  error[1]],
        #                                  [             0.,               0.,     1.,        0.],
        #                                  [             0.,               0.,     0.,        1.]])
        # self.wheelchair.SetTransform(np.array(origin_B_wheelchair))
        # origin_B_wheelchair = np.matrix([[m.cos(error[6]), -m.sin(error[6]),     0.,  error[4]],
        #                                  [m.sin(error[6]),  m.cos(error[6]),     0.,  error[5]],
        #                                  [             0.,               0.,     1.,        0.],
        #                                  [             0.,               0.,     0.,        1.]])
        # self.wheelchair.SetTransform(np.array(origin_B_wheelchair))
        delete_index = []
        config = np.reshape(list(flatten(init_config)), [6, len(list(flatten(init_config)))/6])

        for n_conf in xrange(len(config[0])):
            if len(self.goals) > 0:
                delete_index = []

                x = config[0, n_conf]
                y = config[1, n_conf]
                th = config[2, n_conf]
                z = config[3, n_conf]
                bz = config[4, n_conf]
                bth = config[5, n_conf]
                # print 'bth: ', bth
                # origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0.,         x],
                #                           [ m.sin(th),  m.cos(th),     0.,         y],
                #                           [        0.,         0.,     1.,        0.],
                #                           [        0.,         0.,     0.,        1.]])
                origin_B_pr2 = np.matrix([[ m.cos(th+error[5]), -m.sin(th+error[5]),     0.,         x+error[3]],
                                          [ m.sin(th+error[5]),  m.cos(th+error[5]),     0.,         y+error[4]],
                                          [        0.,         0.,     1.,        0.],
                                          [        0.,         0.,     0.,        1.]])
                self.robot.SetTransform(np.array(origin_B_pr2))
                v = self.robot.GetActiveDOFValues()
                v[self.robot.GetJoint('torso_lift_joint').GetDOFIndex()] = z
                self.robot.SetActiveDOFValues(v, 2)
                # self.env.UpdatePublishedBodies()
                if self.model == 'chair':
                    v = self.wheelchair.GetActiveDOFValues()
                    v[self.wheelchair.GetJoint('wheelchair/body_x_move_joint').GetDOFIndex()] = error[0]
                    v[self.wheelchair.GetJoint('wheelchair/body_y_move_joint').GetDOFIndex()] = error[1]
                    v[self.wheelchair.GetJoint('wheelchair/body_theta_move_joint').GetDOFIndex()] = error[2]
                    # v[self.wheelchair.GetJoint('head_neck_joint').GetDOFIndex()] = error[3]
                    self.wheelchair.SetActiveDOFValues(v, 2)
                    self.env.UpdatePublishedBodies()
                    self.selection_mat = np.zeros(len(self.goals))
                    self.goal_list = np.zeros([len(self.goals), 4, 4])
                    headmodel = self.wheelchair.GetLink('wheelchair/head_link')
                    ual = self.wheelchair.GetLink('wheelchair/arm_left_link')
                    uar = self.wheelchair.GetLink('wheelchair/arm_right_link')
                    fal = self.wheelchair.GetLink('wheelchair/forearm_left_link')
                    far = self.wheelchair.GetLink('wheelchair/forearm_right_link')
                    thl = self.wheelchair.GetLink('wheelchair/quad_left_link')
                    thr = self.wheelchair.GetLink('wheelchair/quad_right_link')
                    kneel = self.wheelchair.GetLink('wheelchair/calf_left_link')
                    kneer = self.wheelchair.GetLink('wheelchair/calf_right_link')
                    footl = self.wheelchair.GetLink('wheelchair/foot_left_link')
                    footr = self.wheelchair.GetLink('wheelchair/foot_right_link')
                    ch = self.wheelchair.GetLink('wheelchair/upper_body_link')
                    origin_B_head = np.matrix(headmodel.GetTransform())
                    origin_B_ual = np.matrix(ual.GetTransform())
                    origin_B_uar = np.matrix(uar.GetTransform())
                    origin_B_fal = np.matrix(fal.GetTransform())
                    origin_B_far = np.matrix(far.GetTransform())
                    origin_B_thl = np.matrix(thl.GetTransform())
                    origin_B_thr = np.matrix(thr.GetTransform())
                    origin_B_kneel = np.matrix(kneel.GetTransform())
                    origin_B_kneer = np.matrix(kneer.GetTransform())
                    origin_B_footl = np.matrix(footl.GetTransform())
                    origin_B_footr = np.matrix(footr.GetTransform())
                    origin_B_ch = np.matrix(ch.GetTransform())
                    self.origin_B_references = []
                    for thing in xrange(len(self.reference_names)):
                        if self.reference_names[thing] == 'head':
                            self.origin_B_references.append(origin_B_head)
                            # self.origin_B_references.append(np.matrix(headmodel.GetTransform())
                        elif self.reference_names[thing] == 'base_link':
                            self.origin_B_references.append(origin_B_pr2)
                            # self.origin_B_references[i] = np.matrix(self.robot.GetTransform())
                        elif self.reference_names[thing] == 'upper_arm_left':
                            self.origin_B_references.append(origin_B_ual)
                        elif self.reference_names[thing] == 'upper_arm_right':
                            self.origin_B_references.append(origin_B_uar)
                        elif self.reference_names[thing] == 'forearm_left':
                            self.origin_B_references.append(origin_B_fal)
                        elif self.reference_names[thing] == 'forearm_right':
                            self.origin_B_references.append(origin_B_far)
                        elif self.reference_names[thing] == 'thigh_left':
                            self.origin_B_references.append(origin_B_thl)
                        elif self.reference_names[thing] == 'thigh_right':
                            self.origin_B_references.append(origin_B_thr)
                        elif self.reference_names[thing] == 'knee_left':
                            self.origin_B_references.append(origin_B_kneel)
                        elif self.reference_names[thing] == 'knee_right':
                            self.origin_B_references.append(origin_B_kneer)
                        elif self.reference_names[thing] == 'foot_left':
                            self.origin_B_references.append(origin_B_footl)
                        elif self.reference_names[thing] == 'foot_right':
                            self.origin_B_references.append(origin_B_footr)
                        elif self.reference_names[thing] == 'chest':
                            self.origin_B_references.append(origin_B_ch)
                    for thing in xrange(len(self.goals)):
                        self.goal_list[thing] = copy.copy(
                            self.origin_B_references[int(self.goals[thing][2])] * np.matrix(self.goals[thing, 0]))
                        self.selection_mat[thing] = self.goals[thing, 1]
                        #            for target in self.goals:
                        #                self.goal_list.append(pr2_B_head*np.matrix(target[0]))
                        #                self.selection_mat.append(target[1])
                    self.set_goals()
                    headmodel = self.wheelchair.GetLink('wheelchair/head_link')
                elif self.model == 'autobed':
                    self.set_autobed(bz, bth, error[0], error[1])
                    self.env.UpdatePublishedBodies()
                    rospy.sleep(0.01)
                    self.selection_mat = np.zeros(len(self.goals))
                    self.goal_list = np.zeros([len(self.goals), 4, 4])
                    headmodel = self.autobed.GetLink('autobed/head_link')
                    ual = self.autobed.GetLink('autobed/arm_left_link')
                    uar = self.autobed.GetLink('autobed/arm_right_link')
                    fal = self.autobed.GetLink('autobed/forearm_left_link')
                    far = self.autobed.GetLink('autobed/forearm_right_link')
                    thl = self.autobed.GetLink('autobed/quad_left_link')
                    thr = self.autobed.GetLink('autobed/quad_right_link')
                    kneel = self.autobed.GetLink('autobed/calf_left_link')
                    kneer = self.autobed.GetLink('autobed/calf_right_link')
                    footl = self.autobed.GetLink('autobed/foot_left_link')
                    footr = self.autobed.GetLink('autobed/foot_right_link')
                    ch = self.autobed.GetLink('autobed/upper_body_link')
                    origin_B_head = np.matrix(headmodel.GetTransform())
                    origin_B_ual = np.matrix(ual.GetTransform())
                    origin_B_uar = np.matrix(uar.GetTransform())
                    origin_B_fal = np.matrix(fal.GetTransform())
                    origin_B_far = np.matrix(far.GetTransform())
                    origin_B_thl = np.matrix(thl.GetTransform())
                    origin_B_thr = np.matrix(thr.GetTransform())
                    origin_B_kneel = np.matrix(kneel.GetTransform())
                    origin_B_kneer = np.matrix(kneer.GetTransform())
                    origin_B_footl = np.matrix(footl.GetTransform())
                    origin_B_footr = np.matrix(footr.GetTransform())
                    origin_B_ch = np.matrix(ch.GetTransform())
                    self.origin_B_references = []
                    for thing in xrange(len(self.reference_names)):
                        if self.reference_names[thing] == 'head':
                            self.origin_B_references.append(origin_B_head)
                            # self.origin_B_references.append(np.matrix(headmodel.GetTransform())
                        elif self.reference_names[thing] == 'base_link':
                            self.origin_B_references.append(origin_B_pr2)
                            # self.origin_B_references[i] = np.matrix(self.robot.GetTransform())
                        elif self.reference_names[thing] == 'upper_arm_left':
                            self.origin_B_references.append(origin_B_ual)
                        elif self.reference_names[thing] == 'upper_arm_right':
                            self.origin_B_references.append(origin_B_uar)
                        elif self.reference_names[thing] == 'forearm_left':
                            self.origin_B_references.append(origin_B_fal)
                        elif self.reference_names[thing] == 'forearm_right':
                            self.origin_B_references.append(origin_B_far)
                        elif self.reference_names[thing] == 'thigh_left':
                            self.origin_B_references.append(origin_B_thl)
                        elif self.reference_names[thing] == 'thigh_right':
                            self.origin_B_references.append(origin_B_thr)
                        elif self.reference_names[thing] == 'knee_left':
                            self.origin_B_references.append(origin_B_kneel)
                        elif self.reference_names[thing] == 'knee_right':
                            self.origin_B_references.append(origin_B_kneer)
                        elif self.reference_names[thing] == 'foot_left':
                            self.origin_B_references.append(origin_B_footl)
                        elif self.reference_names[thing] == 'foot_right':
                            self.origin_B_references.append(origin_B_footr)
                        elif self.reference_names[thing] == 'chest':
                            self.origin_B_references.append(origin_B_ch)
                    # print len(self.origin_B_references)
                    for thing in xrange(len(self.goals)):
                        self.goal_list[thing] = copy.copy(
                            self.origin_B_references[int(self.goals[thing][2])] * np.matrix(self.goals[thing, 0]))
                        self.selection_mat[thing] = self.goals[thing, 1]
                        # print self.selection_mat[thing]
                    # for target in self.goals:
                    #     self.goal_list.append(pr2_B_head*np.matrix(target[0]))
                    #     self.selection_mat.append(target[1])
                    self.set_goals()
                # print 'self.goals length: ', len(self.goals)
                # print 'self.origin_B_grasps length: ', len(self.origin_B_grasps)
                with self.robot:
                    v = self.robot.GetActiveDOFValues()
                    if self.arm[0] == 'l':
                        arm_sign = 1
                    else:
                        arm_sign = -1
                    in_collision = True
                    v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
                    v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                    v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
                    v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                    v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (-3.5)
                    v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                    v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
                    v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (
                    -1.8)
                    v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                    v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (
                    -1.9)
                    v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                    v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
                    v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                    v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
                    self.robot.SetActiveDOFValues(v, 2)
                    self.env.UpdatePublishedBodies()
                    # rospy.sleep(10)
                    in_collision = self.env.CheckCollision(self.robot)
                    if in_collision:
                        v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * 3.14 / 2
                        v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                        v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                        v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.

                        v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = -3.14 / 2
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.
                        self.robot.SetActiveDOFValues(v, 2)
                        self.env.UpdatePublishedBodies()
                        in_collision = self.env.CheckCollision(self.robot)
                        # rospy.sleep(10)
                    if in_collision:
                        v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
                        v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                        v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
                        v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                        v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (-3.5)
                        v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                        v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0

                        v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = -3.14 / 2
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.
                        self.robot.SetActiveDOFValues(v, 2)
                        self.env.UpdatePublishedBodies()
                        in_collision = self.env.CheckCollision(self.robot)
                        # rospy.sleep(10)
                    if in_collision:
                        v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * 3.14 / 2
                        v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.52
                        v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                        v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = 0.
                        v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.

                        v[self.robot.GetJoint(
                            self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
                        v[self.robot.GetJoint(
                            self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
                        v[self.robot.GetJoint(
                            self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
                        v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
                        self.robot.SetActiveDOFValues(v, 2)
                        self.env.UpdatePublishedBodies()
                        in_collision = self.env.CheckCollision(self.robot)
                    # if True:
                    # reached = np.zeros(len(self.origin_B_grasps))
                    if not in_collision:
                        # reached = np.zeros(len(self.origin_B_grasps))
                        # print self.head_angles
                        for num, Tgrasp in enumerate(self.origin_B_grasps):
                            # print 'num:',num
                            this_reached = 0
                            for head_angle in self.head_angles:
                                # self.rotate_head_and_update_goals(head_angle[0], head_angle[1], origin_B_pr2)
                                sol = None
                                sol = self.manip.FindIKSolution(Tgrasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)
                                # sol = self.manip.FindIKSolution(Tgrasp,filteroptions=op.IkFilterOptions.IgnoreSelfCollisions)

                                if sol is not None:
                                    this_reached = 1
                                    # delete_index.append(num)
                                    if self.visualize:
                                        # for sol in sols:
                                        self.robot.SetDOFValues(sol, self.manip.GetArmIndices())
                                        self.env.UpdatePublishedBodies()
                                        rospy.sleep(1.)
                            if this_reached == 1:
                                delete_index.append(num)
                            reached += this_reached

                # print 'goal list: ', self.goals
                # print 'delete list: ', delete_index
                if len(self.goals) > 0:
                    self.goals = np.delete(self.goals, delete_index, 0)
        accuracy = float(reached)/total_number_of_goals
        if reached == total_number_of_goals:
            success = 1
        else:
            success = 0
        # if score < 0.9:
        #     print 'Score was less than 0.9. The error added was: ', modeling_error
        # print 'Score is (% of reached goals): ', score
        # print 'success:', success
        # print 'Time to score this initial configuration: %fs' % (time.time()-start_time)
        return accuracy, success

    def setup_openrave(self):
        # Setup Openrave ENV
        InitOpenRAVELogging()
        self.env = op.Environment()

        # Lets you visualize openrave. Uncomment to see visualization. Does not work footrough ssh.
        if self.visualize:
            self.env.SetViewer('qtcoin')

        ## Set up robot state node to do Jacobians. This works, but is commented out because we can do it with openrave
        #  fine.
        # torso_frame = '/torso_lift_link'
        # inertial_frame = '/base_link'
        # end_effector_frame = '/l_gripper_tool_frame'
        # from pykdl_utils.kdl_kinematics import create_kdl_kin
        # self.kinematics = create_kdl_kin(torso_frame, end_effector_frame)

        ## Load OpenRave PR2 Model
        self.env.Load('robots/pr2-beta-static.zae')
        self.robot = self.env.GetRobots()[0]
        self.robot.CheckLimitsAction = 2
        v = self.robot.GetActiveDOFValues()
        # v[self.robot.GetJoint(self.arm[0]+'_shoulder_pan_joint').GetDOFIndex()] = 3.14/2
        # v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_pan_joint').GetDOFIndex()] = -3.14/2
        # v[self.robot.GetJoint(self.opposite_arm[0]+'_shoulder_lift_joint').GetDOFIndex()] = -0.52
        # v[self.robot.GetJoint(self.opposite_arm[0]+'_upper_arm_roll_joint').GetDOFIndex()] = 0.
        # v[self.robot.GetJoint(self.opposite_arm[0]+'_elbow_flex_joint').GetDOFIndex()] = -3.14*2/3
        # v[self.robot.GetJoint(self.opposite_arm[0]+'_forearm_roll_joint').GetDOFIndex()] = 0.
        # v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_flex_joint').GetDOFIndex()] = 0.
        # v[self.robot.GetJoint(self.opposite_arm[0]+'_wrist_roll_joint').GetDOFIndex()] = 0.
        # v[self.robot.GetJoint(self.arm[0]+'_gripper_l_finger_joint').GetDOFIndex()] = .1

        if self.arm[0] == 'l':
            arm_sign = 1
        else:
            arm_sign = -1
        if False and (self.task == 'blanket_feet_knees' or self.task == 'scratching_knee_left'):
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * 3. * 3.14159 / 4.
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = -0.6
            v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * m.radians(20)
            v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = m.radians(-150.)
            v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = m.radians(150.)
            v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = m.radians(-110)
            v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = arm_sign * 0.0
        elif True or (self.task == 'wiping_mouth' or self.task == 'wiping_forehead'):
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (1.8)
            v[self.robot.GetJoint(self.arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
            v[self.robot.GetJoint(self.arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (1.9)
            v[self.robot.GetJoint(self.arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
            v[self.robot.GetJoint(self.arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * (-3.5)
            v[self.robot.GetJoint(self.arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
            v[self.robot.GetJoint(self.arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
            v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
            v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
            v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
            v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0
            # v[self.robot.GetJoint(self.arm[0]+'_shoulder_pan_joint').GetDOFIndex()] = arm_sign*0.8
            # v[self.robot.GetJoint(self.arm[0]+'_shoulder_lift_joint').GetDOFIndex()] = 0.0
            # v[self.robot.GetJoint(self.arm[0]+'_upper_arm_roll_joint').GetDOFIndex()] = arm_sign*1.57
            # v[self.robot.GetJoint(self.arm[0]+'_elbow_flex_joint').GetDOFIndex()] = -2.9
            # v[self.robot.GetJoint(self.arm[0]+'_forearm_roll_joint').GetDOFIndex()] = 3.0
            # v[self.robot.GetJoint(self.arm[0]+'_wrist_flex_joint').GetDOFIndex()] = -1.0
            # v[self.robot.GetJoint(self.arm[0]+'_wrist_roll_joint').GetDOFIndex()] = arm_sign*1.57
        else:
            print 'The arm initial pose is not defined properly.'
            v[self.robot.GetJoint('I HAVE NO IDEA WHAT TASK Im DOING').GetDOFIndex()] = 0.
        v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_pan_joint').GetDOFIndex()] = arm_sign * (-1.8)
        v[self.robot.GetJoint(self.opposite_arm[0] + '_shoulder_lift_joint').GetDOFIndex()] = 2.45
        v[self.robot.GetJoint(self.opposite_arm[0] + '_upper_arm_roll_joint').GetDOFIndex()] = arm_sign * (-1.9)
        v[self.robot.GetJoint(self.opposite_arm[0] + '_elbow_flex_joint').GetDOFIndex()] = -2.0
        v[self.robot.GetJoint(self.opposite_arm[0] + '_forearm_roll_joint').GetDOFIndex()] = arm_sign * 3.5
        v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_flex_joint').GetDOFIndex()] = -1.5
        v[self.robot.GetJoint(self.opposite_arm[0] + '_wrist_roll_joint').GetDOFIndex()] = 0.0

        # v[self.robot.GetJoint(self.arm[0]+'_gripper_r_finger_joint').GetDOFIndex()] = .54
        v[self.robot.GetJoint(self.arm[0] + '_gripper_l_finger_joint').GetDOFIndex()] = .1
        v[self.robot.GetJoint('torso_lift_joint').GetDOFIndex()] = 0.0
        self.robot.SetActiveDOFValues(v, 2)
        robot_start = np.matrix([[m.cos(0.), -m.sin(0.), 0., 0.],
                                 [m.sin(0.), m.cos(0.), 0., 0.],
                                 [0., 0., 1., 0.],
                                 [0., 0., 0., 1.]])
        self.robot.SetTransform(np.array(robot_start))

        ## Set robot manipulators, ik, planner
        self.arm = 'leftarm'
        self.robot.SetActiveManipulator(self.arm)

        self.manip = self.robot.GetActiveManipulator()
        self.ikmodel = op.databases.inversekinematics.InverseKinematicsModel(self.robot,
                                                                             iktype=op.IkParameterization.Type.Transform6D)
        # free_joints=[self.arm[0]+'_shoulder_pan_joint', self.arm[0]+'_shoulder_lift_joint', self.arm[0]+'_upper_arm_roll_joint', self.arm[0]+'_elbow_flex_joint']  # , self.arm[0]+'_forearm_roll_joint', self.arm[0]+'_wrist_flex_joint', self.arm[0]+'_wrist_roll_joint']
        # self.ikmodel = op.databases.inversekinematics.InverseKinematicsModel(self.robot, iktype=op.IkParameterization.Type.Translation3D, freejoints=free_joints)
        if not self.ikmodel.load():
            print 'IK model not found for leftarm. Will now generate an IK model. This will take a while!'
            self.ikmodel.autogenerate()
            # free_joints=[self.arm[0]+'_shoulder_pan_joint', self.arm[0]+'_shoulder_lift_joint', self.arm[0]+'_upper_arm_roll_joint', self.arm[0]+'_elbow_flex_joint']  # , self.arm[0]+'_forearm_roll_joint', self.arm[0]+'_wrist_flex_joint', self.arm[0]+'_wrist_roll_joint']
            # print free_joints
            # free_joints=[]
            # self.ikmodel.generate(iktype=op.IkParameterizationType.Translation3D, freejoints=free_joints, freeinc=[0.1,0.1,0.1,0.1])

        if self.model is None:
            ## Set robot manipulators, ik, planner
            self.arm = 'rightarm'
            self.robot.SetActiveManipulator(self.arm)
            self.manip = self.robot.GetActiveManipulator()
            self.ikmodel = op.databases.inversekinematics.InverseKinematicsModel(self.robot,
                                                                                 iktype=op.IkParameterization.Type.Transform6D)
            # self.ikmodel = op.databases.inversekinematics.InverseKinematicsModel(self.robot, iktype=op.IkParameterization.Type.Translation3D)
            if not self.ikmodel.load():
                print 'IK model not found for rightarm. Will now generate an IK model. This will take a while!'
                self.ikmodel.autogenerate()
                # self.ikmodel.generate(iktype=op.IkParameterizationType.Translation3D, freejoints=[self.arm[0]+'_shoulder_pan_joint', self.arm[0]+'_shoulder_lift_joint', self.arm[0]+'_upper_arm_roll_joint', self.arm[0]+'_elbow_flex_joint'], freeinc=0.01)
            ## Set robot manipulators, ik, planner
            self.arm = 'leftarm'
            self.robot.SetActiveManipulator(self.arm)
            self.manip = self.robot.GetActiveManipulator()
            self.ikmodel = op.databases.inversekinematics.InverseKinematicsModel(self.robot,
                                                                                 iktype=op.IkParameterization.Type.Transform6D)
            # self.ikmodel = op.databases.inversekinematics.InverseKinematicsModel(self.robot, iktype=op.IkParameterization.Type.Translation3D)
            if not self.ikmodel.load():
                print 'IK model not found for leftarm. Will now generate an IK model. This will take a while!'
                self.ikmodel.autogenerate()
                # self.ikmodel.generate(iktype=op.IkParameterizationType.Translation3D, freejoints=[self.arm[0]+'_shoulder_pan_joint', self.arm[0]+'_shoulder_lift_joint', self.arm[0]+'_upper_arm_roll_joint', self.arm[0]+'_elbow_flex_joint'], freeinc=0.01)
        # create the interface for basic manipulation programs
        self.manipprob = op.interfaces.BaseManipulation(self.robot)

        self.setup_human_model(init=True)

    def setup_human_model(self, height=None, init=False):
        # Height must be of the form X.X in meters.

        ## Find and load Wheelchair Model
        rospack = rospkg.RosPack()
        pkg_path = rospack.get_path('hrl_base_selection')
        # Transform from the coordinate frame of the wc model in the back right bottom corner, to the head location on the floor
        if self.model == 'chair':
            '''
            self.env.Load(''.join([pkg_path, '/collada/wheelchair_and_body_assembly.dae']))
            originsubject_B_headfloor = np.matrix([[m.cos(0.), -m.sin(0.),  0.,      0.], #.45 #.438
                                                   [m.sin(0.),  m.cos(0.),  0.,      0.], #0.34 #.42
                                                   [       0.,         0.,  1.,      0.],
                                                   [       0.,         0.,  0.,      1.]])
            '''
            # This is the new wheelchair model
            if True:
                # Normal is for testing
                # Expanded is for training
                if not self.training:
                    print 'Loading normal non-expanded version of wheelchair'
                    self.env.Load(''.join([pkg_path, '/collada/wheelchair_simulation_normal_rounded.dae']))
                else:
                    print 'Loading expanded version of wheelchair used for training'
                    self.env.Load(''.join([pkg_path, '/collada/wheelchair_simulation_expanded_rounded.dae']))
                rospy.sleep(0.01)
                print self.env.GetRobots()
                self.wheelchair = self.env.GetRobots()[1]


                v = self.wheelchair.GetActiveDOFValues()
                v[self.wheelchair.GetJoint('wheelchair/neck_twist_joint').GetDOFIndex()] = 0  # m.radians(60)
                v[self.wheelchair.GetJoint('wheelchair/neck_tilt_joint').GetDOFIndex()] = 0.75
                v[self.wheelchair.GetJoint('wheelchair/neck_head_rotz_joint').GetDOFIndex()] = 0  # -m.radians(30)
                v[self.wheelchair.GetJoint('wheelchair/neck_head_roty_joint').GetDOFIndex()] = -0.45
                v[self.wheelchair.GetJoint('wheelchair/neck_head_rotx_joint').GetDOFIndex()] = 0
                v[self.wheelchair.GetJoint('wheelchair/neck_body_joint').GetDOFIndex()] = -0.15
                v[self.wheelchair.GetJoint('wheelchair/upper_mid_body_joint').GetDOFIndex()] = 0.4
                v[self.wheelchair.GetJoint('wheelchair/mid_lower_body_joint').GetDOFIndex()] = 0.4
                v[self.wheelchair.GetJoint('wheelchair/body_quad_left_joint').GetDOFIndex()] = 0.5
                v[self.wheelchair.GetJoint('wheelchair/body_quad_right_joint').GetDOFIndex()] = 0.5
                v[self.wheelchair.GetJoint('wheelchair/quad_calf_left_joint').GetDOFIndex()] = 1.3
                v[self.wheelchair.GetJoint('wheelchair/quad_calf_right_joint').GetDOFIndex()] = 1.3
                v[self.wheelchair.GetJoint('wheelchair/calf_foot_left_joint').GetDOFIndex()] = 0.2
                v[self.wheelchair.GetJoint('wheelchair/calf_foot_right_joint').GetDOFIndex()] = 0.2
                v[self.wheelchair.GetJoint('wheelchair/body_arm_left_joint').GetDOFIndex()] = 0.6
                v[self.wheelchair.GetJoint('wheelchair/body_arm_right_joint').GetDOFIndex()] = 0.6
                v[self.wheelchair.GetJoint('wheelchair/arm_forearm_left_joint').GetDOFIndex()] = .8
                v[self.wheelchair.GetJoint('wheelchair/arm_forearm_right_joint').GetDOFIndex()] = .8
                v[self.wheelchair.GetJoint('wheelchair/forearm_hand_left_joint').GetDOFIndex()] = 0.
                v[self.wheelchair.GetJoint('wheelchair/forearm_hand_right_joint').GetDOFIndex()] = 0.
                self.wheelchair.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()
            else:
                self.env.Load(''.join([pkg_path, '/collada/wheelchair_and_body_assembly.dae']))
                self.wheelchair = self.env.GetRobots()[1]

                v = self.wheelchair.GetActiveDOFValues()
                v[self.wheelchair.GetJoint('wheelchair/wheelchair_body_rotation_joint').GetDOFIndex()] = 0.6
                v[self.wheelchair.GetJoint('wheelchair/wheelchair_body_x_joint').GetDOFIndex()] = .8
                v[self.wheelchair.GetJoint('wheelchair/wheelchair_body_y_joint').GetDOFIndex()] = .8
                v[self.wheelchair.GetJoint('wheelchair/head_neck_joint').GetDOFIndex()] = 0.
                self.wheelchair.SetActiveDOFValues(v, 2)
                self.env.UpdatePublishedBodies()

            headmodel = self.wheelchair.GetLink('wheelchair/head_link')
            head_T = np.matrix(headmodel.GetTransform())
            self.originsubject_B_headfloor = np.matrix([[1., 0., 0., head_T[0, 3]],  # .442603 #.45 #.438
                                                        [0., 1., 0., head_T[1, 3]],  # 0.34 #.42
                                                        [0., 0., 1., 0.],
                                                        [0., 0., 0., 1.]])
            self.originsubject_B_originworld = np.matrix(np.eye(4))
            self.subject = self.env.GetBodies()[1]
            self.subject.SetTransform(np.array(self.originsubject_B_originworld))
            self.a_model_is_loaded = True
        elif self.model == 'bed':
            self.env.Load(''.join([pkg_path, '/models/head_bed.dae']))
            an = 0  # m.pi/2
            self.originsubject_B_headfloor = np.matrix([[m.cos(an), 0., m.sin(an), .2954],  # .45 #.438
                                                        [0., 1., 0., 0.],  # 0.34 #.42
                                                        [-m.sin(an), 0., m.cos(an), 0.],
                                                        [0., 0., 0., 1.]])
            self.originsubject_B_originworld = copy.copy(self.originsubject_B_headfloor)
            self.subject = self.env.GetBodies()[1]
            self.subject.SetTransform(np.array(self.originsubject_B_originworld))
            self.a_model_is_loaded = True
        elif self.model == 'autobed':
            # self.env.Load(''.join([pkg_path, '/collada/bed_and_body_v3_real_expanded_rounded.dae']))
            # self.env.Load(''.join([pkg_path, '/collada/bed_and_body_expanded_rounded.dae']))
            # self.env.Load(''.join([pkg_path, '/collada/bed_and_environment_henry_tray_rounded.dae']))
            if not height or True:
                # self.env.Load(''.join(
                #     [pkg_path, '/collada/bed_and_environment_cali_parameterized_tray_openrave_rounded.dae']))
                # Normal is for testing
                # Expanded is for training
                # rospy.sleep(0.05)
                if not self.training:
                    print 'Loading normal non-expanded version of autobed'
                    self.env.Load(''.join([pkg_path, '/collada/autobed_simulation_normal_rounded.dae']))
                else:
                    print 'Loading expanded version of autobed used for training'
                    self.env.Load(''.join([pkg_path, '/collada/autobed_simulation_expanded_rounded.dae']))
            else:  # Height must be of the form X.X in meters.
                parsed_number = str(height)[0] + '_' + str(height)[2] + 'm'
                self.env.Load(''.join([pkg_path,
                                       '/collada/bed_and_environment_cali_' + parsed_number + '_tray_openrave_rounded.dae']))
            rospy.sleep(0.01)
            self.autobed = self.env.GetRobots()[1]
            v = self.autobed.GetActiveDOFValues()
            shift = 0.
            #            if self.task == 'scratching_knee_left':
            #            shift = 0.02
            # 0 degrees, 0 height
            bth = 0
            if False:  # This is the new parameterized version of the model
                v[self.autobed.GetJoint('autobed/tele_legs_joint').GetDOFIndex()] = 0
                v[self.autobed.GetJoint('autobed/bed_neck_base_updown_bedframe_joint').GetDOFIndex()] = 0
                v[self.autobed.GetJoint('autobed/bed_neck_base_leftright_joint').GetDOFIndex()] = 0
                v[self.autobed.GetJoint('autobed/leg_rest_lower_overbed_tray_y_joint').GetDOFIndex()] = 0
                v[self.autobed.GetJoint('autobed/leg_rest_lower_overbed_tray_x_joint').GetDOFIndex()] = -0.6858
                v[self.autobed.GetJoint('autobed/torso_pelvis_joint').GetDOFIndex()] = 0
                v[self.autobed.GetJoint('autobed/bed_neck_worldframe_updown_joint').GetDOFIndex()] = (bth / 40) * (
                0.00 - 0) + 0
                v[self.autobed.GetJoint('autobed/bed_neck_base_updown_bedframe_joint').GetDOFIndex()] = (
                                                                                                        bth / 40) * (
                                                                                                        -0.0 - 0) + 0
                v[self.autobed.GetJoint('autobed/head_rest_hinge').GetDOFIndex()] = m.radians(bth)
                v[self.autobed.GetJoint('autobed/headrest_bed_to_worldframe_joint').GetDOFIndex()] = -m.radians(bth)
                v[self.autobed.GetJoint('autobed/bed_neck_to_bedframe_joint').GetDOFIndex()] = m.radians(bth)
                v[self.autobed.GetJoint('autobed/neck_twist_joint').GetDOFIndex()] = -((bth / 40) * (0 - 0) + 0)
                v[self.autobed.GetJoint('autobed/neck_tilt_joint').GetDOFIndex()] = ((bth / 40) * (.7 - 0) + 0)
                v[self.autobed.GetJoint('autobed/neck_head_rotz_joint').GetDOFIndex()] = -((bth / 40) * (0 - 0) + 0)
                v[self.autobed.GetJoint('autobed/neck_head_roty_joint').GetDOFIndex()] = -(
                (bth / 40) * (-0.2 - 0) + 0)
                v[self.autobed.GetJoint('autobed/neck_head_rotx_joint').GetDOFIndex()] = -((bth / 40) * (0 - 0) + 0)
                v[self.autobed.GetJoint('autobed/torso_upper_arm_right_joint').GetDOFIndex()] = -(
                (bth / 40) * (0.0 - 0) + 0)
                v[self.autobed.GetJoint('autobed/torso_upper_arm_left_joint').GetDOFIndex()] = -(
                (bth / 40) * (0.0 - 0) + 0)
                v[self.autobed.GetJoint('autobed/upper_arm_fore_arm_right_joint').GetDOFIndex()] = -(
                (bth / 40) * (1.3 - 0) + 0)
                v[self.autobed.GetJoint('autobed/upper_arm_fore_arm_left_joint').GetDOFIndex()] = -(
                (bth / 40) * (1.3 - 0) + 0)
                v[self.autobed.GetJoint('autobed/fore_arm_hand_right_joint').GetDOFIndex()] = -(
                (bth / 40) * (-0.5 - 0) + 0)
                v[self.autobed.GetJoint('autobed/fore_arm_hand_left_joint').GetDOFIndex()] = -(
                (bth / 40) * (-0.5 - 0) + 0)
            else:
                v[self.autobed.GetJoint('autobed/tele_legs_joint').GetDOFIndex()] = 0
                v[self.autobed.GetJoint('autobed/bed_neck_base_updown_bedframe_joint').GetDOFIndex()] = 0
                v[self.autobed.GetJoint('autobed/bed_neck_base_leftright_joint').GetDOFIndex()] = 0
                v[self.autobed.GetJoint('autobed/bed_neck_worldframe_updown_joint').GetDOFIndex()] = (bth / 40) * (
                0.03 - 0) + 0 + shift
                v[self.autobed.GetJoint('autobed/bed_neck_base_updown_bedframe_joint').GetDOFIndex()] = (
                                                                                                        bth / 40) * (
                                                                                                        -0.13 - 0) + 0
                v[self.autobed.GetJoint('autobed/head_rest_hinge').GetDOFIndex()] = m.radians(bth)
                v[self.autobed.GetJoint('autobed/headrest_bed_to_worldframe_joint').GetDOFIndex()] = -m.radians(bth)
                v[self.autobed.GetJoint('autobed/bed_neck_to_bedframe_joint').GetDOFIndex()] = m.radians(bth)
                v[self.autobed.GetJoint('autobed/neck_twist_joint').GetDOFIndex()] = -((bth / 40) * (0 - 0) + 0)
                v[self.autobed.GetJoint('autobed/neck_tilt_joint').GetDOFIndex()] = ((bth / 40) * (.7 - 0) + 0)
                v[self.autobed.GetJoint('autobed/neck_body_joint').GetDOFIndex()] = (bth / 40) * (.02 - (0)) + (0)
                v[self.autobed.GetJoint('autobed/neck_head_rotz_joint').GetDOFIndex()] = -((bth / 40) * (0 - 0) + 0)
                v[self.autobed.GetJoint('autobed/neck_head_roty_joint').GetDOFIndex()] = -(
                (bth / 40) * (-0.2 - 0) + 0)
                v[self.autobed.GetJoint('autobed/neck_head_rotx_joint').GetDOFIndex()] = -((bth / 40) * (0 - 0) + 0)
                v[self.autobed.GetJoint('autobed/upper_mid_body_joint').GetDOFIndex()] = (bth / 40) * (0.5 - 0) + 0
                v[self.autobed.GetJoint('autobed/mid_lower_body_joint').GetDOFIndex()] = (bth / 40) * (0.26 - 0) + (
                0)
                v[self.autobed.GetJoint('autobed/body_quad_left_joint').GetDOFIndex()] = -0.05
                v[self.autobed.GetJoint('autobed/body_quad_right_joint').GetDOFIndex()] = -0.05
                v[self.autobed.GetJoint('autobed/quad_calf_left_joint').GetDOFIndex()] = .05
                v[self.autobed.GetJoint('autobed/quad_calf_right_joint').GetDOFIndex()] = .05
                v[self.autobed.GetJoint('autobed/calf_foot_left_joint').GetDOFIndex()] = (bth / 40) * (.0 - 0) + 0
                v[self.autobed.GetJoint('autobed/calf_foot_right_joint').GetDOFIndex()] = (bth / 40) * (.0 - 0) + 0
                v[self.autobed.GetJoint('autobed/body_arm_left_joint').GetDOFIndex()] = (bth / 40) * (
                -0.15 - (-0.15)) + (-0.15)
                v[self.autobed.GetJoint('autobed/body_arm_right_joint').GetDOFIndex()] = (bth / 40) * (
                -0.15 - (-0.15)) + (-0.15)
                if False:
                    v[self.autobed.GetJoint('autobed/arm_forearm_left_rotx_joint').GetDOFIndex()] = 0.
                    v[self.autobed.GetJoint('autobed/arm_forearm_left_rotz_joint').GetDOFIndex()] = (bth / 40) * (
                    .86 - 0.1) + 0.1
                    v[self.autobed.GetJoint('autobed/leg_rest_lower_overbed_tray_y_joint').GetDOFIndex()] = 0.
                    v[self.autobed.GetJoint('autobed/leg_rest_lower_overbed_tray_x_joint').GetDOFIndex()] = -0.6858
                v[self.autobed.GetJoint('autobed/arm_forearm_right_joint').GetDOFIndex()] = (bth / 40) * (
                .86 - 0.1) + 0.1
                v[self.autobed.GetJoint('autobed/forearm_hand_left_joint').GetDOFIndex()] = 0
                v[self.autobed.GetJoint('autobed/forearm_hand_right_joint').GetDOFIndex()] = 0


            if init and False:
                self.vision_cone = op.RaveCreateKinBody(self.env, '')
                self.vision_cone.SetName('vision_cone')
                self.vision_cone.InitFromBoxes(np.array([[-1., -1, -1, 0.01, 0.01, 0.01]]),
                                               True)  # set geometry as one box of extents 0.1, 0.2, 0.3
                self.env.AddKinBody(self.vision_cone)

            self.autobed.SetActiveDOFValues(v, 2)
            self.env.UpdatePublishedBodies()
            self.set_autobed(0., 0., 0., 0.)
            headmodel = self.autobed.GetLink('autobed/head_link')
            head_T = np.matrix(headmodel.GetTransform())

            self.originsubject_B_headfloor = np.matrix([[1., 0., 0., head_T[0, 3]],  # .45 #.438
                                                        [0., 1., 0., head_T[1, 3]],  # 0.34 #.42
                                                        [0., 0., 1., 0.],
                                                        [0., 0., 0., 1.]])
            self.originsubject_B_originworld = np.matrix(np.eye(4))
            self.subject = self.env.GetBodies()[1]
            self.subject.SetTransform(np.array(self.originsubject_B_originworld))
            self.a_model_is_loaded = True
        elif self.model is None:
            self.a_model_is_loaded = False
            with self.env:
                self.environment_model = op.RaveCreateKinBody(self.env, '')
                self.environment_model.SetName('environment_model')
                self.environment_model.InitFromBoxes(np.array([[-1.2, -1.2, -1.2, 1.01, 1.01, 1.01]]),
                                                     True)  # set geometry as one box of extents 0.1, 0.2, 0.3
                self.env.AddKinBody(self.environment_model)

            'Using a custom model at in a real-time mode.'
        else:
            self.a_model_is_loaded = False
            print 'I got a bad model. What is going on???'
            return None

        # self.subject_location = originsubject_B_headfloor.I

        print 'OpenRave has succesfully been initialized. \n'

    def set_autobed(self, z, headrest_th, head_x, head_y):
        # print head_x, head_y
        with self.env:
            bz = z
            # print headrest_th
            bth = m.degrees(headrest_th)
            # print bth
            v = self.autobed.GetActiveDOFValues()
            v[self.autobed.GetJoint('autobed/tele_legs_joint').GetDOFIndex()] = bz
            v[self.autobed.GetJoint('autobed/bed_neck_base_updown_bedframe_joint').GetDOFIndex()] = head_x
            shift = 0.
            #        if self.task == 'scratching_knee_left':
            #        shift = 0.02
            v[self.autobed.GetJoint('autobed/bed_neck_base_leftright_joint').GetDOFIndex()] = head_y
            if bth >= 80.:# and bth < 85.:
                bth = 80.
            if bth <= 0.:
                bth = 0.
                # 0 degrees, 0 height
            if (bth >= 0.) and (bth <= 40.):  # between 0 and 40 degrees
                v[self.autobed.GetJoint('autobed/bed_neck_worldframe_updown_joint').GetDOFIndex()] = (bth / 40) * (
                0.03 - 0) + 0 + shift + head_x
                v[self.autobed.GetJoint('autobed/bed_neck_base_updown_bedframe_joint').GetDOFIndex()] = (bth / 40) * (
                -0.13 - 0) + 0
                v[self.autobed.GetJoint('autobed/head_rest_hinge').GetDOFIndex()] = m.radians(bth)
                v[self.autobed.GetJoint('autobed/headrest_bed_to_worldframe_joint').GetDOFIndex()] = -m.radians(bth)
                v[self.autobed.GetJoint('autobed/bed_neck_to_bedframe_joint').GetDOFIndex()] = m.radians(bth)
                # v[self.autobed.GetJoint('autobed/neck_twist_joint').GetDOFIndex()] = -((bth/40)*(0 - 0)+0)
                v[self.autobed.GetJoint('autobed/neck_tilt_joint').GetDOFIndex()] = ((bth / 40) * (.7 - 0) + 0)
                v[self.autobed.GetJoint('autobed/neck_body_joint').GetDOFIndex()] = (bth / 40) * (.02 - (0)) + (0)
                # v[self.autobed.GetJoint('autobed/neck_head_rotz_joint').GetDOFIndex()] = -((bth/40)*(0 - 0)+0)
                v[self.autobed.GetJoint('autobed/neck_head_roty_joint').GetDOFIndex()] = -((bth / 40) * (-0.2 - 0) + 0)
                v[self.autobed.GetJoint('autobed/neck_head_rotx_joint').GetDOFIndex()] = -((bth / 40) * (0 - 0) + 0)
                v[self.autobed.GetJoint('autobed/upper_mid_body_joint').GetDOFIndex()] = (bth / 40) * (0.5 - 0) + 0
                v[self.autobed.GetJoint('autobed/mid_lower_body_joint').GetDOFIndex()] = (bth / 40) * (0.26 - 0) + (0)
                v[self.autobed.GetJoint('autobed/body_quad_left_joint').GetDOFIndex()] = -0.05
                v[self.autobed.GetJoint('autobed/body_quad_right_joint').GetDOFIndex()] = -0.05
                v[self.autobed.GetJoint('autobed/quad_calf_left_joint').GetDOFIndex()] = .05
                v[self.autobed.GetJoint('autobed/quad_calf_right_joint').GetDOFIndex()] = .05
                v[self.autobed.GetJoint('autobed/calf_foot_left_joint').GetDOFIndex()] = (bth / 40) * (.0 - 0) + 0
                v[self.autobed.GetJoint('autobed/calf_foot_right_joint').GetDOFIndex()] = (bth / 40) * (.0 - 0) + 0
                v[self.autobed.GetJoint('autobed/body_arm_left_joint').GetDOFIndex()] = (bth / 40) * (
                -0.15 - (-0.15)) + (-0.15)
                v[self.autobed.GetJoint('autobed/body_arm_right_joint').GetDOFIndex()] = (bth / 40) * (
                -0.15 - (-0.15)) + (-0.15)
                v[self.autobed.GetJoint('autobed/arm_forearm_left_joint').GetDOFIndex()] = (bth / 40) * (
                .86 - 0.1) + 0.1
                v[self.autobed.GetJoint('autobed/arm_forearm_right_joint').GetDOFIndex()] = (bth / 40) * (
                .86 - 0.1) + 0.1
                v[self.autobed.GetJoint('autobed/forearm_hand_left_joint').GetDOFIndex()] = 0
                v[self.autobed.GetJoint('autobed/forearm_hand_right_joint').GetDOFIndex()] = 0
            elif (bth > 40.) and (bth <= 80.):  # between 0 and 40 degrees
                v[self.autobed.GetJoint('autobed/bed_neck_worldframe_updown_joint').GetDOFIndex()] = ((
                                                                                                      bth - 40) / 40) * (
                                                                                                     0.03 - (0.03)) + (
                                                                                                     0.03) + shift + head_x
                v[self.autobed.GetJoint('autobed/bed_neck_base_updown_bedframe_joint').GetDOFIndex()] = (bth / 40) * (
                -0.18 - (-0.13)) + (-0.13)
                v[self.autobed.GetJoint('autobed/head_rest_hinge').GetDOFIndex()] = m.radians(bth)
                v[self.autobed.GetJoint('autobed/headrest_bed_to_worldframe_joint').GetDOFIndex()] = -m.radians(bth)
                v[self.autobed.GetJoint('autobed/bed_neck_to_bedframe_joint').GetDOFIndex()] = m.radians(bth)
                # v[self.autobed.GetJoint('autobed/neck_twist_joint').GetDOFIndex()] = -(((bth-40)/40)*(0 - 0)+0)
                v[self.autobed.GetJoint('autobed/neck_tilt_joint').GetDOFIndex()] = (
                ((bth - 40) / 40) * (0.7 - 0.7) + 0.7)
                v[self.autobed.GetJoint('autobed/neck_body_joint').GetDOFIndex()] = ((bth - 40) / 40) * (
                -0.1 - (.02)) + (.02)
                # v[self.autobed.GetJoint('autobed/neck_head_rotz_joint').GetDOFIndex()] = -((bth/40)*(0 - 0)+0)
                v[self.autobed.GetJoint('autobed/neck_head_roty_joint').GetDOFIndex()] = -(
                (bth / 40) * (.02 - (-0.2)) + (-0.2))
                v[self.autobed.GetJoint('autobed/neck_head_rotx_joint').GetDOFIndex()] = -((bth / 40) * (0 - 0) + 0)
                v[self.autobed.GetJoint('autobed/upper_mid_body_joint').GetDOFIndex()] = ((bth - 40) / 40) * (
                .7 - (.5)) + (.5)
                v[self.autobed.GetJoint('autobed/mid_lower_body_joint').GetDOFIndex()] = ((bth - 40) / 40) * (
                .63 - (.26)) + (.26)
                v[self.autobed.GetJoint('autobed/body_quad_left_joint').GetDOFIndex()] = -0.05
                v[self.autobed.GetJoint('autobed/body_quad_right_joint').GetDOFIndex()] = -0.05
                v[self.autobed.GetJoint('autobed/quad_calf_left_joint').GetDOFIndex()] = 0.05
                v[self.autobed.GetJoint('autobed/quad_calf_right_joint').GetDOFIndex()] = 0.05
                v[self.autobed.GetJoint('autobed/calf_foot_left_joint').GetDOFIndex()] = ((bth - 40) / 40) * (0 - 0) + (
                0)
                v[self.autobed.GetJoint('autobed/calf_foot_right_joint').GetDOFIndex()] = ((bth - 40) / 40) * (
                0 - 0) + (0)
                v[self.autobed.GetJoint('autobed/body_arm_left_joint').GetDOFIndex()] = ((bth - 40) / 40) * (
                -0.1 - (-0.15)) + (-0.15)
                v[self.autobed.GetJoint('autobed/body_arm_right_joint').GetDOFIndex()] = ((bth - 40) / 40) * (
                -0.1 - (-0.15)) + (-0.15)
                v[self.autobed.GetJoint('autobed/arm_forearm_left_joint').GetDOFIndex()] = ((bth - 40) / 40) * (
                1.02 - 0.86) + .86
                v[self.autobed.GetJoint('autobed/arm_forearm_right_joint').GetDOFIndex()] = ((bth - 40) / 40) * (
                1.02 - 0.86) + .86
                v[self.autobed.GetJoint('autobed/forearm_hand_left_joint').GetDOFIndex()] = ((bth - 40) / 40) * (
                .35 - 0) + 0
                v[self.autobed.GetJoint('autobed/forearm_hand_right_joint').GetDOFIndex()] = ((bth - 40) / 40) * (
                .35 - 0) + 0
            else:
                print 'Error: Bed angle out of range (should be 0 - 80 degrees)'

            self.autobed.SetActiveDOFValues(v, 2)
            self.env.UpdatePublishedBodies()

    def create_vision_cone(self):
        # self.vision_cone = op.RaveCreateKinBody(self.env, '')
        with self.env:
            self.env.Remove(self.vision_cone)
            eyes = self.autobed.GetLink('autobed/eyes_link')
            screen_bottom_left = self.autobed.GetLink('autobed/screen_bottom_left_link')
            screen_bottom_right = self.autobed.GetLink('autobed/screen_bottom_right_link')
            screen_top_left = self.autobed.GetLink('autobed/screen_top_left_link')
            screen_top_right = self.autobed.GetLink('autobed/screen_top_right_link')
            origin_B_eyes = np.matrix(eyes.GetTransform())
            eye_pos = np.array(origin_B_eyes)[0:3, 3]
            origin_B_sbl = np.matrix(screen_bottom_left.GetTransform())
            origin_B_sbr = np.matrix(screen_bottom_right.GetTransform())
            origin_B_stl = np.matrix(screen_top_left.GetTransform())
            origin_B_str = np.matrix(screen_top_right.GetTransform())
            screen_edge_points = []
            # screen_edge_points.append(np.array(origin_B_sbl)[0:3, 3])
            for i_p in xrange(5):
                screen_edge_points.append(
                    np.array(origin_B_sbl)[0:3, 3] + i_p / 5. * (np.array(origin_B_sbr - origin_B_sbl)[0:3, 3]))
                screen_edge_points.append(
                    np.array(origin_B_sbr)[0:3, 3] + i_p / 5. * (np.array(origin_B_str - origin_B_sbr)[0:3, 3]))
                screen_edge_points.append(
                    np.array(origin_B_str)[0:3, 3] + i_p / 5. * (np.array(origin_B_stl - origin_B_str)[0:3, 3]))
                screen_edge_points.append(
                    np.array(origin_B_stl)[0:3, 3] + i_p / 5. * (np.array(origin_B_sbl - origin_B_stl)[0:3, 3]))
            # print 'screen_edge_points'
            # print screen_edge_points
            box_list = []
            for screen_p in xrange(len(screen_edge_points)):
                new_box = op.KinBody.Link.GeometryInfo()
                new_box._type = op.KinBody.Link.GeomType.Box
                box_path = screen_edge_points[screen_p] - eye_pos
                # print 'box_path'
                # print box_path
                x_vector = box_path / np.linalg.norm(box_path)
                # print 'x_vector'
                # print x_vector
                z_origin = np.array([0., 0., 1.])
                y_orth = np.cross(z_origin, x_vector)
                y_orth = y_orth / np.linalg.norm(y_orth)
                z_vector = np.cross(x_vector, y_orth)
                # print 'new_box._t'
                # print new_box._t
                new_box._t[0:3, 0] = copy.copy(x_vector)
                new_box._t[0:3, 1] = copy.copy(y_orth)
                new_box._t[0:3, 2] = copy.copy(z_vector)
                new_box._t[0:3, 3] = copy.copy(eye_pos + (box_path / 2.))
                # new_box._t[2, 3] += 0.005
                # print 'new_box._t'
                # print new_box._t
                new_box._vGeomData = [(np.linalg.norm(box_path)) / 2. - 0.03, 0.025, 0.001]
                # new_box._bVisible = True
                # new_box._fTransparency = 0.5
                box_list.append(copy.copy(new_box))

            self.vision_cone.InitFromGeometries(box_list)
            # k3.SetName('tempcylinder')
            # env.Add(k3,True)
            # self.vison_cone.InitFromBoxes(environment_voxels, True)  # set geometry as many boxes
            self.env.AddKinBody(self.vision_cone)
            self.env.UpdatePublishedBodies()
            return True

    def show_rviz(self):
        #rospy.init_node(''.join(['base_selection_goal_visualization']))
        sub_pos, sub_ori = Bmat_to_pos_quat(self.originsubject_B_originworld)
        self.publish_sub_marker(sub_pos, sub_ori)

#         if self.model == 'autobed':
#             self.selection_mat = np.zeros(len(self.goals))
#             self.goal_list = np.zeros([len(self.goals),4,4])
#             headmodel = self.autobed.GetLink('head_link')
#             pr2_B_head = np.matrix(headmodel.GetTransform())
#             for i in xrange(len(self.goals)):
#                 self.goal_list[i] = copy.copy(pr2_B_head*np.matrix(self.goals[i,0]))
#                 self.selection_mat[i] = copy.copy(self.goals[i,1])
# #            for target in self.goals:
# #                self.goal_list.append(pr2_B_head*np.matrix(target[0]))
# #                self.selection_mat.append(target[1])
#             self.set_goals()

        self.publish_goal_markers(self.goal_list)
        #for i in xrange(len(self.goal_list)):
        #    g_pos,g_ori = Bmat_to_pos_quat(self.goal_list[i])
        #    self.publish_goal_marker(g_pos, g_ori, ''.join(['goal_',str(i)]))

    # Publishes as a marker array the goal marker locations used by openrave to rviz so we can see how it overlaps with the subject
    def publish_goal_markers(self, goals):
        vis_pub = rospy.Publisher('~goal_markers', MarkerArray, queue_size=1, latch=True)
        goal_markers = MarkerArray()
        for num, goal_marker in enumerate(goals):
            pos, ori = Bmat_to_pos_quat(goal_marker)
            marker = Marker()
            #marker.header.frame_id = "/base_footprint"
            marker.header.frame_id = "/base_link"
            marker.header.stamp = rospy.Time()
            marker.ns = str(num)
            marker.id = 0
            marker.type = Marker.ARROW
            marker.action = Marker.ADD
            marker.pose.position.x = pos[0]
            marker.pose.position.y = pos[1]
            marker.pose.position.z = pos[2]
            marker.pose.orientation.x = ori[0]
            marker.pose.orientation.y = ori[1]
            marker.pose.orientation.z = ori[2]
            marker.pose.orientation.w = ori[3]
            marker.scale.x = .05*3
            marker.scale.y = .05*3
            marker.scale.z = .01*3
            marker.color.a = 1.
            marker.color.r = 1.0
            marker.color.g = 0.0
            marker.color.b = 0.0
            goal_markers.markers.append(marker)
        vis_pub.publish(goal_markers)
        print 'Published a goal marker to rviz'

    # Publishes a goal marker location used by openrave to rviz so we can see how it overlaps with the subject
    def publish_goal_marker(self, pos, ori, name):
        vis_pub = rospy.Publisher(''.join(['~', name]), Marker, queue_size=1, latch=True)
        marker = Marker()
        #marker.header.frame_id = "/base_footprint"
        marker.header.frame_id = "/base_link"
        marker.header.stamp = rospy.Time()
        marker.ns = name
        marker.id = 0
        marker.type = Marker.ARROW
        marker.action = Marker.ADD
        marker.pose.position.x = pos[0]
        marker.pose.position.y = pos[1]
        marker.pose.position.z = pos[2]
        marker.pose.orientation.x = ori[0]
        marker.pose.orientation.y = ori[1]
        marker.pose.orientation.z = ori[2]
        marker.pose.orientation.w = ori[3]
        marker.scale.x = .2
        marker.scale.y = .2
        marker.scale.z = .2
        marker.color.a = 1.
        marker.color.r = 1.0
        marker.color.g = 0.0
        marker.color.b = 0.0
        vis_pub.publish(marker)
        print 'Published a goal marker to rviz'

    # Publishes the wheelchair model location used by openrave to rviz so we can see how it overlaps with the real wheelchair
    def publish_sub_marker(self, pos, ori):
        marker = Marker()
        #marker.header.frame_id = "/base_footprint"
        marker.header.frame_id = "/base_link"
        marker.header.stamp = rospy.Time()
        marker.id = 0
        marker.type = Marker.MESH_RESOURCE
        marker.action = Marker.ADD
        marker.pose.position.x = pos[0]
        marker.pose.position.y = pos[1]
        marker.pose.position.z = pos[2]
        marker.pose.orientation.x = ori[0]
        marker.pose.orientation.y = ori[1]
        marker.pose.orientation.z = ori[2]
        marker.pose.orientation.w = ori[3]
        marker.color.a = 1.
        marker.color.r = 0.0
        marker.color.g = 1.0
        marker.color.b = 0.0
        if self.model == 'chair':
            name = 'subject_model'
            marker.mesh_resource = "package://hrl_base_selection/models/wheelchair_and_body_assembly_rviz.STL"
            marker.scale.x = 1.0
            marker.scale.y = 1.0
            marker.scale.z = 1.0
        elif self.model == 'bed':
            name = 'subject_model'
            marker.mesh_resource = "package://hrl_base_selection/models/head_bed.dae"
            marker.scale.x = 1.0
            marker.scale.y = 1.0
            marker.scale.z = 1.0
        elif self.model == 'autobed':
            name = 'subject_model'
            marker.mesh_resource = "package://hrl_base_selection/models/bed_and_body_v3_rviz.dae"
            marker.scale.x = 1.0
            marker.scale.y = 1.0
            marker.scale.z = 1.0
        elif self.model is None:
            print 'Not publishing a marker, no specific model is being used'
        else:
            print 'I got a bad model. What is going on???'
            return None
        vis_pub = rospy.Publisher(''.join(['~',name]), Marker, queue_size=1, latch=True)
        marker.ns = ''.join(['base_service_',name])
        vis_pub.publish(marker)
        print 'Published a model of the subject to rviz'

    # Plot the score as a scatterplot heat map
    def plot_scores(self,scores):
        #print 'score_sheet:',scores
        rospack = rospkg.RosPack()
        pkg_path = rospack.get_path('hrl_base_selection')
        data=scores
        '''
        score2d_temp = []
        for i in np.arange(-1.5,1.55,.05):
            for j in np.arange(-1.5,1.55,.05):
                temp = []
                for item in data:
                    newline = []
                #print 'i is:',i
                #print 'j is:',j
                    if item[0]==i and item[1]==j:
                        newline.append([i,j,item[3]])
                        newline.append(item[int(4)])
                        newline.append(item[int(5)])
                        #print 'newest line ',list(flatten(newline))
                        temp.append(list(flatten(newline)))
                if temp != []:
                    temp=np.array(temp)
                    temp_max = []
                    temp_max.append(np.max(temp[:,2]))
                    temp_max.append(np.max(temp[:,3]))
                    temp_max.append(np.max(temp[:,4]))
                    #print 'temp_max is ',temp_max
                    score2d_temp.append(list(flatten([i,j,temp_max])))
        #print '2d score:',np.array(score2d_temp)[0]
        seen_items = []
        score2d = []
        for item in score2d_temp:
            if not (any((item == x) for x in seen_items)):
                score2d.append(item)
                seen_items.append(item)
        score2d = np.array(score2d)
        #print 'score2d with no repetitions',score2d
        '''
        if self.model == 'chair':
            verts_subject = [(-.438, -.32885),  # left, bottom
                             (-.438, .32885),  # left, top
                             (.6397, .32885),  # right, top
                             (.6397, -.32885),  # right, bottom
                             (0., 0.),  # ignored
                             ]
        elif self.model == 'bed':
            verts_subject = [(-.2954, -.475),  # left, bottom
                             (-.2954, .475),  # left, top
                             (1.805, .475),  # right, top
                             (1.805, -.475),  # right, bottom
                             (0., 0.),  # ignored
                             ]
        elif self.model == 'autobed':
            verts_subject = [(-.2954, -.475),  # left, bottom
                             (-.2954, .475),  # left, top
                             (1.805, .475),  # right, top
                             (1.805, -.475),  # right, bottom
                             (0., 0.),  # ignored
                             ]

        verts_pr2 = [(-1.5,  -1.5),  # left, bottom
                     (-1.5, -.835),  # left, top
                     (-.835, -.835),  # right, top
                     (-.835,  -1.5),  # right, bottom
                     (0.,    0.),  # ignored
                     ]

        codes = [Path.MOVETO,
                 Path.LINETO,
                 Path.LINETO,
                 Path.LINETO,
                 Path.CLOSEPOLY,
                 ]

        path_subject = Path(verts_subject, codes)
        path_pr2 = Path(verts_pr2, codes)

        patch_subject = patches.PathPatch(path_subject, facecolor='orange', lw=2)
        patch_pr2 = patches.PathPatch(path_pr2, facecolor='orange', lw=2)

        X = data[:, 0]
        Y = data[:, 1]
        c3 = data[:, 4]

        fig3 = plt.figure(1)
        ax3 = fig3.add_subplot(111)
        surf3 = ax3.scatter(X, Y, s=60, c=c3, alpha=1)
        ax3.set_xlabel('X Axis')
        ax3.set_ylabel('Y Axis')
        fig3.colorbar(surf3, shrink=0.65, aspect=5)
        ax3.add_patch(patch_subject)
        ax3.add_patch(patch_pr2)
        ax3.set_xlim(-2, 2)
        ax3.set_ylim(-2, 2)
        fig3.set_size_inches(14, 11, forward=True)
        ax3.set_title(''.join(['Plot of personal space score on ', self.model, ' Time stamp: ', str(int(time.time()))]))
        plt.savefig(''.join([pkg_path, '/images/space_score_on_', self.model, '_ts_', str(int(time.time())), '.png']),
                    bbox_inches='tight')


        c = copy.copy(data[:,5])
        c2 = copy.copy(data[:,6])

        fig = plt.figure(2)
        ax = fig.add_subplot(111)
        surf = ax.scatter(X, Y, s=60, c=c, alpha=1)
        ax.set_xlabel('X Axis')
        ax.set_ylabel('Y Axis')
        fig.colorbar(surf, shrink=0.65, aspect=5)
        ax.add_patch(patch_subject)
        ax.add_patch(patch_pr2)
        ax.set_xlim(-2,2)
        ax.set_ylim(-2,2)
        fig.set_size_inches(14,11,forward=True)
        ax.set_title(''.join(['Plot of reach score on ',self.model,' Time stamp: ',str(int(time.time()))]))
        plt.savefig(''.join([pkg_path, '/images/reach_score_on_',self.model,'_ts_',str(int(time.time())),'.png']), bbox_inches='tight')

        fig2 = plt.figure(3)
        ax2 = fig2.add_subplot(111)
        surf2 = ax2.scatter(X, Y, s=60, c=c2, alpha=1)
        ax2.set_xlabel('X Axis')
        ax2.set_ylabel('Y Axis')
        fig2.colorbar(surf2, shrink=0.65, aspect=5)
        ax2.add_patch(patch_subject)
        ax2.add_patch(patch_pr2)
        ax2.set_xlim(-2, 2)
        ax2.set_ylim(-2, 2)
        fig2.set_size_inches(14, 11, forward=True)
        ax2.set_title(''.join(['Plot of manipulability score on ',self.model,' Time stamp: ',str(int(time.time()))]))
        plt.savefig(''.join([pkg_path, '/images/manip_score_on_',self.model,'_ts_',str(int(time.time())),'.png']), bbox_inches='tight')

        plt.ion()
        plt.show()
        ut.get_keystroke('Hit a key to proceed next')

    def gen_joint_limit_weight(self, q):
        # define the total range limit for each joint
        l_min = np.array([-40., -30., -44., -133., -400., -130., -400.])
        # l_min = np.array([-40., -30., -44., -45., -400., -130., -400.])
        l_max = np.array([130., 80., 224., 0., 400., 0., 400.])
        l_range = l_max - l_min
        # l1_max = 40.
        # l2_min = -30.
        # l2_max = 80.
        # l3_min = -44.
        # l3_max = 224.
        # l4_min = 0.
        # l4_max = 133.
        # l5_min = -1000.  # continuous
        # l5_max = 1000.  # continuous
        # l6_min = 0.
        # l6_max = 130.
        # l7_min = -1000.  # continuous
        # l7_max = 1000  # continuous
        # l2 = 120.
        # l3 = 268.
        # l4 = 133.
        # l5 = 10000.  # continuous
        # l6 = 130.
        # l7 = 10000.  # continuous

        weights = np.zeros(7)
        for joint in xrange(len(weights)):
            weights[joint] = (1. - m.pow(0.5, ((l_range[joint])/2. - np.abs((l_range[joint])/2. - m.degrees(q[joint]) + l_min[joint]))/(l_range[joint]/40.)+1.))
            # weights[joint] = 1. - m.pow(0.5, (l_max[joint]-l_min[joint])/2. - np.abs((l_max[joint] - l_min[joint])/2. - m.degrees(q[joint]) + l_min[joint]))
            if weights[joint] < 0.001:
                weights[joint] = 0.001
#        print 'q', q
#        print 'weights', weights
        weights[4] = 1.
        weights[6] = 1.
        return np.matrix(np.diag(weights))

if __name__ == "__main__":
    rospy.init_node('score_generator')
    mytask = 'shoulder'
    mymodel = 'chair'
    #mytask = 'all_goals'
    start_time = time.time()
    selector = ScoreGenerator(visualize=False,task=mytask,goals = None,model=mymodel)
    #selector.choose_task(mytask)
    score_sheet = selector.handle_score_generation()

    print 'Time to load find generate all scores: %fs'%(time.time()-start_time)

    rospack = rospkg.RosPack()
    pkg_path = rospack.get_path('hrl_base_selection')
    save_pickle(score_sheet, ''.join([pkg_path, '/data/', mymodel, '_', mytask, '.pkl']))
    print 'Time to complete program, saving all data: %fs' % (time.time()-start_time)

    # Plot the score as a scatterplot heat map
    #print 'score_sheet:',score_sheet
    score2d_temp = []
    #print t
    for i in np.arange(-1.5, 1.55, .05):
        for j in np.arange(-1.5, 1.55, .05):
            temp = []
            for item in score_sheet:
            #print 'i is:',i
            #print 'j is:',j
                if item[0] == i and item[1] == j:
                    temp.append(item[3])
            if temp != []:
                score2d_temp.append([i, j, np.max(temp)])

    #print '2d score:',np.array(score2d_temp)

    seen_items = []
    score2d = []
    for item in score2d_temp:
#any((a == x).all() for x in my_list)
        #print 'seen_items is: ',seen_items
        #print 'item is: ',item
        #print (any((item == x) for x in seen_items))
        if not (any((item == x) for x in seen_items)):
        #if item not in seen_items:
            #print 'Just added the item to score2d'
            score2d.append(item)
            seen_items.append(item)
    score2d = np.array(score2d)
    #print 'score2d with no repetitions',score2d

    fig, ax = plt.subplots()

    X = score2d[:, 0]
    Y = score2d[:, 1]
    #Th = score_sheet[:,2]
    c = score2d[:, 2]
    #surf = ax.scatter(delta1[:-1], delta1[1:], c=close, s=volume, alpha=0.5)
    surf = ax.scatter(X, Y, s=60, c=c, alpha=1)
    #surf = ax.scatter(X, Y,s=40, c=c,alpha=.6)
    ax.set_xlabel('X Axis')
    ax.set_ylabel('Y Axis')
    #ax.set_zlabel('Theta Axis')

    fig.colorbar(surf, shrink=0.5, aspect=5)

    if mymodel == 'chair':
        verts_subject = [(-.438, -.32885),  # left, bottom
                         (-.438, .32885),  # left, top
                         (.6397, .32885),  # right, top
                         (.6397, -.32885),  # right, bottom
                         (0., 0.), # ignored
                         ]
    elif mymodel == 'bed':
        verts_subject = [(-.2954, -.475),  # left, bottom
                         (-.2954, .475),  # left, top
                         (1.805, .475),  # right, top
                         (1.805, -.475),  # right, bottom
                         (0., 0.),  # ignored
                         ]
    elif mymodel == 'autobed':
        verts_subject = [(-.2954, -.475),  # left, bottom
                         (-.2954, .475),  # left, top
                         (1.805, .475),  # right, top
                         (1.805, -.475),  # right, bottom
                         (0., 0.),  # ignored
                         ]

    verts_pr2 = [(-1.5,  -1.5),  # left, bottom
                 (-1.5, -.835),  # left, top
                 (-.835, -.835),  # right, top
                 (-.835,  -1.5),  # right, bottom
                 (0.,    0.),  # ignored
                ]

    codes = [Path.MOVETO,
             Path.LINETO,
             Path.LINETO,
             Path.LINETO,
             Path.CLOSEPOLY,
            ]

    path_subject = Path(verts_subject, codes)
    path_pr2 = Path(verts_pr2, codes)

    patch_subject = patches.PathPatch(path_subject, facecolor='orange', lw=2)
    patch_pr2 = patches.PathPatch(path_pr2, facecolor='orange', lw=2)

    ax.add_patch(patch_subject)
    ax.add_patch(patch_pr2)
    ax.set_xlim(-2, 2)
    ax.set_ylim(-2, 2)


    plt.show()





    '''
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    X  = score_sheet[:,0]
    Y  = score_sheet[:,1]
    Th = score_sheet[:,2]
    c  = score_sheet[:,3]
    surf = ax.scatter(X, Y, Th,s=40, c=c,alpha=.6)
    #surf = ax.scatter(X, Y,s=40, c=c,alpha=.6)
    ax.set_xlabel('X Axis')
    ax.set_ylabel('Y Axis')
    ax.set_zlabel('Theta Axis')
    fig.colorbar(surf, shrink=0.5, aspect=5)
    plt.show()
'''




