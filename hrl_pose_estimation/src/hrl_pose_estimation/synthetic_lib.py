#!/usr/bin/env python
import sys
import os
import time
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.pylab import *

import cPickle as pkl
import random
from scipy import ndimage
import scipy.stats as ss
from scipy.misc import imresize
from scipy.ndimage.interpolation import zoom
from skimage.feature import hog
from skimage import data, color, exposure

from sklearn.cluster import KMeans
from sklearn.preprocessing import scale
from sklearn import svm, linear_model, decomposition, kernel_ridge, neighbors
from sklearn import metrics, cross_validation
from sklearn.utils import shuffle


import pickle
from hrl_lib.util import load_pickle


# PyTorch libraries
import argparse
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import transforms
from torch.autograd import Variable

MAT_WIDTH = 0.762 #metres
MAT_HEIGHT = 1.854 #metres
MAT_HALF_WIDTH = MAT_WIDTH/2
NUMOFTAXELS_X = 84#73 #taxels
NUMOFTAXELS_Y = 47#30
INTER_SENSOR_DISTANCE = 0.0286#metres
LOW_TAXEL_THRESH_X = 0
LOW_TAXEL_THRESH_Y = 0
HIGH_TAXEL_THRESH_X = (NUMOFTAXELS_X - 1)
HIGH_TAXEL_THRESH_Y = (NUMOFTAXELS_Y - 1)




class SyntheticLib():

    def synthetic_scale(self, images, targets):

        x = np.arange(-10 ,11)
        xU, xL = x + 0.5, x - 0.05
        prob = ss.norm.cdf(xU, scale=3) - ss.norm.cdf(xL, scale=3)
        prob = prob / prob.sum()  # normalize the probabilities so their sum is 1
        multiplier = np.random.choice(x, size=images.shape[0], p=prob)
        multiplier = ( multiplier *0.005 ) +1
        # plt.hist(multiplier)
        # plt.show()

        # print multiplier
        tar_mod = np.reshape(targets, (targets.shape[0], targets.shape[1] / 3, 3) ) /1000

        for i in np.arange(images.shape[0]):
            #multiplier[i] = 0.8
            resized = zoom(images[i ,: ,:], multiplier[i])
            resized = np.clip(resized, 0, 100)

            rl_diff = resized.shape[1] - images[i ,: ,:].shape[1]
            ud_diff = resized.shape[0] - images[i ,: ,:].shape[0]
            l_clip = np.int(math.ceil((rl_diff) / 2))
            # r_clip = rl_diff - l_clip
            u_clip = np.int(math.ceil((ud_diff) / 2))
            # d_clip = ud_diff - u_clip

            if rl_diff < 0:  # if less than 0, we'll have to add some padding in to get back up to normal size
                resized_adjusted = np.zeros_like(images[i ,: ,:])
                resized_adjusted[-u_clip:-u_clip + resized.shape[0], -l_clip:-l_clip + resized.shape[1]] = np.copy(resized)
                images[i ,: ,:] = resized_adjusted
                shift_factor_x = INTER_SENSOR_DISTANCE * -l_clip
            elif rl_diff > 0: # if greater than 0, we'll have to cut the sides to get back to normal size
                resized_adjusted = np.copy \
                    (resized[u_clip:u_clip + images[i ,: ,:].shape[0], l_clip:l_clip + images[i ,: ,:].shape[1]])
                images[i ,: ,:] = resized_adjusted
                shift_factor_x = INTER_SENSOR_DISTANCE * -l_clip
            else:
                shift_factor_x = 0

            if ud_diff < 0:
                shift_factor_y = INTER_SENSOR_DISTANCE * u_clip
            elif ud_diff > 0:
                shift_factor_y = INTER_SENSOR_DISTANCE * u_clip
            else:
                shift_factor_y = 0
            # print shift_factor_y, shift_factor_x

            resized_tar = np.copy(tar_mod[i ,: ,:])
            # resized_tar = np.reshape(resized_tar, (len(resized_tar) / 3, 3))
            # print resized_tar.shape/
            resized_tar = (resized_tar + INTER_SENSOR_DISTANCE ) * multiplier[i]

            resized_tar[:, 0] = resized_tar[:, 0] + shift_factor_x  - INTER_SENSOR_DISTANCE #- 10 * INTER_SENSOR_DISTANCE * (1 - multiplier[i])
            # resized_tar2 = np.copy(resized_tar)
            resized_tar[:, 1] = resized_tar[:, 1] + NUMOFTAXELS_X * (1 - multiplier[i]) * INTER_SENSOR_DISTANCE + shift_factor_y  - INTER_SENSOR_DISTANCE #- 10 * INTER_SENSOR_DISTANCE * (1 - multiplier[i])
            # resized_tar[7,:] = [-0.286,0,0]
            tar_mod[i, :, :] = resized_tar

        targets = np.reshape(tar_mod, (targets.shape[0], targets.shape[1])) * 1000

        return images, targets


    def synthetic_shiftxy(self, images, targets):
        x = np.arange(-10, 11)
        xU, xL = x + 0.5, x - 0.5
        prob = ss.norm.cdf(xU, scale=3) - ss.norm.cdf(xL, scale=3)
        prob = prob / prob.sum()  # normalize the probabilities so their sum is 1
        modified_x = np.random.choice(x, size=images.shape[0], p=prob)
        # plt.hist(modified_x)
        # plt.show()

        y = np.arange(-10, 11)
        yU, yL = y + 0.5, y - 0.5
        prob = ss.norm.cdf(yU, scale=3) - ss.norm.cdf(yL, scale=3)
        prob = prob / prob.sum()  # normalize the probabilities so their sum is 1
        modified_y = np.random.choice(y, size=images.shape[0], p=prob)

        tar_mod = np.reshape(targets, (targets.shape[0], targets.shape[1] / 3, 3))

        # print images[0,30:34,10:14]
        # print modified_x[0]
        for i in np.arange(images.shape[0]):
            if modified_x[i] > 0:
                images[i, :, modified_x[i]:] = images[i, :, 0:-modified_x[i]]
            elif modified_x[i] < 0:
                images[i, :, 0:modified_x[i]] = images[i, :, -modified_x[i]:]

            if modified_y[i] > 0:
                images[i, modified_y[i]:, :] = images[i, 0:-modified_y[i], :]
            elif modified_y[i] < 0:
                images[i, 0:modified_y[i], :] = images[i, -modified_y[i]:, :]

            tar_mod[i, :, 0] += modified_x[i] * INTER_SENSOR_DISTANCE * 1000
            tar_mod[i, :, 1] -= modified_y[i] * INTER_SENSOR_DISTANCE * 1000

        # print images[0, 30:34, 10:14]
        targets = np.reshape(tar_mod, (targets.shape[0], targets.shape[1]))

        return images, targets


    def synthetic_fliplr(self, images, targets):
        coin = np.random.randint(2, size=images.shape[0])
        modified = coin
        original = 1 - coin

        im_orig = np.multiply(images, original[:, np.newaxis, np.newaxis])
        im_mod = np.multiply(images, modified[:, np.newaxis, np.newaxis])

        # flip the x axis on all the modified pressure mat images
        im_mod = im_mod[:, :, ::-1]

        tar_orig = np.multiply(targets, original[:, np.newaxis])
        tar_mod = np.multiply(targets, modified[:, np.newaxis])

        # change the left and right tags on the target in the z, flip x target left to right
        tar_mod = np.reshape(tar_mod, (tar_mod.shape[0], tar_mod.shape[1] / 3, 3))

        # flip the x left to right
        tar_mod[:, :, 0] = (tar_mod[:, :, 0] - 657.8) * -1 + 657.8

        # swap in the z
        dummy = zeros((tar_mod.shape))

        if self.arms_only == True:
            dummy[:, [0, 2], :] = tar_mod[:, [0, 2], :]
            tar_mod[:, [0, 2], :] = tar_mod[:, [1, 3], :]
            tar_mod[:, [1, 3], :] = dummy[:, [0, 2], :]
        else:
            dummy[:, [2, 4, 6, 8], :] = tar_mod[:, [2, 4, 6, 8], :]
            tar_mod[:, [2, 4, 6, 8], :] = tar_mod[:, [3, 5, 7, 9], :]
            tar_mod[:, [3, 5, 7, 9], :] = dummy[:, [2, 4, 6, 8], :]
        # print dummy[0,:,2], tar_mod[0,:,2]

        tar_mod = np.reshape(tar_mod, (tar_mod.shape[0], tar_orig.shape[1]))
        tar_mod = np.multiply(tar_mod, modified[:, np.newaxis])

        images = im_orig + im_mod
        targets = tar_orig + tar_mod
        return images, targets


    def synthetic_master(self, images_tensor, targets_tensor, flip=False, shift=False, scale=False, bedangle = False, arms_only = False, include_inter = False):
        self.arms_only = arms_only
        self.include_inter = include_inter
        self.t1 = time.time()
        images_tensor = torch.squeeze(images_tensor)
        # images_tensor.torch.Tensor.permute(1,2,0)
        imagesangles = images_tensor.numpy()
        targets = targets_tensor.numpy()

        if bedangle == True:
            if include_inter == True:
                images = imagesangles[:, 0:2, :, :]
            else:
                images = imagesangles[:,0,:,:]
        else:
            images = imagesangles
        #print images.shape, targets.shape, 'shapes'

        if scale == True:
            images, targets = self.synthetic_scale(images, targets)
        if flip == True:
            images, targets = self.synthetic_fliplr(images, targets)
        if shift == True:
            images, targets = self.synthetic_shiftxy(images, targets)

        # print images[0, 10:15, 20:25]

        if bedangle == True:
            if include_inter == True:
                imagesangles[:,0:2,:,:] = images
            else:
                imagesangles[:,0,:,:] = images
            images_tensor = torch.Tensor(imagesangles)
        else:
            imagesangles = images
            images_tensor = torch.Tensor(imagesangles)
            images_tensor = images_tensor.unsqueeze(1)


        targets_tensor = torch.Tensor(targets)
        # images_tensor.torch.Tensor.permute(2, 0, 1)
        try:
            self.t2 = time.time() - self.t1
        except:
            self.t2 = 0
        # print self.t2, 'elapsed time'
        return images_tensor, targets_tensor
