"""
LLM-powered explanations for quant concepts.

This module provides educational explanations for:
- Data processing steps
- Feature engineering decisions
- Model behavior
- Portfolio construction
- Backtest results

Works with or without an LLM API key - falls back to templates.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import logging
import json

from ..config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ExplanationConfig:
    """Configuration for explanations."""
    use_llm: bool = True
    detail_level: str = "intermediate"  # beginner, intermediate, advanced
    include_pitfalls: bool = True
    include_experiments: bool = True


class QuantExplainer:
    """
    Generates educational explanations for quant concepts.

    If an LLM API key is available, uses it for dynamic explanations.
    Otherwise, uses comprehensive templates.
    """

    def __init__(self, config: Optional[ExplanationConfig] = None):
        self.config = config or ExplanationConfig()
        self.settings = get_settings()
        self._client = None

    def _get_client(self):
        """Lazy load OpenAI client."""
        if self._client is None and self.settings.has_llm_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.settings.openai_api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")
        return self._client

    def explain_data_ingestion(
        self,
        tickers: List[str],
        date_range: tuple,
        data_quality: Dict[str, Any]
    ) -> Dict[str, str]:
        """Explain data ingestion step."""
        context = {
            "n_tickers": len(tickers),
            "start_date": str(date_range[0]),
            "end_date": str(date_range[1]),
            "data_quality": data_quality
        }

        if self._should_use_llm():
            return self._llm_explain("data_ingestion", context)

        return self._template_explain_data(context)

    def explain_features(
        self,
        feature_config: Dict,
        feature_stats: Dict[str, Any]
    ) -> Dict[str, str]:
        """Explain feature engineering."""
        context = {
            "features": list(feature_config.get("enabled_features", [])),
            "n_features": feature_stats.get("n_features", 0),
            "missing_pct": feature_stats.get("missing_pct", 0),
        }

        if self._should_use_llm():
            return self._llm_explain("features", context)

        return self._template_explain_features(context)

    def explain_model(
        self,
        model_type: str,
        validation_result: Dict,
        feature_importance: Dict[str, float]
    ) -> Dict[str, str]:
        """Explain model training and validation."""
        # Get top features
        sorted_imp = sorted(
            feature_importance.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )[:10]

        context = {
            "model_type": model_type,
            "val_score": validation_result.get("mean_validation_score", 0),
            "train_score": validation_result.get("mean_train_score", 0),
            "n_folds": validation_result.get("n_folds", 0),
            "top_features": sorted_imp,
        }

        if self._should_use_llm():
            return self._llm_explain("model", context)

        return self._template_explain_model(context)

    def explain_portfolio(
        self,
        weights: Dict[str, float],
        risk_metrics: Dict,
        constraints: Dict
    ) -> Dict[str, str]:
        """Explain portfolio construction."""
        context = {
            "n_positions": sum(1 for w in weights.values() if w > 0.01),
            "max_weight": max(weights.values()) if weights else 0,
            "concentration": sum(w**2 for w in weights.values()),
            "risk_metrics": risk_metrics,
            "constraints": constraints,
        }

        if self._should_use_llm():
            return self._llm_explain("portfolio", context)

        return self._template_explain_portfolio(context)

    def explain_backtest(
        self,
        metrics: Dict,
        trades: List[Dict]
    ) -> Dict[str, str]:
        """Explain backtest results."""
        context = {
            "sharpe": metrics.get("sharpe_ratio", 0),
            "cagr": metrics.get("cagr", 0),
            "max_dd": metrics.get("max_drawdown", 0),
            "n_trades": len(trades),
            "total_return": metrics.get("total_return", 0),
        }

        if self._should_use_llm():
            return self._llm_explain("backtest", context)

        return self._template_explain_backtest(context)

    def _should_use_llm(self) -> bool:
        """Check if LLM should be used."""
        return self.config.use_llm and self.settings.has_llm_key

    def _llm_explain(self, topic: str, context: Dict) -> Dict[str, str]:
        """Generate explanation using LLM."""
        client = self._get_client()
        if client is None:
            return self._get_template_explanation(topic, context)

        prompts = {
            "data_ingestion": f"""
                Explain the data ingestion step for a quant research project.
                Context: {json.dumps(context)}

                Provide:
                1. A brief explanation of what happened
                2. Key pitfalls to watch for (survivorship bias, data quality)
                3. 2-3 experiments to try

                Format as JSON with keys: explanation, pitfalls, experiments
            """,
            "features": f"""
                Explain feature engineering for a stock ranking model.
                Context: {json.dumps(context)}

                Cover:
                1. What features were computed and why
                2. Pitfalls (leakage, overfitting to features)
                3. Experiments to try

                Format as JSON with keys: explanation, pitfalls, experiments
            """,
            "model": f"""
                Explain ML model training for stock prediction.
                Context: {json.dumps(context)}

                Cover:
                1. Model performance interpretation
                2. Overfitting and leakage warnings
                3. Experiments to try

                Format as JSON with keys: explanation, pitfalls, experiments
            """,
            "portfolio": f"""
                Explain portfolio optimization and risk management.
                Context: {json.dumps(context)}

                Cover:
                1. How the portfolio was constructed
                2. Risk management considerations
                3. Experiments to try

                Format as JSON with keys: explanation, pitfalls, experiments
            """,
            "backtest": f"""
                Explain backtest results for a trading strategy.
                Context: {json.dumps(context)}

                Cover:
                1. Performance interpretation
                2. Common backtest pitfalls
                3. Experiments to try

                Format as JSON with keys: explanation, pitfalls, experiments
            """
        }

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a senior quant researcher teaching a data scientist. Be rigorous but accessible. Focus on practical insights and pitfalls."},
                    {"role": "user", "content": prompts.get(topic, prompts["data_ingestion"])}
                ],
                response_format={"type": "json_object"},
                max_tokens=1000
            )

            result = json.loads(response.choices[0].message.content)
            return result

        except Exception as e:
            logger.warning(f"LLM explanation failed: {e}")
            return self._get_template_explanation(topic, context)

    def _get_template_explanation(self, topic: str, context: Dict) -> Dict[str, str]:
        """Get template-based explanation."""
        method = getattr(self, f"_template_explain_{topic}", self._template_explain_data)
        return method(context)

    def _template_explain_data(self, context: Dict) -> Dict[str, str]:
        """Template explanation for data ingestion."""
        return {
            "explanation": f"""
Data ingestion loaded {context.get('n_tickers', 0)} tickers from {context.get('start_date')} to {context.get('end_date')}.

The data includes daily OHLCV (Open, High, Low, Close, Volume) prices. This is the foundation for all subsequent analysis.

Key considerations:
- Data is adjusted for splits and dividends (when available)
- Missing data has been forward-filled, which may introduce some staleness
- This is point-in-time data, meaning we only use information available at each date
            """.strip(),
            "pitfalls": [
                "Survivorship bias: We only see stocks that exist today. Delisted stocks are missing.",
                "Data quality: Free data sources may have errors or gaps. Verify critical analyses.",
                "Look-ahead bias: Ensure no future information leaks into historical analysis.",
            ],
            "experiments": [
                "Try different data sources (Stooq vs Yahoo) and compare results",
                "Analyze data quality: plot missing data patterns over time",
                "Check for obvious errors: negative prices, extreme returns (>50% daily)",
            ]
        }

    def _template_explain_features(self, context: Dict) -> Dict[str, str]:
        """Template explanation for features."""
        features = context.get("features", [])
        return {
            "explanation": f"""
Feature engineering created {context.get('n_features', 0)} features from raw price data.

Features computed: {', '.join(features)}

All features are LAGGED by at least 1 day to prevent look-ahead bias. At time t, features only use information available before market close on day t-1.

This is critical: using today's close to predict today's return is a common mistake that creates artificially good backtests.
            """.strip(),
            "pitfalls": [
                "Data leakage: The #1 cause of backtest failure. Always verify features are properly lagged.",
                "Overfitting to features: Too many features relative to samples leads to spurious patterns.",
                "Non-stationarity: Feature distributions change over time. What worked in 2015 may not work now.",
            ],
            "experiments": [
                "Run a leakage test: regress features on future returns at different lags",
                "Try cross-sectional vs time-series standardization",
                "Compute feature stability: how much do feature values change month-to-month?",
            ]
        }

    def _template_explain_model(self, context: Dict) -> Dict[str, str]:
        """Template explanation for model."""
        val_score = context.get("val_score", 0)
        train_score = context.get("train_score", 0)
        gap = train_score - val_score

        quality = "weak" if val_score < 0.02 else "moderate" if val_score < 0.05 else "strong"

        return {
            "explanation": f"""
Model type: {context.get('model_type', 'ensemble')}
Validation score: {val_score:.4f} (rank correlation)
Training score: {train_score:.4f}

Interpretation: A {quality} signal. In equity markets, even small positive correlations (0.02-0.05) can be economically meaningful after proper portfolio construction.

Top predictive features: {', '.join([f[0] for f in context.get('top_features', [])[:5]])}

{"Warning: Large train/validation gap suggests overfitting." if gap > 0.05 else "Train/validation gap is reasonable."}
            """.strip(),
            "pitfalls": [
                "Overfitting: High training score with low validation = model memorized noise",
                "Regime dependence: Model trained on bull markets may fail in bear markets",
                "Crowding: Popular factors (momentum, value) may become crowded and underperform",
            ],
            "experiments": [
                "Try different model types and compare (linear vs tree-based)",
                "Analyze performance by time period (is alpha consistent?)",
                "Test on out-of-sample crisis periods (2008, 2020)",
            ]
        }

    def _template_explain_portfolio(self, context: Dict) -> Dict[str, str]:
        """Template explanation for portfolio."""
        return {
            "explanation": f"""
Portfolio constructed with {context.get('n_positions', 0)} positions.
Maximum position weight: {context.get('max_weight', 0):.1%}
Concentration (HHI): {context.get('concentration', 0):.3f}

The portfolio uses mean-variance optimization with Ledoit-Wolf shrinkage for the covariance matrix. This is more stable than sample covariance, especially with limited data.

Constraints applied: {context.get('constraints', {})}
            """.strip(),
            "pitfalls": [
                "Optimization error: Mean-variance is sensitive to return estimates. Small errors = big weight changes.",
                "Turnover: Frequent rebalancing incurs costs. Ensure benefits exceed transaction costs.",
                "Concentration risk: Even with diversification, correlated positions can move together.",
            ],
            "experiments": [
                "Compare mean-variance vs risk parity allocation",
                "Test different rebalancing frequencies (daily vs weekly vs monthly)",
                "Analyze how sensitive weights are to small changes in expected returns",
            ]
        }

    def _template_explain_backtest(self, context: Dict) -> Dict[str, str]:
        """Template explanation for backtest."""
        sharpe = context.get("sharpe", 0)
        cagr = context.get("cagr", 0)
        max_dd = context.get("max_dd", 0)

        return {
            "explanation": f"""
Backtest Results Summary:
- Total Return: {context.get('total_return', 0):.1%}
- CAGR: {cagr:.1%}
- Sharpe Ratio: {sharpe:.2f}
- Maximum Drawdown: {max_dd:.1%}
- Number of Trades: {context.get('n_trades', 0)}

{"Good risk-adjusted returns (Sharpe > 1)" if sharpe > 1 else "Modest risk-adjusted returns" if sharpe > 0.5 else "Weak risk-adjusted returns"}

{"Manageable drawdown" if abs(max_dd) < 0.15 else "Significant drawdown - consider tighter risk limits"}
            """.strip(),
            "pitfalls": [
                "Backtests always look better than live trading. Expect 30-50% degradation.",
                "Survivorship bias: Returns may be inflated if delisted stocks are excluded.",
                "Transaction costs: Ensure costs are realistic (10+ bps for small positions).",
                "Data snooping: If you tested many strategies, some will look good by chance.",
            ],
            "experiments": [
                "Run Monte Carlo simulations with randomized entry/exit timing",
                "Test on different time periods (in-sample vs out-of-sample)",
                "Increase transaction costs by 2x and see if strategy still works",
                "Add realistic constraints: no trading on earnings, market open, etc.",
            ]
        }
