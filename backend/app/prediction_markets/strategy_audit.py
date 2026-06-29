"""
Forensic Audit Harness for Cross-Market Logical-Consistency Strategies.

Answers the honest gating question for ROADMAP B5:
Do CrossMarketArbitrageStrategy and LogicalImplicationDetector actually FIRE
and find real, exploitable mispricing on real-shaped data?

This module is:
  - Pure and deterministic (no network calls, no randomness, no fitting)
  - Read-only with respect to strategies (no modifications)
  - Honest: if strategies fire rarely/never, that IS the finding

Usage:
    from backend.app.prediction_markets.strategy_audit import audit_strategies
    from backend.app.prediction_markets.strategies import CrossMarketArbitrageStrategy
    from backend.app.prediction_markets.advanced_strategies import LogicalImplicationDetector

    report = audit_strategies(markets, [strategy_a, strategy_b])
    print(report.to_dict())
"""

import json
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SignalRecord:
    """One fired signal from one strategy on one pair/set of markets."""
    strategy_name: str
    market_id: str          # The market the strategy flagged (ScanResult.market.id)
    market_question: str    # Human-readable question for the flagged market
    side: str               # "BUY" or "SELL"
    entry_price: float      # Price at signal time
    expected_value: float   # Strategy's claimed expected value
    edge: float             # Strategy's claimed edge (decimal)
    confidence: float       # Strategy's stated confidence (0-1)
    reason: str             # Strategy's explanation string
    data_source: str        # "real" | "synthetic_should_fire" | "synthetic_should_not_fire"


@dataclass(frozen=True)
class ForensicCheck:
    """
    Post-resolution forensic accuracy check for one signal.

    IMPORTANT: This is DESCRIPTIVE FORENSICS on resolved data, NOT a fitted or
    backtested edge claim.  We never fit parameters on the 54-record sample.
    The hit_rate is simply: did the strategy's recommended side resolve correctly?
    """
    strategy_name: str
    total_signals: int         # Signals with known resolution
    correct_signals: int       # Signals where strategy's side was correct
    hit_rate: Optional[float]  # correct / total (None if total == 0)
    false_positive_count: int  # Signals where strategy's side was wrong
    note: str                  # Honest caveat about this statistic


@dataclass(frozen=True)
class EdgeStats:
    """Distribution of edge values for signals fired by one strategy."""
    strategy_name: str
    count: int
    min_edge: Optional[float]
    median_edge: Optional[float]
    max_edge: Optional[float]


@dataclass(frozen=True)
class StrategyAuditResult:
    """Per-strategy audit summary."""
    strategy_name: str
    signals_fired: int
    distinct_markets_touched: int
    edge_stats: EdgeStats
    forensic_check: Optional[ForensicCheck]  # None if no resolved data available


@dataclass(frozen=True)
class AuditReport:
    """
    Top-level, JSON-serializable audit report.

    Frozen: identical inputs always yield an identical report (determinism guarantee).
    """
    total_markets_scanned: int
    total_signals_fired: int
    signals: Tuple[SignalRecord, ...]         # All individual signals
    per_strategy: Tuple[StrategyAuditResult, ...]
    data_source_breakdown: Dict[str, int]     # {"real": N, "synthetic_...": N}
    honest_finding: str                       # One-line honest summary

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary of the full report."""
        return {
            "total_markets_scanned": self.total_markets_scanned,
            "total_signals_fired": self.total_signals_fired,
            "data_source_breakdown": self.data_source_breakdown,
            "honest_finding": self.honest_finding,
            "per_strategy": [
                {
                    "strategy_name": r.strategy_name,
                    "signals_fired": r.signals_fired,
                    "distinct_markets_touched": r.distinct_markets_touched,
                    "edge_stats": {
                        "count": r.edge_stats.count,
                        "min_edge": r.edge_stats.min_edge,
                        "median_edge": r.edge_stats.median_edge,
                        "max_edge": r.edge_stats.max_edge,
                    },
                    "forensic_check": (
                        {
                            "total_signals": r.forensic_check.total_signals,
                            "correct_signals": r.forensic_check.correct_signals,
                            "hit_rate": r.forensic_check.hit_rate,
                            "false_positive_count": r.forensic_check.false_positive_count,
                            "note": r.forensic_check.note,
                        }
                        if r.forensic_check is not None
                        else None
                    ),
                }
                for r in self.per_strategy
            ],
            "signals": [
                {
                    "strategy_name": s.strategy_name,
                    "market_id": s.market_id,
                    "market_question": s.market_question,
                    "side": s.side,
                    "entry_price": s.entry_price,
                    "expected_value": s.expected_value,
                    "edge": s.edge,
                    "confidence": s.confidence,
                    "reason": s.reason,
                    "data_source": s.data_source,
                }
                for s in self.signals
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Return a JSON string of the full report."""
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ──────────────────────────────────────────────────────────────────────────────
# Resolution oracle helper
# ──────────────────────────────────────────────────────────────────────────────

def _build_resolution_oracle(
    resolved_records: List[Dict[str, Any]]
) -> Dict[str, int]:
    """
    Build a market_id -> outcome (0 or 1) lookup from the flat history records.

    The history format is:
        {"market_id": "253591", "outcome": 1, "market_price": 0.5665, ...}

    outcome=1 means YES resolved, outcome=0 means NO resolved.
    """
    return {str(r["market_id"]): int(r["outcome"]) for r in resolved_records}


def _signal_was_correct(signal: SignalRecord, oracle: Dict[str, int]) -> Optional[bool]:
    """
    Return True if the signal's recommended side resolved correctly.
    Return None if the market_id is not in the oracle (unresolved / unknown).

    Convention:
      - signal.side == "BUY" on outcome_idx=0 means "buy YES" → correct if outcome==1
      - signal.side == "SELL" on outcome_idx=0 means "sell YES" → correct if outcome==0
      - For the strategies we audit, outcome_idx=0 always refers to the YES side
        (per strategies.py: outcomes[0] is YES, outcomes[1] is NO).

    This is a simplified forensic check.  The strategies only emit outcome_idx=0,
    so we can map directly: BUY→correct iff outcome==1, SELL→correct iff outcome==0.
    """
    if signal.market_id not in oracle:
        return None
    resolved_outcome = oracle[signal.market_id]
    if signal.side == "BUY":
        return resolved_outcome == 1
    elif signal.side == "SELL":
        return resolved_outcome == 0
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Core audit function
# ──────────────────────────────────────────────────────────────────────────────

def audit_strategies(
    markets: List[Any],
    strategies: List[Any],
    *,
    resolved_records: Optional[List[Dict[str, Any]]] = None,
    data_source: str = "real",
) -> AuditReport:
    """
    Run each strategy over `markets` and collect a forensic AuditReport.

    Parameters
    ----------
    markets : List[Market]
        Markets to scan.  Read-only — this function does not mutate them.
    strategies : List[BaseStrategy]
        Instantiated strategy objects whose .scan(markets) will be called.
        Expected: CrossMarketArbitrageStrategy and/or LogicalImplicationDetector,
        but any BaseStrategy subclass works.
    resolved_records : optional list of dicts
        If provided, each dict must have "market_id" and "outcome" (0 or 1).
        Used for the post-resolution forensic accuracy check.
    data_source : str
        Label for the source of `markets` — recorded in each SignalRecord.
        Use "real" for real data, "synthetic_should_fire" / "synthetic_should_not_fire"
        for controlled fixtures.

    Returns
    -------
    AuditReport (frozen dataclass, JSON-serializable)

    Notes
    -----
    NO parameter fitting is performed on resolved_records.  The forensic hit-rate
    is purely descriptive: of signals the strategy fired, how many turned out
    correct?  This is NOT an in-sample backtest — we never adjust thresholds.
    """
    oracle: Dict[str, int] = (
        _build_resolution_oracle(resolved_records) if resolved_records else {}
    )

    all_signals: List[SignalRecord] = []
    per_strategy_results: List[StrategyAuditResult] = []

    for strategy in strategies:
        strategy_name: str = getattr(strategy, "name", type(strategy).__name__)

        # Run the strategy — defensive: never crash on bad input
        try:
            scan_results = strategy.scan(markets)
        except Exception as exc:  # noqa: BLE001
            scan_results = []
            # Record the exception in the report as a zero-signal result with a note
            per_strategy_results.append(StrategyAuditResult(
                strategy_name=strategy_name,
                signals_fired=0,
                distinct_markets_touched=0,
                edge_stats=EdgeStats(
                    strategy_name=strategy_name,
                    count=0,
                    min_edge=None,
                    median_edge=None,
                    max_edge=None,
                ),
                forensic_check=ForensicCheck(
                    strategy_name=strategy_name,
                    total_signals=0,
                    correct_signals=0,
                    hit_rate=None,
                    false_positive_count=0,
                    note=f"Strategy raised an exception during scan: {exc}",
                ),
            ))
            continue

        # Convert ScanResult objects to SignalRecord (immutable)
        strategy_signals: List[SignalRecord] = []
        for result in scan_results:
            try:
                market = result.market
                rec = SignalRecord(
                    strategy_name=strategy_name,
                    market_id=str(market.id),
                    market_question=str(market.question),
                    side=str(result.side),
                    entry_price=float(result.entry_price),
                    expected_value=float(result.expected_value),
                    edge=float(result.edge),
                    confidence=float(result.confidence),
                    reason=str(result.reason),
                    data_source=data_source,
                )
                strategy_signals.append(rec)
            except Exception:  # noqa: BLE001
                # Malformed ScanResult — skip gracefully
                continue

        all_signals.extend(strategy_signals)

        # Edge distribution
        edges = [s.edge for s in strategy_signals]
        edge_stats = EdgeStats(
            strategy_name=strategy_name,
            count=len(edges),
            min_edge=min(edges) if edges else None,
            median_edge=statistics.median(edges) if edges else None,
            max_edge=max(edges) if edges else None,
        )

        # Distinct markets touched
        distinct_markets = len({s.market_id for s in strategy_signals})

        # Forensic accuracy check (only if resolved data provided)
        forensic_check: Optional[ForensicCheck] = None
        if oracle:
            verifiable = [
                s for s in strategy_signals if s.market_id in oracle
            ]
            correct = [s for s in verifiable if _signal_was_correct(s, oracle) is True]
            wrong = [s for s in verifiable if _signal_was_correct(s, oracle) is False]
            total = len(verifiable)
            hit_rate = (len(correct) / total) if total > 0 else None
            forensic_check = ForensicCheck(
                strategy_name=strategy_name,
                total_signals=total,
                correct_signals=len(correct),
                hit_rate=hit_rate,
                false_positive_count=len(wrong),
                note=(
                    "Descriptive forensics on resolved data only. "
                    "No parameter fitting was performed. "
                    "Hit-rate on N=" + str(total) + " resolvable signals — "
                    "insufficient sample for statistical significance."
                ),
            )

        per_strategy_results.append(StrategyAuditResult(
            strategy_name=strategy_name,
            signals_fired=len(strategy_signals),
            distinct_markets_touched=distinct_markets,
            edge_stats=edge_stats,
            forensic_check=forensic_check,
        ))

    # Data-source breakdown
    source_breakdown: Dict[str, int] = {}
    for sig in all_signals:
        source_breakdown[sig.data_source] = source_breakdown.get(sig.data_source, 0) + 1

    # Honest one-line finding
    total_real_signals = sum(
        1 for s in all_signals if s.data_source == "real"
    )
    real_strategy_names = {s.strategy_name for s in all_signals if s.data_source == "real"}
    n_real_markets = len(markets)
    if total_real_signals == 0:
        honest_finding = (
            f"FINDING: Neither strategy fired any signal on the {n_real_markets}-record "
            "real sample. The records carry NO real question text and NO pairwise/related "
            "grouping, which the cross-market and logical-implication strategies require to "
            "fire. To actually exercise these alphas, the corpus needs real question text + "
            "related-market grouping sampled earlier in market life (binding constraint, "
            "track B / earlier-life sampling)."
        )
    else:
        honest_finding = (
            f"FINDING: {total_real_signals} signal(s) fired on the real sample "
            f"from strategy/strategies: {', '.join(sorted(real_strategy_names))}. "
            "Forensic accuracy available in per_strategy[*].forensic_check."
        )

    return AuditReport(
        total_markets_scanned=len(markets),
        total_signals_fired=len(all_signals),
        signals=tuple(all_signals),
        per_strategy=tuple(per_strategy_results),
        data_source_breakdown=source_breakdown,
        honest_finding=honest_finding,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers — for use in tests and exploratory analysis
# ──────────────────────────────────────────────────────────────────────────────

def build_market_from_record(
    record: Dict[str, Any],
    question: str = "",
    category: str = "Politics",
    active: bool = True,
    closed: bool = False,
    resolved: bool = False,
    slug: str = "",
) -> Any:
    """
    Build a Market object from a flat history record dict.

    The history records only carry price and market_id; they have no question text
    or multi-market structure, so cross-market strategies cannot fire directly on
    them as pairs.  This helper is provided for completeness.

    The market is treated as a binary (YES/NO) market.
    """
    from datetime import datetime, timedelta, timezone

    from .polymarket_client import Market, Outcome

    mid = str(record["market_id"])
    price = float(record.get("market_price", 0.5))
    no_price = round(max(0.0, min(1.0, 1.0 - price)), 4)

    end_date = None
    try:
        rt = record.get("resolution_time")
        if rt:
            end_date = datetime.fromisoformat(rt)
    except Exception:
        end_date = datetime.now(timezone.utc) + timedelta(days=2)

    return Market(
        id=mid,
        condition_id=mid,
        question=question or f"Market {mid}",
        slug=slug or mid,
        description="",
        category=category,
        end_date=end_date,
        outcomes=[
            Outcome(token_id=f"{mid}_yes", label="Yes", price=price,
                    midpoint=price, volume=float(record.get("volume", 100_000))),
            Outcome(token_id=f"{mid}_no", label="No", price=no_price,
                    midpoint=no_price, volume=float(record.get("volume", 100_000))),
        ],
        total_volume=float(record.get("volume", 100_000)),
        liquidity=float(record.get("liquidity", 10_000)),
        active=active,
        closed=closed,
        resolved=resolved,
    )


def make_synthetic_market(
    mid: str,
    question: str,
    yes_price: float,
    category: str = "Politics",
    volume: float = 200_000,
    liquidity: float = 50_000,
    slug: str = "",
    active: bool = True,
    closed: bool = False,
    resolved: bool = False,
) -> Any:
    """
    Build a synthetic Market for controlled testing of strategy firing logic.

    LABELED SYNTHETIC: these markets are deliberately constructed to exercise
    strategy edge cases, not derived from real data.
    """
    from datetime import datetime, timedelta, timezone

    from .polymarket_client import Market, Outcome

    no_price = round(max(0.0, min(1.0, 1.0 - yes_price)), 4)
    end_date = datetime.now(timezone.utc) + timedelta(hours=48)

    return Market(
        id=mid,
        condition_id=mid,
        question=question,
        slug=slug or mid,
        description="[SYNTHETIC AUDIT FIXTURE]",
        category=category,
        end_date=end_date,
        outcomes=[
            Outcome(token_id=f"{mid}_yes", label="Yes", price=yes_price,
                    midpoint=yes_price, volume=volume),
            Outcome(token_id=f"{mid}_no", label="No", price=no_price,
                    midpoint=no_price, volume=volume),
        ],
        total_volume=volume,
        liquidity=liquidity,
        active=active,
        closed=closed,
        resolved=resolved,
    )


def load_real_markets_from_history(
    history_path: str,
    question_template: str = "Q{market_id}",
    category: str = "Politics",
) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """
    Load the real resolved-history fixture and convert each record to a Market.

    The history records are individual, independent markets that carry NO real
    question text and NO pairwise grouping. The default ``question_template`` is
    therefore a UNIQUE, opaque, id-based placeholder (``"Q{market_id}"``) that
    shares NO content words across markets.

    This is a deliberate honesty fix (adversarial-audit finding): an earlier
    template injected the SAME boilerplate ("Market {id} (real sample)") into
    every record, so the cross-market keyword heuristic — which fires on "3+
    shared non-trivial words" — spuriously paired unrelated markets and reported
    ~98 phantom signals. With unique placeholders the strategies correctly fire
    0 signals on this sample (they genuinely cannot act without real question
    text and related-market grouping). NOTE: that the boilerplate triggered
    phantom firings is itself a real weakness in the strategy's keyword screen,
    recorded in RESEARCH_MEMORY for a future B-track fix — it is NOT papered over
    here (we do not edit the strategy in the audit change).

    Returns
    -------
    (markets, records)
      markets : list of Market objects (active=True so strategies can scan them)
      records : raw dicts (for passing as resolved_records to audit_strategies)
    """
    with open(history_path, encoding="utf-8") as fh:
        records: List[Dict[str, Any]] = json.load(fh)

    markets = []
    for rec in records:
        mid = str(rec["market_id"])
        question = question_template.format(market_id=mid)
        m = build_market_from_record(
            rec,
            question=question,
            category=category,
            active=True,
            closed=False,
            resolved=False,  # We present as active so strategies scan them
        )
        markets.append(m)

    return markets, records
