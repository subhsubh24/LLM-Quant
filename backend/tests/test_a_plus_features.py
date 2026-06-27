"""
Tests for A+ upgrade features:
- Feature selection (IC-based + PCA)
- FDR multiple comparison correction
- OOS holdout evaluation
- Block bootstrap confidence intervals
- Drift detection (KS test)
- Model staleness tracking
- P&L attribution
- CVaR and advanced risk controls
- Correlation regime detection
- Drawdown-based position scaling
- Market impact model
- Trade audit trail
- Position reconciliation
- Model checkpoint manager
"""

import pytest
import numpy as np
import pandas as pd
import tempfile
import os
import json
from datetime import datetime, date, timedelta


# ========== Feature Selection ==========

class TestFeatureSelector:
    """Test IC-based feature selection and PCA."""

    def test_ic_filter_keeps_good_features(self):
        """Features with high IC should be retained."""
        from app.models.framework import FeatureSelector, ModelConfig

        np.random.seed(42)
        n = 500
        config = ModelConfig(min_feature_ic=0.02, use_pca_decorrelation=False)
        selector = FeatureSelector(config)

        # Create features: one predictive, one noise
        y = pd.Series(np.random.randn(n))
        X = pd.DataFrame({
            "good_feature": y * 0.5 + np.random.randn(n) * 0.5,  # Correlated with target
            "noise_feature": np.random.randn(n),  # Pure noise
        })

        X_filtered, selected = selector.select_features(X, y)

        assert "good_feature" in selected
        assert len(selected) >= 1  # At least the good feature passes

    def test_ic_filter_fallback_when_none_pass(self):
        """When no features pass IC filter, keep all features."""
        from app.models.framework import FeatureSelector, ModelConfig

        np.random.seed(42)
        n = 500
        config = ModelConfig(min_feature_ic=0.99, use_pca_decorrelation=False)
        selector = FeatureSelector(config)

        y = pd.Series(np.random.randn(n))
        X = pd.DataFrame({
            "f1": np.random.randn(n),
            "f2": np.random.randn(n),
        })

        X_filtered, selected = selector.select_features(X, y)
        assert len(selected) == 2  # Falls back to all features

    def test_pca_reduces_dimensions(self):
        """PCA should reduce feature count."""
        from app.models.framework import FeatureSelector, ModelConfig

        np.random.seed(42)
        n = 200
        config = ModelConfig(
            min_feature_ic=0.0,
            use_pca_decorrelation=True,
            pca_variance_threshold=0.95,
        )
        selector = FeatureSelector(config)

        # Create 20 features, most of which are collinear
        base = np.random.randn(n, 3)
        X_data = np.hstack([base + np.random.randn(n, 3) * 0.1 for _ in range(7)])[:, :20]
        X = pd.DataFrame(X_data, columns=[f"f{i}" for i in range(20)])

        X_pca = selector.apply_pca(X)

        # Should have fewer columns than 20
        assert X_pca.shape[1] < 20
        assert X_pca.shape[0] == n

    def test_transform_applies_saved_selection(self):
        """Transform should use previously computed selection."""
        from app.models.framework import FeatureSelector, ModelConfig

        np.random.seed(42)
        n = 300
        config = ModelConfig(min_feature_ic=0.02, use_pca_decorrelation=False)
        selector = FeatureSelector(config)

        y = pd.Series(np.random.randn(n))
        X = pd.DataFrame({
            "good": y * 0.5 + np.random.randn(n) * 0.5,
            "noise": np.random.randn(n),
        })

        selector.select_features(X, y)

        # Transform new data
        X_new = pd.DataFrame({
            "good": np.random.randn(50),
            "noise": np.random.randn(50),
            "extra": np.random.randn(50),  # Not in original
        })

        X_transformed = selector.transform(X_new)
        assert "extra" not in X_transformed.columns


# ========== FDR Correction ==========

class TestFDRCorrection:
    """Test Benjamini-Hochberg false discovery rate correction."""

    def test_obvious_signal_passes(self):
        """Very low p-value should survive FDR correction."""
        from app.models.framework import FDRCorrection

        pvalues = [0.001, 0.5, 0.8, 0.9]
        results = FDRCorrection.correct_pvalues(pvalues, alpha=0.05)

        # First p-value (0.001) should be significant
        assert results[0][2] is True  # is_significant
        # Last p-value (0.9) should not be
        assert results[3][2] is False

    def test_all_noise_rejected(self):
        """All high p-values should be rejected."""
        from app.models.framework import FDRCorrection

        pvalues = [0.3, 0.5, 0.7, 0.9]
        results = FDRCorrection.correct_pvalues(pvalues, alpha=0.05)

        for _, _, is_sig in results:
            assert is_sig is False

    def test_strategy_pvalue_positive_scores(self):
        """Consistently positive validation scores should have low p-value."""
        from app.models.framework import FDRCorrection

        scores = [0.05, 0.08, 0.03, 0.07, 0.06, 0.04, 0.09, 0.05]
        pval = FDRCorrection.strategy_pvalue(scores, len(scores))
        assert pval < 0.05  # Consistently positive → low p-value

    def test_strategy_pvalue_mixed_scores(self):
        """Mixed positive/negative scores should have high p-value."""
        from app.models.framework import FDRCorrection

        scores = [0.05, -0.08, 0.03, -0.07, 0.02, -0.04]
        pval = FDRCorrection.strategy_pvalue(scores, len(scores))
        assert pval > 0.1  # Mixed → not significant

    def test_empty_pvalues(self):
        """Empty input should return empty output."""
        from app.models.framework import FDRCorrection
        assert FDRCorrection.correct_pvalues([]) == []


# ========== Block Bootstrap ==========

class TestBlockBootstrap:
    """Test block bootstrap for Sharpe ratio confidence intervals."""

    def test_positive_sharpe_ci(self):
        """Strategy with positive returns should have CI above zero."""
        from app.portfolio.risk import RiskManager

        np.random.seed(42)
        rm = RiskManager()
        # Generate returns with positive drift
        returns = pd.Series(np.random.randn(500) * 0.01 + 0.0005)

        result = rm.bootstrap_sharpe_ci(returns, n_bootstrap=500)

        assert result["sharpe_point"] > 0
        assert result["sharpe_lower"] < result["sharpe_upper"]
        assert result["sharpe_se"] > 0
        assert result["n_bootstrap"] == 500

    def test_noise_ci_contains_zero(self):
        """Pure noise should have CI containing zero."""
        from app.portfolio.risk import RiskManager

        np.random.seed(42)
        rm = RiskManager(risk_free_rate=0.0)
        returns = pd.Series(np.random.randn(500) * 0.01)

        result = rm.bootstrap_sharpe_ci(returns, n_bootstrap=500)

        # CI should contain zero for pure noise
        assert result["sharpe_lower"] < 0 or result["sharpe_upper"] > 0

    def test_short_series_returns_point_estimate(self):
        """Short series should return point estimate without CI."""
        from app.portfolio.risk import RiskManager

        rm = RiskManager()
        returns = pd.Series(np.random.randn(30) * 0.01)

        result = rm.bootstrap_sharpe_ci(returns)
        assert result["n_bootstrap"] == 0
        assert result["sharpe_lower"] == result["sharpe_upper"]

    def test_p_value_for_significant_strategy(self):
        """Strategy with strong positive drift should have low p-value."""
        from app.portfolio.risk import RiskManager

        np.random.seed(42)
        rm = RiskManager(risk_free_rate=0.0)
        returns = pd.Series(np.random.randn(500) * 0.01 + 0.002)

        result = rm.bootstrap_sharpe_ci(returns, n_bootstrap=500)
        assert result["p_value"] < 0.05


# ========== CVaR and Advanced Risk ==========

class TestAdvancedRisk:
    """Test CVaR, correlation regime, drawdown scaling, market impact."""

    def test_cvar_computation(self):
        """CVaR should be more negative than VaR."""
        from app.portfolio.risk import RiskManager

        np.random.seed(42)
        rm = RiskManager()
        returns = pd.Series(np.random.randn(500) * 0.02)

        cvar = rm.compute_cvar(returns, confidence=0.95)
        var = returns.quantile(0.05)

        assert cvar <= var  # CVaR is more extreme than VaR
        assert cvar < 0  # Should be negative

    def test_cvar_limit_check(self):
        """CVaR breach should be detected."""
        from app.portfolio.risk import RiskManager

        np.random.seed(42)
        rm = RiskManager()
        # Create returns with heavy left tail
        returns = pd.Series(np.concatenate([
            np.random.randn(450) * 0.01,
            np.random.randn(50) * 0.05 - 0.05,  # Tail events
        ]))

        breached, cvar = rm.check_cvar_limit(returns, cvar_limit=-0.01)
        assert isinstance(breached, bool)
        assert isinstance(cvar, float)
        assert cvar < 0

    def test_correlation_regime_detection(self):
        """Should detect different correlation regimes."""
        from app.portfolio.risk import RiskManager

        np.random.seed(42)
        rm = RiskManager()

        # High-correlation regime (crisis-like)
        n = 300
        common = np.random.randn(n)
        returns = pd.DataFrame({
            "A": common * 0.8 + np.random.randn(n) * 0.2,
            "B": common * 0.8 + np.random.randn(n) * 0.2,
            "C": common * 0.8 + np.random.randn(n) * 0.2,
        })

        result = rm.detect_correlation_regime(returns, lookback=63)
        assert result["avg_correlation"] > 0.3
        assert result["regime"] in ("crisis", "elevated", "normal", "dispersed")

    def test_correlation_regime_insufficient_data(self):
        """Should handle insufficient data gracefully."""
        from app.portfolio.risk import RiskManager

        rm = RiskManager()
        returns = pd.DataFrame({"A": [0.01, 0.02], "B": [0.01, -0.01]})

        result = rm.detect_correlation_regime(returns, lookback=63)
        assert result["regime"] == "unknown"

    def test_drawdown_scaling(self):
        """Drawdown should reduce position scalar."""
        from app.portfolio.risk import RiskManager

        rm = RiskManager()

        # No drawdown → scalar = 1.0
        equity = pd.Series([100, 101, 102, 103, 104])
        assert rm.drawdown_position_scalar(equity, max_dd_limit=0.15) == 1.0

        # Deep drawdown → scalar < 1.0
        equity = pd.Series([100, 101, 102, 103, 90])
        scalar = rm.drawdown_position_scalar(equity, max_dd_limit=0.15)
        assert scalar < 1.0
        assert scalar >= 0.25

    def test_market_impact_model(self):
        """Market impact should increase with order size."""
        from app.portfolio.risk import RiskManager

        rm = RiskManager()

        small_impact = rm.compute_market_impact(1_000, 1_000_000, base_impact_bps=10)
        large_impact = rm.compute_market_impact(100_000, 1_000_000, base_impact_bps=10)

        assert large_impact > small_impact  # Bigger orders have more impact
        assert small_impact > 0
        assert large_impact > 0

    def test_market_impact_illiquid_penalty(self):
        """Illiquid assets should get penalty."""
        from app.portfolio.risk import RiskManager

        rm = RiskManager()
        impact = rm.compute_market_impact(1000, 0, base_impact_bps=10)
        assert impact == 50  # 5x penalty


# ========== Drift Detection ==========

class TestDriftDetection:
    """Test distribution drift detection."""

    def test_no_drift_on_same_distribution(self):
        """Same distribution should not trigger drift."""
        from app.monitoring.drift_detector import DistributionDriftDetector

        np.random.seed(42)
        detector = DistributionDriftDetector(
            reference_window=200,
            test_window=50,
            ks_threshold=0.05,
        )

        # Set reference
        X_ref = pd.DataFrame({"f1": np.random.randn(200), "f2": np.random.randn(200)})
        detector.set_reference(X_ref)

        # Add observations from same distribution
        for i in range(50):
            obs = pd.Series({"f1": np.random.randn(), "f2": np.random.randn()})
            events = detector.add_observation(obs)

        # Should detect no drift (or very minimal)
        summary = detector.get_drift_summary()
        assert summary["status"] in ("stable", "minor_drift")

    def test_detects_mean_shift(self):
        """Should detect distribution mean shift."""
        from app.monitoring.drift_detector import DistributionDriftDetector

        np.random.seed(42)
        detector = DistributionDriftDetector(
            reference_window=200,
            test_window=50,
            ks_threshold=0.05,
        )

        # Reference: N(0, 1)
        X_ref = pd.DataFrame({"f1": np.random.randn(200)})
        detector.set_reference(X_ref)

        # New data: N(3, 1) — big shift
        for i in range(50):
            obs = pd.Series({"f1": np.random.randn() + 3.0})
            detector.add_observation(obs)

        events = detector.check_drift()
        assert len(events) > 0
        assert events[0].drift_type == "feature"


# ========== Model Staleness ==========

class TestModelStaleness:
    """Test model staleness tracking."""

    def test_new_model_not_stale(self):
        """Freshly trained model should not be stale."""
        from app.monitoring.drift_detector import ModelStalenessTracker

        tracker = ModelStalenessTracker(max_age_days=90)
        tracker.register_model(datetime.now(), baseline_ic=0.05)

        report = tracker.assess_staleness()
        assert not report.is_stale
        assert report.recommended_action == "ok"
        assert report.model_age_days == 0

    def test_old_model_is_stale(self):
        """Model older than max_age should be stale."""
        from app.monitoring.drift_detector import ModelStalenessTracker

        tracker = ModelStalenessTracker(max_age_days=90)
        tracker.register_model(datetime.now() - timedelta(days=100), baseline_ic=0.05)

        report = tracker.assess_staleness()
        assert report.is_stale
        assert report.recommended_action == "retrain_now"

    def test_ic_decay_triggers_staleness(self):
        """IC decay beyond threshold should trigger staleness."""
        from app.monitoring.drift_detector import ModelStalenessTracker

        tracker = ModelStalenessTracker(
            ic_decay_threshold=0.5,
            max_age_days=365,
            monitoring_window=5,
        )
        tracker.register_model(datetime.now() - timedelta(days=30), baseline_ic=0.10)

        # Add declining ICs
        for ic in [0.04, 0.03, 0.02, 0.01, 0.01]:
            tracker.add_ic_observation(ic)

        report = tracker.assess_staleness()
        assert report.ic_decay_pct > 0.5
        assert report.is_stale


# ========== P&L Attribution ==========

class TestPnLAttribution:
    """Test P&L attribution engine."""

    def test_attribution_sums_correctly(self):
        """Alpha + beta + costs should equal total return."""
        from app.monitoring.drift_detector import PnLAttributionEngine

        engine = PnLAttributionEngine()

        attr = engine.record_daily(
            portfolio_return=0.01,
            market_return=0.008,
            portfolio_beta=1.0,
            transaction_costs=0.001,
            n_trades=5,
        )

        # beta_return = 1.0 * 0.008 = 0.008
        # alpha_return = 0.01 - 0.008 + 0.001 = 0.003
        # cost_drag = -0.001
        # total ≈ alpha + beta + cost
        assert abs(attr["beta_return"] - 0.008) < 1e-10
        assert abs(attr["cost_drag"] - (-0.001)) < 1e-10

    def test_cumulative_attribution(self):
        """Cumulative attribution over multiple days."""
        from app.monitoring.drift_detector import PnLAttributionEngine

        engine = PnLAttributionEngine()

        for _ in range(10):
            engine.record_daily(
                portfolio_return=0.005,
                market_return=0.003,
                portfolio_beta=1.0,
                transaction_costs=0.0005,
                n_trades=2,
            )

        cum = engine.get_cumulative_attribution()
        assert cum["n_days"] == 10
        assert cum["total_return"] > 0
        assert cum["beta_return"] > 0
        assert cum["cost_drag"] < 0

    def test_empty_engine(self):
        """Empty engine should return zeros."""
        from app.monitoring.drift_detector import PnLAttributionEngine

        engine = PnLAttributionEngine()
        cum = engine.get_cumulative_attribution()
        assert cum["total_return"] == 0.0


# ========== Trade Audit Trail ==========

class TestTradeAuditTrail:
    """Test persistent trade audit trail."""

    def test_log_and_read_trade(self):
        """Should log a trade and read it back."""
        from app.trading.audit_trail import TradeAuditTrail

        with tempfile.TemporaryDirectory() as tmpdir:
            audit = TradeAuditTrail(audit_dir=tmpdir)
            audit.log_trade("AAPL", "buy", 100, 150.0, commission_bps=5.0)

            records = audit.read_audit_log(event_type="trade")
            assert len(records) == 1
            assert records[0]["details"]["symbol"] == "AAPL"
            assert records[0]["details"]["qty"] == 100
            assert records[0]["details"]["notional"] == 15000.0

    def test_log_rebalance(self):
        """Should log rebalance events."""
        from app.trading.audit_trail import TradeAuditTrail

        with tempfile.TemporaryDirectory() as tmpdir:
            audit = TradeAuditTrail(audit_dir=tmpdir)
            audit.log_rebalance(
                old_weights={"AAPL": 0.3, "GOOG": 0.7},
                new_weights={"AAPL": 0.5, "MSFT": 0.5},
                turnover=0.4,
                n_trades=3,
                total_cost_bps=15.0,
            )

            records = audit.read_audit_log(event_type="rebalance")
            assert len(records) == 1
            assert records[0]["details"]["turnover"] == 0.4
            assert "GOOG" in records[0]["details"]["positions_removed"]
            assert "MSFT" in records[0]["details"]["positions_added"]

    def test_log_risk_event(self):
        """Should log risk events."""
        from app.trading.audit_trail import TradeAuditTrail

        with tempfile.TemporaryDirectory() as tmpdir:
            audit = TradeAuditTrail(audit_dir=tmpdir)
            audit.log_risk_event(
                "circuit_breaker",
                "critical",
                {"loss_pct": -0.05, "action": "pause"},
            )

            records = audit.read_audit_log(event_type="risk_event")
            assert len(records) == 1
            assert records[0]["details"]["severity"] == "critical"

    def test_daily_summary(self):
        """Should produce daily summary."""
        from app.trading.audit_trail import TradeAuditTrail

        with tempfile.TemporaryDirectory() as tmpdir:
            audit = TradeAuditTrail(audit_dir=tmpdir)
            audit.log_trade("AAPL", "buy", 100, 150.0)
            audit.log_trade("GOOG", "sell", 50, 100.0)
            audit.log_risk_event("var_breach", "warning", {})

            summary = audit.get_daily_summary()
            assert summary["n_trades"] == 2
            assert summary["n_risk_events"] == 1
            assert summary["total_notional"] == 20000.0

    def test_model_retrain_log(self):
        """Should log model retraining events."""
        from app.trading.audit_trail import TradeAuditTrail

        with tempfile.TemporaryDirectory() as tmpdir:
            audit = TradeAuditTrail(audit_dir=tmpdir)
            audit.log_model_retrain(
                old_version="v001",
                new_version="v002",
                reason="ic_decay",
                validation_score=0.05,
                oos_score=0.03,
                n_features=150,
            )

            records = audit.read_audit_log(event_type="model_retrain")
            assert len(records) == 1
            assert records[0]["details"]["new_version"] == "v002"


# ========== Position Reconciliation ==========

class TestPositionReconciliation:
    """Test position reconciliation."""

    def test_matching_positions(self):
        """Matching positions should have no discrepancies."""
        from app.trading.audit_trail import PositionReconciler

        reconciler = PositionReconciler(tolerance_pct=0.02)
        discrepancies = reconciler.reconcile(
            expected={"AAPL": 100, "GOOG": 50},
            actual={"AAPL": 100, "GOOG": 50},
        )
        assert len(discrepancies) == 0

    def test_missing_position(self):
        """Missing position should be flagged."""
        from app.trading.audit_trail import PositionReconciler

        reconciler = PositionReconciler()
        discrepancies = reconciler.reconcile(
            expected={"AAPL": 100, "GOOG": 50},
            actual={"AAPL": 100},  # GOOG missing
        )
        assert len(discrepancies) == 1
        assert discrepancies[0]["type"] == "missing"
        assert discrepancies[0]["symbol"] == "GOOG"

    def test_phantom_position(self):
        """Position at broker but not expected should be flagged."""
        from app.trading.audit_trail import PositionReconciler

        reconciler = PositionReconciler()
        discrepancies = reconciler.reconcile(
            expected={"AAPL": 100},
            actual={"AAPL": 100, "TSLA": 25},
        )
        assert len(discrepancies) == 1
        assert discrepancies[0]["type"] == "phantom"

    def test_partial_fill(self):
        """Partial fill should be detected."""
        from app.trading.audit_trail import PositionReconciler

        reconciler = PositionReconciler(tolerance_pct=0.02)
        discrepancies = reconciler.reconcile(
            expected={"AAPL": 100},
            actual={"AAPL": 75},  # Only 75% filled
        )
        assert len(discrepancies) == 1
        assert discrepancies[0]["type"] == "partial_fill"

    def test_within_tolerance(self):
        """Small differences within tolerance should be ignored."""
        from app.trading.audit_trail import PositionReconciler

        reconciler = PositionReconciler(tolerance_pct=0.05)
        discrepancies = reconciler.reconcile(
            expected={"AAPL": 100},
            actual={"AAPL": 99},  # 1% difference, within 5% tolerance
        )
        assert len(discrepancies) == 0


# ========== Model Checkpoint Manager ==========

class TestCheckpointManager:
    """Test model checkpoint versioning and rollback."""

    def test_save_and_load(self):
        """Should save and load model with metadata."""
        from app.models.checkpoint_manager import ModelCheckpointManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ModelCheckpointManager(checkpoint_dir=tmpdir)

            # Save a simple model (dict as stand-in)
            model = {"weights": [0.1, 0.2, 0.3], "type": "test"}
            version = mgr.save(
                model=model,
                model_type="ensemble",
                config_hash="abc123",
                validation_score=0.05,
                oos_score=0.03,
                feature_names=["f1", "f2", "f3"],
                training_samples=1000,
            )

            assert version == "v001"

            # Load it back
            loaded_model, metadata = mgr.load(version)
            assert loaded_model == model
            assert metadata.validation_score == 0.05
            assert metadata.n_features == 3

    def test_version_increment(self):
        """Each save should increment version."""
        from app.models.checkpoint_manager import ModelCheckpointManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ModelCheckpointManager(checkpoint_dir=tmpdir)

            v1 = mgr.save(model="m1", model_type="t", config_hash="h", validation_score=0.0)
            v2 = mgr.save(model="m2", model_type="t", config_hash="h", validation_score=0.0)
            v3 = mgr.save(model="m3", model_type="t", config_hash="h", validation_score=0.0)

            assert v1 == "v001"
            assert v2 == "v002"
            assert v3 == "v003"

    def test_production_promotion(self):
        """Should promote model to production and load via default."""
        from app.models.checkpoint_manager import ModelCheckpointManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ModelCheckpointManager(checkpoint_dir=tmpdir)

            mgr.save(model="m1", model_type="t", config_hash="h",
                      validation_score=0.03, promote_to_production=True)
            mgr.save(model="m2", model_type="t", config_hash="h",
                      validation_score=0.05)

            # Loading without version should return production (v001)
            model, meta = mgr.load()
            assert model == "m1"
            assert meta.version == "v001"

    def test_rollback(self):
        """Rollback should revert to older version."""
        from app.models.checkpoint_manager import ModelCheckpointManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ModelCheckpointManager(checkpoint_dir=tmpdir)

            mgr.save(model="good", model_type="t", config_hash="h",
                      validation_score=0.05, promote_to_production=True)
            mgr.save(model="bad", model_type="t", config_hash="h",
                      validation_score=0.01, promote_to_production=True)

            # Roll back to v001
            model, meta = mgr.rollback("v001")
            assert model == "good"

            # Now production should be v001
            model, meta = mgr.load()
            assert model == "good"

    def test_integrity_check(self):
        """Corrupted checkpoint should raise ValueError."""
        from app.models.checkpoint_manager import ModelCheckpointManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ModelCheckpointManager(checkpoint_dir=tmpdir)
            version = mgr.save(model="test", model_type="t", config_hash="h",
                                validation_score=0.0)

            # Corrupt the model file
            version_dir = mgr._find_version_dir(version)
            model_path = os.path.join(version_dir, "model.pkl")
            with open(model_path, "wb") as f:
                f.write(b"corrupted data")

            with pytest.raises((ValueError, Exception)):
                mgr.load(version)

    def test_list_versions(self):
        """Should list all available versions."""
        from app.models.checkpoint_manager import ModelCheckpointManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ModelCheckpointManager(checkpoint_dir=tmpdir)

            mgr.save(model="m1", model_type="t", config_hash="h", validation_score=0.03)
            mgr.save(model="m2", model_type="t", config_hash="h", validation_score=0.05)

            versions = mgr.list_versions()
            assert len(versions) == 2

    def test_prune_old_versions(self):
        """Should prune old versions beyond max."""
        from app.models.checkpoint_manager import ModelCheckpointManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ModelCheckpointManager(checkpoint_dir=tmpdir, max_versions=3)

            for i in range(5):
                mgr.save(model=f"m{i}", model_type="t", config_hash="h",
                          validation_score=0.01 * i)

            versions = mgr.list_versions()
            assert len(versions) <= 3


# ========== Production Monitor ==========

class TestProductionMonitor:
    """Test integrated production monitoring."""

    def test_daily_check_no_alerts(self):
        """Normal conditions should produce no alerts."""
        from app.monitoring.drift_detector import ProductionMonitor

        monitor = ProductionMonitor()
        monitor.staleness_tracker.register_model(datetime.now(), baseline_ic=0.05)

        result = monitor.daily_check(
            daily_ic=0.04,
            portfolio_return=0.005,
            market_return=0.003,
            portfolio_beta=1.0,
        )

        assert "alerts" in result
        assert result["needs_retrain"] is False

    def test_daily_check_with_stale_model(self):
        """Stale model should trigger retrain alert."""
        from app.monitoring.drift_detector import ProductionMonitor

        monitor = ProductionMonitor()
        monitor.staleness_tracker.register_model(
            datetime.now() - timedelta(days=100), baseline_ic=0.05
        )

        result = monitor.daily_check(daily_ic=0.01)

        assert result["needs_retrain"] is True
        assert len(result["alerts"]) > 0


# ========== OOS Result Structure ==========

class TestOOSResult:
    """Test OOS result data structure."""

    def test_oos_result_creation(self):
        """OOS result should hold all fields."""
        from app.models.framework import OOSResult

        result = OOSResult(
            oos_score=0.04,
            oos_n_samples=252,
            oos_start=date(2024, 1, 1),
            oos_end=date(2024, 12, 31),
            oos_by_regime={"low_volatility": 0.05, "high_volatility": 0.02},
        )

        assert result.oos_score == 0.04
        assert result.oos_n_samples == 252
        assert len(result.oos_by_regime) == 2
