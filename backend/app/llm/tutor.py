"""
Quant Tutor - Interactive learning about quantitative finance.

Provides structured lessons, glossary, and contextual help.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class Lesson:
    """A learning module."""
    id: str
    title: str
    difficulty: str  # beginner, intermediate, advanced
    category: str
    content: str
    key_concepts: List[str]
    pitfalls: List[str]
    next_lessons: List[str]


class QuantTutor:
    """
    Interactive quant tutor providing structured learning.

    Lessons are organized by topic and difficulty, covering:
    - Data and markets
    - Feature engineering
    - Machine learning for finance
    - Portfolio theory
    - Risk management
    - Backtesting best practices
    """

    def __init__(self):
        self.lessons = self._load_lessons()
        self.glossary = self._load_glossary()

    def get_lesson(self, lesson_id: str) -> Optional[Lesson]:
        """Get a specific lesson by ID."""
        return self.lessons.get(lesson_id)

    def list_lessons(self, category: Optional[str] = None) -> List[Lesson]:
        """List all lessons, optionally filtered by category."""
        lessons = list(self.lessons.values())
        if category:
            lessons = [l for l in lessons if l.category == category]
        return lessons

    def get_glossary_term(self, term: str) -> Optional[Dict]:
        """Look up a term in the glossary."""
        return self.glossary.get(term.lower())

    def get_contextual_help(self, context: str) -> Dict:
        """Get help based on current context (what user is doing)."""
        help_map = {
            "data": {
                "title": "Working with Market Data",
                "tips": [
                    "Always check data quality before modeling",
                    "Be aware of survivorship bias in historical data",
                    "Use adjusted prices for returns, unadjusted for volume analysis",
                ],
                "relevant_lessons": ["data_quality", "survivorship_bias"],
            },
            "features": {
                "title": "Feature Engineering",
                "tips": [
                    "Lag all features by at least 1 day to prevent leakage",
                    "Use cross-sectional ranking for more robust features",
                    "Start simple - complex features often don't add value",
                ],
                "relevant_lessons": ["feature_engineering", "leakage_prevention"],
            },
            "model": {
                "title": "Model Training",
                "tips": [
                    "Use walk-forward validation, not random train/test splits",
                    "Small positive correlations (0.02-0.05) are normal and useful",
                    "Beware of overfitting - if train >> validation, you're overfitting",
                ],
                "relevant_lessons": ["ml_finance", "validation"],
            },
            "portfolio": {
                "title": "Portfolio Construction",
                "tips": [
                    "Use shrinkage estimators for covariance (e.g., Ledoit-Wolf)",
                    "Apply position limits to avoid concentration risk",
                    "Consider turnover costs in optimization",
                ],
                "relevant_lessons": ["portfolio_optimization", "risk_management"],
            },
            "backtest": {
                "title": "Backtesting",
                "tips": [
                    "Include realistic transaction costs (10+ bps)",
                    "Test on out-of-sample periods",
                    "Expect 30-50% degradation vs backtest in live trading",
                ],
                "relevant_lessons": ["backtest_pitfalls", "transaction_costs"],
            },
        }

        return help_map.get(context, help_map["data"])

    def _load_lessons(self) -> Dict[str, Lesson]:
        """Load all lessons."""
        return {
            "intro_quant": Lesson(
                id="intro_quant",
                title="Introduction to Quantitative Investing",
                difficulty="beginner",
                category="fundamentals",
                content="""
# What is Quantitative Investing?

Quantitative investing uses mathematical models and data analysis to make investment decisions,
rather than relying solely on human judgment and intuition.

## Key Principles

1. **Systematic Process**: Decisions follow a well-defined, repeatable process
2. **Data-Driven**: Conclusions are based on empirical evidence, not stories
3. **Risk Management**: Quantifiable risk metrics guide position sizing
4. **Scalability**: Models can evaluate thousands of securities simultaneously

## The Quant Research Process

1. **Hypothesis Formation**: What market inefficiency are we exploiting?
2. **Data Collection**: Gather relevant, clean data
3. **Feature Engineering**: Transform raw data into predictive signals
4. **Model Development**: Build and validate predictive models
5. **Portfolio Construction**: Convert predictions to positions
6. **Execution**: Trade efficiently with minimal market impact
7. **Monitoring**: Track performance and adapt

## Common Misconceptions

- **"Quants predict the future"**: No - we estimate probabilities and manage risk
- **"More data = better models"**: Quality matters more than quantity
- **"Complex models are better"**: Simple, robust models often outperform
                """.strip(),
                key_concepts=["alpha", "risk-adjusted returns", "factor investing", "systematic trading"],
                pitfalls=[
                    "Confusing backtested returns with expected future returns",
                    "Ignoring transaction costs and market impact",
                    "Overfitting to historical data",
                ],
                next_lessons=["data_quality", "feature_engineering"]
            ),

            "data_quality": Lesson(
                id="data_quality",
                title="Data Quality and Pitfalls",
                difficulty="beginner",
                category="data",
                content="""
# Data Quality in Quantitative Research

Poor data quality is the #1 cause of failed trading strategies.
Understanding data limitations is essential.

## Common Data Issues

### 1. Survivorship Bias
Historical databases often only include stocks that still exist today.
Delisted companies (often poor performers) are excluded, inflating backtested returns.

**Example**: If you backtest a strategy from 2000, you won't see Enron, Lehman Brothers,
or other companies that went bankrupt. Your strategy looks better than reality.

### 2. Look-Ahead Bias
Using information that wouldn't have been available at the time of trading.

**Examples**:
- Using final quarterly earnings before they were announced
- Using end-of-day prices for intraday decisions
- Point-in-time data vs restated data

### 3. Data Errors
- Missing data points
- Incorrect corporate action adjustments
- Stale prices (especially for illiquid securities)

## Best Practices

1. **Document data sources**: Know where your data comes from
2. **Verify against multiple sources**: Cross-check critical data points
3. **Use point-in-time data**: Only use information available at each historical point
4. **Handle missing data explicitly**: Don't just forward-fill without understanding why
                """.strip(),
                key_concepts=["survivorship bias", "look-ahead bias", "point-in-time data", "data cleaning"],
                pitfalls=[
                    "Assuming free data is accurate",
                    "Not verifying adjusted prices",
                    "Ignoring the impact of missing data",
                ],
                next_lessons=["feature_engineering", "leakage_prevention"]
            ),

            "feature_engineering": Lesson(
                id="feature_engineering",
                title="Feature Engineering for Finance",
                difficulty="intermediate",
                category="features",
                content="""
# Feature Engineering for Quantitative Finance

Features (also called factors or signals) are the inputs to predictive models.
Good feature engineering is often more important than model choice.

## Common Feature Categories

### 1. Price/Return Features
- **Momentum**: Past returns over various horizons (1m, 3m, 6m, 12m)
- **Mean Reversion**: Distance from moving averages
- **Volatility**: Rolling standard deviation of returns

### 2. Volume Features
- **Liquidity**: Average daily dollar volume
- **Volume Trends**: Recent volume vs historical average
- **Volume-Price Relationship**: Accumulation/distribution patterns

### 3. Risk Features
- **Beta**: Sensitivity to market returns
- **Idiosyncratic Volatility**: Stock-specific risk
- **Correlation**: Co-movement with other assets

## Critical Rule: Feature Lag

**ALL features must be computed using only past data.**

At time t, features should only use information from t-1 or earlier.
Using current-day information to predict current-day returns is leakage.

## Standardization

Cross-sectional ranking (ranking stocks against each other each day) is often
more robust than absolute values because:
1. It handles outliers naturally
2. It's stationary across time
3. It captures relative attractiveness
                """.strip(),
                key_concepts=["momentum", "mean reversion", "feature lag", "cross-sectional ranking"],
                pitfalls=[
                    "Using same-day information (leakage)",
                    "Not handling outliers",
                    "Creating too many correlated features",
                ],
                next_lessons=["leakage_prevention", "ml_finance"]
            ),

            "leakage_prevention": Lesson(
                id="leakage_prevention",
                title="Preventing Data Leakage",
                difficulty="intermediate",
                category="features",
                content="""
# Data Leakage: The Silent Strategy Killer

Data leakage occurs when your model has access to information it wouldn't have in live trading.
It's the most common cause of strategies that work in backtest but fail in production.

## Types of Leakage

### 1. Feature Leakage
Using future information in feature construction.

**Bad**: `feature_t = close_t - close_t-1` (uses today's close)
**Good**: `feature_t = close_t-1 - close_t-2` (uses yesterday's data)

### 2. Target Leakage
Target variable contains information from the feature period.

**Bad**: Predicting `return_t` using `feature_t` (overlap)
**Good**: Predicting `return_t+1` using `feature_t` (no overlap)

### 3. Validation Leakage
Using future data in model selection or hyperparameter tuning.

**Bad**: Standard k-fold cross-validation (randomizes time)
**Good**: Walk-forward validation (always train on past, test on future)

## How to Detect Leakage

1. **Suspiciously good results**: If Sharpe > 3, something is likely wrong
2. **Performance cliff**: Great backtest, terrible paper trading
3. **Lag sensitivity**: Performance drops dramatically when you add feature lags
4. **Autocorrelation test**: Regress features on future returns at various lags

## Prevention Strategies

1. Always lag features by at least 1 day
2. Use an embargo period between training and validation
3. Never use data from the future, even indirectly
4. Be paranoid - assume leakage exists until proven otherwise
                """.strip(),
                key_concepts=["feature leakage", "target leakage", "validation leakage", "embargo period"],
                pitfalls=[
                    "Not lagging features",
                    "Using random train/test splits",
                    "Peeking at test data during development",
                ],
                next_lessons=["ml_finance", "validation"]
            ),

            "ml_finance": Lesson(
                id="ml_finance",
                title="Machine Learning for Finance",
                difficulty="intermediate",
                category="models",
                content="""
# Machine Learning for Financial Prediction

ML in finance is different from typical ML applications due to:
- Low signal-to-noise ratio
- Non-stationarity (markets change over time)
- Transaction costs that eat into small edges

## Appropriate Expectations

In equity markets:
- **Weak signal**: Rank correlation 0.01-0.02
- **Moderate signal**: Rank correlation 0.02-0.05
- **Strong signal**: Rank correlation 0.05-0.10

Anything above 0.10 should be scrutinized for leakage!

## Model Selection

### Linear Models (Ridge, Lasso, ElasticNet)
- **Pros**: Interpretable, stable, robust to overfitting
- **Cons**: Can't capture nonlinear patterns
- **When to use**: As a baseline, when interpretability matters

### Tree-Based Models (Random Forest, Gradient Boosting)
- **Pros**: Capture nonlinear relationships, handle interactions
- **Cons**: Prone to overfitting, less interpretable
- **When to use**: When you have sufficient data and regularization

### Ensemble Models
- **Pros**: Often more robust than single models
- **Cons**: Complexity, harder to interpret
- **When to use**: For production strategies

## Regularization is Essential

Financial data is noisy. Without regularization:
- Models memorize noise
- Training performance >> validation performance
- Live trading fails

Always use:
- L1/L2 regularization for linear models
- Max depth, min samples for trees
- Early stopping
                """.strip(),
                key_concepts=["signal-to-noise ratio", "regularization", "ensemble methods", "non-stationarity"],
                pitfalls=[
                    "Expecting high accuracy (this isn't image classification)",
                    "Using complex models without sufficient regularization",
                    "Not accounting for transaction costs in evaluation",
                ],
                next_lessons=["validation", "portfolio_optimization"]
            ),

            "validation": Lesson(
                id="validation",
                title="Time Series Validation",
                difficulty="intermediate",
                category="models",
                content="""
# Proper Validation for Time Series

Standard ML validation (random train/test split) doesn't work for finance.
Markets are temporal - using future data to validate is leakage.

## Walk-Forward Validation

The gold standard for financial ML:

1. Train on historical window (e.g., 3 years)
2. Skip an embargo period (e.g., 5 days)
3. Validate on next period (e.g., 3 months)
4. Move forward and repeat

```
Time →
[====TRAIN====]--EMBARGO--[VAL]
      [====TRAIN====]--EMBARGO--[VAL]
            [====TRAIN====]--EMBARGO--[VAL]
```

## Key Concepts

### Embargo Period
A gap between training and validation to prevent information leakage from:
- Overlapping return windows
- Serial correlation in returns

### Expanding vs Rolling Window
- **Expanding**: Use all available history (more data, but distant past may be irrelevant)
- **Rolling**: Fixed window size (more recent data only)

## Metrics to Track

1. **Rank Correlation (IC)**: Correlation between predictions and actual returns
2. **IC Stability**: Standard deviation of IC across folds
3. **Hit Rate**: Percentage of positive folds
4. **Train/Validation Gap**: Measure of overfitting

## Red Flags

- IC > 0.10 (likely leakage)
- Train IC >> Validation IC (overfitting)
- IC varies wildly across folds (unstable signal)
- Declining IC over time (signal decay)
                """.strip(),
                key_concepts=["walk-forward validation", "embargo period", "information coefficient", "expanding window"],
                pitfalls=[
                    "Using random cross-validation",
                    "Not using an embargo period",
                    "Ignoring temporal patterns in performance",
                ],
                next_lessons=["portfolio_optimization", "risk_management"]
            ),

            "portfolio_optimization": Lesson(
                id="portfolio_optimization",
                title="Portfolio Optimization",
                difficulty="advanced",
                category="portfolio",
                content="""
# From Signals to Portfolios

Converting model predictions to portfolio weights involves:
1. Expected return estimation
2. Risk estimation
3. Optimization with constraints

## Mean-Variance Optimization

Classic Markowitz portfolio theory:
- Maximize: Expected Return - λ × Variance
- Subject to: Constraints (weights sum to 1, position limits, etc.)

## Practical Challenges

### 1. Estimation Error
Expected returns and covariances are estimated with error.
Small errors → large weight changes.

**Solution**: Use shrinkage estimators (Ledoit-Wolf for covariance)

### 2. Turnover
Optimal portfolios change constantly, but trading costs money.

**Solution**: Add turnover constraints or penalties

### 3. Concentration
Optimization may concentrate in few positions.

**Solution**: Position and sector limits

## Alternative Approaches

### Risk Parity
Allocate to equalize risk contribution from each position.
More defensive, doesn't require return forecasts.

### Simple Ranking
Top N stocks by signal, equal weighted.
Often surprisingly competitive with optimization.

## Position Sizing

**Volatility Targeting**: Scale positions so portfolio volatility matches target
- High vol regime → smaller positions
- Low vol regime → larger positions
                """.strip(),
                key_concepts=["mean-variance optimization", "shrinkage estimation", "risk parity", "volatility targeting"],
                pitfalls=[
                    "Ignoring estimation error",
                    "Not considering turnover costs",
                    "Over-optimizing on historical data",
                ],
                next_lessons=["risk_management", "backtest_pitfalls"]
            ),

            "backtest_pitfalls": Lesson(
                id="backtest_pitfalls",
                title="Backtesting Pitfalls",
                difficulty="advanced",
                category="backtest",
                content="""
# Why Backtests Lie

Backtests almost always overstate real performance. Understanding why helps set realistic expectations.

## Common Pitfalls

### 1. Overfitting
Testing many strategies and choosing the best one.
Some will look good by chance.

**Rule of thumb**: Divide expected Sharpe by sqrt(number of strategies tested)

### 2. Survivorship Bias
Only including stocks that survived to today.

**Impact**: Can inflate returns by 1-2% annually

### 3. Look-Ahead Bias
Using information not available at the time.

**Examples**: Point-in-time financials, index reconstitution

### 4. Unrealistic Transaction Costs
Not modeling spreads, market impact, and timing.

**Reality check**: Costs should be at least 10bps for large caps, more for small caps

### 5. Ignoring Market Microstructure
- Can't always trade at close price
- Large orders move markets
- Illiquid stocks are harder to trade

## Reality Adjustment

Expect 30-50% performance degradation from backtest to live trading.

If your backtest Sharpe is 1.0, expect 0.5-0.7 in practice.

## Best Practices

1. Use out-of-sample periods
2. Test on crisis periods (2008, 2020)
3. Double your estimated costs
4. Paper trade before real money
5. Start with small positions
                """.strip(),
                key_concepts=["overfitting", "survivorship bias", "transaction costs", "market impact"],
                pitfalls=[
                    "Trusting backtest results at face value",
                    "Testing too many strategies",
                    "Ignoring implementation details",
                ],
                next_lessons=["risk_management"]
            ),

            "risk_management": Lesson(
                id="risk_management",
                title="Risk Management",
                difficulty="advanced",
                category="risk",
                content="""
# Risk Management for Quant Strategies

Risk management is about survival first, profits second.

## Key Risk Metrics

### Volatility
Standard deviation of returns, annualized.
- **Target**: Typically 10-20% for equity strategies
- **Monitoring**: Daily rolling volatility

### Maximum Drawdown
Largest peak-to-trough decline.
- **Limit**: Usually 15-25% before intervention
- **Reality**: Larger drawdowns are more common than models predict

### Value at Risk (VaR)
"Loss that won't be exceeded X% of the time"
- Useful for sizing
- But underestimates tail risk

### Beta
Sensitivity to market moves.
- Beta 1.0 = moves with market
- Lower beta = more defensive

## Risk Controls

### Position Limits
- **Single stock**: Max 5-10% of portfolio
- **Sector**: Max 20-30% of portfolio
- **Long/short**: Define net exposure limits

### Drawdown Rules
- **Warning**: At 10% drawdown, reduce risk
- **Stop**: At 20% drawdown, significant de-risking
- **Critical**: At 30%, may halt trading

### Volatility Targeting
Scale positions inversely to recent volatility:
- High vol → smaller positions
- Low vol → larger positions

## Remember

- Risk management is not optional
- Markets have fat tails (extreme events more common than normal distribution)
- Correlations increase in crises (diversification fails when you need it most)
- Liquidity evaporates in stress (can't exit when you want to)
                """.strip(),
                key_concepts=["volatility", "maximum drawdown", "VaR", "position limits", "volatility targeting"],
                pitfalls=[
                    "Ignoring tail risk",
                    "Assuming normal distributions",
                    "Overconfidence in diversification",
                ],
                next_lessons=["intro_quant"]
            ),
        }

    def _load_glossary(self) -> Dict[str, Dict]:
        """Load glossary of terms."""
        return {
            "alpha": {
                "term": "Alpha",
                "definition": "The excess return of an investment relative to a benchmark, after adjusting for risk. Represents the 'skill' component of returns.",
                "example": "If a strategy returns 15% when the market returns 10% and beta is 1.0, alpha is 5%.",
                "related": ["beta", "sharpe ratio"]
            },
            "beta": {
                "term": "Beta",
                "definition": "A measure of how much an asset moves relative to the market. Beta of 1 means it moves with the market.",
                "example": "A stock with beta 1.5 tends to move 1.5% for every 1% market move.",
                "related": ["alpha", "systematic risk"]
            },
            "sharpe ratio": {
                "term": "Sharpe Ratio",
                "definition": "Risk-adjusted return calculated as (Return - Risk-Free Rate) / Volatility. Higher is better.",
                "example": "A strategy with 10% return, 4% risk-free rate, and 12% volatility has Sharpe = 0.5",
                "related": ["sortino ratio", "volatility"]
            },
            "drawdown": {
                "term": "Drawdown",
                "definition": "The decline from a peak to a trough in portfolio value, expressed as a percentage.",
                "example": "If a portfolio goes from $100K to $80K, the drawdown is 20%.",
                "related": ["maximum drawdown", "recovery time"]
            },
            "momentum": {
                "term": "Momentum",
                "definition": "The tendency for past winners to continue outperforming and past losers to continue underperforming.",
                "example": "12-1 momentum: stocks that performed well over the last 12 months (excluding the most recent month) tend to continue outperforming.",
                "related": ["mean reversion", "factor investing"]
            },
            "look-ahead bias": {
                "term": "Look-Ahead Bias",
                "definition": "Using information in backtesting that would not have been available at the time of the historical trade.",
                "example": "Using end-of-day prices to make decisions that would have been made during market hours.",
                "related": ["survivorship bias", "data leakage"]
            },
            "survivorship bias": {
                "term": "Survivorship Bias",
                "definition": "The tendency to focus on existing entities (surviving companies) while overlooking those that no longer exist (delisted or bankrupt companies).",
                "example": "Backtesting on today's S&P 500 ignores companies that were in the index but went bankrupt.",
                "related": ["look-ahead bias", "selection bias"]
            },
            "walk-forward validation": {
                "term": "Walk-Forward Validation",
                "definition": "A validation method where models are trained on historical data and tested on subsequent data, then the window moves forward in time.",
                "example": "Train on 2015-2017, test on 2018. Then train on 2016-2018, test on 2019. Repeat.",
                "related": ["cross-validation", "out-of-sample testing"]
            },
            "factor": {
                "term": "Factor",
                "definition": "A characteristic of stocks that explains returns. Common factors include value, momentum, size, and quality.",
                "example": "The value factor captures the tendency of cheap stocks (low P/E) to outperform expensive stocks.",
                "related": ["alpha", "factor investing", "risk premium"]
            },
            "information coefficient": {
                "term": "Information Coefficient (IC)",
                "definition": "The correlation between predicted and actual returns. Measures signal quality.",
                "example": "An IC of 0.05 means a weak but potentially useful predictive relationship.",
                "related": ["rank correlation", "signal strength"]
            },
        }
