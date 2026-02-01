"""
Research Memo Generator.

Generates structured research memos from backtest results,
documenting hypothesis, methodology, results, and next steps.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
import json

from ..config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ResearchMemoContent:
    """Structured research memo content."""
    title: str
    date: str
    hypothesis: str
    data_description: str
    methodology: str
    results: str
    limitations: str
    next_steps: str
    full_memo: str


class ResearchMemoGenerator:
    """
    Generates professional research memos from backtest results.

    Can use LLM for enhanced writing or fall back to templates.
    """

    def __init__(self):
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

    def generate(
        self,
        backtest_result: Dict,
        model_config: Dict,
        feature_config: Dict,
        portfolio_config: Dict,
        use_llm: bool = True
    ) -> ResearchMemoContent:
        """
        Generate a research memo from backtest results.

        Args:
            backtest_result: Backtest performance data
            model_config: Model configuration
            feature_config: Feature engineering configuration
            portfolio_config: Portfolio construction configuration
            use_llm: Whether to use LLM for generation

        Returns:
            ResearchMemoContent with all sections
        """
        context = {
            "metrics": backtest_result.get("metrics", {}),
            "n_trades": backtest_result.get("n_trades", 0),
            "model_type": model_config.get("model_type", "ensemble"),
            "features": feature_config.get("enabled_features", []),
            "rebalance_freq": portfolio_config.get("rebalance_frequency", "weekly"),
            "max_position": portfolio_config.get("max_position_weight", 0.10),
        }

        if use_llm and self.settings.has_llm_key:
            return self._generate_with_llm(context)

        return self._generate_template(context)

    def _generate_with_llm(self, context: Dict) -> ResearchMemoContent:
        """Generate memo using LLM."""
        client = self._get_client()
        if client is None:
            return self._generate_template(context)

        prompt = f"""
        Write a professional quantitative research memo based on these backtest results.

        Context:
        {json.dumps(context, indent=2)}

        Write in a formal, objective tone appropriate for a hedge fund research document.
        Be specific about numbers and methodology.
        Highlight both strengths and weaknesses.
        Focus on statistical rigor and potential pitfalls.

        Format as JSON with these keys:
        - title: A descriptive title for the research
        - hypothesis: What market inefficiency or factor is being exploited?
        - data_description: What data was used? What are its limitations?
        - methodology: How was the strategy constructed? What models and techniques?
        - results: What were the key performance metrics? How should they be interpreted?
        - limitations: What are the caveats? What could go wrong in live trading?
        - next_steps: What experiments or improvements should be explored?
        """

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a senior quantitative researcher writing a formal research memo. Be precise, rigorous, and objective. Avoid hype or overconfidence."
                    },
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                max_tokens=2000
            )

            result = json.loads(response.choices[0].message.content)

            # Build full memo
            full_memo = self._format_full_memo(result)

            return ResearchMemoContent(
                title=result.get("title", "Research Memo"),
                date=datetime.now().strftime("%Y-%m-%d"),
                hypothesis=result.get("hypothesis", ""),
                data_description=result.get("data_description", ""),
                methodology=result.get("methodology", ""),
                results=result.get("results", ""),
                limitations=result.get("limitations", ""),
                next_steps=result.get("next_steps", ""),
                full_memo=full_memo
            )

        except Exception as e:
            logger.warning(f"LLM memo generation failed: {e}")
            return self._generate_template(context)

    def _generate_template(self, context: Dict) -> ResearchMemoContent:
        """Generate memo using templates."""
        metrics = context.get("metrics", {})
        sharpe = metrics.get("sharpe_ratio", 0)
        cagr = metrics.get("cagr", 0)
        max_dd = metrics.get("max_drawdown", 0)
        total_return = metrics.get("total_return", 0)

        title = f"Factor Strategy Analysis: {context.get('model_type', 'Ensemble')} Model"

        hypothesis = f"""
This strategy hypothesizes that a combination of price-based factors
(momentum, volatility, mean reversion) contains predictive information
about future stock returns. We use a {context.get('model_type', 'ensemble')}
model to combine these signals and construct a diversified portfolio.

The key assumption is that these patterns, documented in academic literature,
persist in markets due to behavioral biases and structural constraints.
        """.strip()

        data_description = f"""
**Universe**: Liquid US equities (large/mid cap)
**Period**: As specified in configuration
**Frequency**: Daily OHLCV data
**Source**: Stooq/Yahoo Finance (free data)

**Data Limitations**:
- Survivorship bias: Delisted stocks not included
- Corporate actions: May not be fully adjusted
- Volume data: May be incomplete for some securities
- Point-in-time: Some data may be restated
        """.strip()

        methodology = f"""
**Features**:
{', '.join(context.get('features', ['returns', 'momentum', 'volatility']))}

All features are lagged by at least 1 day to prevent look-ahead bias.
Features are cross-sectionally ranked to improve stationarity.

**Model**:
- Type: {context.get('model_type', 'Ensemble')}
- Validation: Walk-forward with embargo period
- Training window: Expanding window

**Portfolio Construction**:
- Rebalancing: {context.get('rebalance_freq', 'Weekly')}
- Maximum position: {context.get('max_position', 0.10):.0%}
- Optimization: Mean-variance with Ledoit-Wolf covariance
- Risk overlay: Volatility targeting, drawdown limits

**Transaction Costs**:
- Commission: 10 bps
- Slippage: 5 bps estimated
        """.strip()

        # Interpret results
        if sharpe > 1.5:
            perf_quality = "Strong risk-adjusted returns, though unusually high - verify no leakage"
        elif sharpe > 1.0:
            perf_quality = "Good risk-adjusted returns"
        elif sharpe > 0.5:
            perf_quality = "Modest risk-adjusted returns, typical for equity factors"
        else:
            perf_quality = "Weak risk-adjusted returns, may not be tradeable after costs"

        if abs(max_dd) > 0.25:
            dd_quality = "Significant drawdown - may be uncomfortable for many investors"
        elif abs(max_dd) > 0.15:
            dd_quality = "Moderate drawdown within typical equity strategy range"
        else:
            dd_quality = "Low drawdown, suggesting either conservative positioning or favorable backtest period"

        results = f"""
**Key Metrics**:
- Total Return: {total_return:.1%}
- CAGR: {cagr:.1%}
- Sharpe Ratio: {sharpe:.2f}
- Maximum Drawdown: {max_dd:.1%}
- Number of Trades: {context.get('n_trades', 0)}

**Interpretation**:
{perf_quality}

{dd_quality}

**Benchmark Comparison**:
Alpha and information ratio should be examined to understand
active return generation beyond market exposure.
        """.strip()

        limitations = f"""
**Critical Caveats**:

1. **Backtest vs Live Trading**: Expect 30-50% performance degradation in live trading
   due to execution costs, timing differences, and market impact not fully captured.

2. **Data Quality**: Free data sources have known issues including survivorship bias
   and potential errors. Results should be verified with higher-quality data.

3. **Overfitting Risk**: The model may have captured patterns specific to the
   backtest period that don't generalize to future markets.

4. **Regime Dependence**: Strategy performance may vary significantly across
   market regimes (bull/bear, high/low volatility, etc.).

5. **Capacity Constraints**: As strategy size grows, market impact will erode returns.
   This analysis does not estimate capacity limits.

6. **Factor Crowding**: If many market participants use similar strategies,
   expected returns may be compressed.
        """.strip()

        next_steps = f"""
1. **Robustness Testing**:
   - Test on different time periods (particularly crisis periods like 2008, 2020)
   - Increase transaction costs by 2x to stress-test profitability
   - Analyze performance by market regime

2. **Feature Analysis**:
   - Examine feature importance stability over time
   - Test alternative feature definitions
   - Investigate feature correlations and redundancy

3. **Model Enhancements**:
   - Try alternative models (linear vs. tree-based)
   - Experiment with different ensemble approaches
   - Investigate non-linear interactions

4. **Risk Management**:
   - Analyze tail behavior and extreme events
   - Test alternative position sizing approaches
   - Implement more sophisticated drawdown controls

5. **Paper Trading**:
   - Before any live trading, run paper trading for 3-6 months
   - Track slippage and execution quality
   - Compare realized vs. expected performance
        """.strip()

        # Format full memo
        sections = {
            "title": title,
            "hypothesis": hypothesis,
            "data_description": data_description,
            "methodology": methodology,
            "results": results,
            "limitations": limitations,
            "next_steps": next_steps
        }

        full_memo = self._format_full_memo(sections)

        return ResearchMemoContent(
            title=title,
            date=datetime.now().strftime("%Y-%m-%d"),
            hypothesis=hypothesis,
            data_description=data_description,
            methodology=methodology,
            results=results,
            limitations=limitations,
            next_steps=next_steps,
            full_memo=full_memo
        )

    def _format_full_memo(self, sections: Dict) -> str:
        """Format all sections into a complete memo."""
        return f"""
# {sections.get('title', 'Research Memo')}

**Date**: {datetime.now().strftime('%Y-%m-%d')}
**Author**: QuantLab Research System
**Classification**: For Educational Purposes Only

---

## Executive Summary

This memo documents the development and backtesting of a quantitative
equity strategy. The results are presented for educational purposes
and should not be construed as investment advice.

---

## 1. Hypothesis

{sections.get('hypothesis', '')}

---

## 2. Data Description

{sections.get('data_description', '')}

---

## 3. Methodology

{sections.get('methodology', '')}

---

## 4. Results

{sections.get('results', '')}

---

## 5. Limitations and Caveats

{sections.get('limitations', '')}

---

## 6. Next Steps

{sections.get('next_steps', '')}

---

## Disclaimer

This research is for EDUCATIONAL PURPOSES ONLY. It does not constitute
financial advice and should not be used for investment decisions.
Past performance does not indicate future results. Backtested results
are subject to significant biases and limitations.

---
        """.strip()
