"""LLM layer.

The Gemini-backed advisory analysis path (``analyst.QuantAnalyst``, with the enforced
``LLMBudgetExceeded`` spend cap) lives here and is imported directly by the code/tests that
use it. The former stock-era teaching surface (``QuantExplainer``/``QuantTutor``/
``ResearchMemoGenerator`` behind the ``/learn/*`` routes) was retired in ROADMAP A1 — it was
dead, unwired to the frontend, and built an OpenAI client from a non-existent settings field.
"""
