# `_seed_hash` category migration (ROADMAP C6) — 2026-07-26

`walk_forward._seed_hash` now fingerprints `market_categories` **unconditionally**. Every
pinned reproduction hash moved exactly once as a result. **No published trade count, PnL,
CI or verdict changed** — only the set of inputs the fingerprint covers.

This file is the migration record: what the defect was, why the fix has this shape, the
old→new hash table, and how to re-derive every value yourself.

## The defect

`category` is a field on `HistoricalMarket`. It is **PnL-determining** — there are three
independent paths from a category label to a different realized PnL:

1. `category_exposure_cap` sizes trades down per category (concurrent exposure).
2. `cumulative_category_budget_cap` sizes trades down per category (lifetime budget share).
3. `cost_model.fee_schedule` prices each fill at a **per-category** rate (EXP-010).

It was nonetheless **excluded** from the fingerprint, with an in-code comment asserting the
exclusion was safe ("regime-slice metadata that never affects a decision or PnL"). That
assertion was false, and a gate test pinned it while only ever exercising the cap-free case.

The consequence is the one thing a reproducibility fingerprint exists to prevent: two
datasets identical in every fingerprinted field, differing **only** in their category
labels, produced **one hash** with materially different PnL. On the committed frozen corpus
the published headline hash `79a4cca4b966138f` covers four distinct results:

| category assignment | trades | net PnL | hash |
|---|---:|---:|---|
| as committed | 39 | −$3,228.02 | `79a4cca4b966138f` |
| variant A | 42 | −$3,540.44 | `79a4cca4b966138f` |
| variant B | 43 | −$3,895.06 | `79a4cca4b966138f` |
| variant C | 42 | −$3,537.67 | `79a4cca4b966138f` |

A reviewer comparing hashes to confirm a replay was therefore actively misled.

## Why the fix is unconditional (and not a third guard clause)

Two prior attempts fixed this **conditionally** — fingerprint `category` only when the
engine config makes it matter. Both were broken by a fresh adversarial auditor, at
successive boundaries:

1. Guarding on the two per-category caps missed `cost_model.fee_schedule`.
2. Guarding on the engine's `fee_schedule` missed that `make_calibration_bucket_strategy`
   carries its **own** cost model, uncoupled from the engine's.

PR #424 was abandoned at the 2-cycle brake rather than guessing a third time. The
transferable root cause is the *shape*, not the clauses: **the defect was conditioning a
DATA field on ENGINE CONFIG.** Every other `HistoricalMarket` field is fingerprinted
unconditionally; `category` was the sole conditional one, which is precisely what kept being
breakable. Any conditional guard is only as good as the enumeration of paths behind it, and
that enumeration was wrong twice.

Byte-identity of a hash that *provably collides* is not worth preserving. So the key is
unconditional, the hashes moved once, and they are re-pinned below.

Note the contrast with `category_exposure_cap` / `cumulative_category_budget_cap` /
`fee_schedule`, which remain **added-only-when-set**. That discipline is correct for engine
CONFIG — when a cap is `None` the value is genuinely absent from the run — and incorrect for
DATA, which is always present and always describes the corpus.

## Hash migration table

| what | before | after | verified by |
|---|---|---|---|
| 54-record real fixture | `8dc358439ffb5746` | `44cc4fd8dd1aefc7` | `test_real_data_validation.py` |
| frozen real-OOS corpus headline (cap-free) | `79a4cca4b966138f` | `77ce67d0eacc552e` | `scripts/validate_real_oos.py --from-corpus` |
| synthetic walk-forward demo | `b3a8d5e0e9579853` | recomputed at run time | `scripts/run_walk_forward.py` |
| frozen corpus, cumulative-cap lane | `2e4380ec2cd1f9c6` | recomputed at run time | `--cumulative-category-budget-cap` |

**Discrepancy disclosed:** ROADMAP C6 recorded an auditor's pre-verified prediction of
`8dc358439ffb5746 -> c6cfde99dfcd606a` for the 54-record fixture. The measured value on this
implementation is `44cc4fd8dd1aefc7`. The frozen-corpus prediction
(`79a4cca4b966138f -> 77ce67d0eacc552e`) **did** match exactly, which indicates the payload
layout here agrees with the auditor's prototype and the fixture-lane divergence comes from
something else in that lane (the prototype was measured against the pre-#429/#431 tree). The
pinned values in this repo are the ones **measured on this code**, not the predicted ones —
a predicted hash is not evidence, and pinning a constant that the code does not produce is
how a green suite stops meaning anything.

## Re-deriving these yourself

```bash
# frozen real-OOS corpus — run twice, diff, expect byte-identical
python scripts/validate_real_oos.py --from-corpus data/real_oos_corpus_polymarket.json --json
# 54-record fixture
python -m pytest backend/tests/test_real_data_validation.py
# the collision-closure regression (fails loud on the pre-C6 engine)
python -m pytest backend/tests/test_walk_forward_category.py
```

Verified this run: two `--from-corpus` replays are sha256-identical, and the headline result
is unchanged at 39 trades / −$3,228.02 / F11 `significant_negative`, CI [−4325.5199,
−2403.5774].

## What this is NOT

This closes a **reproducibility-fingerprint** hole. It is not an edge, it does not change any
result, and it moves no DoD or floor box. The binding constraint is unchanged: no validated
out-of-sample edge exists. What changes is that from here on, a matching `seed_hash` actually
means the inputs matched.
