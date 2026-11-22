import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement>;

export function Button({ className, type = "button", ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex h-10 items-center justify-center gap-2 rounded-[var(--radius-md)] border border-[var(--border-strong)] bg-[var(--surface-raised)] px-3.5 text-xs font-medium text-[var(--foreground)] transition-colors hover:border-[var(--primary)] hover:bg-[var(--surface-hover)] disabled:cursor-wait disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export function IconButton({
  className,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      aria-label={props["aria-label"]}
      className={cn(
        "inline-flex size-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-raised)] text-[var(--muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--foreground)]",
        className,
      )}
      {...props}
    />
  );
}

export function Surface({
  className,
  children,
  as = "div",
  ...props
}: HTMLAttributes<HTMLDivElement> & { as?: "div" | "section" }) {
  const Element = as;
  return (
    <Element
      className={cn(
        "rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--surface)]",
        className,
      )}
      {...props}
    >
      {children}
    </Element>
  );
}

export function Badge({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[var(--radius-sm)] border border-[var(--border)] px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  id,
}: {
  eyebrow: string;
  title: string;
  id: string;
}) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">
        {eyebrow}
      </p>
      <h2
        id={id}
        className="atlas-display mt-2 text-lg font-semibold text-[var(--foreground)]"
      >
        {title}
      </h2>
    </div>
  );
}
