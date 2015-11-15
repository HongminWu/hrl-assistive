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
import random
import socket

# visualization
import matplotlib
## matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from matplotlib import gridspec

# util
import numpy as np
import scipy
import hrl_lib.util as ut
from hrl_anomaly_detection.util import *
import PyKDL
import sandbox_dpark_darpa_m3.lib.hrl_check_util as hcu
import sandbox_dpark_darpa_m3.lib.hrl_dh_lib as hdl
import hrl_lib.circular_buffer as cb

# learning
from hrl_anomaly_detection.hmm import learning_hmm_multi_n as hmm

# image
from astropy.convolution.kernels import CustomKernel
from astropy.convolution import convolve, convolve_fft

import itertools
colors = itertools.cycle(['r', 'g', 'b', 'm', 'c', 'k', 'y'])
shapes = itertools.cycle(['x','v', 'o', '+'])


def preprocessData(subject_names, task_name, raw_data_path, processed_data_path, nSet=1, \
                   folding_ratio=0.8, downSampleSize=200,\
                   raw_viz=False, interp_viz=False, renew=False, verbose=False, save_pdf=False):

    # Check if there is already scaled data
    for i in xrange(nSet):        
        target_file = os.path.join(processed_data_path, task_name+'_dataSet_'+str(i) )                    
        if os.path.isfile(target_file) is not True: renew=True
            
    if renew == False: return        

    success_list, failure_list = getSubjectFileList(raw_data_path, subject_names, task_name)

    nTrain = int(len(success_list) * folding_ratio)
    nTest  = len(success_list) - nTrain    

    if len(failure_list) < nTest: 
        print "Not enough failure data"
        sys.exit()

    # loading and time-sync
    _, data_dict = loadData(success_list, isTrainingData=False, downSampleSize=downSampleSize)
    
    ## data_min = {}
    ## data_max = {}
    ## for key in data_dict.keys():
    ##     if 'time' in key: continue
    ##     if data_dict[key] == []: continue
    ##     data_min[key] = np.min(data_dict[key])        
    ##     data_max[key] = np.max(data_dict[key])
        
    for i in xrange(nSet):

        # index selection
        success_idx  = range(len(success_list))
        failure_idx  = range(len(failure_list))
        train_idx    = random.sample(success_idx, nTrain)

        if nTest == 0: 
            success_test_idx = []
            failure_test_idx = []
        else: 
            success_test_idx = [x for x in success_idx if not x in train_idx]
            failure_test_idx = random.sample(failure_idx, nTest)

        # get training data
        trainFileList = [success_list[x] for x in train_idx]
        _, trainData = loadData(trainFileList, isTrainingData=True, \
                                downSampleSize=downSampleSize)

        # get test data
        if nTest != 0:        
            normalTestFileList = [success_list[x] for x in success_test_idx]
            _, normalTestData = loadData([success_list[x] for x in success_test_idx], 
                                                          isTrainingData=False, downSampleSize=downSampleSize)
            abnormalTestFileList = [failure_list[x] for x in failure_test_idx]
            _, abnormalTestData = loadData([failure_list[x] for x in failure_test_idx], \
                                        isTrainingData=False, downSampleSize=downSampleSize)

        # scaling data
        ## trainData_scaled = scaleData(trainData, scale=scale, data_min=data_min, 
        ##                              data_max=data_max, verbose=verbose)
        ## normalTestData_scaled = scaleData(normalTestData, scale=scale, data_min=data_min, 
        ##                                   data_max=data_max, verbose=verbose)
        ## abnormalTestData_scaled = scaleData(abnormalTestData, scale=scale, data_min=data_min, 
        ##                                     data_max=data_max, verbose=verbose)

        # cutting data (only traing and thresTest data)
        ## start_idx = int(float(len(trainData_scaled[0][0]))*train_cutting_ratio[0])
        ## end_idx   = int(float(len(trainData_scaled[0][0]))*train_cutting_ratio[1])

        ## for j in xrange(len(trainData_scaled)):
        ##     for k in xrange(len(trainData_scaled[j])):
        ##         trainData_scaled[j][k] = trainData_scaled[j][k][start_idx:end_idx]
                
        ## for j in xrange(len(normalTestData_scaled)):
        ##     for k in xrange(len(normalTestData_scaled[j])):                
        ##         normalTestData_scaled[j][k] = normalTestData_scaled[j][k][start_idx:end_idx]
                
        ## for j in xrange(len(abnormalTestData_scaled)):
        ##     for k in xrange(len(abnormalTestData_scaled[j])):                
        ##         abnormalTestData_scaled[j][k] = abnormalTestData_scaled[j][k][start_idx:end_idx]

        # Save data using dictionary
        d = {}
        d['trainData']        = trainData
        d['normalTestData']   = normalTestData
        d['abnormalTestData'] = abnormalTestData

        d['trainFileList']        = trainFileList
        d['normalTestFileList']   = normalTestFileList
        d['abnormalTestFileList'] = abnormalTestFileList        
        
        # Save data using dictionary
        target_file = os.path.join(processed_data_path, task_name+'_dataSet_'+str(i) )

        try:
            ut.save_pickle(d, target_file)        
        except:
            print "There is already target file: "
        
        

        


def updateMinMax(param_dict, feature_name, feature_array):

    if feature_name in param_dict.keys():
        maxVal = np.max(feature_array)
        minVal = np.min(feature_array)
        if param_dict[feature_name+'_max'] < maxVal:
            param_dict[feature_name+'_max'] = maxVal
        if param_dict[feature_name+'_min'] > minVal:
            param_dict[feature_name+'_min'] = minVal
    else:
        param_dict[feature_name+'_max'] = -100000000000
        param_dict[feature_name+'_min'] =  100000000000
        
    

def likelihoodOfSequences(subject_names, task_name, raw_data_path, processed_data_path, rf_center, local_range, \
                          nSet=1, downSampleSize=200, \
                          feature_list=['crossmodal_targetRelativeDist'], \
                          nState=10, threshold=-1.0, \
                          useTrain=True, useNormalTest=True, useAbnormalTest=False,\
                          useTrain_color=False, useNormalTest_color=False, useAbnormalTest_color=False,\
                          renew=False, save_pdf=False, data_renew=False, show_plot=True):

    allData, trainingData, abnormalTestData = feature_extraction(subject_names, task_name, raw_data_path, \
                                                                 processed_data_path, rf_center, local_range,\
                                                                 nSet=nSet, \
                                                                 downSampleSize=downSampleSize, \
                                                                 feature_list=feature_list, \
                                                                 data_renew=data_renew)

    print "======================================"
    print "Training data: ", np.shape(trainingData)
    print "Normal test data: ", np.shape(normalTestData)
    print "Abnormal test data: ", np.shape(abnormalTestData)
    print "======================================"

    # training hmm
    nEmissionDim = len(trainingData)
    detection_param_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'.pkl')

    ml  = hmm.learning_hmm_multi_n(nState, nEmissionDim, verbose=False)
    ret = ml.fit(trainingData, ml_pkl=detection_param_pkl, use_pkl=not(renew))
    ths = threshold
    
    if ret == 'Failure': 
        print "-------------------------"
        print "HMM returned failure!!   "
        print "-------------------------"
        return (-1,-1,-1,-1)
    
    if show_plot: fig = plt.figure()
    min_logp = 0.0
    max_logp = 0.0
        
    # training data
    if useTrain:

        log_ll = []
        exp_log_ll = []        
        count = 0
        for i in xrange(len(trainingData[0])):

            log_ll.append([])
            exp_log_ll.append([])
            for j in range(2, len(trainingData[0][i])):

                X = [x[i,:j] for x in trainingData]                
                X_test = ml.convert_sequence(X)
                try:
                    logp = ml.loglikelihood(X_test)
                except:
                    print "Too different input profile that cannot be expressed by emission matrix"
                    return [], 0.0 # error

                log_ll[i].append(logp)

            if min_logp > np.amin(log_ll): min_logp = np.amin(log_ll)
            if max_logp < np.amax(log_ll): max_logp = np.amax(log_ll)
                
            # disp
            if useTrain_color:
                plt.plot(log_ll[i], label=str(i))
                print i, " : ", trainFileList[i], log_ll[i][-1]                
            else:
                plt.plot(log_ll[i], 'b-')

        if useTrain_color: 
            plt.legend(loc=3,prop={'size':16})
            
        ## plt.plot(exp_log_ll[i], 'r-')            
                                             
    # normal test data
    if useNormalTest:

        log_ll = []
        exp_log_ll = []        
        count = 0
        for i in xrange(len(normalTestData[0])):

            log_ll.append([])
            exp_log_ll.append([])

            for j in range(2, len(normalTestData[0][i])):
                X = [x[i,:j] for x in normalTestData]                
                X_test = ml.convert_sequence(X)
                try:
                    logp = ml.loglikelihood(X_test)
                except:
                    print "Too different input profile that cannot be expressed by emission matrix"
                    return [], 0.0 # error

                log_ll[i].append(logp)

                ## exp_logp = ml.expLikelihoods(X_test, ths)
                exp_logp = ml.expLikelihoods(X, ths)
                exp_log_ll[i].append(exp_logp)

            if min_logp > np.amin(log_ll): min_logp = np.amin(log_ll)
            if max_logp < np.amax(log_ll): max_logp = np.amax(log_ll)

            # disp 
            if useNormalTest_color:
                print i, " : ", normalTestFileList[i]                
                plt.plot(log_ll[i], label=str(i))
            else:
                plt.plot(log_ll[i], 'g-')

            plt.plot(exp_log_ll[i], 'r*-')


        if useNormalTest_color: 
            plt.legend(loc=3,prop={'size':16})

    # abnormal test data
    if useAbnormalTest:
        log_ll = []
        exp_log_ll = []        
        count = 0
        for i in xrange(len(abnormalTestData[0])):

            log_ll.append([])
            exp_log_ll.append([])

            for j in range(2, len(abnormalTestData[0][i])):
                X = [x[i,:j] for x in abnormalTestData]                
                X_test = ml.convert_sequence(X)
                try:
                    logp = ml.loglikelihood(X_test)
                except:
                    print "Too different input profile that cannot be expressed by emission matrix"
                    return [], 0.0 # error

                log_ll[i].append(logp)

            # disp 
            plt.plot(log_ll[i], 'r-')
            ## plt.plot(exp_log_ll[i], 'r*-')


    plt.ylim([min_logp, max_logp])
    if save_pdf == True:
        fig.savefig('test.pdf')
        fig.savefig('test.png')
        os.system('cp test.p* ~/Dropbox/HRL/')
    else:
        if show_plot: plt.show()        

    return

        

def evaluation_all(subject_names, task_name, check_methods, feature_list, nSet, \
                   processed_data_path, downSampleSize=100, \
                   nState=10, cov_mult=1.0, anomaly_offset=0.0, local_range=0.25,\
                   data_renew=False, hmm_renew=False, save_pdf=False, viz=False):

    # For parallel computing
    strMachine = socket.gethostname()+"_"+str(os.getpid())    

    count = 0
    for method in check_methods:        

        # Check the existance of workspace
        method_path = os.path.join(processed_data_path, task_name, method)
        if os.path.isdir(method_path) == False:
            os.system('mkdir -p '+method_path)

        for idx, subject_name in enumerate(subject_names):

            ## For parallel computing
            # save file name
            res_file        = task_name+'_'+subject_name+'_'+method+'.pkl'
            mutex_file_part = 'running_'+task_name+'_'+subject_name+'_'+method

            res_file        = os.path.join(method_path, res_file)
            mutex_file_full = mutex_file_part+'_'+strMachine+'.txt'
            mutex_file      = os.path.join(method_path, mutex_file_full)

            if os.path.isfile(res_file): 
                count += 1            
                continue
            elif hcu.is_file(method_path, mutex_file_part) and \
              not hcu.is_file(method_path, mutex_file_part+'_'+socket.gethostname() ): 
                print "Mutex file exists"
                continue
            ## elif os.path.isfile(mutex_file): continue
            os.system('touch '+mutex_file)

            preprocessData(subject_names, task_name, processed_data_path, processed_data_path, \
                           renew=data_renew, downSampleSize=downSampleSize)

            (truePos, falseNeg, trueNeg, falsePos)\
              = evaluation(task_name, processed_data_path, nSet=nSet, nState=nState, cov_mult=cov_mult,\
                           anomaly_offset=anomaly_offset, check_method=method,\
                           hmm_renew=hmm_renew, viz=False, verbose=True)


            truePositiveRate = float(truePos) / float(truePos + falseNeg) * 100.0
            if trueNeg == 0 and falsePos == 0:            
                trueNegativeRate = "Not available"
            else:
                trueNegativeRate = float(trueNeg) / float(trueNeg + falsePos) * 100.0
                
            print 'True Negative Rate:', trueNegativeRate, 'True Positive Rate:', truePositiveRate
                           
            if truePos!=-1 :                 
                d = {}
                d['subject'] = subject_name
                d['tp'] = truePos
                d['fn'] = falseNeg
                d['tn'] = trueNeg
                d['fp'] = falsePos
                d['nSet'] = nSet

                try:
                    ut.save_pickle(d,res_file)        
                except:
                    print "There is already the targeted pkl file"
            else:
                target_file = os.path.join(method_path, task_name+'_dataSet_%d_eval_'+str(idx) ) 
                for j in xrange(nSet):
                    os.system('rm '+target_file % j)
                

            os.system('rm '+mutex_file)
            print "-----------------------------------------------"

            if truePos==-1: 
                print "truePos is -1"
                sys.exit()

    if count == len(check_methods)*len(subject_names):
        print "#############################################################################"
        print "All file exist ", count
        print "#############################################################################"        
    else:
        return
                

def evaluation(task_name, processed_data_path, nSet=1, nState=20, cov_mult=5.0, anomaly_offset=0.0,\
               check_method='progress', hmm_renew=False, save_pdf=False, viz=False, verbose=False):

    tot_truePos = 0
    tot_falseNeg = 0
    tot_trueNeg = 0 
    tot_falsePos = 0

    for i in xrange(nSet):        
        target_file = os.path.join(processed_data_path, task_name+'_dataSet_'+str(i) )                    
        if os.path.isfile(target_file) is not True: 
            print "There is no saved data"
            sys.exit()

        data_dict = ut.load_pickle(target_file)
        if viz: visualization_raw_data(data_dict, save_pdf=save_pdf)

        # training set
        trainingData, param_dict = extractLocalFeature(data_dict['trainData'], feature_list, local_range)

        # test set
        normalTestData, _ = extractLocalFeature(data_dict['normalTestData'], feature_list, local_range, \
                                                param_dict=param_dict)        
        abnormalTestData, _ = extractLocalFeature(data_dict['abnormalTestData'], feature_list, local_range, \
                                                param_dict=param_dict)

        print "======================================"
        print "Training data: ", np.shape(trainingData)
        print "Normal test data: ", np.shape(normalTestData)
        print "Abnormal test data: ", np.shape(abnormalTestData)
        print "======================================"

        if True: visualization_hmm_data(feature_list, trainingData=trainingData, \
                                        normalTestData=normalTestData,\
                                        abnormalTestData=abnormalTestData, save_pdf=save_pdf)        

        # training hmm
        nEmissionDim = len(trainingData)
        detection_param_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'.pkl')

        ml = hmm.learning_hmm_multi_n(nState, nEmissionDim, verbose=True)

        print "Start to fit hmm", np.shape(trainingData)
        ret = ml.fit(trainingData, cov_mult=[cov_mult]*nEmissionDim**2, ml_pkl=detection_param_pkl, \
                     use_pkl=hmm_renew)

        if ret == 'Failure': 
            print "-------------------------"
            print "HMM returned failure!!   "
            print "-------------------------"
            return (-1,-1,-1,-1)


        ## minThresholds = None                  
        ## if hmm_renew:
        ##     minThresholds1 = tuneSensitivityGain(ml, trainingData, method=check_method, verbose=verbose)
        ##     ## minThresholds2 = tuneSensitivityGain(ml, thresTestData, method=check_method, verbose=verbose)
        ##     minThresholds = minThresholds1

        ##     if type(minThresholds) == list or type(minThresholds) == np.ndarray:
        ##         for i in xrange(len(minThresholds1)):
        ##             if minThresholds1[i] < minThresholds2[i]:
        ##                 minThresholds[i] = minThresholds1[i]
        ##     else:
        ##         if minThresholds1 < minThresholds2:
        ##             minThresholds = minThresholds1

        ##     d = ut.load_pickle(detection_param_pkl)
        ##     if d is None: d = {}
        ##     d['minThresholds'] = minThresholds                
        ##     ut.save_pickle(d, detection_param_pkl)                
        ## else:
        ##     d = ut.load_pickle(detection_param_pkl)
        ##     minThresholds = d['minThresholds']
        minThresholds=-5.0

        truePos, falseNeg, trueNeg, falsePos = \
          onlineEvaluation(ml, normalTestData, abnormalTestData, c=minThresholds, verbose=True)
        if truePos == -1: 
            print "Error with task ", task_name
            print "Error with nSet ", i
            print "Error with crossEval ID: ", crossEvalID
            return (-1,-1,-1,-1)

        tot_truePos += truePos
        tot_falseNeg += falseNeg
        tot_trueNeg += trueNeg 
        tot_falsePos += falsePos
            
    truePositiveRate = float(tot_truePos) / float(tot_truePos + tot_falseNeg) * 100.0
    if tot_trueNeg == 0 and tot_falsePos == 0:
        trueNegativeRate = "not available"
    else:
        trueNegativeRate = float(tot_trueNeg) / float(tot_trueNeg + tot_falsePos) * 100.0
    print "------------------------------------------------"
    print "Total set of data: ", nSet
    print "------------------------------------------------"
    print 'True Negative Rate:', trueNegativeRate, 'True Positive Rate:', truePositiveRate
    print "------------------------------------------------"

    return (tot_truePos, tot_falseNeg, tot_trueNeg, tot_falsePos)
        
        ## tp_l = []
        ## fn_l = []
        ## fp_l = []
        ## tn_l = []
        ## ths_l = []

        ## # evaluation
        ## threshold_list = -(np.logspace(-1.0, 1.5, nThres, endpoint=True)-1.0 )        
        ## ## threshold_list = [-5.0]
        ## for ths in threshold_list:        
        ##     tp, fn, tn, fp = onlineEvaluation(ml, normalTestData, abnormalTestData, c=ths, 
        ##                                       verbose=True)
        ##     if tp == -1:
        ##         tp_l.append(0)
        ##         fn_l.append(0)
        ##         fp_l.append(0)
        ##         tn_l.append(0)
        ##         ths_l.append(ths)
        ##     else:                       
        ##         tp_l.append(tp)
        ##         fn_l.append(fn)
        ##         fp_l.append(fp)
        ##         tn_l.append(tn)
        ##         ths_l.append(ths)

        ## dd = {}
        ## dd['fn_l']    = fn_l
        ## dd['tn_l']    = tn_l
        ## dd['tp_l']    = tp_l
        ## dd['fp_l']    = fp_l
        ## dd['ths_l']   = ths_l

        ## try:
        ##     ut.save_pickle(dd,res_file)        
        ## except:
        ##     print "There is the targeted pkl file"

    
    
                
def onlineEvaluation(hmm, normalTestData, abnormalTestData, c=-5, verbose=False):
    truePos = 0
    trueNeg = 0
    falsePos = 0
    falseNeg = 0

    # positive is anomaly
    # negative is non-anomaly
    if verbose: print '\nBeginning anomaly testing for test set\n'

    # for normal test data
    if normalTestData != []:    
        for i in xrange(len(normalTestData[0])):
            if verbose: print 'Anomaly Error for test set ', i

            for j in range(20, len(normalTestData[0][i])):

                try:    
                    anomaly, error = hmm.anomaly_check(normalTestData[:][i][:j], c)
                except:
                    print "anomaly_check failed: ", i, j
                    ## return (-1,-1,-1,-1)
                    falsePos += 1
                    break

                if np.isnan(error):
                    print "anomaly check returned nan"
                    falsePos += 1
                    break
                    ## return (-1,-1,-1,-1)

                if verbose: print "Normal: ", j, " => ", anomaly, error

                # This is a successful nonanomalous attempt
                if anomaly:
                    falsePos += 1
                    if verbose: print 'Success Test', i,',',j, ' in ',len(normalTestData[0][i]), ' |', anomaly, 
                    error
                    break
                elif j == len(normalTestData[0][i]) - 1:
                    trueNeg += 1
                    break


    # for abnormal test data
    for i in xrange(len(abnormalTestData[0])):
        if verbose: print 'Anomaly Error for test set ', i

        for j in range(20, len(abnormalTestData[0][i])):
            try:                    
                anomaly, error = hmm.anomaly_check(abnormalTestData[:][i][:j], c)
            except:
                truePos += 1
                break

            if verbose: print anomaly, error
                
            if anomaly:
                truePos += 1
                break
            elif j == len(abnormalTestData[0][i]) - 1:
                falseNeg += 1
                if verbose: print 'Failure Test', i,',',j, ' in ',len(abnormalTestData[0][i]), ' |', anomaly, error
                break

    return truePos, falseNeg, trueNeg, falsePos

        
def data_plot(subject_names, task_name, raw_data_path, processed_data_path, \
              nSet=1, downSampleSize=200, \
              local_range=0.3, rf_center='kinEEPos', \
              success_viz=True, failure_viz=False, \
              raw_viz=False, interp_viz=False, save_pdf=False, \
              successData=False, failureData=True,\
              ## trainingData=True, normalTestData=False, abnormalTestData=False,\
              modality_list=['audio'], data_renew=False, verbose=False):    

    success_list, failure_list = getSubjectFileList(raw_data_path, subject_names, task_name)

    for idx, file_list in enumerate([success_list, failure_list]):
        if idx == 0 and successData is not True: continue
        elif idx == 1 and failureData is not True: continue        

        ## fig = plt.figure('loadData')                        
        # loading and time-sync
        if idx == 0:
            if verbose: print "Load success data"
            data_pkl = os.path.join(processed_data_path, subject+'_'+task+'_success_'+rf_center+\
                                    '_'+str(local_range))
            raw_data_dict, interp_data_dict = loadData(success_list, isTrainingData=False,
                                                       downSampleSize=downSampleSize,\
                                                       local_range=local_range, rf_center=rf_center,\
                                                       renew=data_renew, save_pkl=data_pkl, verbose=verbose)
        else:
            if verbose: print "Load failure data"
            data_pkl = os.path.join(processed_data_path, subject+'_'+task+'_failure_'+rf_center+\
                                    '_'+str(local_range))
            raw_data_dict, interp_data_dict = loadData(failure_list, isTrainingData=False,
                                                       downSampleSize=downSampleSize,\
                                                       local_range=local_range, rf_center=rf_center,\
                                                       renew=data_renew, save_pkl=data_pkl, verbose=verbose)

        ## plt.show()
        ## sys.exit()
                                                       
        if verbose: print "Visualize data"
        count       = 0
        nPlot       = len(modality_list)
        time_lim    = [0, 16]
   
        if raw_viz: target_dict = raw_data_dict
        else: target_dict = interp_data_dict

        fig = plt.figure('all')

        for modality in modality_list:
            count +=1

            if 'audio' in modality:
                time_list = target_dict['audioTimesList']
                data_list = target_dict['audioPowerList']

            if 'kinematics' in modality:
                time_list = target_dict['kinTimesList']
                data_list = target_dict['kinVelList']

                # distance
                new_data_list = []
                for d in data_list:
                    new_data_list.append( np.linalg.norm(d, axis=0) )
                data_list = new_data_list

            if 'ft' in modality:
                time_list = target_dict['ftTimesList']
                data_list = target_dict['ftForceList']

                # distance
                new_data_list = []
                for d in data_list:
                    new_data_list.append( np.linalg.norm(d, axis=0) )
                data_list = new_data_list

            if 'vision' in modality:
                time_list = target_dict['visionTimesList']
                data_list = target_dict['visionPosList']

                # distance
                new_data_list = []
                for d in data_list:                    
                    new_data_list.append( np.linalg.norm(d, axis=0) )
                data_list = new_data_list

            if 'pps' in modality:
                time_list = target_dict['ppsTimesList']
                data_list1 = target_dict['ppsLeftList']
                data_list2 = target_dict['ppsRightList']

                # magnitude
                new_data_list = []
                for i in xrange(len(data_list1)):
                    d1 = np.array(data_list1[i])
                    d2 = np.array(data_list2[i])
                    d = np.vstack([d1, d2])
                    new_data_list.append( np.sum(d, axis=0) )

                data_list = new_data_list

            if 'fabric' in modality:
                time_list = target_dict['fabricTimesList']
                ## data_list = target_dict['fabricValueList']
                data_list = target_dict['fabricMagList']


                ## for ii, d in enumerate(data_list):
                ##     print np.max(d), target_dict['fileNameList'][ii]

                ## # magnitude
                ## new_data_list = []
                ## for d in data_list:

                ##     # d is 3xN-length in which each element has multiple float values
                ##     sample = []
                ##     if len(d) != 0 and len(d[0]) != 0:
                ##         for i in xrange(len(d[0])):
                ##             if d[0][i] == []:
                ##                 sample.append( 0 )
                ##             else:                                                               
                ##                 s = np.array([d[0][i], d[1][i], d[2][i]])
                ##                 v = np.mean(np.linalg.norm(s, axis=0)) # correct?
                ##                 sample.append(v)
                ##     else:
                ##         print "WRONG data size in fabric data"
                        
                ##     new_data_list.append(sample)
                ## data_list = new_data_list

                ## fig_fabric = plt.figure('fabric')
                ## ax_fabric = fig_fabric.add_subplot(111) #, projection='3d')
                ## for d in data_list:
                ##     color = colors.next()
                ##     for i in xrange(len(d[0])):
                ##         if d[0][i] == []: continue
                ##         ax_fabric.scatter(d[1][i], d[0][i], c=color)
                ##         ## ax_fabric.scatter(d[0][i], d[1][i], d[2][i])
                ## ax_fabric.set_xlabel('x')
                ## ax_fabric.set_ylabel('y')
                ## ## ax_fabric.set_zlabel('z')
                ## if save_pdf is False:
                ##     plt.show()
                ## else:
                ##     fig_fabric.savefig('test_fabric.pdf')
                ##     fig_fabric.savefig('test_fabric.png')
                ##     os.system('mv test*.p* ~/Dropbox/HRL/')

            ax = fig.add_subplot(nPlot*100+10+count)
            if idx == 0:
                color = 'b'
            else:
                color = 'r'

            if raw_viz:
                combined_time_list = []

                ## for t in time_list:
                ##     temp = np.array(t[1:])-np.array(t[:-1])
                ##     combined_time_list.append([ [0.0]  + list(temp)] )
                ##     print modality, " : ", np.mean(temp), np.std(temp), np.max(temp)
                ##     ## ax.plot(temp, label=modality)

                for i in xrange(len(time_list)):
                    if len(time_list[i]) > len(data_list[i]):
                        ax.plot(time_list[i][:len(data_list[i])], data_list[i], c=color)
                    else:
                        ax.plot(time_list[i], data_list[i][:len(time_list[i])], c=color)                    
            else:
                interp_time = np.linspace(time_lim[0], time_lim[1], num=downSampleSize)
                
                for i in xrange(len(data_list)):
                    ax.plot(interp_time, data_list[i], c=color)                
                    ## for j in xrange(len(data_list[i])):
                    ##     ax.scatter([j], data_list[i][j])

            ax.set_xlim(time_lim)
            ax.set_title(modality)
    plt.tight_layout(pad=0.1, w_pad=0.5, h_pad=0.0)

    if save_pdf is False:
        plt.show()
    else:
        fig.savefig('test.pdf')
        fig.savefig('test.png')
        os.system('mv test.p* ~/Dropbox/HRL/')


    ## # training set
    ## trainingData, param_dict = extractLocalFeature(data_dict['trainData'], feature_list, local_range)

    ## # test set
    ## normalTestData, _ = extractLocalFeature(data_dict['normalTestData'], feature_list, local_range, \
    ##                                         param_dict=param_dict)        
    ## abnormalTestData, _ = extractLocalFeature(data_dict['abnormalTestData'], feature_list, local_range, \
    ##                                         param_dict=param_dict)

    ## print "======================================"
    ## print "Training data: ", np.shape(trainingData)
    ## print "Normal test data: ", np.shape(normalTestData)
    ## print "Abnormal test data: ", np.shape(abnormalTestData)
    ## print "======================================"

    ## visualization_hmm_data(feature_list, trainingData=trainingData, \
    ##                        normalTestData=normalTestData,\
    ##                        abnormalTestData=abnormalTestData, save_pdf=save_pdf)        
    
            
def feature_extraction(subject_names, task_name, raw_data_path, processed_data_path, rf_center, local_range, \
             nSet=1, downSampleSize=200, success_viz=False, failure_viz=False, \
             save_pdf=False, solid_color=True, \
             feature_list=['crossmodal_targetRelativeDist'], data_renew=False):

    save_pkl = os.path.join(processed_data_path, 'pca_'+rf_center+'_'+str(local_range) )
    if os.path.isfile(save_pkl) and data_renew is not True:
        data_dict = ut.load_pickle(save_pkl)
        allData          = data_dict['allData']
        trainingData     = data_dict['trainingData'] 
        abnormalTestData = data_dict['abnormalTestData']
        abnormalTestNameList = data_dict['abnormalTestNameList']
        param_dict       = data_dict['param_dict']
    else:
        ## data_renew = False #temp
        
        success_list, failure_list = getSubjectFileList(raw_data_path, subject_names, task_name)

        # loading and time-sync    
        all_data_pkl     = os.path.join(processed_data_path, subject+'_'+task+'_all_'+rf_center+\
                                        '_'+str(local_range))
        _, all_data_dict = loadData(success_list+failure_list, isTrainingData=False,
                                    downSampleSize=downSampleSize,\
                                    local_range=local_range, rf_center=rf_center,\
                                    ##global_data=True,\
                                    renew=data_renew, save_pkl=all_data_pkl)

        success_data_pkl     = os.path.join(processed_data_path, subject+'_'+task+'_success_'+rf_center+\
                                            '_'+str(local_range))
        _, success_data_dict = loadData(success_list, isTrainingData=True,
                                        downSampleSize=downSampleSize,\
                                        local_range=local_range, rf_center=rf_center,\
                                        renew=data_renew, save_pkl=success_data_pkl)

        failure_data_pkl     = os.path.join(processed_data_path, subject+'_'+task+'_failure_'+rf_center+\
                                            '_'+str(local_range))
        _, failure_data_dict = loadData(failure_list, isTrainingData=False,
                                        downSampleSize=downSampleSize,\
                                        local_range=local_range, rf_center=rf_center,\
                                        renew=data_renew, save_pkl=failure_data_pkl)

        # data set
        allData, param_dict = extractLocalFeature(all_data_dict, feature_list)
        trainingData, _     = extractLocalFeature(success_data_dict, feature_list, param_dict=param_dict)
        abnormalTestData, _ = extractLocalFeature(failure_data_dict, feature_list, param_dict=param_dict)

        allData          = np.array(allData)
        trainingData     = np.array(trainingData)
        abnormalTestData = np.array(abnormalTestData)

        data_dict = {}
        data_dict['allData'] = allData
        data_dict['trainingData'] = trainingData
        data_dict['abnormalTestData'] = abnormalTestData
        data_dict['abnormalTestNameList'] = abnormalTestNameList = failure_data_dict['fileNameList']
        data_dict['param_dict'] = param_dict
        ut.save_pickle(data_dict, save_pkl)


    ## # test
    ## success_list, failure_list = getSubjectFileList(raw_data_path, subject_names, task_name)
    ## _, success_data_dict = loadData(success_list, isTrainingData=True,
    ##                                 downSampleSize=downSampleSize,\
    ##                                 local_range=local_range, rf_center=rf_center)
    ## trainingData, _      = extractLocalFeature(success_data_dict, feature_list, \
    ##                                            param_dict=data_dict['param_dict'])
    ## sys.exit()
    
    ## All data
    nPlot = None
    feature_names = np.array(param_dict['feature_names'])

    if True:

        # 1) exclude stationary data
        thres = 0.025
        n,m,k = np.shape(trainingData)
        diff_all_data = trainingData[:,:,1:] - trainingData[:,:,:-1]
        add_idx    = []
        remove_idx = []
        std_list = []
        for i in xrange(n):
            std = np.max(np.max(diff_all_data[i], axis=1))
            std_list.append(std)
            if  std < thres: remove_idx.append(i)
            else: add_idx.append(i)

        allData          = allData[add_idx]
        trainingData     = trainingData[add_idx]
        abnormalTestData = abnormalTestData[add_idx]
        feature_names    = feature_names[add_idx]

        print "--------------------------------"
        print "STD list: ", std_list
        print "Add_idx: ", add_idx
        print "Remove idx: ", remove_idx
        print "--------------------------------"
        ## sys.exit()


    # -------------------- Display ---------------------
    fig = None
    if success_viz:
        fig = plt.figure()
        n,m,k = np.shape(trainingData)
        if nPlot is None:
            if n%2==0: nPlot = n
            else: nPlot = n+1

        for i in xrange(n):
            ax = fig.add_subplot((nPlot/2)*100+20+i)
            if solid_color: ax.plot(trainingData[i].T, c='b')
            else: ax.plot(trainingData[i].T)
            ax.set_title( feature_names[i] )

    if failure_viz:
        if fig is None: fig = plt.figure()
        n,m,k = np.shape(abnormalTestData)
        if nPlot is None:
            if n%2==0: nPlot = n
            else: nPlot = n+1

        for i in xrange(n):
            ax = fig.add_subplot((nPlot/2)*100+20+i)
            if solid_color: ax.plot(abnormalTestData[i].T, c='r')
            else: ax.plot(abnormalTestData[i].T)
            ax.set_title( feature_names[i] )

    if success_viz or failure_viz:
        plt.tight_layout(pad=3.0, w_pad=0.5, h_pad=0.5)

        if save_pdf:
            fig.savefig('test.pdf')
            fig.savefig('test.png')
            os.system('cp test.p* ~/Dropbox/HRL/')        
        else:
            plt.show()


    print "---------------------------------------------------"
    print np.shape(trainingData), np.shape(abnormalTestData)
    print "---------------------------------------------------"

    return allData, trainingData, abnormalTestData


def pca_plot(subject_names, task_name, raw_data_path, processed_data_path, rf_center, local_range, \
             nSet=1, downSampleSize=200, success_viz=True, failure_viz=False, \
             save_pdf=False, \
             feature_list=['crossmodal_targetRelativeDist'], data_renew=False):


    allData, trainingData, abnormalTestData = feature_extraction(subject_names, task_name, raw_data_path, \
                                                                 processed_data_path, rf_center, local_range,\
                                                                 nSet=nSet, \
                                                                 downSampleSize=downSampleSize, \
                                                                 feature_list=feature_list, \
                                                                 data_renew=data_renew)

    print "---------------------------------------------------"
    print np.shape(trainingData), np.shape(abnormalTestData)
    print "---------------------------------------------------"
    
    m,n,k = np.shape(allData)
    all_data_array = None
    for i in xrange(n):
        for j in xrange(k):
            if all_data_array is None: all_data_array = allData[:,i,j]
            else: all_data_array = np.vstack([all_data_array, allData[:,i,j]])
                
    m,n,k = np.shape(trainingData)
    success_data_array = None
    for i in xrange(n):
        for j in xrange(k):
            if success_data_array is None: success_data_array = trainingData[:,i,j]
            else: success_data_array = np.vstack([success_data_array, trainingData[:,i,j]])

    m,n,k = np.shape(abnormalTestData)
    failure_data_array = None
    for i in xrange(n):
        for j in xrange(k):
            if failure_data_array is None: failure_data_array = abnormalTestData[:,i,j]
            else: failure_data_array = np.vstack([failure_data_array, abnormalTestData[:,i,j]])

    #--------------------- Parameters -------------------------------
    fig = plt.figure()
    # step size in the mesh
    h = .01

    # ------------------- Visualization using different PCA? --------
    dr = {}
    from sklearn.manifold import Isomap
    ## dr['isomap4'] = Isomap(n_neighbors=4, n_components=2)
    ## dr['isomap5'] = Isomap(n_neighbors=5, n_components=2)
    dr['isomap4'] = Isomap(n_neighbors=4, n_components=2)
    dr['isomap7'] = Isomap(n_neighbors=7, n_components=2)
    from sklearn.decomposition import KernelPCA # Too bad
    dr['kpca_gamma5'] = KernelPCA(n_components=2, kernel="linear", gamma=5.0)
    dr['kpca_gamma2'] = KernelPCA(n_components=2, kernel="rbf", gamma=2.0)
    ## dr['kpca_gamma3'] = KernelPCA(n_components=2, kernel="sigmoid", gamma=0.3)
    ## dr['kpca_gamma5'] = KernelPCA(n_components=2, kernel="cosine", gamma=0.3)
    from sklearn.manifold import LocallyLinearEmbedding # Too bad
    ## dr['lle3'] = LocallyLinearEmbedding(n_neighbors=3, n_components=2, eigen_solver='dense')
    ## dr['lle5'] = LocallyLinearEmbedding(n_neighbors=5, n_components=2, eigen_solver='dense')
    ## dr['lle7'] = LocallyLinearEmbedding(n_neighbors=7, n_components=2, eigen_solver='dense')

    bv = {}
    from sklearn import svm
    bv['svm_gamma1'] = svm.OneClassSVM(nu=0.1, kernel='rbf', gamma=0.4)
    bv['svm_gamma2'] = svm.OneClassSVM(nu=0.1, kernel='rbf', gamma=2.0)
    bv['svm_gamma3'] = svm.OneClassSVM(nu=0.1, kernel='rbf', gamma=3.0)
    bv['svm_gamma4'] = svm.OneClassSVM(nu=0.1, kernel='rbf', gamma=4.0)


    # title for the plots
    for idx, key in enumerate(dr.keys()):
    ## for idx, key in enumerate(bv.keys()):
        ml  = dr[key]
        clf = bv['svm_gamma1'] #[key]
        plt.subplot(2, 2, idx + 1)

        # --------------- Dimension Reduction --------------------------
        success_x = ml.fit_transform(success_data_array)
        success_y = [1.0]*len(success_data_array)

        failure_x = ml.transform(failure_data_array)
        failure_y = [0.0]*len(failure_data_array)

        all_x = ml.transform(all_data_array)

        # ---------------- Boundary Visualization ----------------------
        clf.fit(success_x, success_y)

        # create a mesh to plot in
        x_min, x_max = all_x[:, 0].min() - 0.2, all_x[:, 0].max() + 0.2
        y_min, y_max = all_x[:, 1].min() - 0.2, all_x[:, 1].max() + 0.2
        xx, yy = np.meshgrid(np.arange(x_min, x_max, h),
                             np.arange(y_min, y_max, h))
        
        Z = clf.decision_function(np.c_[xx.ravel(), yy.ravel()])

        # Put the result into a color plot
        Z = Z.reshape(xx.shape)

        plt.contourf(xx, yy, Z, levels=np.linspace(Z.min(), 0, 7), cmap=plt.cm.Blues_r)
        plt.contourf(xx, yy, Z, levels=[0, Z.max()], colors='orange')
        plt.axis('off')

        plt.title(key)

        # ---------------- Sample Visualization ------------------------
        if success_viz:
            plt.scatter(success_x[:,0], success_x[:,1], c='b', label=None)

        # Abnormal
        if failure_viz:
            legend_handles = []
            m,n,k = np.shape(abnormalTestData)
            for i in xrange(n):
                data_array = None
                for j in xrange(k):
                    if data_array is None: data_array = abnormalTestData[:,i,j]
                    else: data_array = np.vstack([data_array, abnormalTestData[:,i,j]])

                res = ml.transform(data_array)
                ## color = colors.next()

                cause = os.path.split(abnormalTestNameList[i])[-1].split('.pkl')[0].split('failure_')[-1]
                if 'unrelated_sound' in cause: color = 'k'
                elif 'forcesound' == cause: color = 'r'
                elif 'force' in cause: color = 'm'
                elif 'sound' in cause: color = 'g'
                else: color = 'k'
                    
                
                plt.scatter(res[:,0], res[:,1], c=color, marker='x', label=cause)
                ## legend_handles.append( h )

            ## plt.legend(loc='upper right') #handles=legend_handles) #loc='upper right', 
            
    if save_pdf:
        fig.savefig('test.pdf')
        fig.savefig('test.png')
        os.system('cp test.p* ~/Dropbox/HRL/')        
    else:
        plt.show()


def space_time_field_plot(subject_names, task_name, raw_data_path, processed_data_path, \
                          nSet=1, downSampleSize=200, success_viz=True, failure_viz=False, \
                          save_pdf=False, data_renew=False):

    
    data_pkl = os.path.join(processed_data_path, 'test.pkl')
    if os.path.isfile(data_pkl):
        data_dict = ut.load_pickle(data_pkl)

        fileNameList     = data_dict['fileNameList']
        # Audio
        audioTimesList   = data_dict['audioTimesList']
        audioAzimuthList = data_dict['audioAzimuthList']
        audioPowerList   = data_dict['audioPowerList']

        # Fabric force
        fabricTimesList  = data_dict['fabricTimesList']
        fabricCenterList = data_dict['fabricCenterList']
        fabricNormalList = data_dict['fabricNormalList']
        fabricValueList  = data_dict['fabricValueList']
        min_audio_power  = data_dict['min_audio_power']
    else:
        success_list, failure_list = getSubjectFileList(raw_data_path, subject_names, task_name)

        #-------------------------------- Success -----------------------------------
        success_data_pkl     = os.path.join(processed_data_path, subject+'_'+task+'_success')
        raw_data_dict, _ = loadData(success_list, isTrainingData=False,
                                    downSampleSize=downSampleSize,\
                                    global_data=True,\
                                    renew=data_renew, save_pkl=success_data_pkl)

        # Audio
        audioTimesList   = raw_data_dict['audioTimesList']
        audioAzimuthList = raw_data_dict['audioAzimuthList']
        audioPowerList   = raw_data_dict['audioPowerList']

        ## min_audio_power = np.mean( [np.mean(x) for x in audioPowerList] )
        min_audio_power = np.min( [np.max(x) for x in audioPowerList] )

        #-------------------------------- Failure -----------------------------------
        failure_data_pkl     = os.path.join(processed_data_path, subject+'_'+task+'_failure')
        raw_data_dict, _ = loadData(failure_list, isTrainingData=False,
                                    downSampleSize=downSampleSize,\
                                    global_data=True,\
                                    renew=data_renew, save_pkl=failure_data_pkl)

        fileNameList     = raw_data_dict['fileNameList']
        # Audio
        audioTimesList   = raw_data_dict['audioTimesList']
        audioAzimuthList = raw_data_dict['audioAzimuthList']
        audioPowerList   = raw_data_dict['audioPowerList']

        # Fabric force
        fabricTimesList  = raw_data_dict['fabricTimesList']
        fabricCenterList = raw_data_dict['fabricCenterList']
        fabricNormalList = raw_data_dict['fabricNormalList']
        fabricValueList  = raw_data_dict['fabricValueList']

        data_dict = {}
        data_dict['fileNameList'] = fileNameList
        # Audio
        data_dict['audioTimesList'] = audioTimesList
        data_dict['audioAzimuthList'] = audioAzimuthList
        data_dict['audioPowerList'] = audioPowerList

        # Fabric force
        data_dict['fabricTimesList'] = fabricTimesList
        data_dict['fabricCenterList'] = fabricCenterList
        data_dict['fabricNormalList'] = fabricNormalList
        data_dict['fabricValueList'] = fabricValueList

        data_dict['min_audio_power'] = min_audio_power
        ut.save_pickle(data_dict, data_pkl)


    nSample = len(audioTimesList)
    azimuth_interval = 2.0
    audioSpace = np.arange(-90, 90, azimuth_interval)
    max_audio_power      = 5000 #np.median( [np.max(x) for x in audioPowerList] )
    max_fabric_value     = 3.0
    max_audio_azimuth  = 15.0
    max_audio_delay    = 1.0
    max_fabric_azimuth = 10.0
    max_fabric_delay   = 1.0

    # gaussian kernel
    # weibull kernel
    ## from astropy.convolution import Gaussian1DKernel
    ## from astropy.convolution import Gaussian2DKernel
    ## from scipy.stats import norm, gumbel_l
    
    for i in xrange(nSample):
        fig = plt.figure(figsize=(12,8))

        # time
        downSampleSize = 1000
        max_time1 = np.max(audioTimesList[i])
        max_time2 = np.max(fabricTimesList[i])
        if max_time1 > max_time2: # min of max time
            max_time = max_time2
        else:
            max_time = max_time1            
        new_times     = np.linspace(0.0, max_time, downSampleSize)
        time_interval = new_times[1]-new_times[0]

        # define the size of kernel
        ## audio_kernel_x = int(np.floor(max_audio_delay/time_interval))*2+1
        ## audio_kernel_y = int(np.floor(max_audio_azimuth/azimuth_interval))*2+1
        ## fabric_kernel_x = int(np.floor(max_fabric_delay/time_interval))*2+1
        ## fabric_kernel_y = int(np.floor(max_fabric_azimuth/azimuth_interval))*2+1

        ## max_gaussian_x = norm.ppf(0.682)
        ## max_audio_kernel_x = int(np.floor(max_gaussian_x*max_audio_delay_range/time_interval))*2+1
        ## max_audio_kernel_y = int(np.floor(max_gaussian_x*max_audio_azimuth_range/azimuth_interval))*2+1
        ## max_fabric_kernel_x = int(np.floor(max_gaussian_x*max_fabric_delay_range/time_interval))*2+1
        ## max_fabric_kernel_y = int(np.floor(max_gaussian_x*max_fabric_azimuth_range/azimuth_interval))*2+1
        ## if max_kernel_x%2==0: max_kernel_x+=1
        ## if max_kernel_y%2==0: max_kernel_y+=1
        ## print max_fabric_kernel_x, max_fabric_kernel_y

        # -------------------------------------------------------------
        # ------------------- Auditory --------------------------------
        audioTime    = audioTimesList[i]
        audioAzimuth = audioAzimuthList[i]
        audioPower   = audioPowerList[i]

        discrete_azimuth_array = hdl.discretization_array(audioAzimuth, [-90,90], len(audioSpace))
        discrete_time_array    = hdl.discretization_array(audioTime, [0.0, max_time], len(new_times))

        image = np.zeros((len(new_times),len(audioSpace)))
        last_time_idx = -1
        for j, time_idx in enumerate(discrete_time_array):
            if time_idx < 0: time_idx = 0
            if time_idx >= len(new_times): time_idx=len(new_times)-1
                
            s = np.zeros(len(audioSpace))
            if audioPower[j] > max_audio_power:
                s[discrete_azimuth_array[j]] = 1.0
            elif audioPower[j] > min_audio_power:                
                s[discrete_azimuth_array[j]] = ((audioPower[j]-min_audio_power)/
                                                (max_audio_power-min_audio_power)) #**2

            #
            if last_time_idx == time_idx:
                for k in xrange(len(s)):
                    if image[time_idx,k] < s[k]: image[time_idx,k] = s[k]
            else:
                # image: (Ang, N)
                if len(np.shape(s))==1: s = np.array([s])
                image[time_idx,:] = s
            last_time_idx = time_idx

        image = image.T
        ax = fig.add_subplot(3,3,1)
        plot_space_time_distribution(ax, image, new_times, audioSpace, \
                                     x_label='Time [msec]', y_label='Azimuth [deg]', title='Auditory RF')

        # -------------------------------------------------------------
        # Convoluted data
        ## g = Gaussian1DKernel(max_audio_kernel_y) # 8*std
        ## a = g.array
        gaussian_2D_kernel = get_space_time_kernel(max_audio_delay, max_audio_azimuth, \
                                                   time_interval, azimuth_interval)
        gaussian_2D_kernel = CustomKernel(gaussian_2D_kernel)

        # For color scale
        image_min = np.amin(image.flatten())
        image_max = np.amax(image.flatten())        
        image = convolve(image, gaussian_2D_kernel, boundary='extend')
        if image_max != image_min:
            image = (image-image_min)/(image_max-image_min)#*image_max
        else:
            image = (image-image_min)
        ## image[0,0] = 1.0
        
        ax = fig.add_subplot(3,3,4)        
        plot_space_time_distribution(ax, image, new_times, audioSpace, \
                                     x_label='Time [msec]', y_label='Azimuth [deg]', title='Auditory RF')
        image1 = copy.copy(image)

        
        # -------------------------------------------------------------
        ## Clustering
        ax = fig.add_subplot(3,3,7)
        clustered_image, audio_label_list = space_time_clustering(image, max_audio_delay, max_audio_azimuth, \
                                                                 azimuth_interval, time_interval, 4)
        plot_space_time_distribution(ax, clustered_image, new_times, audioSpace, \
                                     x_label='Time [msec]', y_label='Azimuth [deg]', title='Auditory RF')
        clustered_audio_image = copy.copy(clustered_image)

        # -------------------------------------------------------------
        # ------------------- Fabric Force ----------------------------
        fabricTime   = fabricTimesList[i]
        fabricCenter = fabricCenterList[i]
        fabricValue  = fabricValueList[i]

        ## discrete_azimuth_array = hdl.discretization_array(audioAzimuth, [-90,90], len(audioSpace))
        discrete_time_array    = hdl.discretization_array(fabricTime, [0.0, max_time], len(new_times))

        image = np.zeros((len(new_times),len(audioSpace)))
        last_time_idx = -1
        for j, time_idx in enumerate(discrete_time_array):
            if time_idx < 0: time_idx = 0
            if time_idx >= len(new_times): time_idx=len(new_times)-1
            s = np.zeros(len(audioSpace))

            # Estimate space
            xyz  = [fabricCenter[0][j], fabricCenter[1][j], fabricCenter[2][j]]
            fxyz = [fabricValue[0][j], fabricValue[1][j], fabricValue[2][j]] 
            for k in xrange(len(xyz[0])):
                if xyz[0][k]==0 and xyz[1][k]==0 and xyz[2][k]==0: continue
                y   = xyz[1][k]/np.linalg.norm( np.array([ xyz[0][k],xyz[1][k],xyz[2][k] ]) )
                ang = np.arcsin(y)*180.0/np.pi 
                mag = np.linalg.norm(np.array([fxyz[0][k],fxyz[1][k],fxyz[2][k]]))

                ang_idx = hdl.discretize_single(ang, [-90,90], len(audioSpace))
                if mag > max_fabric_value:
                    s[ang_idx] = 1.0
                elif mag > 0.0:
                    s[ang_idx] = ((mag-0.0)/(max_fabric_value-0.0))

            #
            if last_time_idx == time_idx:
                ## print "fabrkc: ", np.shape(image), np.shape(s), last_time_idx, time_idx
                for k in xrange(len(s)):
                    if image[time_idx,k] < s[k]: image[time_idx,k] = s[k]
            else:
                # image: (Ang, N)
                if len(np.shape(s))==1: s = np.array([s])
                ## print np.shape(image), time_idx, np.shape(image[time_idx,:]), np.shape(s)
                image[time_idx,:] = s

            # clustering label
            ## for k in xrange(len(z)):
            ##     if z[k,0] > 0.01: X.append([j,k]) #temp # N x Ang

            # For color scale
            ## image[0,0]=1.0
            last_time_idx = time_idx
            
        image = image.T
        ax = fig.add_subplot(3,3,2)
        plot_space_time_distribution(ax, image, new_times, audioSpace, \
                                     x_label='Time [msec]', title='Fabric Skin RF')


        # -------------------------------------------------------------
        # Convoluted data
        gaussian_2D_kernel = get_space_time_kernel(max_fabric_delay, max_fabric_azimuth, \
                                                   time_interval, azimuth_interval)        
        gaussian_2D_kernel = CustomKernel(gaussian_2D_kernel)

        # For color scale
        image_min = np.amin(image.flatten())
        image_max = np.amax(image.flatten())        
        image = convolve(image, gaussian_2D_kernel, boundary='extend')
        if image_max != image_min:
            image = (image-image_min)/(image_max-image_min)#*image_max
        else:
            image = (image-image_min)
        image[0,0] = 1.0

        ax = fig.add_subplot(3,3,5)
        plot_space_time_distribution(ax, image, new_times, audioSpace, \
                                     x_label='Time [msec]', title='Fabric Skin RF')
        image2 = copy.copy(image)



        # -------------------------------------------------------------
        # Clustering
        ax = fig.add_subplot(3,3,8)
        clustered_image, fabric_label_list = space_time_clustering(image, max_fabric_delay , max_fabric_azimuth, \
                                                                  azimuth_interval, time_interval, 4)
        plot_space_time_distribution(ax, clustered_image, new_times, audioSpace, \
                                     x_label='Time [msec]', title='Fabric Skin RF')
        clustered_fabric_image = copy.copy(clustered_image)
                                     
        # -------------------------------------------------------------
        #-----------------Multi modality ------------------------------
        ax = fig.add_subplot(3,3,6)
        image = image1 * image2
        plot_space_time_distribution(ax, image, new_times, audioSpace, \
                                     x_label='Time [msec]', title='Multimodal RF')
                                     
        # -------------------------------------------------------------
        ax = fig.add_subplot(3,3,9)
        ## image = clustered_image1 * clustered_image2
        max_delay   = np.max([max_audio_delay, max_fabric_delay])
        max_azimuth = np.max([max_audio_azimuth, max_fabric_azimuth])
        clustered_image, label_list = space_time_clustering(image, max_fabric_delay , max_fabric_azimuth, \
                                                           azimuth_interval, time_interval, 4)
        plot_space_time_distribution(ax, clustered_image, new_times, audioSpace, \
                                     x_label='Time [msec]', title='Multimodal RF')

        cause = os.path.split(fileNameList[i])[-1].split('.pkl')[0].split('failure_')[-1]
        plt.suptitle('Anomaly: '+cause, fontsize=20)                        
        plt.tight_layout(pad=3.0, w_pad=0.5, h_pad=0.5)
        
        # -------------------------------------------------------------
        # Classification
        # -------------------------------------------------------------
        audio_score = np.zeros((len(audio_label_list)))        
        fabric_score = np.zeros((len(fabric_label_list)))        
        multi_score = np.zeros((len(label_list)))        
        for ii in xrange(len(clustered_image)):
            for jj in xrange(len(clustered_image[ii])):
                # audio
                y = clustered_audio_image[ii,jj]
                if y > 0: audio_score[int(y)-1]+=1
                # fabric
                y = clustered_fabric_image[ii,jj]
                if y > 0: fabric_score[int(y)-1]+=1
                # multimodal
                y = clustered_image[ii,jj]
                if y > 0: multi_score[int(y)-1]+=1

        print "00000000000000000"
        print audio_score
        print fabric_score
        print multi_score
        print "00000000000000000"
        image_area = float(len(clustered_image)*len(clustered_image[0]))
        if np.max(multi_score)/image_area > 0.02:
            print "Force and sound :: ", cause
        else:
            if np.max(audio_score)/image_area > 0.02:
                print "sound :: ", cause
            if np.max(fabric_score)/image_area > 0.02:
                print "Skin contact force :: ", cause
                    
        

        if save_pdf:
            fig.savefig('test.pdf')
            fig.savefig('test.png')
            os.system('cp test.p* ~/Dropbox/HRL/')
            ut.get_keystroke('Hit a key to proceed next')
        else:
            plt.show()

        ## sys.exit()


def plot_space_time_distribution(ax, image, x_range, y_range, x_label=None, y_label=None, title=None):
    ax.imshow(image, aspect='auto', origin='lower', interpolation='none')
    y_tick = np.arange(y_range[0], y_range[-1]+0.0001, 30)
    ax.set_yticks(np.linspace(0, len(image), len(y_tick)))
    ax.set_yticklabels(y_tick)
    x_tick = np.arange(0, x_range[-1], 5.0)
    ax.set_xticks(np.linspace(0, len(image[0]), len(x_tick)))        
    ax.set_xticklabels(x_tick)
    
    if title is not None: ax.set_title(title)
    if x_label is not None: ax.set_xlabel(x_label)
    if y_label is not None: ax.set_ylabel(y_label)
    
    
def offline_classification(subject_names, task_name, raw_data_path, processed_data_path, \
                           nSet=1, downSampleSize=200, \
                           save_pdf=False, data_renew=False):

    
    data_pkl = os.path.join(processed_data_path, 'test.pkl')
    if os.path.isfile(data_pkl):
        data_dict = ut.load_pickle(data_pkl)

        fileNameList     = data_dict['fileNameList']
        # Audio
        audioTimesList   = data_dict['audioTimesList']
        audioAzimuthList = data_dict['audioAzimuthList']
        audioPowerList   = data_dict['audioPowerList']

        # Fabric force
        fabricTimesList  = data_dict['fabricTimesList']
        fabricCenterList = data_dict['fabricCenterList']
        fabricNormalList = data_dict['fabricNormalList']
        fabricValueList  = data_dict['fabricValueList']
        min_audio_power  = data_dict['min_audio_power']
    else:
        success_list, failure_list = getSubjectFileList(raw_data_path, subject_names, task_name)

        #-------------------------------- Success -----------------------------------
        success_data_pkl     = os.path.join(processed_data_path, subject+'_'+task+'_success')
        raw_data_dict, _ = loadData(success_list, isTrainingData=False,
                                    downSampleSize=downSampleSize,\
                                    global_data=True,\
                                    renew=data_renew, save_pkl=success_data_pkl)

        # Audio
        audioTimesList   = raw_data_dict['audioTimesList']
        audioAzimuthList = raw_data_dict['audioAzimuthList']
        audioPowerList   = raw_data_dict['audioPowerList']

        ## min_audio_power = np.mean( [np.mean(x) for x in audioPowerList] )
        min_audio_power = np.min( [np.max(x) for x in audioPowerList] )

        #-------------------------------- Failure -----------------------------------
        failure_data_pkl     = os.path.join(processed_data_path, subject+'_'+task+'_failure')
        raw_data_dict, _ = loadData(failure_list, isTrainingData=False,
                                    downSampleSize=downSampleSize,\
                                    global_data=True,\
                                    renew=data_renew, save_pkl=failure_data_pkl)

        fileNameList     = raw_data_dict['fileNameList']
        # Audio
        audioTimesList   = raw_data_dict['audioTimesList']
        audioAzimuthList = raw_data_dict['audioAzimuthList']
        audioPowerList   = raw_data_dict['audioPowerList']

        # Fabric force
        fabricTimesList  = raw_data_dict['fabricTimesList']
        fabricCenterList = raw_data_dict['fabricCenterList']
        fabricNormalList = raw_data_dict['fabricNormalList']
        fabricValueList  = raw_data_dict['fabricValueList']

        data_dict = {}
        data_dict['fileNameList'] = fileNameList
        # Audio
        data_dict['audioTimesList'] = audioTimesList
        data_dict['audioAzimuthList'] = audioAzimuthList
        data_dict['audioPowerList'] = audioPowerList

        # Fabric force
        data_dict['fabricTimesList'] = fabricTimesList
        data_dict['fabricCenterList'] = fabricCenterList
        data_dict['fabricNormalList'] = fabricNormalList
        data_dict['fabricValueList'] = fabricValueList

        data_dict['min_audio_power'] = min_audio_power
        ut.save_pickle(data_dict, data_pkl)

    # Parameter set
    downSampleSize = 1000

    azimuth_interval = 2.0
    audioSpace = np.arange(-90, 90, azimuth_interval)

    max_audio_azimuth  = 15.0
    max_audio_delay    = 1.0
    max_fabric_azimuth = 10.0
    max_fabric_delay   = 1.0

    max_audio_power    = 5000 #np.median( [np.max(x) for x in audioPowerList] )
    max_fabric_value   = 3.0


    anomaly_list = ['sound', 'force', 'forcesound']
    y_true = []
    y_pred = []
    #
    for i in xrange(len(fileNameList)):

        # time
        max_time1 = np.max(audioTimesList[i])
        max_time2 = np.max(fabricTimesList[i])
        if max_time1 > max_time2: # min of max time
            max_time = max_time2
        else:
            max_time = max_time1            
        new_times     = np.linspace(0.0, max_time, downSampleSize)
        time_interval = new_times[1]-new_times[0]
        
        # ------------------- Data     --------------------------------
        audioTime    = audioTimesList[i]
        audioAzimuth = audioAzimuthList[i]
        audioPower   = audioPowerList[i]

        fabricTime   = fabricTimesList[i]
        fabricCenter = fabricCenterList[i]
        fabricValue  = fabricValueList[i]
        
        # ------------------- Auditory --------------------------------
        discrete_azimuth_array = hdl.discretization_array(audioAzimuth, [-90,90], len(audioSpace))
        discrete_time_array    = hdl.discretization_array(audioTime, [0.0, max_time], len(new_times))

        image = np.zeros((len(new_times),len(audioSpace)))
        last_time_idx = -1
        for j, time_idx in enumerate(discrete_time_array):
            if time_idx < 0: time_idx = 0
            if time_idx >= len(new_times): time_idx=len(new_times)-1
                
            s = np.zeros(len(audioSpace))
            if audioPower[j] > max_audio_power:
                s[discrete_azimuth_array[j]] = 1.0
            elif audioPower[j] > min_audio_power:                
                s[discrete_azimuth_array[j]] = ((audioPower[j]-min_audio_power)/
                                                (max_audio_power-min_audio_power)) #**2

            #
            if last_time_idx == time_idx:
                for k in xrange(len(s)):
                    if image[time_idx,k] < s[k]: image[time_idx,k] = s[k]
            else:
                # image: (Ang, N)
                if len(np.shape(s))==1: s = np.array([s])
                image[time_idx,:] = s
            last_time_idx = time_idx

        image = image.T

        gaussian_2D_kernel = get_space_time_kernel(max_audio_delay, max_audio_azimuth, \
                                                   time_interval, azimuth_interval)
        gaussian_2D_kernel = CustomKernel(gaussian_2D_kernel)
        audio_image = convolve(image, gaussian_2D_kernel, boundary='extend')

        clustered_audio_image, audio_label_list = space_time_clustering(audio_image, max_audio_delay, \
                                                                       max_audio_azimuth, \
                                                                       azimuth_interval, time_interval, 4)

        # ------------------- Fabric Force ----------------------------
        discrete_time_array    = hdl.discretization_array(fabricTime, [0.0, max_time], len(new_times))

        image = np.zeros((len(new_times),len(audioSpace)))
        last_time_idx = -1
        for j, time_idx in enumerate(discrete_time_array):
            if time_idx < 0: time_idx = 0
            if time_idx >= len(new_times): time_idx=len(new_times)-1
            s = np.zeros(len(audioSpace))

            # Estimate space
            xyz  = [fabricCenter[0][j], fabricCenter[1][j], fabricCenter[2][j]]
            fxyz = [fabricValue[0][j], fabricValue[1][j], fabricValue[2][j]] 
            for k in xrange(len(xyz[0])):
                if xyz[0][k]==0 and xyz[1][k]==0 and xyz[2][k]==0: continue
                y   = xyz[1][k]/np.linalg.norm( np.array([ xyz[0][k],xyz[1][k],xyz[2][k] ]) )
                ang = np.arcsin(y)*180.0/np.pi 
                mag = np.linalg.norm(np.array([fxyz[0][k],fxyz[1][k],fxyz[2][k]]))

                ang_idx = hdl.discretize_single(ang, [-90,90], len(audioSpace))
                if mag > max_fabric_value:
                    s[ang_idx] = 1.0
                elif mag > 0.0:
                    s[ang_idx] = ((mag-0.0)/(max_fabric_value-0.0))

            if last_time_idx == time_idx:
                for k in xrange(len(s)):
                    if image[time_idx,k] < s[k]: image[time_idx,k] = s[k]
            else:
                if len(np.shape(s))==1: s = np.array([s])
                image[time_idx,:] = s

            last_time_idx = time_idx
            
        image = image.T

        # Convoluted data
        gaussian_2D_kernel = get_space_time_kernel(max_fabric_delay, max_fabric_azimuth, \
                                                   time_interval, azimuth_interval)        
        gaussian_2D_kernel = CustomKernel(gaussian_2D_kernel)
        fabric_image = convolve(image, gaussian_2D_kernel, boundary='extend')

        clustered_fabric_image, fabric_label_list = space_time_clustering(image, max_fabric_delay , \
                                                                          max_fabric_azimuth, \
                                                                          azimuth_interval, time_interval, 4)

        #-----------------Multi modality ------------------------------
        image = audio_image * fabric_image
        max_delay   = np.max([max_audio_delay, max_fabric_delay])
        max_azimuth = np.max([max_audio_azimuth, max_fabric_azimuth])
        clustered_image, label_list = space_time_clustering(image, max_fabric_delay , max_fabric_azimuth, \
                                                            azimuth_interval, time_interval, 4)


        # -------------------------------------------------------------
        # Classification
        # -------------------------------------------------------------
        audio_score = np.zeros((len(audio_label_list))) if len(audio_label_list) > 0 else [0]       
        fabric_score = np.zeros((len(fabric_label_list))) if len(fabric_label_list) > 0 else [0]       
        multi_score = np.zeros((len(label_list))) if len(label_list) > 0 else [0]      
        for ii in xrange(len(clustered_image)):
            for jj in xrange(len(clustered_image[ii])):
                # audio
                y = clustered_audio_image[ii,jj]
                if y > 0: audio_score[int(y)-1]+=1
                # fabric
                y = clustered_fabric_image[ii,jj]
                if y > 0: fabric_score[int(y)-1]+=1
                # multimodal
                y = clustered_image[ii,jj]
                if y > 0: multi_score[int(y)-1]+=1

        cause = os.path.split(fileNameList[i])[-1].split('.pkl')[0].split('failure_')[-1].split('_')[0]
        image_area = float(len(clustered_image)*len(clustered_image[0]))
        if multi_score is not [] and np.max(multi_score)/image_area > 0.02:
            estimated_cause = 'forcesound'            
            print "Force and sound :: ", cause
        else:
            if np.max(audio_score)/image_area > np.max(fabric_score)/image_area:
                estimated_cause = 'sound'
                print "sound :: ", cause
            else:
                estimated_cause = 'force'
                print "Skin contact force :: ", cause

        for ii, real_anomaly in enumerate(anomaly_list):
            if real_anomaly == cause:
                y_true.append(ii)
                break 
            
        for ii, est_anomaly in enumerate(anomaly_list):
            if est_anomaly == estimated_cause:
                y_pred.append(ii)                
                break
                    

    print y_true
    print y_pred


    from sklearn.metrics import confusion_matrix
    cm = confusion_matrix(y_true, y_pred)
    np.set_printoptions(precision=2)
    cm_normalized = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]

    fig = plt.figure()
    plt.imshow(cm_normalized, interpolation='nearest')
    plt.colorbar()
    tick_marks = np.arange(len(anomaly_list))
    plt.xticks(tick_marks, anomaly_list, rotation=45)
    plt.yticks(tick_marks, anomaly_list)
    plt.tight_layout()
    plt.ylabel('True label')
    plt.xlabel('Predicted label')
    plt.title('Confusion Matrix')
    
    if save_pdf:
        fig.savefig('test.pdf')
        fig.savefig('test.png')
        os.system('cp test.p* ~/Dropbox/HRL/')
        ## ut.get_keystroke('Hit a key to proceed next')
    else:
        plt.show()


        



if __name__ == '__main__':

    import optparse
    p = optparse.OptionParser()
    p.add_option('--dataRenew', '--dr', action='store_true', dest='bDataRenew',
                 default=False, help='Renew pickle files.')
    p.add_option('--hmmRenew', '--hr', action='store_true', dest='bHMMRenew',
                 default=False, help='Renew HMM parameters.')

    p.add_option('--likelihoodplot', '--lp', action='store_true', dest='bLikelihoodPlot',
                 default=False, help='Plot the change of likelihood.')
    p.add_option('--localization', '--ll', action='store_true', dest='bLocalization',
                 default=False, help='Extract local feature.')
    p.add_option('--rawplot', '--rp', action='store_true', dest='bRawDataPlot',
                 default=False, help='Plot raw data.')
    p.add_option('--interplot', '--ip', action='store_true', dest='bInterpDataPlot',
                 default=False, help='Plot raw data.')
    p.add_option('--feature', '--ft', action='store_true', dest='bFeaturePlot',
                 default=False, help='Plot features.')
    p.add_option('--pca', action='store_true', dest='bPCAPlot',
                 default=False, help='Plot pca result.')
    p.add_option('--spacetimerf', '--st', action='store_true', dest='bSTField',
                 default=False, help='Plot space-time receptive field.')
    p.add_option('--classification', '--c', action='store_true', dest='bClassification',
                 default=False, help='Evaluate classification performance.')
    
    p.add_option('--renew', action='store_true', dest='bRenew',
                 default=False, help='Renew pickle files.')
    p.add_option('--savepdf', '--sp', action='store_true', dest='bSavePdf',
                 default=False, help='Save pdf files.')    
    p.add_option('--verbose', '--v', action='store_true', dest='bVerbose',
                 default=False, help='Print out.')

    opt, args = p.parse_args()

    save_data_path = '/home/dpark/hrl_file_server/dpark_data/anomaly/RSS2016'
    raw_data_path  = '/home/dpark/hrl_file_server/dpark_data/anomaly/RSS2016/'

    #---------------------------------------------------------------------------           
    # Run evaluation
    #---------------------------------------------------------------------------           
    subject = 'gatsbii'
    task    = 'scooping'    
    ## feature_list = ['unimodal_ftForce', 'crossmodal_targetRelativeDist', \
    ##                 'crossmodal_targetRelativeAng']
    feature_list = ['unimodal_ftForce', 'crossmodal_targetRelativeDist']

    ## subject = 'gatsbii'
    ## task    = 'feeding' 
    ## feature_list = ['unimodal_audioPower', 'unimodal_ftForce', 'crossmodal_artagRelativeDist', \
    ##                 'crossmodal_artagRelativeAng']
    
    # Dectection TEST 
    nSet           = 1
    local_range    = 0.25    
    viz            = False
    renew          = False
    downSampleSize = 200

    if opt.bRawDataPlot or opt.bInterpDataPlot:
        '''
        Before localization: Raw data plot
        After localization: Raw or interpolated data plot
        '''
        target_data_set = 0
        rf_center       = 'kinEEPos'
        #rf_center       = 'kinForearmPos'
        modality_list   = ['kinematics', 'audio', 'fabric', 'ft', 'vision'] #, 'pps'
        successData     = True #True
        failureData     = False
        local_range     = 0.15
        
        data_plot([subject], task, raw_data_path, save_data_path,\
                  nSet=target_data_set, downSampleSize=downSampleSize, \
                  local_range=local_range, rf_center=rf_center, \
                  raw_viz=opt.bRawDataPlot, interp_viz=opt.bInterpDataPlot, save_pdf=opt.bSavePdf,\
                  successData=successData, failureData=failureData,\
                  modality_list=modality_list, data_renew=opt.bDataRenew, verbose=opt.bVerbose)

    elif opt.bFeaturePlot:
        target_data_set = 0
        rf_center    = 'kinEEPos'
        ## rf_center    = 'kinForearmPos'
        feature_list = ['unimodal_audioPower',\
                        'unimodal_kinVel',\
                        'unimodal_ftForce',\
                        #'unimodal_ppsForce',\
                        'unimodal_fabricForce',\
                        'crossmodal_targetRelativeDist', \
                        'crossmodal_targetRelativeAng']
        local_range = 0.15
        success_viz = True
        failure_viz = True

        feature_extraction([subject], task, raw_data_path, save_data_path, rf_center, local_range,\
                           nSet=target_data_set, downSampleSize=downSampleSize, \
                           success_viz=success_viz, failure_viz=failure_viz,\
                           save_pdf=opt.bSavePdf, solid_color=True,\
                           feature_list=feature_list, data_renew=opt.bDataRenew)

    elif opt.bPCAPlot:
        target_data_set = 0
        rf_center    = 'kinEEPos'
        ## rf_center    = 'kinForearmPos'
        feature_list = ['unimodal_audioPower',\
                        'unimodal_kinVel',\
                        'unimodal_ftForce',\
                        #'unimodal_ppsForce',\
                        'unimodal_fabricForce',\
                        'crossmodal_targetRelativeDist', \
                        'crossmodal_targetRelativeAng']
        local_range = 0.15
        success_viz = True
        failure_viz = False
                        
        pca_plot([subject], task, raw_data_path, save_data_path, rf_center, local_range,\
                  nSet=target_data_set, downSampleSize=downSampleSize, \
                  success_viz=success_viz, failure_viz=failure_viz,\
                  save_pdf=opt.bSavePdf,
                  feature_list=feature_list, data_renew=opt.bDataRenew)

    elif opt.bLikelihoodPlot:
        target_data_set = 0
        rf_center    = 'kinEEPos'
        ## rf_center    = 'kinForearmPos'
        feature_list = ['unimodal_audioPower',\
                        'unimodal_kinVel',\
                        'unimodal_ftForce',\
                        #'unimodal_ppsForce',\
                        'unimodal_fabricForce',\
                        'crossmodal_targetRelativeDist', \
                        'crossmodal_targetRelativeAng']
        local_range = 0.15


        nState    = 15
        threshold = 0.0
        ## preprocessData([subject], task, raw_data_path, save_data_path, renew=opt.bDataRenew, \
        ##                downSampleSize=downSampleSize)
        likelihoodOfSequences([subject], task, raw_data_path, save_data_path, rf_center, local_range,\
                              nSet=target_data_set, downSampleSize=downSampleSize, \
                              feature_list=feature_list, \
                              nState=nState, threshold=threshold,\
                              useTrain=True, useNormalTest=False, useAbnormalTest=True,\
                              useTrain_color=False, useNormalTest_color=False, useAbnormalTest_color=False,\
                              renew=renew, save_pdf=opt.bSavePdf, data_renew=opt.bDataRenew)
                              

    elif opt.bSTField:
        '''
        space time receptive field
        '''
        target_data_set = 0
        success_viz = False
        failure_viz = True
        space_time_field_plot([subject], task, raw_data_path, save_data_path,\
                              nSet=target_data_set, downSampleSize=downSampleSize, \
                              success_viz=success_viz, failure_viz=failure_viz,\
                              save_pdf=opt.bSavePdf, data_renew=opt.bDataRenew)

    elif opt.bClassification:
        '''
        Get classification evaluation result
        '''        
        target_data_set = 0
        offline_classification([subject], task, raw_data_path, save_data_path,\
                               nSet=target_data_set, downSampleSize=downSampleSize, \
                               save_pdf=opt.bSavePdf, data_renew=opt.bDataRenew)

        
    ## else:
    ##     nState         = 10
    ##     cov_mult       = 5.0       
    ##     anomaly_offset = -20.0        
    ##     check_methods = ['progress']
    ##     evaluation_all([subject], task, check_methods, feature_list, nSet,\
    ##                    save_data_path, downSampleSize=downSampleSize, \
    ##                    nState=nState, cov_mult=cov_mult, anomaly_offset=anomaly_offset, local_range=local_range,\
    ##                    data_renew=opt.bDataRenew, hmm_renew=opt.bHMMRenew, viz=viz)    

    else:
        fig = plt.figure()
        ax = fig.add_subplot(1,1,1)
        from scipy.stats import poisson
        mu = 0.6
        mean, var, skew, kurt = poisson.stats(mu, moments='mvsk')
        x = np.arange(0.0, 30.0)
        ax.plot(x, poisson.pmf(x, mu), 'bo', ms=8, label='poisson pmf')
        
        plt.show()
