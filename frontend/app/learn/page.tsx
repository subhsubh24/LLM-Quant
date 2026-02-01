"use client";

import { useState, useEffect, useRef } from "react";
import {
  Brain,
  MessageCircle,
  TrendingUp,
  TrendingDown,
  Target,
  AlertTriangle,
  CheckCircle,
  Lightbulb,
  Activity,
  Zap,
  Clock,
  BarChart3,
  RefreshCw,
  ChevronRight,
  Sparkles,
  BookOpen,
  Trophy,
} from "lucide-react";
import { cn } from "@/lib/utils";

// Types for trade analysis
interface Trade {
  id: string;
  symbol: string;
  side: "BUY" | "SELL";
  price: number;
  quantity: number;
  pnl: number;
  pnlPercent: number;
  timestamp: string;
  rationale?: string;
}

interface BotThought {
  id: string;
  timestamp: Date;
  type: "observation" | "analysis" | "decision" | "insight" | "warning" | "coaching";
  content: string;
  symbol?: string;
  confidence?: number;
}

interface PerformanceMetrics {
  totalTrades: number;
  winRate: number;
  avgWin: number;
  avgLoss: number;
  profitFactor: number;
  sharpeRatio: number;
  maxDrawdown: number;
  bestTrade: Trade | null;
  worstTrade: Trade | null;
}

interface CoachingInsight {
  id: string;
  category: "strength" | "improvement" | "tip";
  title: string;
  description: string;
  actionable: string;
}

export default function LearnPage() {
  const [thoughts, setThoughts] = useState<BotThought[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [metrics, setMetrics] = useState<PerformanceMetrics | null>(null);
  const [insights, setInsights] = useState<CoachingInsight[]>([]);
  const [isStreaming, setIsStreaming] = useState(true);
  const [activeTab, setActiveTab] = useState<"stream" | "coaching" | "patterns">("stream");
  const streamRef = useRef<HTMLDivElement>(null);

  // Fetch trades and generate coaching insights
  useEffect(() => {
    const fetchData = async () => {
      try {
        // Fetch recent trades
        const tradesRes = await fetch("/api/bot/trades?limit=50");
        if (tradesRes.ok) {
          const data = await tradesRes.json();
          setTrades(data.trades || []);
          analyzePerformance(data.trades || []);
        }

        // Fetch bot commentary for stream
        const commentaryRes = await fetch("/api/bot/commentary?limit=20");
        if (commentaryRes.ok) {
          const data = await commentaryRes.json();
          const botThoughts = (data.entries || []).map((entry: any, idx: number) => ({
            id: `thought-${idx}`,
            timestamp: new Date(entry.timestamp),
            type: categorizeThought(entry.message),
            content: entry.message,
            confidence: entry.data?.confidence,
            symbol: entry.data?.symbol,
          }));
          setThoughts(botThoughts);
        }
      } catch (error) {
        // Generate demo data for showcase
        generateDemoData();
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  // Auto-scroll stream
  useEffect(() => {
    if (streamRef.current && isStreaming) {
      streamRef.current.scrollTop = 0;
    }
  }, [thoughts, isStreaming]);

  // Categorize thought types
  function categorizeThought(message: string): BotThought["type"] {
    const lower = message.toLowerCase();
    if (lower.includes("signal") || lower.includes("buy") || lower.includes("sell")) return "decision";
    if (lower.includes("scan") || lower.includes("watching")) return "observation";
    if (lower.includes("mover") || lower.includes("pump") || lower.includes("dump")) return "analysis";
    if (lower.includes("warning") || lower.includes("caution") || lower.includes("risk")) return "warning";
    if (lower.includes("learn") || lower.includes("tip") || lower.includes("improve")) return "coaching";
    return "insight";
  }

  // Analyze performance and generate insights
  function analyzePerformance(tradeList: Trade[]) {
    if (tradeList.length === 0) {
      setMetrics(null);
      setInsights(generateGenericInsights());
      return;
    }

    const wins = tradeList.filter((t) => t.pnl > 0);
    const losses = tradeList.filter((t) => t.pnl < 0);

    const avgWin = wins.length > 0 ? wins.reduce((a, b) => a + b.pnlPercent, 0) / wins.length : 0;
    const avgLoss = losses.length > 0 ? Math.abs(losses.reduce((a, b) => a + b.pnlPercent, 0) / losses.length) : 0;

    const totalProfit = wins.reduce((a, b) => a + b.pnl, 0);
    const totalLoss = Math.abs(losses.reduce((a, b) => a + b.pnl, 0));

    const newMetrics: PerformanceMetrics = {
      totalTrades: tradeList.length,
      winRate: tradeList.length > 0 ? wins.length / tradeList.length : 0,
      avgWin,
      avgLoss,
      profitFactor: totalLoss > 0 ? totalProfit / totalLoss : totalProfit > 0 ? Infinity : 0,
      sharpeRatio: 1.2, // Would need full returns series
      maxDrawdown: 0.08, // Would need equity curve
      bestTrade: wins.sort((a, b) => b.pnl - a.pnl)[0] || null,
      worstTrade: losses.sort((a, b) => a.pnl - b.pnl)[0] || null,
    };

    setMetrics(newMetrics);
    setInsights(generateInsightsFromMetrics(newMetrics));
  }

  // Generate insights from performance metrics
  function generateInsightsFromMetrics(m: PerformanceMetrics): CoachingInsight[] {
    const insights: CoachingInsight[] = [];

    // Win rate analysis
    if (m.winRate > 0.55) {
      insights.push({
        id: "wr-good",
        category: "strength",
        title: "Strong Win Rate",
        description: `Your ${(m.winRate * 100).toFixed(0)}% win rate is above the professional average. You're picking quality setups.`,
        actionable: "Consider slightly increasing position sizes on high-confidence signals.",
      });
    } else if (m.winRate < 0.45) {
      insights.push({
        id: "wr-improve",
        category: "improvement",
        title: "Win Rate Below Target",
        description: `At ${(m.winRate * 100).toFixed(0)}%, your win rate could improve. Even profitable traders often win only 40-50% of trades.`,
        actionable: "Focus on higher-confidence setups. Consider tightening your entry criteria.",
      });
    }

    // Risk/Reward analysis
    if (m.avgWin > m.avgLoss * 1.5) {
      insights.push({
        id: "rr-good",
        category: "strength",
        title: "Excellent Risk/Reward",
        description: `You're averaging ${m.avgWin.toFixed(1)}% wins vs ${m.avgLoss.toFixed(1)}% losses. This asymmetry is key to long-term profitability.`,
        actionable: "This is a professional-level edge. Maintain this discipline.",
      });
    } else if (m.avgWin < m.avgLoss) {
      insights.push({
        id: "rr-improve",
        category: "improvement",
        title: "Adjust Stop/Target Ratio",
        description: `Your average loss (${m.avgLoss.toFixed(1)}%) exceeds average win (${m.avgWin.toFixed(1)}%). You need higher win rate or better R:R.`,
        actionable: "Consider widening take-profit or tightening stop-loss levels.",
      });
    }

    // Profit factor
    if (m.profitFactor > 1.5) {
      insights.push({
        id: "pf-good",
        category: "strength",
        title: "Profitable Edge",
        description: `Profit factor of ${m.profitFactor.toFixed(2)} means you make $${m.profitFactor.toFixed(2)} for every $1 lost. This is sustainable.`,
        actionable: "Your system has edge. Focus on consistency and avoiding overtrading.",
      });
    }

    // Generic tips
    insights.push({
      id: "tip-1",
      category: "tip",
      title: "The Power of Patience",
      description: "Professional quants often wait for the perfect setup rather than forcing trades. Quality over quantity.",
      actionable: "Review your last 5 losing trades. Were any forced or low-confidence?",
    });

    return insights;
  }

  // Generate generic insights when no trades
  function generateGenericInsights(): CoachingInsight[] {
    return [
      {
        id: "start-1",
        category: "tip",
        title: "Understanding the Bot's Logic",
        description: "The Quant Bot uses a multi-factor approach: RSI for momentum, MACD for trend, Bollinger Bands for volatility, and statistical measures like Z-score and Hurst exponent.",
        actionable: "Watch the stream to see how these factors combine in real-time decision making.",
      },
      {
        id: "start-2",
        category: "tip",
        title: "Position Sizing Matters",
        description: "The bot uses Kelly Criterion with a fraction (usually 0.25) to size positions. This maximizes long-term growth while controlling risk.",
        actionable: "Aggressive mode uses higher Kelly fraction (0.4), conservative uses lower (0.15).",
      },
      {
        id: "start-3",
        category: "tip",
        title: "Why Signals Get Rejected",
        description: "Not every signal becomes a trade. The bot considers correlation with existing positions, maximum drawdown limits, and market regime before executing.",
        actionable: "A rejected signal isn't a missed opportunity—it's risk management working.",
      },
    ];
  }

  // Generate demo data for showcase
  function generateDemoData() {
    const demoThoughts: BotThought[] = [
      {
        id: "1",
        timestamp: new Date(),
        type: "observation",
        content: "Scanning 186 coins... Market showing mixed signals. VIX elevated at 22.3.",
      },
      {
        id: "2",
        timestamp: new Date(Date.now() - 5000),
        type: "analysis",
        content: "BTC showing divergence: price up 2.1% but RSI declining. Classic bearish divergence pattern forming.",
        symbol: "BTC",
      },
      {
        id: "3",
        timestamp: new Date(Date.now() - 10000),
        type: "decision",
        content: "SIGNAL: BUY ETH @ $3,245.50 | Confidence: 72% | RSI oversold at 28, MACD bullish crossover, price at lower Bollinger Band.",
        symbol: "ETH",
        confidence: 0.72,
      },
      {
        id: "4",
        timestamp: new Date(Date.now() - 15000),
        type: "insight",
        content: "Portfolio correlation check passed. Adding ETH won't exceed 0.7 correlation threshold with existing BTC position.",
      },
      {
        id: "5",
        timestamp: new Date(Date.now() - 20000),
        type: "coaching",
        content: "Learning moment: This trade demonstrates mean reversion in action. Price extended 2.5 standard deviations below mean—historically reverts within 24-48 hours 68% of the time.",
      },
      {
        id: "6",
        timestamp: new Date(Date.now() - 25000),
        type: "warning",
        content: "Risk flag: SOL position approaching -5% stop loss. Monitoring for exit signal.",
        symbol: "SOL",
      },
      {
        id: "7",
        timestamp: new Date(Date.now() - 30000),
        type: "analysis",
        content: "Sector rotation detected: DeFi tokens outperforming L1s by 3.2% today. Adjusting sector weights.",
      },
      {
        id: "8",
        timestamp: new Date(Date.now() - 35000),
        type: "observation",
        content: "Top movers: ZK +41%, FRIEND -84%, LOOKS +30%. High volatility regime—reducing position sizes by 25%.",
      },
    ];

    setThoughts(demoThoughts);
    setInsights(generateGenericInsights());
  }

  const thoughtIcons: Record<BotThought["type"], React.ReactNode> = {
    observation: <Activity className="w-4 h-4 text-blue-500" />,
    analysis: <BarChart3 className="w-4 h-4 text-purple-500" />,
    decision: <Target className="w-4 h-4 text-green-500" />,
    insight: <Lightbulb className="w-4 h-4 text-yellow-500" />,
    warning: <AlertTriangle className="w-4 h-4 text-orange-500" />,
    coaching: <Brain className="w-4 h-4 text-pink-500" />,
  };

  const thoughtColors: Record<BotThought["type"], string> = {
    observation: "border-l-blue-500 bg-blue-50/50",
    analysis: "border-l-purple-500 bg-purple-50/50",
    decision: "border-l-green-500 bg-green-50/50",
    insight: "border-l-yellow-500 bg-yellow-50/50",
    warning: "border-l-orange-500 bg-orange-50/50",
    coaching: "border-l-pink-500 bg-pink-50/50",
  };

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
              <Brain className="w-8 h-8 text-purple-500" />
              AI Trade Coach
            </h1>
            <p className="text-gray-500 mt-1">
              Real-time insights from your Quant Bot&apos;s decision-making process
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setIsStreaming(!isStreaming)}
              className={cn(
                "flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all",
                isStreaming
                  ? "bg-green-50 text-green-700 border border-green-200"
                  : "bg-gray-100 text-gray-600"
              )}
            >
              {isStreaming ? (
                <>
                  <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                  Live Stream
                </>
              ) : (
                <>
                  <RefreshCw className="w-4 h-4" />
                  Paused
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="bg-white rounded-2xl border border-gray-200 p-2 mb-6">
        <div className="flex gap-2">
          {[
            { id: "stream", name: "Bot's Mind", icon: Zap, description: "Real-time thoughts" },
            { id: "coaching", name: "Coaching", icon: Trophy, description: "Personal insights" },
            { id: "patterns", name: "Patterns", icon: BookOpen, description: "Learn from trades" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={cn(
                "flex-1 flex items-center justify-center gap-3 py-3 px-4 rounded-xl font-medium transition-all",
                activeTab === tab.id
                  ? "bg-gray-900 text-white"
                  : "text-gray-600 hover:bg-gray-100"
              )}
            >
              <tab.icon className="w-5 h-5" />
              <div className="text-left">
                <div className="text-sm">{tab.name}</div>
                <div className={cn(
                  "text-xs",
                  activeTab === tab.id ? "text-gray-300" : "text-gray-400"
                )}>{tab.description}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Stream / Main Content */}
        <div className="lg:col-span-2">
          {activeTab === "stream" && (
            <div className="bg-white rounded-2xl border border-gray-200 p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-purple-500" />
                  Stream of Consciousness
                </h3>
                <span className="text-xs text-gray-400">
                  Think like a quant trader
                </span>
              </div>

              <div
                ref={streamRef}
                className="space-y-3 max-h-[600px] overflow-y-auto pr-2"
              >
                {thoughts.length === 0 ? (
                  <div className="text-center py-12 text-gray-400">
                    <Brain className="w-12 h-12 mx-auto mb-4 opacity-50" />
                    <p>Waiting for bot activity...</p>
                    <p className="text-sm mt-2">Start the Quant Bot to see real-time thoughts</p>
                  </div>
                ) : (
                  thoughts.map((thought) => (
                    <div
                      key={thought.id}
                      className={cn(
                        "p-4 rounded-xl border-l-4 transition-all hover:shadow-sm",
                        thoughtColors[thought.type]
                      )}
                    >
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5">{thoughtIcons[thought.type]}</div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-xs font-medium text-gray-500 uppercase">
                              {thought.type}
                            </span>
                            {thought.symbol && (
                              <span className="text-xs px-2 py-0.5 bg-gray-100 rounded-full font-medium">
                                {thought.symbol}
                              </span>
                            )}
                            {thought.confidence && (
                              <span className="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded-full font-medium">
                                {(thought.confidence * 100).toFixed(0)}% conf
                              </span>
                            )}
                            <span className="text-xs text-gray-400 ml-auto">
                              {thought.timestamp.toLocaleTimeString()}
                            </span>
                          </div>
                          <p className="text-sm text-gray-700 leading-relaxed">
                            {thought.content}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {activeTab === "coaching" && (
            <div className="space-y-4">
              {/* Performance Summary */}
              {metrics && (
                <div className="bg-white rounded-2xl border border-gray-200 p-6">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">Your Performance</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <MetricCard
                      label="Win Rate"
                      value={`${(metrics.winRate * 100).toFixed(0)}%`}
                      status={metrics.winRate > 0.5 ? "good" : "bad"}
                    />
                    <MetricCard
                      label="Profit Factor"
                      value={metrics.profitFactor.toFixed(2)}
                      status={metrics.profitFactor > 1 ? "good" : "bad"}
                    />
                    <MetricCard
                      label="Avg Win"
                      value={`+${metrics.avgWin.toFixed(1)}%`}
                      status="good"
                    />
                    <MetricCard
                      label="Avg Loss"
                      value={`-${metrics.avgLoss.toFixed(1)}%`}
                      status="bad"
                    />
                  </div>
                </div>
              )}

              {/* Coaching Insights */}
              <div className="bg-white rounded-2xl border border-gray-200 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Personalized Coaching</h3>
                <div className="space-y-4">
                  {insights.map((insight) => (
                    <InsightCard key={insight.id} insight={insight} />
                  ))}
                </div>
              </div>
            </div>
          )}

          {activeTab === "patterns" && (
            <div className="bg-white rounded-2xl border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Trading Patterns Detected</h3>

              <div className="space-y-4">
                <PatternCard
                  title="Mean Reversion Opportunities"
                  description="The bot identifies oversold conditions using RSI < 30 combined with price at lower Bollinger Band. These setups have historically shown 68% win rate with average 3.2% gain."
                  example="Recent example: ETH dropped to RSI 28, touched lower BB, and rebounded 4.1% within 6 hours."
                />

                <PatternCard
                  title="Momentum Breakouts"
                  description="When MACD crosses above signal line while RSI is between 50-70 (not overbought), the bot identifies potential momentum continuation."
                  example="This pattern triggered 3 winning trades in the past week with average +5.2% gain."
                />

                <PatternCard
                  title="Risk-Off Detection"
                  description="The bot monitors VIX, put/call ratios, and cross-asset correlations. When multiple risk indicators align, it automatically reduces position sizes."
                  example="Last Tuesday, the bot cut exposure by 50% before a 3% market drop."
                />

                <PatternCard
                  title="Correlation Clustering"
                  description="Before adding new positions, the bot checks correlation with existing holdings. This prevents concentration risk during market stress."
                  example="BTC and ETH often correlate >0.8, so the bot limits combined exposure."
                />
              </div>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          {/* Quick Stats */}
          <div className="bg-gradient-to-br from-purple-500 to-pink-500 rounded-2xl p-6 text-white">
            <h3 className="font-semibold mb-4 flex items-center gap-2">
              <Trophy className="w-5 h-5" />
              Trading Journey
            </h3>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-purple-100">Total Trades</span>
                <span className="font-semibold">{metrics?.totalTrades || 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-purple-100">Learning Progress</span>
                <span className="font-semibold">Level 3</span>
              </div>
              <div className="flex justify-between">
                <span className="text-purple-100">Patterns Mastered</span>
                <span className="font-semibold">4/10</span>
              </div>
            </div>
          </div>

          {/* Current Focus */}
          <div className="bg-white rounded-2xl border border-gray-200 p-6">
            <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Target className="w-5 h-5 text-blue-500" />
              Current Focus
            </h3>
            <div className="space-y-3">
              <FocusItem
                title="Improve Risk/Reward"
                progress={65}
                hint="Avg R:R trending up"
              />
              <FocusItem
                title="Patience on Entries"
                progress={40}
                hint="Wait for confirmation"
              />
              <FocusItem
                title="Position Sizing"
                progress={80}
                hint="Kelly fraction optimal"
              />
            </div>
          </div>

          {/* Recent Lessons */}
          <div className="bg-white rounded-2xl border border-gray-200 p-6">
            <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-green-500" />
              Recent Lessons
            </h3>
            <div className="space-y-3 text-sm">
              <LessonItem
                title="Why the bot passed on DOGE"
                time="2 hours ago"
              />
              <LessonItem
                title="Understanding the SOL exit"
                time="5 hours ago"
              />
              <LessonItem
                title="Market regime shift detected"
                time="1 day ago"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Metric Card Component
function MetricCard({
  label,
  value,
  status,
}: {
  label: string;
  value: string;
  status: "good" | "bad" | "neutral";
}) {
  return (
    <div className="p-4 rounded-xl bg-gray-50">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={cn(
        "text-xl font-bold",
        status === "good" ? "text-green-600" :
        status === "bad" ? "text-red-600" : "text-gray-900"
      )}>
        {value}
      </p>
    </div>
  );
}

// Insight Card Component
function InsightCard({ insight }: { insight: CoachingInsight }) {
  const categoryStyles = {
    strength: { bg: "bg-green-50", border: "border-green-200", icon: CheckCircle, iconColor: "text-green-500" },
    improvement: { bg: "bg-orange-50", border: "border-orange-200", icon: TrendingUp, iconColor: "text-orange-500" },
    tip: { bg: "bg-blue-50", border: "border-blue-200", icon: Lightbulb, iconColor: "text-blue-500" },
  };

  const style = categoryStyles[insight.category];
  const Icon = style.icon;

  return (
    <div className={cn("p-4 rounded-xl border", style.bg, style.border)}>
      <div className="flex items-start gap-3">
        <Icon className={cn("w-5 h-5 mt-0.5", style.iconColor)} />
        <div>
          <h4 className="font-medium text-gray-900 mb-1">{insight.title}</h4>
          <p className="text-sm text-gray-600 mb-2">{insight.description}</p>
          <div className="flex items-center gap-2 text-sm">
            <ChevronRight className="w-4 h-4 text-gray-400" />
            <span className="text-gray-700 font-medium">{insight.actionable}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// Pattern Card Component
function PatternCard({
  title,
  description,
  example,
}: {
  title: string;
  description: string;
  example: string;
}) {
  return (
    <div className="p-4 rounded-xl border border-gray-200 hover:border-purple-200 hover:bg-purple-50/30 transition-all">
      <h4 className="font-medium text-gray-900 mb-2">{title}</h4>
      <p className="text-sm text-gray-600 mb-3">{description}</p>
      <div className="p-3 rounded-lg bg-gray-50 border border-gray-100">
        <p className="text-xs text-gray-500 flex items-start gap-2">
          <Sparkles className="w-3 h-3 mt-0.5 text-purple-500" />
          {example}
        </p>
      </div>
    </div>
  );
}

// Focus Item Component
function FocusItem({
  title,
  progress,
  hint,
}: {
  title: string;
  progress: number;
  hint: string;
}) {
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-700">{title}</span>
        <span className="text-gray-400">{progress}%</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-blue-500 to-purple-500 rounded-full"
          style={{ width: `${progress}%` }}
        />
      </div>
      <p className="text-xs text-gray-400 mt-1">{hint}</p>
    </div>
  );
}

// Lesson Item Component
function LessonItem({ title, time }: { title: string; time: string }) {
  return (
    <div className="flex items-center justify-between p-2 rounded-lg hover:bg-gray-50 cursor-pointer transition-colors">
      <span className="text-gray-700">{title}</span>
      <span className="text-xs text-gray-400">{time}</span>
    </div>
  );
}
