"use client";

import { useState, useEffect } from "react";
import {
  Play,
  Settings,
  Sliders,
  AlertCircle,
  CheckCircle,
  Loader2,
  RotateCcw,
  Save,
  Zap,
  Shield,
  TrendingUp,
  Activity,
  Target,
  DollarSign,
  Clock,
  Info,
  BarChart2,
  LineChart,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Algorithm configuration types
interface AlgorithmConfig {
  // Strategy Mode
  mode: "conservative" | "moderate" | "aggressive";
  strategyType: string;

  // Technical Indicators
  rsiPeriod: number;
  rsiOversold: number;
  rsiOverbought: number;
  macdFast: number;
  macdSlow: number;
  macdSignal: number;
  bollingerPeriod: number;
  bollingerStdDev: number;

  // Z-score Mean Reversion
  zscoreLookback: number;
  zscoreEntry: number;
  zscoreExit: number;

  // Momentum
  momentumLookback: number;
  momentumThreshold: number;

  // Risk Management
  maxPositionSize: number;
  stopLossPercent: number;
  takeProfitPercent: number;
  maxHoldingDays: number;

  // Position Sizing
  kellyFraction: number;
  minConfidence: number;
  maxPositions: number;
}

const defaultConfig: AlgorithmConfig = {
  mode: "moderate",
  strategyType: "combined_multi_factor",
  rsiPeriod: 14,
  rsiOversold: 30,
  rsiOverbought: 70,
  macdFast: 12,
  macdSlow: 26,
  macdSignal: 9,
  bollingerPeriod: 20,
  bollingerStdDev: 2,
  zscoreLookback: 20,
  zscoreEntry: -2.0,
  zscoreExit: 0.0,
  momentumLookback: 20,
  momentumThreshold: 0.05,
  maxPositionSize: 10,
  stopLossPercent: 5,
  takeProfitPercent: 10,
  maxHoldingDays: 10,
  kellyFraction: 0.25,
  minConfidence: 0.6,
  maxPositions: 10,
};

const presets: Record<string, Partial<AlgorithmConfig>> = {
  conservative: {
    mode: "conservative",
    strategyType: "combined_multi_factor",
    rsiOversold: 25,
    rsiOverbought: 75,
    bollingerStdDev: 2.5,
    zscoreEntry: -2.5,
    maxPositionSize: 5,
    stopLossPercent: 8,
    takeProfitPercent: 15,
    maxHoldingDays: 14,
    kellyFraction: 0.15,
    minConfidence: 0.7,
    maxPositions: 5,
  },
  moderate: {
    mode: "moderate",
    strategyType: "combined_multi_factor",
    rsiOversold: 30,
    rsiOverbought: 70,
    bollingerStdDev: 2.0,
    zscoreEntry: -2.0,
    maxPositionSize: 10,
    stopLossPercent: 5,
    takeProfitPercent: 10,
    maxHoldingDays: 10,
    kellyFraction: 0.25,
    minConfidence: 0.6,
    maxPositions: 10,
  },
  aggressive: {
    mode: "aggressive",
    strategyType: "momentum",
    rsiOversold: 35,
    rsiOverbought: 65,
    bollingerStdDev: 1.5,
    zscoreEntry: -1.5,
    momentumThreshold: 0.03,
    maxPositionSize: 15,
    stopLossPercent: 2.5,
    takeProfitPercent: 5,
    maxHoldingDays: 5,
    kellyFraction: 0.4,
    minConfidence: 0.5,
    maxPositions: 15,
  },
};

const strategyTypes = [
  { id: "combined_multi_factor", name: "Multi-Factor", description: "RSI + MACD + Bollinger + Z-score" },
  { id: "rsi_oversold", name: "RSI Oversold", description: "Buy when RSI < oversold threshold" },
  { id: "macd_crossover", name: "MACD Crossover", description: "Buy on bullish MACD crossover" },
  { id: "bollinger_bands", name: "Bollinger Bands", description: "Buy at lower band, sell at upper" },
  { id: "momentum", name: "Momentum", description: "Follow strong price trends" },
  { id: "mean_reversion", name: "Mean Reversion", description: "Fade extreme moves" },
  { id: "zscore", name: "Z-Score Statistical", description: "Trade on statistical extremes" },
];

const testSymbols = ["BTC", "ETH", "AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "SPY"];

export default function ResearchPage() {
  const [config, setConfig] = useState<AlgorithmConfig>(defaultConfig);
  const [activeSection, setActiveSection] = useState<string>("strategy");
  const [testing, setTesting] = useState(false);
  const [testResults, setTestResults] = useState<any>(null);
  const [saved, setSaved] = useState(false);
  const [botStatus, setBotStatus] = useState<any>(null);
  const [testSymbol, setTestSymbol] = useState("BTC");
  const [lookbackDays, setLookbackDays] = useState(365);

  // Fetch current bot configuration on load
  useEffect(() => {
    const fetchBotStatus = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/bot/status`);
        if (response.ok) {
          const data = await response.json();
          setBotStatus(data);
        }
      } catch {
        // Ignore
      }
    };

    fetchBotStatus();
  }, []);

  const applyPreset = (preset: string) => {
    const presetConfig = presets[preset];
    if (presetConfig) {
      setConfig({ ...config, ...presetConfig });
      setSaved(false);
      setTestResults(null);
    }
  };

  const resetToDefaults = () => {
    setConfig(defaultConfig);
    setSaved(false);
    setTestResults(null);
  };

  const saveConfig = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/bot/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          max_positions: config.maxPositions,
          max_position_pct: config.maxPositionSize / 100,
          stop_loss_pct: config.stopLossPercent / 100,
          take_profit_pct: config.takeProfitPercent / 100,
        }),
      });
      if (response.ok) {
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      }
    } catch {
      // Handle error
    }
  };

  const runBacktest = async () => {
    setTesting(true);
    setTestResults(null);

    try {
      const response = await fetch(`${API_BASE}/api/strategy/backtest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: testSymbol,
          strategy_type: config.strategyType,
          rsi_period: config.rsiPeriod,
          rsi_oversold: config.rsiOversold,
          rsi_overbought: config.rsiOverbought,
          macd_fast: config.macdFast,
          macd_slow: config.macdSlow,
          macd_signal: config.macdSignal,
          bb_period: config.bollingerPeriod,
          bb_std: config.bollingerStdDev,
          momentum_lookback: config.momentumLookback,
          momentum_threshold: config.momentumThreshold,
          zscore_lookback: config.zscoreLookback,
          zscore_entry: config.zscoreEntry,
          zscore_exit: config.zscoreExit,
          stop_loss_pct: config.stopLossPercent / 100,
          take_profit_pct: config.takeProfitPercent / 100,
          max_holding_days: config.maxHoldingDays,
          position_size_pct: config.maxPositionSize / 100,
          lookback_days: lookbackDays,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setTestResults(data);
      } else {
        const errorData = await response.json().catch(() => ({}));
        setTestResults({
          error: true,
          message: errorData.detail || "Backtest failed - check backend logs",
        });
      }
    } catch (e) {
      setTestResults({
        error: true,
        message: "Network error - ensure backend is running",
      });
    } finally {
      setTesting(false);
    }
  };

  const sections = [
    { id: "strategy", name: "Strategy", icon: Zap },
    { id: "technical", name: "Indicators", icon: Activity },
    { id: "statistical", name: "Statistical", icon: BarChart2 },
    { id: "risk", name: "Risk", icon: Shield },
    { id: "timing", name: "Timing", icon: Clock },
  ];

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Strategy Research Lab</h1>
            <p className="text-gray-500 mt-1">
              Backtest strategies on historical data before deploying to Quant Bot
            </p>
          </div>
          <div className="flex items-center gap-3">
            {botStatus?.is_running && (
              <span className="flex items-center gap-2 px-3 py-1.5 bg-green-50 text-green-700 rounded-full text-sm font-medium">
                <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                Bot Running
              </span>
            )}
            <button
              onClick={resetToDefaults}
              className="flex items-center gap-2 px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <RotateCcw className="w-4 h-4" />
              Reset
            </button>
            <button
              onClick={saveConfig}
              className={cn(
                "flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all",
                saved
                  ? "bg-green-500 text-white"
                  : "bg-gray-900 text-white hover:bg-gray-800"
              )}
            >
              {saved ? <CheckCircle className="w-4 h-4" /> : <Save className="w-4 h-4" />}
              {saved ? "Saved!" : "Deploy to Bot"}
            </button>
          </div>
        </div>
      </div>

      {/* Preset Buttons */}
      <div className="bg-white rounded-2xl border border-gray-200 p-6 mb-6">
        <h3 className="text-sm font-medium text-gray-700 mb-4">Quick Presets</h3>
        <div className="flex gap-3">
          {Object.keys(presets).map((preset) => (
            <button
              key={preset}
              onClick={() => applyPreset(preset)}
              className={cn(
                "flex-1 py-3 px-4 rounded-xl font-medium transition-all border-2",
                config.mode === preset
                  ? preset === "conservative"
                    ? "border-blue-500 bg-blue-50 text-blue-700"
                    : preset === "moderate"
                    ? "border-purple-500 bg-purple-50 text-purple-700"
                    : "border-orange-500 bg-orange-50 text-orange-700"
                  : "border-gray-200 hover:border-gray-300 text-gray-600"
              )}
            >
              <div className="text-lg mb-1 capitalize">{preset}</div>
              <div className="text-xs opacity-70">
                {preset === "conservative" && "Lower risk, steady gains"}
                {preset === "moderate" && "Balanced approach"}
                {preset === "aggressive" && "Higher risk, higher reward"}
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Configuration Sections */}
        <div className="lg:col-span-2 space-y-4">
          {/* Section Tabs */}
          <div className="bg-white rounded-2xl border border-gray-200 p-2">
            <div className="flex gap-1">
              {sections.map((section) => (
                <button
                  key={section.id}
                  onClick={() => setActiveSection(section.id)}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl text-sm font-medium transition-all",
                    activeSection === section.id
                      ? "bg-gray-900 text-white"
                      : "text-gray-600 hover:bg-gray-100"
                  )}
                >
                  <section.icon className="w-4 h-4" />
                  <span className="hidden md:inline">{section.name}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Configuration Panel */}
          <div className="bg-white rounded-2xl border border-gray-200 p-6">
            {activeSection === "strategy" && (
              <div className="space-y-6">
                <SectionHeader
                  title="Strategy Type"
                  description="Choose the core trading algorithm"
                />
                <div className="grid grid-cols-2 gap-3">
                  {strategyTypes.map((strategy) => (
                    <button
                      key={strategy.id}
                      onClick={() => setConfig({ ...config, strategyType: strategy.id })}
                      className={cn(
                        "p-4 rounded-xl border-2 text-left transition-all",
                        config.strategyType === strategy.id
                          ? "border-blue-500 bg-blue-50"
                          : "border-gray-200 hover:border-gray-300"
                      )}
                    >
                      <div className="font-medium text-gray-900">{strategy.name}</div>
                      <div className="text-xs text-gray-500 mt-1">{strategy.description}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {activeSection === "technical" && (
              <div className="space-y-6">
                <SectionHeader
                  title="Technical Indicators"
                  description="Configure the signals that drive trading decisions"
                />

                <div className="space-y-4">
                  <h4 className="text-sm font-semibold text-gray-700">RSI (Relative Strength Index)</h4>
                  <div className="grid grid-cols-3 gap-4">
                    <ConfigInput
                      label="Period"
                      value={config.rsiPeriod}
                      onChange={(v) => setConfig({ ...config, rsiPeriod: v })}
                      min={5}
                      max={30}
                      hint="Standard: 14"
                    />
                    <ConfigInput
                      label="Oversold"
                      value={config.rsiOversold}
                      onChange={(v) => setConfig({ ...config, rsiOversold: v })}
                      min={10}
                      max={40}
                      hint="Buy signal threshold"
                    />
                    <ConfigInput
                      label="Overbought"
                      value={config.rsiOverbought}
                      onChange={(v) => setConfig({ ...config, rsiOverbought: v })}
                      min={60}
                      max={90}
                      hint="Sell signal threshold"
                    />
                  </div>
                </div>

                <div className="space-y-4">
                  <h4 className="text-sm font-semibold text-gray-700">MACD</h4>
                  <div className="grid grid-cols-3 gap-4">
                    <ConfigInput
                      label="Fast Period"
                      value={config.macdFast}
                      onChange={(v) => setConfig({ ...config, macdFast: v })}
                      min={5}
                      max={20}
                      hint="Standard: 12"
                    />
                    <ConfigInput
                      label="Slow Period"
                      value={config.macdSlow}
                      onChange={(v) => setConfig({ ...config, macdSlow: v })}
                      min={15}
                      max={40}
                      hint="Standard: 26"
                    />
                    <ConfigInput
                      label="Signal Period"
                      value={config.macdSignal}
                      onChange={(v) => setConfig({ ...config, macdSignal: v })}
                      min={5}
                      max={15}
                      hint="Standard: 9"
                    />
                  </div>
                </div>

                <div className="space-y-4">
                  <h4 className="text-sm font-semibold text-gray-700">Bollinger Bands</h4>
                  <div className="grid grid-cols-2 gap-4">
                    <ConfigInput
                      label="Period"
                      value={config.bollingerPeriod}
                      onChange={(v) => setConfig({ ...config, bollingerPeriod: v })}
                      min={10}
                      max={50}
                      hint="Standard: 20"
                    />
                    <ConfigInput
                      label="Std Deviations"
                      value={config.bollingerStdDev}
                      onChange={(v) => setConfig({ ...config, bollingerStdDev: v })}
                      min={1}
                      max={4}
                      step={0.5}
                      hint="Standard: 2"
                    />
                  </div>
                </div>
              </div>
            )}

            {activeSection === "statistical" && (
              <div className="space-y-6">
                <SectionHeader
                  title="Statistical Indicators"
                  description="Mean reversion and momentum parameters"
                />

                <div className="space-y-4">
                  <h4 className="text-sm font-semibold text-gray-700">Z-Score Mean Reversion</h4>
                  <div className="grid grid-cols-3 gap-4">
                    <ConfigInput
                      label="Lookback"
                      value={config.zscoreLookback}
                      onChange={(v) => setConfig({ ...config, zscoreLookback: v })}
                      min={10}
                      max={60}
                      hint="Days for mean calc"
                    />
                    <ConfigInput
                      label="Entry Z"
                      value={config.zscoreEntry}
                      onChange={(v) => setConfig({ ...config, zscoreEntry: v })}
                      min={-4}
                      max={-0.5}
                      step={0.1}
                      hint="Buy when Z < this"
                    />
                    <ConfigInput
                      label="Exit Z"
                      value={config.zscoreExit}
                      onChange={(v) => setConfig({ ...config, zscoreExit: v })}
                      min={-1}
                      max={1}
                      step={0.1}
                      hint="Exit when Z > this"
                    />
                  </div>
                </div>

                <div className="space-y-4">
                  <h4 className="text-sm font-semibold text-gray-700">Momentum</h4>
                  <div className="grid grid-cols-2 gap-4">
                    <ConfigInput
                      label="Lookback Days"
                      value={config.momentumLookback}
                      onChange={(v) => setConfig({ ...config, momentumLookback: v })}
                      min={5}
                      max={60}
                      hint="Days to measure momentum"
                    />
                    <ConfigInput
                      label="Threshold"
                      value={config.momentumThreshold * 100}
                      onChange={(v) => setConfig({ ...config, momentumThreshold: v / 100 })}
                      min={1}
                      max={20}
                      suffix="%"
                      hint="Min move to trigger"
                    />
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-blue-50 border border-blue-100">
                  <div className="flex items-start gap-3">
                    <Info className="w-5 h-5 text-blue-500 mt-0.5" />
                    <div className="text-sm text-blue-700">
                      <p className="font-medium mb-1">Z-Score Strategy</p>
                      <p className="text-blue-600">
                        Z-score measures how far price is from its mean in standard deviations.
                        Z &lt; -2 means price is 2 standard deviations below average (statistically oversold).
                        Mean reversion strategies buy at extreme negative Z and sell when Z returns to 0.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeSection === "risk" && (
              <div className="space-y-6">
                <SectionHeader
                  title="Risk Management"
                  description="Control your exposure and protect capital"
                />

                <div className="grid grid-cols-2 gap-4">
                  <ConfigInput
                    label="Max Position Size"
                    value={config.maxPositionSize}
                    onChange={(v) => setConfig({ ...config, maxPositionSize: v })}
                    min={1}
                    max={25}
                    suffix="%"
                    hint="Max % of portfolio per trade"
                  />
                  <ConfigInput
                    label="Max Positions"
                    value={config.maxPositions}
                    onChange={(v) => setConfig({ ...config, maxPositions: v })}
                    min={1}
                    max={25}
                    hint="Maximum concurrent trades"
                  />
                  <ConfigInput
                    label="Stop Loss"
                    value={config.stopLossPercent}
                    onChange={(v) => setConfig({ ...config, stopLossPercent: v })}
                    min={1}
                    max={20}
                    suffix="%"
                    hint="Exit on loss threshold"
                  />
                  <ConfigInput
                    label="Take Profit"
                    value={config.takeProfitPercent}
                    onChange={(v) => setConfig({ ...config, takeProfitPercent: v })}
                    min={2}
                    max={50}
                    suffix="%"
                    hint="Exit on profit threshold"
                  />
                  <ConfigInput
                    label="Kelly Fraction"
                    value={config.kellyFraction}
                    onChange={(v) => setConfig({ ...config, kellyFraction: v })}
                    min={0.1}
                    max={1}
                    step={0.05}
                    hint="Fraction of Kelly criterion"
                  />
                  <ConfigInput
                    label="Min Confidence"
                    value={config.minConfidence}
                    onChange={(v) => setConfig({ ...config, minConfidence: v })}
                    min={0.3}
                    max={0.9}
                    step={0.05}
                    hint="Minimum signal confidence"
                  />
                </div>
              </div>
            )}

            {activeSection === "timing" && (
              <div className="space-y-6">
                <SectionHeader
                  title="Timing Parameters"
                  description="Control holding periods and trade frequency"
                />

                <div className="grid grid-cols-2 gap-4">
                  <ConfigInput
                    label="Max Holding Days"
                    value={config.maxHoldingDays}
                    onChange={(v) => setConfig({ ...config, maxHoldingDays: v })}
                    min={1}
                    max={30}
                    suffix="days"
                    hint="Auto-exit if exceeded"
                  />
                </div>

                <div className="p-4 rounded-xl bg-amber-50 border border-amber-100">
                  <div className="flex items-start gap-3">
                    <Clock className="w-5 h-5 text-amber-500 mt-0.5" />
                    <div className="text-sm text-amber-700">
                      <p className="font-medium mb-1">Holding Period Impact</p>
                      <p className="text-amber-600">
                        Shorter holding periods (1-5 days) suit aggressive momentum strategies.
                        Longer periods (10-14+ days) work better for mean reversion and value strategies.
                        Max holding prevents dead positions from tying up capital.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Test Panel */}
        <div className="space-y-4">
          <div className="bg-white rounded-2xl border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Play className="w-5 h-5 text-green-500" />
              Backtest Configuration
            </h3>

            <div className="space-y-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Test Symbol</label>
                <select
                  value={testSymbol}
                  onChange={(e) => setTestSymbol(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  {testSymbols.map((symbol) => (
                    <option key={symbol} value={symbol}>
                      {symbol}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Lookback Period</label>
                <select
                  value={lookbackDays}
                  onChange={(e) => setLookbackDays(parseInt(e.target.value))}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value={90}>90 days (3 months)</option>
                  <option value={180}>180 days (6 months)</option>
                  <option value={365}>365 days (1 year)</option>
                  <option value={730}>730 days (2 years)</option>
                </select>
              </div>
            </div>

            <button
              onClick={runBacktest}
              disabled={testing}
              className={cn(
                "w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl font-medium transition-all",
                testing
                  ? "bg-gray-100 text-gray-400 cursor-not-allowed"
                  : "bg-gradient-to-r from-green-500 to-emerald-500 text-white hover:from-green-600 hover:to-emerald-600"
              )}
            >
              {testing ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Running Backtest...
                </>
              ) : (
                <>
                  <Play className="w-5 h-5" />
                  Run Historical Backtest
                </>
              )}
            </button>
          </div>

          {/* Test Results */}
          {testResults && !testResults.error && (
            <div className="bg-white rounded-2xl border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <LineChart className="w-5 h-5 text-blue-500" />
                Backtest Results
              </h3>

              <div className="space-y-3">
                <ResultRow
                  label="Total Return"
                  value={`${testResults.metrics.total_return}%`}
                  positive={testResults.metrics.total_return > 0}
                />
                <ResultRow
                  label="Annual Return"
                  value={`${testResults.metrics.annualized_return}%`}
                  positive={testResults.metrics.annualized_return > 0}
                />
                <ResultRow
                  label="Sharpe Ratio"
                  value={testResults.metrics.sharpe_ratio.toString()}
                  positive={testResults.metrics.sharpe_ratio > 1}
                />
                <ResultRow
                  label="Sortino Ratio"
                  value={testResults.metrics.sortino_ratio.toString()}
                  positive={testResults.metrics.sortino_ratio > 1}
                />
                <ResultRow
                  label="Max Drawdown"
                  value={`${testResults.metrics.max_drawdown}%`}
                  positive={testResults.metrics.max_drawdown > -15}
                />
                <ResultRow
                  label="Win Rate"
                  value={`${testResults.metrics.win_rate}%`}
                  positive={testResults.metrics.win_rate > 50}
                />
                <ResultRow
                  label="Profit Factor"
                  value={testResults.metrics.profit_factor.toString()}
                  positive={testResults.metrics.profit_factor > 1}
                />

                <div className="pt-3 border-t border-gray-100 space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">Total Trades</span>
                    <span className="font-medium">{testResults.trade_stats.total_trades}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">Winning / Losing</span>
                    <span className="font-medium">
                      <span className="text-green-600">{testResults.trade_stats.winning_trades}</span>
                      {" / "}
                      <span className="text-red-600">{testResults.trade_stats.losing_trades}</span>
                    </span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">Avg Holding</span>
                    <span className="font-medium">{testResults.trade_stats.avg_holding_days} days</span>
                  </div>
                </div>

                <div className="pt-3 border-t border-gray-100">
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">vs Buy & Hold</span>
                    <span className={cn(
                      "font-medium",
                      testResults.benchmark.alpha > 0 ? "text-green-600" : "text-red-600"
                    )}>
                      Alpha: {testResults.benchmark.alpha > 0 ? "+" : ""}{testResults.benchmark.alpha}%
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {testResults?.error && (
            <div className="bg-red-50 rounded-2xl border border-red-200 p-6">
              <div className="flex items-center gap-3 text-red-700">
                <AlertCircle className="w-5 h-5" />
                <p className="text-sm font-medium">{testResults.message}</p>
              </div>
            </div>
          )}

          {/* Quick Tips */}
          <div className="bg-gradient-to-br from-gray-900 to-gray-800 rounded-2xl p-6 text-white">
            <h3 className="font-semibold mb-3">Backtesting Tips</h3>
            <ul className="text-sm text-gray-300 space-y-2">
              <li className="flex items-start gap-2">
                <span className="text-green-400">•</span>
                Sharpe &gt; 1.0 is good, &gt; 2.0 is excellent
              </li>
              <li className="flex items-start gap-2">
                <span className="text-green-400">•</span>
                Win rate matters less than risk/reward ratio
              </li>
              <li className="flex items-start gap-2">
                <span className="text-green-400">•</span>
                Alpha &gt; 0 means beating buy-and-hold
              </li>
              <li className="flex items-start gap-2">
                <span className="text-yellow-400">•</span>
                Expect 30-50% worse performance in live trading
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

// Section Header Component
function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-6">
      <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
      <p className="text-sm text-gray-500">{description}</p>
    </div>
  );
}

// Config Input Component
function ConfigInput({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  suffix,
  hint,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
  hint?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">{label}</label>
      <div className="relative">
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value) || min)}
          min={min}
          max={max}
          step={step}
          className="w-full px-3 py-2 rounded-lg border border-gray-200 bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
        />
        {suffix && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-gray-400">
            {suffix}
          </span>
        )}
      </div>
      {hint && <p className="text-xs text-gray-400 mt-1">{hint}</p>}
    </div>
  );
}

// Result Row Component
function ResultRow({
  label,
  value,
  positive,
}: {
  label: string;
  value: string;
  positive: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-gray-600">{label}</span>
      <span className={cn(
        "text-sm font-semibold flex items-center gap-1",
        positive ? "text-green-600" : "text-red-600"
      )}>
        {positive ? (
          <ArrowUpRight className="w-3 h-3" />
        ) : (
          <ArrowDownRight className="w-3 h-3" />
        )}
        {value}
      </span>
    </div>
  );
}
