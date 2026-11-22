"use client";

import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";
import { IconButton } from "@/components/ui/primitives";

type Theme = "light" | "dark";

const STORAGE_KEY = "codesage-theme";

function readTheme(): Theme {
  if (typeof window === "undefined") {
    return "dark";
  }
  const saved = window.localStorage.getItem(STORAGE_KEY);
  if (saved === "light" || saved === "dark") {
    return saved;
  }
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function subscribe(onStoreChange: () => void): () => void {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener("codesage-theme-change", onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener("codesage-theme-change", onStoreChange);
  };
}

export function ThemeControl() {
  const theme = useSyncExternalStore(subscribe, readTheme, () => "dark");

  function toggleTheme(): void {
    const nextTheme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = nextTheme;
    window.localStorage.setItem(STORAGE_KEY, nextTheme);
    window.dispatchEvent(new Event("codesage-theme-change"));
  }

  const target = theme === "dark" ? "light" : "dark";

  return (
    <IconButton
      onClick={toggleTheme}
      aria-label={theme ? `Switch to ${target} theme` : "Switch theme"}
      title={theme ? `Switch to ${target} theme` : "Switch theme"}
    >
      {theme === "light" ? (
        <Moon aria-hidden="true" size={16} />
      ) : (
        <Sun aria-hidden="true" size={16} />
      )}
    </IconButton>
  );
}
