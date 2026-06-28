# DEEP DIAGNOSIS — for any "it builds/deploys but the user hits an error"

When the build is green and the deploy succeeds but a **user hits an error screen, a
dead end, or a wrong/empty result**, do NOT read code and theorize. Observe the real
system, prove one hypothesis against it, fix the root cause, and verify in the live
data — then peel to the next layer. Record every incident in
[`docs/loop-memory.md`](../loop-memory.md).

This is the BUILDS≠WORKS principle applied to debugging: "tests pass / it compiled" is
necessary, **not sufficient**. If you can't click it (or watch the row/row-absence in
the data), you haven't verified it.

---

## Where the real environment lives (LLM-Quant stack)

LLM-Quant is **frontend (Vercel) → backend (Railway/Render, FastAPI) → DB (Neon
Postgres)**. There is no Supabase Data API here; reach each layer directly:

| Layer | How to OBSERVE it (not theorize) |
|---|---|
| **Backend logs** | Railway/Render service logs (`railway logs`, or the host dashboard). The orchestrator/executor/risk-manager log the cause (`[ORCHESTRATOR]`, `[LIVE GATE]`, `[KILL SWITCH]`, risk-check failures). Read these FIRST. |
| **Frontend / function logs** | Vercel deployment + function logs (middleware, `/api/auth/*`). The Next.js error-boundary copy names the route that threw. |
| **Database (Neon)** | Query live: `psql "$DATABASE_URL"` or the Neon Console SQL editor. `\dt` (list tables), `SELECT … LIMIT 5` (inspect rows), check whether a row was/wasn't written. Neon Console also shows connection/compute logs + autosuspend events. |
| **The live journey** | Reproduce the exact user path on the deployed panel (login → dashboard/predictions/bot → the action that errored). |
| **The API directly** | `curl https://<backend>/health`, `/api/prediction-markets/bot/status`, etc. — confirm the backend is reachable + what it returns. |

> No `DATABASE_URL` to hand? That itself is often the diagnosis (config, not code).

---

## The method (follow in order)

1. **Observe the REAL environment — don't theorize.** Pull the production logs and/or
   query the live DB, or reproduce the exact user journey. The logs usually name the
   cause in seconds — read them FIRST, before touching code.
2. **BUILDS ≠ WORKS — separate three layers with evidence:**
   - **code** (a real bug),
   - **data** (schema/migration drift, bad rows, `init_db` didn't create a table),
   - **config** (missing/wrong env var, connecting as the wrong DB role, `DATABASE_URL`/
     `CORS_ALLOW_ORIGINS`/`NEXT_PUBLIC_API_URL` unset or wrong).
   Decide which BEFORE changing anything. Example: *"no new row + no DB error + no
   app→DB connection"* → it's **config**, not code.
3. **Form ONE hypothesis, then PROVE it against the live system.** Run the exact insert/
   query; diff the code's expected schema vs the live Neon DB column-by-column; confirm a
   row is/isn't created. If you can't prove it, you don't understand it yet — keep
   observing.
4. **Find the UNCAUGHT throw.** A `try/catch` that degrades gracefully **cannot** be the
   source of a hard error screen — hunt the **unguarded** call: a bare auth/session read,
   a `get_settings()` that requires a missing env var, a DB call outside the `try`, an
   LLM/3rd-party call with no timeout. The error-boundary copy tells you which route
   threw; the backend stack trace names the line.
5. **Verify the fix in the REAL system, not the build.** Watch the new row appear / the
   query succeed / the journey complete / the toast fire *after the op truly succeeded*
   (see SIDE-EFFECT INTEGRITY in `FACTORY_STANDARD.md` §6). "Tests pass" is necessary,
   not sufficient. If you can't click it, verify in the data and **say so**.
6. **Fix the ROOT cause + regress + fail LOUD.** Never paper a config bug with a code
   workaround. Add a regression test, and turn the silent trap that hid it into a loud
   error or a bounded call so it can't recur quietly.
7. **Peel the layers.** Fixing one error reveals the next (a single outage can stack
   several causes). Keep going until the **real journey works end to end**, not until the
   first error disappears.
8. **Stay honest.** Change your diagnosis the moment evidence contradicts it; never claim
   "fixed" without proof from the live system.

---

## Two hard rules (from real outages)

- **(a) Every external/LLM/3rd-party call must have a timeout shorter than the runtime
  budget.** A graceful `try/catch` is useless if the runtime kills the process first.
  This bites hardest on **Vercel serverless functions** (middleware, `/api/auth/*`) which
  have a hard execution budget — but applies to the FastAPI backend too: Gemini
  (`google-genai`), Polymarket HTTP/CLOB, and websocket calls must time out and fail
  honestly rather than hang the request or the scan loop.
- **(b) An "optional" env var that a critical path actually requires is a latent
  outage — make it fail loud.** If a code path can't function without a var, it must
  refuse loudly at startup/first use, not silently degrade into a dead end. (Good
  example already in the repo: the password gate **fails closed** when `APP_PASSWORD`/
  `AUTH_SECRET` are unset. Bad pattern to avoid: a critical query that silently no-ops
  when `DATABASE_URL` is missing.)

---

## Worked example — the dashboard "0%" incident (this method in action)

- **Symptom:** the AutoFactory dashboard showed LLM-Quant at 0% engine completeness.
- **Observe (step 1):** instead of guessing, read the dashboard's *actual* parser code
  (`lib/growth.ts` `findFencedBlock`) and compared a working project's file.
- **Layer (step 2):** not code, not data — a **format mismatch** (our blocks were HTML
  comments; the dashboard only reads fenced ```yaml). Also a value bug: owner items used
  `status: pending` but the parser counts `open`/`in_progress`.
- **Prove (step 3):** simulated the dashboard's `findFencedBlock` + YAML parse locally on
  our files → it read *nothing* (confirmed) → after converting to fenced, it read
  `engine_pct=45`.
- **Root cause + loud (steps 5–6):** converted all three blocks to fenced; updated
  `preflight.sh` to parse the fenced form so a block the dashboard can't read now FAILS
  our gate (turned the silent trap loud).
- Logged in loop-memory. (See the 2026-06-27 dashboard entry.)

---

## Recording incidents

For each real "builds but errors" incident, append a dated entry to
`docs/loop-memory.md`: the symptom, which layer (code/data/config), the proof, the root
cause, the regression that makes it fail loud, and confirmation the journey works
end-to-end. Honest, evidence-based — never "fixed" without proof.
