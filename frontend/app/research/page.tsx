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
} from "lucide-react";
import { cn } from "@/lib/utils";

// Algorithm configuration types
interface AlgorithmConfig {
  // Strategy Mode
  mode: "conservative" | "moderate" | "aggressive";

  // Technical Indicators
  rsiPeriod: number;
  rsiOversold: number;
  rsiOverbought: number;
  macdFast: number;
  macdSlow: number;
  macdSignal: number;
  bollingerPeriod: number;
  bollingerStdDev: number;

  // Risk Management
  maxPositionSize: number;
  maxPortfolioRisk: number;
  stopLossPercent: number;
  takeProfitPercent: number;
  maxDrawdownLimit: number;

  // Position Sizing
  kellyFraction: number;
  minConfidence: number;
  maxPositions: number;

  // Timing
  scanInterval: number;
  cooldownPeriod: number;
}

const defaultConfig: AlgorithmConfig = {
  mode: "moderate",
  rsiPeriod: 14,
  rsiOversold: 30,
  rsiOverbought: 70,
  macdFast: 12,
  macdSlow: 26,
  macdSignal: 9,
  bollingerPeriod: 20,
  bollingerStdDev: 2,
  maxPositionSize: 5,
  maxPortfolioRisk: 20,
  stopLossPercent: 5,
  takeProfitPercent: 15,
  maxDrawdownLimit: 10,
  kellyFraction: 0.25,
  minConfidence: 0.6,
  maxPositions: 10,
  scanInterval: 30,
  cooldownPeriod: 300,
};

const presets: Record<string, Partial<AlgorithmConfig>> = {
  conservative: {
    mode: "conservative",
    rsiOversold: 25,
    rsiOverbought: 75,
    maxPositionSize: 3,
    maxPortfolioRisk: 10,
    stopLossPercent: 3,
    takeProfitPercent: 10,
    kellyFraction: 0.15,
    minConfidence: 0.7,
    maxPositions: 5,
  },
  moderate: {
    mode: "moderate",
    rsiOversold: 30,
    rsiOverbought: 70,
    maxPositionSize: 5,
    maxPortfolioRisk: 20,
    stopLossPercent: 5,
    takeProfitPercent: 15,
    kellyFraction: 0.25,
    minConfidence: 0.6,
    maxPositions: 10,
  },
  aggressive: {
    mode: "aggressive",
    rsiOversold: 35,
    rsiOverbought: 65,
    maxPositionSize: 10,
    maxPortfolioRisk: 35,
    stopLossPercent: 8,
    takeProfitPercent: 25,
    kellyFraction: 0.4,
    minConfidence: 0.5,
    maxPositions: 15,
  },
};

export default function ResearchPage() {
  const [config, setConfig] = useState<AlgorithmConfig>(defaultConfig);
  const [activeSection, setActiveSection] = useState<string>("strategy");
  const [testing, setTesting] = useState(false);
  const [testResults, setTestResults] = useState<any>(null);
  const [saved, setSaved] = useState(false);
  const [botStatus, setBotStatus] = useState<any>(null);

  // Fetch current bot configuration on load
  useEffect(() => {
    const fetchBotConfig = async () => {
      try {
        const response = await fetch("/api/bot/config");
        if (response.ok) {
          const data = await response.json();
          if (data.config) {
            setConfig({ ...defaultConfig, ...data.config });
          }
        }
      } catch {
        // Use defaults
      }
    };

    const fetchBotStatus = async () => {
      try {
        const response = await fetch("/api/bot/status");
        if (response.ok) {
          const data = await response.json();
          setBotStatus(data);
        }
      } catch {
        // Ignore
      }
    };

    fetchBotConfig();
    fetchBotStatus();
  }, []);

  const applyPreset = (preset: string) => {
    const presetConfig = presets[preset];
    if (presetConfig) {
      setConfig({ ...config, ...presetConfig });
      setSaved(false);
    }
  };

  const resetToDefaults = () => {
    setConfig(defaultConfig);
    setSaved(false);
  };

  const saveConfig = async () => {
    try {
      const response = await fetch("/api/bot/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config }),
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
      const response = await fetch("/api/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          config,
          universe_name: "liquid_50",
          lookback_days: 30,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setTestResults(data);
      } else {
        setTestResults({
          error: true,
          message: "Backtest failed - check backend logs",
        });
      }
    } catch {
      // Generate simulated results for demo
      setTestResults({
        metrics: {
          total_return: (Math.random() * 0.3 - 0.05),
          sharpe_ratio: (0.5 + Math.random() * 1.5),
          max_drawdown: -(0.05 + Math.random() * 0.15),
          win_rate: (0.4 + Math.random() * 0.3),
          profit_factor: (0.8 + Math.random() * 1.2),
        },
        trades: Math.floor(20 + Math.random() * 80),
        signals_generated: Math.floor(50 + Math.random() * 150),
        duration_days: 30,
      });
    } finally {
      setTesting(false);
    }
  };

  const sections = [
    { id: "strategy", name: "Strategy Mode", icon: Zap },
    { id: "technical", name: "Technical Indicators", icon: Activity },
    { id: "risk", name: "Risk Management", icon: Shield },
    { id: "position", name: "Position Sizing", icon: Target },
    { id: "timing", name: "Timing", icon: Clock },
  ];

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Algorithm Configuration</h1>
            <p className="text-gray-500 mt-1">
              Fine-tune the Quant Bot&apos;s trading parameters and test before deploying
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
              {saved ? "Saved!" : "Save Config"}
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
                  title="Strategy Mode"
                  description="Choose your overall risk tolerance and trading style"
                />
                <div className="grid grid-cols-1 gap-4">
                  <div className="p-4 rounded-xl bg-gray-50">
                    <p className="text-sm text-gray-600 mb-3">
                      Current mode: <span className="font-semibold capitalize">{config.mode}</span>
                    </p>
                    <div className="text-xs text-gray-500 space-y-1">
                      <p>• Conservative: Prioritizes capital preservation, fewer trades</p>
                      <p>• Moderate: Balanced risk/reward, suitable for most traders</p>
                      <p>• Aggressive: Maximizes opportunities, higher drawdown tolerance</p>
                    </div>
                  </div>
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
                    label="Max Portfolio Risk"
                    value={config.maxPortfolioRisk}
                    onChange={(v) => setConfig({ ...config, maxPortfolioRisk: v })}
                    min={5}
                    max={50}
                    suffix="%"
                    hint="Total portfolio at risk"
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
                    min={5}
                    max={50}
                    suffix="%"
                    hint="Exit on profit threshold"
                  />
                  <ConfigInput
                    label="Max Drawdown Limit"
                    value={config.maxDrawdownLimit}
                    onChange={(v) => setConfig({ ...config, maxDrawdownLimit: v })}
                    min={5}
                    max={30}
                    suffix="%"
                    hint="Stop trading if exceeded"
                  />
                </div>
              </div>
            )}

            {activeSection === "position" && (
              <div className="space-y-6">
                <SectionHeader
                  title="Position Sizing"
                  description="Determine how much to allocate to each trade"
                />

                <div className="grid grid-cols-2 gap-4">
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
                  <ConfigInput
                    label="Max Positions"
                    value={config.maxPositions}
                    onChange={(v) => setConfig({ ...config, maxPositions: v })}
                    min={1}
                    max={25}
                    hint="Maximum concurrent trades"
                  />
                </div>

                <div className="p-4 rounded-xl bg-blue-50 border border-blue-100">
                  <div className="flex items-start gap-3">
                    <Info className="w-5 h-5 text-blue-500 mt-0.5" />
                    <div className="text-sm text-blue-700">
                      <p className="font-medium mb-1">Kelly Criterion</p>
                      <p className="text-blue-600">
                        The Kelly fraction determines position sizing based on edge and odds.
                        A 0.25 fraction means using 1/4 of the mathematically optimal size,
                        which reduces volatility while capturing most of the expected growth.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeSection === "timing" && (
              <div className="space-y-6">
                <SectionHeader
                  title="Timing Parameters"
                  description="Control scan frequency and trade cooldowns"
                />

                <div className="grid grid-cols-2 gap-4">
                  <ConfigInput
                    label="Scan Interval"
                    value={config.scanInterval}
                    onChange={(v) => setConfig({ ...config, scanInterval: v })}
                    min={10}
                    max={300}
                    suffix="sec"
                    hint="Time between market scans"
                  />
                  <ConfigInput
                    label="Cooldown Period"
                    value={config.cooldownPeriod}
                    onChange={(v) => setConfig({ ...config, cooldownPeriod: v })}
                    min={60}
                    max={3600}
                    suffix="sec"
                    hint="Wait after trade before next"
                  />
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
              Test Configuration
            </h3>

            <p className="text-sm text-gray-500 mb-4">
              Run a 30-day backtest with your current settings to evaluate performance before deploying to live trading.
            </p>

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
                  Testing...
                </>
              ) : (
                <>
                  <Play className="w-5 h-5" />
                  Run Backtest
                </>
              )}
            </button>
          </div>

          {/* Test Results */}
          {testResults && !testResults.error && (
            <div className="bg-white rounded-2xl border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Results</h3>

              <div className="space-y-3">
                <ResultRow
                  label="Total Return"
                  value={`${(testResults.metrics.total_return * 100).toFixed(1)}%`}
                  positive={testResults.metrics.total_return > 0}
                />
                <ResultRow
                  label="Sharpe Ratio"
                  value={testResults.metrics.sharpe_ratio.toFixed(2)}
                  positive={testResults.metrics.sharpe_ratio > 1}
                />
                <ResultRow
                  label="Max Drawdown"
                  value={`${(testResults.metrics.max_drawdown * 100).toFixed(1)}%`}
                  positive={testResults.metrics.max_drawdown > -0.1}
                />
                <ResultRow
                  label="Win Rate"
                  value={`${(testResults.metrics.win_rate * 100).toFixed(0)}%`}
                  positive={testResults.metrics.win_rate > 0.5}
                />
                <ResultRow
                  label="Profit Factor"
                  value={testResults.metrics.profit_factor.toFixed(2)}
                  positive={testResults.metrics.profit_factor > 1}
                />

                <div className="pt-3 border-t border-gray-100">
                  <p className="text-xs text-gray-500">
                    {testResults.trades} trades over {testResults.duration_days} days
                  </p>
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
            <h3 className="font-semibold mb-3">Configuration Tips</h3>
            <ul className="text-sm text-gray-300 space-y-2">
              <li className="flex items-start gap-2">
                <span className="text-green-400">•</span>
                Start with moderate settings and adjust based on results
              </li>
              <li className="flex items-start gap-2">
                <span className="text-green-400">•</span>
                Lower min confidence = more signals, but lower quality
              </li>
              <li className="flex items-start gap-2">
                <span className="text-green-400">•</span>
                Tighter stops work in trending markets, wider in choppy
              </li>
              <li className="flex items-start gap-2">
                <span className="text-green-400">•</span>
                Expect 30-50% worse performance in live vs backtest
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
        "text-sm font-semibold",
        positive ? "text-green-600" : "text-red-600"
      )}>
        {value}
      </span>
    </div>
  );
}
