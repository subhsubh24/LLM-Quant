"""Representative input matrix for the ``llmquant-signal-check`` workflow.

Each case is a realistic prediction-market entry decision. The model is shown
the market data plus an INDEPENDENT fair-value estimate and must return a
trading verdict (allocate / hold / pass) with a confidence. The scenarios span
the full outcome spectrum on purpose:

  - CLEAR EDGE      : fair value well above price, liquid, strong signal  -> allocate
  - OVERPRICED      : fair value well below price (the YES is rich)       -> pass
  - NO EDGE         : fair value ~= price (nothing after costs)          -> pass
  - THIN LIQUIDITY  : real edge but the book is too thin to execute      -> hold/pass
  - AMBIGUOUS       : small/borderline edge, mixed signal                -> no single
                       correct direction; graded on VALIDITY only.

GROUND TRUTH is not hand-labelled per case — it is DERIVED from the scenario
economics by :func:`ground_truth`, an explicit, inspectable rule. That keeps the
labels honest and reproducible: given a fair value, a price, a friction cost and
a liquidity level, the economically-correct action is determined, not guessed.

The matrix is deterministic (no runtime randomness) so a re-run is comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Set

# --- Economic thresholds used to DERIVE ground truth (all in probability pts) --
# Round-trip friction (spread + fees + slippage) expressed in probability points.
FRICTION_COST: float = 0.03
# Net edge (after friction) required before allocating is clearly correct.
EDGE_MIN_ALLOCATE: float = 0.06
# How overpriced the YES must be for "pass" to be clearly correct.
OVERPRICED_MARGIN: float = 0.05
# Minimum on-book liquidity (USD) to consider the edge executable.
LIQUIDITY_MIN_USD: float = 25_000.0
# Minimum signal confidence to trust a positive edge enough to allocate.
CONF_MIN_ALLOCATE: float = 0.55


@dataclass(frozen=True)
class Case:
    """One prediction-market signal-check scenario."""

    id: str
    category: str
    question: str
    market_price: float          # implied YES probability, 0..1
    model_fair_value: float      # our independent YES estimate, 0..1
    liquidity_usd: float         # resting size on the book
    signal_confidence: float     # 0..1, strength of our fair-value signal
    horizon: str                 # human time-to-resolution
    # Bucket is descriptive only; ground truth is computed, not read from here.
    bucket: str = ""
    notes: str = ""

    @property
    def raw_edge(self) -> float:
        """fair - price (positive = YES looks cheap)."""
        return self.model_fair_value - self.market_price

    @property
    def net_edge(self) -> float:
        """Edge net of round-trip friction (only meaningful when positive)."""
        return self.raw_edge - FRICTION_COST


@dataclass
class GroundTruth:
    """The economically-correct answer for a case.

    ``acceptable`` is the set of verdicts that are NOT wrong. ``primary`` is the
    single best verdict when one exists. When ``acceptable`` is None the case is
    AMBIGUOUS: there is no correct direction, so the grader scores validity only
    (well-formed verdict + sane confidence) and uses a ``heuristic`` method
    rather than claiming ``ground_truth``.
    """

    acceptable: Optional[Set[str]]
    primary: Optional[str]
    method: str            # "ground_truth" | "heuristic"
    rationale: str


def ground_truth(case: Case) -> GroundTruth:
    """Derive the correct verdict for a case from its economics.

    This is the honest core of the suite: it never returns "anything passes".
    """
    edge = case.raw_edge
    net = case.net_edge
    liquid = case.liquidity_usd >= LIQUIDITY_MIN_USD

    # 1) The YES is clearly RICH (overpriced) -> do not buy it -> pass.
    if edge <= -OVERPRICED_MARGIN:
        return GroundTruth(
            acceptable={"pass"},
            primary="pass",
            method="ground_truth",
            rationale=f"YES overpriced by {abs(edge):.2f} vs fair; long-only -> pass",
        )

    # 2) No real edge after friction -> pass.
    if abs(edge) <= FRICTION_COST:
        return GroundTruth(
            acceptable={"pass"},
            primary="pass",
            method="ground_truth",
            rationale=f"|edge|={abs(edge):.2f} <= friction {FRICTION_COST}; nothing to trade",
        )

    # 3) A positive edge exists from here on (edge > friction).
    # 3a) Book too thin to execute the edge -> don't allocate; hold or pass.
    if not liquid:
        return GroundTruth(
            acceptable={"hold", "pass"},
            primary="hold",
            method="ground_truth",
            rationale=f"edge {edge:.2f} but liquidity ${case.liquidity_usd:,.0f} "
            f"< ${LIQUIDITY_MIN_USD:,.0f}; not executable -> hold/pass",
        )

    # 3b) Strong, liquid, confident edge -> allocate.
    if net >= EDGE_MIN_ALLOCATE and case.signal_confidence >= CONF_MIN_ALLOCATE:
        return GroundTruth(
            acceptable={"allocate"},
            primary="allocate",
            method="ground_truth",
            rationale=f"net edge {net:.2f} >= {EDGE_MIN_ALLOCATE} & conf "
            f"{case.signal_confidence:.2f} >= {CONF_MIN_ALLOCATE}; liquid -> allocate",
        )

    # 3c) Borderline: small positive net edge, or edge present but low
    # confidence. No single correct direction -> AMBIGUOUS (validity only).
    return GroundTruth(
        acceptable=None,
        primary=None,
        method="heuristic",
        rationale=f"borderline net edge {net:.2f} / conf {case.signal_confidence:.2f}; "
        f"any well-formed verdict is defensible",
    )


# ---------------------------------------------------------------------------
# The matrix. Authored for genuine variety across categories, prices, volumes
# and confidence. Numbers are chosen so the scenario lands in the intended
# bucket, but ground truth is still COMPUTED from the numbers above.
# ---------------------------------------------------------------------------

def _cases() -> List[Case]:
    C = Case
    cases: List[Case] = [
        # ---------- CLEAR EDGE (expect allocate) ----------
        C("edge-pol-01", "Politics",
          "Will the incumbent win re-election in the November general?",
          0.52, 0.68, 180_000, 0.72, "3 months", "clear_edge",
          "poll aggregate + fundamentals both favor YES well above market"),
        C("edge-eco-02", "Economics",
          "Will CPI YoY print at or below 3.0% for the next release?",
          0.41, 0.60, 120_000, 0.66, "3 weeks", "clear_edge",
          "nowcast + shelter disinflation point higher than market"),
        C("edge-spo-03", "Sports",
          "Will the home side reach the semi-final?",
          0.55, 0.74, 90_000, 0.70, "5 weeks", "clear_edge",
          "elo + injuries favor YES; market lagging line move"),
        C("edge-cry-04", "Crypto",
          "Will ETH close the quarter above $4,000?",
          0.38, 0.55, 210_000, 0.63, "2 months", "clear_edge",
          "flows + supply burn skew higher than implied"),
        C("edge-wea-05", "Weather",
          "Will monthly rainfall exceed the 30-year median in the basin?",
          0.47, 0.66, 60_000, 0.68, "4 weeks", "clear_edge",
          "ENSO signal strongly favors wet anomaly"),
        C("edge-pol-06", "Politics",
          "Will the bill pass the chamber before recess?",
          0.44, 0.63, 75_000, 0.61, "2 weeks", "clear_edge",
          "whip count implies more YES votes than price"),
        C("edge-eco-07", "Economics",
          "Will the central bank hold rates at the next meeting?",
          0.58, 0.79, 300_000, 0.75, "6 weeks", "clear_edge",
          "dot-plot + speeches strongly favor a hold"),
        C("edge-cry-08", "Crypto",
          "Will a spot BTC ETF see net positive weekly inflows?",
          0.49, 0.67, 140_000, 0.64, "1 week", "clear_edge",
          "creation baskets already trending positive"),

        # ---------- OVERPRICED (expect pass) ----------
        C("rich-pol-09", "Politics",
          "Will a third-party candidate win any state?",
          0.30, 0.12, 110_000, 0.62, "3 months", "overpriced",
          "market wildly overprices a tail; fair far lower"),
        C("rich-spo-10", "Sports",
          "Will the underdog win the final outright?",
          0.42, 0.25, 95_000, 0.58, "2 weeks", "overpriced",
          "narrative pump; model has YES much lower"),
        C("rich-cry-11", "Crypto",
          "Will a new all-time high print this month?",
          0.55, 0.34, 160_000, 0.60, "4 weeks", "overpriced",
          "over-enthusiasm; funding stretched"),
        C("rich-eco-12", "Economics",
          "Will unemployment fall below 3.5% next print?",
          0.48, 0.30, 130_000, 0.57, "3 weeks", "overpriced",
          "claims trend argues against; YES too rich"),
        C("rich-wea-13", "Weather",
          "Will a named storm make landfall this week?",
          0.40, 0.20, 55_000, 0.59, "1 week", "overpriced",
          "steering pattern unfavorable; market too high"),
        C("rich-pol-14", "Politics",
          "Will the cabinet nominee be confirmed this week?",
          0.66, 0.45, 80_000, 0.56, "1 week", "overpriced",
          "hold-outs make YES overpriced at current level"),
        C("rich-cry-15", "Crypto",
          "Will gas fees average above 100 gwei this week?",
          0.51, 0.33, 70_000, 0.55, "1 week", "overpriced",
          "activity cooling; YES overpriced"),

        # ---------- NO EDGE (expect pass) ----------
        C("flat-eco-16", "Economics",
          "Will retail sales beat consensus next release?",
          0.50, 0.51, 120_000, 0.40, "2 weeks", "no_edge",
          "coin-flip; no informational edge"),
        C("flat-pol-17", "Politics",
          "Will turnout exceed the prior cycle?",
          0.54, 0.55, 100_000, 0.42, "3 months", "no_edge",
          "fair essentially equals price"),
        C("flat-spo-18", "Sports",
          "Will the match go to extra time?",
          0.28, 0.29, 60_000, 0.38, "1 week", "no_edge",
          "no edge net of costs"),
        C("flat-cry-19", "Crypto",
          "Will BTC dominance rise this week?",
          0.49, 0.50, 130_000, 0.41, "1 week", "no_edge",
          "flat; friction eats any move"),
        C("flat-wea-20", "Weather",
          "Will the daily high exceed the seasonal normal tomorrow?",
          0.60, 0.62, 45_000, 0.44, "1 day", "no_edge",
          "within friction band"),
        C("flat-eco-21", "Economics",
          "Will the trade balance narrow next month?",
          0.46, 0.47, 90_000, 0.39, "4 weeks", "no_edge",
          "no meaningful edge"),
        C("flat-pol-22", "Politics",
          "Will the debate change the polling lead?",
          0.50, 0.49, 85_000, 0.37, "2 weeks", "no_edge",
          "essentially priced"),

        # ---------- THIN LIQUIDITY (expect hold/pass) ----------
        C("thin-wea-23", "Weather",
          "Will snowfall exceed 6 inches at the station this week?",
          0.35, 0.55, 6_000, 0.66, "1 week", "thin_liquidity",
          "real edge but book far too thin to size"),
        C("thin-spo-24", "Sports",
          "Will the rookie start the next fixture?",
          0.40, 0.58, 4_500, 0.62, "1 week", "thin_liquidity",
          "edge exists; illiquid micro-market"),
        C("thin-cry-25", "Crypto",
          "Will an altcoin flip its rival in market cap this month?",
          0.30, 0.49, 8_000, 0.60, "4 weeks", "thin_liquidity",
          "edge but only $8k on the book"),
        C("thin-pol-26", "Politics",
          "Will a specific amendment be adopted?",
          0.45, 0.64, 9_500, 0.58, "2 weeks", "thin_liquidity",
          "edge, thin book, cannot execute size"),
        C("thin-eco-27", "Economics",
          "Will a regional Fed index turn positive?",
          0.38, 0.57, 7_200, 0.61, "3 weeks", "thin_liquidity",
          "edge but liquidity below threshold"),
        C("thin-wea-28", "Weather",
          "Will the reservoir level rise above the marker this month?",
          0.42, 0.61, 5_000, 0.59, "4 weeks", "thin_liquidity",
          "genuine edge, non-executable book"),

        # ---------- AMBIGUOUS (validity-only; no correct direction) ----------
        C("amb-eco-29", "Economics",
          "Will core PCE surprise to the downside next print?",
          0.47, 0.53, 110_000, 0.50, "3 weeks", "ambiguous",
          "small positive edge near threshold, medium confidence"),
        C("amb-pol-30", "Politics",
          "Will the runoff be called on election night?",
          0.50, 0.56, 90_000, 0.48, "2 weeks", "ambiguous",
          "borderline edge, mixed signal"),
        C("amb-cry-31", "Crypto",
          "Will BTC realized volatility fall next week?",
          0.45, 0.51, 120_000, 0.46, "1 week", "ambiguous",
          "edge just above friction, low-ish confidence"),
        C("amb-spo-32", "Sports",
          "Will total goals exceed the posted line?",
          0.52, 0.58, 80_000, 0.52, "1 week", "ambiguous",
          "small edge, moderate confidence"),
        C("amb-wea-33", "Weather",
          "Will the heat index breach the alert threshold this week?",
          0.40, 0.46, 50_000, 0.49, "1 week", "ambiguous",
          "borderline, could defensibly hold or pass or nibble"),
        C("amb-eco-34", "Economics",
          "Will jobless claims tick down next week?",
          0.49, 0.55, 100_000, 0.47, "1 week", "ambiguous",
          "edge near threshold, low confidence"),
        C("amb-pol-35", "Politics",
          "Will the leadership vote succeed on the first ballot?",
          0.48, 0.54, 70_000, 0.51, "1 week", "ambiguous",
          "borderline edge, mixed whip signal"),
        C("amb-cry-36", "Crypto",
          "Will stablecoin supply grow this week?",
          0.46, 0.52, 130_000, 0.45, "1 week", "ambiguous",
          "edge just over friction, tepid confidence"),
    ]

    # ---- Programmatic variety layer: sweep price/liquidity/confidence to
    # reach a fuller matrix (~60) WITHOUT collapsing to identical templates.
    # Each generated case still lands in a bucket by construction and its
    # ground truth is computed from the numbers, same as the authored ones.
    sweep_templates = [
        ("Politics", "Will the measure clear its committee before the deadline?", "2 weeks"),
        ("Economics", "Will the PMI print above 50 next release?", "3 weeks"),
        ("Crypto", "Will the network's active addresses rise this week?", "1 week"),
        ("Sports", "Will the favorite cover the spread?", "1 week"),
        ("Weather", "Will monthly mean temperature exceed normal?", "4 weeks"),
    ]
    # (price, fair, liq, conf, bucket-hint) tuples engineered per bucket.
    sweep_points = [
        (0.45, 0.64, 150_000, 0.68, "clear_edge"),   # allocate
        (0.60, 0.40, 150_000, 0.60, "overpriced"),   # pass
        (0.50, 0.505, 120_000, 0.40, "no_edge"),     # pass
        (0.36, 0.57, 6_500, 0.63, "thin_liquidity"), # hold/pass
        (0.48, 0.54, 110_000, 0.49, "ambiguous"),    # validity-only
    ]
    n = 37
    for (cat, q, horizon) in sweep_templates:
        for (price, fair, liq, conf, hint) in sweep_points:
            cases.append(
                Case(
                    id=f"sweep-{n:02d}",
                    category=cat,
                    question=q,
                    market_price=price,
                    model_fair_value=fair,
                    liquidity_usd=liq,
                    signal_confidence=conf,
                    horizon=horizon,
                    bucket=hint,
                    notes="matrix sweep point",
                )
            )
            n += 1
    return cases


ALL_CASES: List[Case] = _cases()


def build_signal_prompt(case: Case) -> str:
    """Render the signal-check prompt shown to the model for one case.

    The model sees the market data + an independent fair-value estimate and is
    asked for a single trading verdict + confidence, ending with two exact lines
    the grader can parse deterministically.
    """
    return f"""You are the signal-check stage of a systematic prediction-market trading bot.
Long-only on YES shares. Decide whether to take a NEW position given the data.

MARKET
- Category: {case.category}
- Question: {case.question}
- Current YES price (implied prob): {case.market_price:.2f}
- Time to resolution: {case.horizon}
- Resting liquidity on the book: ${case.liquidity_usd:,.0f}

OUR INDEPENDENT MODEL
- Fair-value estimate for YES: {case.model_fair_value:.2f}
- Signal confidence (0-1): {case.signal_confidence:.2f}
- Round-trip friction (spread+fees+slippage): ~{FRICTION_COST:.2f} in probability points

DECISION RULES (apply like a disciplined trader)
- allocate : there is a real, executable edge (fair clearly above price net of
             friction, enough liquidity, and enough confidence).
- hold     : there is an edge but it is NOT executable right now (e.g. the book
             is too thin to size the position) — stand by.
- pass     : no tradeable edge (fair ~= price, or the YES is overpriced, i.e.
             fair below price).

Think briefly, then END YOUR REPLY WITH EXACTLY THESE TWO LINES:
VERDICT: <allocate|hold|pass>
CONFIDENCE: <a number from 0.00 to 1.00>"""


def bucket_of(case: Case) -> str:
    """Descriptive bucket derived from the computed ground truth (for reporting)."""
    gt = ground_truth(case)
    if gt.acceptable is None:
        return "ambiguous"
    if gt.primary == "allocate":
        return "clear_edge"
    if gt.acceptable == {"hold", "pass"}:
        return "thin_liquidity"
    # primary == pass
    return "no_edge_or_overpriced"


# Field names of a Case, for external tools that want the raw schema.
CASE_FIELDS: List[str] = list(Case.__dataclass_fields__.keys())
