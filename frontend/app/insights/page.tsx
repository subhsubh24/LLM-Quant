"use client";

import { useEffect, useState } from "react";
import {
  Brain,
  TrendingUp,
  BookOpen,
  MessageSquare,
  RefreshCw,
  Search,
  Sparkles,
  Target,
  AlertTriangle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function InsightsPage() {
  const [activeTab, setActiveTab] = useState<"commentary" | "stock" | "learn" | "portfolio">("commentary");
  const [loading, setLoading] = useState(false);
  const [commentary, setCommentary] = useState<string | null>(null);
  const [stockAnalysis, setStockAnalysis] = useState<any>(null);
  const [learningPath, setLearningPath] = useState<string | null>(null);
  const [portfolioAnalysis, setPortfolioAnalysis] = useState<string | null>(null);
  const [searchSymbol, setSearchSymbol] = useState("");
  const [concept, setConcept] = useState("");
  const [conceptExplanation, setConceptExplanation] = useState<string | null>(null);

  useEffect(() => {
    if (activeTab === "commentary" && !commentary) {
      fetchCommentary();
    }
    if (activeTab === "learn" && !learningPath) {
      fetchLearningPath();
    }
    if (activeTab === "portfolio" && !portfolioAnalysis) {
      fetchPortfolioAnalysis();
    }
  }, [activeTab]);

  const fetchCommentary = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/ai/market-commentary`);
      if (res.ok) {
        const data = await res.json();
        setCommentary(data.commentary);
      }
    } catch (err) {
      console.error("Failed to fetch commentary:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchStockAnalysis = async (symbol: string) => {
    if (!symbol) return;
    setLoading(true);
    setStockAnalysis(null);
    try {
      const res = await fetch(`${API_BASE}/api/ai/analyze/${symbol.toUpperCase()}`);
      if (res.ok) {
        const data = await res.json();
        setStockAnalysis(data);
      }
    } catch (err) {
      console.error("Failed to fetch stock analysis:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchLearningPath = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/ai/learning-path?goal=become%20a%20quant%20in%20one%20year`);
      if (res.ok) {
        const data = await res.json();
        setLearningPath(data.learning_path);
      }
    } catch (err) {
      console.error("Failed to fetch learning path:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchPortfolioAnalysis = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/ai/analyze-portfolio`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setPortfolioAnalysis(data.analysis);
      }
    } catch (err) {
      console.error("Failed to fetch portfolio analysis:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchConceptExplanation = async () => {
    if (!concept) return;
    setLoading(true);
    setConceptExplanation(null);
    try {
      const res = await fetch(`${API_BASE}/api/ai/explain/${encodeURIComponent(concept)}`);
      if (res.ok) {
        const data = await res.json();
        setConceptExplanation(data.explanation);
      }
    } catch (err) {
      console.error("Failed to fetch explanation:", err);
    } finally {
      setLoading(false);
    }
  };

  const tabs = [
    { id: "commentary", label: "MARKET BRIEF", icon: MessageSquare },
    { id: "stock", label: "STOCK ANALYSIS", icon: TrendingUp },
    { id: "portfolio", label: "PORTFOLIO", icon: Target },
    { id: "learn", label: "LEARNING PATH", icon: BookOpen },
  ];

  return (
    <div className="min-h-screen bg-background p-2">
      {/* Header */}
      <header className="terminal-panel mb-2 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Brain className="w-5 h-5 text-bloomberg-orange" />
          <h1 className="text-lg font-bold text-bloomberg-orange font-mono">AI INSIGHTS</h1>
          <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-bloomberg-orange/20 text-bloomberg-orange text-xs font-mono">
            <Sparkles className="w-3 h-3" />
            GPT-4 POWERED
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="terminal-panel mb-2 px-2 py-1 flex items-center gap-1">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 rounded text-xs font-mono transition-colors",
              activeTab === tab.id
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-secondary"
            )}
          >
            <tab.icon className="w-3 h-3" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="terminal-panel min-h-[600px]">
        {/* Market Commentary */}
        {activeTab === "commentary" && (
          <div className="p-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-bloomberg-orange font-mono">
                MORNING MARKET BRIEF
              </h2>
              <button
                onClick={fetchCommentary}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <RefreshCw className={cn("w-3 h-3", loading && "animate-spin")} />
                Refresh
              </button>
            </div>

            {loading && !commentary ? (
              <LoadingState message="Generating market commentary..." />
            ) : commentary ? (
              <div className="prose prose-invert prose-sm max-w-none">
                <ReactMarkdown>{commentary}</ReactMarkdown>
              </div>
            ) : (
              <EmptyState message="Click refresh to generate market commentary" />
            )}
          </div>
        )}

        {/* Stock Analysis */}
        {activeTab === "stock" && (
          <div className="p-4">
            <div className="flex items-center gap-4 mb-4">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  fetchStockAnalysis(searchSymbol);
                }}
                className="flex items-center gap-2"
              >
                <Search className="w-4 h-4 text-muted-foreground" />
                <input
                  type="text"
                  value={searchSymbol}
                  onChange={(e) => setSearchSymbol(e.target.value.toUpperCase())}
                  placeholder="Enter symbol (e.g., AAPL)"
                  className="command-input w-40"
                />
                <button
                  type="submit"
                  className="px-3 py-1.5 rounded bg-primary text-primary-foreground text-xs font-mono"
                >
                  ANALYZE
                </button>
              </form>
            </div>

            {loading ? (
              <LoadingState message={`Analyzing ${searchSymbol}...`} />
            ) : stockAnalysis ? (
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <span className="text-lg font-bold text-bloomberg-orange font-mono">
                    {stockAnalysis.symbol}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    Generated {new Date(stockAnalysis.generated_at).toLocaleTimeString()}
                  </span>
                </div>
                <div className="prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown>{stockAnalysis.analysis}</ReactMarkdown>
                </div>
              </div>
            ) : (
              <EmptyState message="Enter a stock symbol to get AI-powered analysis" />
            )}
          </div>
        )}

        {/* Portfolio Analysis */}
        {activeTab === "portfolio" && (
          <div className="p-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-bloomberg-orange font-mono">
                PORTFOLIO ANALYSIS
              </h2>
              <button
                onClick={fetchPortfolioAnalysis}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <RefreshCw className={cn("w-3 h-3", loading && "animate-spin")} />
                Refresh
              </button>
            </div>

            {loading && !portfolioAnalysis ? (
              <LoadingState message="Analyzing your portfolio..." />
            ) : portfolioAnalysis ? (
              <div className="prose prose-invert prose-sm max-w-none">
                <ReactMarkdown>{portfolioAnalysis}</ReactMarkdown>
              </div>
            ) : (
              <EmptyState message="Add positions to your paper portfolio to get AI analysis" />
            )}
          </div>
        )}

        {/* Learning Path */}
        {activeTab === "learn" && (
          <div className="p-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-bloomberg-orange font-mono">
                YOUR QUANT LEARNING PATH
              </h2>
              <button
                onClick={fetchLearningPath}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <RefreshCw className={cn("w-3 h-3", loading && "animate-spin")} />
                Regenerate
              </button>
            </div>

            {/* Concept lookup */}
            <div className="mb-6 p-3 rounded bg-secondary/50 border border-border">
              <div className="text-xs text-muted-foreground mb-2">
                Need to understand a specific concept?
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  fetchConceptExplanation();
                }}
                className="flex items-center gap-2"
              >
                <input
                  type="text"
                  value={concept}
                  onChange={(e) => setConcept(e.target.value)}
                  placeholder="e.g., Sharpe ratio, mean-variance optimization, alpha decay"
                  className="command-input flex-1"
                />
                <button
                  type="submit"
                  className="px-3 py-1.5 rounded bg-primary text-primary-foreground text-xs font-mono"
                >
                  EXPLAIN
                </button>
              </form>
            </div>

            {conceptExplanation && (
              <div className="mb-6 p-4 rounded bg-card border border-border">
                <div className="flex items-center gap-2 mb-3">
                  <BookOpen className="w-4 h-4 text-bloomberg-orange" />
                  <span className="font-semibold text-sm">{concept}</span>
                </div>
                <div className="prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown>{conceptExplanation}</ReactMarkdown>
                </div>
              </div>
            )}

            {loading && !learningPath ? (
              <LoadingState message="Creating your personalized learning path..." />
            ) : learningPath ? (
              <div className="prose prose-invert prose-sm max-w-none">
                <ReactMarkdown>{learningPath}</ReactMarkdown>
              </div>
            ) : (
              <EmptyState message="Loading your learning path..." />
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <footer className="terminal-panel mt-2 px-4 py-2">
        <p className="text-xs text-muted-foreground text-center">
          AI insights are for educational purposes only | Not financial advice | Always verify with your own research
        </p>
      </footer>
    </div>
  );
}

function LoadingState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12">
      <div className="w-8 h-8 border-2 border-bloomberg-orange border-t-transparent rounded-full animate-spin mb-4" />
      <p className="text-sm text-muted-foreground font-mono">{message}</p>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
      <Brain className="w-12 h-12 mb-4 opacity-50" />
      <p className="text-sm font-mono">{message}</p>
    </div>
  );
}
