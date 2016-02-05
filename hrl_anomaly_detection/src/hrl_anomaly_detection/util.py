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

# system
import rospy, roslib
import os, sys, copy

# util
import numpy as np
import hrl_lib.util as ut
import hrl_lib.quaternion as qt
from pykdl_utils.kdl_kinematics import create_kdl_kin

from scipy import interpolate
from sklearn.decomposition import PCA

import matplotlib
## matplotlib.use('pdf')
import matplotlib.pyplot as plt
## import data_viz

def extrapolateData(data, maxsize):
    if len(np.shape(data[0])) > 1:     
        # need to implement incremental extrapolation
        return [x if len(x[0]) >= maxsize else x + [x[:,-1]]*(maxsize-len(x[0])) for x in data]
    else:
        # need to implement incremental extrapolation        
        return [x if len(x) >= maxsize else x + [x[-1]]*(maxsize-len(x)) for x in data]
        

def loadData(fileNames, isTrainingData=False, downSampleSize=100, local_range=0.3, rf_center='kinEEPos', \
             global_data=False, verbose=False, renew=True, save_pkl=None, plot_data=False):

    if save_pkl is not None:
        if os.path.isfile(save_pkl+'_raw.pkl') is True and os.path.isfile(save_pkl+'_interp.pkl') is True \
          and renew is not True:
            print "Load stored data, ", save_pkl
            raw_data_dict = ut.load_pickle(save_pkl+'_raw.pkl')
            data_dict = ut.load_pickle(save_pkl+'_interp.pkl')
            return raw_data_dict, data_dict

    key_list = ['timesList', 'fileNameList',\
                'audioTimesList', 'audioAzimuthList', 'audioPowerList',\
                'audioWristTimesList', 'audioWristRMSList', \
                'kinTimesList', 'kinEEPosList', 'kinEEQuatList', 'kinJntPosList', 'kinTargetPosList', \
                'kinTargetQuatList', 'kinPosList', 'kinVelList',\
                'ftTimesList', 'ftForceList', \
                'visionArtagTimesList', 'visionArtagPosList', 'visionArtagQuatList', \
                'visionChangeTimesList', 'visionChangeCentersList', 'visionChangeMagList', \
                'ppsTimesList', 'ppsLeftList', 'ppsRightList',\
                'fabricTimesList', 'fabricCenterList', 'fabricNormalList', 'fabricValueList', 'fabricMagList' ]

    raw_data_dict = {}
    data_dict = {}
    data_dict['timesList'] = []
    for key in key_list:
        raw_data_dict[key] = []
        if 'time' not in key:
            data_dict[key]  = []

    # check data to get maximum time limit
    max_time = 0
    for idx, fileName in enumerate(fileNames):
        if os.path.isdir(fileName):
            continue
        d = ut.load_pickle(fileName)        
        init_time = d['init_time']
        for key in d.keys():
            if 'time' in key and 'init' not in key:
                feature_time = d[key]
                if max_time < feature_time[-1]-init_time: max_time = feature_time[-1]-init_time
    new_times = np.linspace(0.01, max_time, downSampleSize)
     
            
    for idx, fileName in enumerate(fileNames):
        if os.path.isdir(fileName):
            continue

        ## cause = os.path.split(fileName)[1].split('_')[3:]
        ## description = ''
        ## if cause is list:
        ##     for c in cause:
        ##         description += c
        raw_data_dict['fileNameList'].append(fileName)
        data_dict['fileNameList'].append(fileName)        

        # Load raw data
        if verbose: print fileName
        d = ut.load_pickle(fileName)        
        init_time = d['init_time']

        ## max_time = 0
        ## for key in d.keys():
        ##     if 'time' in key and 'init' not in key:
        ##         feature_time = d[key]
        ##         if max_time < feature_time[-1]-init_time: max_time = feature_time[-1]-init_time
        ## new_times = np.linspace(0.01, max_time, downSampleSize)

        data_dict['timesList'].append(new_times)

        # Define receptive field center trajectory ---------------------------
        rf_time = np.array(d['kinematics_time']) - init_time
        if rf_center == 'kinEEPos':
            rf_traj = d['kinematics_ee_pos']
        elif rf_center == 'kinForearmPos':
            kin_jnt_pos = d['kinematics_jnt_pos'] # 7xN

            # Forearm
            rf_traj = None
            arm_kdl = create_kdl_kin('torso_lift_link', 'l_gripper_tool_frame')
            for i in xrange(len(kin_jnt_pos[0])):
                mPose1 = arm_kdl.forward(kin_jnt_pos[:,i], end_link='l_forearm_link', \
                                         base_link='torso_lift_link')
                mPose2 = arm_kdl.forward(kin_jnt_pos[:,i], end_link='l_wrist_flex_link', \
                                         base_link='torso_lift_link')
                if rf_traj is None: rf_traj = (np.array(mPose1[:3,3])+np.array(mPose2[:3,3]))/2.0
                else: rf_traj = np.hstack([ rf_traj, (np.array(mPose1[:3,3])+np.array(mPose2[:3,3]))/2.0 ])
        ## elif rf_center == 'l_upper_arm_link':            
        else:
            print "No specified rf center"
            sys.exit()

        # check length of trajectory.
        if len(rf_time) != len(rf_traj[0]):
            rf_time = rf_time[:min(len(rf_time), len(rf_traj[0]))]
            rf_traj = rf_traj[:, :min(len(rf_time), len(rf_traj[0]))]

        if verbose: print "rf_traj: ", np.shape(rf_traj) 

        print d.keys()

        # kinect sound ----------------------------------------------------------------
        if 'audio_time' in d.keys():
            audio_time    = (np.array(d['audio_time']) - init_time).tolist()
            audio_azimuth = d['audio_azimuth']
            audio_power   = np.abs(d['audio_power'])

            # get noise
            noise_power = 0.0 #26.0 #np.mean(audio_power[:100])
            audio_azimuth_margin = 15.0

            ang_max_l = []
            ang_min_l = []
            # extract local feature
            local_audio_power = []
            for time_idx in xrange(len(audio_time)):

                rf_time_idx = np.abs(rf_time - audio_time[time_idx]).argmin()                
                ang_max, ang_min = getAngularSpatialRF(rf_traj[:,rf_time_idx], local_range)

                ang_max_l.append(ang_max)
                ang_min_l.append(ang_min)

                if (audio_azimuth[time_idx] > ang_min-audio_azimuth_margin and \
                  audio_azimuth[time_idx] < ang_max+audio_azimuth_margin) or global_data:
                    local_audio_power.append(audio_power[time_idx])
                    ## if audio_power[time_idx] > 50: local_audio_power.append(audio_power[time_idx-1])
                    ## else: local_audio_power.append(audio_power[time_idx])
                else:                    
                    local_audio_power.append(noise_power) # or append white noise?

            # Save local raw and interpolated data
            raw_data_dict['audioTimesList'].append(audio_time)
            raw_data_dict['audioAzimuthList'].append(audio_azimuth)
            raw_data_dict['audioPowerList'].append(local_audio_power)

            data_dict['audioAzimuthList'].append(interpolationData(audio_time, audio_azimuth, new_times))
            data_dict['audioPowerList'].append(downSampleAudio(audio_time, local_audio_power, new_times))

            ## plt.plot([min(ang_min_l)], [29.0],'k*',  )
            ## plt.plot([max(ang_max_l)], [29.0],'m*',  )
            
            ## plt.scatter(audio_azimuth, audio_power)
            ## plt.scatter(audio_azimuth, local_audio_power, c='r')
            
            ## fig = plt.figure()
            ## plt.plot(audio_time, audio_power, c='k')
            ## plt.plot(audio_time, local_audio_power, c='b')
            ## plt.plot(new_times, downSampleAudio(audio_time, local_audio_power, new_times), c='r')
            ## fig.savefig('test.pdf')
            ## fig.savefig('test.png')
            ## os.system('cp test.p* ~/Dropbox/HRL/')
            ## sys.exit()
            ## ut.get_keystroke('Hit a key to proceed next')

        # wrist sound ----------------------------------------------------------------
        if 'audio_wrist_time' in d.keys():
            audio_time = (np.array(d['audio_wrist_time']) - init_time).tolist()
            audio_rms  = np.abs(d['audio_wrist_rms'])
            audio_mfcc = np.abs(d['audio_wrist_mfcc'])

            # Save local raw and interpolated data
            raw_data_dict['audioWristTimesList'].append(audio_time)
            raw_data_dict['audioWristRMSList'].append(audio_rms)

            data_dict['audioWristRMSList'].append(downSampleAudio(audio_time, audio_rms, new_times))

            
        # kinematics -----------------------------------------------------------
        if 'kinematics_time' in d.keys():
            kin_time        = (np.array(d['kinematics_time']) - init_time).tolist()
            kin_ee_pos      = d['kinematics_ee_pos'] # 3xN
            kin_ee_quat     = d['kinematics_ee_quat'] # ?xN
            kin_target_pos  = d['kinematics_target_pos']
            kin_target_quat = d['kinematics_target_quat']
            kin_jnt_pos     = d['kinematics_jnt_pos'] # 7xN

            # local kinematics feature
            if rf_center == 'kinEEPos':
                local_kin_pos = kin_ee_pos
                last_kin_pos = np.zeros((3,1))
                last_time    = 0.0
                local_kin_vel= None
                for i in xrange(len(kin_ee_pos[0])):
                    if abs(kin_time[i]-last_time) < 0.00000001:
                        if local_kin_vel is None: local_kin_vel = np.zeros((3,1))
                    else:                    
                        local_kin_vel = (kin_ee_pos[:,i:i+1] - last_kin_pos)/(kin_time[i] - last_time)
                    last_kin_pos = kin_ee_pos[:,i:i+1]
                    last_time    = kin_time[i]

            else:
                if rf_center == 'kinForearmPos':
                    frame_list = ['l_forearm_link', 'l_wrist_flex_link']
                else:
                    print "Not implemented RF center"
                    sys.exit()
                    
                local_kin_pos = None
                local_kin_vel = None
                last_mPose      = None
                last_time       = 0.0
                arm_kdl = create_kdl_kin('torso_lift_link', 'l_gripper_tool_frame')
                for i in xrange(len(kin_jnt_pos[0])):
                    mPose1 = arm_kdl.forward(kin_jnt_pos[:,i], end_link=frame_list[0], base_link='torso_lift_link')
                    mPose2 = arm_kdl.forward(kin_jnt_pos[:,i], end_link=frame_list[1], base_link='torso_lift_link')
                    mPose  = np.array((mPose1[:3,3]+mPose2[:3,3])/2.0)
                    if local_kin_pos is None: local_kin_pos = mPose
                    else: local_kin_pos = np.hstack([ local_kin_pos, mPose ])

                    if last_mPose is None:
                        last_mPose = mPose
                        last_time  = 0.0


                    if abs(kin_time[i]-last_time) < 0.00000001:
                        if local_kin_vel is not None: vel = local_kin_vel[:,-1:]
                        else: vel = np.zeros((3,1))
                    else:
                        vel = (mPose-last_mPose)/(kin_time[i]-last_time)

                    # to avoid inf values
                    if np.isinf(np.max(vel)):
                        if local_kin_vel is not None: vel = local_kin_vel[:,-1:]
                        else: vel = np.zeros((3,1))
                        
                    if local_kin_vel is None: local_kin_vel = vel
                    else: local_kin_vel = np.hstack([ local_kin_vel, vel])
                        
                    last_mPose = mPose
                    last_time  = kin_time[i]

            # Change the sign of quaternion
            

            # extract local feature
            data_set = [kin_time, kin_ee_pos, kin_ee_quat]
            [local_kin_ee_pos, local_kin_ee_quat] = extractLocalData(rf_time, rf_traj, local_range, data_set,\
                                                                     global_data=global_data)
            data_set = [kin_time, kin_target_pos, kin_target_quat]
            [local_kin_target_pos, local_kin_target_quat] = extractLocalData(rf_time, rf_traj, local_range, \
                                                                             data_set, global_data=global_data)
            ## data_set = [kin_time, kin_forearm_pos, kin_forearm_vel]
            ## [local_kin_forearm_pos, local_kin_forearm_vel] = extractLocalData(rf_time, rf_traj, local_range, \
            ##                                                                   data_set, global_data=global_data)

            raw_data_dict['kinTimesList'].append(kin_time)
            raw_data_dict['kinEEPosList'].append(local_kin_ee_pos)
            raw_data_dict['kinEEQuatList'].append(local_kin_ee_quat)
            raw_data_dict['kinTargetPosList'].append(local_kin_target_pos)
            raw_data_dict['kinTargetQuatList'].append(local_kin_target_quat)
            raw_data_dict['kinJntPosList'].append(kin_jnt_pos)
            raw_data_dict['kinPosList'].append(local_kin_pos)
            raw_data_dict['kinVelList'].append(local_kin_vel)

            data_dict['kinEEPosList'].append(interpolationData(kin_time, local_kin_ee_pos, new_times))
            data_dict['kinEEQuatList'].append(interpolationData(kin_time, local_kin_ee_quat, new_times, True))
            data_dict['kinTargetPosList'].append(interpolationData(kin_time, local_kin_target_pos, new_times))
            data_dict['kinTargetQuatList'].append(interpolationData(kin_time, local_kin_target_quat, \
                                                                    new_times, True))
            data_dict['kinJntPosList'].append(interpolationData(kin_time, kin_jnt_pos, new_times))
            data_dict['kinPosList'].append(interpolationData(kin_time, local_kin_pos, new_times))
            data_dict['kinVelList'].append(interpolationData(kin_time, local_kin_vel, new_times))

            ## fig = plt.figure()
            ## plt.plot(kin_time, kin_target_pos[2], c='k')
            ## plt.plot(kin_time, local_kin_target_pos[2], c='b')
            ## plt.plot(new_times, interpolationData(kin_time, local_kin_target_pos, new_times)[2], c='r')
            ## fig.savefig('test.pdf')
            ## fig.savefig('test.png')
            ## os.system('cp test.p* ~/Dropbox/HRL/')
            ## sys.exit()


        # ft -------------------------------------------------------------------
        if 'ft_time' in d.keys():
            ft_time  = (np.array(d['ft_time']) - init_time).tolist()
            ft_force = d['ft_force']

            kin_time   = (np.array(d['kinematics_time']) - init_time).tolist()
            kin_ee_pos = d['kinematics_ee_pos'] # 3xN
            ft_pos     = interpolationData(kin_time, kin_ee_pos, ft_time)
           
            # extract local feature
            data_set = [ft_time, ft_pos, ft_force]
            [ _, local_ft_force] = extractLocalData(rf_time, rf_traj, local_range, data_set)

            raw_data_dict['ftTimesList'].append(ft_time)
            raw_data_dict['ftForceList'].append(local_ft_force)

            force_array = interpolationData(ft_time, local_ft_force, new_times)
            data_dict['ftForceList'].append(force_array)                                         

            ## fig = plt.figure()
            ## plt.plot(ft_time, ft_force[2], c='k')
            ## plt.plot(ft_time, local_ft_force[2], c='b')
            ## plt.plot(new_times, interpolationData(ft_time, local_ft_force, new_times)[2], c='r')
            ## ## fig.savefig('test.pdf')
            ## ## fig.savefig('test.png')
            ## ## os.system('cp test.p* ~/Dropbox/HRL/')
            ## plt.show()
            ## sys.exit()
            
                    
        # vision artag -------------------------------------------------------------
        if 'vision_artag_time' in d.keys():
            vision_time = (np.array(d['vision_artag_time']) - init_time).tolist()
            vision_pos  = d['vision_artag_pos'] # timeLength x 3*tags
            vision_quat = d['vision_artag_quat']

            if vision_time[-1] < new_times[0] or vision_time[0] > new_times[-1]:
                vision_time = np.linspace(new_times[0], new_times[-1], len(vision_time))

            # extract local feature
            data_set = [vision_time, vision_pos, vision_quat]
            [ local_vision_pos, local_vision_quat] = extractLocalData(rf_time, rf_traj, local_range, data_set)

            raw_data_dict['visionArtagTimesList'].append(vision_time)
            raw_data_dict['visionArtagPosList'].append(local_vision_pos)
            raw_data_dict['visionArtagQuatList'].append(local_vision_quat)

            vision_pos_array  = interpolationData(vision_time, local_vision_pos, new_times)
            data_dict['visionArtagPosList'].append(vision_pos_array)                                         

            ## fig = plt.figure()
            ## plt.plot(vision_time, vision_pos[2], c='k')
            ## plt.plot(vision_time, local_vision_pos[2], c='b')
            ## plt.plot(new_times, interpolationData(vision_time, local_vision_pos, new_times)[2], c='r')
            ## fig.savefig('test.pdf')
            ## fig.savefig('test.png')
            ## os.system('cp test.p* ~/Dropbox/HRL/')
            ## sys.exit()

        # vision change -----------------------------------------------------------
        if 'vision_change_time' in d.keys():
            vision_time = (np.array(d['vision_change_time']) - init_time).tolist()
            vision_centers_x  = d['vision_change_centers_x']
            vision_centers_y  = d['vision_change_centers_y']
            vision_centers_z  = d['vision_change_centers_z']

            vision_centers = np.array([vision_centers_x, vision_centers_y, vision_centers_z])

            if vision_time[-1] < new_times[0] or vision_time[0] > new_times[-1]:
                vision_time = np.linspace(new_times[0], new_times[-1], len(vision_time))

            # extract local feature
            data_set = [vision_time, vision_centers]
            [ local_centers ] = extractLocalData(rf_time, rf_traj, local_range, data_set, multi_pos_flag=True)

            # Get magnitudes
            local_change_mag = []
            for i in xrange(len(vision_time)):
                local_change_mag.append( len(local_centers[0][i]) )

            raw_data_dict['visionChangeTimesList'].append(vision_time)
            raw_data_dict['visionChangeCentersList'].append(local_centers)
            raw_data_dict['visionChangeMagList'].append(local_change_mag)

            mag_array  = interpolationData(vision_time, local_change_mag, new_times)
            data_dict['visionChangeMagList'].append(mag_array)                                        


        # pps ------------------------------------------------------------------
        if 'pps_skin_time' in d.keys():
            pps_skin_time  = (np.array(d['pps_skin_time']) - init_time).tolist()
            pps_skin_left  = d['pps_skin_left']
            pps_skin_right = d['pps_skin_right']

            kin_time       = (np.array(d['kinematics_time']) - init_time).tolist()
            kin_target_pos = d['kinematics_target_pos'] # 3xN  # not precise
            pps_skin_pos   = interpolationData(kin_time, kin_target_pos, pps_skin_time)

            # extract local feature
            data_set = [pps_skin_time, pps_skin_pos, pps_skin_left, pps_skin_right]
            [ _, local_pps_skin_left, local_pps_skin_right] = extractLocalData(rf_time, rf_traj, local_range, data_set)

            raw_data_dict['ppsTimesList'].append(pps_skin_time)
            raw_data_dict['ppsLeftList'].append(local_pps_skin_left)
            raw_data_dict['ppsRightList'].append(local_pps_skin_right)

            left_array = interpolationData(pps_skin_time, local_pps_skin_left, new_times)
            data_dict['ppsLeftList'].append(left_array)
            right_array = interpolationData(pps_skin_time, local_pps_skin_right, new_times)
            data_dict['ppsRightList'].append(right_array)

            ## fig = plt.figure()
            ## plt.plot(pps_skin_time, pps_skin_left[2], c='k')
            ## plt.plot(pps_skin_time, local_pps_skin_left[2], c='b')
            ## plt.plot(new_times, interpolationData(pps_skin_time, local_pps_skin_left, new_times)[2], c='r')
            ## fig.savefig('test.pdf')
            ## fig.savefig('test.png')
            ## os.system('cp test.p* ~/Dropbox/HRL/')
            ## sys.exit()


        # fabric skin ------------------------------------------------------------------
        if 'fabric_skin_time' in d.keys():
            fabric_skin_time      = (np.array(d['fabric_skin_time']) - init_time).tolist()
            fabric_skin_centers_x = d['fabric_skin_centers_x']
            fabric_skin_centers_y = d['fabric_skin_centers_y']
            fabric_skin_centers_z = d['fabric_skin_centers_z']
            fabric_skin_normals_x = d['fabric_skin_normals_x']
            fabric_skin_normals_y = d['fabric_skin_normals_y']
            fabric_skin_normals_z = d['fabric_skin_normals_z']
            fabric_skin_values_x  = d['fabric_skin_values_x']
            fabric_skin_values_y  = d['fabric_skin_values_y']
            fabric_skin_values_z  = d['fabric_skin_values_z']

            fabric_skin_centers = [fabric_skin_centers_x, fabric_skin_centers_y, fabric_skin_centers_z]
            fabric_skin_normals = [fabric_skin_normals_x, fabric_skin_normals_y, fabric_skin_normals_z]
            fabric_skin_values  = [fabric_skin_values_x, fabric_skin_values_y, fabric_skin_values_z]            

            # extract local feature
            data_set = [fabric_skin_time, fabric_skin_centers, fabric_skin_normals, fabric_skin_values]
            [ local_fabric_skin_centers, local_fabric_skin_normals, local_fabric_skin_values] \
              = extractLocalData(rf_time, rf_traj, local_range, data_set, multi_pos_flag=True, \
                                 global_data=global_data)

            # Get magnitudes
            fabric_skin_mag = []
            local_fabric_skin_mag = []
            for i in xrange(len(fabric_skin_time)):
                if fabric_skin_values[0][i] == []: fabric_skin_mag.append(0)
                else:
                    temp = np.array([fabric_skin_values[0][i], fabric_skin_values[1][i], \
                                     fabric_skin_values[2][i] ])
                    try:
                        fabric_skin_mag.append( np.sum( np.linalg.norm(temp, axis=0) ) )
                    except:
                        print "fabric skin message has different length"
                        minIdx = min([len(fabric_skin_values[0][i]), len(fabric_skin_values[1][i]),\
                                      len(fabric_skin_values[2][i])])
                        temp = np.array([fabric_skin_values[0][i][:minIdx], fabric_skin_values[1][i][:minIdx], \
                                         fabric_skin_values[2][i][:minIdx] ])
                        fabric_skin_mag.append( np.sum( np.linalg.norm(temp, axis=0) ) )
                        
                    ## print temp, fabric_skin_mag[-1]

                if local_fabric_skin_values[0][i] == []: local_fabric_skin_mag.append(0)
                else:
                    temp = np.array([local_fabric_skin_values[0][i], \
                                     local_fabric_skin_values[1][i], \
                                     local_fabric_skin_values[2][i] ])
                    local_fabric_skin_mag.append( np.sum( np.linalg.norm(temp, axis=0) ) )
                    ## print temp, fabric_skin_mag[-1]

            # time weighted sum?
            raw_data_dict['fabricTimesList'].append(fabric_skin_time)
            raw_data_dict['fabricCenterList'].append(local_fabric_skin_centers)
            raw_data_dict['fabricNormalList'].append(local_fabric_skin_normals)
            raw_data_dict['fabricValueList'].append(local_fabric_skin_values)
            raw_data_dict['fabricMagList'].append(local_fabric_skin_mag)

            # skin interpolation
            ## center_array, normal_array, value_array \
            ##   = interpolationSkinData(fabric_skin_time, local_fabric_skin_centers,\
            ##                           local_fabric_skin_normals, local_fabric_skin_values, new_times )
            mag_array = interpolationData(fabric_skin_time, local_fabric_skin_mag, new_times)
            data_dict['fabricMagList'].append(mag_array)            
            ## data_dict['fabricCenterList'].append(center_array)
            ## data_dict['fabricNormalList'].append(normal_array)
            ## data_dict['fabricValueList'].append(value_array)

            ## if np.sum(mag_array)>0.5:
            ##     fig = plt.figure()
            ##     plt.plot(fabric_skin_time, fabric_skin_mag, c='k')
            ##     plt.plot(fabric_skin_time, local_fabric_skin_mag, c='b')
            ##     plt.plot(new_times, mag_array, c='r')
            ##     fig.savefig('test.pdf')
            ##     fig.savefig('test.png')
            ##     os.system('cp test.p* ~/Dropbox/HRL/')
            ##     sys.exit()

            
        # ----------------------------------------------------------------------

    # Each iteration may have a different number of time steps, so we extrapolate so they are all consistent
    if isTrainingData:
        # Find the largest iteration
        max_size = max([ len(x) for x in data_dict['timesList'] ])
        # Extrapolate each time step
        for key in data_dict.keys():
            if 'file' in key: continue
            if data_dict[key] == []: continue
            if 'fabric' in key:
                data_dict[key] = [x if len(x) >= max_size else x + []*(max_size-len(x)) for x in data_dict[key]]
            else:                
                data_dict[key] = extrapolateData(data_dict[key], max_size)

    if save_pkl is not None:
        ut.save_pickle(raw_data_dict, save_pkl+'_raw.pkl')
        ut.save_pickle(data_dict, save_pkl+'_interp.pkl')

    return raw_data_dict, data_dict
    
    
def getSubjectFileList(root_path, subject_names, task_name):
    # List up recorded files
    folder_list = [d for d in os.listdir(root_path) if os.path.isdir(os.path.join(root_path,d))]        

    success_list = []
    failure_list = []
    for d in folder_list:

        name_flag = False
        for name in subject_names:
            if d.find(name) >= 0: name_flag = True
                                    
        if name_flag and d.find(task_name) >= 0:
            files = os.listdir(os.path.join(root_path,d))

            for f in files:
                # pickle file name with full path
                pkl_file = os.path.join(root_path,d,f)
                
                if f.find('success') >= 0:
                    if len(success_list)==0: success_list = [pkl_file]
                    else: success_list.append(pkl_file)
                elif f.find('failure') >= 0:
                    if len(failure_list)==0: failure_list = [pkl_file]
                    else: failure_list.append(pkl_file)
                else:
                    print "It's not success/failure file: ", f

    print "--------------------------------------------"
    print "# of Success files: ", len(success_list)
    print "# of Failure files: ", len(failure_list)
    print "--------------------------------------------"
    
    return success_list, failure_list


def downSampleAudio(time_array, data_array, new_time_array):
    '''
    time_array: N - length array
    data_array: D x N - length array
    '''
    from scipy import interpolate

    if len(np.shape(data_array)) == 1: data_array = np.array([data_array])
    if time_array[-1] < new_time_array[0] or time_array[0] > new_time_array[-1]:
        return data_array[:,: len(new_time_array)]

    n,m = np.shape(data_array)    
    if len(time_array) > m: time_array = time_array[0:m]
    

    # remove repeated data
    temp_time_array = [time_array[0]]
    temp_data_array = data_array[:,0:1]
    for i in xrange(1, len(time_array)):        
        if time_array[i-1] != time_array[i]:
            temp_time_array.append(time_array[i])
            temp_data_array = np.hstack([temp_data_array, data_array[:,i:i+1]])
        else:
            if np.linalg.norm(temp_data_array[:,-1]) < np.linalg.norm(data_array[:,i:i+1]):
                temp_data_array[:,-1:] = data_array[:,i:i+1]

    time_array = temp_time_array
    data_array = temp_data_array

    if len(time_array) < 2:
        nDim = len(data_array)
        return np.zeros((nDim,len(new_time_array)))
    
    new_data_array = None    
    for i in xrange(n):

        last_time_idx = 0
        interp_data = []
        for new_time_idx in xrange(len(new_time_array)):
            
            time_idx = np.abs(time_array - new_time_array[new_time_idx]).argmin()                
            interp_data.append( max(data_array[i,last_time_idx:time_idx+1]) )
            last_time_idx = time_idx
        
        if new_data_array is None: new_data_array = interp_data
        else: new_data_array = np.vstack([new_data_array, interp_data])

    return new_data_array



def interpolationData(time_array, data_array, new_time_array, quat_flag=False):
    '''
    time_array: N - length array
    data_array: D x N - length array
    '''
    from scipy import interpolate

    target_array = copy.deepcopy(data_array)
    if len(np.shape(target_array)) == 1: target_array = np.array([target_array])
    if time_array[-1] < new_time_array[0] or time_array[0] > new_time_array[-1]:
        return target_array[:,: len(new_time_array)]

    n,m = np.shape(target_array)    
    if len(time_array) > m: time_array = time_array[0:m]

    # change quaternion sign
    if quat_flag:
        for i in xrange(m-1):            
            cosHalfTheta = np.sum(target_array[:,i]*target_array[:,i+1])
            if cosHalfTheta < 0.0:
                target_array[:,i+1] *= -1.0


    # remove repeated data
    temp_time_array = [time_array[0]]
    temp_data_array = target_array[:,0:1]
    for i in xrange(1, len(time_array)):        
        if time_array[i-1] != time_array[i]:
            temp_time_array.append(time_array[i])
            temp_data_array = np.hstack([temp_data_array, target_array[:,i:i+1]])
        else:
            if np.linalg.norm(temp_data_array[:,-1]) < np.linalg.norm(target_array[:,i:i+1]):
                temp_data_array[:,-1:] = target_array[:,i:i+1]

    time_array = temp_time_array
    target_array = temp_data_array

    if len(time_array) < 2:
        nDim = len(target_array)
        return np.zeros((nDim,len(new_time_array)))
    
    new_data_array = None    
    for i in xrange(n):
        interp = interpolate.splrep(time_array, target_array[i], s=0)
        interp_data = interpolate.splev(new_time_array, interp, der=0, ext=1)

        if np.isnan(np.max(interp_data)):
            print "Interpolation error by NaN values"
            print "New start time = ", new_time_array[0], " start time = ", time_array[0]
            print "New end time = ", new_time_array[-1], " end time = ", time_array[-1]
            ## print target_array[i]
            sys.exit()

        # handle extrapolation - start part
        if interp_data[0] == 0.0:
            nonzero_idx = None
            for j in xrange(len(interp_data)):
                if abs(interp_data[j]) > 0.0:
                    nonzero_idx = j
                    break
            if nonzero_idx is not None:
                interp_data[:nonzero_idx] += interp_data[nonzero_idx]

        # handle extrapolation - end part
        if interp_data[-1] == 0.0:
            nonzero_idx = None
            for j in xrange(1, len(interp_data)-1):
                if abs(interp_data[-j]) > 0.0:
                    nonzero_idx = -j
                    break
            if nonzero_idx is not None:            
                interp_data[nonzero_idx+1:] += interp_data[nonzero_idx]
        
        if new_data_array is None: new_data_array = interp_data
        else: new_data_array = np.vstack([new_data_array, interp_data])

    return new_data_array
    
def interpolationQuatData(time_array, data_array, new_time_array):
    '''
    We have to use SLERP for start-goal quaternion interpolation.
    But, I cound not find any good library for quaternion array interpolation.
    time_array: N - length array
    data_array: 4 x N - length array
    '''
    from scipy import interpolate

    n,m = np.shape(data_array)
    if len(time_array) > m:
        time_array = time_array[0:m]
    
    new_data_array = None    

    l     = len(time_array)
    new_l = len(new_time_array)

    idx_list = np.linspace(0, l-1, new_l)

    for idx in idx_list:
        if new_data_array is None:
            new_data_array = qt.slerp( data_array[:,int(idx)], data_array[:,int(np.ceil(idx))], idx-int(idx) )
        else:
            new_data_array = np.vstack([new_data_array, 
                                        qt.slerp( data_array[:,int(idx)], data_array[:,int(np.ceil(idx))], \
                                                  idx-int(idx) )])                            
                                                  
    return new_data_array.T

def interpolationSkinData(time_array, center_array, normal_array, value_array, new_time_array, threshold=0.025):
    '''
    Interpolate haptic msg
    Input
    center_array: 3XN list in which each element is a list containing M float values.
    
    Output is a list with 3XN size of list elements
    '''
    from scipy import interpolate

    new_c_arr = []
    new_n_arr = []
    new_v_arr = []

    l     = len(time_array)
    new_l = len(new_time_array)


    if l == 0: return [],[],[]
    ## if len(np.array(center_array[0]).flatten()) == 0: return [],[],[]
    print center_array
    print "temporal exit?????????????????????????? from util.py"
    sys.exit()

    idx_list = np.linspace(0, l-2, new_l)
    for idx in idx_list:
        w1 = idx-int(idx)
        w2 = 1.0 - w1

        idx1 = int(idx)
        idx2 = int(idx)+1

        c1 = np.array(center_array)[:,idx1] #size (3,)
        c2 = np.array(center_array)[:,idx2]
        n1 = np.array(normal_array)[:,idx1]
        n2 = np.array(normal_array)[:,idx2]
        v1 = np.array(value_array)[:,idx1]
        v2 = np.array(value_array)[:,idx2]      

        if c1[0] == []:            
            if c2[0] == []:
                c = []
                n = []
                v = []
            else:
                c = c2.tolist() #w2*np.array(c2) # 3xN
                n = n2.tolist() #w2*np.array(n2)
                v = v2.tolist() #w2*np.array(v2)
        else:
            if c2[0] == []:
                c = c1.tolist() #w1*np.array(c1)
                n = n1.tolist() #w1*np.array(n1)
                v = v1.tolist() #w1*np.array(v1)
            else:
                c1 = np.array(c1.tolist())
                c2 = np.array(c2.tolist())
                n1 = np.array(n1.tolist())
                n2 = np.array(n2.tolist())
                v1 = np.array(v1.tolist())
                v2 = np.array(v2.tolist())
                
                c = None
                n = None
                v = None
                close_idxes = []
                for i in xrange(len(c1[0])):
                    close_idx = None
                    for j in xrange(len(c2[0])):
                        if np.linalg.norm(c1[:,i] - c2[:,j]) < threshold:
                            close_idx = j
                            close_idxes.append(j)
                            break

                    if close_idx is None:                        
                        if c is None:
                            c = c1[:,i:i+1]
                            n = n1[:,i:i+1]
                            v = v1[:,i:i+1]
                        else:
                            c = np.hstack([c, c1[:,i:i+1]])
                            n = np.hstack([n, n1[:,i:i+1]])
                            v = np.hstack([v, v1[:,i:i+1]])
                    else:
                        if c is None:                        
                            c = w1*c1[:,i:i+1] + w2*c2[:,close_idx:close_idx+1]
                            n = w1*n1[:,i:i+1] + w2*n2[:,close_idx:close_idx+1]
                            v = w1*v1[:,i:i+1] + w2*v2[:,close_idx:close_idx+1]
                        else:
                            c = np.hstack([c, w1*c1[:,i:i+1] + w2*c2[:,close_idx:close_idx+1]])
                            n = np.hstack([n, w1*n1[:,i:i+1] + w2*n2[:,close_idx:close_idx+1]])
                            v = np.hstack([v, w1*v1[:,i:i+1] + w2*v2[:,close_idx:close_idx+1]])

                if len(close_idxes) < len(c2[0]):
                    for i in xrange(len(c2[0])):
                        if i not in close_idxes:
                            if c is None:
                                c = c2[:,i:i+1]
                                n = n2[:,i:i+1]
                                v = v2[:,i:i+1]
                            else:
                                c = np.hstack([c, c2[:,i:i+1]])
                                n = np.hstack([n, n2[:,i:i+1]])
                                v = np.hstack([v, v2[:,i:i+1]])
                
                c = c.tolist()
                n = n.tolist()
                v - v.tolist()

        new_c_arr.append(c)
        new_n_arr.append(n)
        new_v_arr.append(v)

    return new_c_arr, new_n_arr, new_v_arr
    
def scaleData(data_dict, scale=10, data_min=None, data_max=None, verbose=False):

    if data_dict == {}: return {}
    
    # Determine max and min values
    if data_min is None or data_max is None:
        data_min = {}
        data_max = {}
        for key in data_dict.keys():
            if 'time' in key or 'Quat' in key: continue
            if data_dict[key] == []: continue            
            data_min[key] = np.min(data_dict[key])
            data_max[key] = np.max(data_dict[key])
            
        if verbose:
            print 'minValues', data_min
            print 'maxValues', data_max

    data_dict_scaled = {}
    for key in data_dict.keys():
        if data_dict[key] == []: continue
        if 'time' in key or 'Quat' in key: 
            data_dict_scaled[key] = data_dict[key]
        else:
            data_dict_scaled[key] = (data_dict[key] - data_min[key])/(data_max[key]-data_min[key]) * scale
        
    return data_dict_scaled


def getAngularSpatialRF(cur_pos, dist_margin ):

    dist = np.linalg.norm(cur_pos)
    if dist <= dist_margin: return 90.0, -90.0
    ang_margin = np.arctan(dist_margin/dist)*180.0/np.pi

    pos      = copy.deepcopy(cur_pos)
    pos     /= np.linalg.norm(pos)
    ang_cur  = np.arcsin(pos[1])*180.0/np.pi #- np.pi/2.0

    ang_max = ang_cur + ang_margin
    ang_min = ang_cur - ang_margin

    return ang_max, ang_min


def extractLocalData(rf_time, rf_traj, local_range, data_set, multi_pos_flag=False, global_data=False, \
                     verbose=False):
    '''
    Extract local data in data_set
    The first element of the data_set should be time data.
    The second element of the data_set should be location data.
    '''

    time_data = data_set[0]
    pos_data  = data_set[1]
    nData = len(data_set)-1
                
    # length adjustment
    if len(time_data) != len(pos_data[0]):
        if len(time_data) > len(pos_data[0]):
            time_data = time_data[:len(pos_data[0])]
        else:
            pos_data = pos_data[:,:len(time_data)]
    
    if multi_pos_flag is False:
        new_data_set = [None for i in xrange(nData)]

        for time_idx in xrange(len(time_data)):
            rf_time_idx = np.abs(rf_time - time_data[time_idx]).argmin()

            if (np.linalg.norm(pos_data[0:3,time_idx] - rf_traj[:,rf_time_idx]) <= local_range) or global_data:
                for i in xrange(nData):
                    if new_data_set[i] is None:
                        if len(np.shape(data_set[i+1])) > 1:
                            new_data_set[i] = data_set[i+1][:,time_idx:time_idx+1]
                        else:
                            new_data_set[i] = data_set[i+1][time_idx:time_idx+1]
                    else:
                        if len(np.shape(data_set[i+1])) > 1:
                            new_data_set[i] = np.hstack([ new_data_set[i], data_set[i+1][:,time_idx:time_idx+1] ])
                        else:
                            new_data_set[i] = np.hstack([ new_data_set[i], data_set[i+1][time_idx:time_idx+1] ])
            else:
                for i in xrange(nData):
                    if new_data_set[i] is None:
                        if len(np.shape(data_set[i+1])) > 1:
                            new_data_set[i] = data_set[i+1][:,time_idx:time_idx+1]
                        else:
                            new_data_set[i] = data_set[i+1][time_idx:time_idx+1]
                    else:
                        if len(np.shape(data_set[i+1])) > 1:
                            new_data_set[i] = np.hstack([ new_data_set[i], new_data_set[i][:,-1:] ])
                        else:
                            new_data_set[i] = np.hstack([ new_data_set[i], new_data_set[i][-1:] ])

    else:
        new_data_set = [[[],[],[]] for i in xrange(nData)]

        for time_idx in xrange(len(time_data)):
            rf_time_idx = np.abs(rf_time - time_data[time_idx]).argmin()                

            if pos_data[0][time_idx] == []:
                for i in xrange(nData):
                    new_data_set[i][0].append( [0] )
                    new_data_set[i][1].append( [0] )
                    new_data_set[i][2].append( [0] )
            else:
                for i in xrange(nData):

                    local_data_x = []
                    local_data_y = []
                    local_data_z = []
                    nPos = len(pos_data[0][time_idx])
                    for j in xrange(nPos):
                        pos_array = np.array([pos_data[0][time_idx][j],\
                                              pos_data[1][time_idx][j],\
                                              pos_data[2][time_idx][j]])
                        if (np.linalg.norm(pos_array - rf_traj[:,rf_time_idx]) <= local_range or global_data)\
                          and len(data_set[i+1][0][time_idx]) >= j+1 \
                          and len(data_set[i+1][1][time_idx]) >= j+1 \
                          and len(data_set[i+1][2][time_idx]) >= j+1 :
                            local_data_x.append( data_set[i+1][0][time_idx][j] )
                            local_data_y.append( data_set[i+1][1][time_idx][j] )
                            local_data_z.append( data_set[i+1][2][time_idx][j] )

                    ## new_data_set[i].append( local_data )
                    new_data_set[i][0].append( local_data_x )
                    new_data_set[i][1].append( local_data_y )
                    new_data_set[i][2].append( local_data_z )

                    if nPos>1:
                        new_data_set[i][0]
                                        
    return new_data_set
    
    


def extractLocalFeature(d, feature_list, param_dict=None, verbose=False):

    if param_dict is None:
        isTrainingData=True
        param_dict = {}

        if 'unimodal_audioPower' in feature_list:
            ## power_max = np.amax(d['audioPowerList'])
            ## power_min = np.amin(d['audioPowerList'])
            ## power_min = np.mean(np.array(d['audioPowerList'])[:,:10])
            power_min = 10000
            power_max = 0
            for pwr in d['audioPowerList']:
                p_min = np.amin(pwr)
                p_max = np.amax(pwr)
                if power_min > p_min:
                    power_min = p_min
                ## if p_max < 50 and power_max < p_max:
                if power_max < p_max:
                    power_max = p_max

            param_dict['unimodal_audioPower_power_max'] = power_max
            param_dict['unimodal_audioPower_power_min'] = power_min
                                
        ## if 'unimodal_ftForce' in feature_list:
        ##     force_array = None
        ##     start_force_array = None
        ##     for idx in xrange(len(d['ftForceList'])):
        ##         if force_array is None:
        ##             force_array = d['ftForceList'][idx]
        ##             ## start_force_array = d['ftForceList'][idx][:,:5]
        ##         else:
        ##             force_array = np.hstack([force_array, d['ftForceList'][idx] ])
        ##             ## start_force_array = np.hstack([start_force_array, d['ftForceList'][idx][:,:5]])

        ##     ftPCADim    = 2
        ##     ftForce_pca = PCA(n_components=ftPCADim)
        ##     res = ftForce_pca.fit_transform( force_array.T )            
        ##     param_dict['unimodal_ftForce_pca'] = ftForce_pca
        ##     param_dict['unimodal_ftForce_pca_dim'] = ftPCADim

        ##     ## res = ftForce_pca.transform(start_force_array.T)
        ##     ## param_dict['unimodal_ftForce_pca_init_avg'] = np.array([np.mean(res, axis=0)]).T
        ##     ## param_dict['unimodal_ftForce_init_avg'] = np.mean(start_force_array, axis=1)

        if 'unimodal_ppsForce' in feature_list:
            ppsLeft  = d['ppsLeftList']
            ppsRight = d['ppsRightList']

            pps_mag = []
            for i in xrange(len(ppsLeft)):                
                pps      = np.vstack([ppsLeft[i], ppsRight[i]])
                pps_mag.append( np.linalg.norm(pps, axis=0) )

            pps_max = np.max( np.array(pps_mag).flatten() )
            pps_min = np.min( np.array(pps_mag).flatten() )
            param_dict['unimodal_ppsForce_max'] = pps_max
            param_dict['unimodal_ppsForce_min'] = pps_min

        param_dict['feature_names'] = []
    else:
        isTrainingData=False
            

    # -------------------------------------------------------------        

    # extract local features
    dataList   = []
    for idx in xrange(len(d['timesList'])): # each sample

        timeList     = d['timesList'][idx]
        dataSample = None

        ## # Define receptive field center trajectory ---------------------------
        ## if rf_center == 'kinEEPos':
        ##     rf_traj = d['kinEEPosList'][idx]
        ## elif rf_center == 'kinForearmPos':
        ##     rf_traj = d['kinForearmPosList'][idx]
        ## ## elif rf_center == 'l_upper_arm_link':            
        ## else:
        ##     sys.exit()
        

        # Unimoda feature - Audio --------------------------------------------
        if 'unimodal_audioPower' in feature_list:
            ## audioAzimuth = d['audioAzimuthList'][idx]
            audioPower   = d['audioPowerList'][idx]            
            unimodal_audioPower = audioPower
            
            if dataSample is None: dataSample = copy.copy(np.array(unimodal_audioPower))
            else: dataSample = np.vstack([dataSample, copy.copy(unimodal_audioPower)])
            if 'audioPower' not in param_dict['feature_names']:
                param_dict['feature_names'].append('audioPower')

        # Unimoda feature - AudioWrist ---------------------------------------
        if 'unimodal_audioWristRMS' in feature_list:
            audioWristRMS = d['audioWristRMSList'][idx]            
            unimodal_audioWristRMS = audioWristRMS
            
            if dataSample is None: dataSample = copy.copy(np.array(unimodal_audioWristRMS))
            else: dataSample = np.vstack([dataSample, copy.copy(unimodal_audioWristRMS)])
            if 'audioWristRMS' not in param_dict['feature_names']:
                param_dict['feature_names'].append('audioWristRMS')

        # Unimodal feature - Kinematics --------------------------------------
        if 'unimodal_kinVel' in feature_list:
            kinVel  = d['kinVelList'][idx]
            unimodal_kinVel = kinVel

            if dataSample is None: dataSample = np.array(unimodal_kinVel)
            else: dataSample = np.vstack([dataSample, unimodal_kinVel])
            if 'kinVel_x' not in param_dict['feature_names']:
                param_dict['feature_names'].append('kinVel_x')
                param_dict['feature_names'].append('kinVel_y')
                param_dict['feature_names'].append('kinVel_z')

        # Unimodal feature - Force -------------------------------------------
        if 'unimodal_ftForce' in feature_list:
            ftForce = d['ftForceList'][idx]

            # magnitude
            if len(np.shape(ftForce)) > 1:
                unimodal_ftForce_mag = np.linalg.norm(ftForce, axis=0)
                # individual force
                unimodal_ftForce_ind = ftForce[2:3,:]                
                
                if dataSample is None: dataSample = np.array(unimodal_ftForce_mag)
                else: dataSample = np.vstack([dataSample, unimodal_ftForce_mag])

                if dataSample is None: dataSample = np.array(unimodal_ftForce_ind)
                else: dataSample = np.vstack([dataSample, unimodal_ftForce_ind])

                if 'ftForce_z' not in param_dict['feature_names']:
                    param_dict['feature_names'].append('ftForce_mag')
                    ## param_dict['feature_names'].append('ftForce_x')
                    ## param_dict['feature_names'].append('ftForce_y')
                    param_dict['feature_names'].append('ftForce_z')
            else:                
                unimodal_ftForce_mag = ftForce
            
                if dataSample is None: dataSample = np.array(unimodal_ftForce_mag)
                else: dataSample = np.vstack([dataSample, unimodal_ftForce_mag])

                if 'ftForce_mag' not in param_dict['feature_names']:
                    param_dict['feature_names'].append('ftForce_mag')

            ## ftPos   = d['kinEEPosList'][idx]
            ## ftForce_pca = param_dict['unimodal_ftForce_pca']

            ## unimodal_ftForce = None
            ## for time_idx in xrange(len(timeList)):
            ##     if unimodal_ftForce is None:
            ##         unimodal_ftForce = ftForce_pca.transform(ftForce[:,time_idx:time_idx+1].T).T
            ##     else:
            ##         unimodal_ftForce = np.hstack([ unimodal_ftForce, \
            ##                                        ftForce_pca.transform(ftForce[:,time_idx:time_idx+1].T).T ])

            ## unimodal_ftForce -= np.array([np.mean(unimodal_ftForce[:,:5], axis=1)]).T
            
            ## if 'ftForce_1' not in param_dict['feature_names']:
            ##     param_dict['feature_names'].append('ftForce_1')
            ##     param_dict['feature_names'].append('ftForce_2')
            ## if 'ftForce_x' not in param_dict['feature_names']:
            ##     param_dict['feature_names'].append('ftForce_x')
            ##     param_dict['feature_names'].append('ftForce_y')
            ##     param_dict['feature_names'].append('ftForce_z')

        # Unimodal feature - pps -------------------------------------------
        if 'unimodal_ppsForce' in feature_list:
            ppsLeft  = d['ppsLeftList'][idx]
            ppsRight = d['ppsRightList'][idx]
            ppsPos   = d['kinTargetPosList'][idx]

            pps = np.vstack([ppsLeft, ppsRight])
            unimodal_ppsForce = pps

            # 2
            pps = np.vstack([np.sum(ppsLeft, axis=0), np.sum(ppsRight, axis=0)])
            unimodal_ppsForce = pps
            
            # 1
            ## unimodal_ppsForce = np.array([np.linalg.norm(pps, axis=0)])

            unimodal_ppsForce -= np.array([np.mean(unimodal_ppsForce[:,:5], axis=1)]).T

            ## unimodal_ppsForce = []
            ## for time_idx in xrange(len(timeList)):
            ##     unimodal_ppsForce.append( np.linalg.norm(pps[:,time_idx]) )

            if dataSample is None: dataSample = unimodal_ppsForce
            else: dataSample = np.vstack([dataSample, unimodal_ppsForce])

            ## if 'ppsForce' not in param_dict['feature_names']:
            ##     param_dict['feature_names'].append('ppsForce')
            if 'ppsForce_1' not in param_dict['feature_names']:
                param_dict['feature_names'].append('ppsForce_1')
                param_dict['feature_names'].append('ppsForce_2')                
            ## if 'ppsForce_1' not in param_dict['feature_names']:
            ##     param_dict['feature_names'].append('ppsForce_1')
            ##     param_dict['feature_names'].append('ppsForce_2')
            ##     param_dict['feature_names'].append('ppsForce_3')
            ##     param_dict['feature_names'].append('ppsForce_4')
            ##     param_dict['feature_names'].append('ppsForce_5')
            ##     param_dict['feature_names'].append('ppsForce_6')


        # Unimodal feature - vision change ------------------------------------
        if 'unimodal_visionChange' in feature_list:
            visionChangeMag = d['visionChangeMagList'][idx]

            unimodal_visionChange = visionChangeMag

            if dataSample is None: dataSample = unimodal_visionChange
            else: dataSample = np.vstack([dataSample, unimodal_visionChange])
            if 'visionChange' not in param_dict['feature_names']:
                param_dict['feature_names'].append('visionChange')

                
        # Unimodal feature - fabric skin ------------------------------------
        if 'unimodal_fabricForce' in feature_list:
            fabricMag = d['fabricMagList'][idx]

            unimodal_fabricForce = fabricMag

            if dataSample is None: dataSample = unimodal_fabricForce
            else: dataSample = np.vstack([dataSample, unimodal_fabricForce])
            if 'fabricForce' not in param_dict['feature_names']:
                param_dict['feature_names'].append('fabricForce')

            
        # Crossmodal feature - relative dist --------------------------
        if 'crossmodal_targetEEDist' in feature_list:
            kinEEPos     = d['kinEEPosList'][idx]
            kinTargetPos  = d['kinTargetPosList'][idx]

            dist = np.linalg.norm(kinTargetPos - kinEEPos, axis=0)
            crossmodal_targetEEDist = []
            for time_idx in xrange(len(timeList)):
                crossmodal_targetEEDist.append( dist[time_idx])

            if dataSample is None: dataSample = np.array(crossmodal_targetEEDist)
            else: dataSample = np.vstack([dataSample, crossmodal_targetEEDist])
            if 'targetEEDist' not in param_dict['feature_names']:
                param_dict['feature_names'].append('targetEEDist')


        # Crossmodal feature - relative angle --------------------------
        if 'crossmodal_targetEEAng' in feature_list:                
            kinEEQuat    = d['kinEEQuatList'][idx]
            kinTargetQuat = d['kinTargetQuatList'][idx]

            ## kinEEPos     = d['kinEEPosList'][idx]
            ## kinTargetPos = d['kinTargetPosList'][idx]
            ## dist         = np.linalg.norm(kinTargetPos - kinEEPos, axis=0)
            
            crossmodal_targetEEAng = []
            for time_idx in xrange(len(timeList)):

                startQuat = kinEEQuat[:,time_idx]
                endQuat   = kinTargetQuat[:,time_idx]

                diff_ang = qt.quat_angle(startQuat, endQuat)
                crossmodal_targetEEAng.append( abs(diff_ang) )

            ## fig = plt.figure()
            ## ## plt.plot(crossmodal_targetEEAng)
            ## plt.plot( kinEEQuat[0] )
            ## plt.plot( kinEEQuat[1] )
            ## plt.plot( kinEEQuat[2] )
            ## plt.plot( kinEEQuat[3] )
            ## fig.savefig('test.pdf')
            ## fig.savefig('test.png')
            ## os.system('cp test.p* ~/Dropbox/HRL/')        
            ## sys.exit()
            
            if dataSample is None: dataSample = np.array(crossmodal_targetEEAng)
            else: dataSample = np.vstack([dataSample, crossmodal_targetEEAng])
            if 'targetEEAng' not in param_dict['feature_names']:
                param_dict['feature_names'].append('targetEEAng')

        # Crossmodal feature - vision relative dist with main(first) vision target----
        if 'crossmodal_artagEEDist' in feature_list:
            kinEEPos  = d['kinEEPosList'][idx]
            visionArtagPos = d['visionArtagPosList'][idx][:3] # originally length x 3*tags

            dist = np.linalg.norm(visionArtagPos - kinEEPos, axis=0)
            crossmodal_artagEEDist = []
            for time_idx in xrange(len(timeList)):
                crossmodal_artagEEDist.append(dist[time_idx])

            if dataSample is None: dataSample = np.array(crossmodal_artagEEDist)
            else: dataSample = np.vstack([dataSample, crossmodal_artagEEDist])
            if 'artagEEDist' not in param_dict['feature_names']:
                param_dict['feature_names'].append('artagEEDist')

        # Crossmodal feature - vision relative angle --------------------------
        if 'crossmodal_artagEEAng' in feature_list:                
            kinEEQuat    = d['kinEEQuatList'][idx]
            visionArtagQuat = d['visionArtagQuatList'][idx][:4]

            kinEEPos  = d['kinEEPosList'][idx]
            visionArtagPos = d['visionArtagPosList'][idx][:3]
            dist = np.linalg.norm(visionArtagPos - kinEEPos, axis=0)
            
            crossmodal_artagEEAng = []
            for time_idx in xrange(len(timeList)):

                startQuat = kinEEQuat[:,time_idx]
                endQuat   = visionArtagQuat[:,time_idx]

                diff_ang = qt.quat_angle(startQuat, endQuat)
                crossmodal_artagEEAng.append( abs(diff_ang) )

            if dataSample is None: dataSample = np.array(crossmodal_artagEEAng)
            else: dataSample = np.vstack([dataSample, crossmodal_artagEEAng])
            if 'artagEEAng' not in param_dict['feature_names']:
                param_dict['feature_names'].append('artagEEAng')

        # ----------------------------------------------------------------
        dataList.append(dataSample)


    # Converting data structure
    nSample      = len(dataList)
    nEmissionDim = len(dataList[0])
    features     = []
    for i in xrange(nEmissionDim):
        feature  = []

        for j in xrange(nSample):
            try:
                ## feature.append(dataList[j][i])
                feature.append(dataList[j][i,:])
            except:
                print np.shape(dataList), np.shape(dataList[j]), j, i
                sys.exit()

        features.append( feature )


    # Scaling ------------------------------------------------------------
    if isTrainingData:
        param_dict['feature_max'] = [ np.max(np.array(feature).flatten()) for feature in features ]
        param_dict['feature_min'] = [ np.min(np.array(feature).flatten()) for feature in features ]
        print "max: ", param_dict['feature_max']
        print "min: ", param_dict['feature_min']
        
        
    scaled_features = []
    for i, feature in enumerate(features):

        if abs( param_dict['feature_max'][i] - param_dict['feature_min'][i]) < 1e-3:
            scaled_features.append( np.array(feature) )
        else:
            scaled_features.append( ( np.array(feature) - param_dict['feature_min'][i] )\
                                    /( param_dict['feature_max'][i] - param_dict['feature_min'][i]) )

    ## import matplotlib.pyplot as plt
    ## plt.figure()
    ## plt.plot(np.array(scaled_features[0]).T)
    ## plt.show()
    ## sys.exit()
                                
    return scaled_features, param_dict



def space_time_clustering(image, time_range, space_range, space_interval, time_interval, n_clusters=8, X=None):

    if X is None:
        X = []
        for i in xrange(len(image)):
            # clustering label
            for j in xrange(len(image[i])):
                if image[i,j] > 0.05: X.append([i,j]) #temp # N x Ang

    if len(X)==0: return  np.zeros(np.shape(image)), []
    if len(X) < n_clusters: n_clusters=len(X)
                    
    ## from sklearn.mixture import DPGMM
    ## mlc = DPGMM(n_components=2)        
    from sklearn.cluster import KMeans
    mlc = KMeans(n_clusters=n_clusters)        
    y = mlc.fit_predict(X)
    
    label_list = [ [x] for x in range(0,n_clusters) ]
    last_label_list = None

    # Merge close labels
    ii = 0
    while True:

        for label_idx, label1 in enumerate(label_list):
            if len(label1)==0 or label_idx==len(label_list)-1: continue
            for ii in label1:

                for label_idx2, label2 in enumerate(label_list[label_idx+1:]):
                    if len(label2)==0: continue
                    for jj in label2:                    
                        if (abs(mlc.cluster_centers_[ii][0]-mlc.cluster_centers_[jj][0])<\
                          space_range/space_interval*2.0 and\
                          abs(mlc.cluster_centers_[ii][1]-mlc.cluster_centers_[jj][1])<\
                          time_range/time_interval*2.0) :
                            label_list[label_idx+1+label_idx2].remove(jj)
                            label_list[label_idx].append(jj)

        if last_label_list == label_list: break
        else: last_label_list = label_list

    # Replace labels into merged labels
    temp = copy.copy(y)
    for ii, label in enumerate(temp):
        for jj in xrange(len(label_list)):
            if label_list[jj] == []: continue
            if label in label_list[jj]:
                y[ii] = label_list[jj][0]+1
                break                                

    # 
    clustered_image = np.zeros(np.shape(image))        
    for idx, l in enumerate(X):
        clustered_image[l[0],l[1]] = y[idx]                

    return clustered_image, label_list


def get_time_kernel(x_max, x_interval):
    '''
    x_max is 97.7%
    '''
    from scipy.stats import gumbel_r

    x_range = np.arange(-x_max*3.0, x_max*3.0, x_interval)
    if len(x_range)%2 == 0:
        x_range = np.hstack([x_range, x_range[-1]+x_interval])-x_interval/2.0

    sigma = (x_max/2.0)
    gumbel_1D_kernel  = gumbel_r().pdf(x_range/sigma)/sigma
    gumbel_1D_kernel /= np.max(gumbel_1D_kernel)

    return gumbel_1D_kernel


def get_space_time_kernel(x_max, y_max, x_interval, y_interval):
    '''
    x_max is 97.7%
    '''

    from scipy.stats import norm, gumbel_r

    y_range = np.arange(-y_max*3.0, y_max*3.0, y_interval)
    if len(y_range)%2 == 0:
        y_range = np.hstack([y_range, y_range[-1]+y_interval])-y_interval/2.0
    x_range = np.arange(-x_max*3.0, x_max*3.0, x_interval)
    if len(x_range)%2 == 0:
        x_range = np.hstack([x_range, x_range[-1]+x_interval])-x_interval/2.0

    sigma = (y_max/2.0)
    a  = norm().pdf(y_range/sigma)/sigma
    gaussian_2D_kernel = None
    for j in xrange(len(x_range)):
        if gaussian_2D_kernel is None: gaussian_2D_kernel = np.array([a]).T
        else: gaussian_2D_kernel = np.hstack([gaussian_2D_kernel, np.array([a]).T])

    ## g = Gaussian1DKernel(len(gaussian_2D_kernel[0])/8. ) # 8*std
    ## a = g.array
    sigma = (x_max/2.0)
    a  = gumbel_r().pdf(x_range/sigma)/sigma
    for j in xrange(len(gaussian_2D_kernel)):
        gaussian_2D_kernel[j] = a * gaussian_2D_kernel[j]

    gaussian_2D_kernel/=np.max(gaussian_2D_kernel.flatten())

    return gaussian_2D_kernel


def cross_2D_correlation(image1, image2, x_pad, y_pad):

    n,m = np.shape(image1)
    
    # padding
    A = np.zeros(( n+(2*x_pad-2), m+(y_pad-1) ))
    A[x_pad-1:x_pad-1+n, y_pad-1:y_pad-1+m] = image1
    B = image2
    
    # convolution
    C = np.zeros((2*(x_pad-1), y_pad-1))
    for i in xrange(len(C)):
        for j in xrange(len(C[0])):
            ## print i,i+n,j,j+m,np.shape(A), np.shape(A[i:i+n,j:j+m]), np.shape(B), np.shape(C)
            C[i,j] = np.sum( A[i:i+n,j:j+m] * B )

    # unpadding
    ## C = C[x_pad-1:x_pad-1+n, y_pad-1:y_pad-1+m]
    ## print "size C and B", np.shape(C), np.shape(B)

    # Find delays with maximum correlation
    x_diff, y_diff = np.unravel_index(C.argmax(), C.shape)
    ## print "diff: ", x_diff, y_diff

    return C, x_diff, y_diff

def cross_1D_correlation(seq1, seq2, pad):

    n = len(seq1)
    
    # padding
    A = np.zeros(( n+(2*pad-2) ))
    A[pad-1:pad-1+n] = seq1
    B = seq2
    
    # convolution
    C = np.zeros((2*(pad-1) ))
    for i in xrange(len(C)):
        ## print i,i+n,j,j+m,np.shape(A), np.shape(A[i:i+n,j:j+m]), np.shape(B), np.shape(C)
        C[i] = np.sum( A[i:i+n] * B )

    # Find delays with maximum correlation ??
    x_diff = C.argmax()
    # print "diff: ", x_diff

    return C, x_diff
