"use client";

import { useEffect, useState, useCallback } from "react";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Info,
  RefreshCw,
  Calculator,
  Target,
  Shield,
  Layers,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface OptionContract {
  id: string;
  symbol: string;
  option_type: string;
  strike: number;
  expiration: string;
  days_to_expiry: number;
  underlying_price: number;
  premium: number;
  bid: number;
  ask: number;
  implied_volatility: number;
  greeks: {
    delta: number;
    gamma: number;
    theta: number;
    vega: number;
    rho: number;
  };
  intrinsic_value: number;
  time_value: number;
  moneyness: string;
  quantity?: number;
}

interface Strategy {
  id: string;
  name: string;
  legs: OptionContract[];
  net_premium: number;
  max_profit: number | null;
  max_loss: number | null;
  breakeven_prices: number[];
  portfolio_greeks: {
    delta: number;
    gamma: number;
    theta: number;
    vega: number;
    rho: number;
  };
}

interface GreeksExplanation {
  [key: string]: {
    definition: string;
    interpretation: string;
    [key: string]: string;
  };
}

export default function OptionsPage() {
  const [symbol, setSymbol] = useState("AAPL");
  const [expirationDays, setExpirationDays] = useState(30);
  const [volatility, setVolatility] = useState(0.3);
  const [chain, setChain] = useState<{ calls: OptionContract[]; puts: OptionContract[] } | null>(null);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null);
  const [greeksHelp, setGreeksHelp] = useState<GreeksExplanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [showGreeksHelp, setShowGreeksHelp] = useState(false);

  // Strategy builder state
  const [strategyType, setStrategyType] = useState("covered-call");
  const [strike1, setStrike1] = useState("");
  const [strike2, setStrike2] = useState("");
  const [strike3, setStrike3] = useState("");
  const [strike4, setStrike4] = useState("");

  const fetchChain = async () => {
    setLoading(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/options/chain/${symbol}?expiration_days=${expirationDays}&volatility=${volatility}&num_strikes=11`
      );
      if (res.ok) {
        const data = await res.json();
        setChain(data);
        // Set default strikes based on underlying price
        if (data.underlying_price) {
          const atm = Math.round(data.underlying_price);
          setStrike1(atm.toString());
          setStrike2((atm + 5).toString());
          setStrike3(atm.toString());
          setStrike4((atm - 5).toString());
        }
      }
    } catch (err) {
      console.error("Failed to fetch options chain:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchStrategies = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/options/strategies`);
      if (res.ok) {
        const data = await res.json();
        setStrategies(data.strategies || []);
      }
    } catch (err) {
      console.error("Failed to fetch strategies:", err);
    }
  };

  const fetchGreeksHelp = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/options/greeks-explain`);
      if (res.ok) {
        const data = await res.json();
        setGreeksHelp(data);
      }
    } catch (err) {
      console.error("Failed to fetch Greeks help:", err);
    }
  };

  useEffect(() => {
    fetchChain();
    fetchStrategies();
    fetchGreeksHelp();
  }, []);

  const createStrategy = async () => {
    if (!strike1) return;

    let endpoint = "";
    let body: any = {
      symbol,
      expiration_days: expirationDays,
      volatility,
    };

    switch (strategyType) {
      case "covered-call":
        endpoint = "/api/options/strategy/covered-call";
        body.strike = parseFloat(strike1);
        break;
      case "protective-put":
        endpoint = "/api/options/strategy/protective-put";
        body.strike = parseFloat(strike1);
        break;
      case "bull-call-spread":
        endpoint = "/api/options/strategy/bull-call-spread";
        body.lower_strike = parseFloat(strike1);
        body.upper_strike = parseFloat(strike2);
        break;
      case "bear-put-spread":
        endpoint = "/api/options/strategy/bear-put-spread";
        body.lower_strike = parseFloat(strike4);
        body.upper_strike = parseFloat(strike1);
        break;
      case "straddle":
        endpoint = "/api/options/strategy/straddle";
        body.strike = parseFloat(strike1);
        body.is_long = true;
        break;
      case "strangle":
        endpoint = "/api/options/strategy/strangle";
        body.put_strike = parseFloat(strike4);
        body.call_strike = parseFloat(strike2);
        body.is_long = true;
        break;
      case "iron-condor":
        endpoint = "/api/options/strategy/iron-condor";
        body.put_lower = parseFloat(strike4) - 5;
        body.put_upper = parseFloat(strike4);
        body.call_lower = parseFloat(strike2);
        body.call_upper = parseFloat(strike2) + 5;
        break;
      case "butterfly":
        endpoint = "/api/options/strategy/butterfly";
        body.lower_strike = parseFloat(strike4);
        body.middle_strike = parseFloat(strike1);
        body.upper_strike = parseFloat(strike2);
        body.use_calls = true;
        break;
      default:
        return;
    }

    try {
      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const strategy = await res.json();
        setSelectedStrategy(strategy);
        fetchStrategies();
      }
    } catch (err) {
      console.error("Failed to create strategy:", err);
    }
  };

  const underlyingPrice = chain?.calls?.[0]?.underlying_price || 0;

  return (
    <div className="min-h-screen bg-background p-2">
      {/* Header */}
      <header className="terminal-panel mb-2 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Layers className="w-5 h-5 text-bloomberg-orange" />
          <h1 className="text-lg font-bold text-bloomberg-orange font-mono">OPTIONS TRADING</h1>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            className="command-input w-20 text-xs"
            placeholder="SYMBOL"
          />
          <select
            value={expirationDays}
            onChange={(e) => setExpirationDays(parseInt(e.target.value))}
            className="command-input text-xs"
          >
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
            <option value={45}>45 days</option>
            <option value={60}>60 days</option>
            <option value={90}>90 days</option>
          </select>
          <button
            onClick={fetchChain}
            disabled={loading}
            className="px-3 py-1.5 rounded bg-primary text-primary-foreground text-xs font-mono"
          >
            {loading ? "..." : "LOAD CHAIN"}
          </button>
        </div>
      </header>

      <div className="grid grid-cols-12 gap-2">
        {/* Options Chain */}
        <div className="col-span-12 lg:col-span-8 terminal-panel">
          <div className="px-3 py-2 border-b border-border flex items-center justify-between">
            <h2 className="text-sm font-semibold text-bloomberg-orange font-mono">
              OPTIONS CHAIN - {symbol} @ ${underlyingPrice.toFixed(2)}
            </h2>
            <button
              onClick={() => setShowGreeksHelp(!showGreeksHelp)}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              <Info className="w-3 h-3" />
              Greeks Help
            </button>
          </div>

          {showGreeksHelp && greeksHelp && (
            <div className="p-3 border-b border-border bg-secondary/30 text-xs space-y-2">
              {Object.entries(greeksHelp).map(([greek, info]) => (
                <div key={greek}>
                  <span className="font-bold text-bloomberg-orange uppercase">{greek}</span>:{" "}
                  <span className="text-muted-foreground">{info.definition}</span>
                </div>
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 divide-x divide-border">
            {/* Calls */}
            <div>
              <div className="px-3 py-2 bg-positive/10 text-positive text-xs font-mono font-semibold">
                CALLS
              </div>
              <div className="max-h-[400px] overflow-y-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Strike</th>
                      <th className="text-right">Bid</th>
                      <th className="text-right">Ask</th>
                      <th className="text-right">IV</th>
                      <th className="text-right">Delta</th>
                      <th className="text-right">Theta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {chain?.calls?.map((opt) => (
                      <tr
                        key={opt.id}
                        className={cn(
                          opt.moneyness === "ITM" && "bg-positive/5",
                          opt.moneyness === "ATM" && "bg-primary/10"
                        )}
                      >
                        <td className="font-semibold">${opt.strike}</td>
                        <td className="text-right tabular-nums">${opt.bid.toFixed(2)}</td>
                        <td className="text-right tabular-nums">${opt.ask.toFixed(2)}</td>
                        <td className="text-right tabular-nums">{(opt.implied_volatility * 100).toFixed(0)}%</td>
                        <td className="text-right tabular-nums text-positive">{opt.greeks?.delta.toFixed(2)}</td>
                        <td className="text-right tabular-nums text-negative">{opt.greeks?.theta.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Puts */}
            <div>
              <div className="px-3 py-2 bg-negative/10 text-negative text-xs font-mono font-semibold">
                PUTS
              </div>
              <div className="max-h-[400px] overflow-y-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Strike</th>
                      <th className="text-right">Bid</th>
                      <th className="text-right">Ask</th>
                      <th className="text-right">IV</th>
                      <th className="text-right">Delta</th>
                      <th className="text-right">Theta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {chain?.puts?.map((opt) => (
                      <tr
                        key={opt.id}
                        className={cn(
                          opt.moneyness === "ITM" && "bg-negative/5",
                          opt.moneyness === "ATM" && "bg-primary/10"
                        )}
                      >
                        <td className="font-semibold">${opt.strike}</td>
                        <td className="text-right tabular-nums">${opt.bid.toFixed(2)}</td>
                        <td className="text-right tabular-nums">${opt.ask.toFixed(2)}</td>
                        <td className="text-right tabular-nums">{(opt.implied_volatility * 100).toFixed(0)}%</td>
                        <td className="text-right tabular-nums text-negative">{opt.greeks?.delta.toFixed(2)}</td>
                        <td className="text-right tabular-nums text-negative">{opt.greeks?.theta.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        {/* Strategy Builder */}
        <div className="col-span-12 lg:col-span-4 space-y-2">
          {/* Build Strategy */}
          <div className="terminal-panel p-3">
            <h2 className="text-sm font-semibold text-bloomberg-orange font-mono mb-3">
              STRATEGY BUILDER
            </h2>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-muted-foreground">Strategy Type</label>
                <select
                  value={strategyType}
                  onChange={(e) => setStrategyType(e.target.value)}
                  className="command-input w-full text-xs mt-1"
                >
                  <optgroup label="Income">
                    <option value="covered-call">Covered Call</option>
                    <option value="iron-condor">Iron Condor</option>
                  </optgroup>
                  <optgroup label="Protection">
                    <option value="protective-put">Protective Put</option>
                  </optgroup>
                  <optgroup label="Directional">
                    <option value="bull-call-spread">Bull Call Spread</option>
                    <option value="bear-put-spread">Bear Put Spread</option>
                  </optgroup>
                  <optgroup label="Volatility">
                    <option value="straddle">Long Straddle</option>
                    <option value="strangle">Long Strangle</option>
                    <option value="butterfly">Butterfly</option>
                  </optgroup>
                </select>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-muted-foreground">Strike 1</label>
                  <input
                    type="number"
                    value={strike1}
                    onChange={(e) => setStrike1(e.target.value)}
                    className="command-input w-full text-xs mt-1"
                    step="1"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground">Strike 2</label>
                  <input
                    type="number"
                    value={strike2}
                    onChange={(e) => setStrike2(e.target.value)}
                    className="command-input w-full text-xs mt-1"
                    step="1"
                  />
                </div>
              </div>

              {(strategyType === "iron-condor" || strategyType === "butterfly") && (
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-xs text-muted-foreground">Strike 3</label>
                    <input
                      type="number"
                      value={strike3}
                      onChange={(e) => setStrike3(e.target.value)}
                      className="command-input w-full text-xs mt-1"
                      step="1"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground">Strike 4</label>
                    <input
                      type="number"
                      value={strike4}
                      onChange={(e) => setStrike4(e.target.value)}
                      className="command-input w-full text-xs mt-1"
                      step="1"
                    />
                  </div>
                </div>
              )}

              <button
                onClick={createStrategy}
                className="w-full py-2 rounded bg-primary text-primary-foreground text-xs font-mono"
              >
                ANALYZE STRATEGY
              </button>
            </div>

            {/* Strategy Description */}
            <div className="mt-3 p-2 rounded bg-secondary/30 text-xs text-muted-foreground">
              {strategyType === "covered-call" && (
                <p>Long 100 shares + Short 1 call. Generates income, caps upside.</p>
              )}
              {strategyType === "protective-put" && (
                <p>Long 100 shares + Long 1 put. Insurance against downside.</p>
              )}
              {strategyType === "bull-call-spread" && (
                <p>Long lower call + Short higher call. Moderately bullish, limited risk.</p>
              )}
              {strategyType === "bear-put-spread" && (
                <p>Long higher put + Short lower put. Moderately bearish, limited risk.</p>
              )}
              {strategyType === "straddle" && (
                <p>Long call + Long put at same strike. Profit from big moves either direction.</p>
              )}
              {strategyType === "strangle" && (
                <p>Long OTM call + Long OTM put. Cheaper straddle, needs bigger move.</p>
              )}
              {strategyType === "iron-condor" && (
                <p>Short strangle + Long wings. Profit if price stays in range.</p>
              )}
              {strategyType === "butterfly" && (
                <p>Long wing, Short 2x body, Long wing. Max profit at middle strike.</p>
              )}
            </div>
          </div>

          {/* Strategy Analysis */}
          {selectedStrategy && (
            <div className="terminal-panel p-3">
              <h2 className="text-sm font-semibold text-bloomberg-orange font-mono mb-3">
                {selectedStrategy.name}
              </h2>

              <div className="space-y-2 text-xs">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Net Premium:</span>
                  <span className={cn(
                    "font-mono",
                    selectedStrategy.net_premium > 0 ? "text-positive" : "text-negative"
                  )}>
                    {selectedStrategy.net_premium > 0 ? "+" : ""}${selectedStrategy.net_premium.toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Max Profit:</span>
                  <span className="font-mono text-positive">
                    {selectedStrategy.max_profit === null ? "Unlimited" : `$${selectedStrategy.max_profit.toFixed(2)}`}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Max Loss:</span>
                  <span className="font-mono text-negative">
                    {selectedStrategy.max_loss === null ? "Unlimited" : `$${selectedStrategy.max_loss.toFixed(2)}`}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Breakeven:</span>
                  <span className="font-mono">
                    {selectedStrategy.breakeven_prices.map(p => `$${p.toFixed(2)}`).join(", ")}
                  </span>
                </div>

                <div className="pt-2 border-t border-border">
                  <div className="text-muted-foreground mb-1">Portfolio Greeks:</div>
                  <div className="grid grid-cols-2 gap-1">
                    <div>
                      <span className="text-muted-foreground">Delta: </span>
                      <span className="font-mono">{selectedStrategy.portfolio_greeks?.delta.toFixed(2)}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Gamma: </span>
                      <span className="font-mono">{selectedStrategy.portfolio_greeks?.gamma.toFixed(4)}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Theta: </span>
                      <span className="font-mono text-negative">{selectedStrategy.portfolio_greeks?.theta.toFixed(2)}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Vega: </span>
                      <span className="font-mono">{selectedStrategy.portfolio_greeks?.vega.toFixed(2)}</span>
                    </div>
                  </div>
                </div>

                {/* Legs */}
                <div className="pt-2 border-t border-border">
                  <div className="text-muted-foreground mb-1">Legs:</div>
                  {selectedStrategy.legs.map((leg, i) => (
                    <div key={i} className="flex justify-between">
                      <span>
                        {(leg.quantity ?? 1) > 0 ? "+" : ""}{leg.quantity ?? 1} {leg.option_type.toUpperCase()} ${leg.strike}
                      </span>
                      <span className="font-mono">${leg.premium.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Recent Strategies */}
          {strategies.length > 0 && (
            <div className="terminal-panel p-3">
              <h2 className="text-sm font-semibold text-bloomberg-orange font-mono mb-3">
                SAVED STRATEGIES
              </h2>
              <div className="max-h-[200px] overflow-y-auto space-y-1">
                {strategies.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setSelectedStrategy(s)}
                    className="w-full text-left p-2 rounded bg-secondary/30 hover:bg-secondary/50 text-xs"
                  >
                    <div className="font-semibold">{s.name}</div>
                    <div className="text-muted-foreground">
                      {s.net_premium > 0 ? "Credit" : "Debit"}: ${Math.abs(s.net_premium).toFixed(2)}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <footer className="terminal-panel mt-2 px-4 py-2">
        <p className="text-xs text-muted-foreground text-center">
          PAPER TRADING ONLY | Options carry significant risk | All strategies are simulated
        </p>
      </footer>
    </div>
  );
}
