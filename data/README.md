# `data/` — real prediction-market datasets (OA-11)

## `polymarket_history_sample.json`

A **real, leakage-safe** snapshot of resolved Polymarket markets, produced by
`scripts/fetch_polymarket_history.py` (which drives
`backend/app/prediction_markets/polymarket_history_fetcher.py`) against Polymarket's
**public** Gamma + CLOB APIs. **No credentials** were used — this is read-only public data.

- 54 records, `--order volumeNum --decision-lead-days 2` (liquid markets, decision sampled
  2 days before resolution).
- Each row: `market_id, decision_time, resolution_time, market_price, model_prob, outcome`.

### What it is — and is NOT

- **Leakage-safe by construction.** `market_price` is a genuine CLOB tick at/before
  `decision_time` and strictly before `resolution_time`. The settled outcome price is
  **never** the decision price; the fetcher raises rather than fabricating.
- **`model_prob` is the crowd baseline** (`== market_price`) — **zero edge by
  construction**. A walk-forward on this file (`scripts/run_walk_forward.py --data
  data/polymarket_history_sample.json`) therefore makes **0 trades / $0 PnL** — that proves
  the pipeline runs + reproduces on REAL data; it does **NOT** demonstrate an edge. A real
  edge needs a real model that overrides `model_prob` from decision-time info (ROADMAP B).
- **Known biases (must be stated in any eval):** (1) **liquidity-selection** — `volumeNum`
  ordering keeps only deep markets; (2) **survivorship** — only unambiguously-settled
  binaries; (3) **late-life pinning** — ~70% of these markets had already pinned to
  <0.05 / >0.95 two days out, so the crowd looks extremely sharp here (Brier ≈ 0.09).
  That last one is the headline finding — see
  `docs/autonomous-loop/OA11_REAL_DATA_VALIDATION.md`.

### Regenerate

```bash
python3 scripts/fetch_polymarket_history.py \
  --out data/polymarket_history_sample.json \
  --limit 250 --max-pages 2 --order volumeNum --decision-lead-days 2
```

Run it where Polymarket egress is permitted (a backend host, or a network-permitted CI
job). The autonomous build env blocks egress to Polymarket (a 403 at the proxy), so the
loop cannot refresh this itself — that is the residual of OA-11.
