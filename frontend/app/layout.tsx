import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider } from "@/components/layout/theme-provider";
import { TabNav } from "@/components/layout/tab-nav";

export const metadata: Metadata = {
  title: "QuantLab - Quant Research & Paper Trading",
  description: "Rigorous quantitative research and paper trading education platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <div className="min-h-screen">
            <TabNav />
            <main className="min-h-screen overflow-auto bg-gray-50">
              {children}
            </main>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
