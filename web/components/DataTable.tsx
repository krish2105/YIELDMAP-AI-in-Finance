"use client";

/**
 * A plain HTML table, in its own module.
 *
 * It used to live beside the charts, and five pages — developers, portfolio, data, evals and
 * security — import nothing else from that file. Sharing a module with the charting library meant
 * those pages shipped 4.4MB of it to render markup that needs none: a table is `<table>`, and the
 * import graph does not care that the code paths never met.
 */
export function DataTable({
  columns,
  rows,
  caption,
}: {
  columns: { key: string; label: string; align?: "left" | "right" }[];
  rows: Record<string, unknown>[];
  caption?: string;
}) {
  return (
    // tabindex and a role, because a region that scrolls must be focusable: without them a
    // keyboard user cannot scroll a wide table sideways, and the columns past the fold are
    // simply unreachable. axe flags this as `scrollable-region-focusable`.
    <div
      className="overflow-x-auto rounded-lg border border-line"
      tabIndex={0}
      role="region"
      aria-label={caption ?? "Data table"}
    >
      <table className="w-full text-xs">
        {caption ? <caption className="p-2 text-left text-ink-muted">{caption}</caption> : null}
        <thead className="bg-sunken">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`px-3 py-2 font-medium text-ink-secondary ${
                  column.align === "right" ? "text-right" : "text-left"
                }`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-line">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`px-3 py-1.5 text-ink-secondary ${
                    column.align === "right" ? "text-right" : "text-left"
                  }`}
                >
                  {row[column.key] === null || row[column.key] === undefined
                    ? "—"
                    : String(row[column.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
