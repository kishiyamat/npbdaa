import numpy as np

from pyhsmm.util.general import list_split
from pyhsmm.util.stats import sample_discrete
from pyhsmm.internals.transitions import WeakLimitHDPHMMTransitions
from pyhsmm.internals.initial_state import HMMInitialState

from pyhlm.internals import hlm_states
import time

class WeakLimitHDPHLMPython(object):
    _states_class = hlm_states.WeakLimitHDPHLMStatesPython

    def __init__(self, hypparams, letter_hsmm, dur_distns, length_distn):
        self._letter_hsmm = letter_hsmm
        self._length_distn = length_distn#Poisson(alpha_0=30, beta_0=10)
        self._dur_distns = dur_distns
        self._num_states = hypparams['num_states']
        self._letter_num_states = letter_hsmm.num_states
        self._init_state_distn = HMMInitialState(self, init_state_concentration=hypparams["init_state_concentration"])
        hypparams.pop("init_state_concentration")
        self._trans_distn = WeakLimitHDPHMMTransitions(**hypparams)
        self.states_list = []

        self.word_list = [None] * self.num_states
        for i in range(self.num_states):
            self._generate_word_and_set_at(i)
        self.resample_dur_distns()

    @property
    def num_states(self):
        return self._num_states

    @property
    def letter_num_states(self):
        return self._letter_num_states

    @property
    def letter_obs_distns(self):
        return self.letter_hsmm.obs_distns

    @property
    def dur_distns(self):
        return self._dur_distns

    @property
    def letter_dur_distns(self):
        return self.letter_hsmm.dur_distns

    @property
    def init_state_distn(self):
        return self._init_state_distn

    @property
    def trans_distn(self):
        return self._trans_distn

    @property
    def length_distn(self):
        return self._length_distn

    @property
    def letter_hsmm(self):
        return self._letter_hsmm

    @property
    def params(self):
        letter_hsmm_params = self.letter_hsmm.params
        bigram_params = {**self.init_state_distn.params, "trans_matrix": self.trans_distn.trans_matrix}
        length_params = self.length_distn.params
        return {"num_states": self.num_states, "word_list": self.word_list, "letter_hsmm": letter_hsmm_params, "word_length": length_params, "bigram": bigram_params}

    @property
    def hypparams(self):
        letter_hsmm_hypparams = self.letter_hsmm.hypparams
        bigram_hypparams = self.init_state_distn.hypparams
        length_hypparams = self.length_distn.hypparams
        return {"letter_hsmm": letter_hsmm_hypparams, "word_length": length_hypparams, "bigram": bigram_hypparams}

    def log_likelihood(self):
        return sum(word_state.log_likelihood() for word_state in self.states_list)

    def generate_word(self):
        size = self.length_distn.rvs() or 1
        return self.letter_hsmm.generate_word(size)

    def _generate_word_and_set_at(self, idx):
        self.word_list[idx] = None
        word = self.generate_word()
        while word in self.word_list:
            word = self.generate_word()
        self.word_list[idx] = word

    def add_data(self, data, **kwargs):
        self.states_list.append(self._states_class(self, data, **kwargs))

    def add_word_data(self, data, **kwargs):
        self.letter_hsmm.add_data(data, **kwargs)

    def resample_model(self, num_procs=0):
        times = [0.] * 4
        self.letter_hsmm.states_list = []
        [word_state.add_word_datas(generate=False) for word_state in self.states_list]
        st = time.time()
        self.letter_hsmm.resample_states(num_procs=num_procs)
        times[1] = time.time() - st
        [letter_state.reflect_letter_stateseq() for letter_state in self.letter_hsmm.states_list]
        st = time.time()
        self.resample_words()
        times[2] = time.time() - st
        st = time.time()
        self.letter_hsmm.resample_parameters()
        self.resample_length_distn()
        self.resample_dur_distns()
        self.resample_trans_distn()
        self.resample_init_state_distn()
        times[3] = time.time() - st
        st = time.time()
        self.resample_states(num_procs=num_procs)
        times[0] = time.time() - st
        self._clear_caches()

        print("Resample states:{}".format(times[0]))
        print("Resample letter states:{}".format(times[1]))
        print("SIR:{}".format(times[2]))
        print("Resample others:{}".format(times[3]))

    def resample_states(self, num_procs=0):
        if num_procs == 0:
            [word_state.resample() for word_state in self.states_list]
        else:
            self._joblib_resample_states(self.states_list, num_procs)

    def _joblib_resample_states(self,states_list,num_procs):
        from joblib import Parallel, delayed
        from . import parallel

        # warn('joblib is segfaulting on OS X only, not sure why')

        if len(states_list) > 0:
            joblib_args = list_split(
                    [self._get_joblib_pair(s) for s in states_list],
                    num_procs)

            parallel.model = self
            parallel.args = joblib_args

            raw_stateseqs = Parallel(n_jobs=num_procs,backend='multiprocessing')\
                    (delayed(parallel._get_sampled_stateseq_norep_and_durations_censored)(idx)
                            for idx in range(len(joblib_args)))

            for s, (stateseq, stateseq_norep, durations_censored, log_likelihood) in zip(
                    [s for grp in list_split(states_list,num_procs) for s in grp],
                    [seq for grp in raw_stateseqs for seq in grp]):
                s.stateseq, s._stateseq_norep, s._durations_censored, s._normalizer = stateseq, stateseq_norep, durations_censored, log_likelihood

    def _get_joblib_pair(self,states_obj):
        return (states_obj.data,states_obj._kwargs)

    def resample_words(self):
        for word_idx in range(self.num_states):
            hsmm_states = [letter_state for letter_state in self.letter_hsmm.states_list if letter_state.word_idx == word_idx]
            candidates = [tuple(letter_state.stateseq_norep) for letter_state in hsmm_states]
            unique_candidates = list(set(candidates))
            ref_array = np.array([unique_candidates.index(candi) for candi in candidates])
            if len(candidates) == 0:
                self._generate_word_and_set_at(word_idx)
                continue
            elif len(unique_candidates) == 1:
                self.word_list[word_idx] = unique_candidates[0]
                continue
            cache_score = np.empty((len(unique_candidates), len(candidates)))
            likelihoods = np.array([letter_state.log_likelihood() for letter_state in hsmm_states])
            range_tmp = list(range(len(candidates)))

            for candi_idx, candi in enumerate(unique_candidates):
                tmp = range_tmp[:]
                if (ref_array == candi_idx).sum() == 1:
                    tmp.remove(np.where(ref_array == candi_idx)[0][0])
                for tmp_idx in tmp:
                    # print(hsmm_states[tmp_idx].likelihood_block_word(candi)[-1])
                    cache_score[candi_idx, tmp_idx] = hsmm_states[tmp_idx].likelihood_block_word(candi)[-1]
            cache_scores_matrix = cache_score[ref_array]
            for i in range_tmp:
                cache_scores_matrix[i, i] = 0.0
            scores = cache_scores_matrix.sum(axis=1) + likelihoods

            assert (np.exp(scores) >= 0).all(), cache_scores_matrix
            sampled_candi_idx = sample_discrete(np.exp(scores))
            self.word_list[word_idx] = candidates[sampled_candi_idx]

        # Merge same letter seq which has different id.
        for i, word in enumerate(self.word_list):
            if word in self.word_list[:i]:
                existed_id = self.word_list[:i].index(word)
                for word_state in self.states_list:
                    stateseq, stateseq_norep = word_state.stateseq, word_state.stateseq_norep
                    word_state.stateseq[stateseq == i] = existed_id
                    word_state.stateseq_norep[stateseq_norep == i] = existed_id
                    self._generate_word_and_set_at(i)

    def resample_length_distn(self):
        self.length_distn.resample(np.array([len(word) for word in self.word_list]))

    def resample_dur_distns(self):#Do not resample!! This code only update the parameter of duration distribution of word.
        letter_lmbdas = np.array([letter_dur_distn.lmbda for letter_dur_distn in self.letter_dur_distns])
        for word, dur_distn in zip(self.word_list, self.dur_distns):
            dur_distn.lmbda = np.sum(letter_lmbdas[list(word)])

    def resample_trans_distn(self):
        self.trans_distn.resample([word_state.stateseq_norep for word_state in self.states_list])

    def resample_init_state_distn(self):
        self.init_state_distn.resample(np.array([word_state.stateseq_norep[0] for word_state in self.states_list]))

    def _clear_caches(self):
        for word_state in self.states_list:
            word_state.clear_caches()

class WeakLimitHDPHLM(WeakLimitHDPHLMPython):
    _states_class = hlm_states.WeakLimitHDPHLMStates