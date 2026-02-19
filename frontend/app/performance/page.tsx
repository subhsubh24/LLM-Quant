"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  BarChart3,
  Zap,
  Shield,
  Globe,
  AlertTriangle,
  CheckCircle,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Market regime types
type MarketRegime = "RISK_ON" | "RISK_OFF" | "NEUTRAL" | "HIGH_VOL";

interface MarketHealth {
  regime: MarketRegime;
  regimeConfidence: number;
  vix: number;
  vixTrend: "rising" | "falling" | "stable";
  fearGreedIndex: number;
  putCallRatio: number;
  advanceDeclineRatio: number;
  newHighsLows: number;
  sectorLeaders: string[];
  sectorLaggards: string[];
  cryptoCorrelation: number;
  bondYield10Y: number;
  yieldCurve: "normal" | "flat" | "inverted";
  liquidityScore: number;
  breadthThrust: boolean;
  marketCap: { large: number; mid: number; small: number };
}

const regimeColors: Record<MarketRegime, { bg: string; text: string; border: string }> = {
  RISK_ON: { bg: "bg-green-50", text: "text-green-700", border: "border-green-200" },
  RISK_OFF: { bg: "bg-red-50", text: "text-red-700", border: "border-red-200" },
  NEUTRAL: { bg: "bg-gray-50", text: "text-gray-700", border: "border-gray-200" },
  HIGH_VOL: { bg: "bg-orange-50", text: "text-orange-700", border: "border-orange-200" },
};

const regimeDescriptions: Record<MarketRegime, string> = {
  RISK_ON: "Favorable conditions for aggressive strategies. Markets trending up with low volatility.",
  RISK_OFF: "Defensive positioning recommended. Risk assets under pressure.",
  NEUTRAL: "Mixed signals. Selective opportunities exist, but caution advised.",
  HIGH_VOL: "Elevated volatility regime. Reduce position sizes, widen stops.",
};

export default function AnalyticsPage() {
  const [marketHealth, setMarketHealth] = useState<MarketHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [usingMockData, setUsingMockData] = useState(false);

  // Fetch market health data
  useEffect(() => {
    const fetchMarketHealth = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/market/health`);
        if (response.ok) {
          const data = await response.json();
          setMarketHealth(data);
          setUsingMockData(false);
        } else {
          // Use intelligent defaults based on typical market conditions
          setMarketHealth(generateMarketHealth());
          setUsingMockData(true);
        }
      } catch {
        setMarketHealth(generateMarketHealth());
        setUsingMockData(true);
      } finally {
        setLoading(false);
        setLastUpdate(new Date());
      }
    };

    fetchMarketHealth();
    const interval = setInterval(fetchMarketHealth, 60000); // Update every minute
    return () => clearInterval(interval);
  }, []);

  // Generate realistic market health data
  function generateMarketHealth(): MarketHealth {
    const vix = 15 + Math.random() * 20;
    const fearGreed = Math.floor(30 + Math.random() * 50);
    const putCall = 0.7 + Math.random() * 0.6;
    const advDec = 0.8 + Math.random() * 0.8;

    let regime: MarketRegime = "NEUTRAL";
    if (vix < 15 && fearGreed > 60) regime = "RISK_ON";
    else if (vix > 25 || fearGreed < 30) regime = "RISK_OFF";
    else if (vix > 20) regime = "HIGH_VOL";

    return {
      regime,
      regimeConfidence: 0.65 + Math.random() * 0.3,
      vix,
      vixTrend: vix > 20 ? "rising" : vix < 15 ? "falling" : "stable",
      fearGreedIndex: fearGreed,
      putCallRatio: putCall,
      advanceDeclineRatio: advDec,
      newHighsLows: Math.floor(-50 + Math.random() * 200),
      sectorLeaders: ["Technology", "Healthcare", "Financials"].slice(0, 2 + Math.floor(Math.random() * 2)),
      sectorLaggards: ["Energy", "Utilities", "Real Estate"].slice(0, 2 + Math.floor(Math.random() * 2)),
      cryptoCorrelation: 0.3 + Math.random() * 0.5,
      bondYield10Y: 4.0 + Math.random() * 1.5,
      yieldCurve: Math.random() > 0.7 ? "inverted" : Math.random() > 0.4 ? "flat" : "normal",
      liquidityScore: 60 + Math.random() * 35,
      breadthThrust: Math.random() > 0.8,
      marketCap: {
        large: -2 + Math.random() * 5,
        mid: -3 + Math.random() * 6,
        small: -4 + Math.random() * 8,
      },
    };
  }

  if (loading || !marketHealth) {
    return (
      <div className="p-8 flex items-center justify-center min-h-screen">
        <div className="text-center">
          <Activity className="w-8 h-8 animate-pulse mx-auto mb-4 text-blue-500" />
          <p className="text-gray-500">Analyzing market conditions...</p>
        </div>
      </div>
    );
  }

  const regime = regimeColors[marketHealth.regime];

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Mock data warning */}
      {usingMockData && (
        <div className="mb-4 p-3 bg-orange-50 border border-orange-200 rounded-xl flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-orange-500 flex-shrink-0" />
          <p className="text-sm text-orange-700">
            Unable to connect to backend API. Showing simulated data for demonstration.
          </p>
        </div>
      )}

      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Market Analytics</h1>
            <p className="text-gray-500 mt-1">
              Real-time market health indicators for informed trading decisions
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs text-gray-400">Last updated</p>
            <p className="text-sm font-medium text-gray-600">
              {lastUpdate.toLocaleTimeString()}
            </p>
          </div>
        </div>
      </div>

      {/* Market Regime Banner */}
      <div className={cn(
        "rounded-2xl p-6 mb-8 border-2",
        regime.bg, regime.border
      )}>
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className={cn(
              "w-16 h-16 rounded-2xl flex items-center justify-center",
              marketHealth.regime === "RISK_ON" ? "bg-green-100" :
              marketHealth.regime === "RISK_OFF" ? "bg-red-100" :
              marketHealth.regime === "HIGH_VOL" ? "bg-orange-100" : "bg-gray-100"
            )}>
              {marketHealth.regime === "RISK_ON" ? <TrendingUp className="w-8 h-8 text-green-600" /> :
               marketHealth.regime === "RISK_OFF" ? <Shield className="w-8 h-8 text-red-600" /> :
               marketHealth.regime === "HIGH_VOL" ? <Zap className="w-8 h-8 text-orange-600" /> :
               <Activity className="w-8 h-8 text-gray-600" />}
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h2 className={cn("text-2xl font-bold", regime.text)}>
                  {marketHealth.regime.replace("_", " ")} REGIME
                </h2>
                <span className={cn(
                  "text-sm px-3 py-1 rounded-full font-medium",
                  regime.bg, regime.text
                )}>
                  {(marketHealth.regimeConfidence * 100).toFixed(0)}% confidence
                </span>
              </div>
              <p className="text-gray-600 mt-1 max-w-xl">
                {regimeDescriptions[marketHealth.regime]}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Key Indicators Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {/* VIX */}
        <IndicatorCard
          title="VIX (Fear Index)"
          value={marketHealth.vix.toFixed(1)}
          status={marketHealth.vix < 15 ? "good" : marketHealth.vix > 25 ? "bad" : "neutral"}
          trend={marketHealth.vixTrend}
          description={
            marketHealth.vix < 15 ? "Low fear - complacency risk" :
            marketHealth.vix > 30 ? "Extreme fear - potential opportunity" :
            marketHealth.vix > 20 ? "Elevated anxiety" : "Normal range"
          }
          icon={<Activity className="w-5 h-5" />}
        />

        {/* Fear & Greed */}
        <IndicatorCard
          title="Fear & Greed Index"
          value={marketHealth.fearGreedIndex.toString()}
          status={marketHealth.fearGreedIndex > 60 ? "good" : marketHealth.fearGreedIndex < 30 ? "bad" : "neutral"}
          description={
            marketHealth.fearGreedIndex > 75 ? "Extreme Greed - caution" :
            marketHealth.fearGreedIndex > 55 ? "Greed" :
            marketHealth.fearGreedIndex > 45 ? "Neutral" :
            marketHealth.fearGreedIndex > 25 ? "Fear" : "Extreme Fear - opportunity"
          }
          icon={<BarChart3 className="w-5 h-5" />}
          suffix="/100"
        />

        {/* Put/Call Ratio */}
        <IndicatorCard
          title="Put/Call Ratio"
          value={marketHealth.putCallRatio.toFixed(2)}
          status={marketHealth.putCallRatio < 0.8 ? "good" : marketHealth.putCallRatio > 1.1 ? "bad" : "neutral"}
          description={
            marketHealth.putCallRatio < 0.7 ? "Bullish sentiment" :
            marketHealth.putCallRatio > 1.2 ? "Bearish sentiment" : "Balanced options flow"
          }
          icon={<TrendingUp className="w-5 h-5" />}
        />

        {/* Advance/Decline */}
        <IndicatorCard
          title="Advance/Decline"
          value={marketHealth.advanceDeclineRatio.toFixed(2)}
          status={marketHealth.advanceDeclineRatio > 1.2 ? "good" : marketHealth.advanceDeclineRatio < 0.8 ? "bad" : "neutral"}
          description={
            marketHealth.advanceDeclineRatio > 1.5 ? "Strong breadth" :
            marketHealth.advanceDeclineRatio < 0.7 ? "Weak breadth" : "Healthy participation"
          }
          icon={<Globe className="w-5 h-5" />}
        />
      </div>

      {/* Two Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Sector Analysis */}
        <div className="bg-white rounded-2xl border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-blue-500" />
            Sector Rotation
          </h3>

          <div className="space-y-4">
            <div>
              <p className="text-sm text-gray-500 mb-2">Leading Sectors</p>
              <div className="flex flex-wrap gap-2">
                {marketHealth.sectorLeaders.map((sector) => (
                  <span key={sector} className="px-3 py-1.5 bg-green-50 text-green-700 rounded-lg text-sm font-medium flex items-center gap-1">
                    <ArrowUpRight className="w-3 h-3" />
                    {sector}
                  </span>
                ))}
              </div>
            </div>

            <div>
              <p className="text-sm text-gray-500 mb-2">Lagging Sectors</p>
              <div className="flex flex-wrap gap-2">
                {marketHealth.sectorLaggards.map((sector) => (
                  <span key={sector} className="px-3 py-1.5 bg-red-50 text-red-700 rounded-lg text-sm font-medium flex items-center gap-1">
                    <ArrowDownRight className="w-3 h-3" />
                    {sector}
                  </span>
                ))}
              </div>
            </div>

            <div className="pt-4 border-t border-gray-100">
              <p className="text-sm text-gray-600">
                <span className="font-medium">Rotation Signal: </span>
                {marketHealth.sectorLeaders.includes("Technology")
                  ? "Growth leadership suggests risk appetite intact"
                  : marketHealth.sectorLeaders.includes("Utilities")
                  ? "Defensive rotation underway - reduce beta"
                  : "Mixed sector signals - maintain balanced exposure"}
              </p>
            </div>
          </div>
        </div>

        {/* Market Cap Performance */}
        <div className="bg-white rounded-2xl border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-purple-500" />
            Market Cap Analysis
          </h3>

          <div className="space-y-4">
            <CapBar label="Large Cap" value={marketHealth.marketCap.large} />
            <CapBar label="Mid Cap" value={marketHealth.marketCap.mid} />
            <CapBar label="Small Cap" value={marketHealth.marketCap.small} />

            <div className="pt-4 border-t border-gray-100">
              <p className="text-sm text-gray-600">
                <span className="font-medium">Size Signal: </span>
                {marketHealth.marketCap.small > marketHealth.marketCap.large
                  ? "Small caps leading - risk appetite strong"
                  : marketHealth.marketCap.large > marketHealth.marketCap.small + 2
                  ? "Flight to quality - large caps preferred"
                  : "Balanced performance across market caps"}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Risk Indicators */}
      <div className="bg-white rounded-2xl border border-gray-200 p-6 mb-8">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Shield className="w-5 h-5 text-red-500" />
          Risk Environment
        </h3>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          {/* Yield Curve */}
          <div>
            <p className="text-sm text-gray-500 mb-1">Yield Curve</p>
            <div className="flex items-center gap-2">
              <span className={cn(
                "text-xl font-bold",
                marketHealth.yieldCurve === "inverted" ? "text-red-600" :
                marketHealth.yieldCurve === "flat" ? "text-orange-600" : "text-green-600"
              )}>
                {marketHealth.yieldCurve.charAt(0).toUpperCase() + marketHealth.yieldCurve.slice(1)}
              </span>
              {marketHealth.yieldCurve === "inverted" && (
                <AlertTriangle className="w-4 h-4 text-red-500" />
              )}
            </div>
            <p className="text-xs text-gray-400 mt-1">
              {marketHealth.yieldCurve === "inverted"
                ? "Recession signal"
                : marketHealth.yieldCurve === "flat"
                ? "Economic uncertainty"
                : "Normal conditions"}
            </p>
          </div>

          {/* 10Y Yield */}
          <div>
            <p className="text-sm text-gray-500 mb-1">10Y Treasury</p>
            <p className="text-xl font-bold text-gray-900">{marketHealth.bondYield10Y.toFixed(2)}%</p>
            <p className="text-xs text-gray-400 mt-1">
              {marketHealth.bondYield10Y > 5 ? "High rate environment" :
               marketHealth.bondYield10Y > 4 ? "Elevated rates" : "Moderate rates"}
            </p>
          </div>

          {/* Liquidity */}
          <div>
            <p className="text-sm text-gray-500 mb-1">Liquidity Score</p>
            <p className={cn(
              "text-xl font-bold",
              marketHealth.liquidityScore > 80 ? "text-green-600" :
              marketHealth.liquidityScore < 50 ? "text-red-600" : "text-gray-900"
            )}>
              {marketHealth.liquidityScore.toFixed(0)}/100
            </p>
            <p className="text-xs text-gray-400 mt-1">
              {marketHealth.liquidityScore > 80 ? "Excellent liquidity" :
               marketHealth.liquidityScore < 50 ? "Thin markets - caution" : "Normal liquidity"}
            </p>
          </div>

          {/* Crypto Correlation */}
          <div>
            <p className="text-sm text-gray-500 mb-1">Crypto-Equity Corr</p>
            <p className="text-xl font-bold text-gray-900">{marketHealth.cryptoCorrelation.toFixed(2)}</p>
            <p className="text-xs text-gray-400 mt-1">
              {marketHealth.cryptoCorrelation > 0.7 ? "High correlation - no diversification" :
               marketHealth.cryptoCorrelation < 0.3 ? "Uncorrelated - diversification works" : "Moderate correlation"}
            </p>
          </div>
        </div>
      </div>

      {/* Breadth Signals */}
      <div className="bg-white rounded-2xl border border-gray-200 p-6 mb-8">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Zap className="w-5 h-5 text-yellow-500" />
          Breadth & Momentum Signals
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* New Highs vs Lows */}
          <div className="p-4 rounded-xl bg-gray-50">
            <p className="text-sm text-gray-500 mb-2">New Highs - New Lows</p>
            <p className={cn(
              "text-2xl font-bold",
              marketHealth.newHighsLows > 50 ? "text-green-600" :
              marketHealth.newHighsLows < -50 ? "text-red-600" : "text-gray-900"
            )}>
              {marketHealth.newHighsLows > 0 ? "+" : ""}{marketHealth.newHighsLows}
            </p>
            <p className="text-xs text-gray-500 mt-2">
              {marketHealth.newHighsLows > 100 ? "Strong expansion" :
               marketHealth.newHighsLows < -100 ? "Broad weakness" : "Normal activity"}
            </p>
          </div>

          {/* Breadth Thrust */}
          <div className="p-4 rounded-xl bg-gray-50">
            <p className="text-sm text-gray-500 mb-2">Breadth Thrust</p>
            <div className="flex items-center gap-2">
              {marketHealth.breadthThrust ? (
                <>
                  <CheckCircle className="w-6 h-6 text-green-500" />
                  <span className="text-lg font-bold text-green-600">ACTIVE</span>
                </>
              ) : (
                <>
                  <Minus className="w-6 h-6 text-gray-400" />
                  <span className="text-lg font-bold text-gray-500">Inactive</span>
                </>
              )}
            </div>
            <p className="text-xs text-gray-500 mt-2">
              {marketHealth.breadthThrust
                ? "Rare bullish signal - historically reliable"
                : "No thrust signal present"}
            </p>
          </div>

          {/* Trading Recommendation */}
          <div className={cn(
            "p-4 rounded-xl",
            marketHealth.regime === "RISK_ON" ? "bg-green-50" :
            marketHealth.regime === "RISK_OFF" ? "bg-red-50" : "bg-blue-50"
          )}>
            <p className="text-sm text-gray-500 mb-2">Bot Recommendation</p>
            <p className={cn(
              "text-lg font-bold",
              marketHealth.regime === "RISK_ON" ? "text-green-700" :
              marketHealth.regime === "RISK_OFF" ? "text-red-700" : "text-blue-700"
            )}>
              {marketHealth.regime === "RISK_ON" ? "Full Position Sizing" :
               marketHealth.regime === "RISK_OFF" ? "Reduce Exposure 50%" :
               marketHealth.regime === "HIGH_VOL" ? "Tighten Stops" : "Standard Parameters"}
            </p>
            <p className="text-xs text-gray-500 mt-2">
              Based on current market conditions
            </p>
          </div>
        </div>
      </div>

      {/* Quant Trader's Checklist */}
      <div className="bg-gradient-to-br from-gray-900 to-gray-800 rounded-2xl p-6 text-white">
        <h3 className="text-lg font-semibold mb-4">Quant Trader&apos;s Checklist</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ChecklistItem
            checked={marketHealth.vix < 25}
            label="Volatility manageable (VIX < 25)"
          />
          <ChecklistItem
            checked={marketHealth.advanceDeclineRatio > 1}
            label="Positive market breadth"
          />
          <ChecklistItem
            checked={marketHealth.liquidityScore > 60}
            label="Adequate liquidity"
          />
          <ChecklistItem
            checked={marketHealth.yieldCurve !== "inverted"}
            label="No yield curve inversion"
          />
          <ChecklistItem
            checked={marketHealth.putCallRatio < 1.1}
            label="Not excessive hedging"
          />
          <ChecklistItem
            checked={marketHealth.fearGreedIndex > 25}
            label="Not extreme fear"
          />
        </div>
        <div className="mt-4 pt-4 border-t border-gray-700">
          <p className="text-sm text-gray-400">
            {Object.values([
              marketHealth.vix < 25,
              marketHealth.advanceDeclineRatio > 1,
              marketHealth.liquidityScore > 60,
              marketHealth.yieldCurve !== "inverted",
              marketHealth.putCallRatio < 1.1,
              marketHealth.fearGreedIndex > 25,
            ]).filter(Boolean).length}/6 conditions met for optimal trading
          </p>
        </div>
      </div>
    </div>
  );
}

// Indicator Card Component
function IndicatorCard({
  title,
  value,
  status,
  trend,
  description,
  icon,
  suffix,
}: {
  title: string;
  value: string;
  status: "good" | "bad" | "neutral";
  trend?: "rising" | "falling" | "stable";
  description: string;
  icon: React.ReactNode;
  suffix?: string;
}) {
  const statusColors = {
    good: "text-green-600",
    bad: "text-red-600",
    neutral: "text-gray-900",
  };

  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-gray-400">{icon}</span>
        {trend && (
          <span className={cn(
            "text-xs px-2 py-0.5 rounded-full",
            trend === "rising" ? "bg-red-50 text-red-600" :
            trend === "falling" ? "bg-green-50 text-green-600" : "bg-gray-50 text-gray-600"
          )}>
            {trend}
          </span>
        )}
      </div>
      <p className="text-sm text-gray-500 mb-1">{title}</p>
      <p className={cn("text-2xl font-bold", statusColors[status])}>
        {value}{suffix}
      </p>
      <p className="text-xs text-gray-400 mt-2">{description}</p>
    </div>
  );
}

// Market Cap Bar Component
function CapBar({ label, value }: { label: string; value: number }) {
  const isPositive = value >= 0;
  const width = Math.min(Math.abs(value) * 10, 100);

  return (
    <div className="flex items-center gap-4">
      <span className="text-sm text-gray-600 w-24">{label}</span>
      <div className="flex-1 h-8 bg-gray-100 rounded-lg overflow-hidden relative">
        <div className="absolute inset-y-0 left-1/2 w-px bg-gray-300" />
        <div
          className={cn(
            "absolute top-1 bottom-1 rounded",
            isPositive ? "bg-green-500 left-1/2" : "bg-red-500 right-1/2"
          )}
          style={{
            width: `${width / 2}%`,
            [isPositive ? "left" : "right"]: "50%",
          }}
        />
      </div>
      <span className={cn(
        "text-sm font-medium w-16 text-right",
        isPositive ? "text-green-600" : "text-red-600"
      )}>
        {isPositive ? "+" : ""}{value.toFixed(1)}%
      </span>
    </div>
  );
}

// Checklist Item Component
function ChecklistItem({ checked, label }: { checked: boolean; label: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className={cn(
        "w-5 h-5 rounded-full flex items-center justify-center",
        checked ? "bg-green-500" : "bg-gray-600"
      )}>
        {checked ? (
          <CheckCircle className="w-3 h-3 text-white" />
        ) : (
          <Minus className="w-3 h-3 text-gray-400" />
        )}
      </div>
      <span className={cn("text-sm", checked ? "text-white" : "text-gray-400")}>
        {label}
      </span>
    </div>
  );
}
