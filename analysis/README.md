# analysis/ — reproducible computations behind cited figures (FACTORY_STANDARD §22)

Every quantitative claim in the docs (unit economics, significance, the business-case number,
Channel-Plan economics, etc.) must be produced by **executed, reproducible code** — never mental
arithmetic. This directory holds those computations, and `figures.json` links each committed
figure to the script that produces it so `scripts/validate-computation.mjs` can re-run it and
diff the output against the cited value.

## How to register a figure
1. Write a small script here that computes ONE figure from **committed inputs** (no live network
   / secrets — deterministic inputs → deterministic output; stamp any date/seed). It prints the
   result as the last numeric token on stdout, or as JSON `{"value": <number>}`.
2. Add an entry to `figures.json`:
   ```json
   { "figures": [
       { "id": "ltv_cac", "script": "analysis/ltv_cac.mjs", "value": 3.2, "tolerance": 0.01 }
   ] }
   ```
3. Cite that exact value in the doc. If the inputs change, recompute and update both.

`scripts/validate-computation.mjs` (run by `preflight.sh`) then: runs each script, asserts its
output equals the cited `value` (within `tolerance`), and re-runs it to confirm determinism.
A mismatch, a script error, or non-determinism FAILS the gate. An empty/absent `figures.json`
PASSES vacuously (the pre-launch norm) — the gate lights up as real figures are registered.

**Scope:** this gate checks figures computed from *committed* inputs (formula/arithmetic
correctness). Figures pulled from *live* analytics are the domain of `validate-gtm` (sourcing),
not this gate.
