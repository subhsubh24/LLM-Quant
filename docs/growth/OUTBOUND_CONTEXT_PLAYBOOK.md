# Outbound context-engineering playbook

Reusable method for **evidence-grounded outbound that compounds**. Per
FACTORY_STANDARD §47 (harness leanness / the four-layer window) and §17 (metric
integrity — a claim not in evidence may not be used). The **method** here is
product-agnostic; the **filled-in** ICP, signals, proof, and voice are
product-specific — keep those in `docs/growth/outbound/` for this product and
edit them, don't start from blank.

## Why context, not prompt
Give two agents the same model, prompt, and buying signal and they still send
completely different messages. A **prompt** is what you tell the model to do;
**context** is what it can see while it does it. Most "AI-slop" outreach is a bad
window: too much context averages to generic, too little makes it guess, missing
evidence makes it fabricate. You fix it by engineering the window — deciding, for
each step, what the model sees and what to keep out.

## The four layers (assemble the SMALLEST sufficient window)
- **Role** — the one narrow job of THIS step (extract signals · score one account
  · write one first line), never "run outbound." One labelled step → you can tell
  which part failed.
- **Case** — this one company, this one person, the exact signal that fired this
  week. Without it you have a template with a merge field.
- **Evidence** — two halves: (a) the account's **own history** (what fired, what
  you already sent, whether they went quiet — so you don't reopen a dead angle),
  and (b) the **proof you're cleared to quote** (real numbers/outcomes only). A
  fact not in Evidence is a fact the model may NOT use (§17). This is the layer
  that stops hallucination.
- **Rules** — voice, length, output shape, and the hard stops: no pricing, no
  unverified claim, nothing sent without a human in front of it.

Drop a layer and the failure is predictable — no Role → whole job done badly at
once; no Case → writes to a segment; no Evidence → makes things up; no Rules →
sends something you'd never put your name to.

## The three skills
1. **Assemble** — build the minimum window from the four layers. Leave OUT the
   product catalogue and the back-catalogue of old emails; keep only the one
   signal, the slice of history that stops a repeat, and the proof that fits this
   moment. Too much here = bland; too little = guessing.
2. **Write** — one message grounded ONLY in the window (never the database). Open
   on the CASE signal — never a template opener. Use a proof figure only if it's
   in EVIDENCE; if none fits, state the outcome with no number. Obey every RULE.
   The instruction never changes; the output changes because the window does.
3. **Refine** — after a batch of outcomes (`replied | meeting | no_reply |
   bounced`), write the context back: promote first-lines that earned replies
   into the proof patterns; reweight or drop signal buckets that keep earning
   silence; NEVER add a proof figure that isn't real, even if it would help. The
   output feeds the next Assemble — the messages get better because the context
   underneath them does, with no retraining.

## In the loop
A scheduled job assembles a fresh window per step — extract the real signals from
the day's activity → score who has earned a message and why → Write the first
line → skeptic-check the draft before it goes anywhere — each as its own narrow
Role. Refine runs weekly over outcomes. Output is a ranked shortlist with the
real trigger quoted beside each name (Case put it there; Rules refused a generic
one). This is maker≠checker (§4): the skeptic-check is the checker; approval
before send is non-negotiable.

## Honesty — non-negotiable (GTM metric integrity applied to copy)
- Every proof figure is REAL and sourced (§17). No fabricated traction, no
  invented numbers.
- No auto-send without a human in front of it. No autonomous account creation.
- Refine may promote or reweight, but may never manufacture a proof point.

*This file is the reusable method (product-agnostic). Fill the four-layer files
with this product's ICP, signal readings, proof, and voice; then run the loop by
hand on one real prospect before wiring it in.*
