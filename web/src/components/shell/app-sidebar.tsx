import Link from "next/link";
import {
  Activity,
  Code2,
  Database,
  LayoutDashboard,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { ThemeControl } from "./theme-control";
import type { DashboardResource, Repository } from "@/components/dashboard/dashboard-types";
import { Button } from "@/components/ui/primitives";

const navigation: {
  label: string;
  href: string;
  icon: LucideIcon;
  active?: boolean;
}[] = [
  {
    label: "Overview",
    href: "#overview",
    icon: LayoutDashboard,
    active: true,
  },
  { label: "Repositories", href: "#repositories", icon: Database },
  { label: "Metrics", href: "#metrics", icon: Activity },
];

export function AppSidebar({
  repositories,
  loading,
  activeRepository,
  onSelectRepository,
  onClose,
  drawer = false,
}: {
  repositories: DashboardResource<Repository[]> | null;
  loading: boolean;
  activeRepository: Repository | null;
  onSelectRepository: (repository: Repository) => void;
  onClose?: () => void;
  drawer?: boolean;
}) {
  const repositoryItems =
    repositories?.status === "success" ? repositories.data : [];

  return (
    <aside
      aria-label="Repository navigation"
      className={
        drawer
          ? "flex h-full w-[280px] flex-col border-r border-[var(--border)] bg-[var(--surface)] px-4 py-5"
          : "sticky top-0 hidden h-screen w-[244px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)] px-4 py-5 xl:flex"
      }
    >
      {drawer && (
        <Button
          onClick={onClose}
          aria-label="Close repository navigation"
          className="mb-4 self-end"
        >
          <X aria-hidden="true" size={15} />
        </Button>
      )}
      <Link
        href="#overview"
        aria-label="CodeSage workspace home"
        className="flex w-fit items-center gap-3 rounded-xl outline-none transition-opacity hover:opacity-80"
      >
        <span className="flex size-10 items-center justify-center rounded-xl border border-[var(--border-strong)] bg-[var(--primary-soft)] text-[var(--primary)]">
          <Code2 aria-hidden="true" size={20} strokeWidth={1.8} />
        </span>
        <span>
          <span className="atlas-display block text-[15px] font-semibold text-[var(--foreground)]">
            CodeSage
          </span>
          <span className="mt-0.5 block text-[10px] font-medium uppercase tracking-[0.18em] text-[var(--muted)]">
            Code intelligence
          </span>
        </span>
      </Link>

      <div className="mt-7 flex items-center justify-between lg:mt-10">
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--muted)]">
          Workspace
        </p>
        <span className="atlas-mono rounded-md border border-[var(--border)] px-1.5 py-0.5 text-[9px] text-[var(--muted)]">
          LOCAL
        </span>
      </div>

      <nav
        aria-label="Workspace navigation"
        className="mt-3 flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0"
      >
        {navigation.map(({ label, href, icon: Icon, active }) => (
          <Link
            key={label}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex shrink-0 items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] transition-colors focus-visible:outline-none",
              active
                ? "bg-[var(--surface-hover)] text-[var(--foreground)]"
                : "text-[var(--muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--foreground)]",
            )}
          >
            <Icon
              aria-hidden="true"
              size={17}
              strokeWidth={1.8}
              className={active ? "text-[var(--primary)]" : ""}
            />
            <span>{label}</span>
          </Link>
        ))}
      </nav>

      <div className="mt-6 border-t border-[var(--border)] pt-5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--muted)]">
          Repositories
        </p>
        <div className="mt-3 space-y-1">
          {loading ? (
            <p className="py-2 text-xs text-[var(--muted)]" aria-live="polite">
              Loading repositories...
            </p>
          ) : repositories?.status === "error" ? (
            <p className="text-xs leading-relaxed text-[var(--muted)]">
              Repository data unavailable.
            </p>
          ) : repositoryItems.length === 0 ? (
            <p className="text-xs leading-relaxed text-[var(--muted)]">
              No repositories indexed.
            </p>
          ) : (
            repositoryItems.map((repository) => {
              const active =
                activeRepository?.repo_name === repository.repo_name;
              return (
                <button
                  type="button"
                  key={repository.repo_name}
                  aria-label={`Select ${repository.repo_name}`}
                  aria-pressed={active}
                  onClick={() => onSelectRepository(repository)}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded-[var(--radius-md)] border px-2.5 py-2 text-left transition-colors",
                    active
                      ? "border-[var(--border-strong)] bg-[var(--surface-hover)]"
                      : "border-transparent hover:border-[var(--border)] hover:bg-[var(--surface-raised)]",
                  )}
                >
                  <span className="atlas-mono min-w-0 truncate text-[11px] text-[var(--foreground)]">
                    {repository.repo_name}
                  </span>
                  <span className="text-[9px] tabular-nums text-[var(--muted)]">
                    {repository.points}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </div>

      <div className="mt-5 flex items-center justify-between rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-raised)] p-3 lg:mt-auto">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-medium text-[var(--muted-strong)]">
            <span className="size-1.5 rounded-full bg-[var(--muted)]" />
            Server-side connection
          </div>
          <p className="mt-1 text-[10px] leading-relaxed text-[var(--muted)]">
            Deployment access boundary
          </p>
        </div>
        <ThemeControl />
      </div>
    </aside>
  );
}
