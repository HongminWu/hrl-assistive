#!/usr/bin/env python

import os, sys
import math
import struct
import numpy as np
import cPickle as pickle
from scipy import interpolate
import matplotlib.pyplot as plt
from contextlib import contextmanager

def extrapolateData(data, maxsize):
    return [x if len(x) >= maxsize else x + [x[-1]]*(maxsize-len(x)) for x in data]

def extrapolateAllData(allData, maxsize):
    return [extrapolateData(data, maxsize) for data in allData]

def get_rms(block):
    # RMS amplitude is defined as the square root of the
    # mean over time of the square of the amplitude.
    # so we need to convert this string of bytes into
    # a string of 16-bit samples...

    # we will get one short out for each
    # two chars in the string.
    count = len(block)/2
    structFormat = '%dh' % count
    shorts = struct.unpack(structFormat, block)

    # iterate over the block.
    sum_squares = 0.0
    for sample in shorts:
        # sample is a signed short in +/- 32768.
        # normalize it to 1.0
        n = sample / 32768.0
        sum_squares += n*n

    return math.sqrt(sum_squares / count)

def scaling(X, minVal, maxVal, scale=1.0):
    X = np.array(X)
    return (X - minVal) / (maxVal - minVal) * scale

def forceKinematics(fileName):
    with open(fileName, 'rb') as f:
        data = pickle.load(f)
        kinematics = data['kinematics_data']
        kinematicsTimes = data['kinematics_time']
        force = data['ft_force_raw']
        forceTimes = data['ft_time']

        # Use magnitude of forces
        forces = np.linalg.norm(force, axis=1).flatten()
        distances = []
        angles = []

        # Compute kinematic distances and angles
        for mic, spoon, objectCenter in kinematics:
            # Determine distance between mic and center of object
            distances.append(np.linalg.norm(mic - objectCenter))
            # Find angle between gripper-object vector and gripper-spoon vector
            micSpoonVector = spoon - mic
            micObjectVector = objectCenter - mic
            angle = np.arccos(np.dot(micSpoonVector, micObjectVector) / (np.linalg.norm(micSpoonVector) * np.linalg.norm(micObjectVector)))
            angles.append(angle)

        return forces, distances, angles, kinematicsTimes, forceTimes

def audioFeatures(fileName):
    with open(fileName, 'rb') as f:
        data = pickle.load(f)
        audios = data['audio_data_raw']
        audioTimes = data['audio_time']
        magnitudes = []
        for audio in audios:
            magnitudes.append(get_rms(audio))

        return magnitudes, audioTimes

def loadData(fileNames, isTrainingData=False, downSampleSize=100, verbose=False):
    timesList = []

    forcesTrueList = []
    distancesTrueList = []
    anglesTrueList = []
    audioTrueList = []
    for idx, fileName in enumerate(fileNames):
        audio, audioTimes = audioFeatures(fileName)
        forces, distances, angles, kinematicsTimes, forceTimes = forceKinematics(fileName)

        # There will be much more kinematics data than force or audio, so interpolate to fill in the gaps
        # print 'Force shape:', np.shape(forces), 'Distance shape:', np.shape(distances), 'Angles shape:', 
        # np.shape(angles), 'Audio shape:', np.shape(audio)

        newTimes = np.linspace(0.01, max(kinematicsTimes), downSampleSize)
        forceInterp = interpolate.splrep(forceTimes, forces, s=0)
        forces = interpolate.splev(newTimes, forceInterp, der=0)
        distanceInterp = interpolate.splrep(kinematicsTimes, distances, s=0)
        distances = interpolate.splev(newTimes, distanceInterp, der=0)
        angleInterp = interpolate.splrep(kinematicsTimes, angles, s=0)
        angles = interpolate.splev(newTimes, angleInterp, der=0)
        # audioInterp = interpolate.splrep(audioTimes, audio, s=0)
        # audio = interpolate.splev(newTimes, audioInterp, der=0)

        # Downsample audio (nicely), by finding the closest time sample in audio for each new time stamp
        audioTimes = np.array(audioTimes)
        audio = [audio[np.abs(audioTimes - t).argmin()] for t in newTimes]

        # print 'Shapes after downsampling'
        # print 'Force shape:', np.shape(forces), 'Distance shape:', np.shape(distances), 'Angles shape:', 
        # np.shape(angles), 'Audio shape:', np.shape(audio)

        # Constant (horizontal linear) interpolation for audio data
        # tempAudio = []
        # audioIndex = 0
        # for t in kinematicsTimes:
        #     if t > audioTimes[audioIndex + 1] and audioIndex < len(audioTimes) - 2:
        #         audioIndex += 1
        #     tempAudio.append(audio[audioIndex])
        # audio = tempAudio

        forcesTrueList.append(forces.tolist())
        distancesTrueList.append(distances.tolist())
        anglesTrueList.append(angles.tolist())
        audioTrueList.append(audio)
        timesList.append(newTimes.tolist())

    if verbose: print 'Load shapes pre extrapolation:', np.shape(forcesTrueList), np.shape(distancesTrueList), \
        np.shape(anglesTrueList), np.shape(audioTrueList)

    # Each iteration may have a different number of time steps, so we extrapolate so they are all consistent
    if isTrainingData:
        # Find the largest iteration
        maxsize = max([len(x) for x in forcesTrueList])
        # Extrapolate each time step
        forcesTrueList, distancesTrueList, anglesTrueList, audioTrueList, timesList\
          = extrapolateAllData([forcesTrueList, distancesTrueList, anglesTrueList, audioTrueList, timesList],\
                               maxsize)

    if verbose: print 'Load shapes post extrapolation:', np.shape(forcesTrueList), np.shape(distancesTrueList),\
      np.shape(anglesTrueList), np.shape(audioTrueList)

    return [forcesTrueList, distancesTrueList, anglesTrueList, audioTrueList], timesList

@contextmanager
def suppress_output():
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr






def displayExpLikelihoods(hmm, trainData, normalTestData, abnormalTestData, ths_mult, save_pdf=False):


    fig = plt.figure()

    n = len(normalTestData[0])
    log_ll = []
    exp_log_ll = []
        
    for i in range(n):
        m = len(normalTestData[0][i])

        log_ll.append([])
        exp_log_ll.append([])
        for j in range(2, m):
            
            X_test = hmm.convert_sequence(normalTestData[0][i][:j], normalTestData[1][i][:j], 
                                          normalTestData[2][i][:j], normalTestData[3][i][:j])
            try:
                logp = hmm.loglikelihood(X_test)
            except:
                print "Too different input profile that cannot be expressed by emission matrix"
                return [], 0.0 # error

            log_ll[i].append(logp)


            exp_logp = hmm.expLikelihoods(normalTestData[0][i][:j], normalTestData[1][i][:j], 
                                          normalTestData[2][i][:j], normalTestData[3][i][:j],
                                          ths_mult)
            exp_log_ll[i].append(exp_logp)
            

        plt.plot(log_ll[i], 'g-')
        plt.plot(exp_log_ll[i], 'r-')


    ## plt.ylim([-500, 500])
        

    if save_pdf == True:
        fig.savefig('test.pdf')
        fig.savefig('test.png')
        os.system('cp test.p* ~/Dropbox/HRL/')
    else:
        plt.show()        


def displayData(hmm, trainData, normalTestData, abnormalTestData, save_pdf=False):

    fig = plt.figure()
    ax1 = plt.subplot(412)
    ax1.set_ylabel('Force\nMagnitude (N)', fontsize=16)
    ax1.set_xticks(np.arange(0, 25, 5))
    # ax1.set_yticks(np.arange(8, 10, 0.5))
    # ax1.set_yticks(np.arange(np.min(self.forcesTrue), np.max(self.forcesTrue), 1.0))
    # ax1.grid()
    ax2 = plt.subplot(411)
    ax2.set_ylabel('Kinematic\nDistance (m)', fontsize=16)
    ax2.set_xticks(np.arange(0, 25, 5))
    # ax2.set_yticks(np.arange(0, 1.0, 0.2))
    # ax2.set_ylim([0, 1.0])
    # ax2.set_yticks(np.arange(np.min(self.distancesTrue), np.max(self.distancesTrue), 0.2))
    # ax2.grid()
    ax3 = plt.subplot(414)
    ax3.set_ylabel('Kinematic\nAngle (rad)', fontsize=16)
    ax3.set_xlabel('Time (sec)', fontsize=16)
    ax3.set_xticks(np.arange(0, 25, 5))
    # ax3.set_yticks(np.arange(0, 1.5, 0.3))
    # ax3.set_ylim([0, 1.5])
    # ax3.set_yticks(np.arange(np.min(self.anglesTrue), np.max(self.anglesTrue), 0.2))
    # ax3.grid()
    ax4 = plt.subplot(413)
    ax4.set_ylabel('Audio\nMagnitude (dec)', fontsize=16)
    ax4.set_xticks(np.arange(0, 25, 5))

    for i in xrange(len(trainData[0])):
        ax1.plot(trainData[0][i], c='b')
        ax2.plot(trainData[1][i], c='b')
        ax3.plot(trainData[2][i], c='b')
        ax4.plot(trainData[3][i], c='b')

    for i in xrange(len(normalTestData[0])):
        ax1.plot(normalTestData[0][i], c='r')
        ax2.plot(normalTestData[1][i], c='r')
        ax3.plot(normalTestData[2][i], c='r')
        ax4.plot(normalTestData[3][i], c='r')
        

    if save_pdf == True:
        fig.savefig('test.pdf')
        fig.savefig('test.png')
        os.system('cp test.p* ~/Dropbox/HRL/')
    else:
        plt.show()        
        
    

def displayLikelihoods(hmm, trainData, normalTestData, abnormalTestData, save_pdf=False):


    fig = plt.figure()

    n = len(trainData[0])
    log_ll = []
    
    for i in range(n):
        m = len(trainData[0][i])

        log_ll.append([])
        for j in range(2, m):

            X_test = hmm.convert_sequence(trainData[0][i][:j], trainData[1][i][:j], 
                                          trainData[2][i][:j], trainData[3][i][:j])
                        
            try:
                logp = hmm.loglikelihood(X_test)
            except:
                print "Too different input profile that cannot be expressed by emission matrix"
                return [], 0.0 # error

            log_ll[i].append(logp)

        plt.plot(log_ll[i], 'b-')
    

    n = len(normalTestData[0])
    log_ll = []

    print "0000000000000000000000"
    print n
    print "0000000000000000000000"
        
    for i in range(n):
        m = len(normalTestData[0][i])

        log_ll.append([])
        for j in range(2, m):

            X_test = hmm.convert_sequence(normalTestData[0][i][:j], normalTestData[1][i][:j], 
                                          normalTestData[2][i][:j], normalTestData[3][i][:j])

            try:
                logp = hmm.loglikelihood(X_test)
            except:
                print "Too different input profile that cannot be expressed by emission matrix"
                return [], 0.0 # error

            log_ll[i].append(logp)

        plt.plot(log_ll[i], 'g-')


    ## n = len(abnormalTestData[0])
    ## log_ll = []
        
    ## for i in range(n):
    ##     m = len(abnormalTestData[0][i])

    ##     log_ll.append([])
    ##     for j in range(2, m):

    ##         X_test = hmm.convert_sequence(abnormalTestData[0][i][:j], abnormalTestData[1][i][:j], 
    ##                                       abnormalTestData[2][i][:j], abnormalTestData[3][i][:j])

    ##         try:
    ##             logp = hmm.loglikelihood(X_test)
    ##         except:
    ##             print "Too different input profile that cannot be expressed by emission matrix"
    ##             return [], 0.0 # error

    ##         log_ll[i].append(logp)

    ##     ax = plt.plot(log_ll[i], 'r-')


    plt.ylim([-500, 500])
        

    if save_pdf == True:
        fig.savefig('test.pdf')
        fig.savefig('test.png')
        os.system('cp test.p* ~/Dropbox/HRL/')
    else:
        plt.show()        
