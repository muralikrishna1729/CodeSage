"use client";

import { useCallback, useState } from "react";
import { FileCode2, FileSearch, Sparkles } from "lucide-react";
import { ApplicationShell } from "@/components/shell/application-shell";
import { Badge } from "@/components/ui/primitives";
import { ChatWorkspace } from "./chat-workspace";
import type { ChatSource } from "@/lib/services/codesageApi";

type LatestAnswer = {
  answer: string;
  source: ChatSource;
};

const sourceLabels: Record<ChatSource, string> = {
  kb: "Codebase retrieval",
  web: "Web search",
  direct: "Direct response",
  fallback: "Fallback response",
};

function ChatEvidenceInspector({ evidence }: { evidence: LatestAnswer | null }) {
  const references = evidence
    ? Array.from(
        new Set(
          Array.from(
            evidence.answer.matchAll(
              /(?:[\w@./-]+\.(?:tsx?|jsx?|py|json|ya?ml|md|css)):\d+(?:-\d+)?/g,
            ),
            (match) => match[0],
          ),
        ),
      )
    : [];

  return (
    <section className="mt-6 border-t border-[var(--border)] pt-5">
      <div className="flex items-center gap-2">
        <Sparkles size={14} className="text-[var(--primary)]" aria-hidden="true" />
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">
          Latest answer
        </p>
      </div>

      {!evidence ? (
        <div className="mt-3 rounded-[var(--radius-md)] border border-dashed border-[var(--border-strong)] px-3 py-4">
          <FileSearch size={17} className="text-[var(--muted)]" aria-hidden="true" />
          <p className="mt-2 text-xs font-medium text-[var(--foreground)]">
            Evidence appears here
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-[var(--muted)]">
            Ask a repository question to inspect the answer source and any file references it includes.
          </p>
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <Badge className="border-[var(--primary)]/30 bg-[var(--primary-soft)] text-[var(--primary)]">
            {sourceLabels[evidence.source]}
          </Badge>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">
              File references in answer
            </p>
            {references.length > 0 ? (
              <ul className="mt-2 space-y-2">
                {references.map((reference) => (
                  <li
                    key={reference}
                    className="flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-2.5 py-2"
                  >
                    <FileCode2 size={13} className="mt-0.5 shrink-0 text-[var(--primary)]" aria-hidden="true" />
                    <span className="atlas-mono break-all text-[10px] leading-5 text-[var(--foreground)]">
                      {reference}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-[11px] leading-relaxed text-[var(--muted)]">
                This response did not include explicit file:line references.
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

export default function ChatPage() {
  const [latestAnswer, setLatestAnswer] = useState<LatestAnswer | null>(null);
  const handleAssistantAnswer = useCallback(
    (answer: string, source: ChatSource) => setLatestAnswer({ answer, source }),
    [],
  );

  return (
    <ApplicationShell
      activeSection="chat"
      inspectorContent={<ChatEvidenceInspector evidence={latestAnswer} />}
    >
      <ChatWorkspace onAssistantAnswer={handleAssistantAnswer} />
    </ApplicationShell>
  );
}
