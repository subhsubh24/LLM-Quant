"""Input matrices for the advisory analyst workflows.

These workflows (analyze_stock, analyze_portfolio, critique_strategy) are
ADVISORY: the LLM produces a written analysis for a human, decoupled from the
trading path. There is therefore no single "correct answer" and no market
ground truth — so the graders (analyst_graders.py) score genuine TASK
COMPLETION (on-topic, structured, references the input, non-refusal), and for
critique_strategy they additionally assert that OBVIOUS flaws are actually
caught (``expected_flags``). Method = ``rubric``, never ``ground_truth``.

Each matrix mixes:
  - normal : realistic inputs across the spectrum.
  - edge   : boundary / degenerate inputs (empty, extreme, zero, negative).
  - fuzz   : seeded-random inputs for robustness (deterministic re-runs).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AnalystCase:
    id: str
    workflow: str                 # analyze_stock | analyze_portfolio | critique_strategy
    bucket: str                   # normal | edge | fuzz
    payload: Dict[str, Any]       # kwargs for the analyst method
    must_mention: List[str] = field(default_factory=list)   # strings required in output
    expected_flags: List[str] = field(default_factory=list)  # critique: flaw keys required
    notes: str = ""


# --------------------------------------------------------------------------- #
# analyze_stock(symbol, quote, price_history=None, news=None)
# --------------------------------------------------------------------------- #
def _stock_cases() -> List[AnalystCase]:
    cases: List[AnalystCase] = []

    normal = [
        ("AAPL", 195.30, 1.4, 191.0, 197.2,
         ["Apple beats on services revenue", "iPhone demand steady in China"]),
        ("NVDA", 128.6, -3.2, 126.1, 134.9,
         ["AI chip demand cooling fears", "New export restrictions weighed"]),
        ("TSLA", 245.1, 5.8, 232.0, 249.5,
         ["Deliveries top estimates", "Margin compression concerns"]),
        ("JPM", 205.4, 0.3, 203.8, 206.9,
         ["Bank earnings season kicks off", "Net interest margin in focus"]),
        ("XOM", 112.7, -1.1, 111.9, 114.6,
         ["Crude slips on demand outlook", "Refining margins normalize"]),
        ("KO", 62.4, 0.2, 62.0, 62.9, ["Defensive names bid", "Dividend aristocrats steady"]),
    ]
    for i, (sym, px, chg, lo, hi, news) in enumerate(normal, 1):
        cases.append(AnalystCase(
            id=f"stock-norm-{i:02d}", workflow="analyze_stock", bucket="normal",
            payload={"symbol": sym,
                     "quote": {"price": px, "change_percent": chg, "low": lo, "high": hi},
                     "news": [{"headline": h} for h in news]},
            must_mention=[sym], notes="realistic single-name analysis"))

    # ---- edge cases ----
    edge = [
        AnalystCase("stock-edge-01", "analyze_stock", "edge",
                    {"symbol": "ZVZZT", "quote": {"price": 0.0, "change_percent": 0.0,
                                                  "low": 0.0, "high": 0.0}, "news": []},
                    must_mention=["ZVZZT"], notes="empty/zero quote, no news"),
        AnalystCase("stock-edge-02", "analyze_stock", "edge",
                    {"symbol": "BRK.A", "quote": {"price": 999999.0, "change_percent": 0.01,
                                                  "low": 998000.0, "high": 1000500.0},
                     "news": [{"headline": "Highest-priced share unchanged"}]},
                    must_mention=["BRK.A"], notes="extreme price"),
        AnalystCase("stock-edge-03", "analyze_stock", "edge",
                    {"symbol": "PENNY", "quote": {"price": 0.03, "change_percent": -99.0,
                                                  "low": 0.02, "high": 3.10}, "news": []},
                    must_mention=["PENNY"], notes="penny stock, -99% crash, huge range"),
        AnalystCase("stock-edge-04", "analyze_stock", "edge",
                    {"symbol": "GME", "quote": {"price": 48.0, "change_percent": 210.0,
                                                "low": 15.0, "high": 65.0},
                     "news": [{"headline": h} for h in
                              ["Meme rally reignites", "Volume spikes 40x", "Options gamma squeeze",
                               "Retail piles in", "Short interest elevated"]]},
                    must_mention=["GME"], notes="parabolic +210%, max news"),
    ]
    cases.extend(edge)

    # ---- fuzz cases (seeded) ----
    rng = random.Random(20260712)
    syms = ["QQXF", "ZLLP", "MRVX", "AABB", "T1CK", "WXYZ", "PLTX", "OMNI"]
    for i in range(1, 7):
        sym = rng.choice(syms)
        px = round(rng.uniform(0.5, 5000.0), 2)
        chg = round(rng.uniform(-40.0, 40.0), 2)
        span = px * rng.uniform(0.01, 0.25)
        cases.append(AnalystCase(
            id=f"stock-fuzz-{i:02d}", workflow="analyze_stock", bucket="fuzz",
            payload={"symbol": sym,
                     "quote": {"price": px, "change_percent": chg,
                               "low": round(px - span, 2), "high": round(px + span, 2)},
                     "news": [{"headline": f"Random wire item {rng.randint(1, 999)}"}]
                     if rng.random() > 0.5 else []},
            must_mention=[sym], notes="seeded fuzz"))
    return cases


# --------------------------------------------------------------------------- #
# analyze_portfolio(positions, total_value, returns_history=None)
# --------------------------------------------------------------------------- #
def _portfolio_cases() -> List[AnalystCase]:
    cases: List[AnalystCase] = []

    def pos(t, mv, w, pnl):
        return {"ticker": t, "market_value": mv, "weight": w, "unrealized_pnl": pnl}

    normal = [
        ("port-norm-01", 250_000, [pos("AAPL", 60000, 0.24, 4200), pos("MSFT", 55000, 0.22, 3100),
                                   pos("NVDA", 45000, 0.18, 9800), pos("JPM", 40000, 0.16, -600),
                                   pos("XOM", 30000, 0.12, 1200), pos("KO", 20000, 0.08, 300)],
         "balanced 6-name book"),
        ("port-norm-02", 120_000, [pos("SPY", 84000, 0.70, 5400), pos("TLT", 24000, 0.20, -900),
                                   pos("GLD", 12000, 0.10, 700)], "ETF macro book"),
        ("port-norm-03", 500_000, [pos("NVDA", 200000, 0.40, 55000), pos("AMD", 120000, 0.24, 18000),
                                   pos("AVGO", 100000, 0.20, 22000), pos("SMCI", 80000, 0.16, -12000)],
         "semis-concentrated growth book"),
        ("port-norm-04", 80_000, [pos("BRK.B", 20000, 0.25, 900), pos("PG", 16000, 0.20, 400),
                                  pos("JNJ", 16000, 0.20, -200), pos("PEP", 14000, 0.175, 150),
                                  pos("WMT", 14000, 0.175, 600)], "defensive value tilt"),
    ]
    for cid, tv, positions, note in normal:
        tickers = [p["ticker"] for p in positions]
        cases.append(AnalystCase(cid, "analyze_portfolio", "normal",
                                 {"positions": positions, "total_value": tv},
                                 must_mention=tickers[:1], notes=note))

    # ---- edge ----
    cases.append(AnalystCase(
        "port-edge-01", "analyze_portfolio", "edge",
        {"positions": [], "total_value": 0.0}, must_mention=[],
        notes="empty portfolio, zero value"))
    cases.append(AnalystCase(
        "port-edge-02", "analyze_portfolio", "edge",
        {"positions": [pos("TSLA", 200000, 1.0, -35000)], "total_value": 200000},
        must_mention=["TSLA"], expected_flags=["concentration"],
        notes="100% single-name concentration -> MUST flag concentration"))
    cases.append(AnalystCase(
        "port-edge-03", "analyze_portfolio", "edge",
        {"positions": [pos("ABC", 5000, 0.5, -8000)], "total_value": -3000},
        must_mention=["ABC"], notes="negative net value (underwater)"))
    cases.append(AnalystCase(
        "port-edge-04", "analyze_portfolio", "edge",
        {"positions": [pos(f"T{i:02d}", 1000, 0.02, 0) for i in range(50)], "total_value": 50000},
        must_mention=[], notes="50 tiny equal positions (over-diversified)"))

    # ---- fuzz ----
    rng = random.Random(770512)
    for i in range(1, 6):
        n = rng.randint(1, 8)
        positions = []
        for j in range(n):
            positions.append(pos(f"FZ{rng.randint(10, 99)}",
                                 round(rng.uniform(1000, 90000), 0),
                                 round(1.0 / n, 3),
                                 round(rng.uniform(-20000, 30000), 0)))
        tv = round(sum(p["market_value"] for p in positions) * rng.uniform(0.9, 1.1), 0)
        cases.append(AnalystCase(f"port-fuzz-{i:02d}", "analyze_portfolio", "fuzz",
                                 {"positions": positions, "total_value": tv},
                                 must_mention=[positions[0]["ticker"]], notes="seeded fuzz"))
    return cases


# --------------------------------------------------------------------------- #
# critique_strategy(strategy_description, backtest_results=None)
# --------------------------------------------------------------------------- #
def _critique_cases() -> List[AnalystCase]:
    cases: List[AnalystCase] = []

    # normal + obviously-flawed cases carry expected_flags the critique MUST raise.
    cases.append(AnalystCase(
        "crit-norm-01", "critique_strategy", "normal",
        {"strategy_description":
            "Long the S&P 500 when the 50-day moving average is above the 200-day "
            "(golden cross), flat otherwise. Monthly rebalance.",
         "backtest_results": {"cagr": 0.09, "sharpe": 0.7, "max_dd": -0.22, "years": 20}},
        notes="plausible trend strategy; critique should be substantive"))
    cases.append(AnalystCase(
        "crit-flaw-02", "critique_strategy", "normal",
        {"strategy_description":
            "Buy any stock when RSI(2) < 5 and sell at the close next day. My backtest "
            "shows a 99% win rate and 300% annual return over 2023 with no transaction costs.",
         "backtest_results": {"win_rate": 0.99, "annual_return": 3.0, "costs": 0.0, "years": 1}},
        expected_flags=["cost", "bias"],
        notes="overfit + zero-cost + 1yr -> MUST flag costs and overfitting/snooping"))
    cases.append(AnalystCase(
        "crit-flaw-03", "critique_strategy", "normal",
        {"strategy_description":
            "I optimized 40 parameters of a mean-reversion model on 18 months of one stock "
            "and it looks amazing in-sample. Planning to deploy full size next week.",
         "backtest_results": {"params": 40, "sample_months": 18, "n_assets": 1}},
        expected_flags=["bias"],
        notes="40 params / in-sample / 1 asset -> MUST flag overfitting/data-mining"))
    cases.append(AnalystCase(
        "crit-flaw-04", "critique_strategy", "normal",
        {"strategy_description":
            "Market-make a micro-cap by quoting 10,000 shares each side. Backtest assumes "
            "I always get filled at mid with no slippage and unlimited size.",
         "backtest_results": {"assumed_fill": "mid", "slippage": 0.0}},
        expected_flags=["cost"],
        notes="illiquid micro-cap, mid-fill, no slippage -> MUST flag cost/capacity/liquidity"))
    cases.append(AnalystCase(
        "crit-norm-05", "critique_strategy", "normal",
        {"strategy_description":
            "Cross-sectional momentum: long top-decile 12-1 month returns, short bottom decile, "
            "monthly rebalance, sector-neutral, 10bps costs modeled, walk-forward tested.",
         "backtest_results": {"sharpe": 1.1, "max_dd": -0.18, "costs_bps": 10, "oos": True}},
        notes="reasonably robust; critique should still probe capacity/regime"))

    # ---- edge ----
    cases.append(AnalystCase(
        "crit-edge-01", "critique_strategy", "edge",
        {"strategy_description": "", "backtest_results": None},
        notes="empty strategy string"))
    cases.append(AnalystCase(
        "crit-edge-02", "critique_strategy", "edge",
        {"strategy_description": "buy low sell high", "backtest_results": None},
        notes="vacuous one-liner, no backtest"))
    cases.append(AnalystCase(
        "crit-edge-03", "critique_strategy", "edge",
        {"strategy_description": "🚀🚀 to the moon, YOLO all in on 0DTE calls 🚀🚀",
         "backtest_results": None},
        expected_flags=["risk"],
        notes="degenerate high-risk -> MUST flag risk"))

    # ---- fuzz ----
    rng = random.Random(424242)
    fragments = [
        "pairs trade {a}/{b} on a {n}-day z-score",
        "buy {a} on earnings gaps and hold {n} days",
        "short {a} when IV rank > {n}",
        "rotate into the strongest sector every {n} weeks",
        "grid-trade {a} with {n} levels each side",
    ]
    tks = ["AAPL", "MSFT", "SPY", "QQQ", "GLD", "TLT", "XLE", "NVDA"]
    for i in range(1, 6):
        frag = rng.choice(fragments).format(a=rng.choice(tks), b=rng.choice(tks),
                                             n=rng.randint(2, 60))
        cases.append(AnalystCase(f"crit-fuzz-{i:02d}", "critique_strategy", "fuzz",
                                 {"strategy_description": frag, "backtest_results": None},
                                 notes="seeded fuzz strategy blurb"))
    return cases


STOCK_CASES: List[AnalystCase] = _stock_cases()
PORTFOLIO_CASES: List[AnalystCase] = _portfolio_cases()
CRITIQUE_CASES: List[AnalystCase] = _critique_cases()

ANALYST_CASES: Dict[str, List[AnalystCase]] = {
    "analyze_stock": STOCK_CASES,
    "analyze_portfolio": PORTFOLIO_CASES,
    "critique_strategy": CRITIQUE_CASES,
}
