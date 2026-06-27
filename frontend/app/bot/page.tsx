"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Play,
  Square,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Activity,
  DollarSign,
  Target,
  Zap,
  Settings,
  Sparkles,
  Shield,
  Layers,
  Globe,
  Bitcoin,
  BarChart3,
  Gauge,
  Eye,
  FileText,
  Clock,
  Brain,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface MasterBotStatus {
  is_running: boolean;
  mode: string;
  market_regime: string;
  vix_level: number;
  initial_capital: number;
  cash: number;
  total_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  positions: { options: number; crypto: number; total: number };
  allocations: Record<string, number>;
  last_scan: string | null;
  opportunities_count: number;
  risk_summary: {
    risk_mode: string;
    portfolio_delta: number;
    portfolio_theta: number;
    portfolio_vega: number;
    delta_utilization: number;
    vega_utilization: number;
    buying_power_used_pct: number;
  };
  ml_metrics?: {
    rl_training_steps: number;
    dqn_epsilon: number;
    episode_reward: number;
    total_episodes: number;
    hmm_fitted: boolean;
    garch_fitted: boolean;
  };
  training_status?: {
    models_trained: boolean;
    meets_requirements: boolean;
    status_message: string;
    epochs_completed: number;
    total_samples: number;
    checkpoint_exists: boolean;
  };
  live_trading_enabled?: boolean;
  broker_connected?: boolean;
}

interface TrainingStatus {
  models_trained: boolean;
  meets_requirements: boolean;
  status_message: string;
  training_metrics: {
    epochs_completed: number;
    total_samples: number;
    training_loss: number[];
    prediction_accuracy: number[];
  };
  checkpoint_exists: boolean;
  dqn_epsilon: number;
  is_pretrained_loaded: boolean;
}

interface BrokerStatus {
  alpaca: { configured: boolean; connected: boolean; mode: string };
  binance: { configured: boolean; connected: boolean; mode: string };
  is_live_trading: boolean;
}

interface Opportunity {
  symbol: string;
  asset_class: string;
  strategy: string;
  expected_return: number;
  max_profit: number;
  max_loss: number;
  probability_of_profit: number;
  risk_reward_ratio: number;
  iv_rank: number;
  score: number;
  rationale: string;
}

interface OptionsPosition {
  id: string;
  symbol: string;
  strategy_name: string;
  entry_time: string;
  entry_iv: number;
  current_pnl: number;
  max_profit: number;
  max_loss: number;
  greeks: { delta: number; theta: number; vega: number };
}

interface CryptoPosition {
  id: string;
  symbol: string;
  derivative_type: string;
  side: string;
  entry_price: number;
  size: number;
  leverage: number;
  current_price: number;
  unrealized_pnl: number;
  greeks: { delta: number; iv: number };
}

interface CommentaryEntry {
  timestamp: string;
  message: string;
  category: string;
}

interface TradeLogEntry {
  id: string;
  timestamp: string;
  symbol: string;
  asset_class: string;
  type: string;
  strategy: string;
  side: string;
  price: number;
  entry_price: number;
  size: number;
  status: string;
  exit_price: number | null;
  exit_timestamp: string | null;
  close_reason: string | null;
  realized_pnl: number | null;
  realized_pnl_pct: number | null;
  duration_minutes: number | null;
  score: number;
  ml_confidence: number;
  iv_rank: number;
  regime: string;
  rationale: string;
  live_executed: boolean;
  llm_summary: string;
}

// Small reusable components
function RiskBar({ value, max = 100, color = "bg-primary" }: { value: number; max?: number; color?: string }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="h-1.5 rounded-full bg-muted overflow-hidden">
      <div className={cn("h-full rounded-full transition-all duration-700", color)} style={{ width: `${pct}%` }} />
    </div>
  );
}

function EmptyState({ icon: Icon, title, subtitle }: { icon: any; title: string; subtitle: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-center">
      <div className="w-12 h-12 rounded-2xl bg-muted flex items-center justify-center mb-3">
        <Icon className="w-6 h-6 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium text-foreground mb-1">{title}</p>
      <p className="text-xs text-muted-foreground max-w-[220px]">{subtitle}</p>
    </div>
  );
}

export default function MasterQuantBotPage() {
  const [status, setStatus] = useState<MasterBotStatus | null>(null);
  const [brokerStatus, setBrokerStatus] = useState<BrokerStatus | null>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [optionsPositions, setOptionsPositions] = useState<OptionsPosition[]>([]);
  const [cryptoPositions, setCryptoPositions] = useState<CryptoPosition[]>([]);
  const [commentary, setCommentary] = useState<CommentaryEntry[]>([]);
  const [tradeLog, setTradeLog] = useState<TradeLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [trainingStatus, setTrainingStatus] = useState<TrainingStatus | null>(null);
  const [isTraining, setIsTraining] = useState(false);
  const [trainingProgress, setTrainingProgress] = useState("");
  const [capital, setCapital] = useState("100000");
  const [mode, setMode] = useState("balanced");

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, oppsRes, posRes, commentaryRes, brokerRes, tradeLogRes, trainingRes] = await Promise.all([
        fetch(`${API_BASE}/api/master-bot/status`),
        fetch(`${API_BASE}/api/master-bot/opportunities?limit=10`),
        fetch(`${API_BASE}/api/master-bot/positions`),
        fetch(`${API_BASE}/api/master-bot/commentary?limit=20`),
        fetch(`${API_BASE}/api/broker/status`),
        fetch(`${API_BASE}/api/master-bot/trade-log?limit=20`),
        fetch(`${API_BASE}/api/master-bot/training-status`),
      ]);

      if (statusRes.ok) setStatus(await statusRes.json());
      if (oppsRes.ok) { const d = await oppsRes.json(); setOpportunities(d.opportunities || []); }
      if (posRes.ok) { const d = await posRes.json(); setOptionsPositions(d.options_positions || []); setCryptoPositions(d.crypto_positions || []); }
      if (commentaryRes.ok) { const d = await commentaryRes.json(); setCommentary(d.commentary || []); }
      if (brokerRes.ok) setBrokerStatus(await brokerRes.json());
      if (tradeLogRes.ok) { const d = await tradeLogRes.json(); setTradeLog(d.trades || []); }
      if (trainingRes.ok) setTrainingStatus(await trainingRes.json());
    } catch (err) {
      console.error("Failed to fetch bot data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const startBot = async () => {
    setStarting(true);
    try {
      const res = await fetch(`${API_BASE}/api/master-bot/start?capital=${capital}&mode=${mode}`, { method: "POST" });
      if (res.ok) await fetchData();
    } catch (err) { console.error("Failed to start bot:", err); }
    finally { setStarting(false); }
  };

  const stopBot = async () => {
    try { await fetch(`${API_BASE}/api/master-bot/stop`, { method: "POST" }); await fetchData(); }
    catch (err) { console.error("Failed to stop bot:", err); }
  };

  const startTraining = async () => {
    if (status?.is_running) { alert("Stop the bot before training"); return; }
    setIsTraining(true);
    setTrainingProgress("Starting training pipeline...");
    try {
      const res = await fetch(`${API_BASE}/api/master-bot/train?days_of_data=180&training_epochs=40`, { method: "POST" });
      if (res.ok) {
        const result = await res.json();
        setTrainingProgress(result.status === "success" ? "Training complete! Models are ready." : `Training incomplete: ${result.message}`);
        await fetchData();
      } else { setTrainingProgress("Training failed - check server logs"); }
    } catch { setTrainingProgress("Training error - check connection"); }
    finally { setIsTraining(false); }
  };

  const downloadData = async () => {
    setTrainingProgress("Downloading historical data...");
    try {
      const res = await fetch(`${API_BASE}/api/master-bot/download-data?days=365`, { method: "POST" });
      if (res.ok) { const r = await res.json(); setTrainingProgress(`Downloaded ${r.total_candles} candles for ${r.total_symbols} symbols`); }
    } catch { setTrainingProgress("Download failed"); }
  };

  const runBacktest = async () => {
    setTrainingProgress("Running backtest...");
    try {
      const res = await fetch(`${API_BASE}/api/master-bot/backtest?days=90`, { method: "POST" });
      if (res.ok) {
        const r = await res.json();
        if (r.error) { setTrainingProgress(`Backtest error: ${r.error}`); }
        else { setTrainingProgress(`Backtest: ${r.total_return_pct?.toFixed(1)}% return, Sharpe: ${r.sharpe_ratio?.toFixed(2)}, Win Rate: ${r.win_rate?.toFixed(1)}%`); }
      }
    } catch { setTrainingProgress("Backtest failed"); }
  };

  const triggerScan = async () => {
    try { await fetch(`${API_BASE}/api/master-bot/scan`, { method: "POST" }); await fetchData(); }
    catch (err) { console.error("Failed to trigger scan:", err); }
  };

  const getAssetClassColor = (ac: string) => {
    const map: Record<string, string> = {
      stock_options: "bg-blue-500/10 text-blue-400",
      etf_options: "bg-purple-500/10 text-purple-400",
      commodity_options: "bg-amber-500/10 text-amber-400",
      crypto_perpetual: "bg-orange-500/10 text-orange-400",
      crypto_options: "bg-yellow-500/10 text-yellow-400",
      crypto_spot: "bg-emerald-500/10 text-emerald-400",
    };
    return map[ac] || "bg-muted text-muted-foreground";
  };

  const getRegimeStyle = (regime: string) => {
    const map: Record<string, string> = {
      high_volatility: "bg-red-500/10 border-red-500/20 text-red-400",
      low_volatility: "bg-green-500/10 border-green-500/20 text-green-400",
    };
    return map[regime] || "bg-amber-500/10 border-amber-500/20 text-amber-400";
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="w-6 h-6 text-primary animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen p-6 lg:p-8 space-y-5">
      {/* Broker Status Banner */}
      {brokerStatus && (
        <div className="glass-card px-4 py-3 flex items-center justify-between fade-in">
          <div className="flex items-center gap-4">
            <span className="text-xs text-muted-foreground font-medium">Data Feeds:</span>
            <div className="flex items-center gap-3">
              {[
                { name: "Alpaca", connected: brokerStatus.alpaca?.connected },
                { name: "Binance", connected: brokerStatus.binance?.connected },
              ].map((b) => (
                <div key={b.name} className="flex items-center gap-1.5">
                  <div className={cn("status-dot", b.connected ? "live" : "offline")} />
                  <span className={cn("text-xs font-medium", b.connected ? "text-green-500" : "text-muted-foreground")}>
                    {b.name}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <span className="text-[10px] text-muted-foreground">
            {brokerStatus.alpaca?.connected || brokerStatus.binance?.connected ? "Live market data" : "Simulated data"}
          </span>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between fade-in">
        <div>
          <h1 className="text-2xl font-bold text-foreground tracking-tight flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-primary" />
            Quant Bot
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">Autonomous trading across stocks, options, and crypto</p>
        </div>
        <div className="flex items-center gap-2">
          {status?.is_running && (
            <button onClick={triggerScan}
              className="px-3 py-2 rounded-xl glass-card hover:border-primary/30 text-xs font-medium text-muted-foreground hover:text-foreground flex items-center gap-1.5 transition-colors">
              <Eye className="w-3.5 h-3.5 text-primary" />
              Scan Markets
            </button>
          )}
          <button onClick={fetchData} className="p-2 rounded-xl glass-card hover:border-primary/30 text-muted-foreground hover:text-foreground transition-colors">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Market Regime Banner */}
      {status?.is_running && (
        <div className={cn("rounded-xl border p-3 flex items-center justify-between fade-in", getRegimeStyle(status.market_regime))}>
          <div className="flex items-center gap-2">
            <Gauge className="w-4 h-4" />
            <span className="text-sm font-semibold capitalize">{status.market_regime.replace("_", " ")} Market</span>
            <span className="text-xs opacity-70">VIX: {status.vix_level}</span>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <span>{status.opportunities_count} opportunities</span>
            <span className="opacity-40">·</span>
            <span className="capitalize">{status.mode} mode</span>
          </div>
        </div>
      )}

      {/* Control Panel (when bot not running) */}
      {!status?.is_running && (
        <div className="glass-card p-6 space-y-6 fade-in">
          <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
            <Settings className="w-4 h-4 text-primary" />
            Start Trading Bot
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-muted-foreground font-medium mb-2">Initial Capital</label>
              <div className="relative">
                <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <input type="number" value={capital} onChange={(e) => setCapital(e.target.value)}
                  className="w-full pl-9 pr-4 py-2.5 bg-muted/50 border border-border rounded-xl text-foreground focus:ring-2 focus:ring-primary/20 focus:border-primary/40 focus:outline-none text-sm" />
              </div>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground font-medium mb-2">Trading Mode</label>
              <select value={mode} onChange={(e) => setMode(e.target.value)}
                className="w-full px-4 py-2.5 bg-muted/50 border border-border rounded-xl text-foreground focus:ring-2 focus:ring-primary/20 focus:border-primary/40 focus:outline-none text-sm appearance-none">
                <option value="aggressive">Aggressive (Max ROI)</option>
                <option value="balanced">Balanced</option>
                <option value="conservative">Conservative</option>
              </select>
            </div>
            <div className="flex items-end">
              <button onClick={startBot} disabled={starting}
                className="w-full py-2.5 px-4 bg-primary rounded-xl font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 text-sm transition-opacity">
                {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                Start Trading
              </button>
            </div>
          </div>

          <div className="p-3 bg-primary/5 border border-primary/10 rounded-xl">
            <div className="flex items-center gap-2 text-primary text-xs mb-1">
              <Shield className="w-3.5 h-3.5" />
              <span className="font-semibold">Paper Trading Mode</span>
            </div>
            <p className="text-[11px] text-muted-foreground">
              {brokerStatus?.alpaca?.connected || brokerStatus?.binance?.connected
                ? "Using LIVE market data with simulated trades. No real money at risk."
                : "Using simulated data. Connect Alpaca/Binance for live prices."}
            </p>
          </div>

          {/* ML Training Section */}
          <div className="border-t border-border/60 pt-5">
            <h3 className="text-base font-semibold text-foreground mb-4 flex items-center gap-2">
              <Brain className="w-4 h-4 text-purple-500" />
              ML Model Training
              <span className={cn(
                "ml-2 px-2 py-0.5 text-[10px] font-bold rounded-md",
                trainingStatus?.models_trained ? "bg-green-500/10 text-green-500" : "bg-amber-500/10 text-amber-500"
              )}>
                {trainingStatus?.models_trained ? "TRAINED" : "UNTRAINED"}
              </span>
            </h3>

            {/* Training Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 stagger-children">
              {[
                { l: "Status", v: trainingStatus?.status_message || "Not trained", c: trainingStatus?.meets_requirements ? "text-green-500" : "text-amber-500" },
                { l: "Epochs", v: `${trainingStatus?.training_metrics?.epochs_completed || 0} / 100`, c: "text-foreground" },
                { l: "Samples", v: (trainingStatus?.training_metrics?.total_samples || 0).toLocaleString(), c: "text-foreground" },
                { l: "DQN Epsilon", v: trainingStatus?.dqn_epsilon?.toFixed(4) || "1.0000", c: "text-foreground" },
              ].map((s) => (
                <div key={s.l} className="p-3 bg-muted/30 rounded-xl border border-border/40">
                  <div className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">{s.l}</div>
                  <div className={cn("text-sm font-semibold mt-0.5 tabular-nums", s.c)}>{s.v}</div>
                </div>
              ))}
            </div>

            {/* Training Actions */}
            <div className="flex flex-wrap gap-2">
              <button onClick={downloadData} disabled={isTraining}
                className="px-3 py-2 bg-muted hover:bg-muted/80 rounded-lg text-xs font-medium text-foreground disabled:opacity-50 flex items-center gap-1.5 transition-colors border border-border">
                <RefreshCw className="w-3.5 h-3.5" /> Download Data
              </button>
              <button onClick={startTraining} disabled={isTraining || status?.is_running}
                className="px-3 py-2 bg-purple-500/10 hover:bg-purple-500/20 rounded-lg text-xs font-semibold text-purple-400 disabled:opacity-50 flex items-center gap-1.5 transition-colors border border-purple-500/20">
                {isTraining ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Brain className="w-3.5 h-3.5" />}
                {isTraining ? "Training..." : "Train Models"}
              </button>
              <button onClick={runBacktest} disabled={isTraining}
                className="px-3 py-2 bg-muted hover:bg-muted/80 rounded-lg text-xs font-medium text-foreground disabled:opacity-50 flex items-center gap-1.5 transition-colors border border-border">
                <BarChart3 className="w-3.5 h-3.5" /> Run Backtest
              </button>
            </div>

            {/* Training Progress */}
            {trainingProgress && (
              <div className="mt-3 p-3 bg-purple-500/5 border border-purple-500/10 rounded-xl text-xs text-purple-400 flex items-center gap-2">
                {isTraining && <Loader2 className="w-3 h-3 animate-spin flex-shrink-0" />}
                {trainingProgress}
              </div>
            )}

            {!trainingStatus?.models_trained && (
              <div className="mt-3 p-3 bg-amber-500/5 border border-amber-500/10 rounded-xl">
                <div className="flex items-center gap-2 text-amber-400 text-xs">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span className="font-semibold">Training Recommended</span>
                </div>
                <p className="text-[11px] text-muted-foreground mt-1">
                  Models are untrained. Trading will be paused until you train on historical data.
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Running Status */}
      {status?.is_running && (
        <>
          {/* Portfolio Stats */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 stagger-children">
            {[
              { l: "Portfolio Value", v: `$${status.total_value?.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, c: "text-foreground" },
              { l: "Total P&L", v: `${status.total_pnl >= 0 ? "+" : ""}$${status.total_pnl?.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, c: status.total_pnl >= 0 ? "text-green-500" : "text-red-500", sub: `${status.total_pnl_pct >= 0 ? "+" : ""}${status.total_pnl_pct?.toFixed(2)}%` },
              { l: "Options", v: String(status.positions?.options || 0), c: "text-blue-400" },
              { l: "Crypto", v: String(status.positions?.crypto || 0), c: "text-orange-400" },
              { l: "Cash", v: `$${status.cash?.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, c: "text-foreground" },
            ].map((s) => (
              <div key={s.l} className="glass-card p-4">
                <div className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">{s.l}</div>
                <div className={cn("text-xl font-bold mt-1 tabular-nums", s.c)}>{s.v}</div>
                {"sub" in s && s.sub && <div className={cn("text-xs font-semibold mt-0.5 tabular-nums", s.c)}>{s.sub}</div>}
              </div>
            ))}
          </div>

          {/* Risk / Greeks */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 stagger-children">
            {[
              { l: "Portfolio Delta", v: status.risk_summary?.portfolio_delta?.toFixed(1) || "0", pct: status.risk_summary?.delta_utilization || 0, color: "bg-blue-500" },
              { l: "Portfolio Theta", v: `${status.risk_summary?.portfolio_theta?.toFixed(1) || "0"}/day`, pct: 50, color: (status.risk_summary?.portfolio_theta || 0) > 0 ? "bg-green-500" : "bg-red-500" },
              { l: "Portfolio Vega", v: status.risk_summary?.portfolio_vega?.toFixed(1) || "0", pct: status.risk_summary?.vega_utilization || 0, color: "bg-purple-500" },
              { l: "Buying Power Used", v: `${status.risk_summary?.buying_power_used_pct?.toFixed(1) || "0"}%`, pct: status.risk_summary?.buying_power_used_pct || 0, color: "bg-amber-500" },
            ].map((g) => (
              <div key={g.l} className="glass-card p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">{g.l}</span>
                  <span className="text-sm font-bold text-foreground tabular-nums">{g.v}</span>
                </div>
                <RiskBar value={g.pct} color={g.color} />
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Opportunities */}
            <div className="glass-card overflow-hidden">
              <div className="px-5 py-3 border-b border-border/60 flex items-center gap-2">
                <Target className="w-4 h-4 text-primary" />
                <span className="text-sm font-semibold text-foreground">Top Opportunities</span>
              </div>
              <div className="max-h-[400px] overflow-y-auto">
                {opportunities.length === 0 ? (
                  <EmptyState icon={Eye} title="Scanning..." subtitle="Looking for opportunities across all markets" />
                ) : (
                  opportunities.map((opp, i) => (
                    <div key={i} className="px-5 py-3 border-b border-border/20 hover:bg-muted/20 transition-colors">
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-2">
                          <span className={cn("px-1.5 py-0.5 rounded-md text-[10px] font-semibold", getAssetClassColor(opp.asset_class))}>
                            {opp.asset_class.replace("_", " ")}
                          </span>
                          <span className="font-bold text-sm text-foreground">{opp.symbol}</span>
                        </div>
                        <span className="text-xs font-bold text-primary tabular-nums">Score: {opp.score.toFixed(0)}</span>
                      </div>
                      <div className="text-xs text-muted-foreground mb-1.5">{opp.strategy}</div>
                      <div className="grid grid-cols-3 gap-2 text-[10px]">
                        <div><span className="text-muted-foreground">Return</span><div className="text-green-500 font-semibold">{opp.expected_return.toFixed(0)}%</div></div>
                        <div><span className="text-muted-foreground">P(Profit)</span><div className="text-foreground font-semibold">{opp.probability_of_profit.toFixed(0)}%</div></div>
                        <div><span className="text-muted-foreground">IV Rank</span><div className="text-amber-400 font-semibold">{opp.iv_rank.toFixed(0)}%</div></div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Bot Activity */}
            <div className="glass-card overflow-hidden">
              <div className="px-5 py-3 border-b border-border/60 flex items-center gap-2">
                <Activity className="w-4 h-4 text-primary" />
                <span className="text-sm font-semibold text-foreground">Bot Activity</span>
              </div>
              <div className="max-h-[400px] overflow-y-auto">
                {commentary.length === 0 ? (
                  <EmptyState icon={Activity} title="Waiting..." subtitle="Activity will appear as the bot trades" />
                ) : (
                  [...commentary].reverse().map((entry, i) => {
                    const catColors: Record<string, string> = {
                      trade: "border-green-500 bg-green-500/5",
                      risk: "border-red-500 bg-red-500/5",
                      scan: "border-blue-500 bg-blue-500/5",
                      analysis: "border-purple-500 bg-purple-500/5",
                    };
                    return (
                      <div key={i} className={cn("px-5 py-2.5 border-b border-border/20 border-l-2", catColors[entry.category] || "border-muted bg-muted/5")}>
                        <p className="text-xs text-foreground/80">{entry.message}</p>
                        <p className="text-[10px] text-muted-foreground mt-0.5 font-mono tabular-nums">
                          {new Date(entry.timestamp).toLocaleTimeString()}
                        </p>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>

          {/* Positions */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Options */}
            <div className="glass-card overflow-hidden">
              <div className="px-5 py-3 border-b border-border/60 flex items-center gap-2">
                <Layers className="w-4 h-4 text-blue-400" />
                <span className="text-sm font-semibold text-foreground">Options ({optionsPositions.length})</span>
              </div>
              <div className="max-h-[300px] overflow-y-auto">
                {optionsPositions.length === 0 ? (
                  <div className="py-8 text-center text-xs text-muted-foreground">No options positions</div>
                ) : (
                  optionsPositions.map((pos) => (
                    <div key={pos.id} className="px-5 py-3 border-b border-border/20 hover:bg-muted/20 transition-colors">
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-bold text-sm text-foreground">{pos.symbol}</span>
                        <span className={cn("font-bold text-sm tabular-nums", pos.current_pnl >= 0 ? "text-green-500" : "text-red-500")}>
                          {pos.current_pnl >= 0 ? "+" : ""}${pos.current_pnl?.toFixed(0)}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground">{pos.strategy_name}</div>
                      <div className="flex items-center gap-3 mt-1.5 text-[10px] text-muted-foreground font-mono tabular-nums">
                        <span>Δ {pos.greeks?.delta?.toFixed(2)}</span>
                        <span>Θ {pos.greeks?.theta?.toFixed(2)}</span>
                        <span>IV: {pos.entry_iv}%</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Crypto */}
            <div className="glass-card overflow-hidden">
              <div className="px-5 py-3 border-b border-border/60 flex items-center gap-2">
                <Bitcoin className="w-4 h-4 text-orange-400" />
                <span className="text-sm font-semibold text-foreground">Crypto ({cryptoPositions.length})</span>
              </div>
              <div className="max-h-[300px] overflow-y-auto">
                {cryptoPositions.length === 0 ? (
                  <div className="py-8 text-center text-xs text-muted-foreground">No crypto positions</div>
                ) : (
                  cryptoPositions.map((pos) => (
                    <div key={pos.id} className="px-5 py-3 border-b border-border/20 hover:bg-muted/20 transition-colors">
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-sm text-foreground">{pos.symbol}</span>
                          <span className={cn("text-[10px] px-1.5 py-0.5 rounded-md font-semibold",
                            pos.side === "long" ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"
                          )}>{pos.side.toUpperCase()}</span>
                        </div>
                        <span className={cn("font-bold text-sm tabular-nums", pos.unrealized_pnl >= 0 ? "text-green-500" : "text-red-500")}>
                          {pos.unrealized_pnl >= 0 ? "+" : ""}${pos.unrealized_pnl?.toFixed(2)}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground">{pos.derivative_type}</div>
                      <div className="flex items-center gap-3 mt-1.5 text-[10px] text-muted-foreground font-mono tabular-nums">
                        <span>Size: ${pos.size?.toLocaleString()}</span>
                        <span>{pos.leverage}x</span>
                        <span>Entry: ${pos.entry_price?.toLocaleString()}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* Trade Log */}
          <div className="glass-card overflow-hidden">
            <div className="px-5 py-3 border-b border-border/60 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-primary" />
                <span className="text-sm font-semibold text-foreground">Trade Log</span>
                <span className="text-[10px] font-bold text-muted-foreground tabular-nums px-1.5 py-0.5 bg-muted rounded-md">{tradeLog.length}</span>
              </div>
              <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                <Brain className="w-3 h-3" /> AI Rationale
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-muted/30">
                  <tr>
                    {["Time", "Asset", "Strategy", "Side", "Entry", "Size", "P&L", "Score", "AI Rationale"].map((h) => (
                      <th key={h} className="text-left text-[10px] font-semibold text-muted-foreground uppercase tracking-wider py-2.5 px-4">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {tradeLog.length === 0 ? (
                    <tr><td colSpan={9} className="py-10 text-center text-xs text-muted-foreground">No trades recorded yet</td></tr>
                  ) : (
                    tradeLog.map((trade) => (
                      <tr key={trade.id} className="border-b border-border/20 hover:bg-muted/20 transition-colors">
                        <td className="py-3 px-4">
                          <div className="text-foreground/80 font-mono tabular-nums flex items-center gap-1">
                            <Clock className="w-2.5 h-2.5 text-muted-foreground" />
                            {new Date(trade.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                          </div>
                          <div className="text-[10px] text-muted-foreground">{new Date(trade.timestamp).toLocaleDateString()}</div>
                        </td>
                        <td className="py-3 px-4">
                          <div className="font-semibold text-foreground">{trade.symbol}</div>
                          <span className={cn("text-[10px] px-1 py-0.5 rounded", getAssetClassColor(trade.asset_class))}>
                            {trade.asset_class.replace(/_/g, " ")}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <div className="text-foreground">{trade.strategy}</div>
                          <div className="text-[10px] text-muted-foreground">IV: {trade.iv_rank?.toFixed(0)}%</div>
                        </td>
                        <td className="py-3 px-4">
                          <span className={cn("px-1.5 py-0.5 rounded-md text-[10px] font-semibold",
                            trade.side === "long" ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"
                          )}>{trade.side?.toUpperCase()}</span>
                        </td>
                        <td className="py-3 px-4 font-mono text-foreground tabular-nums">
                          ${(trade.entry_price || trade.price)?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          {trade.exit_price && <div className="text-[10px] text-muted-foreground">Exit: ${trade.exit_price?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>}
                        </td>
                        <td className="py-3 px-4 font-mono text-foreground tabular-nums">
                          ${trade.size?.toLocaleString()}
                          {trade.live_executed && <div className="text-[10px] text-green-500 font-semibold">LIVE</div>}
                        </td>
                        <td className="py-3 px-4">
                          {trade.status === "closed" && trade.realized_pnl !== null ? (
                            <div>
                              <div className={cn("font-mono font-semibold tabular-nums", trade.realized_pnl >= 0 ? "text-green-500" : "text-red-500")}>
                                {trade.realized_pnl >= 0 ? "+" : ""}${trade.realized_pnl?.toFixed(2)}
                              </div>
                              <div className={cn("text-[10px] tabular-nums", trade.realized_pnl >= 0 ? "text-green-500/70" : "text-red-500/70")}>
                                {(trade.realized_pnl_pct ?? 0) >= 0 ? "+" : ""}{trade.realized_pnl_pct?.toFixed(1)}%
                              </div>
                              {trade.close_reason && <div className="text-[10px] text-muted-foreground">{trade.close_reason}</div>}
                            </div>
                          ) : (
                            <span className="px-1.5 py-0.5 bg-primary/10 text-primary rounded-md text-[10px] font-semibold">OPEN</span>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          <div className={cn("font-semibold tabular-nums",
                            trade.score >= 50 ? "text-green-500" : trade.score >= 30 ? "text-amber-400" : "text-muted-foreground"
                          )}>{trade.score?.toFixed(1)}</div>
                          <div className="text-[10px] text-muted-foreground">{(trade.ml_confidence * 100)?.toFixed(0)}% conf</div>
                        </td>
                        <td className="py-3 px-4 max-w-[280px]">
                          <p className="text-xs text-foreground/80 leading-relaxed line-clamp-2">{trade.llm_summary || trade.rationale || "Generating..."}</p>
                          <div className="text-[10px] text-muted-foreground mt-0.5">
                            Regime: {trade.regime}
                            {trade.duration_minutes && ` · ${trade.duration_minutes?.toFixed(0)}min`}
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Stop Button */}
          <div className="flex justify-center">
            <button onClick={stopBot}
              className="px-8 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-500 hover:bg-red-500/20 transition-colors flex items-center gap-2 font-semibold text-sm">
              <Square className="w-4 h-4" />
              Stop Bot
            </button>
          </div>
        </>
      )}
    </div>
  );
}
