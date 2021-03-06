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
import os, sys, copy
import numpy as np
## import random
from six.moves import cPickle

from hrl_anomaly_detection.hmm.learning_base import learning_base

#theano
import theano
import theano.tensor as T
from theano import function, config, shared, sandbox

# util
import layer as l
import theano_util as util
import hrl_lib.util as ut


class auto_encoder(learning_base):
    def __init__(self, layer_sizes, learning_rate, learning_rate_decay, momentum, dampening, \
                 lambda_reg, time_window, max_iteration=100000, min_loss=0.1, \
                 cuda=True, verbose=False):
        learning_base.__init__(self)
        '''
        '''

        self.layer_sizes = layer_sizes
        self.learning_rate = learning_rate
        self.learning_rate_decay = learning_rate_decay
        self.momentum = momentum
        self.dampening = dampening
        self.lambda_reg = lambda_reg
        ## self.batch_size
        self.time_window = time_window

        # stop parameters
        self.max_iteration = max_iteration
        self.min_loss      = min_loss

        self.cuda    = cuda
        self.verbose = verbose

        self.nFeatures = layer_sizes[-1]
        self.mlp = None

    def convert_vars(self):
        self.learning_rate       = np.float32(self.learning_rate)
        self.learning_rate_decay = np.float32(self.learning_rate_decay)
        self.momentum            = np.float32(self.momentum)
        self.dampening           = np.float32(self.dampening)
        self.lambda_reg          = np.float32(self.lambda_reg)
        

    def create_layers(self, load=False, filename=None):

        self.convert_vars()

        # Set initial parameter values
        W_init_en = []
        b_init_en = []
        activations_en = []
        W_init_de = []
        b_init_de = []
        activations_de = []

        # Encoder layers
        for n_input, n_output in zip(self.layer_sizes[:-1], self.layer_sizes[1:]):
            W_init_en.append(np.random.randn(n_output, n_input).astype('float32'))
            b_init_en.append(np.ones(n_output).astype('float32'))

            ## # We'll use sigmoid activation for all layers
            ## # Note that this doesn't make a ton of sense when using squared distance
            ## # because the sigmoid function is bounded on [0, 1].
            activations_en.append( T.nnet.sigmoid ) #T.tanh ) 


        # Decoder layers
        layer_sizes_rev = list(reversed(self.layer_sizes))
        for n_input, n_output in zip(layer_sizes_rev[:-1], layer_sizes_rev[1:]):
            W_init_de.append(np.random.randn(n_output, n_input).astype('float32'))
            b_init_de.append(np.ones(n_output).astype('float32'))
            activations_de.append( T.nnet.sigmoid )  #T.tanh)

        ## activations_de[-1] = None

        # Create an instance of the MLP class
        self.mlp = l.AD(W_init_en, b_init_en, activations_en,
                   W_init_de, b_init_de, activations_de, nEncoderLayers=len(self.layer_sizes)-1)
        
        if load: self.load_params(filename)


        # Create Theano variables for the MLP input
        mlp_input = T.fmatrix('mlp_input')
        mlp_target = T.fmatrix('mlp_target')
        cost = self.mlp.squared_error(mlp_input, mlp_target)
        ## cost = mlp.L1_error(mlp_input, mlp_target)

        if self.verbose: print 'Creating a theano function for training the network'
        self.train = theano.function([mlp_input, mlp_target], cost,
                                     updates=l.gradient_updates_momentum(cost, self.mlp.params, \
                                                                         self.learning_rate, \
                                                                         self.learning_rate_decay, \
                                                                         self.momentum, \
                                                                         self.dampening, \
                                                                         self.lambda_reg))

        if self.verbose: print 'Creating a theano function for computing the MLP\'s output given some input'
        self.mlp_output = theano.function([mlp_input], self.mlp.output(mlp_input))
        if self.verbose: print 'Creating a theano function for computing the MLP\'s output given some input'
        self.mlp_features = theano.function([mlp_input], self.mlp.get_features(mlp_input))

        self.mlp_cost = theano.function([mlp_input, mlp_target], cost)
        

    def fit(self, X, save_obs={'save': False, 'load': False, 'filename': 'simple_model'}):
        '''
        X: samples x dims
        '''

        X = X.T

        # create mlp layers
        self.create_layers(save_obs['load'], save_obs['filename'])

        if self.verbose: print 'Optimising'
        # Keep track of the number of training iterations performed
        iteration = 0

        batch_size       = X.shape[1]
        train_loss       = np.float32(10000000.0)

        while iteration < self.max_iteration and train_loss > self.min_loss:

            # training with SGD
            train_loss   = np.float32(0.0)
            count = 0.0
            for i in range(0, X.shape[1]-batch_size+1, batch_size):
                count += 1.0
                if self.cuda:
                    train_loss += self.train(X.astype('float32'), X.astype('float32') )
                else:
                    train_loss += self.train(X[:,i:i+batch_size].astype('float32'), \
                                             X[:,i:i+batch_size].astype('float32'))

            train_loss /= np.float32((count*batch_size))
            train_loss /= np.float32(self.time_window)
            if np.isnan(train_loss) or np.isinf(train_loss):
                if self.verbose: print "Train loss is NaN with iter ", iteration
                sys.exit()
            if self.verbose and iteration%20==0: print "iter ", iteration,"/", self.max_iteration, \
              " loss: ", train_loss
            if iteration>0 and iteration%1000==0 and save_obs['save']: self.save_params(save_obs['filename'])

            iteration += 1

        if save_obs['save']: self.save_params(save_obs['filename'])
        return train_loss


    def predict(self, X):
        '''
        X: samples x dims
        '''
        return self.mlp_output(X.T.astype('float32'))


    def predict_features(self, X):
        '''
        X: samples x dims
        '''
        return self.mlp_features(X.T.astype('float32'))


    def score(self, X):
        '''
        X: samples x dims
        '''
        test_batch_data = X.T.astype('float32')
        test_loss = self.mlp_cost(test_batch_data, test_batch_data)/np.float32(len(X[0]))
        test_loss /= np.float32(self.time_window)
        if np.isnan(test_loss) or np.isinf(test_loss):
            if self.verbose: print "Test loss is NaN"
            sys.exit()

        return test_loss


    def save_params(self, filename):
        print "Save model"
        d = {}
        d['params']       = self.mlp.get_params()
        ## d['mlp_features'] = self.mlp_features
        ## d['train']        = self.train
        ## d['mlp_output']   = self.mlp_output
        ## d['mlp_cost']     = self.mlp_cost
        ut.save_pickle(d, filename)        
        ## f = file(filename, 'wb')
        ## cPickle.dump(self.mlp_features, f, protocol=cPickle.HIGHEST_PROTOCOL)
        ## f.close()
        return


    def load_params(self, filename):
        if os.path.isfile(filename) is not True:
            print "Not existing file!!!!"
            return False

        print "load model"
        d = ut.load_pickle(filename)
        self.mlp.set_params(d['params'])
        ## self.mlp_features = d['mlp_features']
        ## self.train        = d['train']
        ## self.mlp_output   = d['mlp_output']
        ## self.mlp_cost     = d['mlp_cost']
        ## f = open(filename, 'rb')
        ## self.mlp_features = cPickle.load(f)
        ## f.close()
        return


    def viz_features(self, X1, X2, nSingleData, filtered=False, abnormal_disp=False):
        '''
        sample x dim
        '''
        ## Normal training data ----------------------------------
        # sample x dim x length 
        feature_list1 = []
        for idx in xrange(0, len(X1), nSingleData):
            features = self.predict_features( X1[idx:idx+nSingleData,:] )
            feature_list1.append(features)

        assert self.nFeatures==len(feature_list1[0])

        # => dim x samples x length
        feature_list1 = np.swapaxes(feature_list1, 0, 1)

        ## Abnormal training data --------------------------------
        # sample x dim x length
        feature_list2 = []
        for idx in xrange(0, len(X2), nSingleData):
            features = self.predict_features( X2[idx:idx+nSingleData,:] )
            feature_list2.append(features)

        assert self.nFeatures==len(feature_list2[0])

        # => dim x samples x length
        feature_list2 = np.swapaxes(feature_list2, 0, 1)


        if filtered:
            from hrl_anomaly_detection import data_manager as dm
            pooling_param_dict  = {'min_all_std': 0.2, 'max_avg_std': 0.2, 'dim': 4} # only for AE
            feature_list1, pooling_param_dict = dm.variancePooling(feature_list1, pooling_param_dict)
            feature_list2, _                  = dm.variancePooling(feature_list2, pooling_param_dict)
            

        from hrl_anomaly_detection import data_viz as dv
        if abnormal_disp: dv.viz(feature_list1, feature_list2)
        else: dv.viz(feature_list1)
        


        return 


if __name__ == '__main__':

    import optparse
    p = optparse.OptionParser()
    p.add_option('--pretrain', '--ptr', action='store_true', dest='bPreTrain',
                 default=False, help='Pre-Train ....')
    p.add_option('--train', '--tr', action='store_true', dest='bTrain',
                 default=False, help='Train ....')
    p.add_option('--test', '--te', action='store_true', dest='bTest',
                 default=False, help='Test ....')
    p.add_option('--param_est', '--pe', action='store_true', dest='bParamEstimation',
                 default=False, help='Parameter Estimation')
    
    p.add_option('--viz', action='store_true', dest='bViz',
                 default=False, help='Visualize ....')
    p.add_option('--viz_raw', '--vr', action='store_true', dest='bVizRaw',
                 default=False, help='Visualize Raw data')
    p.add_option('--rviz', action='store_true', dest='bReconstructViz',
                 default=False, help='Visualize reconstructed signal')
    p.add_option('--save', action='store_true', dest='bSave',
                 default=False, help='Save a model ....')
    p.add_option('--load', action='store_true', dest='bLoadModel',
                 default=False, help='Load a model ....')
    p.add_option('--save_pdf', '--sp', action='store_true', dest='bSavePDF',
                 default=False, help='Save the visualized result as a pdf')
    p.add_option('--data_renew', action='store_true', dest='bDataRenew',
                 default=False, help='Renew data ....')
    p.add_option('--verbose', '--v', action='store_true', dest='bVerbose',
                 default=False, help='Print msg ....')
    p.add_option('--cuda', '--c', action='store_true', dest='bCuda',
                 default=True, help='Enable CUDA')
    
    p.add_option('--time_window', '--tw', action='store', dest='nTimeWindow',
                 type="int", default=4, help='Size of time window')
    p.add_option('--learning_rate', '--lr', action='store', dest='fLearningRate',
                 type="float", default=1e-5, help='Learning rate weight')
    p.add_option('--learning_rate_decay', '--lrd', action='store', dest='fLearningRateDecay',
                 type="float", default=1e-5, help='Learning rate weight decay')
    p.add_option('--momentum', '--m', action='store', dest='fMomentum',
                 type="float", default=1e-6, help='momentum')
    p.add_option('--dampening', '--d', action='store', dest='fDampening',
                 type="float", default=1e-6, help='dampening for momentum')
    p.add_option('--lambda', '--lb', action='store', dest='fLambda',
                 type="float", default=1e-6, help='Lambda for regularization ')
    ## p.add_option('--batch_size', '--bs', action='store', dest='nBatchSize',
    ##              type="int", default=1024, help='Size of batches ....')
    p.add_option('--layer_size', '--ls', action='store', dest='lLayerSize',
                 ## default="[3]", help='Size of layers ....')
                 default="[128,64,16]", help='Size of layers ....')
    p.add_option('--maxiter', '--mi', action='store', dest='nMaxIter',
                 type="int", default=30000, help='Set Max iteration ....')
    p.add_option('--minloss', '--ml', action='store', dest='fMinLoss',
                 type="int", default=0.5, help='Set Min Loss')
    
    opt, args = p.parse_args()

    '''
    parameters
    '''
    time_window   = opt.nTimeWindow
    learning_rate = opt.fLearningRate
    learning_rate_decay = opt.fLearningRateDecay
    momentum      = opt.fMomentum
    dampening     = opt.fDampening
    lambda_reg    = opt.fLambda
    ## batch_size    = opt.nBatchSize
    maxiteration  = opt.nMaxIter
    min_loss      = opt.fMinLoss

    
    subject_names       = ['gatsbii']
    task_name           = 'pushing_microwhite'
    rf_center           = 'kinEEPos'
    local_range         = 10.0 
    raw_data_path       = os.path.expanduser('~')+'/hrl_file_server/dpark_data/anomaly/RSS2016/'   


    if task_name == 'pushing_microwhite':
        from hrl_anomaly_detection.params import *
        _, _, param_dict = getPushingMicroWhite(task_name, opt.bDataRenew, False, False, \
                                                rf_center, local_range, pre_train=opt.bPreTrain )
    else:
        print "not available task"
        sys.exit()


    if opt.bPreTrain:
        processed_data_path = '/home/dpark/hrl_file_server/dpark_data/anomaly/RSS2016/'+task_name+'_data'        
        save_pkl       = os.path.join(processed_data_path, task_name+'_pretrain_data')
        d = ut.load_pickle(save_pkl)
        X_train = d['allDataConv']
        layer_sizes = [X_train.shape[1]] + eval(opt.lLayerSize) #, 20, 10, 5]        
    else:       
        processed_data_path = os.path.expanduser('~')+'/hrl_file_server/dpark_data/anomaly/RSS2016/'+\
          task_name+'_data/AE_test'
        save_pkl            = os.path.join(processed_data_path, 'ae_data.pkl')
        save_model_pkl      = os.path.join(processed_data_path, 'ae_model.pkl')
        downSampleSize      = 100
        nAugment            = 1
        cut_data            = [0,100]
        handFeatures = ['unimodal_ftForce',\
                        'crossmodal_targetEEDist',\
                        'crossmodal_targetEEAng',\
                        'unimodal_audioWristRMS'] #'unimodal_audioPower', ,
        rawFeatures = ['relativePose_artag_EE', \
                       'relativePose_artag_artag', \
                       'wristAudio', \
                       'ft' ]       

        from hrl_anomaly_detection import data_manager as dm
        X_normalTrain, X_abnormalTrain, X_normalTest, X_abnormalTest, nSingleData \
          = dm.get_time_window_data(subject_names, task_name, raw_data_path, processed_data_path, \
                                    save_pkl, \
                                    rf_center, local_range, downSampleSize, time_window, \
                                    handFeatures, rawFeatures, \
                                    cut_data, nAugment=nAugment, renew=opt.bDataRenew)
        layer_sizes = [X_normalTrain.shape[1]] + eval(opt.lLayerSize) #, 20, 10, 5]
        print layer_sizes

        # sample x dim 
        X_train = np.vstack([X_normalTrain, X_abnormalTrain])
        X_test  = np.vstack([X_normalTest, X_abnormalTest])
        print np.shape(X_train), np.shape(X_test)
        
        

    if os.path.isdir(processed_data_path) is False:
        os.system('mkdir -p '+processed_data_path)

    #----------------------------------------------------------------------------------------------------
    if opt.bTrain:
        
        clf = auto_encoder(layer_sizes, learning_rate, learning_rate_decay, momentum, dampening, \
                           lambda_reg, time_window, \
                           max_iteration=maxiteration, min_loss=min_loss, cuda=opt.bCuda, verbose=opt.bVerbose)

        save_obs={'save': opt.bSave, 'load': opt.bLoadModel, 'filename': save_model_pkl}
        clf.fit(X_train, save_obs)

    elif opt.bViz:

        clf = auto_encoder(layer_sizes, learning_rate, learning_rate_decay, momentum, dampening, \
                           lambda_reg, time_window, \
                           max_iteration=maxiteration, min_loss=min_loss, cuda=opt.bCuda, verbose=opt.bVerbose)

        clf.load_params(save_model_pkl)
        clf.viz_features(X_normalTest, X_abnormalTest, nSingleData, filtered=True, abnormal_disp=True)

    elif opt.bVizRaw:
        from hrl_anomaly_detection import data_viz as dv
        d = ut.load_pickle(save_pkl)
        normalTrainData = np.swapaxes(d['normalTrainingData'], 0, 1)
        dv.viz(normalTrainData)

    elif opt.bParamEstimation:
        '''
        You cannot use multiprocessing and cuda in the same time.
        '''
        n_jobs    = 1
        opt.bCuda = True
        if opt.bPreTrain is False: 
            nFold = 2
            X = np.vstack([X_train, X_test])
        else:
            nFold = 1
            X     = X_train

        maxiteration=4000
        parameters = {'learning_rate': [1e-3, 1e-4, 1e-5], 'momentum':[1e-6], 'dampening':[1e-6], \
                      'lambda_reg': [1e-2, 1e-4, 1e-6], \
                      'layer_sizes': [ [X.shape[1], 128,16], [X.shape[1], 128,8], \
                                       [X.shape[1], 64,4], [X.shape[1], 256, 16], [X.shape[1], 256, 8], \
                                       [X.shape[1], 256, 4]  ]}

        save_file='tune_data.pkl'            
        if os.path.isfile(save_file):
            data = ut.load_pickle(save_file)
            from operator import itemgetter
            ## data['mean'].sort(key=itemgetter(0), reverse=False)
            
            for params, mean_score, std_score in zip(data['params'], data['mean'], data['std']):
                print("%0.3f (+/-%0.03f) for %r"
                      % (mean_score, std_score / 2, params))
        else:
            clf = auto_encoder(layer_sizes, learning_rate, learning_rate_decay, momentum, dampening, \
                               lambda_reg, time_window, \
                               max_iteration=maxiteration, min_loss=min_loss, cuda=opt.bCuda, \
                               verbose=opt.bVerbose)

            params_list, mean_list, std_list = clf.param_estimation(X, parameters, nFold, n_jobs=n_jobs)
        
            # Save data
            data = {}
            data['mean'] = mean_list
            data['std'] = std_list
            data['params'] = params_list
            ut.save_pickle(data, save_file)
        
        
