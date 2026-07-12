"""Margin eval suite for LLM-Quant.

A repo-specific evaluation suite that measures the STATISTICAL cost-per-outcome
of the ``llmquant-signal-check`` LLM workflow so Margin gets accurate economics
instead of a single "did it return text" signal.

Modules:
  - ``cases``  — the representative input matrix (varied prediction-market
    scenarios across the full outcome spectrum) + the economic ground-truth
    rule that says what the correct verdict is for each scenario.
  - ``grader`` — a genuine grader that parses the model's verdict + confidence
    and grades it against the scenario's ground truth (never always-pass).

The runner lives at ``scripts/margin_eval.py``.
"""
