"""
Vine Copulas for High-Dimensional Dependency Modeling.

For d>5 contracts, bivariate copulas are insufficient. Vine copulas decompose
the d-dimensional dependency into d*(d-1)/2 bivariate conditional copulas
arranged in a tree structure.

Types:
- C-vine (star): One central event drives everything
  (e.g., presidential winner -> all policy markets)
- D-vine (path): Sequential dependencies
  (e.g., primary results flow into general election)

Construction:
1. Build maximum spanning trees ordered by |tau_Kendall|
2. Select pair-copula families via AIC
3. Estimate parameters sequentially

Sklar's Theorem:
    F(x_1,...,x_d) = C(F_1(x_1),...,F_d(x_d))
    where C is the copula and F_i are marginal CDFs.

References:
- Aas et al. (2009): "Pair-copula constructions of multiple dependence"
- Bedford & Cooke (2002): "Vines - A New Graphical Model for Dependent Random Variables"
- Joe (2014): "Dependence Modeling with Copulas"
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import norm, t as t_dist, kendalltau

logger = logging.getLogger(__name__)


@dataclass
class PairCopulaFit:
    """Result of fitting a bivariate copula."""
    family: str           # "gaussian", "t", "clayton", "gumbel", "frank"
    parameter: float      # Copula parameter (rho for gaussian/t, theta for archimedean)
    dof: Optional[float]  # Degrees of freedom (t-copula only)
    tau: float            # Kendall's tau
    aic: float
    variables: Tuple[int, int]
    conditioning: Tuple[int, ...]  # Conditioning variables (empty for first tree)


class PairCopula:
    """
    Bivariate copula building block for vine constructions.

    Supported families:
    - Gaussian: C(u,v; rho) - no tail dependence
    - Student-t: C(u,v; rho, nu) - symmetric tail dependence
    - Clayton: C(u,v; theta) - lower tail dependence
    - Gumbel: C(u,v; theta) - upper tail dependence
    - Frank: C(u,v; theta) - no tail dependence, symmetric
    """

    @staticmethod
    def gaussian_sample(u: np.ndarray, rho: float, rng: np.random.Generator) -> np.ndarray:
        """Sample v|u from Gaussian copula C(u,v; rho)."""
        x = norm.ppf(u)
        z = rng.standard_normal(len(u))
        y = rho * x + math.sqrt(1 - rho ** 2) * z
        return norm.cdf(y)

    @staticmethod
    def t_sample(u: np.ndarray, rho: float, nu: float, rng: np.random.Generator) -> np.ndarray:
        """Sample v|u from Student-t copula."""
        x = t_dist.ppf(u, nu)
        z = rng.standard_normal(len(u))
        s = rng.chisquare(nu, len(u)) / nu
        y = rho * x + math.sqrt(1 - rho ** 2) * z
        y = y / np.sqrt(s)  # Scale to t-distribution
        return t_dist.cdf(y, nu)

    @staticmethod
    def clayton_sample(u: np.ndarray, theta: float, rng: np.random.Generator) -> np.ndarray:
        """Sample v|u from Clayton copula (lower tail dependence)."""
        if theta < 1e-6:
            return rng.uniform(0, 1, len(u))
        # Conditional approach
        w = rng.uniform(0, 1, len(u))
        v = u * (w ** (-theta / (1 + theta)) - 1 + u ** theta) ** (-1 / theta)
        return np.clip(v, 1e-6, 1 - 1e-6)

    @staticmethod
    def gumbel_sample(u: np.ndarray, theta: float, rng: np.random.Generator) -> np.ndarray:
        """Sample v|u from Gumbel copula (upper tail dependence)."""
        if theta < 1.0 + 1e-6:
            return rng.uniform(0, 1, len(u))
        # Marshall-Olkin algorithm via stable distribution
        alpha = 1.0 / theta
        # Approximate: use uniform mixing
        w = rng.uniform(0, 1, len(u))
        # Simplified conditional sampling
        log_u = -(-np.log(np.clip(u, 1e-10, 1 - 1e-10))) ** theta
        log_v = log_u * (w ** (1 / theta))
        v = np.exp(-(-log_v) ** (1 / theta))
        return np.clip(v, 1e-6, 1 - 1e-6)

    @staticmethod
    def frank_sample(u: np.ndarray, theta: float, rng: np.random.Generator) -> np.ndarray:
        """Sample v|u from Frank copula (no tail dependence)."""
        if abs(theta) < 1e-6:
            return rng.uniform(0, 1, len(u))
        w = rng.uniform(0, 1, len(u))
        v = -np.log(1 + w * (np.exp(-theta) - 1) / (
            np.exp(-theta * u) * (1 - w) + w
        )) / theta
        return np.clip(v, 1e-6, 1 - 1e-6)

    @staticmethod
    def fit(u: np.ndarray, v: np.ndarray) -> PairCopulaFit:
        """
        Select best bivariate copula family via AIC.

        Tests Gaussian, Student-t, Clayton, and Frank.
        Returns the best-fitting copula with estimated parameters.
        """
        tau, _ = kendalltau(u, v)
        n = len(u)
        best_aic = float("inf")
        best_fit = None

        # Gaussian: rho = sin(pi * tau / 2)
        rho_g = math.sin(math.pi * tau / 2)
        rho_g = max(-0.99, min(0.99, rho_g))
        x, y = norm.ppf(np.clip(u, 1e-6, 1 - 1e-6)), norm.ppf(np.clip(v, 1e-6, 1 - 1e-6))
        ll_g = np.sum(
            -0.5 * math.log(1 - rho_g ** 2)
            - (rho_g ** 2 * (x ** 2 + y ** 2) - 2 * rho_g * x * y)
            / (2 * (1 - rho_g ** 2))
        )
        aic_g = -2 * ll_g + 2 * 1  # 1 parameter
        if aic_g < best_aic:
            best_aic = aic_g
            best_fit = PairCopulaFit(
                family="gaussian", parameter=rho_g, dof=None,
                tau=tau, aic=aic_g, variables=(0, 0), conditioning=(),
            )

        # Student-t: same rho, fit nu by profile likelihood
        for nu in [3, 4, 5, 8, 12, 20]:
            xt = t_dist.ppf(np.clip(u, 1e-6, 1 - 1e-6), nu)
            yt = t_dist.ppf(np.clip(v, 1e-6, 1 - 1e-6), nu)
            rho_t = max(-0.99, min(0.99, rho_g))
            R = np.array([[1, rho_t], [rho_t, 1]])
            try:
                R_inv = np.linalg.inv(R)
                det_R = np.linalg.det(R)
                if det_R <= 0:
                    continue
                # t-copula log-likelihood
                xy = np.column_stack([xt, yt])
                quad = np.sum(xy * (xy @ R_inv), axis=1)
                ll_t = np.sum(
                    math.lgamma((nu + 2) / 2) - math.lgamma(nu / 2)
                    - math.log(math.pi * nu) - 0.5 * math.log(det_R)
                    - ((nu + 2) / 2) * np.log(1 + quad / nu)
                    - 2 * t_dist.logpdf(xt, nu)  # Subtract marginals
                )
                aic_t = -2 * ll_t + 2 * 2
                if aic_t < best_aic:
                    best_aic = aic_t
                    best_fit = PairCopulaFit(
                        family="t", parameter=rho_t, dof=float(nu),
                        tau=tau, aic=aic_t, variables=(0, 0), conditioning=(),
                    )
            except np.linalg.LinAlgError:
                continue

        # Frank: theta = tau-to-frank mapping (approximate)
        if abs(tau) > 0.01:
            theta_f = 2.0 * tau / (1.0 - abs(tau)) * math.copysign(1, tau)
            theta_f = max(-30, min(30, theta_f))
            # Simplified Frank log-likelihood
            try:
                et = np.exp(-theta_f)
                etu = np.exp(-theta_f * u)
                etv = np.exp(-theta_f * v)
                etuv = np.exp(-theta_f * (u + v))
                num = -theta_f * (1 - et) * etuv
                den = ((1 - et) - (1 - etu) * (1 - etv)) ** 2
                ll_f = np.sum(np.log(np.maximum(np.abs(num / den), 1e-20)))
                aic_f = -2 * ll_f + 2 * 1
                if aic_f < best_aic:
                    best_aic = aic_f
                    best_fit = PairCopulaFit(
                        family="frank", parameter=theta_f, dof=None,
                        tau=tau, aic=aic_f, variables=(0, 0), conditioning=(),
                    )
            except (FloatingPointError, ZeroDivisionError, ValueError):
                pass

        if best_fit is None:
            best_fit = PairCopulaFit(
                family="gaussian", parameter=rho_g, dof=None,
                tau=tau, aic=aic_g, variables=(0, 0), conditioning=(),
            )

        return best_fit

    @staticmethod
    def sample(family: str, param: float, n: int, rng: np.random.Generator,
               dof: Optional[float] = None) -> Tuple[np.ndarray, np.ndarray]:
        """Sample (u, v) from a bivariate copula."""
        u = rng.uniform(0, 1, n)
        if family == "gaussian":
            v = PairCopula.gaussian_sample(u, param, rng)
        elif family == "t":
            v = PairCopula.t_sample(u, param, dof or 4.0, rng)
        elif family == "clayton":
            v = PairCopula.clayton_sample(u, max(param, 0.01), rng)
        elif family == "gumbel":
            v = PairCopula.gumbel_sample(u, max(param, 1.01), rng)
        elif family == "frank":
            v = PairCopula.frank_sample(u, param, rng)
        else:
            v = rng.uniform(0, 1, n)
        return u, v


class CVine:
    """
    C-vine (Canonical vine) copula.

    Star structure: one central variable is connected to all others.
    Use when one event drives all others (e.g., presidential election outcome
    drives all policy market prices).

    Tree structure:
        Tree 1: (1,2), (1,3), (1,4), ..., (1,d)
        Tree 2: (2,3|1), (2,4|1), ..., (2,d|1)
        Tree k: (k, k+1|1,...,k-1), ..., (k, d|1,...,k-1)
    """

    def __init__(self, d: int, seed: Optional[int] = None):
        self.d = d
        self.rng = np.random.default_rng(seed)
        self.pair_copulas: Dict[Tuple, PairCopulaFit] = {}
        self._fitted = False

    def fit(self, data: np.ndarray, order: Optional[List[int]] = None):
        """
        Fit C-vine to data.

        Args:
            data: (n_samples, d) array of uniform marginals (use probability integral transform)
            order: Variable ordering (first = central node). If None, selected by max sum |tau|.
        """
        n, d = data.shape
        assert d == self.d

        if order is None:
            # Select ordering by max sum of absolute Kendall's tau
            tau_sums = []
            for i in range(d):
                tau_sum = sum(
                    abs(kendalltau(data[:, i], data[:, j])[0])
                    for j in range(d) if j != i
                )
                tau_sums.append(tau_sum)
            order = list(np.argsort(tau_sums)[::-1])

        self._order = order
        reordered = data[:, order]

        # h-functions (conditional CDFs) for building higher trees
        h_values = {}

        # Tree 1: bivariate copulas (order[0], order[j])
        for j in range(1, d):
            u = reordered[:, 0]
            v = reordered[:, j]
            fit = PairCopula.fit(u, v)
            fit.variables = (order[0], order[j])
            fit.conditioning = ()
            self.pair_copulas[(0, j, ())] = fit

            # Compute h-functions for next tree
            h_values[(0, j)] = self._h_function(u, v, fit)
            h_values[(j, 0)] = self._h_function(v, u, fit)

        # Trees 2, ..., d-1
        for tree in range(1, d - 1):
            for j in range(tree + 1, d):
                u = h_values.get((tree, tree - 1), reordered[:, tree])
                v = h_values.get((j, tree - 1), reordered[:, j])

                # Use pseudo-observations from previous tree
                u_key = (tree,) + tuple(range(tree))
                v_key = (j,) + tuple(range(tree))

                fit = PairCopula.fit(
                    np.clip(u, 1e-6, 1 - 1e-6),
                    np.clip(v, 1e-6, 1 - 1e-6),
                )
                fit.variables = (order[tree], order[j])
                fit.conditioning = tuple(order[k] for k in range(tree))
                conditioning_key = tuple(range(tree))
                self.pair_copulas[(tree, j, conditioning_key)] = fit

                # h-functions for next tree
                h_values[(tree, j)] = self._h_function(u, v, fit)
                h_values[(j, tree)] = self._h_function(v, u, fit)

        self._fitted = True

    def sample(self, n: int) -> np.ndarray:
        """Sample from the fitted C-vine copula. Returns (n, d) uniform marginals."""
        if not self._fitted:
            raise RuntimeError("Call fit() first")

        d = self.d
        w = self.rng.uniform(0, 1, (n, d))  # Independent uniforms
        v = np.zeros((n, d))

        # First variable: direct
        v[:, 0] = w[:, 0]

        for j in range(1, d):
            v_j = w[:, j]
            # Invert h-functions from tree j-1 down to tree 0
            for k in range(j - 1, -1, -1):
                conditioning = tuple(range(k))
                key = (k, j, conditioning)
                if key in self.pair_copulas:
                    fit = self.pair_copulas[key]
                    v_j = self._h_inverse(v[:, k], v_j, fit)
            v[:, j] = v_j

        # Reorder back to original variable ordering
        result = np.zeros_like(v)
        for i, orig_idx in enumerate(self._order):
            result[:, orig_idx] = v[:, i]

        return np.clip(result, 1e-6, 1 - 1e-6)

    def _h_function(self, u: np.ndarray, v: np.ndarray, fit: PairCopulaFit) -> np.ndarray:
        """Conditional CDF: h(v|u) = dC(u,v)/du / f(u)."""
        if fit.family == "gaussian":
            rho = fit.parameter
            x = norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))
            y = norm.ppf(np.clip(v, 1e-6, 1 - 1e-6))
            return norm.cdf((y - rho * x) / math.sqrt(max(1 - rho ** 2, 1e-8)))
        elif fit.family == "t":
            rho = fit.parameter
            nu = fit.dof or 4.0
            x = t_dist.ppf(np.clip(u, 1e-6, 1 - 1e-6), nu)
            y = t_dist.ppf(np.clip(v, 1e-6, 1 - 1e-6), nu)
            denom = np.sqrt(np.maximum((1 - rho ** 2) * (nu + x ** 2) / (nu + 1), 1e-8))
            return t_dist.cdf((y - rho * x) / denom, nu + 1)
        else:
            # Fallback: Gaussian approximation
            rho = math.sin(math.pi * fit.tau / 2)
            rho = max(-0.99, min(0.99, rho))
            x = norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))
            y = norm.ppf(np.clip(v, 1e-6, 1 - 1e-6))
            return norm.cdf((y - rho * x) / math.sqrt(max(1 - rho ** 2, 1e-8)))

    def _h_inverse(self, u: np.ndarray, w: np.ndarray, fit: PairCopulaFit) -> np.ndarray:
        """Inverse h-function: find v such that h(v|u) = w."""
        if fit.family == "gaussian":
            rho = fit.parameter
            x = norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))
            z = norm.ppf(np.clip(w, 1e-6, 1 - 1e-6))
            y = rho * x + math.sqrt(max(1 - rho ** 2, 1e-8)) * z
            return norm.cdf(y)
        elif fit.family == "t":
            rho = fit.parameter
            nu = fit.dof or 4.0
            x = t_dist.ppf(np.clip(u, 1e-6, 1 - 1e-6), nu)
            z = t_dist.ppf(np.clip(w, 1e-6, 1 - 1e-6), nu + 1)
            y = rho * x + z * np.sqrt((1 - rho ** 2) * (nu + x ** 2) / (nu + 1))
            return t_dist.cdf(y, nu)
        else:
            rho = math.sin(math.pi * fit.tau / 2)
            rho = max(-0.99, min(0.99, rho))
            x = norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))
            z = norm.ppf(np.clip(w, 1e-6, 1 - 1e-6))
            y = rho * x + math.sqrt(max(1 - rho ** 2, 1e-8)) * z
            return norm.cdf(y)


class DVine:
    """
    D-vine (Drawable vine) copula.

    Path structure: sequential pairwise dependencies.
    Use when events have a natural ordering (e.g., sequential primary states).

    Tree structure:
        Tree 1: (1,2), (2,3), (3,4), ..., (d-1,d)
        Tree 2: (1,3|2), (2,4|3), ..., (d-2,d|d-1)
        Tree k: (1,k+1|2,...,k), ...
    """

    def __init__(self, d: int, seed: Optional[int] = None):
        self.d = d
        self.rng = np.random.default_rng(seed)
        self.pair_copulas: Dict[Tuple, PairCopulaFit] = {}
        self._fitted = False
        self._order: Optional[List[int]] = None

    def fit(self, data: np.ndarray, order: Optional[List[int]] = None):
        """
        Fit D-vine to data.

        Args:
            data: (n_samples, d) uniform marginals
            order: Variable ordering along the path. If None, uses greedy max |tau| path.
        """
        n, d = data.shape
        assert d == self.d

        if order is None:
            order = self._greedy_path_order(data)

        self._order = order
        reordered = data[:, order]

        h_forward: Dict[Tuple, np.ndarray] = {}  # h(v_j | v_i, conditioning)
        h_backward: Dict[Tuple, np.ndarray] = {}

        # Tree 1: adjacent pairs
        for j in range(d - 1):
            u = reordered[:, j]
            v = reordered[:, j + 1]
            fit = PairCopula.fit(u, v)
            fit.variables = (order[j], order[j + 1])
            fit.conditioning = ()
            self.pair_copulas[(j, j + 1, ())] = fit

            # h-functions
            h_forward[(j, j + 1)] = self._h_function(v, u, fit)   # h(v|u)
            h_backward[(j + 1, j)] = self._h_function(u, v, fit)  # h(u|v)

        # Higher trees
        for tree in range(1, d - 1):
            for j in range(d - 1 - tree):
                i1 = j
                i2 = j + tree + 1

                # Get pseudo-observations from previous tree
                if tree == 1:
                    u_pseudo = h_forward.get((j, j + 1), reordered[:, j])
                    v_pseudo = h_backward.get((j + tree + 1, j + tree), reordered[:, j + tree + 1])
                else:
                    u_pseudo = h_forward.get((j, j + tree), reordered[:, j])
                    v_pseudo = h_backward.get((j + tree + 1, j + 1), reordered[:, j + tree + 1])

                u_pseudo = np.clip(u_pseudo, 1e-6, 1 - 1e-6)
                v_pseudo = np.clip(v_pseudo, 1e-6, 1 - 1e-6)

                conditioning = tuple(range(j + 1, j + tree + 1))
                fit = PairCopula.fit(u_pseudo, v_pseudo)
                fit.variables = (order[i1], order[i2])
                fit.conditioning = tuple(order[k] for k in conditioning)
                self.pair_copulas[(i1, i2, conditioning)] = fit

                h_forward[(j, j + tree + 1)] = self._h_function(v_pseudo, u_pseudo, fit)
                h_backward[(j + tree + 1, j)] = self._h_function(u_pseudo, v_pseudo, fit)

        self._fitted = True

    def sample(self, n: int) -> np.ndarray:
        """Sample from the fitted D-vine. Returns (n, d) uniform marginals."""
        if not self._fitted:
            raise RuntimeError("Call fit() first")

        d = self.d
        v = np.zeros((n, d))
        w = self.rng.uniform(0, 1, (n, d))

        v[:, 0] = w[:, 0]

        for j in range(1, d):
            v_j = w[:, j]
            # Apply inverse h-functions
            for k in range(j - 1, -1, -1):
                conditioning = tuple(range(k + 1, j))
                key = (k, j, conditioning)
                if key in self.pair_copulas:
                    fit = self.pair_copulas[key]
                    v_j = self._h_inverse(v[:, k], v_j, fit)
            v[:, j] = v_j

        result = np.zeros_like(v)
        for i, orig_idx in enumerate(self._order):
            result[:, orig_idx] = v[:, i]

        return np.clip(result, 1e-6, 1 - 1e-6)

    def _greedy_path_order(self, data: np.ndarray) -> List[int]:
        """Find variable ordering that maximizes sum of adjacent |tau|."""
        d = data.shape[1]
        tau_matrix = np.zeros((d, d))
        for i in range(d):
            for j in range(i + 1, d):
                tau_matrix[i, j] = abs(kendalltau(data[:, i], data[:, j])[0])
                tau_matrix[j, i] = tau_matrix[i, j]

        # Greedy: start from the node with highest total tau
        start = int(np.argmax(tau_matrix.sum(axis=1)))
        order = [start]
        remaining = set(range(d)) - {start}

        while remaining:
            last = order[-1]
            # Pick the remaining node with highest tau to current last
            best = max(remaining, key=lambda j: tau_matrix[last, j])
            order.append(best)
            remaining.remove(best)

        return order

    def _h_function(self, u: np.ndarray, v: np.ndarray, fit: PairCopulaFit) -> np.ndarray:
        """Conditional CDF h(u|v)."""
        if fit.family == "gaussian":
            rho = fit.parameter
            x = norm.ppf(np.clip(v, 1e-6, 1 - 1e-6))
            y = norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))
            return norm.cdf((y - rho * x) / math.sqrt(max(1 - rho ** 2, 1e-8)))
        elif fit.family == "t":
            rho = fit.parameter
            nu = fit.dof or 4.0
            x = t_dist.ppf(np.clip(v, 1e-6, 1 - 1e-6), nu)
            y = t_dist.ppf(np.clip(u, 1e-6, 1 - 1e-6), nu)
            denom = np.sqrt(np.maximum((1 - rho ** 2) * (nu + x ** 2) / (nu + 1), 1e-8))
            return t_dist.cdf((y - rho * x) / denom, nu + 1)
        else:
            rho = math.sin(math.pi * fit.tau / 2)
            rho = max(-0.99, min(0.99, rho))
            x = norm.ppf(np.clip(v, 1e-6, 1 - 1e-6))
            y = norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))
            return norm.cdf((y - rho * x) / math.sqrt(max(1 - rho ** 2, 1e-8)))

    def _h_inverse(self, u: np.ndarray, w: np.ndarray, fit: PairCopulaFit) -> np.ndarray:
        """Inverse h-function."""
        if fit.family == "gaussian":
            rho = fit.parameter
            x = norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))
            z = norm.ppf(np.clip(w, 1e-6, 1 - 1e-6))
            y = rho * x + math.sqrt(max(1 - rho ** 2, 1e-8)) * z
            return norm.cdf(y)
        elif fit.family == "t":
            rho = fit.parameter
            nu = fit.dof or 4.0
            x = t_dist.ppf(np.clip(u, 1e-6, 1 - 1e-6), nu)
            z = t_dist.ppf(np.clip(w, 1e-6, 1 - 1e-6), nu + 1)
            y = rho * x + z * np.sqrt((1 - rho ** 2) * (nu + x ** 2) / (nu + 1))
            return t_dist.cdf(y, nu)
        else:
            rho = math.sin(math.pi * fit.tau / 2)
            rho = max(-0.99, min(0.99, rho))
            x = norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))
            z = norm.ppf(np.clip(w, 1e-6, 1 - 1e-6))
            y = rho * x + math.sqrt(max(1 - rho ** 2, 1e-8)) * z
            return norm.cdf(y)


# Alias for general use
VineCopula = CVine


class CorrelatedContractSimulator:
    """
    High-level interface for simulating correlated prediction market outcomes.

    Uses vine copulas to model dependencies between d contracts,
    then simulates joint outcomes for portfolio risk, sweep probability,
    and conditional probability estimation.

    Usage:
        # 5 swing states with historical uniform data
        sim = CorrelatedContractSimulator(seed=42)
        sim.fit(historical_uniform_data, vine_type="cvine")
        outcomes = sim.simulate_outcomes(
            marginal_probs=[0.52, 0.53, 0.51, 0.48, 0.50],
            n_simulations=100_000,
        )
        sweep = sim.sweep_probability(outcomes)
    """

    def __init__(self, seed: Optional[int] = None):
        self.rng = np.random.default_rng(seed)
        self.vine: Optional[CVine] = None

    def fit(
        self,
        data: np.ndarray,
        vine_type: str = "cvine",
        order: Optional[List[int]] = None,
    ):
        """
        Fit vine copula to historical data.

        Args:
            data: (n_samples, d) array. Should be on uniform scale (apply PIT first).
            vine_type: "cvine" or "dvine"
        """
        d = data.shape[1]
        if vine_type == "dvine":
            self.vine = DVine(d, seed=int(self.rng.integers(0, 2**31)))
        else:
            self.vine = CVine(d, seed=int(self.rng.integers(0, 2**31)))
        self.vine.fit(data, order=order)

    def fit_from_correlations(
        self,
        d: int,
        corr: np.ndarray,
        n_calibration: int = 5000,
        vine_type: str = "cvine",
    ):
        """
        Fit vine copula from a correlation matrix (no historical data needed).

        Generates synthetic data from a Gaussian copula with the given correlation,
        then fits the vine to capture higher-order dependencies.
        """
        L = np.linalg.cholesky(np.array(corr))
        Z = self.rng.standard_normal((n_calibration, d))
        X = Z @ L.T
        U = norm.cdf(X)
        self.fit(U, vine_type=vine_type)

    def simulate_outcomes(
        self,
        marginal_probs: List[float],
        n_simulations: int = 100_000,
    ) -> np.ndarray:
        """
        Simulate correlated binary outcomes.

        Returns (n_simulations, d) array of 0/1 outcomes.
        """
        if self.vine is None:
            raise RuntimeError("Call fit() or fit_from_correlations() first")

        U = self.vine.sample(n_simulations)
        probs = np.array(marginal_probs)
        return (U < probs).astype(int)

    def sweep_probability(self, outcomes: np.ndarray) -> float:
        """P(all contracts resolve YES)."""
        return float(outcomes.all(axis=1).mean())

    def loss_probability(self, outcomes: np.ndarray) -> float:
        """P(all contracts resolve NO)."""
        return float((1 - outcomes).all(axis=1).mean())

    def conditional_probability(
        self,
        outcomes: np.ndarray,
        target_idx: int,
        condition_indices: List[int],
        condition_values: List[int],
    ) -> Optional[float]:
        """
        P(contract[target] = 1 | contract[cond_i] = val_i for each i).
        """
        mask = np.ones(len(outcomes), dtype=bool)
        for idx, val in zip(condition_indices, condition_values):
            mask &= outcomes[:, idx] == val
        if mask.sum() < 10:
            return None
        return float(outcomes[mask, target_idx].mean())
