import warnings

from sklearn import preprocessing
import random, copy
import numpy as np
import matplotlib.pyplot as plt

from hrl_anomaly_detection import data_manager as dm
from scipy.stats import norm, entropy



def symmetric_entropy(p,q):
    '''
    Return the sum of KL divergences
    '''
    pp = np.array(p)+1e-6
    qq = np.array(q)+1e-6
    
    ## return min(entropy(p,np.array(q)+1e-6), entropy(q,np.array(p)+1e-6))
    return min(entropy(pp,qq), entropy(qq,pp))


def findBestPosteriorDistribution(post, l_statePosterior):
    # Find the best posterior distribution
    min_dist  = 100000000
    min_index = 0

    for j in xrange(len(l_statePosterior)):
        dist = symmetric_entropy(post, l_statePosterior[j])
        
        if min_dist > dist:
            min_index = j
            min_dist  = dist

    return min_index, min_dist


def getProcessSGDdata(X, y, sample_weight=None, remove_overlap=True):
    '''
    y: a list of sample label (1D)
    flattening and randomly mix the data
    '''
    for k in xrange(len(X)):
        X_ptrain, Y_ptrain = X[k], y[k]
        if Y_ptrain[0] > 0 and remove_overlap:           
            X_ptrain, Y_ptrain = dm.getEstTruePositive(X_ptrain)
            if len(X_ptrain) == 0:
                warnings.warn("No likelihood drop. Please, increase the sensitivity!!")
                X_ptrain = X[k][len(X[k])/2:]
                Y_ptrain = y[k][len(y[k])/2:]

        ## sample_weight = np.array([1.0]*len(Y_ptrain))
        if sample_weight is None:
            sample_weights = [1.0]*len(Y_ptrain)
        else:
            sample_weights = [sample_weight[k]]*len(Y_ptrain)        

        if k==0:
            p_train_X = X_ptrain
            p_train_Y = Y_ptrain
            p_train_W = sample_weights
        else:
            p_train_X = np.vstack([p_train_X, X_ptrain])
            p_train_Y = np.hstack([p_train_Y, Y_ptrain])
            p_train_W = p_train_W + sample_weights

    return p_train_X, p_train_Y, p_train_W
    
def vizDecisionBoundary(X, Y, clf, dimReduObs=None):

    if dimReduObs is not None:
        new_X = dimReduObs.transform(X)
    else:
        new_X = X

    # plot the line, the points, and the nearest vectors to the plane
    xx = np.linspace(-1, 2, 10)
    yy = np.linspace(-1, 2, 10)

    X1, X2 = np.meshgrid(xx, yy)
    Z = np.empty(X1.shape)
    for (i, j), val in np.ndenumerate(X1):
            xx1 = val
            xx2 = X2[i, j]
            ## p = clf.decision_function([[xx1, xx2]])
            p = clf.dt.decision_function([[xx1, xx2]])
            Z[i, j] = p[0]

    
    levels = [-1.0, 0.0, 1.0]
    linestyles = ['dashed', 'solid', 'dashed']
    colors = 'k'
    plt.contour(X1, X2, Z, levels, colors=colors, linestyles=linestyles)
    plt.scatter(new_X[:, 0], new_X[:, 1], c=Y, cmap=plt.cm.Paired)
    
    plt.axis('tight')
    plt.show()
    
    
