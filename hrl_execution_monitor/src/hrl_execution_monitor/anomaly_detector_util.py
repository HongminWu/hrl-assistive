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

#  \author Daehyung Park (Healthcare Robotics Lab, Georgia Tech.)

# system & utils
import os, sys, copy, random
import scipy, numpy as np
import hrl_lib.util as ut

random.seed(3334)
np.random.seed(3334)

# Private utils
from hrl_anomaly_detection import util as util
## from hrl_anomaly_detection.util_viz import *
from hrl_anomaly_detection import data_manager as dm
from hrl_execution_monitor import util as autil

# Private learners
from hrl_anomaly_detection.hmm import learning_hmm as hmm
import hrl_anomaly_detection.classifiers.classifier as cf

from joblib import Parallel, delayed



def train_detector_modules(subject_names, task_name, raw_data_path, save_data_path, method,
                            param_dict, verbose=False):

    # load params (param_dict)
    data_dict  = param_dict['data_param']
    data_renew = data_dict['renew']
    ## nNormalFold   = data_dict['nNormalFold']
    ## nAbnormalFold = data_dict['nAbnormalFold']
    
    # HMM
    HMM_dict   = param_dict['HMM']
    nState     = HMM_dict['nState']
    cov        = HMM_dict['cov']
    # SVM
    SVM_dict   = param_dict['SVM']
    # ROC
    ROC_dict = param_dict['ROC']

    # parameters
    startIdx    = 4
    nPoints     = ROC_dict['nPoints']
    

    # load data (mix) -------------------------------------------------
    d = dm.getDataSet(subject_names, task_name, raw_data_path, \
                      save_data_path,\
                      downSampleSize=data_dict['downSampleSize'],\
                      handFeatures=data_dict['isolationFeatures'], \
                      data_renew=data_renew, max_time=data_dict['max_time'],\
                      ros_bag_image=True, rndFold=True)
                      
    # split data with 80:20 ratio, 3set
    kFold_list = d['kFold_list']
    
    # select feature for detection
    feature_list = []
    for feature in data_dict['handFeatures']:
        idx = [ i for i, x in enumerate(data_dict['isolationFeatures']) if feature == x][0]
        feature_list.append(idx)
    
    successData = d['successData'][feature_list]
    failureData = d['failureData'][feature_list]


    # Train a generative model ----------------------------------------
    # Training HMM, and getting classifier training and testing data
    dm.saveHMMinducedFeatures(kFold_list, successData, failureData,\
                              task_name, save_data_path,\
                              HMM_dict, data_renew, startIdx, nState, cov, \
                              success_files=d['successFiles'], failure_files=d['failureFiles'],\
                              noise_mag=0.03, cov_type='full', verbose=verbose)

    # Train a classifier ----------------------------------------------
    roc_pkl = os.path.join(save_data_path, 'roc_'+task_name+'.pkl')

    if os.path.isfile(roc_pkl) is False or HMM_dict['renew'] or SVM_dict['renew']: ROC_data = {}
    else: ROC_data = ut.load_pickle(roc_pkl)
    ROC_data = util.reset_roc_data(ROC_data, [method], ROC_dict['update_list'], nPoints)

    l_data = Parallel(n_jobs=-1, verbose=10)(delayed(cf.run_classifiers)( idx, save_data_path, \
                                                                          task_name, method, \
                                                                          ROC_data, ROC_dict, \
                                                                          SVM_dict, HMM_dict, \
                                                                          startIdx=startIdx, nState=nState,\
                                                                          save_model=True) \
                                                                          for idx in xrange(len(kFold_list)))
    
    ROC_data = util.update_roc_data(ROC_data, l_data, nPoints, [method])
    ut.save_pickle(ROC_data, roc_pkl)
    
    # ROC Visualization ------------------------------------------------
    util.roc_info([method], ROC_data, nPoints, no_plot=True)

    # TODO: 
    # need to print the best weight out
    # need to save acc list

    return 


## def test_detector_modules(save_data_path, task_name):
##     return
    

def get_detector_modules(save_data_path, task_name, method, param_dict, fold_idx=0, \
                          verbose=False):

    # load param
    scr_pkl = os.path.join(save_data_path, 'scr_'+method+'_'+str(fold_idx)+'.pkl')
    hmm_pkl = os.path.join(save_data_path, 'hmm_'+task_name+'_'+str(fold_idx)+'.pkl')
    clf_pkl = os.path.join(save_data_path, 'clf_'+method+'_'+\
                           str(fold_idx)+'.pkl')

    # load scaler
    import pickle
    if os.path.isfile(scr_pkl):
        with open(scr_pkl, 'rb') as f:
            m_scr = pickle.load(f)
    else: m_scr = None

    # load hmm
    if os.path.isfile(hmm_pkl) is False:
        print "No HMM pickle file: ", hmm_pkl
        sys.exit()
        
    d     = ut.load_pickle(hmm_pkl)
    print d.keys()
    m_gen = hmm.learning_hmm(d['nState'], d['nEmissionDim'], verbose=verbose)
    m_gen.set_hmm_object(d['A'], d['B'], d['pi'])


    # load classifier
    m_clf = cf.classifier( method=method, nPosteriors=d['nState'], parallel=True )
    m_clf.load_model(clf_pkl)

    return m_scr, m_gen, m_clf




if __name__ == '__main__':

    import optparse
    p = optparse.OptionParser()
    util.initialiseOptParser(p)
    opt, args = p.parse_args()

    from hrl_execution_monitor.params.IROS2017_params import *
    # IROS2017
    subject_names = ['s2', 's3','s4','s5', 's6','s7','s8', 's9']
    raw_data_path, save_data_path, param_dict = getParams(opt.task, opt.bDataRenew, \
                                                          opt.bHMMRenew, opt.bCLFRenew)
    save_data_path = '/home/dpark/hrl_file_server/dpark_data/anomaly/IROS2017/'+opt.task+'_demo'

    task_name = 'feeding'
    method    = 'hmmgp'

    train_detector_modules(subject_names, task_name, raw_data_path, save_data_path, method,\
                            param_dict, verbose=False)


    get_detector_modules(save_data_path, task_name, method, param_dict, fold_idx=0,\
                          verbose=False)