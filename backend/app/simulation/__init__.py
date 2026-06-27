"""
Institutional-Grade Simulation Engine.

Provides the full simulation stack for both traditional trading and prediction markets:

1. Monte Carlo Engine - GBM path simulation, binary contract pricing, multi-asset paths
2. Importance Sampling - Exponential tilting for rare/tail events (100-10,000x variance reduction)
3. Variance Reduction - Antithetic variates, control variates, stratified sampling (stackable)
4. Particle Filters - Sequential Monte Carlo for real-time Bayesian updating
5. Vine Copulas - C-vine, D-vine for high-dimensional dependency (d>5 contracts)
6. Agent-Based Models - Heterogeneous agent market simulation (informed/noise/MM)
7. Hierarchical Bayesian - Cross-market hyperparameter pooling, national swing models
8. Correlation Stress Testing - What-if correlation spikes, contagion analysis, stressed VaR

References:
- Glasserman (2003): "Monte Carlo Methods in Financial Engineering"
- Asmussen & Glynn (2007): "Stochastic Simulation: Algorithms and Analysis"
- Doucet, de Freitas & Gordon (2001): "Sequential Monte Carlo Methods in Practice"
- Aas et al. (2009): "Pair-copula constructions of multiple dependence"
- Gode & Sunder (1993): "Allocative Efficiency of Markets with Zero-Intelligence Traders"
- Gelman et al. (2013): "Bayesian Data Analysis" Ch. 5 (Hierarchical Models)
- Embrechts, McNeil & Straumann (2002): "Correlation and Dependence in Risk Management"
"""

from .monte_carlo import (
    MonteCarloEngine,
    BinaryContractPricer,
    MultiAssetSimulator,
    PathResult,
    BinaryContractResult,
)
from .importance_sampling import (
    ImportanceSampler,
    ExponentialTilter,
    RareEventEstimator,
)
from .variance_reduction import (
    VarianceReducer,
    AntitheticEngine,
    ControlVariateEngine,
    StratifiedEngine,
    StackedVarianceReduction,
)
from .particle_filter import (
    ParticleFilter,
    PredictionMarketFilter,
    MultiContractFilter,
    TradingRegimeFilter,
)
from .vine_copula import (
    VineCopula,
    CVine,
    DVine,
    PairCopula,
    CorrelatedContractSimulator,
)
from .agent_based import (
    AgentBasedMarket,
    InformedTrader,
    NoiseTrader,
    MarketMaker,
    PredictionMarketABM,
    TradingABM,
)
from .hierarchical_bayesian import (
    HierarchicalBayesianModel,
    NationalSwingModel,
    CategoryPoolingModel,
    HierarchicalEstimate,
    SwingModelResult,
)
from .correlation_stress import (
    CorrelationStressTester,
    StressScenarioResult,
    ContagionResult,
    StressTestReport,
)

__all__ = [
    # Monte Carlo
    "MonteCarloEngine", "BinaryContractPricer", "MultiAssetSimulator",
    "PathResult", "BinaryContractResult",
    # Importance Sampling
    "ImportanceSampler", "ExponentialTilter", "RareEventEstimator",
    # Variance Reduction
    "VarianceReducer", "AntitheticEngine", "ControlVariateEngine",
    "StratifiedEngine", "StackedVarianceReduction",
    # Particle Filters
    "ParticleFilter", "PredictionMarketFilter", "MultiContractFilter",
    "TradingRegimeFilter",
    # Vine Copulas
    "VineCopula", "CVine", "DVine", "PairCopula",
    "CorrelatedContractSimulator",
    # Agent-Based Models
    "AgentBasedMarket", "InformedTrader", "NoiseTrader", "MarketMaker",
    "PredictionMarketABM", "TradingABM",
    # Hierarchical Bayesian
    "HierarchicalBayesianModel", "NationalSwingModel", "CategoryPoolingModel",
    "HierarchicalEstimate", "SwingModelResult",
    # Correlation Stress Testing
    "CorrelationStressTester", "StressScenarioResult", "ContagionResult",
    "StressTestReport",
]
