import { Suspense } from "react";
import type { Metadata } from "next";
import "./globals.css";
import { StoreProvider } from "@/components/providers/store-provider";

export const metadata: Metadata = {
  title: "CodeSage | Code intelligence workspace",
  description:
    "A focused workspace for indexed codebases and CodeSage backend signals.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var key='codesage-theme';var saved=localStorage.getItem(key);var theme=saved==='light'||saved==='dark'?saved:(window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');document.documentElement.dataset.theme=theme}catch(e){document.documentElement.dataset.theme='dark'}})();`,
          }}
        />
      </head>
      <body className="min-h-screen antialiased">
        <Suspense
          fallback={
            <div
              className="flex min-h-screen items-center justify-center bg-[var(--background)] text-sm text-[var(--muted)]"
              role="status"
            >
              Loading CodeSage workspace…
            </div>
          }
        >
          <StoreProvider>{children}</StoreProvider>
        </Suspense>
      </body>
    </html>
  );
}
