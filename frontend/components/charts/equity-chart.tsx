"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

// Demo data for when API is not available
const generateDemoData = () => {
  const data = [];
  let portfolio = 100000;
  let benchmark = 100000;
  const startDate = new Date("2023-01-01");

  for (let i = 0; i < 252; i++) {
    const date = new Date(startDate);
    date.setDate(startDate.getDate() + i);

    // Random walk with slight positive drift
    portfolio *= 1 + (Math.random() - 0.48) * 0.02;
    benchmark *= 1 + (Math.random() - 0.48) * 0.015;

    data.push({
      date: date.toISOString().split("T")[0],
      portfolio: Math.round(portfolio),
      benchmark: Math.round(benchmark),
    });
  }

  return data;
};

const demoData = generateDemoData();

export function EquityChart() {
  return (
    <div className="h-[300px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={demoData}
          margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
        >
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 12 }}
            tickFormatter={(value) => {
              const date = new Date(value);
              return date.toLocaleDateString("en-US", { month: "short" });
            }}
            className="text-muted-foreground"
          />
          <YAxis
            tick={{ fontSize: 12 }}
            tickFormatter={(value) => `$${(value / 1000).toFixed(0)}K`}
            className="text-muted-foreground"
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "hsl(var(--card))",
              border: "1px solid hsl(var(--border))",
              borderRadius: "8px",
            }}
            labelFormatter={(value) =>
              new Date(value).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })
            }
            formatter={(value: number, name: string) => [
              `$${value.toLocaleString()}`,
              name === "portfolio" ? "Portfolio" : "Benchmark",
            ]}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="portfolio"
            stroke="hsl(var(--primary))"
            strokeWidth={2}
            dot={false}
            name="Portfolio"
          />
          <Line
            type="monotone"
            dataKey="benchmark"
            stroke="hsl(var(--muted-foreground))"
            strokeWidth={1.5}
            dot={false}
            strokeDasharray="5 5"
            name="Benchmark"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
