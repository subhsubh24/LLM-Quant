"""
Backtest Metrics Calculation Module

Extracted from WalkForwardBacktester: computes performance metrics including
Sharpe ratio, Sortino ratio, max drawdown, profit factor, win rate,
holding period analysis, and diagnostic breakdowns.
"""

import logging
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def calculate_metrics(
    equity_curve: List[Tuple[datetime, float]],
    trades: List[Dict],
    initial_capital: float,
    annualization_factor: float = 365 * 24,
) -> "BacktestResult":
    """
    Calculate backtest performance metrics.

    Args:
        equity_curve: List of (timestamp, equity_value) tuples
        trades: List of trade dicts with pnl, entry_time, exit_time, etc.
        initial_capital: Starting capital
        annualization_factor: Periods per year (e.g. 8760 for 1h crypto)

    Returns:
        BacktestResult dataclass instance
    """
    # Import here to avoid circular dependency
    from .backtester import BacktestResult

    if not equity_curve:
        return _empty_result(initial_capital)

    # BUG FIX #8: Need minimum samples for statistics
    if len(equity_curve) < 10:
        logger.warning(f"Insufficient equity curve samples: {len(equity_curve)} (need >=10 for statistics)")
        if len(equity_curve) == 1:
            logger.warning("   Only 1 point in equity curve - no trades occurred or single candle backtest")

    logger.info("Calculating returns and Sharpe/Sortino ratios...")
    initial = initial_capital
    final = equity_curve[-1][1]

    # Returns
    total_return = final - initial
    total_return_pct = (total_return / initial) * 100

    # Calculate returns for Sharpe/Sortino
    equity_values = [e[1] for e in equity_curve]
    returns = np.diff(equity_values) / (np.array(equity_values[:-1]) + 1e-8)

    # Sharpe Ratio (annualized)
    annualization = annualization_factor
    returns_std = np.std(returns)
    if len(returns) > 1 and returns_std > 1e-8:
        sharpe = np.mean(returns) / returns_std * np.sqrt(annualization)
    else:
        sharpe = 0

    # Sortino Ratio (downside deviation only)
    downside_returns = returns[returns < 0]
    if len(downside_returns) > 0 and np.std(downside_returns) > 1e-8:
        sortino = np.mean(returns) / np.std(downside_returns) * np.sqrt(annualization)
    else:
        sortino = 999.9
        if len(downside_returns) == 0:
            logger.info("PERFECT BACKTEST: All returns positive, Sortino = infinite (set to 999.9)")

    # BUG FIX #19 & #20: Handle NaN values
    sharpe = 0.0 if not np.isfinite(sharpe) else sharpe
    sortino = 0.0 if not np.isfinite(sortino) else sortino

    logger.info("Calculating drawdown...")
    # Max Drawdown
    peak = equity_values[0]
    max_dd = 0
    for value in equity_values:
        if value > peak:
            peak = value
        dd = (peak - value) / max(peak, 1e-8)
        if dd > max_dd:
            max_dd = dd

    logger.info("Analyzing trade statistics...")
    # Trade statistics
    winning_trades = [t for t in trades if t["pnl"] > 0]
    losing_trades = [t for t in trades if t["pnl"] <= 0]

    win_rate = len(winning_trades) / len(trades) if trades else 0
    avg_win = np.mean([t["pnl"] for t in winning_trades]) if winning_trades else 0
    avg_loss = np.mean([abs(t["pnl"]) for t in losing_trades]) if losing_trades else 0

    # Profit factor
    gross_profit = sum(t["pnl"] for t in winning_trades)
    gross_loss = abs(sum(t["pnl"] for t in losing_trades))
    if len(trades) == 0:
        profit_factor = 0.0
    elif gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = 100.0 if gross_profit > 0 else 0.0

    # Average holding period
    holding_periods = []
    for t in trades:
        entry = datetime.fromisoformat(t["entry_time"])
        exit_time = datetime.fromisoformat(t["exit_time"])
        holding_periods.append((exit_time - entry).total_seconds() / 3600)
    avg_holding = np.mean(holding_periods) if holding_periods else 0

    result = BacktestResult(
        start_date=equity_curve[0][0],
        end_date=equity_curve[-1][0],
        initial_capital=initial,
        final_capital=final,
        total_return=total_return,
        total_return_pct=total_return_pct,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=max_dd * initial,
        max_drawdown_pct=max_dd * 100,
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_trades=len(trades),
        winning_trades=len(winning_trades),
        losing_trades=len(losing_trades),
        avg_win=avg_win,
        avg_loss=avg_loss,
        avg_holding_period=avg_holding,
        equity_curve=equity_curve,
        trades=trades,
    )

    # Log final results
    _log_results(result, initial, trades, winning_trades, losing_trades, win_rate, avg_win, avg_loss)

    return result


def _log_results(
    result,
    initial: float,
    trades: List[Dict],
    winning_trades: List[Dict],
    losing_trades: List[Dict],
    win_rate: float,
    avg_win: float,
    avg_loss: float,
) -> None:
    """Log detailed backtest results and diagnostics."""
    logger.info("=" * 80)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 80)
    logger.info(f"Period: {result.start_date.date()} to {result.end_date.date()}")
    logger.info(f"Initial Capital: ${result.initial_capital:,.2f}")
    logger.info(f"Final Capital: ${result.final_capital:,.2f}")
    logger.info(f"Total Return: ${result.total_return:,.2f} ({result.total_return_pct:.2f}%)")
    logger.info(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
    logger.info(f"Sortino Ratio: {result.sortino_ratio:.2f}")
    logger.info(f"Max Drawdown: ${result.max_drawdown:,.2f} ({result.max_drawdown_pct:.2f}%)")
    logger.info(f"Win Rate: {result.win_rate*100:.2f}% ({result.winning_trades}/{result.total_trades} trades)")
    logger.info(f"Profit Factor: {result.profit_factor:.2f}")
    logger.info(f"Avg Win: ${result.avg_win:,.2f}")
    logger.info(f"Avg Loss: ${result.avg_loss:,.2f}")
    logger.info(f"Avg Holding Period: {result.avg_holding_period:.2f} hours")
    logger.info(f"Win/Loss Ratio: {(avg_win / avg_loss if avg_loss > 0 else 0):.2f}")
    logger.info(f"Expected Value/Trade: ${(win_rate * avg_win - (1 - win_rate) * avg_loss):,.2f}")
    logger.info("=" * 80)

    # DIAGNOSTIC METRICS
    if trades:
        logger.info("")
        logger.info("EXIT REASON BREAKDOWN:")
        exit_reasons = {}
        for t in trades:
            reason = t.get("exit_reason", "unknown")
            if reason not in exit_reasons:
                exit_reasons[reason] = {"count": 0, "total_pnl": 0, "wins": 0}
            exit_reasons[reason]["count"] += 1
            exit_reasons[reason]["total_pnl"] += t["pnl"]
            if t["pnl"] > 0:
                exit_reasons[reason]["wins"] += 1
        for reason, stats in sorted(exit_reasons.items(), key=lambda x: x[1]["count"], reverse=True):
            wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
            avg = stats["total_pnl"] / stats["count"] if stats["count"] > 0 else 0
            pct = stats["count"] / len(trades) * 100
            logger.info(f"  {reason:20s}: {stats['count']:4d} trades ({pct:5.1f}%) | WR: {wr:5.1f}% | Avg P&L: ${avg:+7.2f} | Total: ${stats['total_pnl']:+9.2f}")

        logger.info("")
        logger.info("POSITION SIZE ANALYSIS:")
        sizes = [t.get("size", 0) for t in trades if t.get("size", 0) > 0]
        if sizes:
            logger.info(f"  Avg Position Size: ${np.mean(sizes):,.2f}")
            logger.info(f"  Median Position:   ${np.median(sizes):,.2f}")
            logger.info(f"  Min Position:      ${np.min(sizes):,.2f}")
            logger.info(f"  Max Position:      ${np.max(sizes):,.2f}")
            logger.info(f"  Avg % of Capital:  {np.mean(sizes) / initial * 100:.1f}%")

        logger.info("")
        logger.info("PER-SYMBOL P&L (top 10 by absolute P&L):")
        symbol_pnl = {}
        for t in trades:
            sym = t.get("symbol", "unknown")
            if sym not in symbol_pnl:
                symbol_pnl[sym] = {"pnl": 0, "trades": 0, "wins": 0}
            symbol_pnl[sym]["pnl"] += t["pnl"]
            symbol_pnl[sym]["trades"] += 1
            if t["pnl"] > 0:
                symbol_pnl[sym]["wins"] += 1
        sorted_symbols = sorted(symbol_pnl.items(), key=lambda x: abs(x[1]["pnl"]), reverse=True)[:10]
        for sym, stats in sorted_symbols:
            wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
            logger.info(f"  {sym:10s}: ${stats['pnl']:+9.2f} | {stats['trades']:3d} trades | WR: {wr:5.1f}%")

        logger.info("")
        logger.info("HOLDING PERIOD ANALYSIS:")
        win_holds = []
        loss_holds = []
        for t in trades:
            entry = datetime.fromisoformat(t["entry_time"])
            exit_t = datetime.fromisoformat(t["exit_time"])
            hours = (exit_t - entry).total_seconds() / 3600
            if t["pnl"] > 0:
                win_holds.append(hours)
            else:
                loss_holds.append(hours)
        if win_holds:
            logger.info(f"  Winners avg hold:  {np.mean(win_holds):,.0f} hours ({np.mean(win_holds)/24:.1f} days)")
        if loss_holds:
            logger.info(f"  Losers avg hold:   {np.mean(loss_holds):,.0f} hours ({np.mean(loss_holds)/24:.1f} days)")

        logger.info("")
        logger.info("WIN/LOSS DISTRIBUTION:")
        if winning_trades:
            win_pnls = sorted([t["pnl"] for t in winning_trades], reverse=True)
            logger.info(f"  Biggest win:       ${win_pnls[0]:+,.2f}")
            logger.info(f"  Top 5 wins:        ${sum(win_pnls[:5]):+,.2f}")
            logger.info(f"  Median win:        ${np.median(win_pnls):+,.2f}")
        if losing_trades:
            loss_pnls = sorted([t["pnl"] for t in losing_trades])
            logger.info(f"  Biggest loss:      ${loss_pnls[0]:+,.2f}")
            logger.info(f"  Top 5 losses:      ${sum(loss_pnls[:5]):+,.2f}")
            logger.info(f"  Median loss:       ${np.median(loss_pnls):+,.2f}")

        # Max Favorable/Adverse Excursion
        mfe_values = [t.get("max_favorable_excursion", None) for t in trades]
        mae_values = [t.get("max_adverse_excursion", None) for t in trades]
        if any(v is not None for v in mfe_values):
            mfe_vals = [v for v in mfe_values if v is not None]
            mae_vals = [v for v in mae_values if v is not None]
            logger.info("")
            logger.info("EXCURSION ANALYSIS (MFE/MAE):")
            if mfe_vals:
                logger.info(f"  Avg MFE (max favorable): {np.mean(mfe_vals)*100:.2f}%")
                logger.info(f"  Avg MAE (max adverse):   {np.mean(mae_vals)*100:.2f}%")

        logger.info("")


def _empty_result(initial_capital: float) -> "BacktestResult":
    """Return empty backtest result."""
    from .backtester import BacktestResult

    now = datetime.now()
    return BacktestResult(
        start_date=now,
        end_date=now,
        initial_capital=initial_capital,
        final_capital=initial_capital,
        total_return=0,
        total_return_pct=0,
        sharpe_ratio=0,
        sortino_ratio=0,
        max_drawdown=0,
        max_drawdown_pct=0,
        win_rate=0,
        profit_factor=0,
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        avg_win=0,
        avg_loss=0,
        avg_holding_period=0,
    )
