# define neuron models
import numpy as np
from scipy.optimize import bisect
from multiprocessing import Pool, cpu_count


###############################################################################
# theoretical and theoretical approximations of input, firing rate relations ##
###############################################################################
def th_lif_fi(u, tau, tref, xt):
    """Theoretical LIF tuning curve

    Calculates firing rate from input with
    f = (tref - tau*ln(1-xt/u))**-1, u >  xt
        0                          , u <= xt

    Parameters
    ----------
    u : array-like of floats
        input
    tau : float
        membrane time constant
    tref : float
        refractory period
    xt : float
        threshold
    """
    if isinstance(u, (int, float)):  # handle scalars
        u = np.array([u])
    f = np.zeros_like(u)
    idx = u > xt
    f[idx] = (tref-tau*np.log(1.-xt/u[idx]))**-1.
    return f


def taylor1_lif_fi(a, u, tau, tref, xt, clip_subxt=False):
    """First order Taylor series approximation of the LIF tuning curve

    Parameters
    ----------
    a: float
        input value around which to approximate
    u : array-like of floats
        input
    tau : float
        membrane time constant
    tref : float
        refractory period
    xt : float
        threshold
    clip_subxt : boolean (optional)
        Whether to clip negative values in the approximation to 0
    """
    assert a > xt, "a must be > xt"
    if isinstance(u, (int, float)):  # handle scalars
        u = np.array([u])
    k1 = tau*xt/((tref-tau*np.log(1-xt/a))**2*a*(a-xt))
    k0 = th_lif_fi(a, tau, tref, xt) - k1*a
    f = k0 + k1*u
    if clip_subxt:
        f[f < 0.] = 0.
    return f


def th_lif_if(f, tau, tref, xt):
    """Theoretical inverse of the LIF tuning curve

    Computes input from firing rate with
    u = xt/(1-exp((tref-1/f)/tau))
    Parameters
    ----------
    f : array-like of floats
        firing rates (must be > 0)
    tau : float
        membrane time constant
    tref : float
        refractory period
    xt : float
        threshold
    """
    if isinstance(f, (int, float)):  # handle scalars
        f = np.array([f])
    assert (f > 0.).all(), "LIF tuning curve only invertible for f>0."
    u = xt/(1-np.exp((tref-1./f)/tau))
    return u


def th_usyn_xmin(lam, tau):
    """Theoretical steady state xmin for synapse with uniform input"""
    ret = np.zeros(len(lam))
    idx = lam > 0
    ret[idx] = np.exp(-1./(lam[idx]*tau))/(tau*(1.-np.exp(-1./(lam[idx]*tau))))
    return ret


def th_usyn_xmax(lam, tau):
    """Theoretical steady state xmax for synapse with uniform input"""    
    ret = np.zeros(len(lam))
    idx = lam > 0
    ret[idx] = 1./(tau*(1.-np.exp(-1./(lam[idx]*tau))))
    return ret


###############################################################################
# numerical methods for determining input, firing rate relations ##############
###############################################################################
def _alif_u_tspk(tspk, taum, tref, xt, af, tauf):
    """Computes the input u from tspk for an adaptive LIF neuron"""
    t0 = 1./(1-np.exp(-tspk/taum))
    if taum != tauf:
        t1 = af*np.exp(-tref/tauf)*(np.exp(-tspk/tauf)-np.exp(-tspk/taum))
        t2 = (1.-np.exp(-(tref+tspk)/tauf))*(taum-tauf)
    elif taum == tauf:  # because Python doesn't know LHopital's Rule
        t1 = -af*tspk*np.exp(-(tref+tspk)/taum)
        t2 = taum**2*(1-np.exp(-(tref+tspk)/taum))
    u = t0*(xt-t1/t2)
    return u


def num_alif_fi(u, taum, tref, xt, af, tauf, min_f=.001, max_f=None,
                max_iter=100, tol=1e-3, verbose=False):
    """Numerically determine the approximate adaptive LIF neuron tuning curve

    Uses the bisection method (binary search in CS parlance) to find the
    steady state firing rate

    Parameters
    ----------
    u : array-like of floats
        input
    taum : float
        membrane time constant
    tref : float
        refractory period
    xt : float
        threshold
    af : float (optional)
        scales the inhibitory feedback
    tauf : float (optional)
        time constant of the feedback synapse
    min_f : float (optional)
        minimum firing rate to consider nonzero
    max_f : float (optional)
        maximum firing rate to seed bisection method with. Be sure that the
        maximum firing rate will indeed be within this bound otherwise the
        binary search will break
    max_iter : int (optional)
        maximium number of iterations in binary search
    tol : float (optional)
        tolerance of binary search algorithm in u. The algorithm terminates
        when maximum difference between estimated u and input u is within
        tol
    """
    if isinstance(u, (int, float)):  # handle scalars
        u = np.array([u])
    f_ret = np.zeros_like(u)
    f_high = max_f
    if max_f is None:
        f_high = 1./tref
    f_low = min_f
    tspk_high = 1./f_low - tref
    tspk_low = 1./f_high - tref

    # check for u that produces firing rates below the minimum firing rate
    u_min = _alif_u_tspk(tspk_high, taum, tref, xt, af, tauf)
    idx = u > u_min  # selects the range of u that produces spikes
    if not idx.any():
        return f_ret
    tspk_high = np.zeros_like(u[idx]) + tspk_high
    tspk_low = np.zeros_like(u[idx]) + tspk_low

    exit_msg = 'reached max iterations'
    for i in xrange(max_iter):
        assert (tspk_low <= tspk_low).all(), 'binary search failed'
        tspk = (tspk_high+tspk_low)/2.
        uhat = _alif_u_tspk(tspk, taum, tref, xt, af, tauf)
        max_diff = np.max(np.abs(u[idx]-uhat))
        if max_diff < tol:
            exit_msg = 'reached tolerance in %d iterations' % (i+1)
            break
        high_idx = uhat > u[idx]  # where our estimate of u is too high
        low_idx = uhat <= u[idx]  # where our estimate of u is too low
        tspk_high[low_idx] = tspk[low_idx]
        tspk_low[high_idx] = tspk[high_idx]
    f_ret[idx] = 1./(tref+tspk)
    if verbose:
        print exit_msg
    return f_ret


def scipy_alif_fi(u, taum, tref, xt, af, tauf, method=bisect,
                  min_f=.001, max_f=None, max_iter=100):
    """Numerically determine the approximate adaptive LIF neuron tuning curve

    Same idea as num_alif_fi but uses scipy methods instead

    Parameters
    ----------
    u : array-like of floats
        input
    taum : float
        membrane time constant
    tref : float
        refractory period
    xt : float
        threshold
    af : float (optional)
        scales the inhibitory feedback
    tauf : float (optional)
        time constant of the feedback synapse
    method : bisect or brentq (optional)
        scipy method to use
    min_f : float (optional)
        minimum firing rate to consider nonzero
    max_f : float (optional)
        maximum firing rate to seed bisection method with. Be sure that the
        maximum firing rate will indeed be within this bound otherwise the
        binary search will break
    max_iter : int (optional)
        maximium number of iterations in binary search
    tol : float (optional)
        tolerance of binary search algorithm in u. The algorithm terminates
        when maximum difference between estimated u and input u is within
        tol
    """
    f_ret = np.zeros_like(u)
    f_high = max_f
    if max_f is None:
        f_high = 1./tref
    f_low = min_f
    tspk_high = 1./f_low - tref
    tspk_low = 1./f_high - tref

    # check for u that produces firing rates below the minimum firing rate
    u_min = _alif_u_tspk(tspk_high, taum, tref, xt, af, tauf)
    idx = u > u_min  # selects the range of u that produces spikes
    if not idx.any():
        return f_ret

    def _root_wrapper(tspk, taum, tref, xt, af, tauf, u):
        return u - _alif_u_tspk(tspk, taum, tref, xt, af, tauf)

    f = np.zeros_like(u[idx])
    for i, u_val in enumerate(u[idx]):
        tspk0 = method(_root_wrapper, tspk_low, tspk_high,
                       args=(taum, tref, xt, af, tauf, u_val),
                       maxiter=max_iter)
        f[i] = 1./(tref+tspk0)
    f_ret[idx] = f
    return f_ret


def num_alif_fi_mu_apx(u, taum, tref, xt, af=1e-3, tauf=1e-2,
                       max_iter=100, rel_tol=1e-3,
                       spiking=True, verbose=False):
    """Numerically determine the approximate adaptive LIF neuron tuning curve

    The solution is approximate because this function assumes that the
    steady state feedback value is fixed at its mean (hence the _mu_apx postfix
    in the function name for mu approximation).

    Uses the bisection method (binary search in CS parlance) to find the
    steady state firing rate

    Parameters
    ----------
    u : array-like of floats
        input
    taum : float
        membrane time constant
    tref : float
        refractory period
    xt : float
        threshold
    af : float (optional)
        scales the inhibitory feedback
    tauf : float (optional)
        time constant of the feedback synapse
    max_iter : int (optional)
        maximium number of iterations in binary search
    rel_tol : float (optional)
        relative tolerance of binary search algorithm. The algorithm terminates
        when maximum, relative difference between estimated u and input u is
        within rel_tol
    spiking : bool (optional)
        If true, af is scaled to account for the refractory period.
        If false, af is used as given, which is equivalent to a rate-based
        adaptive lif neuron's behavior
    """
    assert af > 0, "inhibitory feedback scaling must be > 0"
    if spiking:
        af *= np.exp(-tref/tauf)
    if isinstance(u, (int, float)):  # handle scalars
        u = np.array([u])

    f_high = th_lif_fi(u, taum, tref, xt)
    f_ret = np.zeros_like(u)
    idx = f_high > 0.
    f_high = f_high[idx]
    f_low = np.zeros_like(f_high)
    exit_msg = 'reached max iterations'
    for i in xrange(max_iter):
        f = (f_high+f_low)/2.
        u_net = th_lif_if(f, taum, tref, xt)
        uf = f*af
        uhat = u_net + uf
        high_idx = uhat > u[idx]
        low_idx = uhat <= u[idx]
        f_high[high_idx] = f[high_idx]
        f_low[low_idx] = f[low_idx]

        max_rel_diff = np.max(np.abs(uhat-u[idx])/u[idx])
        if max_rel_diff < rel_tol:
            exit_msg = 'reached tolerance'
            break
    f_ret[idx] = f
    if verbose:
        print exit_msg
    return f_ret


def num_rate_alif_fi(*args, **kwargs):
    """Numerically determine the rate based adaptive LIF neuron tuning curve
    
    Same as num_alif_fi_mu_apx with spiking set to False
    See num_alif_fi_mu_apx for parameter descriptions
    """
    return num_alif_fi_mu_apx(*args, spiking=False, **kwargs)


###############################################################################
# empirical methods for determining input, firing rate relations ##############
###############################################################################
def sim_lif_fi(dt, u, tau, tref, xt):
    """Find the LIF tuning curve by simulating the neuron

    Parameters
    ----------
    u : array-like of floats
        input
    tau : float
        membrane time constant
    tref : float
        refractory period
    xt : float
        threshold
    """
    # theory used to set how long to simulate
    th_f = th_lif_fi(u, tau, tref, xt)
    sim_f = np.zeros_like(th_f)
    for idx, u_val in enumerate(u):
        if th_f[idx] < .01:
            # estimated firing rate too low. would require too long to simulate
            continue
        T_f = 1./th_f[idx]  # expected interspike interval
        # run long enough to collect some spikes
        run_time = 5.*T_f
        u_in = u_val+np.zeros(int(np.ceil(run_time/dt)))
        spike_times = run_lifsoma(dt, u_in, tau, tref, xt)
        isi = np.diff(spike_times[-3:])
        if (isi[-2]-isi[-1])/isi[-2] > .01:
            print('Warning (sim_lif_fi): ' +
                  'Greater than 1% change in isi between last two isi. ' +
                  'Something is wrong for u=%.2f...' % u_val)
        sim_f[idx] = 1./isi[-1]
    return sim_f


def _sim_alif_fi_worker(args):
    return _sim_alif_fi_worker_unwrapped(*args)


def _sim_alif_fi_worker_unwrapped(dt, u, taum, tref, xt, af, tauf):
    num_af = num_alif_fi(u, taum, tref, xt, af, tauf)
    if num_af < .01:
        # estimated firing rate too low. would require too long to simulate
        return 0.
    T_af = 1./num_af  # expected interspike interval
    # run long enough to reach steady state and collect some spikes
    run_time = 5.*tauf+5.*T_af
    u_in = u+np.zeros(int(np.ceil(run_time/dt)))
    spike_times = run_alifsoma(dt, u_in, taum, tref, xt, af, tauf)
    isi = np.diff(spike_times[-3:])
    assert ((isi[-2]-isi[-1])/isi[-2] < .01), (
        'sim_alif_fi: Greater than 1% change in isi between last two isi. ' +
        'Has not reached steady state for u_in=%.2f' % u)
    return 1./isi[-1]


def sim_alif_fi(dt, u, taum, tref, xt, af=1e-3, tauf=1e-2,
                max_proc=cpu_count()-1):
    """Find the adaptive LIF tuning curve by simulating the neuron

    Parameters
    ----------
    dt : float or array-like of floats
        time step. If an array, indicates dt to use with each element of u.
    u : array-like of floats
        input
    taum : float
        membrane time constant
    tref : float
        refractory period
    xt : float
        threshold
    af : float (optional)
        scales the inhibitory feedback
    tauf : float (optional)
        time constant of the feedback synapse
    max_proc : int (optional)
        max number of cores to use
    """
    if isinstance(dt, (np.ndarray, list)):
        assert len(dt) == len(u), (
            'lengths of dt and u must match when dt is an array')
        args = [(dt, u_val, taum, tref, xt, af, tauf)
                for u_val, dt in zip(u, dt)]
    else:
        args = [(dt, u_val, taum, tref, xt, af, tauf) for u_val in u]

    if (max_proc in (0, None)) or (len(u) == 1):
        sim_af = map(_sim_alif_fi_worker, args)
    else:
        workers = Pool(max_proc)
        sim_af = workers.map(_sim_alif_fi_worker, args)
        workers.close()
        workers.join()
    return np.array(sim_af)


###############################################################################
# methods for running neuron models ###########################################
###############################################################################
def run_lifsoma(dt, u, tau, tref, xt, ret_state=False, flatten1=True):
    """Simulates an LIF soma(s) given an input current

    Returns the spike times of the LIF soma

    Parameters
    ----------
    dt : float
        time step (s)
    u : array-like (m x n)
        inputs for each time step
    tau : float
        time constant (s)
    xt : float
        threshold
    ret_state : boolean (optional)
        whether to also return the soma state
    flatten1 : boolean (optional)
        whether to flatten the outputs if there is only 1 neuron
    """
    nneurons = 1
    if len(u.shape) > 1:
        nneurons = u.shape[1]
    nsteps = u.shape[0]
    if nneurons == 1:
        u.shape = u.shape[0], 1

    decay = np.exp(-dt/tau)
    increment = (1-decay)

    spiketimes = [[] for i in xrange(nneurons)]
    state = np.zeros_like(u)
    refractory_time = np.zeros(nneurons)

    for i in xrange(1, nsteps):
        # update soma state with prev state and input
        state[i, :] = decay*state[i-1, :] + increment*u[i, :]
        dV = state[i, :]-state[i-1, :]

        # update refractory period assuming no spikes for now
        refractory_time -= dt

        # set voltages of neurons still in their refractory period to 0
        # and reduce voltage of neurons partway out of their ref. period
        state[i, :] *= (1-refractory_time/dt).clip(0, 1)

        # determine which neurons spike
        spiked = state[i, :] > xt
        spiked_idx = np.nonzero(spiked)[0]

        # linearly approximate time since neuron crossed spike threshold
        overshoot = (state[i, spiked] - xt) / dV[spiked]
        interp_spiketime = dt * (1-overshoot)

        for idx, spk_t in zip(spiked_idx, interp_spiketime):
            spiketimes[idx].append(spk_t+i*dt)

        # set spiking neurons' voltages to zero, and ref. time to tref
        state[i, spiked] = 0
        refractory_time[spiked] = tref + interp_spiketime

    if nneurons == 1 and flatten1:
        spiketimes = np.array(spiketimes[0])
    else:
        for idx in xrange(nneurons):
            spiketimes[idx] = np.array(spiketimes[idx])

    if ret_state:
        retval = spiketimes, state
    else:
        retval = spiketimes
    return retval


def run_alifsoma(dt, u, taum, tref, xt, af=1e-2, tauf=1e-2,
                 ret_state=False, ret_fstate=False, flatten1=True):
    """Simulates an adaptive LIF soma(s) given an input current

    Returns the spike times of the LIF soma

    Parameters
    ----------
    dt : float
        time step (s)
    u : array-like (m x n)
        inputs for each time step
    taum : float
        soma time constant (s)
    xt : float
        threshold
    af : float (optional)
        scales the feedback synapse state into a current
    tauf : float (optional)
        time constant of the feedback synapse
    ret_state : boolean (optional)
        whether to also return the soma state
    ret_fstate : boolean (optional)
        whether to also return the feedback synapse state
    flatten1 : boolean (optional)
        whether to flatten the outputs if there is only 1 neuron
    """
    nneurons = 1
    if len(u.shape) > 1:
        nneurons = u.shape[1]
    nsteps = u.shape[0]
    if nneurons == 1:
        u.shape = u.shape[0], 1

    decay = np.expm1(-dt/taum)+1  # expm1 higher precision version of exp
    increment = (1-decay)

    fdecay = np.expm1(-dt/tauf)+1  # expm1 higher precision version of exp
    fincrement = (1-fdecay)

    spiketimes = [[] for i in xrange(nneurons)]
    state = np.zeros_like(u)
    fstate = np.zeros_like(u)
    refractory_time = np.zeros(nneurons)

    for i in xrange(1, nsteps):
        # update feedback with prev state
        fstate[i, :] = fdecay*fstate[i-1, :]

        # update soma state with prev state, input, and feedback
        state[i, :] = (decay*state[i-1, :] +
                       increment*(u[i, :] - af*fstate[i, :]))
        dV = state[i, :]-state[i-1, :]

        # update refractory period assuming no spikes for now
        refractory_time -= dt

        # set voltages of neurons still in their refractory period to 0
        # and reduce voltage of neurons partway out of their ref. period
        state[i, :] *= (1 - refractory_time / dt).clip(0, 1)

        # determine which neurons spike
        spiked = state[i, :] > xt

        # linearly approximate time since neuron crossed spike threshold
        overshoot = (state[i, spiked] - xt) / dV[spiked]
        interp_spiketime = dt * (1 - overshoot)

        # set spiking neurons' voltages to zero, and ref. time to tref
        state[i, spiked] = 0
        refractory_time[spiked] = tref + interp_spiketime

        # update feedback with current spikes
        fstate[i, :] += fincrement*spiked/dt

        # note the specific spike times
        spiked_idx = np.nonzero(spiked)[0]
        for idx, spk_t in zip(spiked_idx, interp_spiketime):
            spiketimes[idx].append(spk_t + i * dt)

    if nneurons == 1 and flatten1:
        spiketimes = np.array(spiketimes[0])
    else:
        for idx in xrange(nneurons):
            spiketimes[idx] = np.array(spiketimes[idx])

    retval = spiketimes
    if ret_state or ret_fstate:
        retval = [retval]
    if ret_state:
        retval.append(state)
    if ret_fstate:
        retval.append(fstate)
    return retval


def run_ralifsoma(dt, u_in, taum, tref, xt, af=1e-2, tauf=1e-2, f0=0.):
    """Simulates a rate-based adaptive LIF soma(s) given an input current

    Returns the rates of the rate-based adaptive LIF soma

    Parameters
    ----------
    dt : float
        time step (s)
    u_in : array-like (m x n)
        inputs for each time step
    taum : float
        soma time constant (s)
    xt : float
        threshold
    af : float (optional)
        scales the feedback synapse state into a current
    tauf : float (optional)
        time constant of the feedback synapse
    f0 : array-like (n,) (optional)
        initial firing rate; also defines the initial feedback
    """
    nneurons = 1
    if len(u_in.shape) > 1:
        nneurons = u_in.shape[1]
    nsteps = u_in.shape[0]
    if nneurons == 1:
        u_in.shape = u_in.shape[0], 1

    ufdecay = np.expm1(-dt/tauf)+1
    ufincrement = (1-ufdecay)
    f = np.zeros_like(u_in)
    uf = np.zeros_like(u_in)
    f[0, :] = f0
    idx = f[0, :] > 0
    uf[0, idx] = u_in[0, idx] - th_lif_if(f[0, idx], taum, tref, xt)
    for i in xrange(1, nsteps):
        uf[i, :] = ufdecay*uf[i-1, :] + ufincrement*af*f[i-1, :]
        f[i, :] = th_lif_fi(u_in[i, :]-uf[i, :], taum, tref, xt)

    return f, uf
