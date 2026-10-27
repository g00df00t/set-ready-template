// Shown when a page's primary data fails to load, instead of leaving the user
// on a blank/empty screen or an infinite skeleton. Gives a clear message and a
// retry, so a transient backend/network blip is recoverable.
export function LoadError({
  message = "Something went wrong loading this.",
  onRetry,
}: {
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="card p-8 text-center space-y-3"
      style={{ borderColor: "var(--border)" }}
    >
      <p className="text-sm" style={{ color: "var(--text-primary)" }}>{message}</p>
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        Check your connection and try again.
      </p>
      {onRetry && (
        <button onClick={onRetry} className="btn btn-secondary btn-sm">Retry</button>
      )}
    </div>
  );
}
