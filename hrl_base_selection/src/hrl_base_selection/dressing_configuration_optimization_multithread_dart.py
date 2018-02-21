#!/usr/bin/env python

import numpy as np
import math as m
import copy

import pydart2 as pydart

import roslib

import rospy, rospkg
import tf
from geometry_msgs.msg import PoseStamped, Pose, PoseArray
from mpl_toolkits.mplot3d import Axes3D
from matplotlib import cm
from matplotlib.ticker import LinearLocator, FormatStrFormatter
import matplotlib.pyplot as plt
from matplotlib.path import Path
import matplotlib.patches as patches
from matplotlib.cbook import flatten

from sensor_msgs.msg import JointState
from std_msgs.msg import String

roslib.load_manifest('hrl_base_selection')
from hrl_base_selection.helper_functions import createBMatrix, Bmat_to_pos_quat, calc_axis_angle
from hrl_base_selection.dart_setup import DartDressingWorld
from hrl_base_selection.graph_search_functions import SimpleGraph, a_star_search, reconstruct_path
from hrl_base_selection.msg import PhysxOutcome
from hrl_base_selection.srv import InitPhysxBodyModel, PhysxInput, IKService, PhysxOutput, PhysxInputWaypoints

from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from hrl_msgs.msg import FloatArrayBare

import random, threading

import openravepy as op
from openravepy.misc import InitOpenRAVELogging

from sklearn.neighbors import NearestNeighbors

import tf.transformations as tft

import pickle as pkl
roslib.load_manifest('hrl_lib')
from hrl_lib.util import save_pickle, load_pickle

import gc

import cma
import multiprocessing as mp


general_option = {'maxiter': 50, 'popsize': 20}

DURATION = 5
OPTIONS = general_option
SIMULATOR_PROCESS = DressingSimulationProcess
CMA_STEP_SIZE = 0.6
NUM_RESTART = 1


class SimulatorPool(object):
    def __init__(self, population, visualize=False):
        self.simulatorPool = mp.Manager().Queue()
        for _ in xrange(population):
            simulator_process = SIMULATOR_PROCESS(process_number=_, visualize=visualize)
            self.simulatorPool.put(simulator_process)


def _init(queue):
    global current_simulator
    current_simulator = queue.get()


def setBoundary(length, joint_max_l, joint_max_u, joint_min_l, joint_min_u, phi_l, phi_h):
    lower_bounds = [0 for _ in range(length)]
    upper_bounds = [0 for _ in range(length)]
    for i in range(length / 3):
        lower_bounds[i] = joint_max_l
        lower_bounds[i + length / 3] = joint_min_l
        lower_bounds[i + length * 2 / 3] = phi_l

        upper_bounds[i] = joint_max_u
        upper_bounds[i + length / 3] = joint_min_u
        upper_bounds[i + length * 2 / 3] = phi_h

    return lower_bounds, upper_bounds

def setup_dart_thread(self):
    # Setup Dart ENV for each thread
    global current_simulator
    # Set up multithreading which is used in the inner loop
    processCnt = mp.cpu_count()
    simulatorPool = SimulatorPool(processCnt).simulatorPool
    pool = mp.Pool(processCnt, _init, (simulatorPool,))

class DressingMultithreadedOptimization(object):
    def __init__(self, number_of_processes=1, visualize=False):

class DressingSimulationProcess(object):
    def __init__(self, process_number=0, robot_arm='rightarm', human_arm='rightarm', visualize=False):
        rospack = rospkg.RosPack()
        self.pkg_path = rospack.get_path('hrl_base_selection')
        self.save_file_path = self.pkg_path + '/data/'
        self.save_file_name_coarse_raw = 'arm_config_coarse_raw.log'
        self.save_file_name_coarse_feasible = 'arm_configs_coarse_feasible.log'
        self.save_file_name_fine_raw = 'arm_configs_fine_raw.log'
        self.save_file_name_fine = 'arm_configs_fine.log'
        self.save_file_name_super_fine = 'arm_configs_super_fine.log'
        # self.save_file_name_per_human_initialization = 'arm_configs_per_human_initialization.log'
        self.visualize = visualize

        self.robot_arm = None
        self.robot_opposite_arm = None

        self.human_arm = None
        self.human_opposite_arm = None

        self.optimization_results = dict()

        self.start_traj = []
        self.end_traj = []

        self.axis = []
        self.angle = None

        self.stretch_allowable = []

        self.human_rot_correction = None

        self.fixed_points = []
        self.add_new_fixed_point = False
        self.fixed_points_to_use = []

        # self.model = None
        self.force_cost = 0.

        self.goals = None
        self.pr2_B_reference = None
        self.task = None
        self.task_dict = None

        self.reference_names = None

        self.distance = 0.
        # self.score_length = {}
        # self.sorted_scores = {}

        self.gripper_B_tool = np.matrix([[0., -1., 0., 0.03],
                                         [1., 0., 0., 0.0],
                                         [0., 0., 1., -0.05],
                                         [0., 0., 0., 1.]])

        # Gripper coordinate system has z in direction of the gripper, x is the axis of the gripper opening and closing.
        # This transform corrects that to make x in the direction of the gripper, z the axis of the gripper open.
        # Centered at the very tip of the gripper.
        self.goal_B_gripper = np.matrix([[0.,  0.,   1.,   0.0],
                                         [0.,  1.,   0.,   0.0],
                                         [-1.,  0.,   0.,  0.0],
                                         [0.,  0.,   0.,   1.0]])
        self.origin_B_grasps = []
        self.goals = []

        self.optimal_z_offset = 0.05

        self.setup_openrave()

        self.set_robot_arm(robot_arm)
        self.set_human_arm(human_arm)

        self.setup_dart(filename='fullbody_50percentile_capsule.skel')

        self.arm_configs_eval = load_pickle(rospack.get_path('hrl_dressing') +
                                            '/data/forearm_trajectory_evaluation/entire_results_list.pkl')
        self.arm_configs_checked = []
        for line in self.arm_configs_eval:
            self.arm_configs_checked.append(line[0:4])
        self.arm_knn = NearestNeighbors(8, m.radians(15.))
        self.arm_knn.fit(self.arm_configs_checked)

    def optimize_entire_dressing_task(self, reset_file=False):
        if reset_file:
            open(self.save_file_path + self.save_file_name, 'w').close()
            open(self.save_file_path + self.save_file_name_only_good, 'w').close()
            open(self.save_file_path + self.save_file_name_per_human_initialization, 'w').close()

        self.set_robot_arm('rightarm')
        subtask_list = ['rightarm', 'leftarm']

        self.fixed_points = []

        self.final_results = []
        self.final_results.append(['subtask', 'overall_score', 'arm_config', 'physx_score', 'pr2_config', 'kinematics_score'])
        for subtask_number, subtask in enumerate(subtask_list):
            self.final_results.append([subtask, '', '', '', '', ''])
            if 'right' in subtask or 'left' in subtask:
                self.set_human_arm(subtask)
            # self.best_pr2_results[subtask_number] = [[], []]
            if subtask_number == 0:
                self.fixed_points_to_use = []
                self.stretch_allowable = []
                self.add_new_fixed_point = True
                self.run_interleaving_optimization_outer_level(subtask=subtask, subtask_step=subtask_number,
                                                               maxiter=2, popsize=2, mode='fine')
            else:
                if subtask_number == 1:
                    self.fixed_points_to_use = [0]
                    self.stretch_allowable = [0.5]
                    self.add_new_fixed_point = True
                # self.run_interleaving_optimization_outer_level(subtask=subtask, subtask_step=subtask_number,
                #                                                maxiter=500, popsize=40, mode='coarse')
                self.run_interleaving_optimization_outer_level(subtask=subtask, subtask_step=subtask_number,
                                                               maxiter=50, popsize=20, mode='fine')
                                                               # maxiter=500, popsize=50)

    def run_interleaving_optimization_outer_level(self, maxiter=1000, popsize=40,
                                                  subtask='', subtask_step=0, mode='fine'):
        self.mode = mode
        self.subtask_step = subtask_step
        # self.best_overall_score = dict()
        self.best_overall_score = 10000.
        # self.best_physx_config = dict()
        self.best_physx_config = None
        self.best_physx_score = 10000.
        # self.best_kinematics_config = dict()
        self.best_kinematics_config = None
        self.best_kinematics_score = 10000.

        # maxiter = 30/
        # popsize = m.pow(5, 2)*100
        # maxiter = 8
        # popsize = 40

        ### Current: Two positions, first with respect to the fist, second with respect to the upper arm, centered at
        # the shoulder and pointing X down the upper arm
        # cma parameters: [human_upper_arm_quaternion(euler:xzy): r, y, p
        #                  human_arm_elbow_angle]

        parameters_min = np.array([m.radians(-5.), m.radians(-10.), m.radians(-10.),
                                   0.])
        parameters_max = np.array([m.radians(100.), m.radians(100.), m.radians(100),
                                   m.radians(135.)])
        parameters_scaling = (parameters_max - parameters_min) / 8.
        parameters_scaling = np.array([m.radians(5.)]*4)
        # parameters_initialization = (parameters_max + parameters_min) / 2.
        init_start_arm_configs = [[m.radians(0.), m.radians(0.), m.radians(0.), m.radians(0.)],
                                  [m.radians(45.), m.radians(0.), m.radians(0.), m.radians(0.)],
                                  [m.radians(0.), m.radians(45.), m.radians(0.), m.radians(0.)],
                                  [m.radians(0.), m.radians(0.), m.radians(45.), m.radians(0.)],
                                  [m.radians(0.), m.radians(0.), m.radians(0.), m.radians(45.)],
                                  [m.radians(25.), m.radians(10.), m.radians(10.), m.radians(45.)],
                                  [0.9679925, 0.18266905, 0.87995157, 0.77562143],
                                  (parameters_max + parameters_min) / 2.]
        # init_start_arm_configs = [(parameters_max + parameters_min) / 2.]
        opts1 = {'seed': 1234, 'ftarget': -1., 'popsize': popsize, 'maxiter': maxiter,
                 'maxfevals': 1e8, 'CMA_cmean': 0.25, 'tolfun': 1e-3,
                 'tolfunhist': 1e-12, 'tolx': 5e-4,
                 'maxstd': 4.0, 'tolstagnation': 100,
                 'verb_filenameprefix': 'outcma_arm_and_trajectory',
                 'scaling_of_variables': list(parameters_scaling),
                 'bounds': [list(parameters_min), list(parameters_max)]}
        regular = False
        if mode == 'fine':
            self.save_all_results = False
            if subtask_step == 1:
                feasible_configs = [line.rstrip('\n').split(',')
                                    for line in open(self.save_file_path + self.save_file_name_only_good)]

                for j in xrange(len(feasible_configs)):
                    feasible_configs[j] = [float(i) for i in feasible_configs[j]]
                feasible_configs = np.array(feasible_configs)
                feasible_configs = np.array([x for x in feasible_configs if int(x[0]) == subtask_step])

                cluster_count = 0
                clusters = [[]]
                while len(feasible_configs) > 0 and not rospy.is_shutdown():
                    if len(clusters) < cluster_count + 1:
                        clusters.append([])
                    queue = []
                    visited = []
                    queue.append(list(feasible_configs[0][1:5]))
                    delete_list = []
                    while len(queue) > 0 and not rospy.is_shutdown():
                        # print 'queue:\n',queue
                        # print 'visited:\n',visited
                        current_node = list(queue.pop(0))
                        # print 'current node:\n',current_node
                        # print 'visited:\n',visited
                        if current_node not in visited:
                            visited.append(list(current_node))
                            clusters[cluster_count].append(current_node)
                            delete_list.append(0)
                        for node_i in xrange(len(feasible_configs)):
                            if np.max(np.abs(np.array(current_node) - np.array(feasible_configs[node_i])[1:5])) < m.radians(
                                    5.1) and list(feasible_configs[node_i][1:5]) not in visited:
                                close_node = list(feasible_configs[node_i][1:5])
                                queue.append(list(close_node))
                                delete_list.append(node_i)
                                # clusters[cluster_count.append(close_node)]
                    feasible_configs = np.delete(feasible_configs, delete_list, axis=0)
                    cluster_count += 1
                clusters = np.array(clusters)
                print 'Number of clusters:', len(clusters)
                init_start_arm_configs = []
                for cluster in clusters:
                    init_start_arm_configs.append(np.array(cluster).mean(axis=0))
            elif subtask_step==0 or False:
                init_start_arm_configs = [(parameters_max + parameters_min) / 2.]
            for init_start_arm_config in init_start_arm_configs:
                parameters_initialization = init_start_arm_config
                # parameters_initialization[0] = m.radians(0.)
                # parameters_initialization[1] = m.radians(70.)
                # parameters_initialization[2] = m.radians(0.)
                # parameters_initialization[3] = m.radians(0.)

                # optimization_results[<model>, <number_of_configs>, <head_rest_angle>, <headx>, <heady>, <allow_bed_movement>]
                self.optimization_results = cma.fmin(self.objective_function_traj_and_arm_config,
                                                              list(parameters_initialization),
                                                              1.,
                                                              options=opts1)
                print 'raw cma optimization results:\n',self.optimization_results
                # self.optimization_results = [self.best_config, self.best_score]
                # print '1',self.save_file_path
                # print '2',self.save_file_name_per_human_initialization
                # print '3',self.best_physx_config
                # print '4',self.best_overall_score
                # print '5',self.best_kinematics_config
                # print '6',self.best_kinematics_score
                with open(self.save_file_path + self.save_file_name_per_human_initialization, 'a') as myfile:
                    myfile.write(str(self.subtask_step)
                                 + ',' + str("{:.5f}".format(self.best_physx_config[0]))
                                 + ',' + str("{:.5f}".format(self.best_physx_config[1]))
                                 + ',' + str("{:.5f}".format(self.best_physx_config[2]))
                                 + ',' + str("{:.5f}".format(self.best_physx_config[3]))
                                 + ',' + str("{:.5f}".format(self.best_overall_score))
                                 + ',' + str("{:.5f}".format(self.best_kinematics_config[0]))
                                 + ',' + str("{:.5f}".format(self.best_kinematics_config[1]))
                                 + ',' + str("{:.5f}".format(self.best_kinematics_config[2]))
                                 + ',' + str("{:.5f}".format(self.best_kinematics_config[3]))
                                 + ',' + str("{:.5f}".format(self.best_kinematics_score))
                                 + '\n')
        else:
            self.save_all_results = True
            [t for t in ((self.objective_function_traj_and_arm_config([arm1, arm2, arm3, arm4]))
                         for arm1 in np.arange(parameters_min[0], parameters_max[0]+0.0001, m.radians(5.))
                         for arm2 in np.arange(parameters_min[1], parameters_max[1]+0.0001, m.radians(5.))
                         for arm3 in np.arange(parameters_min[2], parameters_max[2]+0.0001, m.radians(5.))
                         for arm4 in np.arange(parameters_min[3], parameters_max[3]+0.0001, m.radians(5.))
                         )
             ]
        # print 'Outcome is: '
        # print self.optimization_results
        # print 'Best arm config for ',subtask, 'subtask: \n', self.optimization_results[self.subtask_step][0]
        # print 'Associated score: ', self.optimization_results[self.subtask_step][1]
        # print 'Best PR2 configuration: \n', self.best_pr2_results[self.subtask_step][0]
        # print 'Associated score: ', self.best_pr2_results[self.subtask_step][1]
        print 'Best overall score for ', subtask, 'subtask: \n', self.best_overall_score
        print 'Best arm config for ', subtask, 'subtask: \n', self.best_physx_config
        print 'Associated score: ', self.best_physx_score
        print 'Best PR2 configuration: \n', self.best_kinematics_config
        print 'Associated score: ', self.best_kinematics_score
        self.final_results[subtask_step+1] = [subtask, self.best_overall_score,
                                              self.best_physx_config,
                                              self.best_physx_score,
                                              self.best_kinematics_config,
                                              self.best_kinematics_score]
        # optimized_traj_arm_output = []
        # for key in self.optimization_results.keys():
        #     optimized_traj_arm_output.append([self.optimization_results[key][0], self.optimization_results[key][1]])
        # optimized_pr2_output = []
        # for key in self.best_pr2_results.keys():
        #     optimized_pr2_output.append([self.best_pr2_results[key][0], self.best_pr2_results[key][1]])

        # save_pickle(self.final_results, self.pkg_path+'/data/best_trajectory_and_arm_config.pkl')
        save_pickle(self.final_results, self.pkg_path+'/data/dressing_results.pkl')

    def find_reference_coordinate_frames_and_goals(self, arm):
        skeleton_frame_B_worldframe = np.matrix([[1., 0., 0., 0.],
                                                 [0., 0., 1., 0.],
                                                 [0., -1., 0., 0.],
                                                 [0., 0., 0., 1.]])

        origin_B_pelvis = np.matrix(self.human.bodynode('h_pelvis').world_transform())
        origin_B_upperarmbase = np.matrix(self.human.bodynode('h_bicep_' + arm).world_transform())
        origin_B_upperarmbase[0:3, 0:3] = origin_B_pelvis[0:3, 0:3]
        origin_B_upperarm = np.matrix(self.human.bodynode('h_bicep_' + arm).world_transform())
        origin_B_forearm = np.matrix(self.human.bodynode('h_forearm_' + arm).world_transform())
        origin_B_wrist = np.matrix(self.human.bodynode('h_hand_' + arm).world_transform())
        origin_B_hand = np.matrix(self.human.bodynode('h_hand_' + arm+'2').world_transform())
        #print 'origin_B_upperarm\n', origin_B_upperarm
        z_origin = np.array([0., 0., 1.])
        x_vector = (-1 * np.array(origin_B_hand)[0:3, 1])
        x_vector /= np.linalg.norm(x_vector)
        y_orth = np.cross(z_origin, x_vector)
        y_orth /= np.linalg.norm(y_orth)
        z_orth = np.cross(x_vector, y_orth)
        z_orth /= np.linalg.norm(z_orth)
        origin_B_hand_rotated = np.eye(4)

        origin_B_hand_rotated[0:3, 0] = copy.copy(x_vector)
        origin_B_hand_rotated[0:3, 1] = copy.copy(y_orth)
        origin_B_hand_rotated[0:3, 2] = copy.copy(z_orth)
        origin_B_hand_rotated[0:3, 3] = copy.copy(np.array(origin_B_hand)[0:3, 3])
        origin_B_hand_rotated = np.matrix(origin_B_hand_rotated)

        rev = m.radians(180.)

        traj_y_offset, traj_z_offset = self.get_best_traj_offset()

        hand_rotated_B_traj_start_pos = np.matrix([[m.cos(rev), -m.sin(rev), 0., 0.042],
                                                   [m.sin(rev), m.cos(rev), 0., traj_y_offset],
                                                   [0., 0., 1., traj_z_offset],
                                                   [0., 0., 0., 1.]])

        origin_B_traj_start_pos = origin_B_hand_rotated * hand_rotated_B_traj_start_pos

        origin_B_upperarm_world = origin_B_upperarm * skeleton_frame_B_worldframe
        origin_B_forearm_world = origin_B_forearm * skeleton_frame_B_worldframe

        origin_B_forearm_pointed_down_arm = np.eye(4)
        z_origin = np.array([0., 0., 1.])
        x_vector = -1 * np.array(origin_B_forearm_world)[0:3, 2]
        x_vector /= np.linalg.norm(x_vector)
        if np.abs(x_vector[2]) > 0.99:
            x_vector = np.array([0., 0., np.sign(x_vector[2]) * 1.])
            y_orth = np.array([np.sign(x_vector[2]) * -1., 0., 0.])
            z_orth = np.array([0., np.sign(x_vector[2]) * 1., 0.])
        else:
            y_orth = np.cross(z_origin, x_vector)
            y_orth = y_orth / np.linalg.norm(y_orth)
            z_orth = np.cross(x_vector, y_orth)
            z_orth = z_orth / np.linalg.norm(z_orth)
        origin_B_forearm_pointed_down_arm[0:3, 0] = x_vector
        origin_B_forearm_pointed_down_arm[0:3, 1] = y_orth
        origin_B_forearm_pointed_down_arm[0:3, 2] = z_orth
        origin_B_forearm_pointed_down_arm[0:3, 3] = np.array(origin_B_forearm_world)[0:3, 3]
        origin_B_forearm_pointed_down_arm = np.matrix(origin_B_forearm_pointed_down_arm)

        origin_B_reference_coordinates = np.eye(4)
        x_horizontal = np.cross(y_orth, z_origin)
        x_horizontal /= np.linalg.norm(x_horizontal)
        origin_B_reference_coordinates[0:3, 0] = x_horizontal
        origin_B_reference_coordinates[0:3, 1] = y_orth
        origin_B_reference_coordinates[0:3, 2] = z_origin
        origin_B_reference_coordinates[0:3, 3] = np.array(origin_B_forearm_world)[0:3, 3]
        origin_B_reference_coordinates = np.matrix(origin_B_reference_coordinates)
        horizontal_B_forearm_pointed_down = origin_B_reference_coordinates.I * origin_B_forearm_pointed_down_arm
        angle_from_horizontal = m.degrees(m.acos(horizontal_B_forearm_pointed_down[0, 0]))

        forearm_pointed_down_arm_B_traj_end_pos = np.eye(4)
        forearm_pointed_down_arm_B_traj_end_pos[0:3, 3] = [-0.05, traj_y_offset, traj_z_offset]
        forearm_pointed_down_arm_B_traj_end_pos = np.matrix(forearm_pointed_down_arm_B_traj_end_pos)
        forearm_pointed_down_arm_B_elbow_reference = np.matrix([[m.cos(rev), -m.sin(rev), 0., 0.0],
                                                                [m.sin(rev), m.cos(rev), 0., traj_y_offset],
                                                                [0., 0., 1., traj_z_offset],
                                                                [0., 0., 0., 1.]])
        origin_B_elbow_reference = origin_B_forearm_pointed_down_arm * forearm_pointed_down_arm_B_elbow_reference
        rev = m.radians(180.)
        forearm_pointed_down_arm_B_traj_end = np.matrix([[m.cos(rev), -m.sin(rev), 0., -0.03],
                                                         [m.sin(rev), m.cos(rev), 0., traj_y_offset],
                                                         [0., 0., 1., traj_z_offset],
                                                         [0., 0., 0., 1.]])
        origin_B_traj_forearm_end = origin_B_forearm_pointed_down_arm * forearm_pointed_down_arm_B_traj_end

        origin_B_upperarm_pointed_down_shoulder = np.eye(4)
        z_origin = np.array([0., 0., 1.])
        x_vector = -1 * np.array(origin_B_upperarm_world)[0:3, 2]
        x_vector /= np.linalg.norm(x_vector)
        if np.abs(x_vector[2]) > 0.99:
            x_vector = np.array([0., 0., np.sign(x_vector[2]) * 1.])
            y_orth = np.array([np.sign(x_vector[2]) * -1., 0., 0.])
            z_orth = np.array([0., np.sign(x_vector[2]) * 1., 0.])
        else:
            y_orth = np.cross(z_origin, x_vector)
            y_orth = y_orth / np.linalg.norm(y_orth)
            z_orth = np.cross(x_vector, y_orth)
            z_orth = z_orth / np.linalg.norm(z_orth)
        origin_B_upperarm_pointed_down_shoulder[0:3, 0] = x_vector
        origin_B_upperarm_pointed_down_shoulder[0:3, 1] = y_orth
        origin_B_upperarm_pointed_down_shoulder[0:3, 2] = z_orth
        origin_B_upperarm_pointed_down_shoulder[0:3, 3] = np.array(origin_B_upperarm_world)[0:3, 3]
        origin_B_rotated_pointed_down_shoulder = np.matrix(origin_B_upperarm_pointed_down_shoulder)

        upperarm_pointed_down_shoulder_B_traj_end_pos = np.eye(4)
        upperarm_pointed_down_shoulder_B_traj_end_pos[0:3, 3] = [-0.05, traj_y_offset, traj_z_offset]
        upperarm_pointed_down_shoulder_B_traj_end_pos = np.matrix(upperarm_pointed_down_shoulder_B_traj_end_pos)
        rev = m.radians(180.)
        upperarm_pointed_down_shoulder_B_traj_upper_end = np.matrix([[m.cos(rev), -m.sin(rev), 0., -0.05],
                                                                     [m.sin(rev), m.cos(rev), 0., -0.0],
                                                                     [0., 0., 1., traj_z_offset],
                                                                     [0., 0., 0., 1.]])

        origin_B_traj_upper_end = origin_B_upperarm_pointed_down_shoulder * upperarm_pointed_down_shoulder_B_traj_upper_end

        origin_B_traj_upper_start = copy.copy(origin_B_elbow_reference)
        origin_B_traj_upper_start[0:3, 0:3] = origin_B_traj_upper_end[0:3, 0:3]

        forearm_B_upper_arm = origin_B_elbow_reference.I*origin_B_traj_upper_start

        # Calculation of goal at the top of the shoulder. Parallel to the ground, but pointing opposite direction of
        # the upper arm.
        # print 'origin_B_traj_upper_end\n', origin_B_traj_upper_end
        origin_B_traj_final_end = np.eye(4)
        z_vector = np.array([0., 0., 1.])
        original_x_vector = np.array(origin_B_traj_upper_end)[0:3, 0]
        # x_vector /= np.linalg.norm(x_vector)
        y_orth = np.cross(z_vector, original_x_vector)
        y_orth = y_orth / np.linalg.norm(y_orth)
        x_vector = np.cross(y_orth, z_vector)
        x_vector = x_vector / np.linalg.norm(x_vector)
        origin_B_traj_final_end[0:3, 0] = x_vector
        origin_B_traj_final_end[0:3, 1] = y_orth
        origin_B_traj_final_end[0:3, 2] = z_vector
        origin_B_traj_final_end[0:3, 3] = np.array([0.0, 0.0, traj_z_offset]) + \
                                          np.array(origin_B_upperarm_world)[0:3, 3]
        # print 'origin_B_traj_final_end\n', origin_B_traj_final_end
        # origin_B_rotated_pointed_down_shoulder = np.matrix(origin_B_upperarm_pointed_down_shoulder)

        # rev = m.radians(180.)
        # shoulder_position_B_traj_final_end = np.matrix([[m.cos(rev), -m.sin(rev), 0., 0.0],
        #                                                 [m.sin(rev), m.cos(rev), 0., -0.0],
        #                                                 [0., 0., 1., traj_z_offset],
        #                                                 [0., 0., 0., 1.]])
        origin_B_shoulder_position = np.eye(4)
        origin_B_shoulder_position[0:3, 3] = np.array(origin_B_upperarm)[0:3, 3]
        # origin_B_traj_final_end = np.matrix(origin_B_shoulder_position) * shoulder_position_B_traj_final_end

        origin_B_traj_start = origin_B_traj_start_pos

        # Find the transforms from the origin to the goal poses.
        goals = []
        # Goals along forearm
        path_distance = np.linalg.norm(np.array(origin_B_traj_start)[0:3, 3] -
                                       np.array(origin_B_traj_forearm_end)[0:3, 3])
        path_waypoints = np.arange(0., path_distance + path_distance * 0.01, (path_distance - 0.15) / 2.)
        for goal in path_waypoints:
            traj_start_B_traj_waypoint = np.matrix(np.eye(4))
            traj_start_B_traj_waypoint[0, 3] = goal
            origin_B_traj_waypoint = copy.copy(np.matrix(origin_B_traj_start) *
                                               np.matrix(traj_start_B_traj_waypoint))
            goals.append(copy.copy(origin_B_traj_waypoint))

        # Goals along upper arm
        path_distance = np.linalg.norm(np.array(origin_B_traj_forearm_end)[0:3, 3] -
                                       np.array(origin_B_traj_upper_end)[0:3, 3])
        path_waypoints = np.arange(path_distance, 0.0 - path_distance *0.01, -path_distance / 2.)
        for goal in path_waypoints:
            traj_start_B_traj_waypoint = np.matrix(np.eye(4))
            traj_start_B_traj_waypoint[0, 3] = -goal
            origin_B_traj_waypoint = copy.copy(np.matrix(origin_B_traj_upper_end) *
                                               np.matrix(traj_start_B_traj_waypoint))
            goals.append(copy.copy(origin_B_traj_waypoint))

        # Goals at the top of the shoulder
        origin_B_traj_waypoint[0:3, 0:3] = origin_B_traj_final_end[0:3, 0:3]
        goals.append(copy.copy(origin_B_traj_waypoint))
        goals.append(copy.copy(origin_B_traj_final_end))

        # for goal in goals:
        #     print goal

        # path_distance = np.linalg.norm(np.array(origin_B_traj_upper_end)[0:3, 3] -
        #                                np.array(origin_B_traj_final_end)[0:3, 3])
        # path_waypoints = np.arange(path_distance,  0.0 - path_distance * 0.01, -path_distance / 1.)
        # for goal in path_waypoints:
        #     traj_start_B_traj_waypoint = np.matrix(np.eye(4))
        #     traj_start_B_traj_waypoint[0, 3] = -goal
        #     origin_B_traj_waypoint = copy.copy(np.matrix(origin_B_traj_final_end) *
        #                                        np.matrix(traj_start_B_traj_waypoint))
        #     goals.append(copy.copy(origin_B_traj_waypoint))
        fixed_point_exceeded_amount = 0.
        # print 'stretch allowable:\n', self.stretch_allowable
        if self.add_new_fixed_point:
            self.add_new_fixed_point = False
            self.fixed_points.append(np.array(goals[-1])[0:3, 3])
        for point_i in self.fixed_points_to_use:
            fixed_point = self.fixed_points[point_i]
            # fixed_position = np.array(fixed_point)[0:3, 3]
            # print 'fixed point:\n', fixed_point
            for goal in goals:
                goal_position = np.array(goal)[0:3, 3]
                # print 'goal_position:\n', goal_position
                # print 'stretch allowable:\n', self.stretch_allowable
                # print 'amount stretched:\n', np.linalg.norm(fixed_point - goal_position)
                # print 'amount exceeded by this goal:\n', np.linalg.norm(fixed_point - goal_position) - self.stretch_allowable[point_i]
                fixed_point_exceeded_amount = np.max([fixed_point_exceeded_amount, np.linalg.norm(fixed_point - goal_position) - self.stretch_allowable[point_i]])
            # if fixed_point_exceeded_amount > 0.:
            #     print 'The gown is being stretched too much to try to do the next part of the task.'

        # print 'fixed_point_exceeded_amount:', fixed_point_exceeded_amount
        return goals, np.matrix(origin_B_forearm_pointed_down_arm), np.matrix(origin_B_upperarm_pointed_down_shoulder), \
               np.matrix(origin_B_hand), np.matrix(origin_B_wrist), \
               np.matrix(origin_B_traj_start), np.matrix(origin_B_traj_forearm_end), np.matrix(origin_B_traj_upper_end), \
               np.matrix(origin_B_traj_final_end), angle_from_horizontal, \
               np.matrix(forearm_B_upper_arm), fixed_point_exceeded_amount

    def objective_function_coarse(self, params):
        # params = [m.radians(90.0),  m.radians(0.), m.radians(45.), m.radians(0.)]
        # print 'doing subtask', self.subtask_step
        # print 'params:\n', params
        if self.subtask_step == 0 or False:  # for right arm
            # params = [1.41876758,  0.13962405,  1.47350044,  0.95524629]  # old solution with joint jump
            # params = [1.73983062, -0.13343737,  0.42208647,  0.26249355]  # solution with arm snaking
            # params = [0.3654207,  0.80081779,  0.44793856,  1.83270078]  # without checking with phsyx
            params = [0.9679925, 0.18266905, 0.87995157, 0.77562143]
            # self.visualize = False

        elif False:  # for left arm
            params = [1.5707963267948966, -0.17453292519943295, 1.3962634015954636, 1.5707963267948966]
            # self.visualize = True

        # Check if all arm configurations within a ball in configuration space of the current configuration are 'good'
        neigh_distances, neighbors = self.arm_knn.kneighbors([params], 16)
        for neigh_dist, neighbor in zip(neigh_distances[0], neighbors[0]):
            if np.max(np.abs(np.array(self.arm_configs_checked[neighbor] - np.array(params)))) < m.radians(15.):
                if not self.arm_configs_eval[neighbor][5] == 'good':
                    # print 'arm evaluation found this configuration to be bad'
                    this_score = 10. + 10. + 4. + random.random()
                    with open(self.save_file_path + self.save_file_name_coarse_raw, 'a') as myfile:
                        myfile.write(str(self.subtask_step)
                                     + ',' + str("{:.5f}".format(params[0]))
                                     + ',' + str("{:.5f}".format(params[1]))
                                     + ',' + str("{:.5f}".format(params[2]))
                                     + ',' + str("{:.5f}".format(params[3]))
                                     + ',' + str("{:.5f}".format(this_score))
                                     + '\n')
                    return this_score
        print 'arm config is not bad'
        arm = self.human_arm.split('a')[0]

        # Set both of the human's arms in DART. The opposite arm is held by the side of the body. The arm that will be
        # dressed is set to the values of this objective function evaluation.
        self.set_human_model_dof_dart([0, 0, 0, 0], self.human_opposite_arm)
        self.set_human_model_dof_dart([params[0], params[1], params[2], params[3]], self.human_arm)

        # Check if the person is in self collision, which means parts of the arm are in collision with anything other
        # than the shoulder or itself.
        if self.is_human_in_self_collision():
            this_score = 10. + 10. + 2. + random.random()
            if self.save_all_results:
                with open(self.save_file_path + self.save_file_name_coarse_raw, 'a') as myfile:
                    myfile.write(str(self.subtask_step)
                                 + ',' + str("{:.5f}".format(params[0]))
                                 + ',' + str("{:.5f}".format(params[1]))
                                 + ',' + str("{:.5f}".format(params[2]))
                                 + ',' + str("{:.5f}".format(params[3]))
                                 + ',' + str("{:.5f}".format(this_score))
                                 + '\n')
            return this_score

        print 'arm config is not in self collision'

        # Now generates the trajectories based on the arm configuration. Here we also set and check constraints on the
        # trajectory. For example, once one arm is dressed, the gown must stay on that arm. That adds a constraint
        # that the top of that gown basically stays above the dressed shoulder. So all trajectories for the second arm
        # must stay within some distance of the fixed point.
        self.goals, \
        origin_B_forearm_pointed_down_arm, \
        origin_B_upperarm_pointed_down_shoulder, \
        origin_B_hand, \
        origin_B_wrist, \
        origin_B_traj_start, \
        origin_B_traj_forearm_end, \
        origin_B_traj_upper_end, \
        origin_B_traj_final_end, \
        angle_from_horizontal, \
        forearm_B_upper_arm, \
        fixed_points_exceeded_amount = self.find_reference_coordinate_frames_and_goals(arm)
        if fixed_points_exceeded_amount <= 0:
            print 'arm does not break fixed_points requirement'
        else:
            print 'fixed points exceeded: ', fixed_points_exceeded_amount

        if fixed_points_exceeded_amount > 0.:
            # print 'The gown is being stretched too much to try to do the next part of the task.'
            # return 10. + 1. + 10. * fixed_points_exceeded_amount
            this_score = 10. + 10. + 1. + 10. * fixed_points_exceeded_amount
            if self.save_all_results:
                with open(self.save_file_path + self.save_file_name_coarse_raw, 'a') as myfile:
                    myfile.write(str(self.subtask_step)
                                 + ',' + str("{:.5f}".format(params[0]))
                                 + ',' + str("{:.5f}".format(params[1]))
                                 + ',' + str("{:.5f}".format(params[2]))
                                 + ',' + str("{:.5f}".format(params[3]))
                                 + ',' + str("{:.5f}".format(this_score))
                                 + '\n')
            return this_score

        # We also have calculated when generating the trajectories, the angle from horizontal of the forearm. We have
        # previous simulation that gives a range of angles for which dressing can succeed. We apply that constraint
        # here
        print 'angle from horizontal = ', angle_from_horizontal
        if abs(angle_from_horizontal) > 30.:
            print 'Angle of forearm is too high for success'
            this_score = 10. + 10. + 10. * (abs(angle_from_horizontal) - 30.)
            if self.save_all_results:
                with open(self.save_file_path + self.save_file_name_coarse_raw, 'a') as myfile:
                    myfile.write(str(self.subtask_step)
                                 + ',' + str("{:.5f}".format(params[0]))
                                 + ',' + str("{:.5f}".format(params[1]))
                                 + ',' + str("{:.5f}".format(params[2]))
                                 + ',' + str("{:.5f}".format(params[3]))
                                 + ',' + str("{:.5f}".format(this_score))
                                 + '\n')
            return this_score

        # Here we calculate the torque on the shoulder of the person based on average limb weights. We scale that
        # torque by an estimated maximum torque, which is the torque with the arm fully extended. This gives us a
        # torque cost that ranges from 0 to 1.
        ############################################
        # Body mass from https://msis.jsc.nasa.gov/sections/section03.htm for average human male
        # upper arm: 2.500 kg
        # fore arm: 1.450 kg
        # hand: 0.530 kg
        upper_arm_force = np.array([0, 0, 2.5 * -9.8])
        forearm_force = np.array([0., 0., 1.45 * -9.8])
        hand_force = np.array([0., 0., 0.53 * -9.8])
        shoulder_to_upper_arm_midpoint = (np.array(origin_B_forearm_pointed_down_arm)[0:3, 3] -
                                          np.array(origin_B_upperarm_pointed_down_shoulder)[0:3, 3]) / 2.
        shoulder_to_forearm = (np.array(origin_B_forearm_pointed_down_arm)[0:3, 3] -
                               np.array(origin_B_upperarm_pointed_down_shoulder)[0:3, 3])
        shoulder_to_forearm_midpoint = (np.array(origin_B_forearm_pointed_down_arm)[0:3, 3] -
                                        np.array(origin_B_upperarm_pointed_down_shoulder)[0:3, 3]) + \
                                       (np.array(origin_B_wrist)[0:3, 3] -
                                        np.array(origin_B_forearm_pointed_down_arm)[0:3, 3]) / 2.
        shoulder_to_hand_midpoint = (np.array(origin_B_hand)[0:3, 3] -
                                     np.array(origin_B_upperarm_pointed_down_shoulder)[0:3, 3])
        # elbow_to_forearm_midpoint = (np.array(origin_B_wrist)[0:3, 3] -
        #                              np.array(origin_B_forearm_pointed_down_arm)[0:3, 3]) / 2.
        # elbow_to_hand_midpoint = (np.array(origin_B_hand)[0:3, 3] -
        #                           np.array(origin_B_forearm_pointed_down_arm)[0:3, 3])
        # print 'shoulder_to_upper_arm_midpoint\n', shoulder_to_upper_arm_midpoint
        # print 'shoulder_to_forearm\n', shoulder_to_forearm
        # print 'shoulder_to_forearm_midpoint\n', shoulder_to_forearm_midpoint
        # print 'shoulder_to_hand_midpoint\n', shoulder_to_hand_midpoint
        torque_at_shoulder = np.cross(-1 * shoulder_to_upper_arm_midpoint, upper_arm_force) + \
                             np.cross(-1 * shoulder_to_forearm_midpoint, forearm_force) + \
                             np.cross(-1 * shoulder_to_hand_midpoint, hand_force)
        # torque_at_elbow = np.cross(-1 * elbow_to_forearm_midpoint, forearm_force) + \
        #                   np.cross(-1 * elbow_to_hand_midpoint, hand_force)
        # forearm_mass*np.linalg.norm(shoulder_to_forearm_midpoint[0:2]) + \
        # hand_mass*np.linalg.norm(shoulder_to_hand_midpoint[0:2])
        torque_magnitude = np.linalg.norm(torque_at_shoulder)  # + np.linalg.norm(torque_at_elbow)
        max_possible_torque = 12.376665  # found manually with arm straight out from arm
        # print 'torque_at_shoulder\n', torque_at_shoulder
        # print 'torque_magnitude\n', torque_magnitude
        torque_cost = torque_magnitude / max_possible_torque

        ############################################

        self.force_cost = 0.

        alpha = 1.  # cost on forces
        beta = 1.  # cost on manipulability
        zeta = 0.5  # cost on torque
        physx_score = self.force_cost * alpha + torque_cost * zeta
        this_score = physx_score

        print 'Physx score was: ', physx_score
        if self.save_all_results:
            with open(self.save_file_path + self.save_file_name_coarse_raw, 'a') as myfile:
                myfile.write(str(self.subtask_step)
                             + ',' + str("{:.5f}".format(params[0]))
                             + ',' + str("{:.5f}".format(params[1]))
                             + ',' + str("{:.5f}".format(params[2]))
                             + ',' + str("{:.5f}".format(params[3]))
                             + ',' + str("{:.5f}".format(this_score))
                             + '\n')
            with open(self.save_file_path + self.save_file_name_coarse_feasible, 'a') as myfile:
                myfile.write(str(self.subtask_step)
                             + ',' + str("{:.5f}".format(params[0]))
                             + ',' + str("{:.5f}".format(params[1]))
                             + ',' + str("{:.5f}".format(params[2]))
                             + ',' + str("{:.5f}".format(params[3]))
                             + ',' + str("{:.5f}".format(this_score))
                             + '\n')
        return this_score

    def objective_function_fine(self, params):
        # params = [m.radians(90.0),  m.radians(0.), m.radians(45.), m.radians(0.)]
        # print 'doing subtask', self.subtask_step
        # print 'params:\n', params
        if self.subtask_step == 0 or False:  # for right arm
            # params = [1.41876758,  0.13962405,  1.47350044,  0.95524629]  # old solution with joint jump
            # params = [1.73983062, -0.13343737,  0.42208647,  0.26249355]  # solution with arm snaking
            # params = [0.3654207,  0.80081779,  0.44793856,  1.83270078]  # without checking with phsyx
            params = [0.9679925, 0.18266905, 0.87995157, 0.77562143]
            # self.visualize = False

        elif False:  # for left arm
            params = [1.5707963267948966, -0.17453292519943295, 1.3962634015954636, 1.5707963267948966]
            # self.visualize = True

        # Check if all arm configurations within a ball in configuration space of the current configuration are 'good'
        neigh_distances, neighbors = self.arm_knn.kneighbors([params], 16)
        for neigh_dist, neighbor in zip(neigh_distances[0], neighbors[0]):
            if np.max(np.abs(np.array(self.arm_configs_checked[neighbor] - np.array(params)))) < m.radians(15.):
                if not self.arm_configs_eval[neighbor][5] == 'good':
                    # print 'arm evaluation found this configuration to be bad'
                    this_score = 10. + 10. + 4. + random.random()
                    with open(self.save_file_path+self.save_file_name_fine_raw, 'a') as myfile:
                        myfile.write(str(self.subtask_step)
                                     + ',' + str("{:.5f}".format(params[0]))
                                     + ',' + str("{:.5f}".format(params[1]))
                                     + ',' + str("{:.5f}".format(params[2]))
                                     + ',' + str("{:.5f}".format(params[3]))
                                     + ',' + str("{:.5f}".format(this_score))
                                     + '\n')
                    return this_score
        print 'arm config is not bad'
        arm = self.human_arm.split('a')[0]

        self.set_human_model_dof_dart([0, 0, 0, 0], self.human_opposite_arm)
        self.set_human_model_dof_dart([params[0], params[1], params[2], params[3]], self.human_arm)

        if self.is_human_in_self_collision():
            this_score = 10. + 10. + 2. + random.random()
            if self.save_all_results:
                with open(self.save_file_path + self.save_file_name_fine_raw, 'a') as myfile:
                    myfile.write(str(self.subtask_step)
                                 + ',' + str("{:.5f}".format(params[0]))
                                 + ',' + str("{:.5f}".format(params[1]))
                                 + ',' + str("{:.5f}".format(params[2]))
                                 + ',' + str("{:.5f}".format(params[3]))
                                 + ',' + str("{:.5f}".format(this_score))
                                 + '\n')
            return this_score

        print 'arm config is not in self collision'

        self.goals, \
        origin_B_forearm_pointed_down_arm, \
        origin_B_upperarm_pointed_down_shoulder, \
        origin_B_hand, \
        origin_B_wrist, \
        origin_B_traj_start, \
        origin_B_traj_forearm_end, \
        origin_B_traj_upper_end, \
        origin_B_traj_final_end, \
        angle_from_horizontal, \
        forearm_B_upper_arm, \
        fixed_points_exceeded_amount = self.find_reference_coordinate_frames_and_goals(arm)
        if fixed_points_exceeded_amount <= 0:
            print 'arm does not break fixed_points requirement'
        else:
            print 'fixed points exceeded: ', fixed_points_exceeded_amount

        if fixed_points_exceeded_amount > 0.:
            # print 'The gown is being stretched too much to try to do the next part of the task.'
            # return 10. + 1. + 10. * fixed_points_exceeded_amount
            this_score = 10. + 10. + 1. + 10. * fixed_points_exceeded_amount
            if self.save_all_results:
                with open(self.save_file_path + self.save_file_name_fine_raw, 'a') as myfile:
                    myfile.write(str(self.subtask_step)
                                 + ',' + str("{:.5f}".format(params[0]))
                                 + ',' + str("{:.5f}".format(params[1]))
                                 + ',' + str("{:.5f}".format(params[2]))
                                 + ',' + str("{:.5f}".format(params[3]))
                                 + ',' + str("{:.5f}".format(this_score))
                                 + '\n')
            return this_score

        print 'angle from horizontal = ', angle_from_horizontal
        if abs(angle_from_horizontal) > 30.:
            print 'Angle of forearm is too high for success'
            this_score = 10. + 10. + 10. * (abs(angle_from_horizontal) - 30.)
            if self.save_all_results:
                with open(self.save_file_path + self.save_file_name_fine_raw, 'a') as myfile:
                    myfile.write(str(self.subtask_step)
                                 + ',' + str("{:.5f}".format(params[0]))
                                 + ',' + str("{:.5f}".format(params[1]))
                                 + ',' + str("{:.5f}".format(params[2]))
                                 + ',' + str("{:.5f}".format(params[3]))
                                 + ',' + str("{:.5f}".format(this_score))
                                 + '\n')
            return this_score

        ############################################
        # Body mass from https://msis.jsc.nasa.gov/sections/section03.htm for average human male
        # upper arm: 2.500 kg
        # fore arm: 1.450 kg
        # hand: 0.530 kg
        upper_arm_force = np.array([0, 0, 2.5 * -9.8])
        forearm_force = np.array([0., 0., 1.45 * -9.8])
        hand_force = np.array([0., 0., 0.53 * -9.8])
        shoulder_to_upper_arm_midpoint = (np.array(origin_B_forearm_pointed_down_arm)[0:3, 3] -
                                          np.array(origin_B_upperarm_pointed_down_shoulder)[0:3, 3]) / 2.
        shoulder_to_forearm = (np.array(origin_B_forearm_pointed_down_arm)[0:3, 3] -
                               np.array(origin_B_upperarm_pointed_down_shoulder)[0:3, 3])
        shoulder_to_forearm_midpoint = (np.array(origin_B_forearm_pointed_down_arm)[0:3, 3] -
                                        np.array(origin_B_upperarm_pointed_down_shoulder)[0:3, 3]) + \
                                       (np.array(origin_B_wrist)[0:3, 3] -
                                        np.array(origin_B_forearm_pointed_down_arm)[0:3, 3]) / 2.
        shoulder_to_hand_midpoint = (np.array(origin_B_hand)[0:3, 3] -
                                     np.array(origin_B_upperarm_pointed_down_shoulder)[0:3, 3])
        # elbow_to_forearm_midpoint = (np.array(origin_B_wrist)[0:3, 3] -
        #                              np.array(origin_B_forearm_pointed_down_arm)[0:3, 3]) / 2.
        # elbow_to_hand_midpoint = (np.array(origin_B_hand)[0:3, 3] -
        #                           np.array(origin_B_forearm_pointed_down_arm)[0:3, 3])
        # print 'shoulder_to_upper_arm_midpoint\n', shoulder_to_upper_arm_midpoint
        # print 'shoulder_to_forearm\n', shoulder_to_forearm
        # print 'shoulder_to_forearm_midpoint\n', shoulder_to_forearm_midpoint
        # print 'shoulder_to_hand_midpoint\n', shoulder_to_hand_midpoint
        torque_at_shoulder = np.cross(-1 * shoulder_to_upper_arm_midpoint, upper_arm_force) + \
                             np.cross(-1 * shoulder_to_forearm_midpoint, forearm_force) + \
                             np.cross(-1 * shoulder_to_hand_midpoint, hand_force)
        # torque_at_elbow = np.cross(-1 * elbow_to_forearm_midpoint, forearm_force) + \
        #                   np.cross(-1 * elbow_to_hand_midpoint, hand_force)
        # forearm_mass*np.linalg.norm(shoulder_to_forearm_midpoint[0:2]) + \
        # hand_mass*np.linalg.norm(shoulder_to_hand_midpoint[0:2])
        torque_magnitude = np.linalg.norm(torque_at_shoulder)  # + np.linalg.norm(torque_at_elbow)
        max_possible_torque = 12.376665  # found manually with arm straight out from arm
        # print 'torque_at_shoulder\n', torque_at_shoulder
        # print 'torque_magnitude\n', torque_magnitude
        torque_cost = torque_magnitude / max_possible_torque

        ############################################

        start_time = rospy.Time.now()
        self.set_goals()
        # print self.origin_B_grasps
        maxiter = 50
        popsize = 20#4*20

        # cma parameters: [pr2_base_x, pr2_base_y, pr2_base_theta, pr2_base_height,
        # human_arm_dof_1, human_arm_dof_2, human_arm_dof_3, human_arm_dof_4, human_arm_dof_5,
        # human_arm_dof_6, human_arm_dof_7]
        parameters_min_pr2 = np.array([-1.5, -1.5, -6.5*m.pi-.001, 0.0])
        parameters_max_pr2 = np.array([1.5, 1.5, 6.5*m.pi+.001, 0.3])
        # [0.3, -0.9, 1.57 * m.pi / 3., 0.3]
        # parameters_min = np.array([-0.1, -1.0, m.pi/2. - .001, 0.2])
        # parameters_max = np.array([0.8, -0.3, 2.5*m.pi/2. + .001, 0.3])
        parameters_scaling_pr2 = (parameters_max_pr2-parameters_min_pr2)/8.

        init_start_pr2_configs = [[0.1, 0.6, m.radians(180.), 0.3],
                                  [0.1, -0.6, m.radians(0.), 0.3],
                                  [0.6, 0.0, m.radians(90.), 0.3]]

        parameters_initialization_pr2 = (parameters_max_pr2+parameters_min_pr2)/2.
        opts_cma_pr2 = {'seed': 1234, 'ftarget': -1., 'popsize': popsize, 'maxiter': maxiter,
                        'maxfevals': 1e8, 'CMA_cmean': 0.25, 'tolfun': 1e-3,
                        'tolfunhist': 1e-12, 'tolx': 5e-4,
                        'maxstd': 4.0, 'tolstagnation': 100,
                        'verb_filenameprefix': 'outcma_pr2_base',
                        'scaling_of_variables': list(parameters_scaling_pr2),
                        'bounds': [list(parameters_min_pr2), list(parameters_max_pr2)]}

        self.this_best_pr2_config = None
        self.this_best_pr2_score = 1000.

        for init_start_pr2_config in init_start_pr2_configs:
            print 'Starting to evaluate a new initial PR2 configuration:', init_start_pr2_config
            parameters_initialization = init_start_pr2_config
            self.kinematics_optimization_results = cma.fmin(self.objective_function_one_config,
                                                          list(parameters_initialization),
                                                          1.,
                                                          options=opts_cma_pr2)
            print 'This arm config is:\n',params
            print 'Best PR2 configuration for this arm config so far: \n', self.this_best_pr2_config
            print 'Associated score: ', self.this_best_pr2_score
        # self.pr2_parameters.append([self.kinematics_optimization_results[0], self.kinematics_optimization_results[1]])
        # save_pickle(self.pr2_parameters, self.pkg_path+'/data/all_pr2_configs.pkl')
        gc.collect()
        elapsed_time = rospy.Time.now()-start_time
        print 'Done with openrave round. Time elapsed:', elapsed_time.to_sec()
        print 'Openrave results:'
        # print self.kinematics_optimization_results
        self.force_cost = 0.
        alpha = 1.  # cost on forces
        beta = 1.  # cost on manipulability
        zeta = 0.5  # cost on torque
        if self.this_best_pr2_score < 0.:
            physx_score = self.force_cost*alpha + torque_cost*zeta
            this_score = physx_score + self.this_best_pr2_score*beta
            print 'Force cost was: ', self.force_cost
            print 'Torque score was: ', torque_cost
            print 'Physx score was: ', physx_score
            print 'Best pr2 kinematics score was: ', self.this_best_pr2_score
            if self.save_all_results:
                with open(self.save_file_path+self.save_file_name_fine_raw, 'a') as myfile:
                    myfile.write(str(self.subtask_step)
                                 + ',' + str("{:.5f}".format(params[0]))
                                 + ',' + str("{:.5f}".format(params[1]))
                                 + ',' + str("{:.5f}".format(params[2]))
                                 + ',' + str("{:.5f}".format(params[3]))
                                 + ',' + str("{:.5f}".format(this_score))
                                 + ',' + str("{:.5f}".format(self.this_best_pr2_config[0]))
                                 + ',' + str("{:.5f}".format(self.this_best_pr2_config[1]))
                                 + ',' + str("{:.5f}".format(self.this_best_pr2_config[2]))
                                 + ',' + str("{:.5f}".format(self.this_best_pr2_config[3]))
                                 + ',' + str("{:.5f}".format(self.this_best_pr2_score))
                                 + '\n')
                with open(self.save_file_path + self.save_file_name_fine, 'a') as myfile:
                    myfile.write(str(self.subtask_step)
                                 + ',' + str("{:.5f}".format(params[0]))
                                 + ',' + str("{:.5f}".format(params[1]))
                                 + ',' + str("{:.5f}".format(params[2]))
                                 + ',' + str("{:.5f}".format(params[3]))
                                 + ',' + str("{:.5f}".format(this_score))
                                 + ',' + str("{:.5f}".format(self.this_best_pr2_config[0]))
                                 + ',' + str("{:.5f}".format(self.this_best_pr2_config[1]))
                                 + ',' + str("{:.5f}".format(self.this_best_pr2_config[2]))
                                 + ',' + str("{:.5f}".format(self.this_best_pr2_config[3]))
                                 + ',' + str("{:.5f}".format(self.this_best_pr2_score))
                                 + '\n')
            return this_score

        print 'Force cost was: ', self.force_cost
        print 'Kinematics score was: ', self.this_best_pr2_score
        print 'Torque score was: ', torque_cost
        physx_score = self.force_cost*alpha + torque_cost*zeta
        this_score = 10. + physx_score + self.this_best_pr2_score*beta
        print 'Total score was: ', this_score
        if self.save_all_results:
            with open(self.save_file_path + self.save_file_name_fine_raw, 'a') as myfile:
                myfile.write(str(self.subtask_step)
                             + ',' + str("{:.5f}".format(params[0]))
                             + ',' + str("{:.5f}".format(params[1]))
                             + ',' + str("{:.5f}".format(params[2]))
                             + ',' + str("{:.5f}".format(params[3]))
                             + ',' + str("{:.5f}".format(this_score))
                             + ',' + str("{:.5f}".format(self.this_best_pr2_config[0]))
                             + ',' + str("{:.5f}".format(self.this_best_pr2_config[1]))
                             + ',' + str("{:.5f}".format(self.this_best_pr2_config[2]))
                             + ',' + str("{:.5f}".format(self.this_best_pr2_config[3]))
                             + ',' + str("{:.5f}".format(self.this_best_pr2_score))
                             + '\n')
        return this_score

    def set_goals(self, single_goal=False):
        self.origin_B_grasps = []
        for num in xrange(len(self.goals)):
            self.origin_B_grasps.append(np.array(np.matrix(self.goals[num]))*np.matrix(self.gripper_B_tool.I))#*np.matrix(self.goal_B_gripper)))

    def set_robot_arm(self, arm):
        if self.robot_arm == arm:
            return False
        elif 'left' in arm or 'right' in arm:
            # Set robot arm for dressing
            print 'Setting the robot arm being used by base selection to ', arm
            if 'left' in arm:
                self.robot_arm = 'leftarm'
                self.robot_opposite_arm = 'rightarm'
            elif 'right' in arm:
                self.robot_arm = 'rightarm'
                self.robot_opposite_arm = 'leftarm'
            for robot_arm in [self.robot_opposite_arm, self.robot_arm]:
                self.op_robot.SetActiveManipulator(robot_arm)
                self.manip = self.op_robot.GetActiveManipulator()
                ikmodel = op.databases.inversekinematics.InverseKinematicsModel(self.op_robot,
                                                                                iktype=op.IkParameterization.Type.Transform6D)
                if not ikmodel.load():
                    print 'IK model not found for this arm. Generating the ikmodel for the ', robot_arm
                    print 'This will take a while'
                    ikmodel.autogenerate()
                self.manipprob = op.interfaces.BaseManipulation(self.op_robot)
            return True
        else:
            print 'ERROR'
            print 'I do not know what arm to be using'
            return False

    def set_human_arm(self, arm):
        # Set human arm for dressing
        print 'Setting the human arm being used by base selection to ', arm
        if 'left' in arm:
            self.gripper_B_tool = np.matrix([[0., 1., 0., 0.03],
                                             [-1., 0., 0., 0.0],
                                             [0., 0., 1., -0.05],
                                             [0., 0., 0., 1.]])
            self.human_arm = 'leftarm'
            self.human_opposite_arm = 'rightarm'
            return True
        elif 'right' in arm:
            self.gripper_B_tool = np.matrix([[0., -1., 0., 0.03],
                                             [1., 0., 0., 0.0],
                                             [0., 0., 1., -0.05],
                                             [0., 0., 0., 1.]])
            self.human_arm = 'rightarm'
            self.human_opposite_arm = 'leftarm'
            return True
        else:
            print 'ERROR'
            print 'I do not know what arm to be using'
            return False

    def objective_function_one_config(self, current_parameters):
        # start_time = rospy.Time.now()
        # current_parameters = [0.3, -0.9, 1.57*m.pi/3., 0.3]
        if self.subtask_step == 0 or False:  # right arm
            # current_parameters = [0.2743685, -0.71015745, 0.20439603, 0.29904425]
            # current_parameters = [0.2743685, -0.71015745, 2.2043960252256807, 0.29904425]  # old solution with joint jump
            # current_parameters = [2.5305254, -0.6124738, -2.37421411, 0.02080042]  # solution with arm snaking
            # current_parameters = [0.44534457, -0.85069379, 2.95625035, 0.07931574]  # solution with arm in lap, no physx
            current_parameters = [ 0.04840878, -0.83110347 , 0.97416245,  0.29999239]
        elif False:  # left arm
            current_parameters = [0.69510576,  0.68875733, -0.85141057, 0.05047799]
        x = current_parameters[0]
        y = current_parameters[1]
        th = current_parameters[2]
        z = current_parameters[3]

        origin_B_pr2 = np.matrix([[ m.cos(th), -m.sin(th),     0.,         x],
                                  [ m.sin(th),  m.cos(th),     0.,         y],
                                  [        0.,         0.,     1.,        0.],
                                  [        0.,         0.,     0.,        1.]])
        # print 'pr2_B_origin\n', origin_B_pr2.I
        v = self.robot.positions()

        # For a solution for a bit to get screenshots, etc. Check colllision removes old collision markers.
        if False:
            self.dart_world.check_collision()
            rospy.sleep(20)

        v['rootJoint_pos_x'] = x
        v['rootJoint_pos_y'] = y
        v['rootJoint_pos_z'] = 0.
        v['rootJoint_rot_z'] = th
        self.dart_world.displace_gown()
        # sign_flip = 1.
        # if 'right' in self.robot_arm:
        #     sign_flip = -1.
        v['l_shoulder_pan_joint'] = 3.14 / 2
        v['l_shoulder_lift_joint'] = -0.52
        v['l_upper_arm_roll_joint'] = 0.
        v['l_elbow_flex_joint'] = -3.14 * 2 / 3
        v['l_forearm_roll_joint'] = 0.
        v['l_wrist_flex_joint'] = 0.
        v['l_wrist_roll_joint'] = 0.
        v['l_gripper_l_finger_joint'] = .24
        v['l_gripper_r_finger_joint'] = .24
        v['r_shoulder_pan_joint'] = -1 * 3.14 / 2
        v['r_shoulder_lift_joint'] = -0.52
        v['r_upper_arm_roll_joint'] = 0.
        v['r_elbow_flex_joint'] = -3.14 * 2 / 3
        v['r_forearm_roll_joint'] = 0.
        v['r_wrist_flex_joint'] = 0.
        v['r_wrist_roll_joint'] = 0.
        v['r_gripper_l_finger_joint'] = .24
        v['r_gripper_r_finger_joint'] = .24
        v['torso_lift_joint'] = 0.3

        v['torso_lift_joint'] = z

        self.robot.set_positions(v)

        # self.dart_world.set_gown()

        # PR2 is too close to the person (who is at the origin). PR2 base is 0.668m x 0.668m
        distance_from_origin = np.linalg.norm(origin_B_pr2[:2, 3])
        if distance_from_origin <= 0.334:
            this_pr2_score = 10. + 1. + (0.4 - distance_from_origin)
            return this_pr2_score

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
            this_pr2_score = 10. +1.+ 20.*(distance - 1.25)
            return this_pr2_score

        reach_score = 0.
        manip_score = 0.
        goal_scores = []
        manip = 0.
        reached = 0.

        # sign_flip = 1.
        # if 'right' in self.robot_arm:
        #     sign_flip = -1.
        # v = self.robot.q
        # v[self.robot_opposite_arm[0] + '_shoulder_pan_joint'] = -sign_flip * 3.14 / 2
        # v[self.robot_opposite_arm[0] + '_shoulder_lift_joint'] = -0.52
        # v[self.robot_opposite_arm[0] + '_upper_arm_roll_joint'] = 0.
        # v[self.robot_opposite_arm[0] + '_elbow_flex_joint'] = -3.14 * 2 / 3
        # v[self.robot_opposite_arm[0] + '_forearm_roll_joint'] = 0.
        # v[self.robot_opposite_arm[0] + '_wrist_flex_joint'] = 0.
        # v[self.robot_opposite_arm[0] + '_wrist_roll_joint'] = 0.
        # self.robot.set_positions(v)

        # in_collision = self.is_dart_in_collision()
        base_in_collision = self.is_dart_base_in_collision()

        close_to_collision = False
        check_if_PR2_is_near_collision = False
        if check_if_PR2_is_near_collision:
            positions = self.robot.positions()
            positions['rootJoint_pos_x'] = x + 0.04
            positions['rootJoint_pos_y'] = y + 0.04
            positions['rootJoint_pos_z'] = 0.
            positions['rootJoint_rot_z'] = th
            self.robot.set_positions(positions)
            self.dart_world.set_gown([self.robot_arm])
            close_to_collision = np.max([self.is_dart_in_collision(), close_to_collision])

            positions['rootJoint_pos_x'] = x - 0.04
            positions['rootJoint_pos_y'] = y + 0.04
            positions['rootJoint_pos_z'] = 0.
            positions['rootJoint_rot_z'] = th
            self.robot.set_positions(positions)
            self.dart_world.set_gown([self.robot_arm])
            close_to_collision = np.max([self.is_dart_in_collision(), close_to_collision])

            positions['rootJoint_pos_x'] = x - 0.04
            positions['rootJoint_pos_y'] = y - 0.04
            positions['rootJoint_pos_z'] = 0.
            positions['rootJoint_rot_z'] = th
            self.robot.set_positions(positions)
            self.dart_world.set_gown([self.robot_arm])
            close_to_collision = np.max([self.is_dart_in_collision(), close_to_collision])

            positions['rootJoint_pos_x'] = x + 0.04
            positions['rootJoint_pos_y'] = y - 0.04
            positions['rootJoint_pos_z'] = 0.
            positions['rootJoint_rot_z'] = th
            self.robot.set_positions(positions)
            self.dart_world.set_gown([self.robot_arm])
            close_to_collision = np.max([self.is_dart_in_collision(), close_to_collision])

            positions['rootJoint_pos_x'] = x
            positions['rootJoint_pos_y'] = y
            positions['rootJoint_pos_z'] = 0.
            positions['rootJoint_rot_z'] = th
            self.robot.set_positions(positions)
            self.dart_world.set_gown([self.robot_arm])
        best_ik = None
        if not close_to_collision and not base_in_collision:
            reached = np.zeros(len(self.origin_B_grasps))
            manip = np.zeros(len(self.origin_B_grasps))
            is_smooth_ik_possible, joint_change_amount = self.check_smooth_ik_feasiblity(self.origin_B_grasps)
            if not is_smooth_ik_possible:
                this_pr2_score = 10. + 1. + joint_change_amount
                if this_pr2_score < self.this_best_pr2_score:
                    self.this_best_pr2_config = current_parameters
                    self.this_best_pr2_score = this_pr2_score
                return this_pr2_score
            all_sols = []
            all_jacobians = []

            for num, origin_B_grasp in enumerate(self.origin_B_grasps):
                pr2_B_grasp = origin_B_pr2.I * origin_B_grasp
                single_goal_sols, single_goal_jacobians = self.ik_request(pr2_B_grasp, z)
                all_sols.append(list(single_goal_sols))
                all_jacobians.append(list(single_goal_jacobians))

            graph = SimpleGraph()
            graph.edges['start'] = []
            graph.value['start'] = 0
            graph.edges['end'] = []
            graph.value['end'] = 0
            for goal_i in xrange(len(all_sols)):
                for sol_i in xrange(len(all_sols[goal_i])):
                    v = self.robot.q
                    v[self.robot_arm[0] + '_shoulder_pan_joint'] = all_sols[goal_i][sol_i][0]
                    v[self.robot_arm[0] + '_shoulder_lift_joint'] = all_sols[goal_i][sol_i][1]
                    v[self.robot_arm[0] + '_upper_arm_roll_joint'] = all_sols[goal_i][sol_i][2]
                    v[self.robot_arm[0] + '_elbow_flex_joint'] = all_sols[goal_i][sol_i][3]
                    v[self.robot_arm[0] + '_forearm_roll_joint'] = all_sols[goal_i][sol_i][4]
                    v[self.robot_arm[0] + '_wrist_flex_joint'] = all_sols[goal_i][sol_i][5]
                    v[self.robot_arm[0] + '_wrist_roll_joint'] = all_sols[goal_i][sol_i][6]
                    self.robot.set_positions(v)
                    self.dart_world.set_gown([self.robot_arm])
                    if not self.is_dart_in_collision():
                        graph.edges[str(goal_i)+'-'+str(sol_i)] = []
                        J = np.matrix(all_jacobians[goal_i][sol_i])
                        joint_limit_weight = self.gen_joint_limit_weight(all_sols[goal_i][sol_i], self.robot_arm)
                        manip = (m.pow(np.linalg.det(J * joint_limit_weight * J.T), (1. / 6.))) / (np.trace(J * joint_limit_weight * J.T) / 6.)
                        graph.value[str(goal_i)+'-'+str(sol_i)] = manip
            # print sorted(graph.edges)
            for node in graph.edges.keys():
                if not node == 'start' and not node == 'end':
                    goal_i = int(node.split('-')[0])
                    sol_i = int(node.split('-')[1])
                    if goal_i == 0:
                        graph.edges['start'].append(str(goal_i)+'-'+str(sol_i))
                    if goal_i == len(all_sols) - 1:
                        graph.edges[str(goal_i)+'-'+str(sol_i)].append('end')
                    else:
                        possible_next_nodes = [t for t in (a
                                                           for a in graph.edges.keys())
                                               if str(goal_i+1) in t.split('-')[0]
                                               ]
                        for next_node in possible_next_nodes:
                            goal_j = int(next_node.split('-')[0])
                            sol_j = int(next_node.split('-')[1])
                            if np.max(np.abs(np.array(all_sols[goal_j][sol_j])[[0,1,2,3,5]]-np.array(all_sols[goal_i][sol_i])[[0,1,2,3,5]])) < m.radians(40.):
                                # if self.path_is_clear(np.array(all_sols[goal_j][sol_j]), np.array(all_sols[goal_i][sol_i])):
                                graph.edges[str(goal_i)+'-'+str(sol_i)].append(str(goal_j)+'-'+str(sol_j))

            path_confirmation_complete = False
            while not path_confirmation_complete:
                came_from, value_so_far = a_star_search(graph, 'start', 'end')
                path = reconstruct_path(came_from, 'start', 'end')
                # print 'came_from\n', came_from
                # print sorted(graph.edges)
                # print 'path\n', path
                if not path:
                    path_confirmation_complete = True
                    if len(value_so_far) == 1:
                        reach_score = 0.
                        manip_score = 0.
                    else:
                        value_so_far.pop('start')
                        furthest_reached = np.argmax([t for t in ((int(a[0].split('-')[0]))
                                                                    for a in value_so_far.items())
                                                     ])
                        # print value_so_far.keys()
                        # print 'furthest reached', furthest_reached
                        # print value_so_far.items()[furthest_reached]
                        reach_score = 1.*int(value_so_far.items()[furthest_reached][0].split('-')[0])/len(self.origin_B_grasps)
                        manip_score = 1.*value_so_far.items()[furthest_reached][1]/len(self.origin_B_grasps)
                else:
                    path_confirmation_complete = True
                    # print 'I FOUND A SOLUTION'
                    # print 'value_so_far[end]:', value_so_far['end']
                    path.pop(0)
                    path.pop(path.index('end'))

                    # Go through the solution and remove edges that are invalid. Then recalculate the path.
                    if False:
                        print 'path\n', path
                        for node_i in xrange(len(path)-1):
                            goal_i = node_i
                            sol_i = int(path[goal_i].split('-')[1])
                            goal_j = node_i+1
                            sol_j = int(path[goal_j].split('-')[1])
                            if not self.path_is_clear(np.array(all_sols[goal_j][sol_j]),
                                                      np.array(all_sols[goal_i][sol_i])):
                                graph.edges[str(goal_i)+'-'+str(sol_i)].pop(graph.edges[str(goal_i)+'-'+str(sol_i)].index(str(goal_j)+'-'+str(sol_j)))
                                path_confirmation_complete = False
                                print 'The path I wanted had a collision. Redoing path.'
                    reach_score = 1.
                    manip_score = value_so_far['end']/len(self.origin_B_grasps)

            if self.visualize or (not self.subtask_step == 0 and False):
                if path:
                    goal_i = int(path[0].split('-')[0])
                    sol_i = int(path[0].split('-')[1])
                    prev_sol = np.array(all_sols[goal_i][sol_i])
                    print 'Solution being visualized:'
                for path_step in path:
                    # if not path_step == 'start' and not path_step == 'end':
                    goal_i = int(path_step.split('-')[0])
                    sol_i = int(path_step.split('-')[1])
                    print 'solution:\n', all_sols[goal_i][sol_i]
                    print 'diff:\n', np.abs(np.array(all_sols[goal_i][sol_i]) - prev_sol)
                    print 'max diff:\n', np.degrees(np.max(np.abs(np.array(all_sols[goal_i][sol_i])[[0,1,2,3,5]] - prev_sol[[0,1,2,3,5]])))
                    prev_sol = np.array(all_sols[goal_i][sol_i])

                    v = self.robot.q
                    v[self.robot_arm[0] + '_shoulder_pan_joint'] = all_sols[goal_i][sol_i][0]
                    v[self.robot_arm[0] + '_shoulder_lift_joint'] = all_sols[goal_i][sol_i][1]
                    v[self.robot_arm[0] + '_upper_arm_roll_joint'] = all_sols[goal_i][sol_i][2]
                    v[self.robot_arm[0] + '_elbow_flex_joint'] = all_sols[goal_i][sol_i][3]
                    v[self.robot_arm[0] + '_forearm_roll_joint'] = all_sols[goal_i][sol_i][4]
                    v[self.robot_arm[0] + '_wrist_flex_joint'] = all_sols[goal_i][sol_i][5]
                    v[self.robot_arm[0] + '_wrist_roll_joint'] = all_sols[goal_i][sol_i][6]
                    self.robot.set_positions(v)
                    self.dart_world.displace_gown()
                    self.dart_world.check_collision()
                    self.dart_world.set_gown([self.robot_arm])
                    rospy.sleep(1.5)
                    # rospy.sleep(0.1)
        else:
            # print 'In base collision! single config distance: ', distance
            if distance < 2.0:
                this_pr2_score = 10. + 1. + (1.25 - distance)
                return this_pr2_score

        # self.human_model.SetActiveManipulator('leftarm')
        # self.human_manip = self.robot.GetActiveManipulator()
        # human_torques = self.human_manip.ComputeInverseDynamics([])
        # torque_cost = np.linalg.norm(human_torques)/10.

        # angle_cost = np.sum(np.abs(human_dof))
        # print 'len(self.goals)'
        # print len(self.goals)

        # print 'reached'
        # print reached

        # reach_score /= len(self.goals)
        # manip_score /= len(self.goals)

        # print 'reach_score'
        # print reach_score
        # print 'manip_score'
        # print manip_score

        # Set the weights for the different scores.
        beta = 10.  # Weight on number of reachable goals
        gamma = 1.  # Weight on manipulability of arm at each reachable goal
        zeta = 0.05  # Weight on torques
        if reach_score == 0.:
            this_pr2_score = 10. + 1.+ 2*random.random()
            return this_pr2_score
        else:
            # print 'Reach score: ', reach_score
            # print 'Manip score: ', manip_score
            if reach_score == 1.:
                if self.visualize:
                    # rospy.sleep(2.0)
                    rospy.sleep(0.1)
            # print 'reach_score:', reach_score
            # print 'manip_score:', manip_score
            this_pr2_score = 10.-beta*reach_score-gamma*manip_score #+ zeta*angle_cost
            return this_pr2_score

    def is_dart_base_in_collision(self):
        self.dart_world.check_collision()
        for contact in self.dart_world.collision_result.contacts:
            if ((self.robot == contact.skel1 or self.robot == contact.skel2) and
                    (self.robot.bodynode('base_link') == contact.bodynode1
                     or self.robot.bodynode('base_link') == contact.bodynode2)):
                return True
        return False

    def is_dart_in_collision(self):
        self.dart_world.check_collision()
        # collided_bodies = self.dart_world.collision_result.contacted_bodies
        for contact in self.dart_world.collision_result.contacts:
            if ((self.robot == contact.skel1 or self.robot == contact.skel2) and
                    (self.human == contact.skel1 or self.human == contact.skel2)) or \
                    ((self.robot == contact.skel1 or self.robot == contact.skel2) and
                         (self.gown_leftarm == contact.skel1 or self.gown_leftarm == contact.skel2)) or \
                    ((self.robot == contact.skel1 or self.robot == contact.skel2) and
                         (self.gown_rightarm == contact.skel1 or self.gown_rightarm == contact.skel2)):
                return True
        return False

    def path_is_clear(self, jc1, jc2):
        for j_i in np.linspace(0., 1., 5)[1:-1]:
            jc = jc1+(jc2-jc1)*j_i
            v = self.robot.q
            v[self.robot_arm[0] + '_shoulder_pan_joint'] = jc[0]
            v[self.robot_arm[0] + '_shoulder_lift_joint'] = jc[1]
            v[self.robot_arm[0] + '_upper_arm_roll_joint'] = jc[2]
            v[self.robot_arm[0] + '_elbow_flex_joint'] = jc[3]
            v[self.robot_arm[0] + '_forearm_roll_joint'] = jc[4]
            v[self.robot_arm[0] + '_wrist_flex_joint'] = jc[5]
            v[self.robot_arm[0] + '_wrist_roll_joint'] = jc[6]
            self.robot.set_positions(v)
            self.dart_world.set_gown([self.robot_arm])
            if self.visualize:
                rospy.sleep(0.5)
            if self.is_dart_in_collision():
                return False
        return True

    def is_human_in_self_collision(self):
        self.dart_world.human.set_self_collision_check(True)
        self.dart_world.check_collision()
        arm = self.human_arm.split('a')[0]
        arm_parts = [self.human.bodynode('h_bicep_'+arm),
                     self.human.bodynode('h_forearm_'+arm),
                     self.human.bodynode('h_hand_'+arm),
                     self.human.bodynode('h_hand_'+arm+'2')]
        for contact in self.dart_world.collision_result.contacts:
            contacts = [contact.bodynode1, contact.bodynode2]
            for arm_part in arm_parts:
                if arm_part in contacts and self.human == contact.skel1 and self.human == contact.skel2:
                    contacts.remove(arm_part)
                    if contacts:
                        if contacts[0] not in arm_parts and not contacts[0] == self.human.bodynode('h_scapula_'+arm):
                            return True
        self.human.set_self_collision_check(False)
        return False

    def visualize_dart(self):
        win = pydart.gui.viewer.PydartWindow(self.dart_world)
        win.camera_event(1)
        win.set_capture_rate(10)
        win.run_application()

    def setup_openrave(self):
        # Setup Openrave ENV
        op.RaveSetDebugLevel(op.DebugLevel.Error)
        InitOpenRAVELogging()
        self.env = op.Environment()

        self.check_self_collision = True

        # if self.visualize:
        #     self.env.SetViewer('qtcoin')

        self.env.Load('robots/pr2-beta-static.zae')
        self.op_robot = self.env.GetRobots()[0]
        self.op_robot.CheckLimitsAction = 2

        robot_start = np.matrix([[m.cos(0.), -m.sin(0.), 0., 0.],
                                 [m.sin(0.), m.cos(0.), 0., 0.],
                                 [0., 0., 1., 0.],
                                 [0., 0., 0., 1.]])
        self.op_robot.SetTransform(np.array(robot_start))

        self.goal_B_gripper = np.matrix([[0., 0., 1., 0.0],
                                         [0., 1., 0., 0.0],
                                         [-1., 0., 0., 0.0],
                                         [0., 0., 0., 1.0]])

        self.gripper_B_tool = np.matrix([[0., -1., 0., 0.03],
                                         [1., 0., 0., 0.0],
                                         [0., 0., 1., -0.05],
                                         [0., 0., 0., 1.0]])

        self.origin_B_grasp = None

        # self.set_openrave_arm(self.robot_opposite_arm)
        # self.set_openrave_arm(self.robot_arm)
        print 'Openrave IK is now ready'

    def setup_ik_service(self):
        print 'Looking for IK service.'
        rospy.wait_for_service('ikfast_service')
        print 'Found IK service.'
        self.ik_service = rospy.ServiceProxy('ikfast_service', IKService, persistent=True)
        print 'IK service is ready for use!'

    def ik_request(self, pr2_B_grasp, spine_height):
        with self.frame_lock:
            jacobians = []
            with self.env:
                v = self.op_robot.GetActiveDOFValues()
                v[self.op_robot.GetJoint('l_shoulder_pan_joint').GetDOFIndex()] = 3.14 / 2
                v[self.op_robot.GetJoint('l_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.op_robot.GetJoint('l_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.op_robot.GetJoint('l_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.op_robot.GetJoint('l_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.op_robot.GetJoint('l_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.op_robot.GetJoint('l_wrist_roll_joint').GetDOFIndex()] = 0.
                v[self.op_robot.GetJoint('r_shoulder_pan_joint').GetDOFIndex()] = -3.14 / 2
                v[self.op_robot.GetJoint('r_shoulder_lift_joint').GetDOFIndex()] = -0.52
                v[self.op_robot.GetJoint('r_upper_arm_roll_joint').GetDOFIndex()] = 0.
                v[self.op_robot.GetJoint('r_elbow_flex_joint').GetDOFIndex()] = -3.14 * 2 / 3
                v[self.op_robot.GetJoint('r_forearm_roll_joint').GetDOFIndex()] = 0.
                v[self.op_robot.GetJoint('r_wrist_flex_joint').GetDOFIndex()] = 0.
                v[self.op_robot.GetJoint('r_wrist_roll_joint').GetDOFIndex()] = 0.
                v[self.op_robot.GetJoint('torso_lift_joint').GetDOFIndex()] = spine_height
                self.op_robot.SetActiveDOFValues(v, checklimits=2)
                self.env.UpdatePublishedBodies()

                # base_footprint_B_tool_goal = createBMatrix(goal_position, goal_orientation)

                origin_B_grasp = np.array(np.matrix(pr2_B_grasp)*self.goal_B_gripper)  # * self.gripper_B_tool.I * self.goal_B_gripper)
                # print 'here'
                # print self.origin_B_grasp
                # sols = self.manip.FindIKSolutions(self.origin_B_grasp,4)
                # init_time = rospy.Time.now()
                if self.check_self_collision:
                    sols = self.manip.FindIKSolutions(origin_B_grasp, filteroptions=op.IkFilterOptions.CheckEnvCollisions)
                else:
                    sols = self.manip.FindIKSolutions(origin_B_grasp, filteroptions=op.IkFilterOptions.IgnoreSelfCollisions)
                if list(sols):
                    with self.op_robot:
                        for sol in sols:
                            # self.robot.SetDOFValues(sol, self.manip.GetArmIndices(), checklimits=2)
                            self.op_robot.SetDOFValues(sol, self.manip.GetArmIndices())
                            self.env.UpdatePublishedBodies()
                            jacobians.append(np.vstack([self.manip.CalculateJacobian(), self.manip.CalculateAngularVelocityJacobian()]))
                            # if self.visualize:
                            #     rospy.sleep(1.5)
                    # print jacobians[0]
                    return sols, jacobians
                else:
                    return [], []

    def call_ik_service(self, Bmat, pr2_height):
        pos, quat = Bmat_to_pos_quat(Bmat)
        return self.ik_service(pos, quat, pr2_height, self.robot_arm)

    def check_smooth_ik_feasiblity(self, goal_poses):

        max_joint_change = 1.0
        feasible_ik = True
        return feasible_ik, max_joint_change

    def set_human_model_dof_dart(self, dof, human_arm):
        # bth = m.degrees(headrest_th)
        if not len(dof) == 4:
            print 'There should be exactly 4 values used for arm configuration. Three for the shoulder and one for ' \
                  'the elbow. But instead ' + str(len(dof)) + 'was sent. This is a ' \
                                                              'problem!'
            return False

        q = self.human.q
        # print 'human_arm', human_arm
        # j_bicep_left_x,y,z are euler angles applied in xyz order. x is forward, y is opposite direction of
        # upper arm, z is to the right.
        # j_forearm_left_1 is bend in elbow.
        if human_arm == 'leftarm':
            q['j_bicep_left_x'] = dof[0]
            q['j_bicep_left_y'] = -1*dof[1]
            q['j_bicep_left_z'] = dof[2]
            # q['j_bicep_left_roll'] = -1*0.
            q['j_forearm_left_1'] = dof[3]
            q['j_forearm_left_2'] = 0.
        elif human_arm == 'rightarm':
            q['j_bicep_right_x'] = -1*dof[0]
            q['j_bicep_right_y'] = dof[1]
            q['j_bicep_right_z'] = dof[2]
            # q['j_bicep_right_roll'] = 0.
            q['j_forearm_right_1'] = dof[3]
            q['j_forearm_right_2'] = 0.
        else:
            print 'I am not sure what arm to set the dof for.'
            return False
        self.human.set_positions(q)

    def get_best_traj_offset(self):
        return 0.0, 0.1

    def gen_joint_limit_weight(self, q, side):
        # define the total range limit for each joint
        if 'left' in side:
            joint_min = np.array([-40., -30., -44., -133., -400., -130., -400.])
            joint_max = np.array([130., 80., 224., 0., 400., 0., 400.])
        elif 'right' in side:
            # print 'Need to check the joint limits for the right arm'
            joint_min = np.array([-130., -30., -224., -133., -400., -130., -400.])
            joint_max = np.array([40., 80., 44., 0., 400., 0., 400.])
        joint_range = joint_max - joint_min
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
            weights[joint] = (1. - m.pow(0.5, ((joint_range[joint])/2. - np.abs((joint_range[joint])/2. - m.degrees(q[joint]) + joint_min[joint]))/(joint_range[joint]/40.)+1.))
        weights[4] = 1.
        weights[6] = 1.
        return np.diag(weights)

if __name__ == "__main__":
    rospy.init_node('score_generator')
    # start_time = time.time()
    outer_start_time = rospy.Time.now()

    pydart.init()
    print('pydart initialization OK')

    filename = 'fullbody_alex_capsule.skel'
    rospack = rospkg.RosPack()
    pkg_path = rospack.get_path('hrl_base_selection')
    skel_file = pkg_path + '/models/' + filename

    testSimulator = SIMULATOR(skel_file)
    testSimulator = SIMULATOR()

    joint_max = testSimulator.controller.joint_max
    joint_min = testSimulator.controller.joint_min
    phi = testSimulator.controller.phi

    x0 = np.concatenate((joint_max, joint_min, phi))

    lb, hb = setBoundary(len(x0), 0, np.pi / 3, -np.pi / 3, 0, -np.pi, np.pi)
    OPTIONS['boundary_handling'] = cma.BoundTransform
    OPTIONS['bounds'] = [lb, hb]

    selector = ScoreGeneratorDressingMultithread(human_arm='rightarm', visualize=False)
    # selector.visualize_many_configurations()
    # selector.output_results_for_use()
    # selector.run_interleaving_optimization_outer_level()
    selector.optimize_entire_dressing_task(reset_file=False)
    outer_elapsed_time = rospy.Time.now()-outer_start_time
    print 'Everything is complete!'
    print 'Done with optimization. Total time elapsed:', outer_elapsed_time.to_sec()
    # rospy.spin()

    #selector.choose_task(mytask)
    # score_sheet = selector.handle_score_generation()

    # print 'Time to load find generate all scores: %fs'%(time.time()-start_time)

    # rospack = rospkg.RosPack()
    # pkg_path = rospack.get_path('hrl_base_selection')
    # save_pickle(score_sheet, ''.join([pkg_path, '/data/', mymodel, '_', mytask, '.pkl']))
    # print 'Time to complete program, saving all data: %fs' % (time.time()-start_time)





