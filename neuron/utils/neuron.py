# define neuron models
import numpy as np


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
    f = np.zeros(u.shape)
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
    assert (f > 0.).all(), "LIF tuning curve only invertible for f>0."
    u = xt/(1-np.exp((tref-1./f)/tau))
    return u


###############################################################################
# numerical methods for determining input, firing rate relations ##############
###############################################################################
def num_alif_fi_mu_apx(u, tau, tref, xt, af=1e-3, tauf=1e-2, ref_fdecay=True,
                max_iter=100, rel_tol=1e-3, verbose=False):
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
    tau : float
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
        when maximum difference between estimated af and input af is within
        tol*af
    ref_fdecay : boolean (optional)
        whether the feedback decays during the refractory period. If the
        feedback decays during the refractory period, af is scaled by
        exp(-tref/tauf)
    """
    # assert af > 0, "inhibitory feedback scaling must be > 0"
    if ref_fdecay:
        af *= np.exp(-tref/tauf)
    if isinstance(u, (int, float)):  # handle scalars
        u = np.array([u])

    f_high = th_lif_fi(u, tau, tref, xt)
    f_ret = np.zeros(f_high.shape)
    idx = f_high > 0.
    f_high = f_high[idx]
    f_low = np.zeros(f_high.shape)
    tol = abs(af)*rel_tol  # set tolerance relative to af
    while True:
        f = (f_high+f_low)/2.
        u_net = th_lif_if(f, tau, tref, xt)
        u_f = u[idx] - u_net
        a = u_f/f
        high_idx = a > af
        low_idx = a <= af
        f_high[low_idx] = f[low_idx]
        f_low[high_idx] = f[high_idx]

        max_diff = np.max(np.abs(a-af))
        if max_diff < tol:
            exit_msg = 'reached tolerance'
            break
        max_iter -= 1
        if max_iter == 0:
            exit_msg = 'reached max iterations'
            break
    f_ret[idx] = f
    if verbose:
        print exit_msg
    return f_ret


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
    sim_f = np.zeros(th_f.shape)
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


def sim_alif_fi(dt, u, taum, tref, xt, af=1e-3, tauf=1e-2, ref_fdecay=True):
    """Find the adaptive LIF tuning curve by simulating the neuron

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
    ref_fdecay : boolean (optional)
        whether the feedback decays during the refractory period. If the
        feedback decays during the refractory period, af is scaled by
        exp(-tref/tauf)
    """
    # numerical estimate used to set how long to simulate
    num_af = num_alif_fi_mu_apx(u, taum, tref, xt, af, tauf, ref_fdecay)
    sim_af = np.zeros(num_af.shape)
    for idx, u_val in enumerate(u):
        if num_af[idx] < .01:
            # estimated firing rate too low. would require too long to simulate
            continue
        T_af = 1./num_af[idx]  # expected interspike interval
        # run long enough to reach steady state and collect some spikes
        run_time = 5.*tauf+5.*T_af
        u_in = u_val+np.zeros(int(np.ceil(run_time/dt)))
        spike_times = run_alifsoma(dt, u_in, taum, tref, xt, af, tauf)
        isi = np.diff(spike_times[-3:])
        if (isi[-2]-isi[-1])/isi[-2] > .01:
            print('Warning (sim_alif_fi): ' +
                  'Greater than 1% change in isi between last two isi. ' +
                  'Has not reached steady state for u_in=%.2f' % u_val)
        sim_af[idx] = 1./isi[-1]
    return sim_af


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
    state = np.zeros(u.shape)
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


def run_alifsoma(dt, u, tau, tref, xt, af=1e-2, tauf=1e-2,
                 ret_state=False, ret_fstate=False, flatten1=True):
    """Simulates an adaptive LIF soma(s) given an input current

    Returns the spike times of the LIF soma

    Parameters
    ----------
    dt : float
        time step (s)
    u : array-like (m x n)
        inputs for each time step
    tau : float
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

    decay = np.exp(-dt/tau)
    increment = (1-decay)

    fdecay = np.exp(-dt/tauf)
    fincrement = (1-fdecay)

    spiketimes = [[] for i in xrange(nneurons)]
    state = np.zeros(u.shape)
    fstate = np.zeros((u.shape[0], u.shape[1]))  # +1 for end point edge case
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
        state[i, :] *= (1-refractory_time/dt).clip(0, 1)

        # determine which neurons spike
        spiked = state[i, :] > xt
        spiked_idx = np.nonzero(spiked)[0]

        # update feedback with current spikes
        fstate[i, :] += fincrement*spiked/dt

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

    retval = spiketimes
    if ret_state or ret_fstate:
        retval = [retval]
    if ret_state:
        retval.append(state)
    if ret_fstate:
        retval.append(fstate)
    return retval
