"""polymarket_v1_hf_fetcher.py — leakage-safe ingestion of the HuggingFace
``TimeSeventeen/Polymarket-v1`` archive into ``walk_forward.HistoricalMarket``
records (ROADMAP A6 — the VOLUME unlock).

WHY THIS EXISTS
The binding constraint for go-live is a *validated out-of-sample edge*, and the
one thing every OOS validation needs is a large, real, resolved-market corpus.
``polymarket_history_fetcher.py`` (the Gamma/CLOB fetcher) can only reach a few
dozen liquid markets per run and is egress-blocked in the autonomous env. The
``TimeSeventeen/Polymarket-v1`` dataset (arxiv 2606.04217, CC-BY-4.0) is the
complete on-chain trade archive — ~1.2B trades across ~1.3M markets, with a
``daily_aligned/`` Parquet layer carrying cleaned market metadata + resolution
outcomes + a daily price series. HuggingFace is a DIFFERENT domain from
gamma-api.polymarket.com, so a GitHub-Actions runner (or any network-permitted
host) can stream it even when the direct Polymarket API is blocked. This module
is the missing ingest: it assembles those daily rows into the exact leakage-safe
``HistoricalMarket`` shape the walk-forward backtest + calibration eval consume —
turning the "statistically meaningless 54-record sample" into a real corpus.

HONEST SCOPE
This INGESTS + assembles; it does NOT itself prove an edge. Fed to the backtest a
naive ``model_prob = market_price`` has ~zero edge until a real strategy overrides
it (exactly like the Gamma fetcher). The actual download runs where HuggingFace is
reachable (the ``real-oos-validation`` lane / a permitted host); the PARSING +
LEAKAGE-SAFETY logic is what matters for correctness and is fully unit-tested
offline on realistic-shaped rows with NO heavy dependency (see
backend/tests/test_polymarket_v1_hf_fetcher.py).

SCHEMA IS VERIFIED ON THE FIRST DOWNLOAD (unconfirmed offline)
The exact ``daily_aligned`` column names for the resolution outcome, the
pre-resolution price, the timestamp, the resolution time, the market id, and the
category are NOT documented in this repo and cannot be confirmed from the
egress-blocked env. So the field names are a configurable ``HFFieldSpec`` with
documented DEFAULTS, and ``stream_daily_aligned`` LOGS the real column set of the
first row and ``assemble_historical_markets`` RAISES a clear, key-dumping error if
a required field is absent — so the first real run surfaces the true schema
immediately rather than silently mis-parsing. Adjust ``HFFieldSpec`` once the live
schema is known; the leakage-safety logic never changes.

THE ANTI-LEAKAGE GUARANTEE (identical to polymarket_history_fetcher.py)
A resolved market's settled outcome is the answer. Using it — or any price tick at
or after ``resolution_time`` — as the decision-time crowd price is 100% look-ahead
leakage. ``market_price`` is taken ONLY from a daily price tick whose timestamp is
at-or-before ``decision_time`` AND strictly before ``resolution_time``. If no such
pre-resolution tick exists, we RAISE (single market) or skip with a loud warning
(batch) — we NEVER fabricate a price, and we NEVER derive the decision price from
the settled outcome.

RESEARCH-INTEGRITY CAVEATS (read before trusting any eval built on this data)
* SELECTION / SURVIVORSHIP BIAS: only unambiguously-settled binary markets are
  kept; contested / re-resolved / cancelled markets are excluded — exactly the
  cases where the crowd was most wrong. Any calibration eval is an OPTIMISTIC upper
  bound and must say so.
* LATE-LIFE PRICE PINNING: a small ``decision_lead`` samples ``market_price`` after
  the crowd has pinned to ~1/~0 — a contemporaneous, non-look-ahead price that
  flatters crowd calibration and leaves a model little headroom. Prefer a lead
  large relative to market lifetime, OR use the point-in-time / earlier-life
  sampling in ``polymarket_history_fetcher`` (ROADMAP A7) for edge headroom.
* CATEGORY SUBSETTING IS A P-HACKING LEVER: any ``categories`` filter must be
  PRE-REGISTERED, never chosen after seeing which category looks best.

CI-SAFETY
Module-level imports are ONLY stdlib + ``HistoricalMarket`` — NO
``datasets`` / ``huggingface_hub`` / ``pyarrow`` / ``pandas`` (absent from CI). The
heavy deps are LAZY-imported inside ``stream_daily_aligned`` with a clear install
message if missing; the leakage-safe assembly is a pure function over plain row
dicts, exhaustively testable offline.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .walk_forward import HistoricalMarket

logger = logging.getLogger(__name__)

# The public CC-BY-4.0 dataset + the market-metadata-joined layer.
HF_DATASET = "TimeSeventeen/Polymarket-v1"
HF_CONFIG = "daily_aligned"

# Tolerance for treating a settled outcome value as exactly 0 or 1.
SETTLE_TOL = 0.02


@dataclass(frozen=True)
class HFFieldSpec:
    """Column-name mapping for the ``daily_aligned`` rows.

    The DEFAULTS are the best-guess names from the dataset card; the exact schema
    is VERIFIED on the first real download (see module docstring). Each attribute
    lists CANDIDATE names tried in order (presence, not truthiness) so a couple of
    plausible variants resolve without a code change; the first real run logs the
    actual columns and RAISES if none of the candidates for a required field match.
    """

    market_id: Tuple[str, ...] = ("market_id", "condition_id", "conditionId", "id")
    timestamp: Tuple[str, ...] = ("date", "timestamp", "day", "t", "ts")
    price_yes: Tuple[str, ...] = ("price", "yes_price", "price_yes", "p", "close")
    resolution_time: Tuple[str, ...] = (
        "resolution_time", "resolved_at", "end_date", "endDate", "close_time",
    )
    outcome: Tuple[str, ...] = ("outcome", "resolution", "result", "winning_outcome")
    category: Tuple[str, ...] = ("category", "tag", "topic")
    question: Tuple[str, ...] = ("question", "title", "market_question")


@dataclass(frozen=True)
class HFDailyRow:
    """One normalized daily-aligned observation for a single market.

    ``price_yes`` is the crowd P[YES] observed on ``timestamp`` (never the settled
    answer). ``outcome`` / ``resolution_time`` are market-level fields that repeat
    across a market's daily rows in an aligned layer; the assembler reconciles them.
    """

    market_id: str
    timestamp: datetime
    price_yes: float
    resolution_time: datetime
    outcome: Optional[int]        # 0/1 when cleanly settled; None = present-but-ambiguous (contested)
    category: str = ""
    question: str = ""


class PolymarketV1HFFetcher:
    """Streams the HuggingFace ``daily_aligned`` layer and assembles leakage-safe
    ``HistoricalMarket`` records. No auth, no order placement — a public read-only
    dataset. The heavy ``datasets`` dependency is only touched inside
    ``stream_daily_aligned``; everything else is pure + offline-testable."""

    def __init__(self, field_spec: Optional[HFFieldSpec] = None):
        self.field_spec = field_spec or HFFieldSpec()

    # ------------------------------------------------------------------
    # Streaming (the ONLY method that touches the heavy deps — lazy import)
    # ------------------------------------------------------------------
    def stream_daily_aligned(
        self,
        *,
        max_rows: Optional[int] = None,
        split: str = "train",
    ) -> Iterator[dict]:
        """Yield raw ``daily_aligned`` rows (plain dicts) from HuggingFace, streaming
        so we never materialize the whole archive. ``max_rows`` BOUNDS the stream — it
        must never run unbounded.

        Lazy-imports ``datasets`` (absent from CI); raises a clear, actionable
        ImportError if it is not installed on the runner. Logs the column set of the
        FIRST row so the true schema is visible immediately on a real run.
        """
        try:
            from datasets import load_dataset  # type: ignore
        except ImportError as e:  # pragma: no cover - exercised only on a real runner
            raise ImportError(
                "polymarket_v1_hf_fetcher requires the 'datasets' package to stream "
                "the HuggingFace archive (a permitted-host / CI-runner dependency, "
                "NOT installed in the deterministic gate). Install with: "
                "pip install datasets"
            ) from e

        ds = load_dataset(HF_DATASET, HF_CONFIG, streaming=True, split=split)
        logged_schema = False
        for i, row in enumerate(ds):
            if not logged_schema:
                logger.info(
                    "Polymarket-v1 daily_aligned first-row columns: %s",
                    sorted(row.keys()) if isinstance(row, dict) else type(row),
                )
                logged_schema = True
            if max_rows is not None and i >= max_rows:
                break
            yield dict(row)

    def build_historical_markets(
        self,
        *,
        decision_lead: timedelta,
        max_rows: Optional[int] = 100_000,
        categories: Optional[Sequence[str]] = None,
        split: str = "train",
    ) -> List[HistoricalMarket]:
        """Stream the archive and assemble leakage-safe ``HistoricalMarket`` records.

        Thin orchestration over ``stream_daily_aligned`` (I/O) +
        ``assemble_historical_markets`` (pure). ``categories`` must be PRE-REGISTERED
        (a p-hacking lever). Runs only where HuggingFace is reachable.
        """
        rows = self.stream_daily_aligned(max_rows=max_rows, split=split)
        return assemble_historical_markets(
            rows,
            decision_lead=decision_lead,
            field_spec=self.field_spec,
            categories=categories,
        )


# ---------------------------------------------------------------------------
# Pure assembly (no I/O, no heavy deps — exhaustively unit-testable offline)
# ---------------------------------------------------------------------------
def assemble_historical_markets(
    rows: Iterable[dict],
    *,
    decision_lead: timedelta,
    field_spec: Optional[HFFieldSpec] = None,
    categories: Optional[Sequence[str]] = None,
) -> List[HistoricalMarket]:
    """Group daily rows by market and assemble one leakage-safe ``HistoricalMarket``
    per market. Pure: operates on plain row dicts, no network, no heavy deps.

    A market is SKIPPED (loud warning), never guessed, when: it has no resolvable market
    id / timestamp / price / resolution time, has a present-but-ambiguous (contested)
    outcome, or no price tick survives the anti-leakage guard. TWO schema-surfacing guards
    make a real first-download mismatch LOUD rather than a silent empty corpus: (1) a
    required-field ABSENCE on the FIRST parseable row RAISES with the actual keys; (2) if
    rows were seen but ZERO markets assembled, RAISE — a whole-corpus wipeout is almost
    always a schema UNIT/format mismatch (ms epochs, percent prices, wrong column names),
    not a legitimately-empty result.
    """
    spec = field_spec or HFFieldSpec()
    if decision_lead <= timedelta(0):
        raise ValueError(f"decision_lead must be positive: {decision_lead}")
    cats = {c.lower() for c in categories} if categories else None

    # 1. Normalize daily rows, grouped by market id.
    by_market: Dict[str, List[HFDailyRow]] = {}
    seen_any = False
    n_rows = 0
    first_row_keys: List[str] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        if not seen_any:
            first_row_keys = sorted(raw.keys())
        row = _parse_daily_row(raw, spec, strict=not seen_any)
        seen_any = True
        n_rows += 1
        if row is None:
            continue
        by_market.setdefault(row.market_id, []).append(row)

    # Whole-corpus wipeout guard: rows arrived but nothing usable was parsed → almost
    # certainly a value UNIT/format mismatch the per-field ABSENCE check can't see (e.g.
    # millisecond epochs overflowing _parse_dt, or 0-100 percent prices failing the [0,1]
    # range). Fail LOUD (the "verify schema on first download" promise) instead of silently
    # returning []. When a category filter is applied it can legitimately empty the set, so
    # the guard only fires when NO category filter is in play.
    if seen_any and not by_market and cats is None:
        raise ValueError(
            f"parsed {n_rows} Polymarket-v1 rows but 0 were usable — likely a schema "
            f"UNIT/format mismatch (ms epoch timestamps? percent prices? wrong column "
            f"names?). First-row columns: {first_row_keys}. Adjust HFFieldSpec / verify units."
        )

    # 2. Per market: reconcile market-level fields + apply the anti-leakage core.
    out: List[HistoricalMarket] = []
    skipped = 0
    for market_id, drows in by_market.items():
        try:
            hm = _assemble_one(market_id, drows, decision_lead, cats)
        except _CategoryFiltered:
            continue
        except (ValueError, AssertionError) as e:
            skipped += 1
            logger.warning("skipping HF market %s (no leakage-safe record): %s", market_id, e)
            continue
        if hm is not None:
            out.append(hm)
    logger.info(
        "assembled %d leakage-safe HistoricalMarket records from %d markets (%d skipped)",
        len(out), len(by_market), skipped,
    )
    return out


class _CategoryFiltered(Exception):
    """Internal sentinel: a market excluded by the pre-registered category filter
    (not a data error — must not count as 'skipped')."""


def _assemble_one(
    market_id: str,
    drows: Sequence[HFDailyRow],
    decision_lead: timedelta,
    cats: Optional[set],
) -> Optional[HistoricalMarket]:
    """Build one leakage-safe HistoricalMarket from a market's daily rows.

    RAISES ValueError (skip in the batch) if the outcome/resolution are inconsistent
    or no pre-resolution price tick exists. Never uses the settled outcome as a price.
    """
    # Resolution time: the daily rows repeat it. Use the EARLIEST (min) as the canonical
    # resolution + leakage cutoff — NOT the max. With max, a row whose true resolution is
    # earlier could still contribute a tick that falls after that earlier resolution but
    # before the max, and it would be admitted as the decision price (a LEAK an auditor
    # demonstrated under jittered resolution_time). Min is the safe cutoff: any tick
    # at-or-after the earliest plausible resolution is potentially contaminated and excluded.
    # Reject rows that disagree beyond a day — a data inconsistency we will not paper over.
    res_times = sorted({r.resolution_time for r in drows})
    if (res_times[-1] - res_times[0]) > timedelta(days=1):
        raise ValueError(f"inconsistent resolution_time across daily rows: {res_times}")
    resolution_time = res_times[0]

    # Outcome: unanimous, clean, and NON-contested. A row whose outcome field was PRESENT
    # but ambiguous carries outcome=None — its presence SKIPS the whole market (never
    # assemble an outcome from only the clean-looking survivors; the survivorship-honesty fix).
    outcomes = {r.outcome for r in drows}
    if None in outcomes:
        raise ValueError(
            f"market {market_id} has a present-but-ambiguous outcome row "
            f"(contested / schema mismatch) — refusing to assemble from survivors"
        )
    if len(outcomes) != 1:
        raise ValueError(f"inconsistent outcome across daily rows: {sorted(outcomes)}")
    outcome = next(iter(outcomes))

    category = next((r.category for r in drows if r.category), "")
    if cats is not None and category.lower() not in cats:
        raise _CategoryFiltered()

    decision_time = resolution_time - decision_lead
    if decision_time >= resolution_time:
        raise ValueError("decision_time must be strictly before resolution_time")

    # Anti-leakage price selection: last tick at-or-before decision_time and strictly
    # before resolution_time. The settled outcome NEVER enters this. Ticks are SORTED by
    # (timestamp, price) so a shard delivering intra-day rows in a different order yields
    # the SAME market_price (determinism — an auditor's duplicate-timestamp finding).
    history = sorted(
        ({"t": r.timestamp.timestamp(), "p": r.price_yes} for r in drows),
        key=lambda x: (x["t"], x["p"]),
    )
    decision_ts = decision_time.timestamp()
    resolution_ts = resolution_time.timestamp()
    market_price = _last_pre_decision_price(history, decision_ts, resolution_ts)
    if market_price is None:
        raise ValueError(
            f"no pre-resolution price tick at/before decision_time for HF market "
            f"{market_id}; refusing to fabricate decision-time price"
        )

    return HistoricalMarket(
        market_id=market_id,
        decision_time=decision_time,
        resolution_time=resolution_time,
        market_price=market_price,
        # Naive crowd baseline: a real strategy OVERRIDES model_prob with its own
        # decision-time estimate (computed from info available up to decision_time).
        model_prob=market_price,
        outcome=outcome,
    )


def _parse_daily_row(raw: dict, spec: HFFieldSpec, *, strict: bool) -> Optional[HFDailyRow]:
    """Parse one raw daily row into an HFDailyRow, or None to skip it.

    ``strict`` (the FIRST parseable row) RAISES with the actual keys when a REQUIRED
    field is missing, so the true schema surfaces on the first real run instead of a
    silent all-skip. Non-strict rows just skip on a missing field (a sparse row is
    not fatal)."""
    def pick(candidates: Tuple[str, ...]) -> Any:
        return _first_present(raw, candidates)

    def require(name: str, candidates: Tuple[str, ...]) -> Any:
        v = pick(candidates)
        if v is None and strict:
            raise ValueError(
                f"Polymarket-v1 daily_aligned row is missing a '{name}' field "
                f"(tried {candidates}); actual columns: {sorted(raw.keys())}. "
                f"Update HFFieldSpec.{name} to the real column name."
            )
        return v

    mid = require("market_id", spec.market_id)
    ts_raw = require("timestamp", spec.timestamp)
    price_raw = require("price_yes", spec.price_yes)
    res_raw = require("resolution_time", spec.resolution_time)
    out_raw = require("outcome", spec.outcome)
    if mid is None or ts_raw is None or price_raw is None or res_raw is None or out_raw is None:
        return None

    timestamp = _parse_dt(ts_raw)
    resolution_time = _parse_dt(res_raw)
    price = _to_float(price_raw)
    # An unparseable/out-of-range required VALUE (not just an absent column) skips the row.
    # A whole-corpus empty result is then caught loudly by assemble_historical_markets so a
    # schema UNIT/format mismatch (ms epochs, percent prices) can't silently return [].
    if timestamp is None or resolution_time is None or price is None:
        return None
    if not math.isfinite(price) or not (0.0 <= price <= 1.0):
        return None

    # Outcome is PRESENT (out_raw not None). A clean 0/1 → the outcome; a present-but-
    # AMBIGUOUS value → None, a CONTESTED / schema-mismatch marker. The row is KEPT (not
    # silently dropped) so _assemble_one skips the WHOLE market rather than assembling an
    # outcome from only the clean-looking survivors (the survivorship-honesty fix).
    outcome = _settled_outcome(out_raw)
    return HFDailyRow(
        market_id=str(mid),
        timestamp=timestamp,
        price_yes=price,
        resolution_time=resolution_time,
        outcome=outcome,   # Optional[int]; None = present-but-ambiguous (contested)
        category=str(pick(spec.category) or ""),
        question=str(pick(spec.question) or ""),
    )


# ---------------------------------------------------------------------------
# Leaf helpers (mirror polymarket_history_fetcher; NaN-timestamp-hardened)
# ---------------------------------------------------------------------------
def _first_present(d: dict, keys: Sequence[str]) -> Any:
    """First key whose value is not None (presence, NOT truthiness — a legit 0/0.0
    is returned, not skipped). None if all absent."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _settled_outcome(value: Any) -> Optional[int]:
    """Map a settled-outcome value to 1 (YES) / 0 (NO), or None if ambiguous.

    Accepts booleans, the strings 'yes'/'no'/'true'/'false'/'1'/'0', and numeric
    values within ``SETTLE_TOL`` of 0 or 1 (a settled outcomePrice). Anything
    ambiguous (e.g. 0.6) returns None so the caller skips rather than guessing."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("yes", "true", "y"):
            return 1
        if s in ("no", "false", "n"):
            return 0
        # fall through: numeric-looking strings handled below
    num = _to_float(value)
    if num is None or not math.isfinite(num):
        return None
    tol = SETTLE_TOL + 1e-9
    if abs(num - 1.0) <= tol:
        return 1
    if abs(num) <= tol:
        return 0
    return None


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 string (with trailing 'Z') OR a unix epoch number (SECONDS or
    MILLISECONDS) into a UTC-aware datetime. Returns None on anything unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    # Numeric unix epoch (int/float or a numeric string).
    num = _to_float(value)
    if num is not None and math.isfinite(num) and not isinstance(value, bool):
        # Heuristic: a plausible unix timestamp (after ~2001). Unix SECONDS never reach 1e11
        # until ~year 5138, whereas MILLISECONDS epochs are ~1e12-1e13 (year 2001-2286) — a
        # very common format in trade archives — so a value > 1e11 is almost certainly ms;
        # scale it to seconds rather than overflowing to None (a schema-drift format the
        # reviewer flagged as a likely first-download surprise).
        if num > 1e11:
            num = num / 1000.0
        if num > 1_000_000_000:
            try:
                return datetime.fromtimestamp(num, tz=timezone.utc)
            except (ValueError, OverflowError, OSError):
                return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _last_pre_decision_price(
    history: Sequence[dict],
    decision_ts: float,
    resolution_ts: float,
) -> Optional[float]:
    """The price ``p`` of the LAST tick with ``t <= decision_ts`` AND ``t <
    resolution_ts``. Returns None if no such pre-resolution tick exists.

    Ticks at/after resolution are excluded — they are (or are contaminated by) the
    settled outcome and must never become a decision price. NaN/inf timestamps are
    rejected up front: a NaN ``t`` fails every ordered comparison silently and would
    otherwise pin ``best_t`` to NaN and block all later real ticks, returning a
    fabricated price (a data-integrity hole shared by every ``_last_pre_decision_price``
    — see the A6/A7/A3 finiteness hardening)."""
    best_t: Optional[float] = None
    best_p: Optional[float] = None
    for tick in history:
        t = _to_float(tick.get("t"))
        p = _to_float(tick.get("p"))
        if t is None or p is None:
            continue
        if not math.isfinite(t):
            continue
        if t > decision_ts:
            continue
        if t >= resolution_ts:  # belt-and-suspenders: never use a settled tick
            continue
        if not (0.0 <= p <= 1.0):
            continue
        if best_t is None or t > best_t:
            best_t, best_p = t, p
    return best_p


__all__ = [
    "HF_DATASET",
    "HF_CONFIG",
    "HFFieldSpec",
    "HFDailyRow",
    "PolymarketV1HFFetcher",
    "assemble_historical_markets",
]
