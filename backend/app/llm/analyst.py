"""
AI-powered market analyst for real-time insights and learning.
Provides professional-grade analysis like a senior quant would deliver.
Uses Google Gemini for AI capabilities.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime, date
import logging
import json
import concurrent.futures
import threading
import time

logger = logging.getLogger(__name__)

from ..config import get_settings


# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------

# Hard timeout for every Gemini network call.  A single synchronous call
# that does not return within this window is cancelled and returns None so
# the caller's graceful-degradation path (template fallback) kicks in.
LLM_CALL_TIMEOUT_SEC: float = 30.0

# Gemini 2.5 Flash public pricing (conservative – use higher published rates
# so the estimator is a safe upper bound, not an undercount).
# https://ai.google.dev/pricing  (as of mid-2025)
# Input:  $0.15 / 1M tokens
# Output: $0.60 / 1M tokens
_COST_PER_INPUT_TOKEN_USD: float = 0.15 / 1_000_000
_COST_PER_OUTPUT_TOKEN_USD: float = 0.60 / 1_000_000

# Chars-per-token approximation (conservative: 3 chars ≈ 1 token)
_CHARS_PER_TOKEN: float = 3.0


class LLMBudgetExceeded(RuntimeError):
    """Raised when a requested LLM call would push cumulative estimated spend
    past the configured llm_spend_cap_usd limit.

    Design choice: we RAISE rather than silently drop or log-only because
    a silent drop could mask runaway call loops and still accrue cost if the
    cap is not perfectly tight.  The raised exception is caught by the route
    handler (which returns a 503 / error payload) — the request worker does
    not crash, but the caller learns immediately that the budget is exhausted.
    """


# ---------------------------------------------------------------------------
# Process-local spend tracker (thread-safe, resettable for tests)
# ---------------------------------------------------------------------------

class _SpendTracker:
    """Thread-safe cumulative estimated-spend accumulator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_usd: float = 0.0

    def estimate_cost(self, prompt: str, max_output_tokens: int) -> float:
        """Return a conservative USD cost estimate for one call."""
        input_tokens = max(1, len(prompt) / _CHARS_PER_TOKEN)
        return (
            input_tokens * _COST_PER_INPUT_TOKEN_USD
            + max_output_tokens * _COST_PER_OUTPUT_TOKEN_USD
        )

    def check_and_accrue(self, estimated_cost: float, cap_usd: float) -> None:
        """Raise LLMBudgetExceeded if adding *estimated_cost* would exceed the
        cap; otherwise atomically add it to the running total.

        The check-and-accrue is done under the same lock so two concurrent
        callers cannot both slip through just under the cap.
        """
        with self._lock:
            if self._total_usd + estimated_cost > cap_usd:
                raise LLMBudgetExceeded(
                    f"LLM spend cap of ${cap_usd:.4f} USD would be exceeded. "
                    f"Cumulative so far: ${self._total_usd:.4f} USD, "
                    f"this call estimate: ${estimated_cost:.4f} USD. "
                    "Refusing call to avoid overspend. Reset the tracker or "
                    "raise LLM_SPEND_CAP_USD to continue."
                )
            self._total_usd += estimated_cost

    @property
    def total_usd(self) -> float:
        with self._lock:
            return self._total_usd

    def reset(self) -> None:
        """Reset cumulative spend to zero.  Intended for tests and daily
        scheduled resets; NOT called automatically inside this module."""
        with self._lock:
            self._total_usd = 0.0


# Module-level singleton tracker — shared across all QuantAnalyst instances.
_spend_tracker = _SpendTracker()


def get_spend_tracker() -> _SpendTracker:
    """Return the module-level spend tracker (useful for tests)."""
    return _spend_tracker


@dataclass
class AnalysisRequest:
    """Request for AI analysis."""
    type: str  # stock, market, portfolio, strategy, learn
    context: Dict[str, Any]
    depth: str = "detailed"  # quick, detailed, comprehensive


class QuantAnalyst:
    """
    AI-powered quant analyst providing institutional-grade insights.
    Uses Gemini for deep analysis and learning support.
    """

    SYSTEM_PROMPT = """You are a senior quantitative researcher at a top hedge fund, now mentoring an aspiring quant.

Your background:
- PhD in Financial Mathematics from MIT
- 15 years experience at Renaissance Technologies and Two Sigma
- Expert in factor investing, statistical arbitrage, and ML for finance
- Known for rigorous, skeptical analysis that catches pitfalls others miss

Your teaching style:
- Direct and honest - if something is wrong or risky, say so clearly
- Always explain the "why" behind concepts
- Use real numbers and concrete examples
- Connect theory to practice
- Highlight common mistakes that blow up portfolios
- Suggest specific experiments and next steps

Format your responses with clear sections using markdown headers.
Be concise but thorough. A busy trader should be able to scan and get key points."""

    def __init__(self):
        self.settings = get_settings()
        self._client = None

    def _get_client(self):
        """Lazy load the Gemini client."""
        if self._client is None and self.settings.has_llm_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.settings.gemini_api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini client: {e}")
        return self._client

    def _call_llm(self, prompt: str, max_tokens: int = 1500) -> Optional[str]:
        """Make a call to the Gemini API with timeout and spend-cap enforcement.

        Returns the model's text response, or None when:
        - no API key is configured (template-fallback path, no exception raised)
        - the call times out (logged as ERROR, returns None)
        - the Gemini API returns an error (logged as ERROR, returns None)

        Raises LLMBudgetExceeded (a RuntimeError subclass) when the estimated
        cost of this call would push cumulative spend past llm_spend_cap_usd.
        The exception propagates to the route handler so the caller learns the
        budget is exhausted; it is NOT silently swallowed here.
        """
        client = self._get_client()
        if not client:
            # No API key — graceful no-op, template fallback handles it.
            return None

        # --- Spend cap check (fail loud before making the network call) ---
        estimated_cost = _spend_tracker.estimate_cost(prompt, max_tokens)
        cap = self.settings.llm_spend_cap_usd
        _spend_tracker.check_and_accrue(estimated_cost, cap)
        # From here the cost has been committed to the tracker; if the
        # network call fails or times out the spend was still "used" (we
        # don't roll back) — this is intentionally conservative.

        # --- Timeout-guarded network call ---
        # Resolve the GenerateContentConfig *before* entering the thread so
        # that an ImportError (e.g. google-genai not installed in test env)
        # is caught here rather than silently swallowed inside the executor.
        try:
            from google.genai import types as _genai_types
            _call_config = _genai_types.GenerateContentConfig(
                system_instruction=self.SYSTEM_PROMPT,
                max_output_tokens=max_tokens,
            )
        except ImportError:
            # google-genai not installed — only reachable in tests where the
            # client itself is already a stub that doesn't need a real config.
            _call_config = None

        model_name = self.settings.gemini_model

        # --- Margin economics meter (lazy + guarded + fail-safe) ---
        # Imported here (NOT at module top) so the module still imports and
        # tests still collect when margin-meter is absent (e.g. the CI env,
        # which installs requirements-ci.txt without it). The meter only
        # emits when MARGIN_INGEST_URL + MARGIN_INGEST_KEY are set; unset in
        # CI means no network I/O. All emission is non-blocking and swallows
        # every error so telemetry can never affect the trading path.
        try:
            from margin_meter import MarginMeter
            _meter = MarginMeter(timeout=2.0)
        except Exception:
            _meter = None

        def _do_call() -> Optional[str]:
            kwargs: Dict[str, Any] = {
                "model": model_name,
                "contents": prompt,
            }
            if _call_config is not None:
                kwargs["config"] = _call_config
            _t0 = time.perf_counter()
            response = client.models.generate_content(**kwargs)
            _latency_ms = (time.perf_counter() - _t0) * 1000.0

            # Emit cost-per-outcome telemetry to Margin without blocking the
            # trading path. gemini-2.5-flash can return empty .text without
            # raising, so a non-empty stripped body is the outcome signal.
            if _meter is not None:
                _text = response.text

                def _emit() -> None:
                    try:
                        um = response.usage_metadata
                        _meter.record_call(
                            workflow_id="llmquant-signal-check",
                            provider="google",
                            model=model_name,
                            input_tokens=um.prompt_token_count,
                            output_tokens=um.candidates_token_count,
                            cache_read_tokens=getattr(
                                um, "cached_content_token_count", 0
                            ) or 0,
                            latency_ms=_latency_ms,
                            status="ok",
                        )
                    except Exception:
                        pass
                    try:
                        _meter.record_outcome(
                            workflow_id="llmquant-signal-check",
                            passed=bool(_text and _text.strip()),
                            quality_method="ground_truth",
                        )
                    except Exception:
                        pass

                threading.Thread(target=_emit, daemon=True).start()

            return response.text

        try:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(_do_call)
            try:
                return future.result(timeout=LLM_CALL_TIMEOUT_SEC)
            except concurrent.futures.TimeoutError:
                logger.error(
                    "Gemini API call timed out after %s seconds — "
                    "returning None (template fallback will apply).",
                    LLM_CALL_TIMEOUT_SEC,
                )
                return None
            finally:
                # Do NOT wait for the hung worker thread — shut down without
                # blocking so the caller returns promptly after a timeout.
                executor.shutdown(wait=False, cancel_futures=True)
        except LLMBudgetExceeded:
            # Must not be swallowed here — re-raise so callers know.
            raise
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            return None

    async def analyze_stock(
        self,
        symbol: str,
        quote: Dict,
        price_history: Optional[List[Dict]] = None,
        news: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """Generate comprehensive stock analysis."""
        prompt = f"""Analyze {symbol} for a quant trader. Current data:

**Current Quote:**
- Price: ${quote.get('price', 0):.2f}
- Change: {quote.get('change_percent', 0):.2f}%
- Day Range: ${quote.get('low', 0):.2f} - ${quote.get('high', 0):.2f}

**Recent News Headlines:**
{chr(10).join(['- ' + n.get('headline', '') for n in (news or [])[:5]])}

Provide analysis covering:
1. **Technical Setup** - Key levels, trend, momentum
2. **Quant Factors** - How does it score on momentum, value, quality, volatility?
3. **Risk Assessment** - What could go wrong? Position sizing considerations
4. **Trading Ideas** - Specific entry/exit levels if relevant
5. **For Learning** - What quant concepts does this stock illustrate well?

Be specific with numbers. This is for education, not advice."""

        response = self._call_llm(prompt, max_tokens=1500)

        if response:
            return {
                "symbol": symbol,
                "analysis": response,
                "generated_at": datetime.now().isoformat(),
                "model": self.settings.gemini_model
            }
        return self._template_stock_analysis(symbol, quote)

    async def generate_market_commentary(
        self,
        overview: Dict,
        top_movers: List[Dict] = None
    ) -> Dict[str, Any]:
        """Generate professional market commentary."""
        indices = overview.get('indices', [])
        sectors = overview.get('sectors', [])

        prompt = f"""Generate institutional-grade morning market commentary.

**Market Data (as of {datetime.now().strftime('%Y-%m-%d %H:%M')}):**

Indices:
{chr(10).join([f"- {i.get('name')}: {i.get('price', 0):,.2f} ({i.get('change_percent', 0):+.2f}%)" for i in indices])}

Sector Performance (sorted by performance):
{chr(10).join([f"- {s.get('name')}: {s.get('change_percent', 0):+.2f}%" for s in sectors[:6]])}

Write a brief but insightful commentary covering:
1. **Market Tone** - Risk-on or risk-off? What's driving it?
2. **Sector Rotation** - What's the story behind sector moves?
3. **Key Levels** - Important technical levels to watch
4. **Quant Perspective** - Factor performance, momentum signals
5. **Today's Focus** - What should a quant trader be watching?

Write like you're briefing a trading desk at 7am. Concise, actionable."""

        response = self._call_llm(prompt, max_tokens=1000)

        if response:
            return {
                "commentary": response,
                "generated_at": datetime.now().isoformat(),
                "market_status": overview.get('market_status', 'unknown')
            }
        return self._template_market_commentary(overview)

    async def critique_strategy(
        self,
        strategy_description: str,
        backtest_results: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Provide rigorous critique of a trading strategy."""
        prompt = f"""I want to trade this strategy:

{strategy_description}

{f"Backtest results: {json.dumps(backtest_results)}" if backtest_results else "No backtest provided yet."}

As a senior quant, ruthlessly critique this:

1. **Red Flags** - What concerns you immediately?
2. **Hidden Risks** - What could blow this up that I'm not seeing?
3. **Data Issues** - Potential leakage, survivorship bias, snooping?
4. **Implementation** - Transaction costs, slippage, capacity issues?
5. **Improvements** - How would you make this more robust?
6. **Verdict** - Would you allocate capital? Why/why not?

Be brutally honest. Better to kill a bad idea now than lose money later."""

        response = self._call_llm(prompt, max_tokens=1500)

        if response:
            return {
                "critique": response,
                "generated_at": datetime.now().isoformat()
            }
        return {"error": "LLM not available for strategy critique"}

    async def get_learning_path(
        self,
        current_level: str = "beginner",
        interests: List[str] = None,
        goals: str = "become a quant"
    ) -> Dict[str, Any]:
        """Generate personalized quant learning path."""
        prompt = f"""Create a personalized 12-month learning path for someone who wants to: {goals}

Current level: {current_level}
Interests: {', '.join(interests or ['general quant'])}

Structure the path as:

**Month 1-3: Foundations**
- Specific topics to master
- Key textbooks/resources (be specific with titles)
- Projects to build

**Month 4-6: Core Skills**
- Same structure

**Month 7-9: Advanced Topics**
- Same structure

**Month 10-12: Specialization & Job Prep**
- Same structure

**Weekly Schedule** - How should they structure their learning time?

**Milestones** - How do they know they're progressing?

**Common Mistakes** - What derails most aspiring quants?

Be specific. No vague advice like "learn statistics" - instead say "Complete chapters 1-8 of Casella & Berger, focusing on MLE and hypothesis testing."""

        response = self._call_llm(prompt, max_tokens=2000)

        if response:
            return {
                "learning_path": response,
                "generated_at": datetime.now().isoformat(),
                "estimated_duration": "12 months"
            }
        return self._template_learning_path()

    async def explain_concept(
        self,
        concept: str,
        context: str = ""
    ) -> Dict[str, Any]:
        """Deep dive explanation of a quant concept."""
        prompt = f"""Explain this quant concept thoroughly: {concept}

{f"Context: {context}" if context else ""}

Cover:
1. **What It Is** - Clear definition with mathematical notation if relevant
2. **Why It Matters** - How it's used in real trading
3. **The Math** - Key formulas with intuition for each term
4. **Python Example** - Working code snippet
5. **Common Mistakes** - What trips people up
6. **Interview Question** - A typical interview question about this concept
7. **Further Reading** - Specific papers or book chapters

Make it rigorous enough for a quant interview, but clear enough for a motivated learner."""

        response = self._call_llm(prompt, max_tokens=2000)

        if response:
            return {
                "concept": concept,
                "explanation": response,
                "generated_at": datetime.now().isoformat()
            }
        return {"error": "LLM not available"}

    async def analyze_portfolio(
        self,
        positions: List[Dict],
        total_value: float,
        returns_history: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """Comprehensive portfolio analysis and recommendations."""
        positions_str = "\n".join([
            f"- {p.get('ticker')}: ${p.get('market_value', 0):,.0f} ({p.get('weight', 0)*100:.1f}%) | P&L: {p.get('unrealized_pnl', 0):+,.0f}"
            for p in positions
        ])

        prompt = f"""Analyze this paper trading portfolio:

**Portfolio Value:** ${total_value:,.2f}

**Positions:**
{positions_str}

Provide institutional-grade analysis:

1. **Concentration Risk** - Is the portfolio too concentrated? In what?
2. **Factor Exposures** - What factors is this portfolio betting on?
3. **Sector/Industry Tilts** - Hidden correlations?
4. **Risk Assessment** - What could hurt this portfolio?
5. **Suggested Adjustments** - Specific rebalancing ideas
6. **Learning Moment** - What does this portfolio teach about position sizing?

Be specific with numbers and recommendations."""

        response = self._call_llm(prompt, max_tokens=1500)

        if response:
            return {
                "analysis": response,
                "generated_at": datetime.now().isoformat(),
                "portfolio_value": total_value,
                "n_positions": len(positions)
            }
        return self._template_portfolio_analysis(positions)

    async def analyze_crypto(
        self,
        symbol: str,
        quote: Dict
    ) -> Dict[str, Any]:
        """Generate cryptocurrency analysis."""
        prompt = f"""Analyze {symbol} for a crypto trader. Current data:

**Current Quote:**
- Price: ${quote.get('price', 0):.2f}
- 24h Change: {quote.get('change_percent_24h', 0):.2f}%
- 24h High: ${quote.get('high_24h', 0):.2f}
- 24h Low: ${quote.get('low_24h', 0):.2f}
- Market Cap: ${quote.get('market_cap', 0):,.0f}
- Volume 24h: ${quote.get('volume_24h', 0):,.0f}

Provide analysis covering:
1. **Technical Setup** - Key support/resistance levels, trend analysis
2. **Market Context** - How is this performing vs BTC and overall crypto market?
3. **On-Chain Metrics** - What would you want to check (exchange flows, whale activity)?
4. **Risk Assessment** - Volatility considerations, correlation with BTC
5. **Trading Ideas** - Potential entry/exit zones

Be specific with numbers. This is for education, not advice."""

        response = self._call_llm(prompt, max_tokens=1500)

        if response:
            return {
                "symbol": symbol,
                "analysis": response,
                "generated_at": datetime.now().isoformat(),
                "model": self.settings.gemini_model
            }
        return {
            "symbol": symbol,
            "analysis": f"## {symbol} Quick Analysis\n\n**Current Price:** ${quote.get('price', 0):.2f}\n\n*Configure Anthropic API key for detailed AI analysis.*",
            "generated_at": datetime.now().isoformat(),
            "model": "template"
        }

    async def generate_crypto_commentary(
        self,
        overview: Dict
    ) -> Dict[str, Any]:
        """Generate crypto market commentary."""
        top_cryptos = overview.get('top_cryptos', [])[:5]

        prompt = f"""Generate crypto market commentary.

**Market Data:**
- Total Market Cap: ${overview.get('total_market_cap', 0):,.0f}
- BTC Dominance: {overview.get('btc_dominance', 0)}%

**Top Cryptocurrencies:**
{chr(10).join([f"- {c.get('symbol')}: ${c.get('price', 0):,.2f} ({c.get('change_percent_24h', 0):+.2f}%)" for c in top_cryptos])}

Write a brief market commentary covering:
1. **Market Sentiment** - Risk-on or risk-off for crypto?
2. **BTC Analysis** - Bitcoin's current position and significance
3. **Alt Season?** - Are altcoins outperforming BTC?
4. **Key Levels** - Important price levels to watch
5. **Today's Focus** - What should traders be watching?

Be concise and actionable."""

        response = self._call_llm(prompt, max_tokens=1000)

        if response:
            return {
                "commentary": response,
                "generated_at": datetime.now().isoformat()
            }
        return {
            "commentary": "## Crypto Market Overview\n\nReview the market data displayed on your terminal.\n\n*Configure Anthropic API key for AI-generated commentary.*",
            "generated_at": datetime.now().isoformat()
        }

    def _template_stock_analysis(self, symbol: str, quote: Dict) -> Dict[str, Any]:
        """Fallback template analysis."""
        return {
            "symbol": symbol,
            "analysis": f"""## {symbol} Quick Analysis

**Current Price:** ${quote.get('price', 0):.2f} ({quote.get('change_percent', 0):+.2f}%)

### Key Points
- Monitor relative strength vs sector
- Check recent volume for confirmation
- Review earnings calendar for upcoming catalysts

*Configure Anthropic API key for detailed AI analysis.*""",
            "generated_at": datetime.now().isoformat(),
            "model": "template"
        }

    def _template_market_commentary(self, overview: Dict) -> Dict[str, Any]:
        """Fallback market commentary."""
        return {
            "commentary": """## Market Overview

Review the indices and sector performance displayed on your terminal.

Key factors to consider:
- VIX level indicates current volatility regime
- Sector rotation shows where capital is flowing
- Index breadth (advancers vs decliners) shows market health

*Configure Anthropic API key for AI-generated commentary.*""",
            "generated_at": datetime.now().isoformat(),
            "market_status": overview.get('market_status', 'unknown')
        }

    def _template_portfolio_analysis(self, positions: List[Dict]) -> Dict[str, Any]:
        """Fallback portfolio analysis."""
        return {
            "analysis": f"""## Portfolio Summary

**Positions:** {len(positions)}

### Quick Check
- Review position concentration (largest weight)
- Check sector diversification
- Monitor correlation between holdings

*Configure Anthropic API key for detailed AI analysis.*""",
            "generated_at": datetime.now().isoformat(),
            "n_positions": len(positions)
        }

    async def generate_trade_summary(
        self,
        trade_info: Dict[str, Any]
    ) -> str:
        """Generate a concise LLM summary of why a trade was made."""
        symbol = trade_info.get("symbol", "Unknown")
        asset_class = trade_info.get("asset_class", "unknown")
        strategy = trade_info.get("strategy", "")
        side = trade_info.get("side", "")
        price = trade_info.get("price", 0)
        size = trade_info.get("size", 0)
        score = trade_info.get("score", 0)
        ml_confidence = trade_info.get("ml_confidence", 0)
        iv_rank = trade_info.get("iv_rank", 0)
        regime = trade_info.get("regime", "unknown")
        rationale = trade_info.get("rationale", "")

        prompt = f"""Summarize this trade decision in 1-2 sentences for a trading log:

**Trade Details:**
- Symbol: {symbol}
- Asset Class: {asset_class}
- Strategy: {strategy}
- Side: {side}
- Entry Price: ${price:.2f}
- Position Size: ${size:,.0f}
- ML Score: {score:.1f}
- ML Confidence: {ml_confidence:.1%}
- IV Rank: {iv_rank:.0f}%
- Market Regime: {regime}
- Original Rationale: {rationale}

Write a brief, professional summary explaining why this trade was taken. Include the key factors (IV levels, technical setup, ML signals) in plain English. Keep it under 50 words."""

        response = self._call_llm(prompt, max_tokens=150)

        if response:
            return response.strip()

        # Fallback if LLM not available
        return f"{strategy} on {symbol} - {rationale[:100] if rationale else 'ML score: ' + str(round(score, 1))}"

    def _template_learning_path(self) -> Dict[str, Any]:
        """Fallback learning path."""
        return {
            "learning_path": """## Quant Learning Path (12 Months)

### Months 1-3: Foundations
- Statistics: Khan Academy + "All of Statistics" by Wasserman
- Python: Complete pandas, numpy tutorials
- Project: Build a simple momentum strategy

### Months 4-6: Core Skills
- Machine Learning: Andrew Ng's course
- Financial Theory: Read "Active Portfolio Management" by Grinold & Kahn
- Project: Build a factor model

### Months 7-9: Advanced
- Time Series: Hamilton's textbook, chapters 1-10
- Options: Hull's "Options, Futures, and Other Derivatives"
- Project: Implement a backtest engine

### Months 10-12: Specialization
- Pick a niche: Stat arb, factor investing, or ML
- Interview prep: 150 practice problems
- Project: Full trading system with paper trading

*Configure Anthropic API key for personalized learning paths.*""",
            "generated_at": datetime.now().isoformat(),
            "estimated_duration": "12 months"
        }


# Singleton
_analyst: Optional[QuantAnalyst] = None

def get_quant_analyst() -> QuantAnalyst:
    """Get singleton analyst instance."""
    global _analyst
    if _analyst is None:
        _analyst = QuantAnalyst()
    return _analyst
