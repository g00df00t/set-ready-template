export function Skeleton({ width = "100%", height = "1rem", className = "" }: {
  width?: string;
  height?: string;
  className?: string;
}) {
  return (
    <div
      className={`animate-pulse rounded ${className}`}
      style={{ width, height, background: "var(--bg-elevated)" }}
    />
  );
}

/* Placeholders shaped like the three ways a project page renders its data,
 * built from the real .data-table/.card classes rather than approximated
 * with plain divs — so a page's loading state has the same row height and
 * borders as what replaces it, instead of a jump when the real content lands. */

export function TableSkeleton({ columns = 6, rows = 4 }: { columns?: number; rows?: number }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          {Array.from({ length: columns }).map((_, i) => (
            <th key={i}><Skeleton width="60%" height="0.6rem" /></th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }).map((_, r) => (
          <tr key={r}>
            {Array.from({ length: columns }).map((_, c) => (
              <td key={c}><Skeleton width={c === 0 ? "75%" : "45%"} height="0.875rem" /></td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function CardListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="card px-4 py-3 flex items-center gap-3">
          <Skeleton width="30%" height="0.875rem" />
          <Skeleton width="20%" height="0.75rem" />
        </div>
      ))}
    </div>
  );
}

export function FormCardSkeleton({ blocks = 1, fields = 2 }: { blocks?: number; fields?: number }) {
  return (
    <div className="space-y-4">
      {Array.from({ length: blocks }).map((_, i) => (
        <div key={i} className="card p-5 space-y-4">
          <Skeleton width="20%" height="0.65rem" />
          <div className="grid grid-cols-2 gap-4">
            {Array.from({ length: fields }).map((_, f) => (
              <Skeleton key={f} height="2.25rem" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
