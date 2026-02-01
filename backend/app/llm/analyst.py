"""
AI-powered market analyst for real-time insights and learning.
Provides professional-grade analysis like a senior quant would deliver.
Uses Anthropic Claude for AI capabilities.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from loguru import logger
import json

from ..config import get_settings


@dataclass
class AnalysisRequest:
    """Request for AI analysis."""
    type: str  # stock, market, portfolio, strategy, learn
    context: Dict[str, Any]
    depth: str = "detailed"  # quick, detailed, comprehensive


class QuantAnalyst:
    """
    AI-powered quant analyst providing institutional-grade insights.
    Uses Claude for deep analysis and learning support.
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
        """Lazy load Anthropic client."""
        if self._client is None and self.settings.has_llm_key:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize Anthropic client: {e}")
        return self._client

    def _call_claude(self, prompt: str, max_tokens: int = 1500) -> Optional[str]:
        """Make a call to Claude API."""
        client = self._get_client()
        if not client:
            return None

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                system=self.SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Claude API call failed: {e}")
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

        response = self._call_claude(prompt, max_tokens=1500)

        if response:
            return {
                "symbol": symbol,
                "analysis": response,
                "generated_at": datetime.now().isoformat(),
                "model": "claude-sonnet-4"
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

        response = self._call_claude(prompt, max_tokens=1000)

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

        response = self._call_claude(prompt, max_tokens=1500)

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

        response = self._call_claude(prompt, max_tokens=2000)

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

        response = self._call_claude(prompt, max_tokens=2000)

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

        response = self._call_claude(prompt, max_tokens=1500)

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

        response = self._call_claude(prompt, max_tokens=1500)

        if response:
            return {
                "symbol": symbol,
                "analysis": response,
                "generated_at": datetime.now().isoformat(),
                "model": "claude-sonnet-4"
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

        response = self._call_claude(prompt, max_tokens=1000)

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
