// Monospace, tabular-nums date/day-count text — so a column of them lines up.
// See jobDates.formatSpan for what produces the string this wraps.

export function DateText({ children, muted, className = "" }: {
  children: React.ReactNode;
  muted?: boolean;
  className?: string;
}) {
  return (
    <span
      className={`date-text ${className}`}
      style={muted ? { color: "var(--text-muted)", fontSize: "0.6875rem" } : undefined}
    >
      {children}
    </span>
  );
}
