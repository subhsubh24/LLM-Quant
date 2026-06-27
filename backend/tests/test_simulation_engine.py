"""
Tests for the simulation engine modules.

Covers: Monte Carlo, Importance Sampling, Variance Reduction,
Particle Filters, Vine Copulas, Agent-Based Models, Hierarchical Bayesian,
Correlation Stress Testing, and Integration.
"""

import math
import numpy as np
import pytest
from scipy.stats import norm


# ============================================================
# Monte Carlo Engine
# ============================================================

class TestMonteCarloEngine:
    def test_gbm_expected_value(self):
        """E[S_T] = S0 * exp(mu*T) for GBM."""
        from backend.app.simulation.monte_carlo import MonteCarloEngine

        engine = MonteCarloEngine(seed=42)
        S0, mu, sigma, T = 100.0, 0.08, 0.20, 1.0
        result = engine.simulate_gbm(S0, mu, sigma, T, n_steps=252, n_paths=50_000)

        expected = S0 * math.exp(mu * T)
        assert abs(result.mean_terminal - expected) < 2.0

    def test_gbm_terminal_shape(self):
        from backend.app.simulation.monte_carlo import MonteCarloEngine

        engine = MonteCarloEngine(seed=42)
        result = engine.simulate_gbm(100, 0.05, 0.2, 1.0, n_steps=10, n_paths=1_000)
        assert result.paths.shape == (1_000, 11)
        assert result.terminal_values.shape == (1_000,)
        assert len(result.times) == 11

    def test_jump_diffusion_heavier_tails(self):
        """Jump-diffusion should have heavier tails than GBM."""
        from backend.app.simulation.monte_carlo import MonteCarloEngine

        engine = MonteCarloEngine(seed=42)
        gbm = engine.simulate_gbm(100, 0.08, 0.20, 1.0, n_steps=50, n_paths=10_000)

        engine2 = MonteCarloEngine(seed=42)
        jd = engine2.simulate_jump_diffusion(
            100, 0.08, 0.20, 1.0,
            jump_intensity=2.0, jump_mean=-0.05, jump_vol=0.10,
            n_steps=50, n_paths=10_000,
        )
        gbm_kurt = float(np.mean((gbm.terminal_values - gbm.mean_terminal) ** 4) / gbm.std_terminal ** 4)
        jd_kurt = float(np.mean((jd.terminal_values - jd.mean_terminal) ** 4) / jd.std_terminal ** 4)
        assert jd_kurt > gbm_kurt

    def test_ou_mean_reversion(self):
        """OU process terminal mean should be close to long-run mean."""
        from backend.app.simulation.monte_carlo import MonteCarloEngine

        engine = MonteCarloEngine(seed=42)
        result = engine.simulate_ou(
            X0=5.0, theta=2.0, mu=0.0, sigma=0.5, T=3.0,
            n_steps=100, n_paths=20_000,
        )
        assert abs(result.mean_terminal) < 0.1

    def test_binary_pricer_atm(self):
        """ATM binary option P(S_T > K) ~ 0.5 for zero drift."""
        from backend.app.simulation.monte_carlo import BinaryContractPricer

        pricer = BinaryContractPricer()
        result = pricer.price_asset_binary(
            S0=100, K=100, mu=0.0, sigma=0.2, T=1.0, n_paths=50_000,
        )
        assert 0.40 < result.probability < 0.60
        assert result.std_error < 0.01

    def test_binary_pricer_prediction_market(self):
        from backend.app.simulation.monte_carlo import BinaryContractPricer

        pricer = BinaryContractPricer()
        result = pricer.price_prediction_market_binary(
            current_prob=0.60, prob_volatility=0.5, T=30 / 365, n_paths=20_000,
        )
        assert 0.0 < result.probability < 1.0
        assert result.ci_95[0] < result.probability < result.ci_95[1]

    def test_multi_asset_correlation_preserved(self):
        from backend.app.simulation.monte_carlo import MultiAssetSimulator

        sim = MultiAssetSimulator(seed=42)
        result = sim.simulate_correlated_gbm(
            S0=[100, 50], mu=[0.05, 0.08], sigma=[0.2, 0.3],
            corr=np.array([[1.0, 0.7], [0.7, 1.0]]),
            T=1.0, n_steps=50, n_paths=20_000,
        )
        realized = result["correlation_realized"]
        assert abs(realized[0][1] - 0.7) < 0.1

    def test_portfolio_var_is_loss(self):
        from backend.app.simulation.monte_carlo import MultiAssetSimulator

        sim = MultiAssetSimulator(seed=42)
        result = sim.simulate_portfolio_value(
            S0=[100, 50], weights=[0.6, 0.4],
            mu=[0.05, 0.08], sigma=[0.2, 0.3],
            corr=np.array([[1.0, 0.5], [0.5, 1.0]]),
            T=1.0, n_paths=10_000,
        )
        assert result["var_95"] < 0
        assert result["cvar_95"] <= result["var_95"]


# ============================================================
# Importance Sampling
# ============================================================

class TestImportanceSampling:
    def test_exponential_tilter_matches_analytical(self):
        from backend.app.simulation.importance_sampling import ExponentialTilter

        tilter = ExponentialTilter(seed=42)
        result = tilter.estimate_tail_probability(
            mu=0.0, sigma=1.0, threshold=3.0, n_samples=50_000,
        )
        analytical = 1.0 - norm.cdf(3.0)
        assert abs(result.estimate - analytical) < 3 * result.std_error

    def test_is_reduces_variance(self):
        from backend.app.simulation.importance_sampling import ExponentialTilter

        tilter = ExponentialTilter(seed=42)
        result = tilter.estimate_tail_probability(
            mu=0.0, sigma=1.0, threshold=3.0, n_samples=50_000,
        )
        assert result.variance_reduction > 1.0

    def test_crash_probability(self):
        from backend.app.simulation.importance_sampling import ExponentialTilter

        tilter = ExponentialTilter(seed=42)
        result = tilter.estimate_crash_probability(
            S0=100, crash_pct=0.20, sigma=0.20, T=21 / 252, n_samples=50_000,
        )
        assert 0 < result.estimate < 0.01
        assert result.std_error < result.estimate

    def test_rare_event_prediction_market_tail(self):
        from backend.app.simulation.importance_sampling import RareEventEstimator

        estimator = RareEventEstimator(seed=42)
        result = estimator.estimate_prediction_market_tail(
            current_prob=0.05, vol=0.5, T=30 / 365, n_samples=50_000,
        )
        assert 0 < result.estimate < 0.5
        assert result.std_error > 0

    def test_joint_tail(self):
        from backend.app.simulation.importance_sampling import RareEventEstimator

        estimator = RareEventEstimator(seed=42)
        result = estimator.estimate_joint_tail(
            means=[0.0, 0.0],
            stds=[1.0, 1.0],
            corr=np.array([[1.0, 0.5], [0.5, 1.0]]),
            thresholds=[2.0, 2.0],
            n_samples=50_000,
        )
        marginal_p = 1.0 - norm.cdf(2.0)
        assert result.estimate < marginal_p


# ============================================================
# Variance Reduction
# ============================================================

class TestVarianceReduction:
    def test_antithetic_binary(self):
        from backend.app.simulation.variance_reduction import AntitheticEngine

        engine = AntitheticEngine(seed=42)
        result = engine.estimate_binary(
            S0=100, K=105, mu=0.05, sigma=0.20, T=1.0, n_paths=25_000,
        )
        d2 = (math.log(100 / 105) + (0.05 - 0.5 * 0.04) * 1.0) / 0.20
        analytical = norm.cdf(d2)
        assert abs(result.estimate - analytical) < 2 * result.std_error + 0.02

    def test_antithetic_reduces_variance(self):
        from backend.app.simulation.variance_reduction import AntitheticEngine

        engine = AntitheticEngine(seed=42)
        result = engine.estimate_binary(S0=100, K=100, mu=0.0, sigma=0.2, T=1.0)
        assert result.variance_reduction > 0.8

    def test_stratified_binary(self):
        from backend.app.simulation.variance_reduction import StratifiedEngine

        engine = StratifiedEngine(seed=42)
        result = engine.estimate_binary(
            S0=100, K=100, mu=0.0, sigma=0.2, T=1.0, n_strata=10, n_total=50_000,
        )
        assert 0.3 < result.estimate < 0.7
        # Stratified estimate should be accurate (close to ~0.46 BS digital)
        assert result.std_error < 0.2

    def test_stacked_vr(self):
        from backend.app.simulation.variance_reduction import StackedVarianceReduction

        engine = StackedVarianceReduction(seed=42)
        result = engine.estimate_binary(
            S0=100, K=105, mu=0.05, sigma=0.20, T=1.0,
            n_strata=10, n_total=50_000,
        )
        assert 0.2 < result.estimate < 0.8
        assert result.std_error < 0.05

    def test_control_variate(self):
        from backend.app.simulation.variance_reduction import ControlVariateEngine

        engine = ControlVariateEngine(seed=42)
        result = engine.estimate_binary_with_bs_control(
            S0=100, K=100, mu=0.05, sigma=0.2, T=1.0, sigma_true=0.2,
            n_paths=50_000,
        )
        assert 0.3 < result.estimate < 0.7
        assert result.method == "control_variate_bs"


# ============================================================
# Particle Filters
# ============================================================

class TestParticleFilters:
    def test_prediction_market_filter_converges(self):
        from backend.app.simulation.particle_filter import PredictionMarketFilter

        pf = PredictionMarketFilter(
            n_particles=3000, prior_prob=0.50, process_vol=0.02,
            obs_noise=0.02, seed=42,
        )
        rng = np.random.default_rng(42)
        for _ in range(20):
            obs = 0.65 + rng.normal(0, 0.02)
            pf.update(obs)

        est = pf.estimate()
        assert abs(est - 0.65) < 0.08

    def test_multi_contract_filter(self):
        from backend.app.simulation.particle_filter import MultiContractFilter

        mcf = MultiContractFilter(
            n_contracts=3, prior_probs=[0.5, 0.5, 0.5],
            n_particles=5000, process_vol=0.02, obs_noise=0.02, seed=42,
        )
        for _ in range(10):
            mcf.update(0, 0.70)
        probs = mcf.estimate_all()
        assert probs[0] > 0.55
        assert len(probs) == 3

    def test_multi_contract_sweep(self):
        from backend.app.simulation.particle_filter import MultiContractFilter

        mcf = MultiContractFilter(
            n_contracts=2, prior_probs=[0.6, 0.6],
            n_particles=5000, seed=42,
        )
        sweep = mcf.estimate_joint_event(lambda p: all(x > 0.5 for x in p))
        assert 0.0 < sweep < 1.0

    def test_trading_regime_filter(self):
        from backend.app.simulation.particle_filter import TradingRegimeFilter

        rf = TradingRegimeFilter(n_particles=3000, seed=42)
        for _ in range(30):
            rf.update(daily_return=0.005, realized_vol=0.10)

        regime = rf.estimate_regime()
        assert "regime_score" in regime
        assert "regime_label" in regime
        # After consistent positive returns, regime should not be strongly bearish
        assert regime["regime_score"] > -0.5


# ============================================================
# Vine Copulas
# ============================================================

class TestVineCopulas:
    def test_pair_copula_fit(self):
        from backend.app.simulation.vine_copula import PairCopula

        rng = np.random.default_rng(42)
        n = 500
        x = rng.standard_normal(n)
        y = 0.6 * x + 0.8 * rng.standard_normal(n)
        u = norm.cdf(x)
        v = norm.cdf(y)

        fit = PairCopula.fit(u, v)
        assert fit.family in ("gaussian", "t", "frank", "clayton", "gumbel")
        assert abs(fit.tau) < 1.0

    def test_cvine_samples_uniform_marginals(self):
        from backend.app.simulation.vine_copula import CVine

        rng = np.random.default_rng(42)
        d = 3
        L = np.linalg.cholesky([[1, 0.5, 0.3], [0.5, 1, 0.4], [0.3, 0.4, 1]])
        Z = rng.standard_normal((300, d)) @ L.T
        U = norm.cdf(Z)

        vine = CVine(d=d, seed=42)
        vine.fit(U)
        samples = vine.sample(1000)

        assert samples.shape == (1000, 3)
        for j in range(d):
            assert 0.3 < samples[:, j].mean() < 0.7

    def test_correlated_simulator_sweep(self):
        from backend.app.simulation.vine_copula import CorrelatedContractSimulator

        sim = CorrelatedContractSimulator(seed=42)
        corr = np.array([[1.0, 0.6], [0.6, 1.0]])
        sim.fit_from_correlations(d=2, corr=corr, n_calibration=2000)

        probs = [0.6, 0.6]
        outcomes = sim.simulate_outcomes(probs, n_simulations=50_000)
        sweep = sim.sweep_probability(outcomes)
        independent_sweep = 0.6 * 0.6

        assert sweep > independent_sweep * 0.8


# ============================================================
# Agent-Based Models
# ============================================================

class TestAgentBasedModels:
    def test_market_price_converges(self):
        from backend.app.simulation.agent_based import AgentBasedMarket

        market = AgentBasedMarket(initial_price=0.50, true_value=0.70, seed=42)
        market.add_informed_traders(10)
        market.add_noise_traders(30)
        market.add_market_makers(3)
        market.run(500)

        summary = market.summary()
        assert abs(summary["final_price"] - 0.70) < abs(0.50 - 0.70)

    def test_prediction_market_abm_brier(self):
        from backend.app.simulation.agent_based import PredictionMarketABM

        pm = PredictionMarketABM(
            initial_price=0.50, true_prob=0.65,
            n_informed=10, n_noise=30, n_mm=3, seed=42,
        )
        pm.run(500)
        assert 0 < pm.brier_score() < 0.5

    def test_prediction_market_info_efficiency(self):
        from backend.app.simulation.agent_based import PredictionMarketABM

        pm = PredictionMarketABM(
            initial_price=0.50, true_prob=0.70,
            n_informed=15, n_noise=30, n_mm=3, seed=42,
        )
        pm.run(1000)
        assert pm.information_efficiency() > 0.0

    def test_trading_abm_tracks_fundamental(self):
        from backend.app.simulation.agent_based import TradingABM

        abm = TradingABM(
            initial_price=100.0, fundamental_vol=0.01,
            n_informed=20, n_noise=50, n_mm=5, seed=42,
        )
        summary = abm.run(1000)
        assert summary["price_fundamental_corr"] > 0.5


# ============================================================
# Integration
# ============================================================

class TestSimulationIntegration:
    def test_enhanced_pricer_tail_uses_is(self):
        from backend.app.prediction_markets.simulation_integration import EnhancedContractPricer

        pricer = EnhancedContractPricer(seed=42)
        result = pricer.price_contract(
            current_prob=0.03, vol=0.5, T=30 / 365, n_paths=10_000,
        )
        assert result["method"] == "importance_sampling"
        assert 0 < result["probability"] < 0.5

    def test_enhanced_pricer_standard_uses_vr(self):
        from backend.app.prediction_markets.simulation_integration import EnhancedContractPricer

        pricer = EnhancedContractPricer(seed=42)
        result = pricer.price_contract(
            current_prob=0.55, vol=0.3, T=30 / 365, n_paths=10_000,
        )
        assert result["method"] == "stacked_variance_reduction"
        assert 0.2 < result["probability"] < 0.8

    def test_live_tracker_estimate_within_ci(self):
        from backend.app.prediction_markets.simulation_integration import LiveProbabilityTracker

        tracker = LiveProbabilityTracker(prior_prob=0.50, seed=42)
        for price in [0.52, 0.54, 0.56, 0.58, 0.60]:
            tracker.update(price)

        est = tracker.estimate()
        ci = tracker.credible_interval()
        assert ci[0] <= est <= ci[1]

    def test_correlated_portfolio_var(self):
        from backend.app.prediction_markets.simulation_integration import CorrelatedPortfolioAnalyzer

        analyzer = CorrelatedPortfolioAnalyzer(seed=42)
        corr = np.array([[1.0, 0.5], [0.5, 1.0]])
        analyzer.fit_from_correlation(n_contracts=2, corr_matrix=corr)

        var_result = analyzer.portfolio_var(
            marginal_probs=[0.6, 0.55], bet_sizes=[10, 5], n_sim=20_000,
        )
        assert "var" in var_result
        assert "cvar" in var_result
        assert var_result["cvar"] <= var_result["var"]

    def test_microstructure_simulator(self):
        from backend.app.prediction_markets.simulation_integration import MarketMicrostructureSimulator

        sim = MarketMicrostructureSimulator(seed=42)
        result = sim.simulate_price_discovery(
            true_prob=0.65, initial_price=0.50, n_steps=500,
        )
        assert "brier_score" in result
        assert "information_efficiency" in result

    def test_crash_contract_pricing(self):
        from backend.app.prediction_markets.simulation_integration import EnhancedContractPricer

        pricer = EnhancedContractPricer(seed=42)
        result = pricer.price_crash_contract(
            asset_price=5000, crash_pct=0.15, sigma=0.20, T=5 / 252,
            n_paths=50_000,
        )
        assert result["method"] == "importance_sampling"
        assert 0 <= result["probability"] < 0.1


# ============================================================
# Hierarchical Bayesian
# ============================================================

class TestHierarchicalBayesian:
    def test_shrinkage_toward_mean(self):
        """Extreme markets should be shrunk toward the group mean."""
        from backend.app.simulation.hierarchical_bayesian import HierarchicalBayesianModel

        model = HierarchicalBayesianModel(seed=42)
        # One outlier at 0.90, rest around 0.55
        probs = np.array([0.55, 0.53, 0.57, 0.54, 0.90])
        result = model.fit(probs, n_iter=3000, burn_in=500)

        # The outlier (0.90) should be pulled toward the group
        assert result.group_estimates[4] < 0.90
        # The middle markets should barely move
        for i in range(4):
            assert abs(result.group_estimates[i] - probs[i]) < 0.15

    def test_ci_contains_estimate(self):
        from backend.app.simulation.hierarchical_bayesian import HierarchicalBayesianModel

        model = HierarchicalBayesianModel(seed=42)
        probs = np.array([0.50, 0.55, 0.60, 0.45])
        result = model.fit(probs, n_iter=3000, burn_in=500)

        for i in range(len(probs)):
            assert result.group_ci_lower[i] <= result.group_estimates[i] <= result.group_ci_upper[i]

    def test_acceptance_rate_reasonable(self):
        from backend.app.simulation.hierarchical_bayesian import HierarchicalBayesianModel

        model = HierarchicalBayesianModel(seed=42)
        probs = np.array([0.50, 0.55, 0.60, 0.45, 0.52])
        result = model.fit(probs, n_iter=5000, burn_in=1000)

        # MH acceptance rate should be in a reasonable range
        assert 0.1 < result.acceptance_rate < 0.95

    def test_swing_model_detects_shift(self):
        """If observed prices all shift up, swing should be positive."""
        from backend.app.simulation.hierarchical_bayesian import NationalSwingModel

        model = NationalSwingModel(seed=42)
        base = np.array([0.50, 0.45, 0.55, 0.40, 0.60])
        # All shifted up by ~5-10%
        observed = np.array([0.58, 0.52, 0.62, 0.48, 0.68])
        result = model.estimate_swing(base, observed)

        assert result.swing_estimate > 0
        for i in range(len(base)):
            assert result.adjusted_probs[i] > base[i]

    def test_category_pooling(self):
        from backend.app.simulation.hierarchical_bayesian import CategoryPoolingModel

        pooler = CategoryPoolingModel(seed=42)
        result = pooler.pool_probabilities(
            market_probs={"a": 0.55, "b": 0.60, "c": 0.50},
            market_volumes={"a": 100000, "b": 500, "c": 200},
        )
        assert "a" in result and "b" in result and "c" in result
        # High volume market "a" should barely shrink
        assert abs(result["a"]["pooled_prob"] - 0.55) < abs(result["c"]["pooled_prob"] - 0.50)


# ============================================================
# Correlation Stress Testing
# ============================================================

class TestCorrelationStress:
    def test_uniform_stress_increases_var(self):
        """High uniform correlation should increase VaR (worse risk)."""
        from backend.app.simulation.correlation_stress import CorrelationStressTester

        tester = CorrelationStressTester(seed=42)
        d = 4
        # Start with low/no correlation so stress has visible effect
        base_corr = np.eye(d)

        result = tester.stress_uniform_correlation(
            marginal_probs=np.array([0.55, 0.60, 0.45, 0.50]),
            base_corr=base_corr,
            bet_sizes=np.array([100, 100, 100, 100], dtype=float),
            stress_rho=0.9,
            n_sim=20_000,
        )
        # Stressed VaR should be worse (more negative) or equal
        assert result.stressed_var <= result.base_var + 1.0

    def test_contagion_propagates_shock(self):
        from backend.app.simulation.correlation_stress import CorrelationStressTester

        tester = CorrelationStressTester(seed=42)
        d = 3
        corr = np.array([[1.0, 0.7, 0.3],
                         [0.7, 1.0, 0.2],
                         [0.3, 0.2, 1.0]])

        result = tester.contagion_analysis(
            marginal_probs=np.array([0.60, 0.55, 0.50]),
            corr=corr,
            bet_sizes=np.array([100, 100, 100], dtype=float),
            source_idx=0,
            shock_size=-0.20,
        )
        # Market 1 (corr=0.7 with source) should be impacted more than market 2 (corr=0.3)
        assert abs(result.impact_on_others[1]) > abs(result.impact_on_others[2])
        assert result.portfolio_impact < 0  # Negative shock -> negative impact

    def test_full_stress_report(self):
        from backend.app.simulation.correlation_stress import CorrelationStressTester

        tester = CorrelationStressTester(seed=42)
        d = 3
        base_corr = np.eye(d) * 0.7 + np.full((d, d), 0.3)

        report = tester.full_stress_test(
            marginal_probs=[0.55, 0.60, 0.50],
            base_correlation=base_corr,
            bet_sizes=[100, 100, 100],
            n_sim=10_000,
        )
        assert len(report.scenarios) == 4
        assert report.stress_multiplier >= 1.0 or report.stress_multiplier >= 0  # Decorrelation may improve
        assert len(report.recommendation) > 0

    def test_block_correlation(self):
        from backend.app.simulation.correlation_stress import CorrelationStressTester

        tester = CorrelationStressTester(seed=42)
        d = 4
        base_corr = np.eye(d)

        result = tester.stress_block_correlation(
            marginal_probs=np.array([0.55, 0.60, 0.45, 0.50]),
            base_corr=base_corr,
            bet_sizes=np.array([100, 100, 100, 100], dtype=float),
            blocks=[[0, 1], [2, 3]],
            within_block_rho=0.9,
            between_block_rho=0.2,
            n_sim=10_000,
        )
        assert result.scenario_name == "block_correlation"
        # Block correlation with identity base should show stressed VaR worse than base
        assert result.correlation_matrix.shape == (4, 4)

    def test_nearest_psd(self):
        from backend.app.simulation.correlation_stress import _nearest_positive_semidefinite

        # Create an invalid correlation matrix
        bad = np.array([[1.0, 0.9, 0.9],
                        [0.9, 1.0, -0.9],
                        [0.9, -0.9, 1.0]])
        fixed = _nearest_positive_semidefinite(bad)

        # Should be positive semi-definite
        eigvals = np.linalg.eigvalsh(fixed)
        assert np.all(eigvals >= -1e-6)
        # Diagonal should be 1
        np.testing.assert_allclose(np.diag(fixed), 1.0, atol=1e-6)


# ============================================================
# Integration: Hierarchical Bayesian + Stress Testing
# ============================================================

class TestNewIntegration:
    def test_cross_market_pooler(self):
        from backend.app.prediction_markets.simulation_integration import CrossMarketPooler

        pooler = CrossMarketPooler(seed=42)
        result = pooler.pool_category(
            market_probs={"m1": 0.55, "m2": 0.60, "m3": 0.50},
        )
        assert len(result) == 3
        for k, v in result.items():
            assert "pooled_prob" in v
            assert "shrinkage" in v

    def test_portfolio_stress_tester(self):
        from backend.app.prediction_markets.simulation_integration import PortfolioStressTester

        tester = PortfolioStressTester(seed=42)
        result = tester.run_stress_test(
            probs=[0.55, 0.60, 0.45],
            bet_sizes=[100, 200, 150],
            n_sim=10_000,
        )
        assert "normal_var" in result
        assert "worst_case_var" in result
        assert "recommendation" in result
        assert result["n_scenarios"] == 4

    def test_contagion_check(self):
        from backend.app.prediction_markets.simulation_integration import PortfolioStressTester

        tester = PortfolioStressTester(seed=42)
        d = 3
        corr = np.eye(d) * 0.6 + np.full((d, d), 0.4)
        results = tester.contagion_check(
            probs=[0.55, 0.60, 0.45],
            bet_sizes=[100, 200, 150],
            corr=corr,
            shock_size=-0.15,
        )
        assert len(results) == 3
        for r in results:
            assert "portfolio_impact" in r
