import numpy as np
from scipy.special import binom, poch, factorial
from sklearn.base import TransformerMixin, BaseEstimator
from sklearn.utils import check_array
from scipy.signal import fftconvolve
from .utils import (nm2j, j2nm, nm2j_complex, grid_rt)

from scipy.linalg import norm
from sklearn.preprocessing import normalize



#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
# Zernike (ZPs)
#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
def zp_norm(n, m):
    '''
    Given a pair of (n, m), this function returns the normalization factor for Zernike Polynomials.
    :param n: array-like, an array of indices n
    :param m: array-like, an array of indices m, m and n should have the same length.
    :return: array-like, the normalization factors for Zernike Polynomial
    '''
    n = np.atleast_1d(n)
    m = np.atleast_1d(m)
    mask = (m == 0)
    # don't use np.zeros_like(n) as n.dtype is np.int
    norm = np.zeros(len(n))
    norm[mask] = np.sqrt(n[mask] + 1)
    norm[~mask] = np.sqrt(2 * n[~mask] + 2)
    return norm


def zp_get_coeffs(n, m, normalize=True):
    N = np.atleast_1d(n)
    M = np.atleast_1d(m)
    n_max = N.max()
    M_abs = np.abs(M)
    assert (((N - M_abs) % 2 == 0).all())
    l = []
    for (n, m) in zip(N, M_abs):
        num = (n - m) // 2
        c = np.r_[
            [0] * (n_max - n), [np.power(-1, k) * binom(n - k, k) * binom(n - 2 * k, num - k) if i % 2 == 0 else 0 for
                                i, k in enumerate(np.arange(0, n + 1) // 2)]]
        l.append(c)
    c_matrix = np.array(l)
    if normalize:
        c_matrix = c_matrix * (zp_norm(N, M)[:, np.newaxis])
    return c_matrix


# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
# Generalized Pseudo Zernike (GPZPs)
# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def gpzp_norm(n, m, alpha=0):
    n = np.atleast_1d(n)
    m = np.atleast_1d(m)
    m_abs = np.abs(m)

    m_abs = np.abs(m)
    a = n + m_abs
    b = n - m_abs
    mask = (m == 0)
    norm = np.zeros(len(n))
    norm[mask] = (np.sqrt((n + alpha / 2 + 1) * poch(b + alpha + 1, 2 * m_abs + 1) / (poch(b + 1, 2 * m_abs + 1))))[
        mask]
    norm[~mask] = (np.sqrt((2 * n + alpha + 2) * poch(b + alpha + 1, 2 * m_abs + 1) / (poch(b + 1, 2 * m_abs + 1))))[
        ~mask]
    return norm


def gpzp_get_coeffs(n, m, alpha=0, normalize=True):
    N = np.atleast_1d(n)
    M = np.atleast_1d(m)
    M_abs = np.abs(M)
    n_max = N.max()

    A = N + M_abs
    B = N - M_abs
    C = factorial(A + 1) / poch(alpha + 1, A + 1)

    l = []
    for i in range(len(N)):
        a, b, c, n = A[i], B[i], C[i], N[i]
        coeffs = [
            c * (-1) ** k * poch(alpha + 1, 2 * n + 1 - k) / (factorial(k) * factorial(a + 1 - k) * factorial(b - k))
            for k in np.arange(0, b + 1)]
        coeffs = [0] * (n_max - n) + coeffs + [0] * (n - b)
        l.append(coeffs)
    c_matrix = np.array(l)
    if normalize:
        c_matrix = c_matrix * (gpzp_norm(N, M, alpha=alpha)[:, np.newaxis])
    return c_matrix


# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
#  Shared
# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=


def get_Rn_matrix(n, size, alpha=None):
    n = np.atleast_1d(n)
    n_max = n.max()

    r, t = grid_rt(size)
    disk_array = (r > 0) * 1.
    disk_array[size // 2, size // 2] = 1.

    if alpha is None:
        w = 1.
    else:
        w = (1 - r) ** (alpha / 2) * disk_array
    # shape of Rn_matrix is (n_max+1, size*size)
    Rn_matrix = np.array([np.power(r, i) * w for i in np.arange(1, n_max + 1)[::-1]] + [disk_array * w])
    return Rn_matrix.reshape(n_max + 1, -1)


def get_mt_matrix(m, size):
    m = np.atleast_1d(m)

    t = grid_rt(size)[1].ravel()
    f = np.array([np.sin, np.cos])
    mask = (m >= 0) * 1
    funcs = f[mask]
    return np.array([func(e * t) for e, func in zip(np.abs(m), funcs)])


def generate_data_from_nm(n, m, size, alpha=None, reshape=True):
    Rn_matrix = get_Rn_matrix(n, size, alpha=alpha)
    mt_matrix = get_mt_matrix(m, size)

    if alpha is None:
        c_matrix = zp_get_coeffs(n, m)
    else:
        c_matrix = gpzp_get_coeffs(n, m, alpha)

    Rnm_ = c_matrix.dot(Rn_matrix)

    if reshape:
        return (Rnm_ * mt_matrix).reshape((c_matrix.shape[0], size, size))
    else:
        return (Rnm_ * mt_matrix)


def _get_m_states(m, states=None):
    if not np.iterable(states):
        if states is None:
            states = list(set(np.abs(m)))
        elif states < 0:  # states is negative number
            uniq = np.unique(np.abs(m))
            states = uniq[np.nonzero(uniq)]
        else:
            states = [states]
    else:
        states = np.unique(np.abs(states))
    return states


class ZPs(TransformerMixin, BaseEstimator):

    def __init__(self, n_max, size, alpha=None, states=None):
        self.n_max = n_max
        self.size = size
        self.alpha = alpha
        self.states = states

        self.j_max = nm2j(n_max, n_max, self.alpha)
        nm = j2nm(np.arange(self.j_max + 1), self.alpha)
        self.n, self.m = nm[:, 0], nm[:, 1]

        states = _get_m_states(self.m, states)
        ind = np.where(np.in1d(np.abs(self.m), states))[0]
        self.n = self.n[ind]
        self.m = self.m[ind]

        self.n_components_ = len(self.n)
        self.data = generate_data_from_nm(self.n, self.m, size, self.alpha)
        self.moments = None

    def fit(self, X, y=None, method='matrix'):
        """
        Fit the model using X as training data

        Parameters
        ----------
        X: array_like
            Training image data. If array or matrix, shape [n_samples, image_height, image_width]
        y : None
            Ignored variable.
        Returns
        -------
        self : object
            Returns the instance itself.
        """
        X = check_array(X, allow_nd=True)
        if len(X.shape) == 2:
            if X.shape[0] == self.data.shape[1]:
                X = X[np.newaxis, :]
                method = method
            elif X.shape[0] > self.data.shape[1]:
                shape = (self.n_components_, X.shape[0], X.shape[1])
                X = np.broadcast_to(X, shape)
                method = 'fftconv'

        self.n_samples_, self.n_features_ = X.shape[0], np.prod(X.shape[1:])

        if method == 'matrix':
            X = X.reshape(X.shape[0], -1)
            N = self.data.shape[0]
            data_ = self.data.reshape(N, -1)
            # self.moments = zmarray(X.dot(np.linalg.pinv(data_)), self.n, self.m)
            # linear regression method
            moments = np.linalg.inv(data_.dot(data_.T)).dot(data_).dot(X.T)
            self.moments = zmarray(moments.T, self.n, self.m, self.alpha)

        # this is very slow, here for validation
        elif method == 'direct':
            zps = self.data
            s = X.shape[1]
            num_zps = len(self.n)
            moments = np.array([(p * zp).sum() for p in X for zp in zps]).reshape((self.n_samples_, num_zps))
            moments = moments / (s * s / 4) / np.pi
            self.moments = zmarray(moments, self.n, self.m, self.alpha)

        elif method == 'transpose':
            X = X.reshape(X.shape[0], -1)
            N = self.data.shape[0]
            data_ = self.data.reshape(N, -1)
            d = np.sqrt(X.shape[1]).astype(int)
            area = np.pi * d * d / 4
            moments = X.dot(data_.T) / area
            self.moments = zmarray(moments, self.n, self.m, self.alpha)

        elif method == 'pseudo':
            X = X.reshape(X.shape[0], -1)
            N = self.data.shape[0]
            data_ = self.data.reshape(N, -1)
            self.moments = zmarray(X.dot(np.linalg.pinv(data_)), self.n, self.m, self.alpha)

        elif method == 'fftconv':
            self.moments = fftconvolve(X, self.data, mode='same', axes=[1, 2])
            f = 1 - self.n % 2
            f[f == 0] = -1
            area = np.pi * (self.data.shape[1]) ** 2 / 4
            self.moments = self.moments * f[:, np.newaxis, np.newaxis] / area
            self.moments = zmarray(self.moments.reshape(len(self.m), -1).T, self.n, self.m, self.alpha)

        return self

    def fit_transform(self, X, y=None):
        """
        Fit the model with X and apply the Zernike dimensionality reduction on X

        Parameters
        ----------
        X: array_like
            Training image data. If array or matrix, shape [n_samples, image_height, image_width]
        y : None
            Ignored variable.

        Returns
        -------
        X_new : array-like, shape (n_samples, n_components)
            Transformed values.
        """
        self.fit(X)
        X_new = self.moments
        if X_new.shape[0] == 1:
            X_new = X_new[0]
        return X_new


# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
#  Zernike moments
# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=


def construct_complex_matrix(n, m, alpha=None):
    j1 = nm2j(n, m, alpha)
    j2 = nm2j_complex(n, np.abs(m), alpha)

    # j2 has duplicate elements
    uniq_j2 = np.unique(j2)

    num_rows, num_cols = len(uniq_j2), len(j1)
    vals = np.zeros(len(j1), dtype=complex)
    vals[m >= 0] = 1
    vals[m < 0] = 1j

    d = dict(zip(uniq_j2, range(num_rows)))

    c_matrix = np.zeros(shape=(num_rows, num_cols), dtype=complex)
    for i, (ind, v) in enumerate(zip(j2, vals)):
        c_matrix[d[ind], i] = v
    return c_matrix


def construct_rot_matrix(n, m, theta, alpha=None):
    theta = np.deg2rad(theta)
    rot_matrix = np.zeros(shape=(len(n), len(n)))
    for i, (en, em) in enumerate(zip(n, m)):
        if em == 0:
            rot_matrix[i, nm2j(en, em, alpha)] = 1.
        elif em < 0:
            # DON'T forget to multiply m
            t = theta * (-em)
            rot_matrix[i, nm2j(en, em, alpha)] = np.cos(t)
            rot_matrix[i, nm2j(en, -em, alpha)] = -np.sin(t)
        else:
            t = theta * em
            rot_matrix[i, nm2j(en, em, alpha)] = np.cos(t)
            rot_matrix[i, nm2j(en, -em, alpha)] = np.sin(t)
    return rot_matrix


# construct reflection matrix
def construct_ref_matrix(n, m, theta, alpha=None):
    theta = 2 * np.deg2rad(theta)
    ref_matrix = np.zeros(shape=(len(n), len(n)))
    for i, (en, em) in enumerate(zip(n, m)):
        if em == 0:
            ref_matrix[i, nm2j(en, em, alpha=alpha)] = 1.
        elif em < 0:
            # DON'T forget to multiply m
            t = theta * (-em)
            ref_matrix[i, nm2j(en, em, alpha=alpha)] = -np.cos(t)
            ref_matrix[i, nm2j(en, -em, alpha=alpha)] = -np.sin(t)
        else:
            t = theta * em
            ref_matrix[i, nm2j(en, em, alpha=alpha)] = np.cos(t)
            ref_matrix[i, nm2j(en, -em, alpha=alpha)] = -np.sin(t)
    return ref_matrix


class zmarray(np.ndarray):

    def __new__(cls, input_array, n=None, m=None, alpha=None):
        # Input array is an already formed ndarray instance
        # We first cast to be our class type
        obj = np.asarray(input_array).view(cls)
        obj.N = input_array.shape[1]
        obj.alpha = alpha
        if n is None:
            obj.n = j2nm(range(obj.N), obj.alpha)[:, 0]
        else:
            obj.n = n
        if m is None:
            obj.m = j2nm(range(obj.N), obj.alpha)[:, 1]
        else:
            obj.m = m
        return obj

    def select(self, states=None):
        states = _get_m_states(self.m, states)
        ind = np.where(np.in1d(np.abs(self.m), states))[0]
        return zmarray(self[:, ind], n=self.n[ind], m=self.m[ind], alpha=self.alpha)

    def complex(self):
        if self.dtype != complex:
            c_matrix = construct_complex_matrix(self.n, self.m, self.alpha)
            zm_complex = c_matrix.dot(self.T).T
            # update n and m
            c_matrix[c_matrix == 1j] = 0
            m = c_matrix.dot(np.abs(self.m)).real.astype(int)
            n = c_matrix.dot(np.abs(self.n)).real.astype(int)
            return zmarray(zm_complex, n, m, alpha=self.alpha)
        else:
            return self

    def rotinv(self):
        zm_complex = self.complex()
        mask = (zm_complex.m == 0)
        zm_complex[:, ~mask] = np.abs(zm_complex[:, ~mask])
        zm_rotinv = zm_complex.real
        return zmarray(zm_rotinv, zm_complex.n, zm_complex.m, alpha=self.alpha)

    def rot(self, theta):
        rot_matrix = construct_rot_matrix(self.n, self.m, theta)
        zm_rot = rot_matrix.dot(self.T).T
        return zmarray(zm_rot, self.n, self.m, alpha=self.alpha)

    def ref(self, theta):
        ref_matrix = construct_ref_matrix(self.n, self.m, theta)
        zm_rot = ref_matrix.dot(self.T).T
        return zmarray(zm_rot, self.n, self.m, alpha=self.alpha)

    def maps(self, n_fold, reshape=True):
        a = construct_rot_weight_matrix(n_fold, self.m)
        t = self.copy()
        # abs(m) = 0, 1 components contribute too much to similarity, make then all zeros
        t[:, np.abs(self.m) == 0] = 0
        t[:, np.abs(self.m) == 1] = 0
        nn = norm(t, axis=1)
        t2 = (t / nn[:, np.newaxis]) ** 2
        ss = t2.dot(a)[:, 0]

        size = np.sqrt(ss.shape[0])
        if reshape and size.is_integer():
            ss = ss.reshape(int(size), int(size))
        return ss

    def rot_curve(self, thetas):
        if thetas is None:
            thetas = np.linspace(0, 2 * np.pi, 360)

        # make a copy of Zernike moments
        t = self.copy()
        t[:, np.abs(self.m) == 0] = 0
        t[:, np.abs(self.m) == 1] = 0
        nn = norm(t, axis=1)
        t2 = (t / nn[:, np.newaxis]) ** 2

        ms = np.abs(self.m)
        cosmt = np.array([np.cos(m * t) for m in ms for t in thetas]).reshape(len(ms), -1)
        tt = t2.dot(cosmt)
        return tt

    def reflect_curve(self, thetas=None):
        if thetas is None:
            thetas = np.linspace(0, 2 * np.pi, 360)
        # make a copy of Zernike moments
        t = self.copy()
        # remove m = 0 terms and normalize
        nn = t.select(-1).normalize()
        a = nn.complex().real
        b = nn.complex().imag
        coeffs1 = a**2 - b**2
        coeffs2 = 2*a*b
        coeffs = np.hstack([coeffs1, coeffs2])
        ms = nn.complex().m

        sinmt = np.array([np.sin(m * t) for m in ms for t in thetas]).reshape(len(ms), -1)
        cosmt = np.array([np.cos(m * t) for m in ms for t in thetas]).reshape(len(ms), -1)
        cos_sinmt = np.vstack([cosmt, sinmt])
        tt = coeffs.dot(cos_sinmt)
        return tt

    def reflect_map(self, thetas=None, reshape=True):
        if thetas is None:
            thetas = np.linspace(0, 2 * np.pi, 361)[0:360]
        tt = self.reflect_curve(thetas)
        symm_map = tt.max(axis=1)
        size = np.sqrt(symm_map.shape[0])
        if reshape and size.is_integer():
            symm_map = symm_map.reshape(int(size), int(size))
        return symm_map

    def normalize(self, norm='l2'):
        if self.dtype != np.complex:
            return zmarray(normalize(self, axis=1, norm=norm), self.n, self.m)
        else:
            return self

    def reconstruct(self, zps_data):
        """
        .. todo::
            need modification
        """
        data_ = zps_data.reshape(zps_data.shape[0], -1)
        shape = (self.shape[0], zps_data.shape[1], zps_data.shape[2])
        return self.dot(data_).reshape(shape)

    def __array_finalize__(self, obj):
        if obj is None: return
        self.n = getattr(obj, 'n', None)
        self.m = getattr(obj, 'm', None)
        self.alpha = getattr(obj, 'alpha', None)

def construct_rot_weight_matrix(n_fold, m):
    assert(n_fold != 1)
    a = np.zeros(len(m))
    for n in np.arange(1, n_fold):
        a += np.cos(np.abs(m) * 2 * np.pi / n_fold * n)
    a = a / (n_fold - 1)
    return a[:, np.newaxis]



# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
# functional form
# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def n_components_to_nmax(n_components, alpha=None):
    n, m = j2nm(n_components-1, alpha)[0]
    return n

def ps_zps(ps, n_components=66):
    n_max = n_components_to_nmax(n_components)
    zps = ZPs(n_max=n_max, size=ps.shape[1])
    zps.fit(ps)
    X = zps.moments[:, 0:n_components]
    return X

def ps_pzp(ps, n_components=66, alpha=0):
    n_max = n_components_to_nmax(n_components, alpha=alpha)
    zps = ZPs(n_max=n_max, size=ps.shape[1], alpha=alpha)
    zps.fit(ps)
    X = zps.moments[:, 0:n_components]
    return X

# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
# Testing
# =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

# test coeffs

# test ortho

# test rotinv

# test symm

