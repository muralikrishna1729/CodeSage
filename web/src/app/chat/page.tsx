"use client";

import { useCallback, useState } from "react";
import { Button } from "@/components/ui/primitives";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { clearRepository, selectRepository } from "@/lib/features/repository/repositorySlice";
import { selectActiveRepository, selectRepositories } from "@/lib/features/repository/repositorySelectors";
import { useChatMutation, useGetRepositoriesQuery, type ChatResponse } from "@/lib/services/codesageApi";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  source?: ChatResponse["source"];
};

export default function ChatPage() {
  const dispatch = useAppDispatch();
  const repositories = useAppSelector(selectRepositories);
  const activeRepository = useAppSelector(selectActiveRepository);
  useGetRepositoriesQuery();
  const [chat] = useChatMutation();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(async () => {
    if (loading) return;
    if (!input.trim() || !activeRepository) return;
    setLoading(true);
    setError(null);

    const chatHistory = messages.slice(-8).map((msg) => ({
      role: msg.role,
      content: msg.content,
    }));

    try {
      const data = await chat({ question: input.trim(), repo_name: activeRepository.repo_name, history: chatHistory }).unwrap();
      setMessages((prev) => [
        ...prev,
        { role: "user", content: input.trim() },
        {
          role: "assistant",
          content: data.answer,
          source: data.source,
        },
      ]);
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unknown error occurred");
      // Preserve the question so the user can retry without retyping.
    } finally {
      setLoading(false);
    }
  }, [input, messages, activeRepository, loading, chat]);

  const handleInputChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInput(event.target.value);
    },
    []
  );

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    } else if (event.key === "Enter" && event.shiftKey) {
      event.preventDefault();
      const textarea = event.currentTarget;
      const start = textarea.selectionStart ?? 0;
      const end = textarea.selectionEnd ?? 0;
      const value = textarea.value;
      const newValue = value.slice(0, start) + "\n" + value.slice(end);
      textarea.value = newValue;
      textarea.selectionStart = start + 1;
      textarea.selectionEnd = start + 1;
      setInput(newValue);
    }
  };

  const isDisabled = !activeRepository || loading || !input.trim();

  return (
    <div className="flex flex-col h-full">
      <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
        <div className="max-w-2xl mx-auto">
          <h1 className="atlas-display mb-2 text-xl font-semibold text-[var(--foreground)]">
            Chat
          </h1>
          <p className="mb-6 text-sm text-[var(--muted)]">
            Ask a question about the currently selected repository.
          </p>

          {/* Question input */}
          <div className="mb-4">
            <textarea
              id="question-input"
              placeholder="Ask a question about the selected repository"
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              disabled={loading || !activeRepository}
              rows={4}
              className="min-w-full rounded-[var(--radius-md)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--foreground)] placeholder:text-[var(--muted)] focus-visible:outline-none"
              aria-label="Question"
            />
          </div>

          <div className="flex items-center gap-3 mb-6">
            <Button
              type="button"
              onClick={handleSubmit}
              disabled={isDisabled}
              aria-label="Submit"
            >
              Submit
            </Button>
            {loading && (
              <span className="text-xs text-[var(--muted)]">Submitting…</span>
            )}
          </div>
          {/* Error state */}
          {error && (
            <p className="mb-4 text-sm text-[var(--error)]" role="alert">
              {error}
            </p>
          )}

          {/* Message list */}
          <ul className="mt-4 space-y-3 max-h-[60vh] overflow-y-auto border-t border-[var(--border)] p-2 bg-[var(--surface)] rounded-md">
            {messages.length === 0 && !loading && !error && (
              <p className="py-4 text-sm text-[var(--muted)] text-center">
                No conversation yet. Ask a question to get started.
              </p>
            )}
            {messages.map((msg, idx) => (
              <li key={idx} className="flex items-start space-y-2">
                <div className="flex-1 min-w-0">
                  <p
                    className={`mb-1 ${msg.role === "user" ? "text-right" : "text-left"}`}
                  >
                    {msg.content}
                  </p>
                  {msg.source && (
                    <span className="inline-block text-xs text-[var(--muted)] bg-[var(--surface-hover)] rounded px-1 py-0.5">
                      Answer source: {msg.source}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      </main>

      <aside className="w-full md:w-1/2 flex-shrink-0 bg-[var(--surface)] border-l border-[var(--border)] p-4 sm:p-6 lg:p-8">
        <div className="space-y-6">
          {/* Repository selector - always visible, even when no repository is selected */}
          <div>
            <h3 className="text-sm font-semibold text-[var(--muted)]">Repository</h3>
            <select
              id="repository-select"
              data-testid="repository-select"
              value={activeRepository?.repo_name ?? ""}
              onChange={(event) => {
                const repoName = event.target.value;
                const repository =
                  repositories.find((item) => item.repo_name === repoName) ??
                  null;
                if (repository) dispatch(selectRepository(repository.repo_name));
                else dispatch(clearRepository());
              }}
              className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] text-[var(--foreground)] text-sm px-3 py-2"
            >
              <option value="">Select a repository</option>
              {repositories.map((repository) => (
                <option key={repository.repo_name} value={repository.repo_name}>
                  {repository.repo_name} ({repository.points})
                </option>
              ))}
            </select>
            <p className="mt-1 text-[9px] text-[var(--muted)]">
              {activeRepository
                ? `Active: ${activeRepository.repo_name}`
                : "No repository selected — input is disabled"}
            </p>
          </div>

          {/* Connection status */}
          <div>
            <h3 className="text-sm font-semibold text-[var(--muted)]">Connection</h3>
            <p className="mt-1 text-[9px] text-[var(--muted)]">
              {activeRepository ? "Connected" : "No active repository"}
            </p>
          </div>
        </div>
      </aside>
    </div>
  );
}
