#!/usr/local/bin/python

import numpy as np
import sys, os, copy
import cPickle as pickle
from scipy.stats import norm, entropy

# Matplot
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import gridspec

import ghmm
from sklearn.metrics import r2_score
from joblib import Parallel, delayed

class learning_hmm_multi_4d:
    def __init__(self, nState, nFutureStep=5, nCurrentStep=10, nEmissionDim=4, check_method='progress'):
        self.ml = None

        ## Tunable parameters
        self.nState = nState # the number of hidden states
        self.nGaussian = nState
        self.nFutureStep = nFutureStep
        self.nCurrentStep = nCurrentStep
        self.nEmissionDim = nEmissionDim
        
        ## Un-tunable parameters
        self.trans_type = 'left_right' # 'left_right' 'full'
        self.A = None # transition matrix        
        self.B = None # emission matrix
        self.pi = None # Initial probabilities per state
        self.check_method = check_method # ['global', 'progress']

        self.l_statePosterior = None
        self.ll_mu = None
        self.ll_std = None
        self.l_mean_delta = None
        self.l_std_delta = None
        self.l_mu = None
        self.l_std = None
        self.std_coff = None

        # emission domain of this model        
        self.F = ghmm.Float()  

        print 'HMM initialized for', self.check_method

    def fit(self, xData1, xData2, xData3, xData4, A=None, B=None, pi=None, cov_mult=[100.0]*16, verbose=False, ml_pkl='ml_temp_4d.pkl', use_pkl=False):
        ml_pkl = os.path.join(os.path.dirname(__file__), ml_pkl)
        X1 = np.array(xData1)
        X2 = np.array(xData2)
        X3 = np.array(xData3)
        X4 = np.array(xData4)

        if A is None:        
            if verbose: print "Generating a new A matrix"
            # Transition probability matrix (Initial transition probability, TODO?)
            A = self.init_trans_mat(self.nState).tolist()

            # print 'A', A

        if B is None:
            if verbose: print "Generating a new B matrix"
            # We should think about multivariate Gaussian pdf.  

            mu1, mu2, mu3, mu4, cov = self.vectors_to_mean_cov(X1, X2, X3, X4, self.nState)
            for i in xrange(self.nEmissionDim):
                for j in xrange(self.nEmissionDim):
                    cov[:, j, i] *= cov_mult[self.nEmissionDim*i + j]

            print 'mu1:', mu1
            print 'mu2:', mu2
            print 'mu3:', mu3
            print 'mu4:', mu4
            print 'cov', cov

            # Emission probability matrix
            B = [0.0] * self.nState
            for i in range(self.nState):
                B[i] = [[mu1[i], mu2[i], mu3[i], mu4[i]], [cov[i,0,0], cov[i,0,1], cov[i,0,2], cov[i,0,3],
                                                           cov[i,1,0], cov[i,1,1], cov[i,1,2], cov[i,1,3],
                                                           cov[i,2,0], cov[i,2,1], cov[i,2,2], cov[i,2,3],
                                                           cov[i,3,0], cov[i,3,1], cov[i,3,2], cov[i,3,3]]]
        if pi is None:
            # pi - initial probabilities per state 
            ## pi = [1.0/float(self.nState)] * self.nState
            pi = [0.0] * self.nState
            pi[0] = 1.0

        print 'Generating HMM'
        # HMM model object
        self.ml = ghmm.HMMFromMatrices(self.F, ghmm.MultivariateGaussianDistribution(self.F), A, B, pi)
        print 'Creating Training Data'
        X_train = self.convert_sequence(X1, X2, X3, X4) # Training input
        X_train = X_train.tolist()
        
        print 'Run Baum Welch method with (samples, length)', np.shape(X_train)
        final_seq = ghmm.SequenceSet(self.F, X_train)
        ## ret = self.ml.baumWelch(final_seq, loglikelihoodCutoff=2.0)
        ret = self.ml.baumWelch(final_seq, 10000)
        print 'Baum Welch return:', ret

        [self.A, self.B, self.pi] = self.ml.asMatrices()
        self.A = np.array(self.A)
        self.B = np.array(self.B)
        # print 'B\'s shape:', self.B.shape, self.B[0].shape, self.B[1].shape
        # print B[0]
        # print B[1]

        #--------------- learning for anomaly detection ----------------------------
        [A, B, pi] = self.ml.asMatrices()
        n, m = np.shape(X1)
        self.nGaussian = self.nState

        # Get average loglikelihood threshold wrt progress
        self.std_coff  = 1.0
        g_mu_list = np.linspace(0, m-1, self.nGaussian) #, dtype=np.dtype(np.int16))
        g_sig = float(m) / float(self.nGaussian) * self.std_coff

        print 'g_mu_list:', g_mu_list
        print 'g_sig:', g_sig

        ######################################################################################
        if os.path.isfile(ml_pkl) and use_pkl:
            with open(ml_pkl, 'rb') as f:
                d = pickle.load(f)
                self.l_statePosterior = d['state_post'] # time x state division
                self.ll_mu            = d['ll_mu']
                self.ll_std           = d['ll_std']
        else:
            n_jobs = -1
            print 'Begining parallel job'
            r = Parallel(n_jobs=n_jobs)(delayed(learn_likelihoods_progress)(i, n, m, A, B, pi, self.F, X_train,
                                                                   self.nEmissionDim, g_mu_list[i], g_sig, self.nState)
                                                                   for i in xrange(self.nGaussian))
            print 'Completed parallel job'
            l_i, self.l_statePosterior, self.ll_mu, self.ll_std = zip(*r)

            d = dict()
            d['state_post'] = self.l_statePosterior
            d['ll_mu'] = self.ll_mu
            d['ll_std'] = self.ll_std
            with open(ml_pkl, 'wb') as f:
                pickle.dump(d, f, protocol=pickle.HIGHEST_PROTOCOL)

    def predict(self, X):
        X = np.squeeze(X)
        X_test = X.tolist()

        mu_l = np.zeros(self.nEmissionDim)
        cov_l = np.zeros(self.nEmissionDim**2)

        print self.F
        final_ts_obj = ghmm.EmissionSequence(self.F, X_test) # is it neccessary?

        try:
            # alpha: X_test length y # latent States at the moment t when state i is ended
            # test_profile_length x number_of_hidden_state
            (alpha, scale) = self.ml.forward(final_ts_obj)
            alpha = np.array(alpha)
        except:
            print "No alpha is available !!"
            
        f = lambda x: round(x, 12)
        for i in range(len(alpha)):
            alpha[i] = map(f, alpha[i])
        alpha[-1] = map(f, alpha[-1])
        
        n = len(X_test)
        pred_numerator = 0.0

        for j in xrange(self.nState): # N+1
            total = np.sum(self.A[:,j]*alpha[n/self.nEmissionDim-1,:]) #* scaling_factor
            [mus, covars] = self.B[j]

            ## print mu1, mu2, cov11, cov12, cov21, cov22, total
            pred_numerator += total

            for i in xrange(mu_l.size):
                mu_l[i] += mus[i]*total
            for i in xrange(cov_l.size):
                cov_l[i] += covars[i] * (total**2)

        return mu_l, cov_l

    def predict2(self, X, x1, x2, x3, x4):
        X = np.squeeze(X)
        X_test = X.tolist()        
        n = len(X_test)

        mu_l = np.zeros(self.nEmissionDim)
        cov_l = np.zeros(self.nEmissionDim**2)

        final_ts_obj = ghmm.EmissionSequence(self.F, X_test + [x1, x2, x3, x4])

        try:
            (alpha, scale) = self.ml.forward(final_ts_obj)
        except:
            print "No alpha is available !!"
            sys.exit()

        alpha = np.array(alpha)

        for j in xrange(self.nState):
            
            [[mu1, mu2, mu3, mu4], [cov11, cov12, cov13, cov14, cov21, cov22, cov23, cov24,
                                    cov31, cov32, cov33, cov34, cov41, cov42, cov43, cov44]] = self.B[j]

            mu_l[0] = x1
            mu_l[1] += alpha[n/self.nEmissionDim, j] * (mu2 + cov21/cov11*(x1 - mu1) )
            mu_l[2] += alpha[n/self.nEmissionDim, j] * (mu3 + cov31/cov21*(x2 - mu2)) # TODO Where does this come from?
            mu_l[3] += alpha[n/self.nEmissionDim, j] * (mu4 + cov41/cov31*(x3 - mu3)) # TODO Where does this come from?
            ## cov_l[0] += (cov11)*(total**2)
            ## cov_l[1] += (cov12)*(total**2)
            ## cov_l[2] += (cov21)*(total**2)
            ## cov_l[3] += (cov22)*(total**2)

        return mu_l, cov_l
        
    def loglikelihood(self, X):

        X = np.squeeze(X)
        X_test = X.tolist()        

        final_ts_obj = ghmm.EmissionSequence(self.F, X_test)

        try:    
            p = self.ml.loglikelihood(final_ts_obj)
        except:
            print 'Likelihood error!!!!'
            sys.exit()

        return p
        
    # Returns mu,sigma for n hidden-states from feature-vector
    @staticmethod
    def vectors_to_mean_sigma(vec, nState):
        index = 0
        m,n = np.shape(vec)
        mu  = np.zeros(nState)
        sig = np.zeros(nState)
        DIVS = n/nState

        while index < nState:
            m_init = index*DIVS
            temp_vec = vec[:, m_init:(m_init+DIVS)]
            temp_vec = np.reshape(temp_vec, (1, DIVS*m))
            mu[index]  = np.mean(temp_vec)
            sig[index] = np.std(temp_vec)
            index = index+1

        return mu, sig
        
    # Returns mu,sigma for n hidden-states from feature-vector
    def vectors_to_mean_cov(self, vec1, vec2, vec3, vec4, nState):
        index = 0
        m, n = np.shape(vec1)
        #print m,n
        mu_1 = np.zeros(nState)
        mu_2 = np.zeros(nState)
        mu_3 = np.zeros(nState)
        mu_4 = np.zeros(nState)
        cov = np.zeros((nState, self.nEmissionDim, self.nEmissionDim))
        DIVS = n/nState

        while index < nState:
            m_init = index*DIVS
            temp_vec1 = vec1[:, m_init:(m_init+DIVS)]
            temp_vec2 = vec2[:, m_init:(m_init+DIVS)]
            temp_vec3 = vec3[:, m_init:(m_init+DIVS)]
            temp_vec4 = vec4[:, m_init:(m_init+DIVS)]
            temp_vec1 = np.reshape(temp_vec1, (1, DIVS*m))
            temp_vec2 = np.reshape(temp_vec2, (1, DIVS*m))
            temp_vec3 = np.reshape(temp_vec3, (1, DIVS*m))
            temp_vec4 = np.reshape(temp_vec4, (1, DIVS*m))
            mu_1[index] = np.mean(temp_vec1)
            mu_2[index] = np.mean(temp_vec2)
            mu_3[index] = np.mean(temp_vec3)
            mu_4[index] = np.mean(temp_vec4)
            cov[index, :, :] = np.cov(np.concatenate((temp_vec1, temp_vec2, temp_vec3, temp_vec4), axis=0))
            index = index+1

        return mu_1, mu_2, mu_3, mu_4, cov

    @staticmethod
    def init_trans_mat(nState):
        # Reset transition probability matrix
        trans_prob_mat = np.zeros((nState, nState))

        for i in xrange(nState):
            # Exponential function
            # From y = a*e^(-bx)
            #a = 0.4
            #b = np.log(0.00001/a)/(-(nState-i))
            #f = lambda x: a*np.exp(-b*x)

            # Exponential function
            # From y = -a*x + b
            b = 0.4
            a = b/float(nState)
            f = lambda x: -a*x+b

            for j in np.array(range(nState-i))+i:
                trans_prob_mat[i, j] = f(j)

            # Gaussian transition probability
            ## z_prob = norm.pdf(float(i),loc=u_mu_list[i],scale=u_sigma_list[i])

            # Normalization
            trans_prob_mat[i,:] /= np.sum(trans_prob_mat[i,:])

        return trans_prob_mat

    def init_plot(self):
        print "Start to print out"

        self.fig = plt.figure(1)
        gs = gridspec.GridSpec(4, 1)
        
        self.ax1 = self.fig.add_subplot(gs[0])        
        self.ax2 = self.fig.add_subplot(gs[1])        
        self.ax3 = self.fig.add_subplot(gs[2])
        self.ax4 = self.fig.add_subplot(gs[3])

    def data_plot(self, X_test1, X_test2, X_test3, X_test4, color='r'):
        self.ax1.plot(np.hstack([X_test1[0]]), color)
        self.ax2.plot(np.hstack([X_test2[0]]), color)
        self.ax3.plot(np.hstack([X_test3[0]]), color)
        self.ax4.plot(np.hstack([X_test4[0]]), color)

    @staticmethod
    def final_plot():
        plt.rc('text', usetex=True)
        plt.show()

    @staticmethod
    def convert_sequence(data1, data2, data3, data4, emission=False):
        # change into array from other types
        if type(data1) is not np.ndarray:
            X1 = copy.copy(np.array(data1))
        else:
            X1 = copy.copy(data1)
        if type(data2) is not np.ndarray:
            X2 = copy.copy(np.array(data2))
        else:
            X2 = copy.copy(data2)
        if type(data3) is not np.ndarray:
            X3 = copy.copy(np.array(data3))
        else:
            X3 = copy.copy(data3)
        if type(data4) is not np.ndarray:
            X4 = copy.copy(np.array(data4))
        else:
            X4 = copy.copy(data4)

        # Change into 2dimensional array
        dim = np.shape(X1)
        if len(dim) == 1:
            X1 = np.reshape(X1, (1, len(X1)))
        dim = np.shape(X2)
        if len(dim) == 1:
            X2 = np.reshape(X2, (1, len(X2)))
        dim = np.shape(X3)
        if len(dim) == 1:
            X3 = np.reshape(X3, (1, len(X3)))
        dim = np.shape(X4)
        if len(dim) == 1:
            X4 = np.reshape(X4, (1, len(X4)))

        n, m = np.shape(X1)

        X = []
        for i in xrange(n):
            Xs = []
                
            if emission:
                for j in xrange(m):
                    Xs.append([X1[i, j], X2[i, j], X3[i, j], X4[i, j]])
                X.append(Xs)
            else:
                for j in xrange(m):
                    Xs.append([X1[i, j], X2[i, j], X3[i, j], X4[i, j]])
                X.append(np.array(Xs).flatten().tolist())

        return np.array(X)
        
    def anomaly_check(self, X1, X2=None, X3=None, X4=None, ths_mult=None):
        if self.nEmissionDim == 1: X_test = np.array([X1])
        else: X_test = self.convert_sequence(X1, X2, X3, X4, emission=False)

        try:
            final_ts_obj = ghmm.EmissionSequence(self.F, X_test[0].tolist())
            logp = self.ml.loglikelihood(final_ts_obj)
        except:
            print "Too different input profile that cannot be expressed by emission matrix"
            return -1, 0.0 # error

        try:
            post = np.array(self.ml.posterior(final_ts_obj))
        except:
            print "Unexpected profile!! GHMM cannot handle too low probability. Underflow?"
            return 1.0, 0.0 # anomaly

        n = len(np.squeeze(X1))

        # Find the best posterior distribution
        min_dist  = 100000000
        min_index = 0
        print 'Loglikelihood', logp
        # print 'Last posterior', post[n-1]
        print 'Computing entropies'
        for j in xrange(self.nGaussian):
            dist = entropy(post[n-1], self.l_statePosterior[j])
            # print 'Index:', j, 'Entropy:', dist
            if min_dist > dist:
                min_index = j
                min_dist  = dist

        print 'Computing anomaly'
        print logp
        print self.ll_mu[min_index]
        print self.ll_std[min_index]

        if (type(ths_mult) == list or type(ths_mult) == np.ndarray or type(ths_mult) == tuple) and len(ths_mult)>1:
            err = logp - (self.ll_mu[min_index] + ths_mult[min_index]*self.ll_std[min_index])
        else:
            err = logp - (self.ll_mu[min_index] + ths_mult*self.ll_std[min_index])

        print 'Error', err

        if err < 0.0: return 1.0, 0.0 # anomaly
        else: return 0.0, err # normal    


    @staticmethod
    def scaling(X, min_c=None, max_c=None, scale=10.0, verbose=False):
        '''
        scale should be over than 10.0(?) to avoid floating number problem in ghmm.
        Return list type
        '''
        ## X_scaled = preprocessing.scale(np.array(X))

        if min_c is None or max_c is None:
            min_c = np.min(X)
            max_c = np.max(X)

        X_scaled = []
        for x in X:
            if verbose is True: print min_c, max_c, " : ", np.min(x), np.max(x)
            X_scaled.append(((x-min_c) / (max_c-min_c) * scale))

        return X_scaled, min_c, max_c

    def likelihood_disp(self, X1, X2, X3, X4, X1_true, X2_true, X3_true, X4_true, ths_mult, scale1=None, scale2=None, scale3=None, scale4=None):
        print np.shape(X1)
        n, m = np.shape(X1)
        print "Input sequence X1: ", n, m

        X_test = self.convert_sequence(X1, X2, X3, X4, emission=False)

        x = np.arange(0., float(m))
        ll_likelihood = np.zeros(m)
        ll_state_idx  = np.zeros(m)
        ll_likelihood_mu  = np.zeros(m)
        ll_likelihood_std = np.zeros(m)
        ll_thres_mult = np.zeros(m)
        for i in xrange(m):
            if i == 0: continue

            final_ts_obj = ghmm.EmissionSequence(self.F, X_test[0,:i*self.nEmissionDim].tolist())
            logp = self.ml.loglikelihood(final_ts_obj)
            post = np.array(self.ml.posterior(final_ts_obj))

            # Find the best posterior distribution
            min_dist  = 100000000
            min_index = 0
            for j in xrange(self.nGaussian):
                dist = entropy(post[i-1], self.l_statePosterior[j])
                if min_dist > dist:
                    min_index = j
                    min_dist  = dist

            ll_likelihood[i] = logp
            ll_state_idx[i]  = min_index
            ll_likelihood_mu[i]  = self.ll_mu[min_index]
            ll_likelihood_std[i] = self.ll_std[min_index] #self.ll_mu[min_index] + ths_mult*self.ll_std[min_index]
            ll_thres_mult[i] = ths_mult

        # state blocks
        block_flag = []
        block_x    = []
        block_state= []
        text_n     = []
        text_x     = []
        for i, p in enumerate(ll_state_idx):
            if i is 0:
                block_flag.append(0)
                block_state.append(0)
                text_x.append(0.0)
            elif ll_state_idx[i] != ll_state_idx[i-1]:
                if block_flag[-1] is 0: block_flag.append(1)
                else: block_flag.append(0)
                block_state.append( int(p) )
                text_x[-1] = (text_x[-1]+float(i-1))/2.0 - 0.5 #
                text_x.append(float(i))
            else:
                block_flag.append(block_flag[-1])
            block_x.append(float(i))
        text_x[-1] = (text_x[-1]+float(m-1))/2.0 - 0.5 #

        block_flag_interp = []
        block_x_interp    = []
        for i in xrange(len(block_flag)):
            block_flag_interp.append(block_flag[i])
            block_flag_interp.append(block_flag[i])
            block_x_interp.append( float(block_x[i]) )
            block_x_interp.append(block_x[i]+0.5)


        # y1 = (X1_true[0]/scale1[2])*(scale1[1]-scale1[0])+scale1[0]
        # y2 = (X2_true[0]/scale2[2])*(scale2[1]-scale2[0])+scale2[0]
        # y3 = (X3_true[0]/scale3[2])*(scale3[1]-scale3[0])+scale3[0]
        # y4 = (X4_true[0]/scale4[2])*(scale4[1]-scale4[0])+scale4[0]
        y1 = X1_true[0]
        y2 = X2_true[0]
        y3 = X3_true[0]
        y4 = X4_true[0]

        import matplotlib.collections as collections

        ## matplotlib.rcParams['figure.figsize'] = 8,7
        matplotlib.rcParams['pdf.fonttype'] = 42
        matplotlib.rcParams['ps.fonttype'] = 42

        fig = plt.figure()
        plt.rc('text', usetex=True)

        ax1 = plt.subplot(511)
        print np.shape(x), np.shape(y1)
        ax1.plot(x*(1./43.), y1)
        y_min = np.amin(y1)
        y_max = np.amax(y1)
        collection = collections.BrokenBarHCollection.span_where(np.array(block_x_interp)*(1./43.),
                                                                 ymin=0, ymax=y_max+2.0,
                                                                 where=np.array(block_flag_interp)>0,
                                                                 facecolor='green',
                                                                 edgecolor='none', alpha=0.3)
        ax1.add_collection(collection)
        # Text for progress
        for i in xrange(len(block_state)):
            if i%2 is 0:
                if i<10:
                    ax1.text((text_x[i])*(1./43.), y_max+1.0, str(block_state[i]+1))
                else:
                    ax1.text((text_x[i]-1.0)*(1./43.), y_max+1.0, str(block_state[i]+1))
            else:
                if i<10:
                    ax1.text((text_x[i])*(1./43.), y_max, str(block_state[i]+1))
                else:
                    ax1.text((text_x[i]-1.0)*(1./43.), y_max, str(block_state[i]+1))

        ax1.set_ylabel("Force (N)", fontsize=18)
        ax1.set_xlim([0, x[-1]*(1./43.)])
        ## ax1.set_ylim([0, np.amax(y1)*1.1])
        ax1.set_ylim([y_min - 1, y_max + 2.0])

        # -----

        ax2 = plt.subplot(512)
        ax2.plot(x*(1./43.), y2)
        y_max = np.amax(y2)
        collection = collections.BrokenBarHCollection.span_where(np.array(block_x_interp)*(1./43.),
                                                                 ymin=0, ymax=y_max,
                                                                 where=np.array(block_flag_interp)>0,
                                                                 facecolor='green',
                                                                 edgecolor='none', alpha=0.3)
        ax2.add_collection(collection)
        ax2.set_ylabel("Distance (m)", fontsize=18)
        ax2.set_xlim([0, x[-1]*(1./43.)])
        ax2.set_ylim([0, y_max])

        # -----

        ax4 = plt.subplot(513)
        ax4.plot(x*(1./43.), y3)
        y_max = np.amax(y3)
        collection = collections.BrokenBarHCollection.span_where(np.array(block_x_interp)*(1./43.),
                                                                 ymin=0, ymax=y_max,
                                                                 where=np.array(block_flag_interp)>0,
                                                                 facecolor='green',
                                                                 edgecolor='none', alpha=0.3)
        ax4.add_collection(collection)
        ax4.set_ylabel("Receptive Field 1", fontsize=18)
        ax4.set_xlim([0, x[-1]*(1./43.)])
        ax4.set_ylim([0, y_max])

        # -----

        ax5 = plt.subplot(514)
        ax5.plot(x*(1./43.), y4)
        y_max = np.amax(y4)
        collection = collections.BrokenBarHCollection.span_where(np.array(block_x_interp)*(1./43.),
                                                                 ymin=0, ymax=y_max,
                                                                 where=np.array(block_flag_interp)>0,
                                                                 facecolor='green',
                                                                 edgecolor='none', alpha=0.3)
        ax5.add_collection(collection)
        ax5.set_ylabel("Receptive Field 2", fontsize=18)
        ax5.set_xlim([0, x[-1]*(1./43.)])
        ax5.set_ylim([0, y_max])

        # -----

        ax3 = plt.subplot(515)
        ax3.plot(x*(1./43.), ll_likelihood, 'b', label='Log-likelihood \n from test data')
        ax3.plot(x*(1./43.), ll_likelihood_mu, 'r', label='Expected log-likelihood \n from trained model')
        ax3.plot(x*(1./43.), ll_likelihood_mu + ll_thres_mult*ll_likelihood_std, 'r--', label='Threshold')
        ## ax3.set_ylabel(r'$log P({\mathbf{X}} | {\mathbf{\theta}})$',fontsize=18)
        ax3.set_ylabel('Log-likelihood',fontsize=18)
        ax3.set_xlim([0, x[-1]*(1./43.)])

        ## ax3.legend(loc='upper left', fancybox=True, shadow=True, ncol=3, prop={'size':14})
        lgd = ax3.legend(loc='upper center', fancybox=True, shadow=True, ncol=3, bbox_to_anchor=(0.5, -0.3), \
                   prop={'size':14})
        ax3.set_xlabel('Time (sec)', fontsize=18)

        plt.subplots_adjust(bottom=0.15)
        plt.show()

        # fig.savefig('test.pdf', bbox_extra_artists=(lgd,), bbox_inches='tight')
        # fig.savefig('test.png', bbox_extra_artists=(lgd,), bbox_inches='tight')


####################################################################
# functions for paralell computation
####################################################################
        
def learn_likelihoods_progress(i, n, m, A, B, pi, F, X_train, nEmissionDim, g_mu, g_sig, nState):
    if nEmissionDim >= 2:
        ml = ghmm.HMMFromMatrices(F, ghmm.MultivariateGaussianDistribution(F), A, B, pi)
    else:
        ml = ghmm.HMMFromMatrices(F, ghmm.GaussianDistribution(F), A, B, pi)
        
    l_likelihood_mean = 0.0
    l_likelihood_mean2 = 0.0
    l_statePosterior = np.zeros(nState)

    for j in xrange(n):    

        g_post = np.zeros(nState)
        g_lhood = 0.0
        g_lhood2 = 0.0
        prop_sum = 0.0

        for k in xrange(1, m):
            final_ts_obj = ghmm.EmissionSequence(F, X_train[j][:k*nEmissionDim])
            logp = ml.loglikelihoods(final_ts_obj)[0]
            # print 'Log likelihood:', logp
            post = np.array(ml.posterior(final_ts_obj))

            k_prop = norm(loc=g_mu, scale=g_sig).pdf(k)
            g_post += post[k-1] * k_prop
            g_lhood += logp * k_prop
            g_lhood2 += logp * logp * k_prop

            prop_sum  += k_prop

        l_statePosterior += g_post / prop_sum / float(n)
        l_likelihood_mean += g_lhood / prop_sum / float(n)
        l_likelihood_mean2 += g_lhood2 / prop_sum / float(n)

    return i, l_statePosterior, l_likelihood_mean, np.sqrt(l_likelihood_mean2 - l_likelihood_mean**2)
    
