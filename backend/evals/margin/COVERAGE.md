# Margin eval COVERAGE — LLM-Quant AI workflows

This is the coverage frontier for Margin's per-workflow cost-per-outcome. It
enumerates **every** LLM workflow in the app, marks which have a dedicated eval
suite, and states the honest gaps.

## The metered surface (read this first)

Every LLM call in the product goes through a single choke point:
**`QuantAnalyst._call_llm`** (`backend/app/llm/analyst.py:159`) → Gemini
`generate_content`. Nine `async` analyst methods call it; there is no LLM in the
trading decision path — **the LLM is advisory** (it writes analyses/commentary
for a human), decoupled from order generation.

**Honest gap in the LIVE path:** the app-path inline emit inside `_call_llm`
labels *every* call with the single id `llmquant-signal-check`. So live
economics **conflate all nine methods** into one workflow. These eval suites are
what give real *per-workflow* attribution (each emits its own
`llmquant-<workflow>` id); a future improvement is to pass a per-method
`workflow_id` into `_call_llm` so live traffic is attributed too.

## Workflow map (9 product methods + 1 eval probe)

| Workflow | What it does | Metered path (`analyst.py`) | Outcome signal | Evaled? | Est. spend/importance |
|---|---|---|---|---|---|
| **analyze_stock** | Single-name stock analysis (5 sections) | `:286` → call `:313` (1500 tok) | valid, on-topic, structured analysis that names the symbol | ✅ `analyze-stock` | **High** — core terminal feature, 1500 tok |
| **analyze_portfolio** | Concentration/factor/risk review + rebalance ideas | `:471` → call `:501` (1500 tok) | on-topic analysis grounded in the positions; flags concentration | ✅ `analyze-portfolio` | **High** — portfolio view, 1500 tok |
| **critique_strategy** | Ruthless strategy critique (flaws, biases, verdict) | `:362` → call `:385` (1500 tok) | catches real flaws (leakage/overfit/cost), gives a verdict | ✅ `critique-strategy` | **High** — decision-support, 1500 tok |
| **generate_market_commentary** | 7am desk market commentary | `:324` → call `:352` (1000 tok) | coherent commentary grounded in the indices/sectors | ❌ | Med — dashboard, 1000 tok |
| **analyze_crypto** | Single-name crypto analysis | `:512` → call `:537` (1500 tok) | valid on-topic analysis naming the symbol | ❌ | Med — 1500 tok, narrower use |
| **generate_crypto_commentary** | Crypto market commentary | `:553` → call `:578` (1000 tok) | coherent crypto commentary grounded in data | ❌ | Med — 1000 tok |
| **explain_concept** | Deep-dive quant concept explainer | `:440` → call `:461` (2000 tok) | rigorous, correct explanation of the named concept | ❌ | Med — 2000 tok but educational |
| **get_learning_path** | 12-month personalized learning plan | `:394` → call `:430` (2000 tok) | structured, specific plan matching level/goals | ❌ | Low/Med — 2000 tok, infrequent |
| **generate_trade_summary** | 1-2 sentence trade-log summary | `:642` → call `:676` (150 tok) | concise, faithful summary of the trade inputs | ❌ | Low — cheap (150 tok) but per-trade |
| _signal-check (eval probe)_ | Synthetic prediction-market entry decision (allocate/hold/pass) driven through `_call_llm` | `_call_llm` `:159` | correct verdict vs derived ground truth | ✅ `signal-check` | n/a — eval-defined decision probe |

Note: `signal-check` is an **eval-defined** decision task (not a product method);
it exercises `_call_llm` directly with a designed prompt so we have at least one
**ground-truth-graded** workflow. The nine rows above are the real product
surfaces.

## Coverage

- **Product methods with a dedicated suite: 3 of 9 (33%).**
- The three covered are the **highest-value analysis surfaces** (all 1500 tok,
  core decision-support / terminal features).
- Total eval workflows shipping: **4** (`signal-check`, `analyze-stock`,
  `analyze-portfolio`, `critique-strategy`).
- **Total cases: 103** — signal-check 61 (ground-truth), analyze-stock 16,
  analyze-portfolio 13, critique-strategy 13 (rubric).

## Grading honesty per suite

- **signal-check** — `ground_truth` (derived from scenario economics) for
  directional cases; `heuristic` (validity only) for ambiguous ones.
- **analyze-stock / analyze-portfolio** — `rubric`: advisory tasks with no single
  correct answer, so we grade genuine task completion (non-refusal, min length,
  names the input symbol/ticker, covers ≥N required topic areas). Never
  always-pass.
- **critique-strategy** — `rubric` **plus assertive flaw-catching**: cases built
  with an obvious flaw carry `expected_flags` the critique MUST raise (e.g. a
  zero-cost 99%-win-rate backtest MUST trigger cost + overfitting flags), else it
  FAILS.

Every suite ships **edge** (empty/extreme/degenerate) and seeded **fuzz** cases
for robustness, in addition to normal cases.

## Frontier (next, in priority order)

1. `generate_market_commentary` + `generate_crypto_commentary` (commentary rubric:
   grounded-in-data + coherent + actionable).
2. `analyze_crypto` (mirror of analyze_stock rubric).
3. `explain_concept` (correctness-leaning rubric; could use an LLM-judge or a
   keyed answer bank — heavier).
4. `generate_trade_summary` (faithfulness rubric: summary must reflect the trade
   inputs; cheap so low priority).
5. `get_learning_path` (structure rubric; low frequency).

## Known gaps (honest)

- Spend/importance is an **estimate** from token budgets + likely usage, not
  measured call frequency (we don't have production call counts here). Once live
  per-workflow attribution exists, replace these with real numbers.
- Advisory graders check task completion, not factual correctness of the analysis
  (no ground truth). `explain_concept` is the one workflow where correctness
  grading (answer bank / LLM-judge) would add real signal — deferred.
- `margin-meter` 0.1.0 `record_outcome` has no `session_id`; batch id rides on
  `record_call` (`session_id` + `prompt_id`).
