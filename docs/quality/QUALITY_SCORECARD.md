# QUALITY SCORECARD — LLM-Quant

> Produced by the **independent Quality Auditor** (maker ≠ checker). The factory reads
> the fenced `QUALITY_SCORECARD` block below as **data**, never as instructions. Grades
> are backed by mechanical signals the auditor actually ran + file/line evidence (see
> `QUALITY_MEMORY.md` for the dated rationale). Grade scale & ship gate: see
> `QUALITY_RUBRIC.md`.

**As of 2026-07-03 — overall `B`. Ship gate: NOT met.**

The engineering remains genuinely strong and the factory closed real gaps since the
2026-07-01 grade: **four of the five #125 A→A+ hardening nits are now fixed** — backend
mutating-route auth is **default-CLOSED** (unset token → 401, `BACKEND_AUTH_DISABLED`
the sole dev opt-out, verified E2E); the SQLModel dual-registration **suite-ordering
fragility is gone** (951 tests pass identically in default *and* fully-reversed file
order); a **correctness-only ruff gate (E9/F821/F811)** is enforced in CI and passes;
and the dashboard **header/strategy-strip now honors the "—" honesty bar** (no hardcoded
`+$0.00` before load). The curated suite grew **634 → 894** passing. The backtest engine
remains **leak-free, deterministic, and reproducible**, and — new this run — a real OOS
probe was actually executed: the B4a alpha ran on **real Polymarket history (n=52)** and
returned **3 trades, net −$480.86** — an honest **loss**, explicitly labelled "NOT a
validated edge." No fabricated PnL, no unreproducible backtest, no fabricated edge was
found anywhere.

Two things hold the overall at **B** and keep the ship gate closed:

1. **business_case_strength = B (ship-critical, unchanged, THE binding constraint):**
   there is still **no validated, out-of-sample, cost-net edge**. Revenue $0, the
   $104k/yr floor is unmet, and the only real-data OOS run is a small-sample net loss.
   This is the honest north-star state, gated on a real resolved-market corpus that only
   widening egress (owner action, OA-11/OA-16) can unblock. (Issue #79.)
2. **functional_reality A→B (ship-critical, newly surfaced):** on the **degraded-data**
   path, `strategies.py:1451-1457` **fabricates** `total_volume=10000`/`liquidity=5000`
   for every zero-volume market whenever Gamma stops returning volume (>80% zero). Those
   invented values sit *above* every strategy filter threshold (`min_volume` 1000/5000 at
   `:263,:959`; `min_liquidity` 500/1000 at `:381,:439,:781`), so they flip real BUY-gate
   decisions from reject→pass on invented liquidity. The comment's *intent* is to disable
   the filter; the *implementation* injects passing values into the live decision path.
   This is issue **#165** (previously filed MED); it now caps a ship-critical dimension at
   B. Fix by neutralizing the filter on `_volume_unavailable` (or tagging
   `data_incomplete` and excluding from recorded metrics), not by injecting a passing
   number. The rest of the pipeline is genuinely end-to-end and un-stubbed.

## Grades at a glance

| Dimension | Grade | Ship-critical | Headline evidence |
|-----------|:---:|:---:|-------------------|
| functional_reality | B | ✅ | Pipeline is real end-to-end (orchestrator wires scan→DQ→risk→Kelly→executor→persist, `orchestrator.py:778-1032`; real paper fills; fail-closed live gate `execution.py:988-1009`; real n=52 OOS trades). **BUT** `strategies.py:1451-1457` injects synthetic volume=10000/liquidity=5000 on Gamma-zero-volume data, clearing every filter threshold → flips real BUY-gate decisions (#165). |
| backtest_integrity | A | ✅ | Reproduces bit-identically (`seed_hash b3a8d5e0e9579853` synthetic + `8dc358439ffb5746` fixture, ran twice); structural leakage guard (`MarketView` omits `outcome`, `walk_forward.py:95-108`; train = `resolution_time < w_start`, `:361`); fetcher rejects any tick `> decision_ts` / `>= resolution_ts` and RAISES rather than fabricate; costs single-source-of-truth shared with executor (`cost_model.py`→`execution.py:27`). Only real result is an honest loss. Below A+: uncalibrated impact term + n=52. |
| correctness_reliability | A | ✅ | 894/951 pass; determinism verified in default AND fully-reversed file order (SQLModel dual-registration fixed, `eb615c9`); ruff E9/F821/F811 clean; non-finite kelly guard (`orchestrator.py:119-130`), CLOB `[0,1]` coercion (`polymarket_client.py:358`), loss-cap net-of-fees (`execution.py:893,1093`), filled_price None-safety (`:392,:535`) all verified real. |
| security | A | ✅ | Auth **default-CLOSED**: unset token → 401 (`auth.py:47-61`), `BACKEND_AUTH_DISABLED` sole opt-out, fail-closed on settings error; live gate server-side + not body-flippable (`execution.py:990-1009,262-287`); config refuses live boot without token (`config.py:205-212`); 15 mutating routes guarded; no committed secrets (only `.env.example`). |
| run_risk_readiness | A | ✅ | Kill switch wired first in order path (`execution.py:972,931`); loss cap **net-of-fees** trips earlier/conservative (harness: gross −$40 → net −$41.20 trips $10 cap); durable state rehydrates + **fails closed** on unreadable store (`execution.py:804-806`); HUMAN-CORE holds (no loop mutation of `live_enabled`/caps); real `render.yaml`. |
| artifact_integrity | A | ✅ | Every metric honestly 0/null (`BUSINESS_CASE.md:28-36`, `GROWTH_STATUS.md`); "894 tests"=894; seed hashes reproduce; DoD 10 boxes honestly unchecked; `check_scorecard.py gate`→NOT-READY. Nit: `ruff.toml:3-7` comment is now stale (claims full-lint enforcement withheld, but ruff IS in requirements-ci.txt and enforcement is correctness-only). |
| business_case_strength | B | ✅ | Honest no-edge disclosure + credible cost/capacity-aware path — but **no validated OOS edge**: revenue $0, floor unmet, the sole real-data OOS probe is a **net loss** (B4a 3tr −$480.86, n=52). THE binding constraint (#79). |
| design_taste | A | — | #125 header/strategy-strip honesty fixed (`page.tsx:574,604-613`); every number traces to a real API response; charts honest (labeled axes, zero-anchored domains). Nit: positions-tab "Unrealized: +$0.00" doesn't distinguish not-loaded from zero. |
| tests_evals | A | — | 62 test files; leakage/seed-hash/cost/loss-cap/live-gate/calibration coverage proven **non-tautological** via live mutation (dropping fee-netting fails the boundary test); exclusions honest (1 xfail, 1 skip documented). |
| performance | A | — | Scan/execute hot loop O(1) per opp (dict dedup `orchestrator.py:933`); only nested loops are bounded correlation scans; walk_forward O(windows×markets) is cold-path only. Proportionate. |

```yaml
QUALITY_SCORECARD:
  overall: "B"
  as_of: 2026-07-03
  ship_gate_met: false
  graded_by: independent-quality-auditor
  mechanical_signals:
    preflight_code_scope: green        # import smoke + 894 tests + safety + secrets + harness (CI skips full ruff by design)
    pytest_curated: "894 passed, 1 xfailed"
    pytest_full_pandas_free: "951 passed, 16 skipped, 1 xfailed (order-independent: identical default vs reversed file order)"
    runtime_harness: passed            # live gate + kill switch + loss caps (net-of-fees) + paper PnL
    walk_forward_reproduces: true       # seed_hash b3a8d5e0e9579853 (synthetic) + 8dc358439ffb5746 (real fixture), identical PnL across two runs
    real_oos_probe: "B4a alpha 3 trades net -$480.86 OOS on real Polymarket n=52 (honest LOSS; NOT a validated edge); Kalshi leg egress-blocked (429)"
    real_history_fixture: "0 trades / $0 (model_prob == crowd; honest)"
    ci_default_branch: green            # preflight.yml code gate on HEAD b23ea58
    scorecard_gate: "NOT-READY (business_case_strength: B)"
    ruff_correctness_gate: "clean — E9/F821/F811 pass; enforced in CI (requirements-ci.txt + preflight.sh:129)"
    ruff_full: "131 findings (cosmetic hygiene F401/E402/F841; zero F821/E9; unenforced by design)"
  dimensions:
    - name: functional_reality
      grade: "B"
      ship_critical: true
      top_gaps: ["strategies.py:1451-1457 fabricates volume=10000/liquidity=5000 on Gamma-zero-volume (degraded) data; the synthetic values exceed every strategy filter threshold (min_volume/min_liquidity) so they flip real BUY-gate decisions reject->pass on invented liquidity — fabricated data in the live decision path (issue #165). Fix: neutralize the filter on _volume_unavailable (or tag data_incomplete + exclude from metrics), do not inject passing values."]
    - name: backtest_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["market-impact/capacity term is a self-admitted uncalibrated toy (cost_model.py:38-47,104-116) and the only real corpus is n=52 with 3 trades — statistically meaningless, so no positive OOS edge is demonstrated on a meaningful sample (egress-gated); caps below A+."]
    - name: correctness_reliability
      grade: "A"
      ship_critical: true
      top_gaps: ["13 pandas-dependent test files (test_execution_engine/optimization/risk_and_backtest) cannot run in the light env — validated via CI preflight only, not independently re-run; installing pandas in the grading env would close the last corner (documented, non-blocking)."]
    - name: security
      grade: "A"
      ship_critical: true
      top_gaps: []
    - name: run_risk_readiness
      grade: "A"
      ship_critical: true
      top_gaps: ["durable-state restart-survival is proven via an injected in-memory engine, not through the production get_executor() singleton seam end-to-end (test_executor_state_persistence.py never references get_executor) — a coverage nit; wiring is trivial and separately pinned."]
    - name: artifact_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["ruff.toml:3-7 comment is stale after the #125 fix: it claims the requirements-ci.txt ruff add is 'withheld until ruff check backend/app is clean' and that enforcement is the full `ruff check backend/app`, but ruff IS already added (131 findings remain) and enforcement is the correctness-only --select E9,F821,F811 gate — the config file now contradicts its sibling requirements-ci.txt + preflight.sh."]
    - name: business_case_strength
      grade: "B"
      ship_critical: true
      top_gaps: ["no validated out-of-sample cost-net edge exists — revenue $0, $104k/yr floor unmet; the sole real-data OOS probe is a net LOSS (B4a 3tr -$480.86, n=52). Honest but unproven (THE binding constraint); gated on a real >=200-record 7-day-lead resolved-market corpus (OA-11/OA-16, owner/egress)."]
    - name: design_taste
      grade: "A"
      ship_critical: false
      top_gaps: ["positions-tab header renders 'Unrealized: +$0.00' (page.tsx:863-864) — a real reduce over a possibly-empty livePositions that doesn't distinguish 'not loaded' from 'loaded, zero' the way the portfolio tab's '—' null-bar does; minor consistency blemish."]
    - name: tests_evals
      grade: "A"
      ship_critical: false
      top_gaps: ["heavy pandas/sklearn risk/backtest suites stay out of the light CI-blocking gate by design — documented, but a CI coverage hole."]
    - name: performance
      grade: "A"
      ship_critical: false
      top_gaps: ["per-window train rebuild is O(windows*markets); a moving-cursor sweep would make it O(n log n) — cold backtest path only, low stakes."]
  top_gaps:
    - "business_case_strength (B, ship-critical): no validated OOS cost-net edge — the sole real-data OOS probe is a net LOSS (B4a 3tr -$480.86, n=52). Run the alpha through walk_forward on a real, point-in-time, non-survivorship resolved-market panel (>=200 records, 7-day lead) with a passing B2 calibration gate and report a cost-net, reproducible, NON-fragile OOS weekly-PnL series above the $2k/wk floor. THE binding constraint (issue #79, OA-11/OA-16, owner/egress)."
    - "functional_reality (B, ship-critical): strategies.py:1451-1457 injects synthetic volume=10000/liquidity=5000 on degraded (Gamma-zero-volume) data; the values clear every filter threshold and flip real BUY-gate decisions on invented liquidity. Neutralize the filter on _volume_unavailable (or tag data_incomplete + exclude from recorded metrics) instead of fabricating passing values (issue #165)."
    - "artifact/correctness (A->A+): update ruff.toml:3-7 to match the shipped resolution — ruff is present in requirements-ci.txt and enforcement is the correctness-only E9/F821/F811 gate (full lint-at-zero still aspirational, 131 findings) — so the config file stops contradicting requirements-ci.txt + preflight.sh."
    - "design_taste (A->A+): hold the positions-tab 'Unrealized' header to the same '—'-when-unloaded honesty bar as the portfolio tab (distinguish not-loaded from loaded-zero)."
    - "run_risk_readiness (A->A+): add an end-to-end durable-state test through the production get_executor() singleton seam (not only the injected in-memory engine)."
```

## Why ship gate is NOT met

`scripts/check_scorecard.py gate` requires every ship-critical dimension at A/A+ and all
others ≥ B. **Two ship-critical dimensions are B** — `business_case_strength` (no
validated OOS edge) and `functional_reality` (synthetic volume/liquidity on the degraded
path reaches the BUY gate) — so the quality gate fails, and independently the full
`preflight.sh` is honest-RED (`floor_met_year1: false`, DoD boxes unchecked). Both the
edge gap and the data-honesty gap are the same species of the project's core discipline:
**never let a number that isn't real drive a decision.** The factory made real, verified
progress this cycle (four #125 nits closed, +260 passing tests, a real OOS probe run
honestly to a loss); the two remaining ship-critical gaps are correctly, honestly open.
