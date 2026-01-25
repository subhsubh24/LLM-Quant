"use client";

import { useState, useEffect } from "react";
import { BookOpen, Search, ChevronRight, GraduationCap } from "lucide-react";
import { cn } from "@/lib/utils";

interface Lesson {
  id: string;
  title: string;
  difficulty: string;
  category: string;
  key_concepts: string[];
}

const categories = [
  { id: "all", name: "All Topics" },
  { id: "fundamentals", name: "Fundamentals" },
  { id: "data", name: "Data" },
  { id: "features", name: "Features" },
  { id: "models", name: "Models" },
  { id: "portfolio", name: "Portfolio" },
  { id: "backtest", name: "Backtesting" },
  { id: "risk", name: "Risk" },
];

const difficultyColors = {
  beginner: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  intermediate: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  advanced: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
};

export default function LearnPage() {
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [selectedLesson, setSelectedLesson] = useState<any>(null);
  const [activeCategory, setActiveCategory] = useState("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchLessons();
  }, [activeCategory]);

  async function fetchLessons() {
    setLoading(true);
    try {
      const url =
        activeCategory === "all"
          ? "/api/learn/lessons"
          : `/api/learn/lessons?category=${activeCategory}`;
      const res = await fetch(url);
      if (res.ok) {
        setLessons(await res.json());
      }
    } catch (err) {
      // Use demo data if API fails
      setLessons([
        {
          id: "intro_quant",
          title: "Introduction to Quantitative Investing",
          difficulty: "beginner",
          category: "fundamentals",
          key_concepts: ["alpha", "risk-adjusted returns", "systematic trading"],
        },
        {
          id: "data_quality",
          title: "Data Quality and Pitfalls",
          difficulty: "beginner",
          category: "data",
          key_concepts: ["survivorship bias", "look-ahead bias", "data cleaning"],
        },
        {
          id: "feature_engineering",
          title: "Feature Engineering for Finance",
          difficulty: "intermediate",
          category: "features",
          key_concepts: ["momentum", "mean reversion", "feature lag"],
        },
        {
          id: "leakage_prevention",
          title: "Preventing Data Leakage",
          difficulty: "intermediate",
          category: "features",
          key_concepts: ["feature leakage", "target leakage", "embargo period"],
        },
        {
          id: "ml_finance",
          title: "Machine Learning for Finance",
          difficulty: "intermediate",
          category: "models",
          key_concepts: ["signal-to-noise ratio", "regularization", "ensemble methods"],
        },
        {
          id: "validation",
          title: "Time Series Validation",
          difficulty: "intermediate",
          category: "models",
          key_concepts: ["walk-forward validation", "information coefficient"],
        },
        {
          id: "portfolio_optimization",
          title: "Portfolio Optimization",
          difficulty: "advanced",
          category: "portfolio",
          key_concepts: ["mean-variance", "shrinkage estimation", "risk parity"],
        },
        {
          id: "backtest_pitfalls",
          title: "Backtesting Pitfalls",
          difficulty: "advanced",
          category: "backtest",
          key_concepts: ["overfitting", "transaction costs", "market impact"],
        },
        {
          id: "risk_management",
          title: "Risk Management",
          difficulty: "advanced",
          category: "risk",
          key_concepts: ["volatility", "maximum drawdown", "position limits"],
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function loadLesson(lessonId: string) {
    try {
      const res = await fetch(`/api/learn/lesson/${lessonId}`);
      if (res.ok) {
        setSelectedLesson(await res.json());
      }
    } catch (err) {
      // Demo content
      setSelectedLesson({
        id: lessonId,
        title: lessons.find((l) => l.id === lessonId)?.title || "Lesson",
        content: `
# Lesson Content

This is a placeholder for the full lesson content.

When the backend is running, you'll see comprehensive lessons covering:

- Key concepts and theory
- Practical examples
- Common pitfalls to avoid
- Experiments to try

## Key Takeaways

1. Always validate your assumptions
2. Be paranoid about data leakage
3. Expect degradation from backtest to live trading
4. Start simple, add complexity only when needed
        `,
        pitfalls: [
          "Common mistake 1",
          "Common mistake 2",
          "Common mistake 3",
        ],
        next_lessons: ["next_lesson_1", "next_lesson_2"],
      });
    }
  }

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold">Learn</h1>
        <p className="text-muted-foreground mt-1">
          Structured lessons to build your quant skills
        </p>
      </div>

      {/* Category Tabs */}
      <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
        {categories.map((cat) => (
          <button
            key={cat.id}
            onClick={() => setActiveCategory(cat.id)}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors",
              activeCategory === cat.id
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground"
            )}
          >
            {cat.name}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Lesson List */}
        <div className="lg:col-span-1 space-y-3">
          {loading ? (
            <div className="animate-pulse space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="h-24 bg-muted rounded-xl" />
              ))}
            </div>
          ) : (
            lessons.map((lesson) => (
              <button
                key={lesson.id}
                onClick={() => loadLesson(lesson.id)}
                className={cn(
                  "w-full p-4 rounded-xl border border-border text-left transition-colors",
                  selectedLesson?.id === lesson.id
                    ? "bg-primary/5 border-primary"
                    : "bg-card hover:bg-muted/50"
                )}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <h3 className="font-medium">{lesson.title}</h3>
                    <div className="flex items-center gap-2 mt-2">
                      <span
                        className={cn(
                          "px-2 py-0.5 rounded text-xs font-medium",
                          difficultyColors[lesson.difficulty as keyof typeof difficultyColors]
                        )}
                      >
                        {lesson.difficulty}
                      </span>
                    </div>
                  </div>
                  <ChevronRight className="w-5 h-5 text-muted-foreground mt-1" />
                </div>
              </button>
            ))
          )}
        </div>

        {/* Lesson Content */}
        <div className="lg:col-span-2">
          {selectedLesson ? (
            <div className="bg-card rounded-xl border border-border p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                  <BookOpen className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <h2 className="text-xl font-semibold">{selectedLesson.title}</h2>
                </div>
              </div>

              <div className="prose prose-slate dark:prose-invert max-w-none">
                <div
                  className="whitespace-pre-wrap text-sm leading-relaxed"
                  style={{ fontFamily: "inherit" }}
                >
                  {selectedLesson.content}
                </div>
              </div>

              {selectedLesson.pitfalls && (
                <div className="mt-6 p-4 rounded-lg bg-destructive/10 border border-destructive/20">
                  <h3 className="font-medium text-destructive mb-2">Common Pitfalls</h3>
                  <ul className="text-sm space-y-1 list-disc list-inside">
                    {selectedLesson.pitfalls.map((p: string, i: number) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-card rounded-xl border border-border p-12 flex flex-col items-center justify-center text-center">
              <GraduationCap className="w-12 h-12 text-muted-foreground mb-4" />
              <h3 className="text-lg font-medium mb-2">Select a Lesson</h3>
              <p className="text-sm text-muted-foreground max-w-sm">
                Choose a lesson from the list to start learning about quantitative
                finance concepts.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Learning Path */}
      <div className="mt-8 p-6 rounded-xl bg-card border border-border">
        <h3 className="font-medium mb-4">Recommended Learning Path</h3>
        <div className="flex flex-wrap gap-2">
          {[
            "Introduction to Quant",
            "Data Quality",
            "Feature Engineering",
            "Preventing Leakage",
            "ML for Finance",
            "Validation",
            "Portfolio Construction",
            "Backtesting",
            "Risk Management",
          ].map((step, i) => (
            <div
              key={step}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted text-sm"
            >
              <span className="w-5 h-5 rounded-full bg-primary/10 text-primary text-xs flex items-center justify-center">
                {i + 1}
              </span>
              {step}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
