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

# system & utils
import os, sys, copy, random
import numpy
import numpy as np
import scipy

# Keras
import h5py 
from keras.models import Sequential, Model
from keras.layers import Merge, Input, TimeDistributed, Layer
from keras.layers import Activation, Dropout, Flatten, Dense, merge, Lambda, RepeatVector, LSTM
from keras.layers.advanced_activations import PReLU, LeakyReLU
from keras.utils.np_utils import to_categorical
from keras.optimizers import SGD, Adagrad, Adadelta, RMSprop, Adam
from keras import backend as K
from keras import objectives

from hrl_anomaly_detection.vae import keras_util as ku
from hrl_anomaly_detection.vae import util as vutil

import gc



def lstm_vae(trainData, testData, weights_file=None, batch_size=1024, nb_epoch=500, \
             patience=20, fine_tuning=False, save_weights_file=None, \
             noise_mag=0.0, timesteps=4, sam_epoch=1, \
             x_std_div=1, x_std_offset=0.001,             
             re_load=False, plot=True):
    """
    Variational Autoencoder with two LSTMs and one fully-connected layer
    x_train is (sample x length x dim)
    x_test is (sample x length x dim)
    """

    # stateful mode uses single batch and no subsample like windows.
    #batch_size = 1
    
    x_train = trainData[0]
    y_train = trainData[1]
    x_test = testData[0]
    y_test = testData[1]

    input_dim = len(x_train[0][0])

    h1_dim = input_dim
    h2_dim = 2 #input_dim
    z_dim  = 2

    inputs = Input(batch_shape=(1, timesteps, input_dim))
    encoded = LSTM(h1_dim, return_sequences=True, activation='tanh', stateful=True)(inputs)
    encoded = LSTM(h2_dim, return_sequences=False, activation='tanh', stateful=True)(encoded)
    z_mean  = Dense(z_dim)(encoded) 
    z_log_var = Dense(z_dim)(encoded) 
    
    def sampling(args):
        z_mean, z_log_var = args
        epsilon = K.random_normal(shape=K.shape(z_mean), mean=0., stddev=1.0)
        #epsilon = K.random_normal(shape=(z_dim,), mean=0., stddev=1.0)
        return z_mean + K.exp(z_log_var/2.0) * epsilon    
        
    # we initiate these layers to reuse later.
    decoded_h1 = Dense(h2_dim, name='h_1') #, activation='tanh'
    decoded_h2 = RepeatVector(timesteps, name='h_2')
    decoded_L1 = LSTM(h1_dim, return_sequences=True, activation='tanh', stateful=True, name='L_1')
    decoded_L21 = LSTM(input_dim*2, return_sequences=True, activation='sigmoid', stateful=True, name='L_21')

    # Custom loss layer
    class CustomVariationalLayer(Layer):
        def __init__(self, **kwargs):
            self.is_placeholder = True
            super(CustomVariationalLayer, self).__init__(**kwargs)

        def vae_loss(self, x, x_d_mean, x_d_std):
            # default 1
            log_p_x_z = -0.5 * ( K.sum(K.square((x-x_d_mean)/x_d_std), axis=-1) \
                                 + float(input_dim) * K.log(2.0*np.pi) + K.sum(K.log(K.square(x_d_std)),
                                                                               axis=-1) )
            xent_loss = K.mean(-log_p_x_z, axis=-1)

            kl_loss = - 0.5 * K.sum(1 + z_log_var - K.square(z_mean) - K.exp(z_log_var), axis=-1)
            return K.mean(xent_loss + kl_loss) 

        def call(self, args):
            x = args[0]
            x_d_mean = args[1][:,:,:input_dim]
            x_d_std  = args[1][:,:,input_dim:]/x_std_div + x_std_offset
            
            loss = self.vae_loss(x, x_d_mean, x_d_std)
            self.add_loss(loss, inputs=args)
            # We won't actually use the output.
            return x_d_mean


    z = Lambda(sampling)([z_mean, z_log_var])    
    decoded = decoded_h1(z)
    decoded = decoded_h2(decoded)
    decoded = decoded_L1(decoded)
    decoded = decoded_L21(decoded)
    outputs = CustomVariationalLayer()([inputs, decoded])

    vae_autoencoder = Model(inputs, outputs)
    print(vae_autoencoder.summary())

    # Encoder --------------------------------------------------
    vae_encoder_mean = Model(inputs, z_mean)
    vae_encoder_var  = Model(inputs, z_log_var)

    # Decoder (generator) --------------------------------------
    ## decoder_input = Input(batch_shape=(1,z_dim))
    ## _decoded = decoded_h1(decoder_input)
    ## _decoded = decoded_h2(_decoded)
    ## _decoded = decoded_L1(_decoded)
    ## _decoded = decoded_L21(_decoded)
    ## generator = Model(decoder_input, _decoded)
    generator = None

    # VAE --------------------------------------
    vae_mean_std = Model(inputs, decoded)

    if weights_file is not None and os.path.isfile(weights_file) and fine_tuning is False and re_load is False:
        vae_autoencoder.load_weights(weights_file)
    else:
        if fine_tuning:
            vae_autoencoder.load_weights(weights_file)
            lr = 0.0001
            optimizer = Adam(lr=lr, clipvalue=10)                
            vae_autoencoder.compile(optimizer=optimizer, loss=None)
        else:
            if re_load and os.path.isfile(weights_file):
                vae_autoencoder.load_weights(weights_file)
            lr = 0.01
            #optimizer = RMSprop(lr=lr, rho=0.9, epsilon=1e-08, decay=0.0001, clipvalue=10)
            #optimizer = Adam(lr=lr, clipvalue=10)                
            #vae_autoencoder.compile(optimizer=optimizer, loss=None)
            vae_autoencoder.compile(optimizer='adam', loss=None)

        # ---------------------------------------------------------------------------------
        nDim         = len(x_train[0][0])
        wait         = 0
        plateau_wait = 0
        min_loss = 1e+15
        for epoch in xrange(nb_epoch):
            print 

            mean_tr_loss = []
            for sample in xrange(sam_epoch):
                for i in xrange(len(x_train)):
                    seq_tr_loss = []
                    for j in xrange(len(x_train[i])-timesteps+1):
                        np.random.seed(3334 + i*len(x_train[i]) + j)
                        noise = np.random.normal(0, noise_mag, (timesteps, nDim))

                        tr_loss = vae_autoencoder.train_on_batch(
                            np.expand_dims(x_train[i,j:j+timesteps]+noise, axis=0),
                            np.expand_dims(x_train[i,j:j+timesteps]+noise, axis=0))
                        seq_tr_loss.append(tr_loss)
                    mean_tr_loss.append( np.mean(seq_tr_loss) )
                    vae_autoencoder.reset_states()

                sys.stdout.write('Epoch {} / {} : loss training = {} , loss validating = {}\r'.format(epoch, nb_epoch, np.mean(mean_tr_loss), 0))
                sys.stdout.flush()   


            mean_te_loss = []
            for i in xrange(len(x_test)):
                seq_te_loss = []
                for j in xrange(len(x_test[i])-timesteps+1):
                    ## np.random.seed(3334 + i*len(x_test[i]) + j)
                    #noise = np.random.normal(0, noise_mag, np.shape((timesteps,nDim)))                    
                    te_loss = vae_autoencoder.test_on_batch(
                        np.expand_dims(x_test[i,j:j+timesteps], axis=0),
                        np.expand_dims(x_test[i,j:j+timesteps], axis=0))
                    seq_te_loss.append(te_loss)
                mean_te_loss.append( np.mean(seq_te_loss) )
                vae_autoencoder.reset_states()


            val_loss = np.mean(mean_te_loss)
            sys.stdout.write('Epoch {} / {} : loss training = {} , loss validating = {}\r'.format(epoch, nb_epoch, np.mean(mean_tr_loss), val_loss))
            sys.stdout.flush()   


            # Early Stopping
            if val_loss <= min_loss:
                min_loss = val_loss
                wait         = 0
                plateau_wait = 0

                if save_weights_file is not None:
                    vae_autoencoder.save_weights(save_weights_file)
                else:
                    vae_autoencoder.save_weights(weights_file)
                
            else:
                if wait > patience:
                    print "Over patience!"
                    break
                else:
                    wait += 1
                    plateau_wait += 1

            #ReduceLROnPlateau
            if plateau_wait > 2:
                old_lr = float(K.get_value(vae_autoencoder.optimizer.lr))
                new_lr = old_lr * 0.2
                K.set_value(vae_autoencoder.optimizer.lr, new_lr)
                plateau_wait = 0
                print 'Reduced learning rate {} to {}'.format(old_lr, new_lr)

        gc.collect()

    # ---------------------------------------------------------------------------------
    # visualize outputs
    if False:
        print "latent variable visualization"

    if plot:
        print "variance visualization"
        nDim = len(x_test[0,0])
        
        for i in xrange(len(x_test)):
            print i

            vae_autoencoder.reset_states()
            vae_mean_std.reset_states()
            
            x_pred_mean = []
            x_pred_std  = []
            for j in xrange(len(x_test[i])-timesteps+1):
                x_pred = vae_mean_std.predict(x_test[i:i+1,j:j+timesteps])
                x_pred_mean.append(x_pred[0,-1,:nDim])
                x_pred_std.append(x_pred[0,-1,nDim:]/x_std_div+x_std_offset)

            vutil.graph_variations(x_test[i], x_pred_mean, x_pred_std)
        


    return vae_autoencoder, vae_mean_std, vae_mean_std, vae_encoder_mean, vae_encoder_var, generator

