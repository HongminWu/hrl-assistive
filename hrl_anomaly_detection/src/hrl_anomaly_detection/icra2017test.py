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
from hrl_anomaly_detection.ICRA2017_params import *
from hrl_anomaly_detection.optimizeParam import *
from hrl_anomaly_detection import util as util

# learning
## from hrl_anomaly_detection.hmm import learning_hmm_multi_n as hmm
from hrl_anomaly_detection.hmm import learning_hmm as hmm
from mvpa2.datasets.base import Dataset
## from sklearn import svm
from joblib import Parallel, delayed
from sklearn import metrics
from sklearn.grid_search import ParameterGrid

# private learner
import hrl_anomaly_detection.classifiers.classifier as cf
import hrl_anomaly_detection.data_viz as dv

import itertools
colors = itertools.cycle(['g', 'm', 'c', 'k', 'y','r', 'b', ])
shapes = itertools.cycle(['x','v', 'o', '+'])

matplotlib.rcParams['pdf.fonttype'] = 42
matplotlib.rcParams['ps.fonttype'] = 42 
random.seed(3334)
np.random.seed(3334)

def evaluation_all(subject_names, task_name, raw_data_path, processed_data_path, param_dict,\
                   data_renew=False, save_pdf=False, verbose=False, debug=False,\
                   no_plot=False, delay_plot=True, find_param=False, data_gen=False):

    ## Parameters
    # data
    data_dict  = param_dict['data_param']
    data_renew = data_dict['renew']
    # HMM
    HMM_dict   = param_dict['HMM']
    nState     = HMM_dict['nState']
    cov        = HMM_dict['cov']
    add_logp_d = HMM_dict.get('add_logp_d', False)
    # SVM
    SVM_dict   = param_dict['SVM']

    # ROC
    ROC_dict = param_dict['ROC']
    
    #------------------------------------------

   
    if os.path.isdir(processed_data_path) is False:
        os.system('mkdir -p '+processed_data_path)

    crossVal_pkl = os.path.join(processed_data_path, 'cv_'+task_name+'.pkl')
    
    if os.path.isfile(crossVal_pkl) and data_renew is False and data_gen is False:
        print "CV data exists and no renew"
        d = ut.load_pickle(crossVal_pkl)
        kFold_list = d['kFoldList'] 
    else:
        '''
        Use augmented data? if nAugment is 0, then aug_successData = successData
        '''        
        d = dm.getDataSet(subject_names, task_name, raw_data_path, \
                           processed_data_path, data_dict['rf_center'], data_dict['local_range'],\
                           downSampleSize=data_dict['downSampleSize'], scale=1.0,\
                           handFeatures=data_dict['handFeatures'], \
                           ## rawFeatures=AE_dict['rawFeatures'],\
                           data_renew=data_renew, max_time=data_dict['max_time'])

        # TODO: need leave-one-person-out
        # Task-oriented hand-crafted features        
        kFold_list = dm.kFold_data_index(len(d['successData'][0]), len(d['failureData'][0]), \
                                          data_dict['nNormalFold'], data_dict['nAbnormalFold'] )
        d['kFoldList']   = kFold_list
        ut.save_pickle(d, crossVal_pkl)
        if data_gen: sys.exit()

    #-----------------------------------------------------------------------------------------
    # parameters
    startIdx    = 4
    method_list = ROC_dict['methods'] 
    nPoints     = ROC_dict['nPoints']

    successData = d['successData']
    failureData = d['failureData']
    param_dict2  = d['param_dict']
    if 'timeList' in param_dict2.keys():
        timeList    = param_dict2['timeList'][startIdx:]
    else: timeList = None

    #-----------------------------------------------------------------------------------------
    # Training HMM, and getting classifier training and testing data
    for idx, (normalTrainIdx, abnormalTrainIdx, normalTestIdx, abnormalTestIdx) \
      in enumerate(kFold_list):

        if verbose: print idx, " : training hmm and getting classifier training and testing data"
        modeling_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'_'+str(idx)+'.pkl')

        if not (os.path.isfile(modeling_pkl) is False or HMM_dict['renew'] or data_renew): continue

        # dim x sample x length
        normalTrainData   = successData[:, normalTrainIdx, :] * HMM_dict['scale']
        abnormalTrainData = failureData[:, abnormalTrainIdx, :] * HMM_dict['scale'] 
        normalTestData    = successData[:, normalTestIdx, :] * HMM_dict['scale'] 
        abnormalTestData  = failureData[:, abnormalTestIdx, :] * HMM_dict['scale'] 

        # training hmm
        if verbose: print "start to fit hmm"
        nEmissionDim = len(normalTrainData)
        cov_mult     = [cov]*(nEmissionDim**2)
        nLength      = len(normalTrainData[0][0]) - startIdx

        ml  = hmm.learning_hmm(nState, nEmissionDim, verbose=verbose) 
        if data_dict['handFeatures_noise']:
            ret = ml.fit(normalTrainData+\
                         np.random.normal(0.0, 0.03, np.shape(normalTrainData) )*HMM_dict['scale'], \
                         cov_mult=cov_mult, use_pkl=False)
        else:
            ret = ml.fit(normalTrainData, cov_mult=cov_mult, use_pkl=False)

        if ret == 'Failure' or np.isnan(ret): return (-1,-1,-1,-1)

        # Classifier training data
        ll_classifier_train_X, ll_classifier_train_Y, ll_classifier_train_idx =\
          hmm.getHMMinducedFeaturesFromRawFeatures(ml, normalTrainData, abnormalTrainData, startIdx, add_logp_d)

        # Classifier test data
        ll_classifier_test_X, ll_classifier_test_Y, ll_classifier_test_idx =\
          hmm.getHMMinducedFeaturesFromRawFeatures(ml, normalTestData, abnormalTestData, startIdx, add_logp_d)

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
        d['scale']        = HMM_dict['scale']
        d['cov']          = HMM_dict['cov']
        ut.save_pickle(d, modeling_pkl)
        sys.exit()

    #-----------------------------------------------------------------------------------------
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
            ROC_data[method]['tp_delay_l'] = [ [] for j in xrange(nPoints) ]
            ROC_data[method]['tp_idx_l'] = [ [] for j in xrange(nPoints) ]

    osvm_data = None ; bpsvm_data = None
    if 'osvm' in method_list  and ROC_data['osvm']['complete'] is False:
        normalTrainData   = successData[:, normalTrainIdx, :] 
        abnormalTrainData = failureData[:, abnormalTrainIdx, :]

        fold_list = []
        for train_fold, test_fold in normal_folds:
            fold_list.append([train_fold, test_fold])

        normalFoldData = (fold_list, normalTrainData, abnormalTrainData)

        osvm_data = dm.getRawData(len(fold_list), normalFoldData=normalFoldData, \
                                  window=SVM_dict['raw_window_size'],
                                  use_test=True, use_pca=False )

    # parallelization
    if debug: n_jobs=1
    else: n_jobs=-1
    l_data = Parallel(n_jobs=n_jobs, verbose=50)(delayed(cf.run_classifiers)( idx, processed_data_path, \
                                                                         task_name, \
                                                                         method, ROC_data, \
                                                                         ROC_dict, \
                                                                         SVM_dict, HMM_dict, \
                                                                         raw_data=(osvm_data,bpsvm_data),\
                                                                         startIdx=startIdx, nState=nState) \
                                                                         for idx in xrange(len(kFold_list)) \
                                                                         for method in method_list )


    print "finished to run run_classifiers"
    for i in xrange(len(l_data)):
        for j in xrange(nPoints):
            try:
                method = l_data[i].keys()[0]
            except:                
                print "Error when collect ROC data:", l_data[i]
                sys.exit()
            if ROC_data[method]['complete'] == True: continue
            ROC_data[method]['tp_l'][j] += l_data[i][method]['tp_l'][j]
            ROC_data[method]['fp_l'][j] += l_data[i][method]['fp_l'][j]
            ROC_data[method]['tn_l'][j] += l_data[i][method]['tn_l'][j]
            ROC_data[method]['fn_l'][j] += l_data[i][method]['fn_l'][j]
            ROC_data[method]['delay_l'][j] += l_data[i][method]['delay_l'][j]
            ROC_data[method]['tp_delay_l'][j].append( l_data[i][method]['delay_l'][j] )
            ROC_data[method]['tp_idx_l'][j].append( l_data[i][method]['tp_idx_l'][j] )

    for i, method in enumerate(method_list):
        ROC_data[method]['complete'] = True

    ut.save_pickle(ROC_data, roc_pkl)

    #-----------------------------------------------------------------------------------------
    # ---------------- ROC Visualization ----------------------
    roc_info(method_list, ROC_data, nPoints, no_plot=True)




def evaluation_unexp(subject_names, unexpected_subjects, task_name, raw_data_path, processed_data_path, \
                     param_dict,\
                     data_renew=False, save_pdf=False, verbose=False, debug=False,\
                     no_plot=False, delay_plot=False, find_param=False, data_gen=False):

    ## Parameters
    # data
    data_dict  = param_dict['data_param']
    data_renew = data_dict['renew']
    # HMM
    HMM_dict   = param_dict['HMM']
    nState     = HMM_dict['nState']
    cov        = HMM_dict['cov']
    add_logp_d = HMM_dict.get('add_logp_d', False)
    # SVM
    SVM_dict   = param_dict['SVM']

    # ROC
    ROC_dict = param_dict['ROC']
    
    #------------------------------------------
    if os.path.isdir(processed_data_path) is False:
        os.system('mkdir -p '+processed_data_path)

    crossVal_pkl = os.path.join(processed_data_path, 'cv_'+task_name+'.pkl')
    
    if os.path.isfile(crossVal_pkl) and data_renew is False and data_gen is False:
        print "CV data exists and no renew"
    else:
        '''
        Use augmented data? if nAugment is 0, then aug_successData = successData
        '''        
        d = dm.getDataSet(subject_names, task_name, raw_data_path, \
                           processed_data_path, data_dict['rf_center'], data_dict['local_range'],\
                           downSampleSize=data_dict['downSampleSize'], scale=1.0,\
                           handFeatures=data_dict['handFeatures'], \
                           ## rawFeatures=AE_dict['rawFeatures'],\
                           data_renew=data_renew, max_time=data_dict['max_time'])

        # TODO: need leave-one-person-out
        # Task-oriented hand-crafted features        
        kFold_list = dm.kFold_data_index(len(d['successData'][0]), len(d['failureData'][0]), \
                                          data_dict['nNormalFold'], data_dict['nAbnormalFold'] )
        d['kFoldList']   = kFold_list
        ut.save_pickle(d, crossVal_pkl)
        if data_gen: sys.exit()

    #-----------------------------------------------------------------------------------------
    # parameters
    startIdx    = 4
    method_list = ROC_dict['methods'] 
    nPoints     = ROC_dict['nPoints']

    # Training HMM, and getting classifier training and testing data
    idx = 0
    modeling_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'_unexp_'+str(idx)+'.pkl')
    if not (os.path.isfile(modeling_pkl) is False or HMM_dict['renew'] or data_renew):
        print "learned hmm exists"
    else:
        d = ut.load_pickle(crossVal_pkl)
        
        # dim x sample x length
        normalTrainData   = d['successData'] * HMM_dict['scale']
        abnormalTrainData = d['failureData'] * HMM_dict['scale']
        handFeatureParams  = d['param_dict']

        # training hmm
        if verbose: print "start to fit hmm"
        nEmissionDim = len(normalTrainData)
        cov_mult     = [cov]*(nEmissionDim**2)
        nLength      = len(normalTrainData[0][0]) - startIdx

        ml  = hmm.learning_hmm(nState, nEmissionDim, verbose=verbose) 
        if data_dict['handFeatures_noise']:
            ret = ml.fit(normalTrainData+\
                         np.random.normal(0.0, 0.03, np.shape(normalTrainData) )*HMM_dict['scale'], \
                         cov_mult=cov_mult, use_pkl=False)
        else:
            ret = ml.fit(normalTrainData, cov_mult=cov_mult, use_pkl=False)

        if ret == 'Failure' or np.isnan(ret):
            print "Failed to fit"
            sys.exit()

        #-----------------------------------------------------------------------------------------
        # Classifier training data
        #-----------------------------------------------------------------------------------------
        ll_classifier_train_X, ll_classifier_train_Y, ll_classifier_train_idx =\
          hmm.getHMMinducedFeaturesFromRawFeatures(ml, normalTrainData, abnormalTrainData, startIdx, \
                                                   add_logp_d)

        #-----------------------------------------------------------------------------------------
        # Classifier test data
        #-----------------------------------------------------------------------------------------
        fileList = util.getSubjectFileList(raw_data_path, unexpected_subjects, \
                                           task_name, no_split=True)                
                                           
        testDataX,_ = dm.getDataList(fileList, data_dict['rf_center'], data_dict['local_range'],\
                                   handFeatureParams,\
                                   downSampleSize = data_dict['downSampleSize'], \
                                   cut_data       = data_dict['cut_data'],\
                                   handFeatures   = data_dict['handFeatures'])

        # scaling and applying offset            
        testDataX = np.array(testDataX)*HMM_dict['scale']
        testDataX = dm.applying_offset(testDataX, normalTrainData, startIdx, nEmissionDim)

        testDataY = []
        for f in fileList:
            if f.find("success")>=0:
                testDataY.append(-1)
            elif f.find("failure")>=0:
                testDataY.append(1)

        # Classifier test data
        ll_classifier_test_X, ll_classifier_test_Y, ll_classifier_test_idx =\
          hmm.getHMMinducedFeaturesFromRawCombinedFeatures(ml, testDataX, testDataY, startIdx, add_logp_d)

        #-----------------------------------------------------------------------------------------
        d = {}
        d['nEmissionDim'] = ml.nEmissionDim
        d['A']            = ml.A 
        d['B']            = ml.B 
        d['pi']           = ml.pi
        d['F']            = ml.F
        d['nState']       = nState
        d['startIdx']     = startIdx
        d['ll_classifier_train_X']     = ll_classifier_train_X
        d['ll_classifier_train_Y']     = ll_classifier_train_Y            
        d['ll_classifier_train_idx']   = ll_classifier_train_idx
        d['ll_classifier_test_X']      = ll_classifier_test_X
        d['ll_classifier_test_Y']      = ll_classifier_test_Y            
        d['ll_classifier_test_idx']    = ll_classifier_test_idx
        d['ll_classifier_test_labels'] = fileList
        d['nLength']      = nLength
        ut.save_pickle(d, modeling_pkl)


    #-----------------------------------------------------------------------------------------
    roc_pkl = os.path.join(processed_data_path, 'roc_'+task_name+'.pkl')
    if os.path.isfile(roc_pkl) is False or HMM_dict['renew']: ROC_data = {}
    else: ROC_data = ut.load_pickle(roc_pkl)
    ROC_data = util.reset_roc_data(ROC_data, method_list, ROC_dict['update_list'], nPoints)

    # parallelization
    if debug: n_jobs=1
    else: n_jobs=-1
    l_data = Parallel(n_jobs=n_jobs, verbose=1)(delayed(cf.run_classifiers)( idx, \
                                                                              processed_data_path, \
                                                                              task_name, \
                                                                              method, ROC_data, \
                                                                              ROC_dict, \
                                                                              SVM_dict, HMM_dict, \
                                                                              startIdx=startIdx, nState=nState,\
                                                                              failsafe=False)\
                                                                              for method in method_list )

    print "finished to run run_classifiers"
    ROC_data = util.update_roc_data(ROC_data, l_data, nPoints, method_list)
    ut.save_pickle(ROC_data, roc_pkl)
        
    # ---------------- ACC Visualization ----------------------
    acc_rates = acc_info(method_list, ROC_data, nPoints, delay_plot=delay_plot, \
                        no_plot=True, save_pdf=save_pdf, \
                        only_tpr=False, legend=True)

    #----------------- List up anomaly cases ------------------
    ## for method in method_list:
    ##     max_idx = np.argmax(acc_rates[method])

    ##     print "-----------------------------------"
    ##     print "Method: ", method
    ##     print acc_rates[method][max_idx]
        

    for method in method_list:
        n = len(ROC_data[method]['fn_labels'])
        a = []
        for i in range(nPoints):
            a += ROC_data[method]['fn_labels'][i]
            
        d = {x: a.count(x) for x in a}
        l_idx = np.array(d.values()).argsort()[-10:]


        print np.array(d.keys())[l_idx]
        print np.array(d.values())[l_idx]

        

    

def evaluation_online(subject_names, task_name, raw_data_path, processed_data_path, param_dict,\
                      data_renew=False, data_gen=False, many_to_one=False, \
                      n_random_trial=1, random_eval=False, find_param=False, \
                      viz=False, no_plot=False, delay_plot=False, save_pdf=False, \
                      save_result=False, verbose=False, debug=False, custom_mode=False,\
                      hmm_update=True):

    ## Parameters
    # data
    data_dict  = param_dict['data_param']
    data_renew = data_dict['renew']
    # HMM
    HMM_dict   = param_dict['HMM']
    nState     = HMM_dict['nState']
    cov        = HMM_dict['cov']
    add_logp_d = False #HMM_dict.get('add_logp_d', True)
    # SVM
    SVM_dict   = param_dict['SVM']
    # ROC
    ROC_dict   = param_dict['ROC']

    if many_to_one: prefix = 'm2o_'
    else: prefix = 'o2o_'
    
    #------------------------------------------
    if os.path.isdir(processed_data_path) is False:
        os.system('mkdir -p '+processed_data_path)

    '''
    Use augmented data? if nAugment is 0, then aug_successData = successData
    '''
    crossVal_pkl = os.path.join(processed_data_path, prefix+'cv_'+task_name+'.pkl')
    if os.path.isfile(crossVal_pkl) and data_renew is False and data_gen is False:
        print "CV data exists and no renew"
    else:
    
        # Get a data set with a leave-one-person-out
        print "Extract data using getDataLOPO"
        d = dm.getDataLOPO(subject_names, task_name, raw_data_path, \
                           processed_data_path, data_dict['rf_center'], data_dict['local_range'],\
                           downSampleSize=data_dict['downSampleSize'], scale=1.0,\
                           handFeatures=data_dict['handFeatures'], \
                           cut_data=data_dict['cut_data'], \
                           data_renew=data_renew, max_time=data_dict['max_time'])

        successData, failureData, _, _, kFold_list = dm.LOPO_data_index(d['successDataList'], \
                                                                        d['failureDataList'],\
                                                                        d['successFileList'],\
                                                                        d['failureFileList'],\
                                                                        many_to_one)

        d['successData'] = successData
        d['failureData'] = failureData
        d['kFoldList']   = kFold_list
        ut.save_pickle(d, crossVal_pkl)
                           
        if data_gen: sys.exit()

    #-----------------------------------------------------------------------------------------
    # parameters
    startIdx    = 4
    method_list = ROC_dict['methods'] 
    nPoints     = ROC_dict['nPoints']
    nPtrainData  = 20
    nTrainOffset = 2
    nTrainTimes  = 10
    nNormalTrain = 30

    # aws 5,4,  - 20, 2, 5, 30, 20
    # c11 8,8,  - 20, 2, 5, 30, 20 - good
    # c11 9.0,9.0,  - 20, 2, 5, 30, 20 * 0.1?  org 0.15

    # feeding
    # 9.0,9.0,  - 20, 2, 5, 30, 20 * 0.15 
    # 9.0,9.0,  - 20, 2, 5, 30, 20 * 0.1  
    # 7.5,7.5,  - 20, 2, 5, 30, 20 * 0.15
    # 9.0,9.0,  - 20, 2, 5, 30, 20 * 0.015 
    #[9(9), , 7.5(7.5), ????]
    ## if task_name == 'feeding':
    ##     scale_list  = [9, 9, 7.5, 9.]
    ##     cov_list    = [9, 9, 7.5, 9.]
    ##     alpha_coeff_list = [0.15, 0.1, 0.15, 0.015]

    
    # leave-one-person-out
    kFold_list = []
    for idx in xrange(len(subject_names)):
        idx_list = range(len(subject_names))
        train_idx = idx_list[:idx]+idx_list[idx+1:]
        test_idx  = idx_list[idx:idx+1]
        if many_to_one is False:
            for tidx in train_idx:
                kFold_list.append([[tidx], test_idx])
        else:
            kFold_list.append([train_idx, test_idx])


    #temp
    ## kFold_list = kFold_list[-1:]
    print kFold_list

    # Task-oriented hand-crafted features
    for idx, (train_idx, test_idx) in enumerate(kFold_list):
        print "Run kFold idx: ", idx, train_idx, test_idx
           
        # Training HMM, and getting classifier training and testing data
        modeling_pkl = os.path.join(processed_data_path, prefix+'hmm_'+task_name+'_'+str(idx)+'.pkl')
        if not (os.path.isfile(modeling_pkl) is False or HMM_dict['renew'] or data_renew):
            print "learned hmm exists"
        else:
            d = ut.load_pickle(crossVal_pkl)
            # person x dim x sample x length => sample x dim x length
            for i, tidx in enumerate(train_idx):
                if i == 0:
                    normalTrainData = np.swapaxes(d['successDataList'][tidx], 0, 1)
                    abnormalTrainData = np.swapaxes(d['failureDataList'][tidx], 0, 1)
                else:
                    normalTrainData = np.vstack([normalTrainData, np.swapaxes(d['successDataList'][tidx], 0, 1)])
                    abnormalTrainData = np.vstack([abnormalTrainData, np.swapaxes(d['failureDataList'][tidx], 0, 1)])

            for i, tidx in enumerate(test_idx):
                if i == 0:
                    normalTestData = np.swapaxes(d['successDataList'][tidx], 0, 1)
                    abnormalTestData = np.swapaxes(d['failureDataList'][tidx], 0, 1)
                else:
                    normalTestData = np.vstack([normalTestData, np.swapaxes(d['successDataList'][tidx], 0, 1)])
                    abnormalTestData = np.vstack([abnormalTestData, np.swapaxes(d['failureDataList'][tidx], 0, 1)])

            normalTrainData = np.swapaxes(normalTrainData, 0, 1) 
            abnormalTrainData = np.swapaxes(abnormalTrainData, 0, 1) 
            normalTestData = np.swapaxes(normalTestData, 0, 1) 
            abnormalTestData = np.swapaxes(abnormalTestData, 0, 1) 
            handFeatureParams = d['param_dict']

            # load hmm params
            if custom_mode:
                scale       = HMM_dict['scale']
                cov         = HMM_dict['cov']
                noise_max   = 0.0
                ## scale = scale_list[idx]
                ## cov   = scale_list[idx]
                ## alpha_coeff = alpha_coeff_list[idx]                
            else:
                if many_to_one:
                    scale       = ROC_dict['m2o']['hmm_scale']
                    cov         = ROC_dict['m2o']['hmm_cov']
                    noise_max   = ROC_dict['m2o']['noise_max']
                else:
                    scale       = ROC_dict['o2o']['hmm_scale']
                    cov         = ROC_dict['o2o']['hmm_cov']
                    noise_max   = ROC_dict['o2o']['noise_max']

            print "scale: ", scale, " cov: ", cov

            # training hmm
            if verbose: print "start to fit hmm"
            nEmissionDim = len(normalTrainData)
            nLength      = len(normalTrainData[0][0]) - startIdx
            cov_mult     = [cov]*(nEmissionDim**2)
            
            normalTrainData   *= scale
            abnormalTrainData *= scale
            normalTestData    *= scale
            abnormalTestData  *= scale

            # many to one adaptation
            if noise_max > 0.0:
                normalTrainData[:,0:3] += np.random.normal( 0, noise_max, \
                                                            np.shape(normalTrainData[:,0:3]) )*scale
            
            ml  = hmm.learning_hmm(nState, nEmissionDim, verbose=verbose)
            ret = ml.fit(normalTrainData+\
                         np.random.normal(0.0, 0.03, np.shape(normalTrainData) )*scale, \
                         cov_mult=cov_mult, use_pkl=False)
            if ret == 'Failure' or np.isnan(ret):
                print "hmm training failed"
                sys.exit()

            #-----------------------------------------------------------------------------------------
            # Classifier training data
            #-----------------------------------------------------------------------------------------
            ll_classifier_train_X, ll_classifier_train_Y, ll_classifier_train_idx =\
              hmm.getHMMinducedFeaturesFromRawFeatures(ml, normalTrainData, abnormalTrainData, startIdx, add_logp_d)

            #-----------------------------------------------------------------------------------------
            # Classifier partial train/test data
            #-----------------------------------------------------------------------------------------
            rndNormalTraindataIdx = range(len(normalTrainData[0]))
            random.shuffle(rndNormalTraindataIdx)

            #-----------------------------------------------------------------------------------------
            [A, B, pi, out_a_num, vec_num, mat_num, u_denom] = ml.get_hmm_object()

            dd = {}
            dd['nEmissionDim'] = ml.nEmissionDim
            dd['F']            = ml.F
            dd['nState']       = nState
            dd['A']            = A 
            dd['B']            = B 
            dd['pi']           = pi
            dd['out_a_num']    = out_a_num
            dd['vec_num']      = vec_num
            dd['mat_num']      = mat_num
            dd['u_denom']      = u_denom
            dd['startIdx']     = startIdx
            dd['ll_classifier_train_X']  = ll_classifier_train_X
            dd['ll_classifier_train_Y']  = ll_classifier_train_Y            
            dd['ll_classifier_train_idx']= ll_classifier_train_idx
            dd['normalTrainData'] = normalTrainData
            dd['rndNormalTraindataIdx'] = rndNormalTraindataIdx
            dd['nLength']      = nLength
            dd['scale']        = scale
            dd['cov']          = cov
            ut.save_pickle(dd, modeling_pkl)
            print modeling_pkl

    #-----------------------------------------------------------------------------------------
    if hmm_update:
        roc_pkl = os.path.join(processed_data_path, prefix+'roc_'+task_name+'.pkl')
    else:
        roc_pkl = os.path.join(processed_data_path, prefix+'roc_'+task_name+'_nohmm.pkl')
        
    if os.path.isfile(roc_pkl) is False or HMM_dict['renew'] or SVM_dict['renew']:        
        ROC_data = []
    else:
        ROC_data = ut.load_pickle(roc_pkl)

    for kFold_idx in xrange(len(kFold_list)):
        ROC_data.append({})
        for i, method in enumerate(method_list):
            for j in xrange(nTrainTimes+1):
                if method+'_'+str(j) not in ROC_data[kFold_idx].keys() or method in ROC_dict['update_list'] or\
                  SVM_dict['renew']:            
                    data = {}
                    data['complete'] = False 
                    data['tp_l']     = [ [] for jj in xrange(nPoints) ]
                    data['fp_l']     = [ [] for jj in xrange(nPoints) ]
                    data['tn_l']     = [ [] for jj in xrange(nPoints) ]
                    data['fn_l']     = [ [] for jj in xrange(nPoints) ]
                    data['delay_l']  = [ [] for jj in xrange(nPoints) ]
                    data['tp_idx_l']  = [ [] for jj in xrange(nPoints) ]
                    ROC_data[kFold_idx][method+'_'+str(j)] = data


    # temp
    ## kFold_list = kFold_list[0:1]
    d = ut.load_pickle(crossVal_pkl)

    print "Start the incremental evaluation"
    l_data = []
    for idx in xrange(len(kFold_list)):
        for jj in xrange(n_random_trial):
            r = run_online_classifier(idx, processed_data_path, task_name, method, \
                                      nPtrainData, nTrainOffset, nTrainTimes, \
                                      ROC_data, param_dict, \
                                      np.array([d['successDataList'][i] for i in kFold_list[idx][1]])[0],\
                                      np.array([d['failureDataList'][i] for i in kFold_list[idx][1]])[0],\
                                      verbose=debug, viz=viz, random_eval=random_eval, many_to_one=many_to_one,\
                                      hmm_update=hmm_update)
            l_data.append( (idx, r) )

    
    for (kFold_idx, data) in l_data:
        for i, method in enumerate(method_list):
            for j in xrange(nTrainTimes+1):
                if ROC_data[kFold_idx][method+'_'+str(j)]['complete']: continue
                for key in ROC_data[kFold_idx][method+'_'+str(j)].keys():
                    if key.find('complete')>=0: continue
                    for jj in xrange(nPoints):
                        ROC_data[kFold_idx][method+'_'+str(j)][key][jj] += data[method+'_'+str(j)][key][jj]

        
    for kFold_idx in xrange(len(kFold_list)):
        for i, method in enumerate(method_list):
            for j in xrange(nTrainTimes+1):
                print len(ROC_data[kFold_idx][method+'_'+str(j)]), j
                ROC_data[kFold_idx][method+'_'+str(j)]['complete'] = True

    ut.save_pickle(ROC_data, roc_pkl)
        
    #-----------------------------------------------------------------------------------------
    # ---------------- ROC Visualization ----------------------
    l_auc = []
    for kFold_idx in xrange(len(kFold_list)):
        auc_rates = roc_info(method_list, ROC_data[kFold_idx], nPoints, delay_plot=delay_plot, \
                             no_plot=no_plot, \
                             save_pdf=save_pdf, \
                             only_tpr=False, legend=True)

        acc_rates = acc_info(method_list, ROC_data[kFold_idx], nPoints, delay_plot=False, \
                             no_plot=no_plot, save_pdf=False, \
                             only_tpr=False, legend=True)


        print subject_names[kFold_idx], " : ", auc_rates
        auc = []
        for i in xrange(nTrainTimes+1):
            auc.append(auc_rates[method_list[0]+'_'+str(i)])
                
        l_auc.append(auc)

    if l_auc == []:
        print "empty l_auc"
        sys.exit()
    print "---------------------"
    l_auc = np.array(l_auc)
    l_auc_d = l_auc-l_auc[:,0:1]
    for auc in l_auc:
        print auc
    print "---------------------"
    for auc_d in l_auc_d:
        print auc_d
    print "---------------------"

    if len(kFold_list)>1:
        print "Mean: ", np.mean(l_auc_d, axis=0)
        print "Std:  ", np.std(l_auc_d, axis=0)




    if save_result or True:
        savefile = os.path.join(processed_data_path,'../','result_online_eval.txt')       
        if os.path.isfile(savefile) is False:
            with open(savefile, 'w') as file:
                file.write( "-----------------------------------------\n")
                file.write( "-----------------------------------------\n")
                file.write( 'nState: '+str(nState)+' scale: '+str(HMM_dict['scale'])+\
                            ' cov: '+str(HMM_dict['cov'])+'\n' )

                for auc in l_auc:
                    t = ''
                    for i in xrange(len(auc)):
                        t += str(auc[i])
                        t += ', '
                    t += ' \n'
                    file.write(t)
                file.write( "-----------------------------------------\n")

                t = 'Mean(d) '
                for v in np.mean(l_auc_d, axis=0):
                    t += str(v)
                    t += ', '
                t += ' \n'
                file.write(t)

                t = 'Std(d) '
                for v in np.std(l_auc_d, axis=0):
                    t += str(v)
                    t += ', '
                t += ' \n\n'
                file.write(t)
        else:
            with open(savefile, 'a') as file:
                file.write( "-----------------------------------------\n")
                file.write( "-----------------------------------------\n")
                file.write( 'nState: '+str(nState)+' scale: '+str(HMM_dict['scale'])+\
                            ' cov: '+str(HMM_dict['cov'])+'\n' )

                for auc in l_auc:
                    t = ''
                    for i in xrange(len(auc)):
                        t += str(auc[i])
                        t += ', '
                    t += ' \n'
                    file.write(t)
                file.write( "-----------------------------------------\n")

                t = 'Mean(d) '
                for v in np.mean(l_auc_d, axis=0):
                    t += str(v)
                    t += ', '
                t += ' \n'
                file.write(t)

                t = 'Std(d) '
                for v in np.std(l_auc_d, axis=0):
                    t += str(v)
                    t += ', '
                t += ' \n\n'
                file.write(t)



def evaluation_online_multi(subject_names, task_name, raw_data_path, processed_data_path, \
                            param_dict, n_random_trial=1, random_eval=False, many_to_one=False,\
                            data_renew=False, \
                            verbose=False, debug=False):

    parameters = {'nState': [25], 'scale': np.linspace(11.0,13.0,3) }
    param_list = list(ParameterGrid(parameters))

    for param in param_list:
        
        param_dict['ROC']['m2o']['hmm_scale'] = param['scale']
        param_dict['ROC']['m2o']['hmm_cov']   = param['scale']
        param_dict['ROC']['o2o']['hmm_scale'] = param['scale']
        param_dict['ROC']['o2o']['hmm_cov'] = param['scale']
        param_dict['HMM']['nState'] = param['nState']
        param_dict['HMM']['scale']  = param['scale']
        param_dict['HMM']['cov']    = param['scale']
        param_dict['HMM']['renew']  = True

        print param_dict['HMM']

        evaluation_online(subjects, opt.task, raw_data_path, save_data_path, \
                          param_dict, n_random_trial=n_random_trial, random_eval=random_eval, \
                          many_to_one=False, data_renew=data_renew, no_plot=True,\
                          save_result=True, verbose=verbose, debug=debug)
        data_renew = False
        ## sys.exit()
        

def evaluation_acc(subject_names, task_name, raw_data_path, processed_data_path, param_dict,\
                   data_renew=False, save_pdf=False, verbose=False, debug=False,\
                   no_plot=False):
    ''' find best threshold parameter and find the list of labels that failed to detect over methods
    '''
    ## Parameters
    # data
    data_dict  = param_dict['data_param']
    data_renew = data_dict['renew']
    # HMM
    HMM_dict   = param_dict['HMM']
    nState     = HMM_dict['nState']
    cov        = HMM_dict['cov']
    add_logp_d = HMM_dict.get('add_logp_d', False)
    # SVM
    SVM_dict   = param_dict['SVM']

    # ROC
    ROC_dict = param_dict['ROC']
    
    #------------------------------------------
    if os.path.isdir(processed_data_path) is False:
        os.system('mkdir -p '+processed_data_path)

    crossVal_pkl = os.path.join(processed_data_path, 'cv_'+task_name+'.pkl')
    
    if os.path.isfile(crossVal_pkl):
        print "CV data exists and no renew"
        d = ut.load_pickle(crossVal_pkl)
        kFold_list = d['kFoldList']
    else:
        print "No CV data"
        sys.exit()

    #-----------------------------------------------------------------------------------------
    # parameters
    startIdx    = 4
    method_list = ROC_dict['methods'] 
    nPoints     = ROC_dict['nPoints']

    successData = d['successData']
    failureData = d['failureData']
    param_dict2  = d['param_dict']
    if 'timeList' in param_dict2.keys():
        timeList    = param_dict2['timeList'][startIdx:]
    else: timeList = None
    handFeatureParams = d['param_dict']
    normalTrainData   = d['successData'] * HMM_dict['scale']

    #-----------------------------------------------------------------------------------------
    # Training HMM, and getting classifier training and testing data
    for idx, (normalTrainIdx, abnormalTrainIdx, normalTestIdx, abnormalTestIdx) \
      in enumerate(kFold_list):

        if verbose: print idx, " : training hmm and getting classifier training and testing data"
        modeling_pkl = os.path.join(processed_data_path, 'hmm_'+task_name+'_'+str(idx)+'.pkl')
        if not (os.path.isfile(modeling_pkl) is False or HMM_dict['renew'] or data_renew):
            continue
        
        dd = ut.load_pickle(modeling_pkl)
        nEmissionDim = dd['nEmissionDim']
        ml  = hmm.learning_hmm(nState, nEmissionDim, verbose=verbose) 
        ml.set_hmm_object(dd['A'],dd['B'],dd['pi'])

        #-----------------------------------------------------------------------------------------
        # Classifier test data
        #-----------------------------------------------------------------------------------------
        fileList = util.getSubjectFileList(raw_data_path, subject_names, \
                                           task_name, no_split=True)                
                                           
        testDataX,_ = dm.getDataList(fileList, data_dict['rf_center'], data_dict['local_range'],\
                                   handFeatureParams,\
                                   downSampleSize = data_dict['downSampleSize'], \
                                   cut_data       = data_dict['cut_data'],\
                                   handFeatures   = data_dict['handFeatures'])

        # scaling and applying offset            
        testDataX = np.array(testDataX)*HMM_dict['scale']
        testDataX = dm.applying_offset(testDataX, normalTrainData, startIdx, nEmissionDim)

        testDataY = []
        for f in fileList:
            if f.find("success")>=0:
                testDataY.append(-1)
            elif f.find("failure")>=0:
                testDataY.append(1)

        # Classifier test data
        ll_classifier_test_X, ll_classifier_test_Y, ll_classifier_test_idx =\
          hmm.getHMMinducedFeaturesFromRawCombinedFeatures(ml, testDataX, testDataY, startIdx, add_logp_d)
        
        #-----------------------------------------------------------------------------------------
        dd['ll_classifier_test_X']      = ll_classifier_test_X
        dd['ll_classifier_test_Y']      = ll_classifier_test_Y            
        dd['ll_classifier_test_idx']    = ll_classifier_test_idx
        dd['ll_classifier_test_labels'] = fileList
        ut.save_pickle(dd, modeling_pkl)

    #-----------------------------------------------------------------------------------------
    roc_pkl = os.path.join(processed_data_path, 'roc_'+task_name+'_anomaly.pkl')
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
            ROC_data[method]['delay_l']   = [ [] for j in xrange(nPoints) ]
            ROC_data[method]['fn_labels'] = [ [] for j in xrange(nPoints) ]

    # parallelization
    if debug: n_jobs=1
    else: n_jobs=-1
    l_data = Parallel(n_jobs=n_jobs, verbose=1)(delayed(cf.run_classifiers)( idx, \
                                                                              processed_data_path, \
                                                                              task_name, \
                                                                              method, ROC_data, \
                                                                              ROC_dict, \
                                                                              SVM_dict, HMM_dict, \
                                                                              startIdx=startIdx, nState=nState,\
                                                                              failsafe=False)\
                                                                              for idx in xrange(len(kFold_list))
                                                                              for method in method_list )

    print "finished to run run_classifiers"
    for data in l_data:
        for j in xrange(nPoints):
            try:
                method = data.keys()[0]
            except:
                print "no method key in data: ", data
                sys.exit()
            if ROC_data[method]['complete'] == True: continue
            ROC_data[method]['tp_l'][j] += data[method]['tp_l'][j]
            ROC_data[method]['fp_l'][j] += data[method]['fp_l'][j]
            ROC_data[method]['tn_l'][j] += data[method]['tn_l'][j]
            ROC_data[method]['fn_l'][j] += data[method]['fn_l'][j]
            ROC_data[method]['delay_l'][j] += data[method]['delay_l'][j]
            ROC_data[method]['fn_labels'][j] += data[method]['fn_labels'][j]

    for i, method in enumerate(method_list):
        ROC_data[method]['complete'] = True

    ut.save_pickle(ROC_data, roc_pkl)


    # get best param
    roc_pkl        = os.path.join(processed_data_path, 'roc_'+task_name+'.pkl')
    ROC_data_ref   = ut.load_pickle(roc_pkl)    
    best_param_idx = getBestParamIdx(method_list, ROC_data_ref, nPoints, verbose=False)

    print len(kFold_list)
    print method_list
    print best_param_idx

    for i, method in enumerate(method_list):
        idx = best_param_idx[i][0]
        
        a = ROC_data[method]['fn_labels'][idx]            
        d = {x: a.count(x) for x in a}
        l_idx = np.array(d.values()).argsort()[-10:]
        print np.array(d.keys())[l_idx]
        print np.array(d.values())[l_idx]

        tp_l = ROC_data[method]['tp_l'][idx]
        fn_l = ROC_data[method]['fn_l'][idx]        
        print "tpr: ", float(np.sum(tp_l))/float(np.sum(tp_l)+np.sum(fn_l))*100.0
    


    

def run_online_classifier(idx, processed_data_path, task_name, method, nPtrainData,\
                          nTrainOffset, nTrainTimes, ROC_data, param_dict, \
                          normalDataX, abnormalDataX, verbose=False, viz=False,\
                          random_eval=False, many_to_one=False, hmm_update=True):
    '''
    '''
    HMM_dict = param_dict['HMM']
    SVM_dict = param_dict['SVM']
    ROC_dict = param_dict['ROC']
    
    method_list = ROC_dict['methods'] 
    nPoints     = ROC_dict['nPoints']
    add_logp_d  = False #HMM_dict.get('add_logp_d', True)
    if many_to_one:
        nSubSample  = ROC_dict['m2o']['gp_nSubsample']
        alpha_coeff = ROC_dict['m2o']['alpha_coeff']
        prefix      = 'm2o_'
    else:
        nSubSample  = ROC_dict['o2o']['gp_nSubsample']
        alpha_coeff = ROC_dict['o2o']['alpha_coeff']
        prefix      = 'o2o_'
        
    
    ROC_data_cur = {}
    for i, m in enumerate(method_list):
        for j in xrange(nTrainTimes+1):
            data = {}
            data['complete'] = False 
            data['tp_l']     = [ [] for jj in xrange(nPoints) ]
            data['fp_l']     = [ [] for jj in xrange(nPoints) ]
            data['tn_l']     = [ [] for jj in xrange(nPoints) ]
            data['fn_l']     = [ [] for jj in xrange(nPoints) ]
            data['delay_l']  = [ [] for jj in xrange(nPoints) ]
            data['tp_idx_l'] = [ [] for jj in xrange(nPoints) ]
            ROC_data_cur[m+'_'+str(j)] = data
 
    #
    modeling_pkl = os.path.join(processed_data_path, prefix+'hmm_'+task_name+'_'+str(idx)+'.pkl')
    dd = ut.load_pickle(modeling_pkl)
    
    print modeling_pkl
    print dd.keys()

    nEmissionDim = dd['nEmissionDim']
    nState    = dd['nState']       
    A         = dd['A']      
    B         = dd['B']      
    pi        = dd['pi']     
    out_a_num = dd['out_a_num']
    vec_num   = dd['vec_num']  
    mat_num   = dd['mat_num']  
    u_denom   = dd['u_denom']  
    startIdx  = dd['startIdx']
    nLength   = dd['nLength']
    scale     = dd['scale'] 

    #-----------------------------------------------------------------------------------------
    # Classifier partial train/test data
    #-----------------------------------------------------------------------------------------
    normalTrainData       = dd['normalTrainData']

    if random_eval:
        rndNormalTraindataIdx = range(len(normalTrainData[0]))
        random.shuffle(rndNormalTraindataIdx)
    else:
        rndNormalTraindataIdx = dd['rndNormalTraindataIdx']
    normalPtrainData      = normalTrainData[:,rndNormalTraindataIdx[:nPtrainData],:]

    # Incremental evaluation
    normalData   = copy.copy(normalDataX) * scale
    abnormalData = copy.copy(abnormalDataX) * scale

    # random split into two groups
    normalDataIdx   = range(len(normalData[0]))
    ## abnormalDataIdx = range(len(abnormalData[0]))
    random.shuffle(normalDataIdx)
    ## random.shuffle(abnormalDataIdx)

    normalTrainData = normalData[:,:nTrainOffset*nTrainTimes,:]
    normalTestData  = normalData[:,nTrainOffset*nTrainTimes:,:]
    ## abnormalTrainData = abnormalData[:,:len(abnormalDataIdx)/2,:]
    ## abnormalTestData  = abnormalData[:,len(abnormalDataIdx)/2:,:]
    abnormalTestData  = abnormalData

    testDataX = np.vstack([ np.swapaxes(normalTestData,0,1), np.swapaxes(abnormalTestData,0,1) ])
    testDataX = np.swapaxes(testDataX, 0,1)
    testDataY = np.hstack([-np.ones(len(normalTestData[0])), np.ones(len(abnormalTestData[0])) ])

    if len(normalPtrainData[0]) < nPtrainData:
        print "size of normal train data: ", len(normalPtrainData[0])
        sys.exit()
    if len(normalTrainData[0]) < nTrainOffset*nTrainTimes:
        print "size of normal partial fitting data for hmm: ", len(normalTrainData[0])
        print np.shape(normalDataX)
        print subject_names[test_idx[0]]
        sys.exit()

    #temp
    normalPtrainDataY = -np.ones(len(normalPtrainData[0]))


    ml = hmm.learning_hmm(nState, nEmissionDim, verbose=verbose) 
    ml.set_hmm_object(A,B,pi,out_a_num,vec_num,mat_num,u_denom)
    
    for i in xrange(nTrainTimes+1): 
        print "---------------- Train: ", i, " -----------------------"
        if ROC_data[idx][method+'_'+str(i)]['complete']: continue
        # partial fitting with
        if i > 0 and hmm_update:
            print "Run partial fitting with online HMM : ", i
            ## for j in xrange(nTrainOffset):
            ##     alpha = np.exp(-0.1*float((i-1)*nTrainOffset+j) )*0.02
            ##     print np.shape(normalTrainData[:,(i-1)*nTrainOffset+j:(i-1)*nTrainOffset+j+1]), i,j, alpha
            ##     ret = ml.partial_fit( normalTrainData[:,(i-1)*nTrainOffset+j:(i-1)*nTrainOffset+j+1], learningRate=alpha,\
            ##                           nrSteps=3) 

            alpha = np.exp(-0.5*float(i-1) )*alpha_coeff #0.15 #0.04
            ret = ml.partial_fit( normalTrainData[:,(i-1)*nTrainOffset:i*nTrainOffset]+\
                                  np.random.normal(0.0, 0.03, np.shape(normalTrainData[:,(i-1)*nTrainOffset:i*nTrainOffset]) )*scale,\
                                  learningRate=alpha, nrSteps=1 )
                                  
            if np.nan == ret or ret == 'Failure':
                print "Failed to partial fit hmm: ", i, ret
                sys.exit()
                
            # Update last samples
            normalPtrainData = np.vstack([ np.swapaxes(normalPtrainData,0,1), \
                                           np.swapaxes(normalTrainData[:,(i-1)*nTrainOffset:i*nTrainOffset],\
                                                       0,1) ])
            normalPtrainData = np.swapaxes(normalPtrainData, 0,1)
            normalPtrainData = np.delete(normalPtrainData, np.s_[:nTrainOffset],1)
            
        if method.find('svm')>=0 or method.find('sgd')>=0: remove_fp=True
        else: remove_fp = False
            
        # Get classifier training data using last 10 samples
        if method == 'hmmgp':
            ll_classifier_train_X, ll_classifier_train_Y, ll_classifier_train_idx = \
              hmm.getHMMinducedFeaturesFromRawCombinedFeatures(ml, normalPtrainData, \
                                                               -np.ones(len(normalPtrainData[0])), \
                                                               startIdx, \
                                                               add_logp_d=False, cov_type='full',\
                                                               nSubSample=nSubSample)

            for ii in reversed(range(len(ll_classifier_train_X))):
                if True in np.isnan( np.array(ll_classifier_train_X[ii]).flatten() ):
                    print "NaN in training data ", ii, len(ll_classifier_train_X)
                    del ll_classifier_train_X[ii]
                    del ll_classifier_train_Y[ii]
                    del ll_classifier_train_idx[ii]
                                                               
            # flatten the data
            X_train_org, Y_train_org, idx_train_org = dm.flattenSample(ll_classifier_train_X, \
                                                                       ll_classifier_train_Y, \
                                                                       ll_classifier_train_idx)

        else:
            r = Parallel(n_jobs=-1)(delayed(hmm.computeLikelihoods)(ii, ml.A, ml.B, ml.pi, ml.F, \
                                                                    [ normalPtrainData[jj][ii] for jj in \
                                                                      xrange(ml.nEmissionDim) ], \
                                                                      ml.nEmissionDim, ml.nState,\
                                                                      startIdx=startIdx, \
                                                                      bPosterior=True)
                                                                      for ii in xrange(len(normalPtrainData[0])))
            _, ll_classifier_train_idx, ll_logp, ll_post = zip(*r)

            X_train_org, Y_train_org, idx_train_org = \
              hmm.getHMMinducedFlattenFeatures(ll_logp, ll_post, ll_classifier_train_idx,\
                                               -np.ones(len(normalPtrainData[0])), \
                                               c=1.0, add_delta_logp=add_logp_d,\
                                               remove_fp=remove_fp, remove_outlier=True)
        if verbose: print "Partial set for classifier: ", np.shape(X_train_org), np.shape(Y_train_org)


        # -------------------------------------------------------------------------------
        print "Test data extraction"
        r = Parallel(n_jobs=-1)(delayed(hmm.computeLikelihoods)(ii, ml.A, ml.B, ml.pi, ml.F, \
                                                                [ testDataX[jj][ii] for jj in \
                                                                  xrange(ml.nEmissionDim) ], \
                                                                  ml.nEmissionDim, ml.nState,\
                                                                  startIdx=startIdx, \
                                                                  bPosterior=True)
                                                                  for ii in xrange(len(testDataX[0])))
        _, ll_classifier_test_idx, ll_logp_test, ll_post_test = zip(*r)
                                                                     
        ll_classifier_test_X, ll_classifier_test_Y = \
          hmm.getHMMinducedFeatures(ll_logp_test, ll_post_test, testDataY, c=1.0, add_delta_logp=add_logp_d)
        X_test = ll_classifier_test_X
        Y_test = ll_classifier_test_Y

        ## ## # temp
        if viz:
            if method == 'hmmgp':
                ll_logp = [ ll_classifier_train_X[i][0] for i in xrange(len(ll_classifier_train_X))  ]
                ll_post = [ np.array(ll_classifier_train_X)[i,-nState:].tolist() for i in xrange(len(ll_classifier_train_X)) ]
                
            vizLikelihoods2(ll_logp, ll_post, -np.ones(len(normalPtrainData[0])),\
                            ll_logp_test, ll_post_test, testDataY)
            continue

        # -------------------------------------------------------------------------------
        # update kmean
        print "Classifier fitting", method
        dtc = cf.classifier( method=method, nPosteriors=nState, nLength=nLength )
        ret = dtc.fit(X_train_org, Y_train_org, idx_train_org, parallel=True)
        print "Classifier fitting completed"
        

        if method == 'progress':
            cf_dict = {}
            cf_dict['method']      = dtc.method
            cf_dict['nPosteriors'] = dtc.nPosteriors
            cf_dict['l_statePosterior'] = dtc.l_statePosterior
            cf_dict['ths_mult']    = dtc.ths_mult
            cf_dict['ll_mu']       = dtc.ll_mu
            cf_dict['ll_std']      = dtc.ll_std
            cf_dict['logp_offset'] = dtc.logp_offset
        elif method == 'hmmgp':
            cf_dict = {}
            cf_dict['method']      = dtc.method
            cf_dict['nPosteriors'] = dtc.nPosteriors
            cf_dict['ths_mult']    = dtc.ths_mult
            dtc.save_model('./temp_hmmgp.pkl')

        r = Parallel(n_jobs=-1)(delayed(run_classifier)(ii, method, nState, nLength, cf_dict, SVM_dict,\
                                                        ROC_dict, X_test, Y_test)
                                                        for ii in xrange(nPoints))

        print "ROC data update"
        for (j, tp_l, fp_l, fn_l, tn_l, delay_l, tp_idx_l) in r:
            ROC_data_cur[method+'_'+str(i)]['tp_l'][j] += tp_l
            ROC_data_cur[method+'_'+str(i)]['fp_l'][j] += fp_l
            ROC_data_cur[method+'_'+str(i)]['fn_l'][j] += fn_l
            ROC_data_cur[method+'_'+str(i)]['tn_l'][j] += tn_l
            ROC_data_cur[method+'_'+str(i)]['delay_l'][j] += delay_l
            ROC_data_cur[method+'_'+str(i)]['tp_idx_l'][j] += tp_idx_l
            

    return ROC_data_cur

def run_classifier(idx, method, nState, nLength, param_dict, SVM_dict, ROC_dict, \
                   X_test, Y_test, verbose=False):

    dtc = cf.classifier( method=method, nPosteriors=nState, nLength=nLength )
    dtc.set_params( **SVM_dict )
    ll_classifier_test_idx = None
    for k, v in param_dict.iteritems():        
        exec 'dtc.%s = v' % k        
    if method == 'hmmgp':
        dtc.load_model('./temp_hmmgp.pkl')

    if method == 'progress' or method == 'kmean' or method == 'hmmgp':
        thresholds = ROC_dict[method+'_param_range']
        dtc.set_params( ths_mult = thresholds[idx] )
    else:
        print "Not available method = ", method
        sys.exit()

    # evaluate the classifier wrt new never seen data
    tp_l = []
    fp_l = []
    tn_l = []
    fn_l = []
    delay_l = []
    delay_idx = 0
    tp_idx_l = []
    for ii in xrange(len(X_test)):
        if len(Y_test[ii])==0: continue

        if method.find('osvm')>=0 or method == 'cssvm':
            est_y = dtc.predict(X_test[ii], y=np.array(Y_test[ii])*-1.0)
            est_y = np.array(est_y)* -1.0
        else:
            est_y    = dtc.predict(X_test[ii], y=Y_test[ii])

        anomaly = False
        for jj in xrange(len(est_y)):
            if est_y[jj] > 0.0:

                if ll_classifier_test_idx is not None and Y_test[ii][0]>0:
                    try:
                        delay_idx = ll_classifier_test_idx[ii][jj]
                    except:
                        print "Error!!!!!!!!!!!!!!!!!!"
                        print np.shape(ll_classifier_test_idx), ii, jj
                    delay_l.append(delay_idx)
                if Y_test[ii][0] > 0:
                    tp_idx_l.append(ii)

                anomaly = True
                break        

        if Y_test[ii][0] > 0.0:
            if anomaly: tp_l.append(1)
            else: fn_l.append(1)
        elif Y_test[ii][0] <= 0.0:
            if anomaly: fp_l.append(1)
            else: tn_l.append(1)

    return idx, tp_l, fp_l, fn_l, tn_l, delay_l, tp_idx_l


## def applying_offset(data, normalTrainData, startOffsetSize, nEmissionDim):

##     # get offset
##     refData = np.reshape( np.mean(normalTrainData[:,:,:startOffsetSize], axis=(1,2)), \
##                           (nEmissionDim,1,1) ) # 4,1,1

##     curData = np.reshape( np.mean(data[:,:,:startOffsetSize], axis=(1,2)), \
##                           (nEmissionDim,1,1) ) # 4,1,1
##     offsetData = refData - curData

##     for i in xrange(nEmissionDim):
##         data[i] = (np.array(data[i]) + offsetData[i][0][0]).tolist()

##     return data


def data_selection(subject_names, task_name, raw_data_path, processed_data_path, \
                  downSampleSize=200, \
                  local_range=0.3, rf_center='kinEEPos', \
                  success_viz=True, failure_viz=False, \
                  raw_viz=False, save_pdf=False, \
                  modality_list=['audio'], data_renew=False, \
                  max_time=None, verbose=False):
    '''
    '''
    dv.data_plot(subject_names, task_name, raw_data_path, processed_data_path,\
                 downSampleSize=downSampleSize, \
                 local_range=local_range, rf_center=rf_center, \
                 raw_viz=True, interp_viz=False, save_pdf=save_pdf,\
                 successData=success_viz, failureData=failure_viz,\
                 continuousPlot=True, \
                 modality_list=modality_list, data_renew=data_renew, \
                 max_time=max_time, verbose=verbose)

def vizLikelihoods(ll_logp, ll_post, l_y):

    fig = plt.figure(1)

    print "viz likelihood ", np.shape(ll_logp), np.shape(ll_post)

    for i in xrange(len(ll_logp)):

        l_logp  = ll_logp[i]
        l_state = np.argmax(ll_post[i], axis=1)

        ## plt.plot(l_state, l_logp, 'b-')
        if l_y[i] < 0:
            plt.plot(l_logp, 'b-')
        else:
            plt.plot(l_logp, 'r-')

    plt.ylim([0, np.amax(ll_logp) ])
    plt.show()

def vizLikelihoods2(ll_logp, ll_post, l_y, ll_logp2, ll_post2, l_y2):

    fig = plt.figure(1)

    print "viz likelihoood2 :", np.shape(ll_logp), np.shape(ll_post)

    for i in xrange(len(ll_logp)):

        l_logp  = ll_logp[i]
        l_state = np.argmax(ll_post[i], axis=1)

        ## plt.plot(l_state, l_logp, 'b-')
        if l_y[i] < 0:
            plt.plot(l_logp, 'b-', linewidth=3.0, alpha=0.7)
        ## else:
        ##     plt.plot(l_logp, 'r-')

    for i in xrange(len(ll_logp2)):

        l_logp  = ll_logp2[i]
        l_state = np.argmax(ll_post2[i], axis=1)

        ## plt.plot(l_state, l_logp, 'b-')
        if l_y2[i] < 0:
            plt.plot(l_logp, 'k-')
        else:
            plt.plot(l_logp, 'm-')


    if np.amax(ll_logp) > 0:
        plt.ylim([0, np.amax(ll_logp) ])
    plt.show()



if __name__ == '__main__':

    import optparse
    p = optparse.OptionParser()
    p.add_option('--dataRenew', '--dr', action='store_true', dest='bDataRenew',
                 default=False, help='Renew pickle files.')
    p.add_option('--AERenew', '--ar', action='store_true', dest='bAERenew',
                 default=False, help='Renew AE data.')
    p.add_option('--hmmRenew', '--hr', action='store_true', dest='bHMMRenew',
                 default=False, help='Renew HMM parameters.')
    p.add_option('--cfRenew', '--cr', action='store_true', dest='bCLFRenew',
                 default=False, help='Renew Classifiers.')

    p.add_option('--task', action='store', dest='task', type='string', default='feeding',
                 help='type the desired task name')
    p.add_option('--dim', action='store', dest='dim', type=int, default=4,
                 help='type the desired dimension')
    p.add_option('--aeswtch', '--aesw', action='store_true', dest='bAESwitch',
                 default=False, help='Enable AE data.')

    p.add_option('--rawplot', '--rp', action='store_true', dest='bRawDataPlot',
                 default=False, help='Plot raw data.')
    p.add_option('--interplot', '--ip', action='store_true', dest='bInterpDataPlot',
                 default=False, help='Plot raw data.')
    p.add_option('--feature', '--ft', action='store_true', dest='bFeaturePlot',
                 default=False, help='Plot features.')
    p.add_option('--likelihoodplot', '--lp', action='store_true', dest='bLikelihoodPlot',
                 default=False, help='Plot the change of likelihood.')
    p.add_option('--viz', action='store_true', dest='bViz',
                 default=False, help='temp.')
    p.add_option('--dataselect', '--ds', action='store_true', dest='bDataSelection',
                 default=False, help='Plot data and select it.')
    
    p.add_option('--evaluation_all', '--ea', action='store_true', dest='bEvaluationAll',
                 default=False, help='Evaluate a classifier with cross-validation.')
    p.add_option('--evaluation_unexp', '--eu', action='store_true', dest='bEvaluationUnexpected',
                 default=False, help='Evaluate a classifier with cross-validation.')
    p.add_option('--evaluation_online', '--eo', action='store_true', dest='bOnlineEval',
                 default=False, help='Evaluate a classifier with cross-validation with onlineHMM.')
    p.add_option('--evaluation_online_temp', '--eot', action='store_true', dest='bOnlineEvalTemp',
                 default=False, help='Evaluate a classifier with cross-validation with onlineHMM.')
    p.add_option('--evaluation_acc', '--eaa', action='store_true', dest='bEvaluationMaxAcc',
                 default=False, help='Evaluate the max acc.')

    
    p.add_option('--data_generation', action='store_true', dest='bDataGen',
                 default=False, help='Data generation before evaluation.')
    p.add_option('--find_param', action='store_true', dest='bFindParam',
                 default=False, help='Find hmm parameter.')
    p.add_option('--eval_aws', '--aws', action='store_true', dest='bEvaluationAWS',
                 default=False, help='Data generation before evaluation.')
    p.add_option('--cparam', action='store_true', dest='bCustomParam',
                 default=False, help='')
                 

    p.add_option('--m2o', action='store_true', dest='bManyToOneAdaptation',
                 default=False, help='Many-To-One adaptation flag')
    p.add_option('--no_partial_fit', '--npf', action='store_true', dest='bNoPartialFit',
                 default=False, help='HMM partial fit')

    p.add_option('--auro', action='store_true', dest='bAURO',
                 default=False, help='Enable AURO.')
    
    p.add_option('--debug', '--dg', action='store_true', dest='bDebug',
                 default=False, help='Set debug mode.')
    p.add_option('--renew', action='store_true', dest='bRenew',
                 default=False, help='Renew pickle files.')
    p.add_option('--savepdf', '--sp', action='store_true', dest='bSavePdf',
                 default=False, help='Save pdf files.')    
    p.add_option('--noplot', '--np', action='store_true', dest='bNoPlot',
                 default=False, help='No Plot.')    
    p.add_option('--noupdate', '--nu', action='store_true', dest='bNoUpdate',
                 default=False, help='No update.')    
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

    raw_data_path, save_data_path, param_dict = getParams(opt.task, opt.bDataRenew, \
                                                          opt.bAERenew, opt.bHMMRenew, opt.dim,\
                                                          rf_center, local_range, \
                                                          bAESwitch=opt.bAESwitch)


    if opt.bAURO:
        subjects = ['hwang']
        save_data_path = os.path.expanduser('~')+\
          '/hrl_file_server/dpark_data/anomaly/ICRA2017/'+opt.task+'_data_auro/'+\
          str(param_dict['data_param']['downSampleSize'])+'_'+str(opt.dim)

    else:
        #---------------------------------------------------------------------------
        if opt.task == 'scooping':
            subjects = ['park', 'test'] #'Henry', 
        #---------------------------------------------------------------------------
        elif opt.task == 'feeding':
            subjects = ['park', 'sai'] #'jina', , 'linda']        #'ari', 
            ## subjects = [ 'zack', 'hkim', 'ari', 'park', 'jina', 'linda']
        elif opt.task == 'pushing':
            subjects = ['microblack', 'microwhite']        
        else:
            print "Selected task name is not available."
            sys.exit()

                                                          
    if opt.bCLFRenew: param_dict['SVM']['renew'] = True
    
    #---------------------------------------------------------------------------           
    if opt.bRawDataPlot or opt.bInterpDataPlot:
        '''
        Before localization: Raw data plot
        After localization: Raw or interpolated data plot
        '''
        successData = True
        failureData = True
        modality_list   = ['kinematics', 'audio', 'ft', 'vision_artag'] # raw plot

        dv.data_plot(subjects, opt.task, raw_data_path, save_data_path,\
                  downSampleSize=param_dict['data_param']['downSampleSize'], \
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
        modality_list   = ['kinematics', 'ft']
        success_viz = True
        failure_viz = True

        data_selection(subjects, opt.task, raw_data_path, save_data_path,\
                       downSampleSize=param_dict['data_param']['downSampleSize'], \
                       local_range=local_range, rf_center=rf_center, \
                       success_viz=success_viz, failure_viz=failure_viz,\
                       raw_viz=opt.bRawDataPlot, save_pdf=opt.bSavePdf,\
                       modality_list=modality_list, data_renew=opt.bDataRenew, \
                       max_time=param_dict['data_param']['max_time'], verbose=opt.bVerbose)        

    elif opt.bFeaturePlot:
        success_viz = True
        failure_viz = False
        
        ## save_data_path = os.path.expanduser('~')+\
        ##   '/hrl_file_server/dpark_data/anomaly/ICRA2017/'+opt.task+'_data_online/'+\
        ##   str(param_dict['data_param']['downSampleSize'])+'_'+str(opt.dim)
        dm.getDataLOPO(subjects, opt.task, raw_data_path, save_data_path,
                       param_dict['data_param']['rf_center'], param_dict['data_param']['local_range'],\
                       downSampleSize=param_dict['data_param']['downSampleSize'], scale=scale, \
                       success_viz=success_viz, failure_viz=failure_viz,\
                       cut_data=param_dict['data_param']['cut_data'],\
                       save_pdf=opt.bSavePdf, solid_color=True,\
                       handFeatures=param_dict['data_param']['handFeatures'], data_renew=opt.bDataRenew, \
                       max_time=param_dict['data_param']['max_time'])

    elif opt.bLikelihoodPlot and opt.bOnlineEval is not True:
        import hrl_anomaly_detection.data_viz as dv        
        dv.vizLikelihoods(subjects, opt.task, raw_data_path, save_data_path, param_dict,\
                          decision_boundary_viz=False, \
                          useTrain=True, useNormalTest=False, useAbnormalTest=False,\
                          useTrain_color=False, useNormalTest_color=False, useAbnormalTest_color=False,\
                          hmm_renew=opt.bHMMRenew, data_renew=opt.bDataRenew, save_pdf=opt.bSavePdf,\
                          verbose=opt.bVerbose)
                              
    elif opt.bEvaluationAll or opt.bDataGen:
        if opt.bHMMRenew: param_dict['ROC']['methods'] = ['fixed'] 
        if opt.bNoUpdate: param_dict['ROC']['update_list'] = []
                    
        evaluation_all(subjects, opt.task, raw_data_path, save_data_path, param_dict, save_pdf=opt.bSavePdf, \
                       verbose=opt.bVerbose, debug=opt.bDebug, no_plot=opt.bNoPlot, \
                       find_param=False, data_gen=opt.bDataGen)

    elif opt.bEvaluationUnexpected:
        unexp_subjects = ['unexpected1', 'unexpected2', 'unexpected3']
        save_data_path = os.path.expanduser('~')+\
          '/hrl_file_server/dpark_data/anomaly/ICRA2017/'+opt.task+'_data_unexp/'+\
          str(param_dict['data_param']['downSampleSize'])+'_'+str(opt.dim)
        param_dict['ROC']['methods'] = ['fixed', 'progress', 'svm', 'change', 'hmmgp']
        if opt.bNoUpdate: param_dict['ROC']['update_list'] = []
        param_dict['ROC']['update_list'] = ['fixed']

        nPoints = param_dict['ROC']['nPoints']
        param_dict['ROC']['progress_param_range'] = -np.logspace(-1, 1.0, nPoints)
        param_dict['ROC']['fixed_param_range'] = np.linspace(0.3, -0.1, nPoints)
        param_dict['ROC']['change_param_range'] = np.logspace(0, 1.8, nPoints)*-1.0
        param_dict['ROC']['hmmgp_param_range'] = np.logspace(-2, 1.8, nPoints)*-1.0

        evaluation_unexp(subjects, unexp_subjects, opt.task, raw_data_path, save_data_path, \
                         param_dict, save_pdf=opt.bSavePdf, \
                         verbose=opt.bVerbose, debug=opt.bDebug, no_plot=opt.bNoPlot, \
                         find_param=False, data_gen=opt.bDataGen)

    elif opt.bOnlineEval:
        param_dict['ROC']['methods'] = ['hmmgp']
        param_dict['ROC']['nPoints'] = 16

        many_to_one = False

        if opt.bEvaluationAWS or opt.bFindParam:
            n_random_trial = 1 #10
            opt.bNoPlot    = True
        else:
            n_random_trial = 1
                             
        save_data_path = os.path.expanduser('~')+\
          '/hrl_file_server/dpark_data/anomaly/ICRA2017/'+opt.task+'_data_online/'+\
          str(param_dict['data_param']['downSampleSize'])+'_'+str(opt.dim)

        if opt.bLikelihoodPlot:
            if param_dict['ROC']['methods'][0] == 'hmmgp': nSubSample = 20
            param_dict['HMM'] = {'renew': opt.bHMMRenew, 'nState': 25, 'cov': 5., 'scale': 8.0,\
                                 'add_logp_d': False}
                                     
            crossVal_pkl = os.path.join(save_data_path, 'cv_'+opt.task+'.pkl')
            d = ut.load_pickle(crossVal_pkl)

            import hrl_anomaly_detection.data_viz as dv        
            dv.vizLikelihoods(subjects, opt.task, raw_data_path, save_data_path, param_dict,\
                              decision_boundary_viz=False, \
                              useTrain=True, useNormalTest=True, useAbnormalTest=True,\
                              useTrain_color=False, useNormalTest_color=False, useAbnormalTest_color=False,\
                              hmm_renew=opt.bHMMRenew, data_renew=opt.bDataRenew, save_pdf=opt.bSavePdf,\
                              verbose=opt.bVerbose, dd=d, nSubSample=nSubSample)
        elif opt.bFindParam:
            evaluation_online_multi(subjects, opt.task, raw_data_path, save_data_path, \
                                    param_dict, n_random_trial=n_random_trial, random_eval=True,\
                                    many_to_one=opt.bManyToOneAdaptation, data_renew=opt.bDataRenew,\
                                    verbose=opt.bVerbose, debug=opt.bDebug)
        else:          
            evaluation_online(subjects, opt.task, raw_data_path, save_data_path, \
                              param_dict, save_pdf=opt.bSavePdf, many_to_one=opt.bManyToOneAdaptation, \
                              verbose=opt.bVerbose, debug=opt.bDebug, no_plot=opt.bNoPlot, \
                              find_param=False, data_gen=opt.bDataGen, n_random_trial=n_random_trial,\
                              random_eval=opt.bEvaluationAWS, custom_mode=opt.bCustomParam, \
                              data_renew=opt.bDataRenew, viz=opt.bViz, hmm_update=not(opt.bNoPartialFit))

    elif opt.bEvaluationMaxAcc:
        param_dict['ROC']['methods'] = ['fixed'] 
        if opt.bNoUpdate: param_dict['ROC']['update_list'] = []
        save_data_path = os.path.expanduser('~')+\
          '/hrl_file_server/dpark_data/anomaly/ICRA2017/'+opt.task+'_data_auro/'+\
          str(param_dict['data_param']['downSampleSize'])+'_'+str(opt.dim)

        subjects = ['park', 'jina', 'sai', 'linda']
        ## evaluation_all(subjects, opt.task, raw_data_path, save_data_path, param_dict, save_pdf=opt.bSavePdf, \
        ##                verbose=opt.bVerbose, debug=opt.bDebug, no_plot=True)

        unexp_subjects = ['hwang']
        ## evaluation_unexp(subjects, unexp_subjects, opt.task, raw_data_path, save_data_path, \
        ##                  param_dict, save_pdf=opt.bSavePdf, \
        ##                  verbose=opt.bVerbose, debug=opt.bDebug, no_plot=opt.bNoPlot, \
        ##                  find_param=False, data_gen=opt.bDataGen)
                       
        unexp_subjects = ['hwang']
        evaluation_acc(unexp_subjects, opt.task, raw_data_path, save_data_path, param_dict, \
                       save_pdf=opt.bSavePdf, verbose=opt.bVerbose, debug=opt.bDebug, \
                       no_plot=opt.bNoPlot)
