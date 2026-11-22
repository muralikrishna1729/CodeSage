"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode, FormEvent, KeyboardEvent } from "react";
import {
  ArrowUp,
  Bot,
  Copy,
  LoaderCircle,
  Menu,
  MessageSquare,
  PanelRight,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { clearRepository, selectRepository } from "@/lib/features/repository/repositorySlice";
import { selectActiveRepository, selectRepositories } from "@/lib/features/repository/repositorySelectors";
import {
  useChatMutation,
  useGetRepositoriesQuery,
  type ChatResponse,
  type ChatSource,
} from "@/lib/services/codesageApi";
import { Button } from "@/components/ui/primitives";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  source?: ChatResponse["source"];
};

const suggestedQuestions = [
  "How is the API structured?",
  "Trace the repository ingestion flow",
  "How does a chat request reach LangGraph?",
];

function copyText(value: string): void {
  if (typeof navigator !== "undefined" && navigator.clipboard) {
    void navigator.clipboard.writeText(value).catch(() => undefined);
  }
}

function renderInlineMarkdown(value: string): ReactNode[] {
  const delimiter = String.fromCharCode(96);
  const pattern = new RegExp(
    "(" + delimiter + "[^" + delimiter + "]+" + delimiter + "|\\*\\*[^*]+\\*\\*)",
    "g",
  );

  return value.split(pattern).map((part, index) => {
    if (part.startsWith(delimiter) && part.endsWith(delimiter)) {
      return (
        <code
          key={index}
          className="atlas-mono rounded bg-[var(--surface-hover)] px-1.5 py-0.5 text-[0.9em] text-[var(--primary-strong)]"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index} className="font-semibold text-[var(--foreground)]">{part.slice(2, -2)}</strong>;
    }
    return <span key={index}>{part}</span>;
  });
}

function renderTextBlocks(value: string, prefix: string): ReactNode[] {
  return value
    .trim()
    .split(/\n\s*\n/)
    .filter(Boolean)
    .map((block, index) => {
      const lines = block.split("\n");
      const key = prefix + "-" + index;

      if (lines.every((line) => line.trim().startsWith("- "))) {
        return (
          <ul key={key} className="my-2 list-disc space-y-1 pl-5 text-sm leading-7 text-[var(--muted-strong)]">
            {lines.map((line, lineIndex) => (
              <li key={lineIndex}>{renderInlineMarkdown(line.trim().slice(2))}</li>
            ))}
          </ul>
        );
      }

      if (lines.length === 1 && /^#{1,3}\s/.test(lines[0])) {
        const heading = lines[0].replace(/^#{1,3}\s/, "");
        return (
          <h3 key={key} className="atlas-display mb-2 mt-4 text-base font-semibold text-[var(--foreground)]">
            {renderInlineMarkdown(heading)}
          </h3>
        );
      }

      return (
        <p key={key} className="my-2 whitespace-pre-wrap text-sm leading-7 text-[var(--muted-strong)]">
          {lines.map((line, lineIndex) => (
            <span key={lineIndex}>
              {lineIndex > 0 && <br />}
              {renderInlineMarkdown(line)}
            </span>
          ))}
        </p>
      );
    });
}

function AssistantAnswer({ content }: { content: string }) {
  const fence = String.fromCharCode(96).repeat(3);
  const codeBlockPattern = new RegExp(
    fence + "([a-zA-Z0-9_+-]*)[ \t]*\r?\n([\s\S]*?)" + fence,
    "g",
  );
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  let blockIndex = 0;

  while ((match = codeBlockPattern.exec(content)) !== null) {
    if (match.index > cursor) {
      nodes.push(...renderTextBlocks(content.slice(cursor, match.index), "text-" + blockIndex));
    }

    const language = match[1] || "code";
    const code = match[2].replace(/\n$/, "");
    nodes.push(
      <div
        key={"code-" + blockIndex}
        className="my-4 overflow-hidden rounded-xl border border-[var(--border-strong)] bg-[#151a17] text-[#e6ece6]"
      >
        <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
          <span className="atlas-mono text-[10px] uppercase tracking-[0.14em] text-[#a6b7aa]">
            {language}
          </span>
          <button
            type="button"
            onClick={() => copyText(code)}
            className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-[10px] text-[#c9d5cc] transition-colors hover:bg-white/10"
            aria-label="Copy code"
          >
            <Copy size={12} aria-hidden="true" />
            Copy
          </button>
        </div>
        <pre className="overflow-x-auto p-4 text-xs leading-6">
          <code className="atlas-mono">{code}</code>
        </pre>
      </div>,
    );
    cursor = codeBlockPattern.lastIndex;
    blockIndex += 1;
  }

  if (cursor < content.length) {
    nodes.push(...renderTextBlocks(content.slice(cursor), "text-" + blockIndex));
  }

  return <div className="min-w-0">{nodes}</div>;
}

function getChatError(error: unknown): string {
  if (
    typeof error === "object" &&
    error !== null &&
    "data" in error &&
    typeof error.data === "object" &&
    error.data !== null &&
    "error" in error.data &&
    typeof error.data.error === "string"
  ) {
    return error.data.error;
  }
  if (error instanceof Error && error.message) return error.message;
  return "The request could not be completed. Check the backend and try again.";
}

export function ChatWorkspace({
  onAssistantAnswer,
}: {
  onAssistantAnswer: (answer: string | null, source: ChatSource | null) => void;
  onOpenNavigation: () => void;
  onOpenInspector: () => void;
}) {
  const dispatch = useAppDispatch();
  const repositories = useAppSelector(selectRepositories);
  const activeRepository = useAppSelector(selectActiveRepository);
  const repositoriesQuery = useGetRepositoriesQuery();
  const [chat] = useChatMutation();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const conversationRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const conversation = conversationRef.current;
    if (conversation) {
      conversation.scrollTo({
        top: conversation.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [messages, loading]);

  const handleSubmit = useCallback(async () => {
    const question = input.trim();
    if (loading || !question || !activeRepository) return;

    setLoading(true);
    setError(null);
    const history = messages.slice(-8).map((message) => ({
      role: message.role,
      content: message.content,
    }));

    try {
      const response = await chat({
        question,
        repo_name: activeRepository.repo_name,
        history,
      }).unwrap();

      setMessages((current) => [
        ...current,
        { role: "user", content: question },
        {
          role: "assistant",
          content: response.answer,
          source: response.source,
        },
      ]);
      onAssistantAnswer(response.answer, response.source);
      setInput("");
    } catch (requestError) {
      setError(getChatError(requestError));
    } finally {
      setLoading(false);
    }
  }, [activeRepository, chat, input, loading, messages, onAssistantAnswer]);

  function submitForm(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    void handleSubmit();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSubmit();
    }
  }

  const canSubmit = Boolean(activeRepository && input.trim() && !loading);
  const repositoryLoading = repositoriesQuery.isLoading;

  return (
    <main className="flex min-h-screen min-w-0 flex-1 flex-col">
      <div className="mx-auto flex h-screen max-h-screen w-full max-w-[1120px] min-w-0 flex-col px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        <header className="flex flex-col gap-4 border-b border-[var(--border)] pb-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex shrink-0 gap-1 xl:hidden">
              <Button
                onClick={onOpenNavigation}
                aria-label="Open repository navigation"
                className="size-9 px-0"
              >
                <Menu size={15} aria-hidden="true" />
              </Button>
              <Button
                onClick={onOpenInspector}
                aria-label="Open contextual inspector"
                className="size-9 px-0"
              >
                <PanelRight size={15} aria-hidden="true" />
              </Button>
            </div>
            <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--primary)]">
              Code intelligence workspace
            </p>
            <h1 className="atlas-display mt-2 text-2xl font-semibold tracking-tight text-[var(--foreground)] sm:text-3xl">
              Chat with your codebase
            </h1>
            <p className="mt-1.5 text-xs leading-relaxed text-[var(--muted)] sm:text-sm">
              Ask questions. Trace execution. Understand unfamiliar code.
            </p>
            </div>
          </div>

          <div className="w-full sm:max-w-[270px]">
            <label
              htmlFor="repository-select"
              className="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.15em] text-[var(--muted)]"
            >
              Repository context
            </label>
            <select
              id="repository-select"
              data-testid="repository-select"
              value={activeRepository?.repo_name ?? ""}
              onChange={(event) => {
                const selected = repositories.find(
                  (repository) => repository.repo_name === event.target.value,
                );
                if (selected) dispatch(selectRepository(selected.repo_name));
                else dispatch(clearRepository());
                setMessages([]);
                setError(null);
                onAssistantAnswer(null, null);
              }}
              disabled={repositoryLoading || repositories.length === 0}
              className="h-10 w-full rounded-[var(--radius-md)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 text-xs text-[var(--foreground)] outline-none transition-colors focus:border-[var(--primary)] disabled:opacity-60"
            >
              <option value="">Select a repository</option>
              {repositories.map((repository) => (
                <option key={repository.repo_name} value={repository.repo_name}>
                  {repository.repo_name} · {repository.points.toLocaleString()} points
                </option>
              ))}
            </select>
            <p className="mt-1 text-[10px] text-[var(--muted)]">
              {activeRepository
                ? "Active: " + activeRepository.repo_name
                : "No repository selected"}
            </p>
          </div>
        </header>

        <section
          className="flex min-h-0 flex-1 flex-col"
          aria-label="Codebase conversation"
        >
          <div
            ref={conversationRef}
            role="log"
            aria-label="Conversation"
            aria-live="polite"
            className="min-h-0 flex-1 overflow-y-auto py-5 sm:py-7"
          >
            {messages.length === 0 && !loading ? (
              <div className="mx-auto flex min-h-full max-w-2xl flex-col justify-center py-8">
                <div className="mx-auto flex size-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--primary)] shadow-sm">
                  <Sparkles size={21} strokeWidth={1.6} aria-hidden="true" />
                </div>
                <h2 className="atlas-display mt-5 text-center text-xl font-semibold text-[var(--foreground)] sm:text-2xl">
                  What would you like to understand?
                </h2>
                <p className="mx-auto mt-2 max-w-md text-center text-sm leading-6 text-[var(--muted)]">
                  CodeSage will use the selected repository to ground its answer in your code.
                </p>

                {activeRepository ? (
                  <div className="mt-7 grid gap-2 sm:grid-cols-3">
                    {suggestedQuestions.map((question) => (
                      <button
                        key={question}
                        type="button"
                        onClick={() => setInput(question)}
                        className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 text-left text-xs leading-5 text-[var(--muted-strong)] transition-colors hover:border-[var(--primary)] hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)]"
                      >
                        <MessageSquare size={14} className="mb-2 text-[var(--primary)]" aria-hidden="true" />
                        {question}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="mt-7 rounded-xl border border-dashed border-[var(--border-strong)] bg-[var(--surface)] px-4 py-5 text-center">
                    <p className="text-sm font-medium text-[var(--foreground)]">
                      {repositoryLoading ? "Loading indexed repositories…" : "No repository selected"}
                    </p>
                    <p className="mt-1 text-xs text-[var(--muted)]">
                      {repositories.length > 0
                        ? "Choose a repository from the selector above or the sidebar."
                        : "Index a GitHub repository from the Overview page to start chatting."}
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className="mx-auto flex max-w-3xl flex-col gap-6">
                {messages.map((message, index) => (
                  <article
                    key={index}
                    className={message.role === "user" ? "ml-auto flex w-full max-w-[88%] items-start justify-end gap-3 sm:max-w-[82%]" : "flex w-full items-start gap-3"}
                  >
                    {message.role === "assistant" && (
                      <span className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--primary-soft)] text-[var(--primary)]">
                        <Bot size={16} aria-hidden="true" />
                      </span>
                    )}

                    <div
                      className={
                        message.role === "user"
                          ? "min-w-0 rounded-2xl rounded-tr-md border border-[var(--primary)]/20 bg-[var(--primary-soft)] px-4 py-3.5"
                          : "min-w-0 flex-1 rounded-2xl rounded-tl-md border border-[var(--border)] bg-[var(--surface)] px-4 py-3.5 sm:px-5"
                      }
                    >
                      <div className="mb-2 flex items-center justify-between gap-3">
                        <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-[var(--muted)]">
                          {message.role === "user" ? "You" : "CodeSage"}
                        </span>
                        {message.role === "assistant" && (
                          <div className="flex items-center gap-2">
                            {message.source && (
                              <span className="rounded-full border border-[var(--border)] bg-[var(--surface-raised)] px-2 py-1 text-[9px] font-medium text-[var(--muted)]">
                                Answer source: {message.source}
                              </span>
                            )}
                            <button
                              type="button"
                              onClick={() => copyText(message.content)}
                              aria-label="Copy assistant answer"
                              title="Copy answer"
                              className="rounded-md p-1.5 text-[var(--muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--foreground)]"
                            >
                              <Copy size={13} aria-hidden="true" />
                            </button>
                          </div>
                        )}
                      </div>
                      {message.role === "assistant" ? (
                        <AssistantAnswer content={message.content} />
                      ) : (
                        <p className="whitespace-pre-wrap text-sm leading-7 text-[var(--foreground)]">
                          {message.content}
                        </p>
                      )}
                    </div>

                    {message.role === "user" && (
                      <span className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface)] text-[var(--muted)]">
                        <UserRound size={15} aria-hidden="true" />
                      </span>
                    )}
                  </article>
                ))}

                {loading && (
                  <div className="flex items-start gap-3" aria-label="CodeSage is thinking">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--primary-soft)] text-[var(--primary)]">
                      <Bot size={16} aria-hidden="true" />
                    </span>
                    <div className="rounded-2xl rounded-tl-md border border-[var(--border)] bg-[var(--surface)] px-4 py-3.5">
                      <span className="flex items-center gap-2 text-xs text-[var(--muted)]">
                        <LoaderCircle size={14} className="animate-spin" aria-hidden="true" />
                        Analyzing repository context…
                      </span>
                    </div>
                  </div>
                )}
                <div aria-hidden="true" />
              </div>
            )}
          </div>

          <div className="shrink-0 border-t border-[var(--border)] bg-[var(--background)] pb-1 pt-4">
            {error && (
              <div role="alert" className="mx-auto mb-3 flex max-w-3xl items-start gap-2 rounded-lg border border-[var(--warning)] bg-[var(--warning-soft)] px-3 py-2.5 text-xs text-[var(--foreground)]">
                <span className="min-w-0 flex-1">{error}</span>
                <button
                  type="button"
                  onClick={() => setError(null)}
                  aria-label="Dismiss error"
                  className="shrink-0 text-[var(--muted)] hover:text-[var(--foreground)]"
                >
                  ×
                </button>
              </div>
            )}

            <form
              onSubmit={submitForm}
              className="mx-auto max-w-3xl rounded-2xl border border-[var(--border-strong)] bg-[var(--surface)] p-2 shadow-[0_8px_30px_var(--shadow)] focus-within:border-[var(--primary)]"
            >
              <textarea
                id="question-input"
                placeholder="Ask a question about the selected repository"
                aria-label="Question"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                disabled={!activeRepository || loading}
                rows={2}
                className="max-h-40 min-h-16 w-full resize-y border-0 bg-transparent px-3 py-2 text-sm leading-6 text-[var(--foreground)] outline-none placeholder:text-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-60"
              />
              <div className="flex items-center justify-between gap-3 px-2 pb-1">
                <span className="text-[10px] text-[var(--muted)]">
                  Enter to send · Shift + Enter for a new line
                </span>
                <Button
                  type="submit"
                  aria-label="Submit question"
                  disabled={!canSubmit}
                  className="h-9 rounded-xl border-[var(--primary)] bg-[var(--primary)] px-3.5 text-[var(--background)] hover:bg-[var(--primary-strong)]"
                >
                  {loading ? (
                    <LoaderCircle size={14} className="animate-spin" aria-hidden="true" />
                  ) : (
                    <ArrowUp size={15} aria-hidden="true" />
                  )}
                  <span>Send</span>
                </Button>
              </div>
            </form>
            <p className="mx-auto mt-2 max-w-3xl text-center text-[9px] text-[var(--muted)]">
              Answers are generated from the selected repository and may need verification against source code.
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}
