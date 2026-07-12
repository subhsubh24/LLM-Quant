# Margin eval suite — LLM-Quant AI workflows

A repo-specific evaluation suite that gives **Margin** an accurate *statistical
cost-per-outcome* **per LLM workflow**, instead of the coarse "did the model
return text" signal the app path emits for live traffic.

It is **additive only** — nothing here touches the trading/app path.

**Workflow map + coverage frontier:** see [`COVERAGE.md`](./COVERAGE.md). Four
suites ship today (`--workflow` picks one, default `all`):

| Suite | Workflow id | Grading |
|---|---|---|
| `signal-check` | `llmquant-signal-check` | ground-truth (derived) |
| `analyze-stock` | `llmquant-analyze-stock` | rubric |
| `analyze-portfolio` | `llmquant-analyze-portfolio` | rubric |
| `critique-strategy` | `llmquant-critique-strategy` | rubric + flaw-catching |

Registry: `suites.py`. Signal-check matrix/grader: `cases.py` / `grader.py`.
Advisory matrices/graders: `analyst_cases.py` / `analyst_graders.py`.

## What it measures (signal-check example)

The `signal-check` workflow: given a prediction-market entry decision (market
price, an independent fair-value estimate, liquidity, signal confidence,
horizon), the model must return a trading verdict — `allocate` / `hold` / `pass`
— with a confidence. The advisory suites (stock/portfolio/critique) grade genuine
task completion of the real analyst methods.

- **`cases.py`** — a representative input matrix (~60 cases) spanning the full
  outcome spectrum: clear edge, overpriced YES, no edge, thin liquidity, and
  ambiguous/borderline. Genuine variety across categories (Politics, Economics,
  Crypto, Sports, Weather), prices, volumes and confidence. Deterministic.
- **Ground truth is derived, not hand-waved.** `ground_truth(case)` computes the
  economically-correct action from the scenario (fair vs price, friction,
  liquidity, confidence). Ambiguous cases have **no** correct direction and are
  graded on validity only (method `heuristic`), never claimed as ground truth.
- **`grader.py`** — a genuine grader. It **never always-passes**: empty replies,
  unparseable verdicts, missing/out-of-range confidence, and wrong-direction
  calls all FAIL. `quality_score` is a graded number scaled by confidence
  coherence, and `quality_method` is `ground_truth` for directional cases /
  `heuristic` for ambiguous ones.
- **`scripts/margin_eval.py`** — the runner. Sends each case through the REAL
  metered production path (`QuantAnalyst._call_llm` — same Gemini client, model,
  system prompt, spend cap, timeout), captures the full response for real token
  counts + latency, grades it, and emits one `record_call` + one graded
  `record_outcome` per case via the published `margin-meter` SDK
  (`workflow_id="llmquant-signal-check"`, `session_id="eval:<run-id>"`).

## Guardrails

- **No real Gemini in the keyless CI gate.** This is an on-demand / scheduled
  tool. It is **not** wired into `scripts/preflight.sh`. With no `GEMINI_API_KEY`
  it prints a skip and exits 0.
- **`--self-test` is offline** (no Gemini, no network) — it validates the grader
  and matrix and is safe to run anywhere, including CI.
- **Fail-safe emit.** With `MARGIN_INGEST_URL`/`MARGIN_INGEST_KEY` unset it still
  runs and grades, just without emitting.
- **No double-counting.** During each `_call_llm`, the analyst's own inline emit
  is suppressed (the runner hides `MARGIN_INGEST_KEY` from the env for the
  duration) so the runner is the single authoritative emitter and call cost is
  counted once.
- **Cost-capped.** Stops the batch once measured spend crosses `--max-cost-usd`
  (default $1.00) and honors the analyst's own `llm_spend_cap_usd`.

## How to run

```bash
# Offline harness check (no key, no network) — run this in CI or locally:
python3 scripts/margin_eval.py --self-test

# Inspect all suites + case matrices:
python3 scripts/margin_eval.py --list

# Real run: measure + grade + emit to Margin (ALL suites by default)
GEMINI_API_KEY=...            \
MARGIN_INGEST_URL=https://<margin-app>/  \
MARGIN_INGEST_KEY=mgk_...     \
  python3 scripts/margin_eval.py --run-id 2026-07-12a

# Run a single workflow suite:
python3 scripts/margin_eval.py --workflow critique-strategy --run-id 2026-07-12a

# Re-run with a model/config override (comparison), first 20 cases, tighter cap:
python3 scripts/margin_eval.py --model gemini-2.5-pro --limit 20 --max-cost-usd 0.50
```

## Known gaps (honest)

- **Outcome `session_id`.** `margin-meter` 0.1.0's `record_outcome` has no
  `session_id` field, so the batch id is set on `record_call` (plus `prompt_id`
  = case id) but not on outcomes. When the SDK adds it, set it there too.
- **Ground truth is model-relative.** Correctness is judged against the scenario's
  *given* fair value (the bot's own estimate), i.e. it grades whether the model
  acts rationally on the edge it is shown — not whether that fair value later
  proved right in the market. Realized-outcome grading would need resolved
  historical markets and is a separate, heavier layer.
- **Ambiguous cases** are graded on validity/coherence only (method
  `heuristic`), by construction — they have no single correct direction.
