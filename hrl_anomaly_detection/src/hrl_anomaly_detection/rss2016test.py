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
## import rospy, roslib
import os, sys, copy
import random
import socket

# visualization
import matplotlib
#matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from matplotlib import gridspec
# util
import numpy as np
import scipy
import hrl_lib.util as ut
from hrl_anomaly_detection.util import *
from hrl_anomaly_detection.util_viz import *
from hrl_anomaly_detection import data_manager as dm
## from hrl_anomaly_detection.scooping_feeding import util as sutil
## import PyKDL
## import sandbox_dpark_darpa_m3.lib.hrl_check_util as hcu
## import sandbox_dpark_darpa_m3.lib.hrl_dh_lib as hdl
## import hrl_lib.circular_buffer as cb
from hrl_anomaly_detection.params import *

# learning
## from hrl_anomaly_detection.hmm import learning_hmm_multi_n as hmm
from hrl_anomaly_detection.hmm import learning_hmm as hmm
from mvpa2.datasets.base import Dataset
from sklearn import svm
from joblib import Parallel, delayed

# private learner
import hrl_anomaly_detection.classifiers.classifier as cf

import itertools
colors = itertools.cycle(['r', 'g', 'b', 'm', 'c', 'k', 'y'])
shapes = itertools.cycle(['x','v', 'o', '+'])

matplotlib.rcParams['pdf.fonttype'] = 42
matplotlib.rcParams['ps.fonttype'] = 42 
   
def likelihoodOfSequences(subject_names, task_name, raw_data_path, processed_data_path, param_dict,\
                          decision_boundary_viz=False, \
                          useTrain=True, useNormalTest=True, useAbnormalTest=False,\
                          useTrain_color=False, useNormalTest_color=False, useAbnormalTest_color=False,\
                          data_renew=False, hmm_renew=False, save_pdf=False, verbose=False):

    ## Parameters
    # data
    data_dict  = param_dict['data_param']
    # AE
    AE_dict     = param_dict['AE']
    # HMM
    HMM_dict = param_dict['HMM']
    nState   = HMM_dict['nState']
    cov      = HMM_dict['cov']
    # SVM
    
    #------------------------------------------

    if AE_dict['switch']:
        
        AE_proc_data = os.path.join(processed_data_path, 'ae_processed_data_0.pkl')
        d = ut.load_pickle(AE_proc_data)
        if AE_dict['filter']:
            # Bottle features with variance filtering
            successData = d['normTrainDataFiltered']
            failureData = d['abnormTrainDataFiltered']
        else:
            # Bottle features without filtering
            successData = d['normTrainData']
            failureData = d['abnormTrainData']

        if AE_dict['add_option'] is not None:
            newHandSuccessData = handSuccessData = d['handNormTrainData']
            newHandFailureData = handFailureData = d['handAbnormTrainData']
            
            ## for i in xrange(AE_dict['nAugment']):
            ##     newHandSuccessData = stackSample(newHandSuccessData, handSuccessData)
            ##     newHandFailureData = stackSample(newHandFailureData, handFailureData)

            successData = combineData( successData, newHandSuccessData, \
                                       AE_dict['add_option'], d['handFeatureNames'] )
            failureData = combineData( failureData, newHandFailureData, \
                                       AE_dict['add_option'], d['handFeatureNames'] )

            ## # reduce dimension by pooling
            ## pooling_param_dict  = {'dim': AE_dict['filterDim']} # only for AE        
            ## successData, pooling_param_dict = dm.variancePooling(successData, \
            ##                                                   pooling_param_dict)
            ## failureData, _ = dm.variancePooling(failureData, pooling_param_dict)
            
            
        successData *= HMM_dict['scale']
        failureData *= HMM_dict['scale']
        
    else:
        dd = dm.getDataSet(subject_names, task_name, raw_data_path, \
                           processed_data_path, data_dict['rf_center'], \
                           data_dict['local_range'],\
                           downSampleSize=data_dict['downSampleSize'], \
                           scale=1.0,\
                           ae_data=False,\
                           data_ext=data_dict['lowVarDataRemv'],\
                           handFeatures=data_dict['handFeatures'], \
                           cut_data=data_dict['cut_data'],\
                           data_renew=data_dict['renew'])
                           
        successData = dd['successData'] * HMM_dict['scale']
        failureData = dd['failureData'] * HMM_dict['scale']
                           

    normalTestData = None                                    
    print "======================================"
    print "Success data: ", np.shape(successData)
    ## print "Normal test data: ", np.shape(normalTestData)
    print "Failure data: ", np.shape(failureData)
    print "======================================"

    kFold_list = dm.kFold_data_index2(len(successData[0]),\
                                      len(failureData[0]),\
                                      data_dict['nNormalFold'], data_dict['nAbnormalFold'] )
    normalTrainIdx, abnormalTrainIdx, normalTestIdx, abnormalTestIdx = kFold_list[0]
    normalTrainData   = successData[:, normalTrainIdx, :] 
    abnormalTrainData = failureData[:, abnormalTrainIdx, :] 
    normalTestData    = successData[:, normalTestIdx, :] 
    abnormalTestData  = failureData[:, abnormalTestIdx, :] 
    

    # training hmm
    nEmissionDim = len(normalTrainData)
    ## hmm_param_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'.pkl')    
    cov_mult = [cov]*(nEmissionDim**2)

    # generative model
    ml  = hmm.learning_hmm(nState, nEmissionDim, verbose=False)
    ret = ml.fit(normalTrainData, cov_mult=cov_mult, ml_pkl=None, use_pkl=False) # not(renew))
    ## ths = threshold
    startIdx = 4
        
    if ret == 'Failure': 
        print "-------------------------"
        print "HMM returned failure!!   "
        print "-------------------------"
        return (-1,-1,-1,-1)

    if decision_boundary_viz:
        testDataX = np.vstack([np.swapaxes(normalTestData, 0, 1), np.swapaxes(abnormalTestData, 0, 1)])
        testDataX = np.swapaxes(testDataX, 0, 1)
        testDataY = np.hstack([ -np.ones(len(normalTestData[0])), \
                                np.ones(len(abnormalTestData[0])) ])

        r = Parallel(n_jobs=-1)(delayed(hmm.computeLikelihoods)(i, ml.A, ml.B, ml.pi, ml.F, \
                                                                [testDataX[j][i] for j in \
                                                                 xrange(nEmissionDim)], \
                                                                ml.nEmissionDim, ml.nState,\
                                                                startIdx=startIdx, \
                                                                bPosterior=True)
                                                                for i in xrange(len(testDataX[0])))
        _, ll_classifier_train_idx, ll_logp, ll_post = zip(*r)

        ll_classifier_train_X = []
        ll_classifier_train_Y = []
        for i in xrange(len(ll_logp)):
            l_X = []
            l_Y = []
            for j in xrange(len(ll_logp[i])):        
                l_X.append( [ll_logp[i][j]] + ll_post[i][j].tolist() )

                if testDataY[i] > 0.0: l_Y.append(1)
                else: l_Y.append(-1)

            ll_classifier_train_X.append(l_X)
            ll_classifier_train_Y.append(l_Y)

        # flatten the data
        X_train_org = []
        Y_train_org = []
        idx_train_org = []
        for i in xrange(len(ll_classifier_train_X)):
            for j in xrange(len(ll_classifier_train_X[i])):
                X_train_org.append(ll_classifier_train_X[i][j])
                Y_train_org.append(ll_classifier_train_Y[i][j])
                idx_train_org.append(ll_classifier_train_idx[i][j])

        # discriminative classifier
        if decision_boundary_viz:
            dtc = cf.classifier( method='progress_time_cluster', nPosteriors=nState, \
                                 nLength=len(normalTestData[0,0]), ths_mult=0.0 )
            dtc.fit(X_train_org, Y_train_org, idx_train_org, parallel=True)

    print "----------------------------------------------------------------------------"
    fig = plt.figure()
    min_logp = 0.0
    max_logp = 0.0
    target_idx = 1

    # training data
    if useTrain:

        log_ll = []
        exp_log_ll = []        
        for i in xrange(len(normalTrainData[0])):

            log_ll.append([])
            exp_log_ll.append([])
            for j in range(startIdx, len(normalTrainData[0][i])):

                X = [x[i,:j] for x in normalTrainData]
                logp = ml.loglikelihood(X)
                log_ll[i].append(logp)

                if decision_boundary_viz and i==target_idx:
                    if j>=len(ll_logp[i]): continue
                    l_X = [ll_logp[i][j]] + ll_post[i][j].tolist()

                    exp_logp = dtc.predict(l_X)[0] + ll_logp[i][j]
                    exp_log_ll[i].append(exp_logp)


            if min_logp > np.amin(log_ll): min_logp = np.amin(log_ll)
            if max_logp < np.amax(log_ll): max_logp = np.amax(log_ll)
                
            # disp
            if useTrain_color: plt.plot(log_ll[i], label=str(i))
            else: plt.plot(log_ll[i], 'b-')

            ## # temp
            ## if show_plot:
            ##     plt.plot(log_ll[i], 'b-', lw=3.0)
            ##     plt.plot(exp_log_ll[i], 'm-')                            
            ##     plt.show()
            ##     fig = plt.figure()

        if useTrain_color: 
            plt.legend(loc=3,prop={'size':16})
            
        plt.plot(log_ll[target_idx], 'k-', lw=3.0)
        if decision_boundary_viz:
            plt.plot(exp_log_ll[target_idx], 'm-', lw=3.0)            

            
    # normal test data
    ## if useNormalTest and False:

    ##     log_ll = []
    ##     ## exp_log_ll = []        
    ##     for i in xrange(len(normalTestData[0])):

    ##         log_ll.append([])
    ##         ## exp_log_ll.append([])

    ##         for j in range(2, len(normalTestData[0][i])):
    ##             X = [x[i,:j] for x in normalTestData]                

    ##             logp = ml.loglikelihood(X)
    ##             log_ll[i].append(logp)

    ##             ## exp_logp, logp = ml.expLoglikelihood(X, ths, bLoglikelihood=True)
    ##             ## log_ll[i].append(logp)
    ##             ## exp_log_ll[i].append(exp_logp)

    ##         if min_logp > np.amin(log_ll): min_logp = np.amin(log_ll)
    ##         if max_logp < np.amax(log_ll): max_logp = np.amax(log_ll)

    ##         # disp 
    ##         if useNormalTest_color: plt.plot(log_ll[i], label=str(i))
    ##         else: plt.plot(log_ll[i], 'g-')

    ##         ## plt.plot(exp_log_ll[i], 'r*-')

    ##     if useNormalTest_color: 
    ##         plt.legend(loc=3,prop={'size':16})

    # abnormal test data
    if useAbnormalTest:
        log_ll = []
        ## exp_log_ll = []        
        for i in xrange(len(abnormalTestData[0])):

            log_ll.append([])
            ## exp_log_ll.append([])

            for j in range(startIdx, len(abnormalTestData[0][i])):
                X = [x[i,:j] for x in abnormalTestData]                
                try:
                    logp = ml.loglikelihood(X)
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
        plt.show()        

    return


    
def aeDataExtraction(subject_names, task_name, raw_data_path, \
                    processed_data_path, param_dict,\
                    handFeature_viz=False,\
                    success_viz=False, failure_viz=False,\
                    cuda=True, verbose=False):

    ## Parameters
    # data
    data_dict  = param_dict['data_param']
    data_renew = data_dict['renew']
    handFeatures = data_dict['handFeatures']
    # AE
    AE_dict     = param_dict['AE']
    rawFeatures = AE_dict['rawFeatures']
    #------------------------------------------
    assert AE_dict['switch'] == True
                   
    crossVal_pkl = os.path.join(processed_data_path, 'cv_'+task_name+'.pkl')
    if os.path.isfile(crossVal_pkl) and data_renew is False: 
        print "Loading cv data"
        d = ut.load_pickle(crossVal_pkl)
    else:
        d = dm.getDataSet(subject_names, task_name, raw_data_path, processed_data_path, \
                           data_dict['rf_center'], data_dict['local_range'],\
                           downSampleSize=data_dict['downSampleSize'], scale=1.0,\
                           ae_data=AE_dict['switch'], data_ext=data_dict['lowVarDataRemv'], \
                           handFeatures=handFeatures, rawFeatures=rawFeatures,\
                           cut_data=data_dict['cut_data'],
                           data_renew=data_renew)

        kFold_list = dm.kFold_data_index2(len(d['aeSuccessData'][0]),\
                                          len(d['aeFailureData'][0]),\
                                          data_dict['nNormalFold'], data_dict['nAbnormalFold'] )

        d['kFoldList']       = kFold_list                                             
        ut.save_pickle(d, crossVal_pkl)

    # Training HMM, and getting classifier training and testing data
    for idx, (normalTrainIdx, abnormalTrainIdx, normalTestIdx, abnormalTestIdx) \
      in enumerate( d['kFoldList'] ):

        if verbose: print "Start "+str(idx)+"/"+str(len( d['kFoldList'] ))+"th iteration"

        AE_proc_data = os.path.join(processed_data_path, 'ae_processed_data_'+str(idx)+'.pkl')

        # From dim x sample x length
        # To reduced_dim x sample
        dd = dm.getAEdataSet(idx, d['aeSuccessData'], d['aeFailureData'], \
                             d['successData'], d['failureData'], d['param_dict'], \
                             normalTrainIdx, abnormalTrainIdx, normalTestIdx, abnormalTestIdx,
                             AE_dict['time_window'], AE_dict['nAugment'], \
                             AE_proc_data, \
                             # data param
                             processed_data_path, \
                             # AE param
                             layer_sizes=AE_dict['layer_sizes'], learning_rate=AE_dict['learning_rate'], \
                             learning_rate_decay=AE_dict['learning_rate_decay'], \
                             momentum=AE_dict['momentum'], dampening=AE_dict['dampening'], \
                             lambda_reg=AE_dict['lambda_reg'], \
                             max_iteration=AE_dict['max_iteration'], min_loss=AE_dict['min_loss'], \
                             cuda=AE_dict['cuda'], \
                             filtering=AE_dict['filter'], filteringDim=AE_dict['filterDim'],\
                             verbose=verbose, renew=AE_dict['renew'], train_ae=False )

        if AE_dict['filter']:
            # NOTE: pooling dimension should vary on each auto encoder.
            # Filtering using variances
            normalTrainData   = dd['normTrainDataFiltered']
            abnormalTrainData = dd['abnormTrainDataFiltered']
            normalTestData    = dd['normTestDataFiltered']
            abnormalTestData  = dd['abnormTestDataFiltered']
        else:
            normalTrainData   = dd['normTrainData']
            abnormalTrainData = dd['abnormTrainData']
            normalTestData    = dd['normTestData']
            abnormalTestData  = dd['abnormTestData']            

        if success_viz or failure_viz and False:
            import data_viz as dv
            print dd.keys()
            dv.viz(dd['normTrainData'], normTest=dd['normTestData'], \
                   abnormTest=dd['abnormTestData'],skip=True)
            ## else: dv.viz(dd['normTrainData'], dd['abnormTrainData'])
            dv.viz(dd['normTrainDataFiltered'], abnormTest=dd['abnormTrainDataFiltered'])

        if handFeature_viz:
            print AE_dict['add_option'], dd['handFeatureNames']
            handNormalTrainData = combineData( normalTrainData, dd['handNormTrainData'],\
                                               AE_dict['add_option'], dd['handFeatureNames'])
            handAbnormalTrainData = combineData( abnormalTrainData, dd['handAbnormTrainData'],\
                                                 AE_dict['add_option'], dd['handFeatureNames'])

            
            import data_viz as dv
            dv.viz(handNormalTrainData, abnormTest=handAbnormalTrainData)

            ## normalTrainData   = stackSample(normalTrainData, handNormalTrainData)
            ## abnormalTrainData = stackSample(abnormalTrainData, handAbnormalTrainData)



# ------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------

def evaluation_all(subject_names, task_name, raw_data_path, processed_data_path, param_dict,\
                   data_renew=False, save_pdf=False, show_plot=True, verbose=False):

    ## Parameters
    # data
    data_dict  = param_dict['data_param']
    data_renew = data_dict['renew']
    # AE
    AE_dict     = param_dict['AE']
    # HMM
    HMM_dict = param_dict['HMM']
    nState   = HMM_dict['nState']
    cov      = HMM_dict['cov']
    # SVM
    SVM_dict = param_dict['SVM']

    # ROC
    ROC_dict = param_dict['ROC']
    
    #------------------------------------------

    

    if os.path.isdir(processed_data_path) is False:
        os.system('mkdir -p '+processed_data_path)

    crossVal_pkl = os.path.join(processed_data_path, 'cv_'+task_name+'.pkl')
    
    if os.path.isfile(crossVal_pkl) and data_renew is False:
        d = ut.load_pickle(crossVal_pkl)
        kFold_list  = d['kFoldList']
    else:
        '''
        Use augmented data? if nAugment is 0, then aug_successData = successData
        '''        
        d = dm.getDataSet(subject_names, task_name, raw_data_path, \
                           processed_data_path, data_dict['rf_center'], data_dict['local_range'],\
                           downSampleSize=data_dict['downSampleSize'], scale=1.0,\
                           ae_data=AE_dict['switch'],\
                           data_ext=data_dict['lowVarDataRemv'], \
                           handFeatures=data_dict['handFeatures'], \
                           cut_data=data_dict['cut_data'], \
                           data_renew=data_renew)
                           
        if AE_dict['switch']:
            # Task-oriented raw features        
            kFold_list = dm.kFold_data_index2(len(d['aeSuccessData'][0]), len(d['aeFailureData'][0]), \
                                              data_dict['nNormalFold'], data_dict['nAbnormalFold'] )
        else:
            # Task-oriented hand-crafted features        
            kFold_list = dm.kFold_data_index2(len(d['successData'][0]), len(d['failureData'][0]), \
                                              data_dict['nNormalFold'], data_dict['nAbnormalFold'] )
        d['kFoldList']   = kFold_list
        ut.save_pickle(d, crossVal_pkl)

    #-----------------------------------------------------------------------------------------
    # parameters
    startIdx    = 4
    method_list = ROC_dict['methods'] 
    nPoints     = ROC_dict['nPoints']

    successData = d['successData']
    failureData = d['failureData']
    param_dict  = d['param_dict']
    aeSuccessData = d.get('aeSuccessData', None)
    aeFailureData = d.get('aeFailureData', None)
    

    #-----------------------------------------------------------------------------------------
    # Training HMM, and getting classifier training and testing data
    for idx, (normalTrainIdx, abnormalTrainIdx, normalTestIdx, abnormalTestIdx) \
      in enumerate(kFold_list):

        if verbose: print idx, " : training hmm and getting classifier training and testing data"

        if AE_dict['switch'] and AE_dict['add_option'] is not None:
            tag = ''
            for ft in AE_dict['add_option']:
                tag += ft[:2]
            modeling_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'_raw_'+tag+'_'+str(idx)+'.pkl')
        elif AE_dict['switch'] and AE_dict['add_option'] is None:
            modeling_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'_raw_'+str(idx)+'.pkl')
        else:
            modeling_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'_'+str(idx)+'.pkl')

        if os.path.isfile(modeling_pkl) is False or HMM_dict['renew'] or data_renew:

            if AE_dict['switch']:
                if verbose: print "Start "+str(idx)+"/"+str(len(kFold_list))+"th iteration"

                AE_proc_data = os.path.join(processed_data_path, 'ae_processed_data_'+str(idx)+'.pkl')
            
                # From dim x sample x length
                # To reduced_dim x sample x length
                d = dm.getAEdataSet(idx, aeSuccessData, aeFailureData, \
                                    successData, failureData, param_dict,\
                                    normalTrainIdx, abnormalTrainIdx, normalTestIdx, abnormalTestIdx,\
                                    AE_dict['time_window'], AE_dict['nAugment'], \
                                    AE_proc_data, \
                                    # data param
                                    processed_data_path, \
                                    # AE param
                                    layer_sizes=AE_dict['layer_sizes'], learning_rate=AE_dict['learning_rate'], \
                                    learning_rate_decay=AE_dict['learning_rate_decay'], \
                                    momentum=AE_dict['momentum'], dampening=AE_dict['dampening'], \
                                    lambda_reg=AE_dict['lambda_reg'], \
                                    max_iteration=AE_dict['max_iteration'], min_loss=AE_dict['min_loss'], \
                                    cuda=False, \
                                    filtering=AE_dict['filter'], filteringDim=AE_dict['filterDim'],\
                                    verbose=False)

                if AE_dict['filter']:
                    # NOTE: pooling dimension should vary on each auto encoder.
                    # Filtering using variances
                    normalTrainData   = d['normTrainDataFiltered']
                    abnormalTrainData = d['abnormTrainDataFiltered']
                    normalTestData    = d['normTestDataFiltered']
                    abnormalTestData  = d['abnormTestDataFiltered']
                    ## import data_viz as dv
                    ## dv.viz(normalTrainData)
                    ## continue                   
                else:
                    normalTrainData   = d['normTrainData']
                    abnormalTrainData = d['abnormTrainData']
                    normalTestData    = d['normTestData']
                    abnormalTestData  = d['abnormTestData']

            else:
                # dim x sample x length
                normalTrainData   = successData[:, normalTrainIdx, :] 
                abnormalTrainData = failureData[:, abnormalTrainIdx, :] 
                normalTestData    = successData[:, normalTestIdx, :] 
                abnormalTestData  = failureData[:, abnormalTestIdx, :] 


            if AE_dict['switch'] and AE_dict['add_option'] is not None:
                print "add hand-crafted features.."
                newHandSuccTrData = handSuccTrData = d['handNormTrainData']
                newHandFailTrData = handFailTrData = d['handAbnormTrainData']
                handSuccTeData = d['handNormTestData']
                handFailTeData = d['handAbnormTestData']

                ## for i in xrange(AE_dict['nAugment']):
                ##     newHandSuccTrData = stackSample(newHandSuccTrData, handSuccTrData)
                ##     newHandFailTrData = stackSample(newHandFailTrData, handFailTrData)

                normalTrainData   = combineData( normalTrainData, newHandSuccTrData,\
                                                 AE_dict['add_option'], d['handFeatureNames'], \
                                                 add_noise_features=AE_dict['add_noise_option'] )
                abnormalTrainData = combineData( abnormalTrainData, newHandFailTrData,\
                                                 AE_dict['add_option'], d['handFeatureNames'])
                normalTestData   = combineData( normalTestData, handSuccTeData,\
                                                AE_dict['add_option'], d['handFeatureNames'])
                abnormalTestData  = combineData( abnormalTestData, handFailTeData,\
                                                 AE_dict['add_option'], d['handFeatureNames'])

                ## # reduce dimension by pooling
                ## pooling_param_dict  = {'dim': AE_dict['filterDim']} # only for AE        
                ## normalTrainData, pooling_param_dict = dm.variancePooling(normalTrainData, \
                ##                                                          pooling_param_dict)
                ## abnormalTrainData, _ = dm.variancePooling(abnormalTrainData, pooling_param_dict)
                ## normalTestData, _    = dm.variancePooling(normalTestData, pooling_param_dict)
                ## abnormalTestData, _  = dm.variancePooling(abnormalTestData, pooling_param_dict)
                

            # scaling
            if verbose: print "scaling data"
            normalTrainData   *= HMM_dict['scale']
            abnormalTrainData *= HMM_dict['scale']
            normalTestData    *= HMM_dict['scale']
            abnormalTestData  *= HMM_dict['scale']

            # training hmm
            if verbose: print "start to fit hmm"
            nEmissionDim = len(normalTrainData)
            cov_mult     = [cov]*(nEmissionDim**2)
            nLength      = len(normalTrainData[0][0]) - startIdx

            ml  = hmm.learning_hmm(nState, nEmissionDim, verbose=verbose) 
            ret = ml.fit(normalTrainData, cov_mult=cov_mult, use_pkl=False) 

            if ret == 'Failure': 
                print "-------------------------"
                print "HMM returned failure!!   "
                print "-------------------------"
                sys.exit()
                return (-1,-1,-1,-1)
            
            #-----------------------------------------------------------------------------------------
            # Classifier training data
            #-----------------------------------------------------------------------------------------
            testDataX = []
            testDataY = []
            for i in xrange(nEmissionDim):
                temp = np.vstack([normalTrainData[i], abnormalTrainData[i]])
                testDataX.append( temp )

            testDataY = np.hstack([ -np.ones(len(normalTrainData[0])), \
                                    np.ones(len(abnormalTrainData[0])) ])

            r = Parallel(n_jobs=-1)(delayed(hmm.computeLikelihoods)(i, ml.A, ml.B, ml.pi, ml.F, \
                                                                    [ testDataX[j][i] for j in xrange(nEmissionDim) ], \
                                                                    ml.nEmissionDim, ml.nState,\
                                                                    startIdx=startIdx, \
                                                                    bPosterior=True)
                                                                    for i in xrange(len(testDataX[0])))
            _, ll_classifier_train_idx, ll_logp, ll_post = zip(*r)

            ll_classifier_train_X = []
            ll_classifier_train_Y = []
            for i in xrange(len(ll_logp)):
                l_X = []
                l_Y = []
                for j in xrange(len(ll_logp[i])):        
                    l_X.append( [ll_logp[i][j]] + ll_post[i][j].tolist() )

                    if testDataY[i] > 0.0: l_Y.append(1)
                    else: l_Y.append(-1)

                if np.nan in l_X:
                    print i,j
                    print l_X
                    sys.exit()

                ll_classifier_train_X.append(l_X)
                ll_classifier_train_Y.append(l_Y)


            #-----------------------------------------------------------------------------------------
            # Classifier test data
            #-----------------------------------------------------------------------------------------
            testDataX = []
            testDataY = []
            for i in xrange(nEmissionDim):
                temp = np.vstack([normalTestData[i], abnormalTestData[i]])
                testDataX.append( temp )

            testDataY = np.hstack([ -np.ones(len(normalTestData[0])), \
                                    np.ones(len(abnormalTestData[0])) ])

            r = Parallel(n_jobs=-1)(delayed(hmm.computeLikelihoods)(i, ml.A, ml.B, ml.pi, ml.F, \
                                                                    [ testDataX[j][i] for j in xrange(nEmissionDim) ], \
                                                                    ml.nEmissionDim, ml.nState,\
                                                                    startIdx=startIdx, \
                                                                    bPosterior=True)
                                                                    for i in xrange(len(testDataX[0])))
            _, ll_classifier_test_idx, ll_logp, ll_post = zip(*r)

            # nSample x nLength
            ll_classifier_test_X = []
            ll_classifier_test_Y = []
            for i in xrange(len(ll_logp)):
                l_X = []
                l_Y = []
                for j in xrange(len(ll_logp[i])):        
                    l_X.append( [ll_logp[i][j]] + ll_post[i][j].tolist() )

                    if testDataY[i] > 0.0: l_Y.append(1)
                    else: l_Y.append(-1)

                    if np.isnan(ll_logp[i][j]):
                        print "nan values in ", i, j
                        print testDataX[0][i]
                        print ll_logp[i][j], ll_post[i][j]
                        sys.exit()
                       

                ll_classifier_test_X.append(l_X)
                ll_classifier_test_Y.append(l_Y)

                ## if len(l_Y) < 10:
                ##     print ">> ", np.shape(ll_logp[i]), np.shape(ll_post[i])
                ##     print i, np.shape(l_X), np.shape(l_Y)

            #-----------------------------------------------------------------------------------------
            d = {}
            d['nEmissionDim'] = ml.nEmissionDim
            d['A']            = ml.A 
            d['B']            = ml.B 
            d['pi']           = ml.pi
            d['F']            = ml.F
            d['nState']       = nState
            d['startIdx']     = startIdx
            d['ll_classifier_train_X']  = ll_classifier_train_X
            d['ll_classifier_train_Y']  = ll_classifier_train_Y            
            d['ll_classifier_train_idx']= ll_classifier_train_idx
            d['ll_classifier_test_X']   = ll_classifier_test_X
            d['ll_classifier_test_Y']   = ll_classifier_test_Y            
            d['ll_classifier_test_idx'] = ll_classifier_test_idx
            d['nLength']      = nLength
            ut.save_pickle(d, modeling_pkl)


    #-----------------------------------------------------------------------------------------


    if AE_dict['switch'] and AE_dict['add_option'] is not None:
        tag = ''
        for ft in AE_dict['add_option']:
            tag += ft[:2]
        
        roc_pkl = os.path.join(processed_data_path, 'roc_'+task_name+'_raw_'+tag+'.pkl')
    elif AE_dict['switch'] and AE_dict['add_option'] is None:
        roc_pkl = os.path.join(processed_data_path, 'roc_'+task_name+'_raw.pkl')
    else:
        roc_pkl = os.path.join(processed_data_path, 'roc_'+task_name+'.pkl')

        
    if os.path.isfile(roc_pkl) is False or HMM_dict['renew']:        
        ROC_data = {}
    else:
        ROC_data = ut.load_pickle(roc_pkl)
        
    for i, method in enumerate(method_list):
        if method not in ROC_data.keys() or method in ROC_dict['update_list']: 
            ROC_data[method] = {}
            ROC_data[method]['complete'] = False 
            ROC_data[method]['tp_l'] = [ [] for j in xrange(nPoints) ]
            ROC_data[method]['fp_l'] = [ [] for j in xrange(nPoints) ]
            ROC_data[method]['tn_l'] = [ [] for j in xrange(nPoints) ]
            ROC_data[method]['fn_l'] = [ [] for j in xrange(nPoints) ]
            ROC_data[method]['delay_l'] = [ [] for j in xrange(nPoints) ]

    ## if os.path.isfile('temp.pkl'):
    ##     r = ut.load_pickle('temp.pkl')
    ## else:
    # parallelization
    r = Parallel(n_jobs=-1, verbose=50)(delayed(run_classifiers)( idx, processed_data_path, task_name, \
                                                                 method, ROC_data, ROC_dict, AE_dict, \
                                                                 SVM_dict ) \
                                                                 for idx in xrange(len(kFold_list)) \
                                                                 for method in method_list )

    ## for method in method_list:
    ##     for idx in xrange(len(kFold_list[:2])):
    ##         print method, idx, len(kFold_list[:2])
    ##         r = run_classifiers( idx, processed_data_path, task_name, \
    ##                              method, ROC_data, ROC_dict, AE_dict, \
    ##                              SVM_dict )            
                                                                  
    #l_data = zip(*r)
    l_data = r
    print "finished to run run_classifiers"

    for i in xrange(len(l_data)):
        for j in xrange(nPoints):
            try:
                method = l_data[i].keys()[0]
            except:
                print l_data[i]
                sys.exit()
            if ROC_data[method]['complete'] == True: continue
            ROC_data[method]['tp_l'][j] += l_data[i][method]['tp_l'][j]
            ROC_data[method]['fp_l'][j] += l_data[i][method]['fp_l'][j]
            ROC_data[method]['tn_l'][j] += l_data[i][method]['tn_l'][j]
            ROC_data[method]['fn_l'][j] += l_data[i][method]['fn_l'][j]
            ROC_data[method]['delay_l'][j] += l_data[i][method]['delay_l'][j]

    for i, method in enumerate(method_list):
        ROC_data[method]['complete'] = True

    ut.save_pickle(ROC_data, roc_pkl)
        
    #-----------------------------------------------------------------------------------------
    # ---------------- ROC Visualization ----------------------
    
    if True:
        print "Start to visualize ROC curves!!!"
        ROC_data = ut.load_pickle(roc_pkl)        

        fig = plt.figure()

        for method in method_list:

            tp_ll = ROC_data[method]['tp_l']
            fp_ll = ROC_data[method]['fp_l']
            tn_ll = ROC_data[method]['tn_l']
            fn_ll = ROC_data[method]['fn_l']
            delay_ll = ROC_data[method]['delay_l']

            tpr_l = []
            fpr_l = []
            fnr_l = []
            delay_mean_l = []
            delay_std_l  = []

            print np.shape(tp_ll), np.shape(fn_ll), nPoints

            for i in xrange(nPoints):
                tpr_l.append( float(np.sum(tp_ll[i]))/float(np.sum(tp_ll[i])+np.sum(fn_ll[i]))*100.0 )
                fpr_l.append( float(np.sum(fp_ll[i]))/float(np.sum(fp_ll[i])+np.sum(tn_ll[i]))*100.0 )
                fnr_l.append( 100.0 - tpr_l[-1] )
                delay_mean_l.append( np.mean(delay_ll[i]) )
                delay_std_l.append( np.std(delay_ll[i]) )

            print "--------------------------------"
            print method
            print tpr_l
            print fpr_l
            print "--------------------------------"

            if method == 'svm': label='HMM-SVM'
            elif method == 'progress_time_cluster': label='HMMs with a dynamic threshold'
            elif method == 'fixed': label='HMMs with a fixed threshold'
                
            # visualization
            color = colors.next()
            shape = shapes.next()
            ax1 = fig.add_subplot(111)            
            plt.plot(fpr_l, tpr_l, '-'+shape+color, label=label, mec=color, ms=6, mew=2)
            plt.xlim([-1, 101])
            plt.ylim([-1, 101])
            plt.ylabel('True positive rate (percentage)', fontsize=22)
            plt.xlabel('False positive rate (percentage)', fontsize=22)

            ## font = {'family' : 'normal',
            ##         'weight' : 'bold',
            ##         'size'   : 22}
            ## matplotlib.rc('font', **font)
            ## plt.tick_params(axis='both', which='major', labelsize=12)
            plt.xticks([0, 50, 100], fontsize=22)
            plt.yticks([0, 50, 100], fontsize=22)
            plt.tight_layout(pad=0.4, w_pad=0.5, h_pad=1.0)
            
            ## x = range(len(delay_mean_l))
            ## ax1 = fig.add_subplot(122)
            ## plt.errorbar(x, delay_mean_l, yerr=delay_std_l, c=color, label=method)

        plt.legend(loc='lower right', prop={'size':20})

        if save_pdf:
            fig.savefig('test.pdf')
            fig.savefig('test.png')
            os.system('cp test.p* ~/Dropbox/HRL/')        
        else:
            plt.show()
                   

def run_classifiers(idx, processed_data_path, task_name, method, ROC_data, ROC_dict, AE_dict, SVM_dict ):

    ## print idx, " : training classifier and evaluate testing data"
    # train a classifier and evaluate it using test data.
    from hrl_anomaly_detection.classifiers import classifier as cb
    from sklearn import preprocessing

    if AE_dict['switch'] and AE_dict['add_option'] is not None:
        tag = ''
        for ft in AE_dict['add_option']:
            tag += ft[:2]

        modeling_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'_raw_'+tag+'_'+str(idx)+'.pkl')
    elif AE_dict['switch'] and AE_dict['add_option'] is None:
        modeling_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'_raw_'+str(idx)+'.pkl')
    else:
        modeling_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'_'+str(idx)+'.pkl')

    print "start to load hmm data, ", modeling_pkl
    d            = ut.load_pickle(modeling_pkl)
    nState       = d['nState']        
    ll_classifier_train_X   = d['ll_classifier_train_X']
    ll_classifier_train_Y   = d['ll_classifier_train_Y']         
    ll_classifier_train_idx = d['ll_classifier_train_idx']
    ll_classifier_test_X    = d['ll_classifier_test_X']  
    ll_classifier_test_Y    = d['ll_classifier_test_Y']
    ll_classifier_test_idx  = d['ll_classifier_test_idx']
    nLength      = d['nLength']

    nPoints     = ROC_dict['nPoints']

    #-----------------------------------------------------------------------------------------
    # flatten the data
    X_train_org = []
    Y_train_org = []
    idx_train_org = []
    for i in xrange(len(ll_classifier_train_X)):
        for j in xrange(len(ll_classifier_train_X[i])):
            X_train_org.append(ll_classifier_train_X[i][j])
            Y_train_org.append(ll_classifier_train_Y[i][j])
            idx_train_org.append(ll_classifier_train_idx[i][j])

    data = {}
    # pass method if there is existing result
    data[method] = {}
    data[method]['tp_l'] = [ [] for j in xrange(nPoints) ]
    data[method]['fp_l'] = [ [] for j in xrange(nPoints) ]
    data[method]['tn_l'] = [ [] for j in xrange(nPoints) ]
    data[method]['fn_l'] = [ [] for j in xrange(nPoints) ]
    data[method]['delay_l'] = [ [] for j in xrange(nPoints) ]

    if ROC_data[method]['complete'] == True: return data

    #-----------------------------------------------------------------------------------------
    # Generate parameter list for ROC curve
    # pass method if there is existing result

    # data preparation
    if 'svm' in method:
        scaler = preprocessing.StandardScaler()
        ## scaler = preprocessing.scale()
        X_scaled = scaler.fit_transform(X_train_org)
    else:
        X_scaled = X_train_org
    print method, " : Before classification : ", np.shape(X_scaled), np.shape(Y_train_org)

    X_test = []
    Y_test = [] 
    for j in xrange(len(ll_classifier_test_X)):
        if len(ll_classifier_test_X[j])==0: continue

        try:
            if 'svm' in method:
                X = scaler.transform(ll_classifier_test_X[j])                                
            elif method == 'progress_time_cluster' or method == 'fixed':
                X = ll_classifier_test_X[j]
        except:
            print ll_classifier_test_X[j]
            continue
            
        X_test.append(X)
        Y_test.append(ll_classifier_test_Y[j])


    # classifier # TODO: need to make it efficient!!
    dtc = cb.classifier( method=method, nPosteriors=nState, nLength=nLength )        
    for j in xrange(nPoints):
        if method == 'svm':
            weights = ROC_dict['svm_param_range']
            dtc.set_params( class_weight=weights[j] )
            dtc.set_params( **SVM_dict )
            ret = dtc.fit(X_scaled, Y_train_org, idx_train_org, parallel=False)                
        elif method == 'cssvm_standard':
            weights = np.logspace(-2, 0.1, nPoints)
            dtc.set_params( class_weight=weights[j] )
            ret = dtc.fit(X_scaled, Y_train_org, idx_train_org, parallel=False)                
        elif method == 'cssvm':
            weights = ROC_dict['cssvm_param_range']
            dtc.set_params( class_weight=weights[j] )
            ret = dtc.fit(X_scaled, Y_train_org, idx_train_org, parallel=False)                
        elif method == 'progress_time_cluster':
            thresholds = ROC_dict['progress_param_range']
            dtc.set_params( ths_mult = thresholds[j] )
            if j==0: ret = dtc.fit(X_scaled, Y_train_org, idx_train_org, parallel=False)                
        elif method == 'fixed':
            thresholds = ROC_dict['fixed_param_range']
            dtc.set_params( ths_mult = thresholds[j] )
            if j==0: ret = dtc.fit(X_scaled, Y_train_org, idx_train_org, parallel=False)                

        ## X_scaled = scaler.transform(X_test_org)
        ## est_y = dtc.predict(X_scaled, Y_test_org)
        ## print est_y[:10]

        ## for jj in xrange(len(ll_classifier_test_X[0])):
        ##     X = scaler.transform([ll_classifier_test_X[0][jj]])
        ##     est_y = dtc.predict(X, y=ll_classifier_test_Y[0][jj:jj+1])
        ##     print est_y
        ##     if jj>10: break

        # evaluate the classifier
        tp_l = []
        fp_l = []
        tn_l = []
        fn_l = []
        delay_l = []
        delay_idx = 0
        for ii in xrange(len(X_test)):
            if len(Y_test[ii])==0: continue
            X = X_test[ii]                
            est_y    = dtc.predict(X, y=Y_test[ii])

            for jj in xrange(len(est_y)):
                if est_y[jj] > 0.0:
                    try:
                        delay_idx = ll_classifier_test_idx[ii][jj]
                    except:
                        print np.shape(ll_classifier_test_idx), ii, jj
                    #print "Break ", ii, " ", jj, " in ", est_y, " = ", ll_classifier_test_Y[ii][jj]
                    break        

            if Y_test[ii][0] > 0.0:
                if est_y[jj] > 0.0:
                    tp_l.append(1)
                    delay_l.append(delay_idx)
                else: fn_l.append(1)
            elif Y_test[ii][0] <= 0.0:
                if est_y[jj] > 0.0: fp_l.append(1)
                else: tn_l.append(1)

        data[method]['tp_l'][j] += tp_l
        data[method]['fp_l'][j] += fp_l
        data[method]['fn_l'][j] += fn_l
        data[method]['tn_l'][j] += tn_l
        data[method]['delay_l'][j] += delay_l

    print "finished ", idx, method
    return data


    
    
                
        
def data_plot(subject_names, task_name, raw_data_path, processed_data_path, \
              downSampleSize=200, \
              local_range=0.3, rf_center='kinEEPos', global_data=False, \
              success_viz=True, failure_viz=False, \
              raw_viz=False, interp_viz=False, save_pdf=False, \
              successData=False, failureData=True,\
              continuousPlot=False, \
              ## trainingData=True, normalTestData=False, abnormalTestData=False,\
              modality_list=['audio'], data_renew=False, verbose=False):    

    if os.path.isdir(processed_data_path) is False:
        os.system('mkdir -p '+processed_data_path)

    success_list, failure_list = getSubjectFileList(raw_data_path, subject_names, task_name)

    fig = plt.figure('all')
    time_lim    = [0.01, 0] 
    nPlot       = len(modality_list)

    for idx, file_list in enumerate([success_list, failure_list]):
        if idx == 0 and successData is not True: continue
        elif idx == 1 and failureData is not True: continue        

        ## fig = plt.figure('loadData')                        
        # loading and time-sync
        if idx == 0:
            if verbose: print "Load success data"
            data_pkl = os.path.join(processed_data_path, task+'_success_'+rf_center+\
                                    '_'+str(local_range))
            raw_data_dict, interp_data_dict = loadData(success_list, isTrainingData=True,
                                                       downSampleSize=downSampleSize,\
                                                       local_range=local_range, rf_center=rf_center,\
                                                       global_data=global_data, \
                                                       renew=data_renew, save_pkl=data_pkl, verbose=verbose)
        else:
            if verbose: print "Load failure data"
            data_pkl = os.path.join(processed_data_path, task+'_failure_'+rf_center+\
                                    '_'+str(local_range))
            raw_data_dict, interp_data_dict = loadData(failure_list, isTrainingData=False,
                                                       downSampleSize=downSampleSize,\
                                                       local_range=local_range, rf_center=rf_center,\
                                                       global_data=global_data,\
                                                       renew=data_renew, save_pkl=data_pkl, verbose=verbose)
            
        ## plt.show()
        ## sys.exit()
        if raw_viz: target_dict = raw_data_dict
        else: target_dict = interp_data_dict

        # check only training data to get time limit (TEMP)
        if idx == 0:
            for key in interp_data_dict.keys():
                if 'timesList' in key:
                    time_list = interp_data_dict[key]
                    if len(time_list)==0: continue
                    for tl in time_list:
                        ## print tl[-1]
                        time_lim[-1] = max(time_lim[-1], tl[-1])
            ## continue

        # for each file in success or failure set
        for fidx in xrange(len(file_list)):
                        
            count = 0
            for modality in modality_list:
                count +=1

                if 'audioWrist' in modality:
                    time_list = target_dict['audioWristTimesList']
                    data_list = target_dict['audioWristRMSList']
                    
                elif 'audio' in modality:
                    time_list = target_dict['audioTimesList']
                    data_list = target_dict['audioPowerList']

                elif 'kinematics' in modality:
                    time_list = target_dict['kinTimesList']
                    data_list = target_dict['kinPosList']

                    # distance
                    new_data_list = []
                    for d in data_list:
                        new_data_list.append( np.linalg.norm(d, axis=0) )
                    data_list = new_data_list

                elif 'ft' in modality:
                    time_list = target_dict['ftTimesList']
                    data_list = target_dict['ftForceList']

                    # distance
                    if len(np.shape(data_list[0])) > 1:
                        new_data_list = []
                        for d in data_list:
                            new_data_list.append( np.linalg.norm(d, axis=0) )
                        data_list = new_data_list

                elif 'vision_artag' in modality:
                    time_list = target_dict['visionArtagTimesList']
                    data_list = target_dict['visionArtagPosList']

                    # distance
                    new_data_list = []
                    for d in data_list:                    
                        new_data_list.append( np.linalg.norm(d[:3], axis=0) )
                    data_list = new_data_list

                elif 'vision_change' in modality:
                    time_list = target_dict['visionChangeTimesList']
                    data_list = target_dict['visionChangeMagList']

                elif 'pps' in modality:
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

                elif 'fabric' in modality:
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
                if idx == 0: color = 'b'
                else: color = 'r'            

                if raw_viz:
                    combined_time_list = []
                    if data_list == []: continue

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

                    if continuousPlot:
                        new_color = 'm'
                        i         = fidx
                        if len(time_list[i]) > len(data_list[i]):
                            ax.plot(time_list[i][:len(data_list[i])], data_list[i], c=new_color, lw=3.0)
                        else:
                            ax.plot(time_list[i], data_list[i][:len(time_list[i])], c=new_color, lw=3.0)
                                                    
                else:
                    interp_time = np.linspace(time_lim[0], time_lim[1], num=downSampleSize)
                    for i in xrange(len(data_list)):
                        ax.plot(interp_time, data_list[i], c=color)                
                
                ax.set_xlim(time_lim)
                ax.set_title(modality)

            #------------------------------------------------------------------------------    
            if continuousPlot is False: break
            else:
                        
                print "-----------------------------------------------"
                print file_list[fidx]
                print "-----------------------------------------------"

                plt.tight_layout(pad=0.1, w_pad=0.5, h_pad=0.0)

                if save_pdf is False:
                    plt.show()
                else:
                    print "Save pdf to Dropbox folder"
                    fig.savefig('test.pdf')
                    fig.savefig('test.png')
                    os.system('mv test.p* ~/Dropbox/HRL/')

                fig = plt.figure('all')

                
    plt.tight_layout(pad=0.1, w_pad=0.5, h_pad=0.0)

    if save_pdf is False:
        plt.show()
    else:
        print "Save pdf to Dropbox folder"
        fig.savefig('test.pdf')
        fig.savefig('test.png')
        os.system('mv test.p* ~/Dropbox/HRL/')


    ## # training set
    ## trainingData, param_dict = extractFeature(data_dict['trainData'], feature_list, local_range)

    ## # test set
    ## normalTestData, _ = extractFeature(data_dict['normalTestData'], feature_list, local_range, \
    ##                                         param_dict=param_dict)        
    ## abnormalTestData, _ = extractFeature(data_dict['abnormalTestData'], feature_list, local_range, \
    ##                                         param_dict=param_dict)

    ## print "======================================"
    ## print "Training data: ", np.shape(trainingData)
    ## print "Normal test data: ", np.shape(normalTestData)
    ## print "Abnormal test data: ", np.shape(abnormalTestData)
    ## print "======================================"

    ## visualization_hmm_data(feature_list, trainingData=trainingData, \
    ##                        normalTestData=normalTestData,\
    ##                        abnormalTestData=abnormalTestData, save_pdf=save_pdf)        
    

def data_selection(subject_names, task_name, raw_data_path, processed_data_path, \
                  downSampleSize=200, \
                  local_range=0.3, rf_center='kinEEPos', \
                  success_viz=True, failure_viz=False, \
                  raw_viz=False, save_pdf=False, \
                  modality_list=['audio'], data_renew=False, verbose=False):    

    ## success_list, failure_list = getSubjectFileList(raw_data_path, subject_names, task_name)
    
    # Success data
    successData = success_viz
    failureData = failure_viz

    count = 0
    while True:
        
        ## success_list, failure_list = getSubjectFileList(raw_data_path, subject_names, task_name)        
        ## print "-----------------------------------------------"
        ## print success_list[count]
        ## print "-----------------------------------------------"
        
        data_plot(subject_names, task_name, raw_data_path, processed_data_path,\
                  downSampleSize=downSampleSize, \
                  local_range=local_range, rf_center=rf_center, \
                  raw_viz=True, interp_viz=False, save_pdf=save_pdf,\
                  successData=successData, failureData=failureData,\
                  continuousPlot=True, \
                  modality_list=modality_list, data_renew=data_renew, verbose=verbose)

        break

        ## feedback  = raw_input('Do you want to exclude the data? (e.g. y:yes n:no else: exit): ')
        ## if feedback == 'y':
        ##     print "move data"
        ##     ## os.system('mv '+subject_names+' ')
        ##     data_renew = True

        ## elif feedback == 'n':
        ##     print "keep data"
        ##     data_renew = False
        ##     count += 1
        ## else:
        ##     break
   

    


if __name__ == '__main__':

    import optparse
    p = optparse.OptionParser()
    p.add_option('--dataRenew', '--dr', action='store_true', dest='bDataRenew',
                 default=False, help='Renew pickle files.')
    p.add_option('--AERenew', '--ar', action='store_true', dest='bAERenew',
                 default=False, help='Renew AE data.')
    p.add_option('--hmmRenew', '--hr', action='store_true', dest='bHMMRenew',
                 default=False, help='Renew HMM parameters.')

    p.add_option('--task', action='store', dest='task', type='string', default='pushing',
                 help='type the desired task name')

    p.add_option('--rawplot', '--rp', action='store_true', dest='bRawDataPlot',
                 default=False, help='Plot raw data.')
    p.add_option('--interplot', '--ip', action='store_true', dest='bInterpDataPlot',
                 default=False, help='Plot raw data.')
    p.add_option('--feature', '--ft', action='store_true', dest='bFeaturePlot',
                 default=False, help='Plot features.')
    p.add_option('--likelihoodplot', '--lp', action='store_true', dest='bLikelihoodPlot',
                 default=False, help='Plot the change of likelihood.')
    p.add_option('--dataselect', '--ds', action='store_true', dest='bDataSelection',
                 default=False, help='Plot data and select it.')
    
    p.add_option('--aeDataExtraction', '--ae', action='store_true', dest='bAEDataExtraction',
                 default=False, help='Extract auto-encoder data.')
    p.add_option('--aeDataExtractionPlot', '--aep', action='store_true', dest='bAEDataExtractionPlot',
                 default=False, help='Extract auto-encoder data and plot it.')
    p.add_option('--aeDataAddFeature', '--aea', action='store_true', dest='bAEDataAddFeature',
                 default=False, help='Add hand-crafted data.')

    p.add_option('--evaluation_all', '--ea', action='store_true', dest='bEvaluationAll',
                 default=False, help='Evaluate a classifier with cross-validation.')
    
    p.add_option('--renew', action='store_true', dest='bRenew',
                 default=False, help='Renew pickle files.')
    p.add_option('--savepdf', '--sp', action='store_true', dest='bSavePdf',
                 default=False, help='Save pdf files.')    
    p.add_option('--verbose', '--v', action='store_true', dest='bVerbose',
                 default=False, help='Print out.')

    
    opt, args = p.parse_args()

    #---------------------------------------------------------------------------           
    # Run evaluation
    #---------------------------------------------------------------------------           
    rf_center     = 'kinEEPos'        
    scale         = 1.0
    # Dectection TEST 
    local_range    = 10.0    

    if opt.task == 'scooping':
        ## subjects = ['gatsbii']
        subjects = ['Wonyoung', 'Tom', 'lin', 'Ashwin', 'Song', 'Henry2'] #'Henry', 
        task     = opt.task

        raw_data_path, save_data_path, param_dict = getScooping(opt.task, opt.bDataRenew, \
                                                                opt.bAERenew, opt.bHMMRenew,\
                                                                rf_center, local_range)
        
    #---------------------------------------------------------------------------
    elif opt.task == 'feeding':
        
        subjects = ['Tom', 'lin', 'Ashwin', 'Song'] #'Wonyoung']
        task     = opt.task 
        raw_data_path, save_data_path, param_dict = getFeeding(opt.task, opt.bDataRenew, \
                                                               opt.bAERenew, opt.bHMMRenew,\
                                                               rf_center, local_range)
        
    #---------------------------------------------------------------------------           
    elif opt.task == 'pushing':
        subjects = ['gatsbii']
        task     = opt.task
        raw_data_path, save_data_path, param_dict = getPushingMicroWhite(opt.task, opt.bDataRenew, \
                                                                         opt.bAERenew, opt.bHMMRenew,\
                                                                         rf_center, local_range)
        
    else:
        print "Selected task name is not available."
        sys.exit()

    #---------------------------------------------------------------------------
    ## if opt.bAEDataAddFeature:
    ##     param_dict['AE']['add_option'] = ['wristAudio'] #'featureToBottleneck'
    ##     param_dict['AE']['switch']     = True
    
    #---------------------------------------------------------------------------           
    #---------------------------------------------------------------------------           
    #---------------------------------------------------------------------------           
    #---------------------------------------------------------------------------           
    

    if opt.bRawDataPlot or opt.bInterpDataPlot:
        '''
        Before localization: Raw data plot
        After localization: Raw or interpolated data plot
        '''
        successData = True
        failureData = True
        
        data_plot(subjects, task, raw_data_path, save_data_path,\
                  downSampleSize=downSampleSize, \
                  local_range=local_range, rf_center=rf_center, \
                  raw_viz=opt.bRawDataPlot, interp_viz=opt.bInterpDataPlot, save_pdf=opt.bSavePdf,\
                  successData=successData, failureData=failureData,\
                  modality_list=modality_list, data_renew=opt.bDataRenew, verbose=opt.bVerbose)

    elif opt.bDataSelection:
        '''
        Manually select and filter bad data out
        '''
        ## modality_list   = ['kinematics', 'audioWrist','audio', 'fabric', 'ft', \
        ##                    'vision_artag', 'vision_change', 'pps']
        success_viz = True
        failure_viz = True

        data_selection(subjects, task, raw_data_path, save_data_path,\
                       downSampleSize=downSampleSize, \
                       local_range=local_range, rf_center=rf_center, \
                       success_viz=success_viz, failure_viz=failure_viz,\
                       raw_viz=opt.bRawDataPlot, save_pdf=opt.bSavePdf,\
                       modality_list=modality_list, data_renew=opt.bDataRenew, verbose=opt.bVerbose)        

    elif opt.bFeaturePlot:
        success_viz = True
        failure_viz = True

        dm.getDataSet(subjects, task, raw_data_path, save_data_path,
                      param_dict['data_param']['rf_center'], param_dict['data_param']['local_range'],\
                      downSampleSize=param_dict['data_param']['downSampleSize'], scale=scale, \
                      success_viz=success_viz, failure_viz=failure_viz,\
                      ae_data=param_dict['AE']['switch'],\
                      data_ext=param_dict['data_param']['lowVarDataRemv'],\
                      cut_data=param_dict['data_param']['cut_data'],
                      save_pdf=opt.bSavePdf, solid_color=True,\
                      handFeatures=param_dict['data_param']['handFeatures'], data_renew=opt.bDataRenew)

    elif opt.bAEDataExtraction:
        aeDataExtraction(subjects, task, raw_data_path, save_data_path, param_dict, verbose=opt.bVerbose)

    elif opt.bAEDataExtractionPlot:
        success_viz = True
        failure_viz = True
        handFeature_viz = True
        aeDataExtraction(subjects, task, raw_data_path, save_data_path, param_dict,\
                         handFeature_viz=handFeature_viz,\
                         success_viz=success_viz, failure_viz=failure_viz,\
                         verbose=opt.bVerbose)


    elif opt.bLikelihoodPlot:
        likelihoodOfSequences(subjects, task, raw_data_path, save_data_path, param_dict,\
                              decision_boundary_viz=True, \
                              useTrain=True, useNormalTest=False, useAbnormalTest=True,\
                              useTrain_color=False, useNormalTest_color=False, useAbnormalTest_color=False,\
                              hmm_renew=opt.bHMMRenew, data_renew=opt.bDataRenew, save_pdf=opt.bSavePdf)
                              
    elif opt.bEvaluationAll:                
        evaluation_all(subjects, task, raw_data_path, save_data_path, param_dict, save_pdf=opt.bSavePdf, \
                       verbose=opt.bVerbose)


