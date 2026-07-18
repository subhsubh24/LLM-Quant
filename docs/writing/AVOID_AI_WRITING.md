# Avoid AI-writing tells — the full ruleset

The concrete rules behind FACTORY_STANDARD §55. Consult this whenever the factory
writes anything a human will read: product / UI microcopy, marketing & GTM copy,
store listings, outreach, blog posts, docs, PR and commit messages. The goal: prose
that reads like a specific person with a point of view wrote it — not the average
of the internet. This is the §6b "no generic-AI slop" bar applied to words.

Adapted from **github.com/conorbronsdon/avoid-ai-writing**. Run it as a real pass,
not a vibe check.

## Content & language patterns
- **Significance inflation** — cut "marking a pivotal moment in the evolution of…",
  "in the ever-evolving landscape". Use a specific fact ("founded in 2019 to solve X").
- **Notability name-dropping** — don't stack prestigious names for borrowed credibility.
  Attribute concretely ("in a 2024 NYT interview, she argued…").
- **Superficial "-ing" analysis** — "symbolizing… reflecting… showcasing…" → make a
  specific claim or delete.
- **Promotional adjectives** — "vibrant", "nestled", "thriving", "breathtaking" → factual
  description.
- **Vague attribution** — "experts believe", "studies show" → dated, named source
  ("per a 2019 Gartner survey").
- **Formulaic challenge arcs** — "despite challenges… continues to thrive" → name the
  actual challenge and the actual response.
- **Novelty inflation** — "a term I hadn't heard before" → "how X works in practice".

## Tell-words (replace)
Tier 1 (always): leverage→use, utilize→use, robust→reliable, seamless→smooth,
commence→start; and: delve, tapestry, realm, testament, "a testament to". Tier 2/3
accumulate into an "AI voice" at density — "the integration of", "community-driven",
"long-term sustainability", "decentralized compute". Flag when clustering (≥2 repeats
of one phrase, or ≥3 distinct boilerplate phrases).

## Grammar & structure
- **Copula-dressing** — "serves as", "features", "boasts", "presents" → "is", "has".
- **Synonym cycling** — don't rotate developers/engineers/practitioners/builders for one
  concept; repeat the clearest term.
- **Template phrases** — "a [adj] step towards [adj] infrastructure" → the specific outcome.
- **Filler** — "in order to" → "to"; "due to the fact that" → "because".
- **False ranges** — "from the Big Bang to dark matter" → list the actual topics.
- **Parenthetical hedging** — "tools (like X and Y)" → name them or omit.

## Formatting tells
- **Em-dash overuse** — prefer commas and periods; an em-dash is fine sparingly, a stream
  of them is a tell.
- **No emoji headers, no decorative bold.** Selective emphasis only.
- **No inline-header lists** — not "**Speed:** speed improved by…" as a fake heading; write
  the point in prose or keep it a real list.
- **Sentence-case headings** — "Strategic negotiations and partnerships", not Title Case.
- **No numbered-list inflation** — "Here are 7 reasons…" → keep the 2–3 that matter.
- **List labels take a colon, not a period** — "- **Intros:** years of conferences", not
  "- **Intros.** Years of conferences".
- **No bare-noun-phrase bullets** — not "Stable mining efficiency / Reliable pool
  connectivity"; write full sentences with verbs and numbers, or use prose.

## Sentence & paragraph patterns
- **"It's not X, it's Y"** hollow parallelism → a direct positive statement.
- **Rhetorical-question openers** — "What if there were a better way…?" → lead with the claim.
- **Transition overuse** — "Moreover", "Furthermore", "In today's [X]" → "and", "also", or
  restructure.
- **False concession** — "while X has limitations, it's still remarkable" → the genuine tradeoff.
- **Uniform rhythm** — not every paragraph the same length, every sentence 15–25 words. Mix
  short and long; use fragments and the occasional question.
- **Wall-of-text** — break 4+ sentence blocks at thought boundaries.

## Conversational-register tells (kill in comments, replies, outreach)
- No "I hope this helps! Let me know if you have questions."
- No "Let's explore / Let's break this down / Let's dive in." Just start.
- No sycophancy — "Great question!", "You're absolutely right!".
- No recap-flattery openers — "Thanks for all the legwork here — [recap]…". Substance first.
- No acknowledgment loops — "You're asking about…", "To answer your question…". Answer.
- No confidence-calibration filler — "It's worth noting", "Interestingly", "Surprisingly".
- No unearned emotion — "What surprised me most", "I was fascinated to discover".
- No reasoning-chain artifacts — "Let me think step by step", "Breaking this down".
- No cutoff disclaimers — "while details are limited in available sources…".
- No generic conclusions — "the future looks bright", "only time will tell".
- No engagement hooks — "The catch?", "The kicker?", "Here's the thing."
- No self-labeling — "this is the interesting part", "that's the contrarian move". Let it stand.

## Prediction / hedge tells
- **Hedge-stacking** — "could potentially create", "may eventually unlock" → one hedge or none.
- **Future-narrative closers** — "may become one of the most important narratives of the next
  cycle" → make it falsifiable ("X may exceed Y by 2027").
- **"Real/actual" inflation** — "real tokenomics", "actual sustainability" → drop the modifier
  (carve-out: honest contrast like "real settlement, not bridged IOUs" is fine).
- **Hashtag stuffing** — 6+ tags is an LLM tell; use 2–3 specific ones or none.

## AI-tool fingerprints (always strip)
- Unfilled placeholders: `[Your Name]`, `[INSERT SOURCE]`, `2025-XX-XX`.
- Citation markup: `citeturn0search0`, `oai_citation`, `contentReference[oaicite:0]`.
- Tracking params: `utm_source=chatgpt.com`, `utm_source=copilot.com`.
- Speculative gap-filling: "maintains a low profile", "likely began his career" → cut or source.

## Two writer-side judgment tests
- **Paragraph-reshuffle** — if you can swap two body paragraphs without breaking the piece, it
  lacks real logical flow (filler).
- **Treadmill** — if each paragraph mostly restates the previous one in new words, that's the
  LLM-repetition tell.

## Required: the two-pass rewrite
After the first pass removes the obvious tells, RE-READ and catch what survived — recycled
transitions, lingering inflation, copula swaps that snuck back. One pass is never enough.
