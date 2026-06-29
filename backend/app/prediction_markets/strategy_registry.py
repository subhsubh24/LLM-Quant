"""
strategy_registry.py — alpha lifecycle state machine (ROADMAP B3 / E4).

WHY THIS EXISTS
VISION's learning loop is: **propose → backtest-gate → paper (stable eval window) →
promote → retire decayed alphas → repeat, forever.** Until now those lifecycle states
lived only as prose verdicts in ``docs/growth/RESEARCH_MEMORY.md`` — there was no code
object that (a) tracks which state each alpha is in, (b) refuses an ILLEGAL transition
(e.g. promoting an alpha that never passed a backtest), and (c) enforces the integrity
bar ROADMAP states plainly: *"No alpha ships while research & backtest integrity is
weak."* This module is that object: a pure, deterministic, JSON-serializable registry
that makes the lifecycle a guard rather than a guideline.

WHAT IT IS / IS NOT
  * IS: a state machine with a fixed legal-transition map; a promotion gate that requires
    explicit, recorded EVIDENCE (backtest passed AND out-of-sample validated AND
    calibration passed); an append-only transition log per alpha; deterministic
    serialization for persistence/inspection.
  * IS NOT: a metrics computer (per-strategy realized PnL lives in
    ``per_strategy_metrics.py``), a scheduler, or anything that fabricates evidence. It
    records the evidence the CALLER supplies; it cannot invent a passing backtest. An
    honest caller passes real gate results; the registry refuses to promote without them.

DETERMINISM
  All timestamps are CALLER-SUPPLIED (``datetime``), never ``datetime.now()`` — so the
  same sequence of calls yields byte-identical serialization, and tests/backtests are
  reproducible. Pure stdlib; trivially CI-importable.

THE STATE MACHINE (legal transitions only — anything else raises ``IllegalTransition``)::

    PROPOSED ─▶ BACKTESTING ─▶ PAPER ─▶ PROMOTED
        │            │            │          │
        └────────────┴────────────┴──────────┴──▶ RETIRED   (abandon / fail / decay)

  * PROPOSED→BACKTESTING: begin offline validation.
  * BACKTESTING→PAPER:    backtest cleared the gate (evidence.backtest_passed required).
  * PAPER→PROMOTED:       paper validated out-of-sample + calibration (evidence: all of
                          backtest_passed, oos_validated, calibration_passed required) —
                          this is the integrity gate.
  * *→RETIRED:            abandon a proposal, retire a failed/decayed alpha (E4). Always
                          legal from any non-terminal state.
  * RETIRED is terminal (no transitions out — a retired alpha is re-PROPOSED as a NEW
    record, preserving history).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple


class LifecycleState(str, Enum):
    """The lifecycle states of an alpha (str-valued so it serializes cleanly)."""

    PROPOSED = "proposed"
    BACKTESTING = "backtesting"
    PAPER = "paper"
    PROMOTED = "promoted"
    RETIRED = "retired"


# Legal transitions (excluding *→RETIRED, which is always allowed from a non-terminal
# state). RETIRED is terminal.
_LEGAL: Dict[LifecycleState, Tuple[LifecycleState, ...]] = {
    LifecycleState.PROPOSED: (LifecycleState.BACKTESTING,),
    LifecycleState.BACKTESTING: (LifecycleState.PAPER,),
    LifecycleState.PAPER: (LifecycleState.PROMOTED,),
    LifecycleState.PROMOTED: (),  # promoted can only be RETIRED (decay)
    LifecycleState.RETIRED: (),   # terminal
}


class IllegalTransition(Exception):
    """Raised (fail-loud) when a lifecycle transition is not permitted."""


class MissingEvidence(Exception):
    """Raised (fail-loud) when a transition lacks the integrity evidence it requires."""


@dataclass(frozen=True)
class Evidence:
    """Recorded, caller-supplied evidence backing a lifecycle transition.

    The registry cannot verify these — it RECORDS them and gates on them. A caller that
    sets ``calibration_passed=True`` without a real passing eval is lying to itself; the
    gate's value is that it refuses to even reach PROMOTED unless all three are present,
    so a promotion can always be audited back to the evidence claimed at the time.
    """

    backtest_passed: bool = False
    oos_validated: bool = False
    calibration_passed: bool = False
    # Optional free-form metrics snapshot (e.g. {"oos_brier": 0.18, "n": 120}). Stored
    # verbatim for the audit trail; not interpreted by the gate.
    metrics: Tuple[Tuple[str, float], ...] = ()

    def to_dict(self) -> dict:
        return {
            "backtest_passed": self.backtest_passed,
            "oos_validated": self.oos_validated,
            "calibration_passed": self.calibration_passed,
            "metrics": {k: v for k, v in self.metrics},
        }

    @staticmethod
    def from_dict(d: dict) -> "Evidence":
        m = d.get("metrics") or {}
        return Evidence(
            backtest_passed=bool(d.get("backtest_passed", False)),
            oos_validated=bool(d.get("oos_validated", False)),
            calibration_passed=bool(d.get("calibration_passed", False)),
            metrics=tuple(sorted((str(k), float(v)) for k, v in m.items())),
        )


@dataclass(frozen=True)
class Transition:
    """One recorded state transition (append-only history)."""

    at: datetime
    from_state: LifecycleState
    to_state: LifecycleState
    reason: str
    evidence: Evidence

    def to_dict(self) -> dict:
        return {
            "at": self.at.astimezone(timezone.utc).isoformat(),
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "reason": self.reason,
            "evidence": self.evidence.to_dict(),
        }


@dataclass
class AlphaRecord:
    """The lifecycle record for a single named alpha.

    NOTE: ``state`` is mutated only via ``StrategyRegistry.transition`` (which enforces
    the legal-transition + integrity gate) and ``history`` is append-only through the same
    path. Callers that obtain a record via ``get``/``in_state`` MUST NOT mutate ``state``
    or ``history`` directly — doing so bypasses the gate. (Kept as a plain dataclass rather
    than frozen because the registry legitimately advances ``state`` in place.)
    """

    name: str
    state: LifecycleState
    created_at: datetime
    history: List[Transition] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
            "history": [t.to_dict() for t in self.history],
        }


def _require_aware(at: datetime) -> datetime:
    """Normalise a caller timestamp to tz-aware UTC (fail loud on a non-datetime)."""
    if not isinstance(at, datetime):
        raise TypeError(f"transition timestamp must be a datetime, got {type(at)!r}")
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


class StrategyRegistry:
    """A registry of alpha lifecycle records. Pure, deterministic, serializable."""

    def __init__(self) -> None:
        self._records: Dict[str, AlphaRecord] = {}

    # ---- queries -------------------------------------------------------
    def __contains__(self, name: str) -> bool:
        return name in self._records

    def get(self, name: str) -> AlphaRecord:
        if name not in self._records:
            raise KeyError(f"unknown alpha {name!r}")
        return self._records[name]

    def state_of(self, name: str) -> LifecycleState:
        return self.get(name).state

    def names(self) -> List[str]:
        """All registered alpha names, sorted (deterministic)."""
        return sorted(self._records)

    def in_state(self, state: LifecycleState) -> List[str]:
        """Names of alphas currently in ``state``, sorted."""
        return sorted(n for n, r in self._records.items() if r.state == state)

    # ---- mutations -----------------------------------------------------
    def propose(self, name: str, at: datetime, reason: str = "") -> AlphaRecord:
        """Register a NEW alpha in the PROPOSED state.

        A name already present (in any state, including RETIRED) raises — retiring then
        re-proposing the same idea must use a distinct name (e.g. ``no_scanner_v2``) so
        history is never overwritten.
        """
        if name in self._records:
            raise IllegalTransition(
                f"alpha {name!r} already exists (state={self._records[name].state.value}); "
                f"use a new name to re-propose"
            )
        at = _require_aware(at)
        self._records[name] = AlphaRecord(
            name=name, state=LifecycleState.PROPOSED, created_at=at
        )
        return self._records[name]

    def transition(
        self,
        name: str,
        to_state: LifecycleState,
        at: datetime,
        reason: str = "",
        evidence: Optional[Evidence] = None,
    ) -> AlphaRecord:
        """Move ``name`` to ``to_state``, enforcing legality + the integrity gate.

        Raises ``IllegalTransition`` if the move is not in the legal map, and
        ``MissingEvidence`` if a gated transition lacks its required evidence.
        """
        record = self.get(name)
        at = _require_aware(at)
        evidence = evidence or Evidence()
        current = record.state

        # RETIRED is always reachable from any non-terminal state (abandon / decay).
        if to_state == LifecycleState.RETIRED:
            if current == LifecycleState.RETIRED:
                raise IllegalTransition(f"{name!r} is already RETIRED (terminal)")
        else:
            if to_state not in _LEGAL.get(current, ()):
                raise IllegalTransition(
                    f"illegal transition for {name!r}: {current.value} → {to_state.value}"
                )

        # Integrity gate: the requirements grow as the alpha advances toward real capital.
        if to_state == LifecycleState.PAPER:
            if not evidence.backtest_passed:
                raise MissingEvidence(
                    f"cannot move {name!r} to PAPER without evidence.backtest_passed"
                )
        if to_state == LifecycleState.PROMOTED:
            missing = [
                k
                for k, v in (
                    ("backtest_passed", evidence.backtest_passed),
                    ("oos_validated", evidence.oos_validated),
                    ("calibration_passed", evidence.calibration_passed),
                )
                if not v
            ]
            if missing:
                raise MissingEvidence(
                    f"cannot PROMOTE {name!r} — integrity evidence missing: {missing}"
                )

        record.history.append(
            Transition(
                at=at,
                from_state=current,
                to_state=to_state,
                reason=reason,
                evidence=evidence,
            )
        )
        record.state = to_state
        return record

    # ---- serialization -------------------------------------------------
    def to_dict(self) -> dict:
        """Deterministic, JSON-serializable snapshot (records sorted by name)."""
        return {"alphas": [self._records[n].to_dict() for n in sorted(self._records)]}

    @staticmethod
    def from_dict(d: dict) -> "StrategyRegistry":
        reg = StrategyRegistry()
        for rec in d.get("alphas", []):
            # Normalise to tz-aware UTC so a naive ISO string in externally-authored JSON
            # cannot make a later to_dict() reinterpret it in the host's local timezone
            # (which would break byte-stable round trips across hosts).
            created = _require_aware(datetime.fromisoformat(rec["created_at"]))
            ar = AlphaRecord(
                name=rec["name"],
                state=LifecycleState(rec["state"]),
                created_at=created,
                history=[
                    Transition(
                        at=_require_aware(datetime.fromisoformat(t["at"])),
                        from_state=LifecycleState(t["from_state"]),
                        to_state=LifecycleState(t["to_state"]),
                        reason=t.get("reason", ""),
                        evidence=Evidence.from_dict(t.get("evidence", {})),
                    )
                    for t in rec.get("history", [])
                ],
            )
            reg._records[ar.name] = ar
        return reg
