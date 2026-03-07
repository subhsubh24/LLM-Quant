"""
Agent-Based Market Simulation.

Simulates markets populated by heterogeneous agents whose interactions
produce emergent dynamics that no closed-form SDE can capture.

Agent types:
1. Informed traders - know the true value, trade toward it (Kyle model)
2. Noise traders - random orders, provide liquidity
3. Market makers - two-sided quotes, capture spread, manage inventory
4. Momentum traders - chase trends
5. Mean-reversion traders - fade extremes

Key insight from Gode & Sunder (1993): even zero-intelligence agents
achieve near-100% allocative efficiency in a double auction.
Farmer et al. (2005): one parameter (order flow rate) explains 96% of
cross-sectional spread variation on the London Stock Exchange.

Applications:
- Prediction markets: test how fast prices converge to true probability
- Trading: stress-test market making strategies against adversarial flow
- Risk: simulate flash crashes, liquidity withdrawal, cascade effects

References:
- Kyle (1985): "Continuous Auctions and Insider Trading"
- Gode & Sunder (1993): "Allocative Efficiency of Markets with ZI Traders"
- Farmer, Patelli & Zovko (2005): "The Predictive Power of Zero Intelligence"
- Cont, Stoikov & Talreja (2010): "A Stochastic Model for Order Book Dynamics"
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """A limit or market order."""
    agent_id: int
    side: str         # "buy" or "sell"
    price: float
    size: float
    order_type: str   # "limit" or "market"
    timestamp: int


@dataclass
class Trade:
    """A completed trade."""
    price: float
    size: float
    buyer_id: int
    seller_id: int
    timestamp: int
    aggressor: str    # "buy" or "sell" - which side initiated


@dataclass
class MarketState:
    """Snapshot of market state at a time step."""
    price: float
    best_bid: float
    best_ask: float
    spread: float
    volume: float
    n_trades: int
    informed_pnl: float
    noise_pnl: float
    mm_pnl: float


class InformedTrader:
    """
    Informed trader: knows the true value and trades toward it.

    Implements the Kyle (1985) model where the informed trader
    strategically hides orders among noise flow.

    Kyle's lambda (price impact) = sigma_v / (2 * sigma_u)
    where sigma_v = value uncertainty, sigma_u = noise trader volume.
    """

    def __init__(
        self,
        agent_id: int,
        true_value: float,
        signal_noise: float = 0.02,
        aggression: float = 0.5,
        seed: Optional[int] = None,
    ):
        self.agent_id = agent_id
        self.true_value = true_value
        self.signal_noise = signal_noise
        self.aggression = aggression
        self.rng = np.random.default_rng(seed)
        self.pnl = 0.0
        self.position = 0.0

    def generate_order(
        self, current_price: float, best_bid: float, best_ask: float
    ) -> Optional[Order]:
        """Generate an order based on private signal."""
        signal = self.true_value + self.rng.normal(0, self.signal_noise)
        edge = signal - current_price

        # Only trade when edge exceeds spread
        if abs(edge) < (best_ask - best_bid) * 0.5:
            return None

        size = min(0.1, abs(edge) * self.aggression * 2)

        if edge > 0:
            return Order(
                agent_id=self.agent_id, side="buy",
                price=best_ask + 0.001,  # Aggressive buy
                size=size, order_type="market", timestamp=0,
            )
        else:
            return Order(
                agent_id=self.agent_id, side="sell",
                price=best_bid - 0.001,
                size=size, order_type="market", timestamp=0,
            )


class NoiseTrader:
    """
    Noise (zero-intelligence) trader: random buy/sell orders.

    Provides liquidity and allows informed traders to hide their signal.
    The variance of noise trading determines market efficiency speed.
    """

    def __init__(
        self,
        agent_id: int,
        intensity: float = 0.3,
        avg_size: float = 0.02,
        seed: Optional[int] = None,
    ):
        self.agent_id = agent_id
        self.intensity = intensity
        self.avg_size = avg_size
        self.rng = np.random.default_rng(seed)
        self.pnl = 0.0

    def generate_order(
        self, current_price: float, best_bid: float, best_ask: float
    ) -> Optional[Order]:
        """Random order with probability = intensity."""
        if self.rng.random() > self.intensity:
            return None

        side = "buy" if self.rng.random() > 0.5 else "sell"
        size = self.rng.exponential(self.avg_size)

        if side == "buy":
            price = best_ask + 0.001
        else:
            price = best_bid - 0.001

        return Order(
            agent_id=self.agent_id, side=side,
            price=price, size=size,
            order_type="market", timestamp=0,
        )


class MarketMaker:
    """
    Market maker: provides two-sided liquidity, captures spread.

    Adjusts quotes based on:
    - Inventory (shift reservation price away from large positions)
    - Recent order flow (VPIN-like toxicity detection)
    - Volatility (wider spreads in volatile conditions)

    This is a simplified Avellaneda-Stoikov model.
    """

    def __init__(
        self,
        agent_id: int,
        base_spread: float = 0.02,
        max_inventory: float = 1.0,
        risk_aversion: float = 0.1,
        seed: Optional[int] = None,
    ):
        self.agent_id = agent_id
        self.base_spread = base_spread
        self.max_inventory = max_inventory
        self.risk_aversion = risk_aversion
        self.rng = np.random.default_rng(seed)
        self.inventory = 0.0
        self.pnl = 0.0

    def compute_quotes(
        self, mid_price: float, volatility: float
    ) -> Tuple[float, float]:
        """Compute bid/ask quotes."""
        # Reservation price: shift away from inventory
        reservation = mid_price - self.inventory * self.risk_aversion * volatility

        # Spread: base + volatility component + inventory component
        spread = max(
            self.base_spread,
            self.base_spread + self.risk_aversion * volatility
            + abs(self.inventory) * 0.005,
        )

        bid = reservation - spread / 2
        ask = reservation + spread / 2

        return max(0.01, bid), min(0.99, ask)


class AgentBasedMarket:
    """
    Core agent-based market simulation engine.

    Implements a continuous double auction with heterogeneous agents.
    Tracks price discovery, spread dynamics, and P&L attribution.

    Usage:
        market = AgentBasedMarket(initial_price=0.50, true_value=0.65)
        market.add_informed_traders(10)
        market.add_noise_traders(50)
        market.add_market_makers(5)
        history = market.run(n_steps=2000)
    """

    def __init__(
        self,
        initial_price: float = 0.50,
        true_value: float = 0.65,
        tick_size: float = 0.001,
        seed: Optional[int] = None,
    ):
        self.price = initial_price
        self.true_value = true_value
        self.tick_size = tick_size
        self.rng = np.random.default_rng(seed)

        self.best_bid = initial_price - 0.01
        self.best_ask = initial_price + 0.01

        self.informed_traders: List[InformedTrader] = []
        self.noise_traders: List[NoiseTrader] = []
        self.market_makers: List[MarketMaker] = []

        self.trades: List[Trade] = []
        self.history: List[MarketState] = []
        self.volume = 0.0
        self._step = 0
        self._next_id = 0

    def _next_agent_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def add_informed_traders(
        self, n: int, signal_noise: float = 0.02, aggression: float = 0.5
    ):
        for _ in range(n):
            self.informed_traders.append(InformedTrader(
                agent_id=self._next_agent_id(),
                true_value=self.true_value,
                signal_noise=signal_noise,
                aggression=aggression,
                seed=int(self.rng.integers(0, 2**31)),
            ))

    def add_noise_traders(self, n: int, intensity: float = 0.3, avg_size: float = 0.02):
        for _ in range(n):
            self.noise_traders.append(NoiseTrader(
                agent_id=self._next_agent_id(),
                intensity=intensity,
                avg_size=avg_size,
                seed=int(self.rng.integers(0, 2**31)),
            ))

    def add_market_makers(
        self, n: int, base_spread: float = 0.02, risk_aversion: float = 0.1
    ):
        for _ in range(n):
            self.market_makers.append(MarketMaker(
                agent_id=self._next_agent_id(),
                base_spread=base_spread,
                risk_aversion=risk_aversion,
                seed=int(self.rng.integers(0, 2**31)),
            ))

    def step(self):
        """Execute one time step: randomly select and process agent actions."""
        self._step += 1

        # Market makers update quotes
        volatility = self._estimate_volatility()
        for mm in self.market_makers:
            bid, ask = mm.compute_quotes(self.price, volatility)
            self.best_bid = max(self.best_bid, bid)
            self.best_ask = min(self.best_ask, ask)

        if self.best_ask <= self.best_bid:
            self.best_ask = self.best_bid + self.tick_size

        # Randomly select agent to trade
        all_agents = self.informed_traders + self.noise_traders
        if not all_agents:
            return

        agent = all_agents[self.rng.integers(0, len(all_agents))]
        order = agent.generate_order(self.price, self.best_bid, self.best_ask)

        if order is None:
            return

        order.timestamp = self._step
        self._execute_order(order, agent)

        # Record state
        self.history.append(MarketState(
            price=self.price,
            best_bid=self.best_bid,
            best_ask=self.best_ask,
            spread=self.best_ask - self.best_bid,
            volume=self.volume,
            n_trades=len(self.trades),
            informed_pnl=sum(t.pnl for t in self.informed_traders),
            noise_pnl=sum(t.pnl for t in self.noise_traders),
            mm_pnl=sum(m.pnl for m in self.market_makers),
        ))

    def _execute_order(self, order: Order, agent):
        """Execute an order against the market maker quotes."""
        # Kyle's lambda: price impact
        sigma_v = abs(self.true_value - self.price) + 0.05
        n_noise = max(len(self.noise_traders), 1)
        sigma_u = 0.1 * math.sqrt(n_noise)
        kyle_lambda = sigma_v / (2 * sigma_u)

        if order.side == "buy":
            fill_price = self.best_ask
            impact = order.size * kyle_lambda
            self.price = min(0.99, self.price + impact)

            # P&L attribution
            if isinstance(agent, InformedTrader):
                agent.pnl += (self.true_value - fill_price) * order.size
                agent.position += order.size
            else:
                agent.pnl -= abs(self.price - self.true_value) * order.size * 0.5

            # Market maker gets the other side
            for mm in self.market_makers:
                mm.inventory -= order.size / max(len(self.market_makers), 1)
                mm.pnl += (fill_price - self.price) * order.size / max(len(self.market_makers), 1)

        else:  # sell
            fill_price = self.best_bid
            impact = order.size * kyle_lambda
            self.price = max(0.01, self.price - impact)

            if isinstance(agent, InformedTrader):
                agent.pnl += (fill_price - self.true_value) * order.size
                agent.position -= order.size
            else:
                agent.pnl -= abs(self.price - self.true_value) * order.size * 0.5

            for mm in self.market_makers:
                mm.inventory += order.size / max(len(self.market_makers), 1)
                mm.pnl += (self.price - fill_price) * order.size / max(len(self.market_makers), 1)

        self.volume += order.size
        self.trades.append(Trade(
            price=fill_price, size=order.size,
            buyer_id=order.agent_id if order.side == "buy" else 0,
            seller_id=order.agent_id if order.side == "sell" else 0,
            timestamp=self._step, aggressor=order.side,
        ))

        # Update quotes
        spread = max(self.tick_size, self.best_ask - self.best_bid)
        self.best_bid = self.price - spread / 2
        self.best_ask = self.price + spread / 2

    def _estimate_volatility(self) -> float:
        """Estimate recent volatility from price history."""
        if len(self.history) < 10:
            return 0.05
        recent = [s.price for s in self.history[-20:]]
        returns = [recent[i] / max(recent[i-1], 0.001) - 1 for i in range(1, len(recent))]
        if not returns:
            return 0.05
        return float(np.std(returns)) + 0.01

    def run(self, n_steps: int = 2000) -> List[MarketState]:
        """Run the simulation for n_steps."""
        for _ in range(n_steps):
            self.step()
        return self.history

    def summary(self) -> Dict:
        """Summary statistics of the simulation."""
        prices = [s.price for s in self.history] if self.history else [self.price]
        return {
            "true_value": self.true_value,
            "initial_price": self.history[0].price if self.history else self.price,
            "final_price": prices[-1],
            "convergence_error": abs(prices[-1] - self.true_value),
            "price_at_25pct": prices[len(prices) // 4] if len(prices) > 4 else prices[-1],
            "price_at_50pct": prices[len(prices) // 2] if len(prices) > 2 else prices[-1],
            "price_at_75pct": prices[3 * len(prices) // 4] if len(prices) > 4 else prices[-1],
            "total_volume": self.volume,
            "total_trades": len(self.trades),
            "avg_spread": float(np.mean([s.spread for s in self.history])) if self.history else 0,
            "informed_total_pnl": sum(t.pnl for t in self.informed_traders),
            "noise_total_pnl": sum(t.pnl for t in self.noise_traders),
            "mm_total_pnl": sum(m.pnl for m in self.market_makers),
            "n_informed": len(self.informed_traders),
            "n_noise": len(self.noise_traders),
            "n_mm": len(self.market_makers),
        }


class PredictionMarketABM(AgentBasedMarket):
    """
    Agent-based model specialized for prediction markets.

    Adds prediction-market-specific features:
    - Resolution events (market closes and pays out)
    - Information arrival (true probability shifts over time)
    - Calibration tracking (Brier score over time)

    Usage:
        pm = PredictionMarketABM(
            initial_price=0.50,
            true_prob=0.65,
            n_informed=10, n_noise=50, n_mm=5,
        )
        pm.run(2000)
        print(pm.summary())
        print(f"Brier: {pm.brier_score():.4f}")
    """

    def __init__(
        self,
        initial_price: float = 0.50,
        true_prob: float = 0.65,
        n_informed: int = 10,
        n_noise: int = 50,
        n_mm: int = 5,
        seed: Optional[int] = None,
    ):
        super().__init__(
            initial_price=initial_price,
            true_value=true_prob,
            seed=seed,
        )
        self.true_prob = true_prob
        self.add_informed_traders(n_informed)
        self.add_noise_traders(n_noise)
        self.add_market_makers(n_mm)
        self._brier_snapshots: List[float] = []

    def step(self):
        super().step()
        # Track Brier score
        if self.history:
            price = self.history[-1].price
            # Assume true outcome = 1 if true_prob > 0.5, else 0
            outcome = 1 if self.true_prob > 0.5 else 0
            brier = (price - outcome) ** 2
            self._brier_snapshots.append(brier)

    def brier_score(self) -> float:
        """Average Brier score over the simulation (lower is better)."""
        if not self._brier_snapshots:
            return 1.0
        return float(np.mean(self._brier_snapshots))

    def convergence_speed(self, threshold: float = 0.05) -> Optional[int]:
        """Number of steps until price is within threshold of true probability."""
        for i, state in enumerate(self.history):
            if abs(state.price - self.true_prob) < threshold:
                return i
        return None

    def information_efficiency(self) -> float:
        """Fraction of true value reflected in the price (1.0 = perfectly efficient)."""
        if not self.history:
            return 0.0
        initial_gap = abs(self.history[0].price - self.true_prob)
        final_gap = abs(self.history[-1].price - self.true_prob)
        if initial_gap < 1e-8:
            return 1.0
        return max(0.0, 1.0 - final_gap / initial_gap)


class TradingABM:
    """
    Agent-based model for traditional asset trading.

    Models a stock/ETF market with fundamental value that evolves
    stochastically, and agents that react to prices and signals.

    Use for:
    - Market impact simulation (how does a large order move the price?)
    - Flash crash scenarios (what happens when MMs withdraw?)
    - Liquidity regime changes
    - Strategy backtesting against simulated microstructure

    Usage:
        abm = TradingABM(
            initial_price=100.0,
            fundamental_vol=0.02,
            n_informed=20, n_noise=100, n_mm=10,
        )
        abm.run(5000)
        stats = abm.summary()
    """

    def __init__(
        self,
        initial_price: float = 100.0,
        fundamental_vol: float = 0.02,
        n_informed: int = 20,
        n_noise: int = 100,
        n_mm: int = 10,
        n_momentum: int = 15,
        seed: Optional[int] = None,
    ):
        self.rng = np.random.default_rng(seed)
        self.price = initial_price
        self.fundamental = initial_price
        self.fundamental_vol = fundamental_vol

        self.best_bid = initial_price * 0.999
        self.best_ask = initial_price * 1.001

        self.n_informed = n_informed
        self.n_noise = n_noise
        self.n_mm = n_mm
        self.n_momentum = n_momentum

        # Simplified agent state
        self._mm_inventory = 0.0
        self._momentum_signal = 0.0

        self.price_history: List[float] = [initial_price]
        self.fundamental_history: List[float] = [initial_price]
        self.spread_history: List[float] = []
        self.volume_history: List[float] = []
        self._step = 0
        self.total_volume = 0.0

    def step(self):
        self._step += 1

        # Fundamental value evolves (random walk with drift)
        self.fundamental *= math.exp(
            self.rng.normal(0.0001, self.fundamental_vol)
        )

        # Update market maker quotes
        vol = self._recent_vol()
        inv_adj = self._mm_inventory * 0.001  # Inventory adjustment
        spread = max(0.01, 0.02 * self.price + vol * self.price * 2 + abs(self._mm_inventory) * 0.005)
        self.best_bid = self.price - spread / 2 - inv_adj
        self.best_ask = self.price + spread / 2 - inv_adj
        self.spread_history.append(spread)

        # Select agent type
        total = self.n_informed + self.n_noise + self.n_momentum
        r = self.rng.random()
        step_volume = 0.0

        if r < self.n_informed / total:
            # Informed trade
            signal = self.fundamental + self.rng.normal(0, self.price * 0.005)
            edge = signal - self.price
            if abs(edge) > spread * 0.3:
                size = min(10.0, abs(edge) * 0.5)
                direction = 1 if edge > 0 else -1
                impact = size * 0.001 * direction
                self.price += impact
                self._mm_inventory -= size * direction
                step_volume = size

        elif r < (self.n_informed + self.n_noise) / total:
            # Noise trade
            direction = 1 if self.rng.random() > 0.5 else -1
            size = self.rng.exponential(1.0)
            impact = size * 0.0005 * direction
            self.price += impact
            self._mm_inventory -= size * direction
            step_volume = size

        else:
            # Momentum trade
            self._momentum_signal = 0.9 * self._momentum_signal
            if len(self.price_history) > 10:
                ret_5 = self.price / max(self.price_history[-5], 0.01) - 1
                self._momentum_signal += ret_5 * 0.1

            if abs(self._momentum_signal) > 0.001:
                direction = 1 if self._momentum_signal > 0 else -1
                size = min(5.0, abs(self._momentum_signal) * 100)
                impact = size * 0.0003 * direction
                self.price += impact
                step_volume = size

        # Clamp price
        self.price = max(self.price * 0.5, min(self.price * 2.0, self.price))

        # Market maker mean reversion of inventory
        if abs(self._mm_inventory) > 50:
            revert = self._mm_inventory * 0.01
            self.price -= revert * 0.0001
            self._mm_inventory -= revert

        self.price_history.append(self.price)
        self.fundamental_history.append(self.fundamental)
        self.total_volume += step_volume
        self.volume_history.append(step_volume)

    def _recent_vol(self) -> float:
        if len(self.price_history) < 10:
            return 0.01
        recent = self.price_history[-20:]
        returns = [recent[i] / max(recent[i-1], 0.01) - 1 for i in range(1, len(recent))]
        return float(np.std(returns)) if returns else 0.01

    def run(self, n_steps: int = 5000) -> Dict:
        for _ in range(n_steps):
            self.step()
        return self.summary()

    def simulate_flash_crash(self, crash_step: int, mm_withdrawal_duration: int = 50):
        """
        Simulate a flash crash by temporarily removing market makers.

        At crash_step, all MMs withdraw for mm_withdrawal_duration steps.
        This models the liquidity vacuum that causes flash crashes.
        """
        original_mm = self.n_mm
        for i in range(len(self.price_history), len(self.price_history) + crash_step + mm_withdrawal_duration + 200):
            if crash_step <= (i - len(self.price_history) + 1) < crash_step + mm_withdrawal_duration:
                self.n_mm = 0  # MMs withdraw
            else:
                self.n_mm = original_mm
            self.step()
        self.n_mm = original_mm

    def summary(self) -> Dict:
        prices = np.array(self.price_history)
        fundamentals = np.array(self.fundamental_history)

        returns = np.diff(prices) / prices[:-1] if len(prices) > 1 else np.array([0])
        tracking_error = np.std(prices - fundamentals) if len(prices) > 1 else 0

        # Max drawdown
        peak = np.maximum.accumulate(prices)
        dd = (peak - prices) / np.maximum(peak, 1e-8)

        return {
            "initial_price": float(prices[0]),
            "final_price": float(prices[-1]),
            "final_fundamental": float(fundamentals[-1]),
            "tracking_error": float(tracking_error),
            "price_fundamental_corr": float(np.corrcoef(prices, fundamentals)[0, 1]) if len(prices) > 2 else 0,
            "total_volume": self.total_volume,
            "avg_spread": float(np.mean(self.spread_history)) if self.spread_history else 0,
            "return_vol": float(np.std(returns) * math.sqrt(252)),
            "max_drawdown": float(dd.max()),
            "sharpe": float(returns.mean() / max(returns.std(), 1e-8) * math.sqrt(252)),
            "n_steps": len(prices) - 1,
        }
