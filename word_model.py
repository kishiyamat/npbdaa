from pyhsmm.models import WeakLimitHDPHSMM
from pyhsmm.internals.hsmm_states import HSMMStatesEigen
from pybasicbayes.distributions.poisson import Poisson
from pyhsmm.util.stats import sample_discrete
import numpy as np
from scipy.misc import logsumexp
from numba import jit

class LetterHSMMState(HSMMStatesEigen):

    def __init__(self, model, hlmstate=None, word_idx=-1, d0=-1, d1=-1, **kwargs):
        self._hlmstate = hlmstate
        self._word_idx = word_idx
        self._d0 = d0
        self._d1 = d1
        super(LetterHSMMState, self).__init__(model, **kwargs)

    @property
    def word_idx(self):
        return self._word_idx

    @jit
    def likelihood_block_word(self, word):
        T = self.T
        tsize = T
        aBl = self.aBl
        alDl = self.aDl
        len_word = len(word)
        alphal = np.ones((tsize, len_word), dtype=np.float64) * -np.inf

        if tsize-len_word+1 <= 0:
            return alphal[:, -1]

        cumsum_aBl = np.empty(tsize-len_word+1, dtype=np.float64)
        alphal[:tsize-len_word+1, 0] = np.cumsum(aBl[:tsize-len_word+1, word[0]]) + alDl[:tsize-len_word+1, word[0]]
        cache_range = range(tsize - len_word + 1)
        for j, l in enumerate(word[1:]):
            cumsum_aBl[:] = 0.0
            for t in cache_range:
                cumsum_aBl[:t+1] += aBl[t+j+1, l]
                alphal[t+j+1, j+1] = np.logaddexp.reduce(cumsum_aBl[:t+1] + alDl[t::-1, l] + alphal[j:t+j+1, j])
        return alphal[:, -1]

    def reflect_letter_stateseq(self):
        if self._hlmstate is not None:
            self._hlmstate.letter_stateseq[self._d0:self._d1] = self.stateseq

    def sample_forwards(self,betal,betastarl):
        from pyhsmm.internals.hsmm_messages_interface import sample_forwards_log
        if self.left_censoring:
            raise NotImplementedError
        caBl = np.vstack((np.zeros(betal.shape[1]), np.cumsum(self.aBl[:-1],axis=0)))
        self.stateseq = sample_forwards_log(
                self.trans_matrix, caBl, self.aDl, self.pi_0, betal, betastarl,
                np.empty(betal.shape[0],dtype='int32'))
        # assert not (0 == self.stateseq).all() #Remove this assertion.

class LetterHSMM(WeakLimitHDPHSMM):
    _states_class = LetterHSMMState

    def generate_word(self, word_size):
        nextstate_distn = self.init_state_distn.pi_0
        A = self.trans_distn.trans_matrix
        word = [-1] * word_size
        for idx in range(word_size):
            word[idx] = sample_discrete(nextstate_distn)
            nextstate_distn = A[word[idx]]
        return tuple(word)

    @property
    def params(self):
        obs_params = {"obs_distn({})".format(idx): obs_distn.params for idx, obs_distn in enumerate(self.obs_distns)}
        dur_params = {"dur_distn({})".format(idx): dur_distn.params for idx, dur_distn in enumerate(self.dur_distns)}
        bigram_params = {**self.init_state_distn.params, "trans_matrix":self.trans_distn.trans_matrix}
        return {"num_states": self.num_states, "obs_distns": obs_params, "dur_distns": dur_params, "bigram": bigram_params}

    @property
    def hypparams(self):
        obs_hypparams = {"obs_distn({})".format(idx): obs_distn.hypparams for idx, obs_distn in enumerate(self.obs_distns)}
        dur_hypparams = {"dur_distn({})".format(idx): dur_distn.hypparams for idx, dur_distn in enumerate(self.dur_distns)}
        bigram_hypparams = self.init_state_distn.hypparams
        return {"obs_distns": obs_hypparams, "dur_distns": dur_hypparams, "bigram": bigram_hypparams}
