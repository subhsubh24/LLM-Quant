"""
Single-Pipeline, Multi-Strategy Composition Architecture.

Replaces the god-object pattern (MasterQuantBot + QuantBot) with:
  FeatureStore  -> [Strategy_1, Strategy_2, ...] -> RiskGate -> Executor

Components:
  feature_store.py       - Shared state: prices, returns, indicators, ML, regime
  risk_gate.py           - Drawdown, correlation, sizing, dynamic thresholds
  orchestrator.py        - Thin pipeline coordinator with same public API
  strategies/            - Pluggable strategy modules
"""

from .feature_store import FeatureStore
from .risk_gate import RiskGate
from .orchestrator import PipelineOrchestrator

__all__ = [
    "FeatureStore",
    "RiskGate",
    "PipelineOrchestrator",
]
