/**
 * MultiverseTree — Phase 7.
 *
 * Branches are anchored to the lap axis: a branch physically forks at the lap
 * its decision was taken, x is lap and y is finishing position. That is the only
 * layout considered that carries information rather than decoration — a radial
 * or indented tree would be legible but would say nothing about *when* the
 * timelines diverged, which is the whole subject.
 *
 * Depth is a data question, not a layout one; see `TreeLab` for the legibility
 * test and DECISIONS.md for what depth this fixture can actually support.
 */

export type TreeNode = {
  id: string;
  parentId: string | null;
  /** Lap the branch leaves its parent. The root uses lap 1. */
  divergenceLap: number;
  /** Finishing position this branch ends on. Labelled, not plotted — see below. */
  endPosition: number;
  label: string;
  /**
   * Net effect in seconds. This is the y coordinate.
   *
   * The first layout used finishing position for y, and it failed the depth-3
   * legibility test for a reason that also applies at depth 2: position is an
   * integer over ~20 values, so branches that finish in the same place land on
   * exactly the same line and both the paths and their labels overlap. Thirteen
   * nodes collapsed onto four rows.
   *
   * Net effect is continuous, so exact collisions are rare and near-collisions
   * are *meaningful* — two branches drawn close together really did cost the
   * same. It is also the variable the main chart plots, with reality at zero, so
   * the tree's y axis and the comparison view's y axis mean the same thing.
   */
  deltaS: number;
  /** Laps past observed tyre age; drives the caution shading. */
  extrapolatedLaps: number;
  /** Non-null when the answer is an artifact, and of what kind. */
  cause: "degenerateFit" | "traffic" | "extrapolation" | "unexplained" | null;
  /**
   * Branches that exist in principle but have no precomputed ensemble. Drawn as
   * a visible stub rather than omitted: a tree that silently stops is
   * indistinguishable from one that has nothing more to say.
   */
  unavailable?: boolean;
};

export type MultiverseTreeProps = {
  nodes: TreeNode[];
  totalLaps: number;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  height?: number;
};

const MARGIN = { top: 16, right: 108, bottom: 22, left: 34 };
const WIDTH = 760;

function cautionStroke(extrapolatedLaps: number, worst: number): string {
  if (extrapolatedLaps <= 0) return "#1A1917";
  const t = Math.min(1, extrapolatedLaps / Math.max(1, worst));
  return `rgba(168,118,31,${(0.45 + t * 0.55).toFixed(2)})`;
}

export default function MultiverseTree({
  nodes,
  totalLaps,
  selectedId,
  onSelect,
  height = 320,
}: MultiverseTreeProps) {
  if (nodes.length === 0) return null;

  const innerW = WIDTH - MARGIN.left - MARGIN.right;
  const innerH = height - MARGIN.top - MARGIN.bottom;
  const worst = Math.max(1, ...nodes.map((n) => n.extrapolatedLaps));

  // Symmetric about zero, so "reality" sits on the middle rule and gained time
  // reads above it. Floored so a set of near-identical branches is not blown up
  // to fill the height.
  const extent = Math.max(2, ...nodes.map((n) => Math.abs(n.deltaS)));
  const x = (lap: number) => ((lap - 1) / Math.max(1, totalLaps - 1)) * innerW;
  const y = (deltaS: number) => innerH / 2 + (deltaS / extent) * (innerH / 2 - 8);

  const byId = new Map(nodes.map((n) => [n.id, n]));

  /**
   * Label y positions, pushed apart where branches end close together.
   *
   * The paths may legitimately converge — two decisions really can cost the same
   * — but two labels drawn on top of each other are simply unreadable, and the
   * depth-3 test produced exactly that. The nudge is applied to the TEXT only,
   * never to the path, so the geometry keeps telling the truth.
   */
  const LABEL_MIN_GAP = 11;
  const labelY = new Map<string, number>();
  for (const node of [...nodes].sort((a, b) => y(a.deltaS) - y(b.deltaS))) {
    const wanted = y(node.deltaS);
    const last = [...labelY.values()].reduce((m, v) => Math.max(m, v), -Infinity);
    labelY.set(node.id, Number.isFinite(last) ? Math.max(wanted, last + LABEL_MIN_GAP) : wanted);
  }

  return (
    <figure className="m-0">
      <svg
        width={WIDTH}
        height={height}
        role="img"
        aria-label="Multiverse tree: each branch forks at the lap its decision was taken"
        className="block"
      >
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {/* Zero: reality. Same meaning as the comparison chart's zero rule. */}
          <line x1={0} x2={innerW} y1={y(0)} y2={y(0)} stroke="#1A1917" strokeWidth={1} opacity={0.25} />
          <text x={-6} y={y(0) + 3} textAnchor="end" className="font-mono" fontSize={9} fill="#1A1917" opacity={0.5}>
            0
          </text>
          <text x={-6} y={12} textAnchor="end" className="font-mono" fontSize={8} fill="#1A1917" opacity={0.35}>
            gained
          </text>
          <text x={-6} y={innerH} textAnchor="end" className="font-mono" fontSize={8} fill="#1A1917" opacity={0.35}>
            lost
          </text>

          {/* Lap gridlines, so a fork's x position is readable as a lap. */}
          {Array.from({ length: Math.floor(totalLaps / 10) + 1 }, (_, i) => i * 10)
            .filter((lap) => lap >= 1)
            .map((lap) => (
              <g key={lap}>
                <line x1={x(lap)} x2={x(lap)} y1={0} y2={innerH} stroke="#E8E4DA" strokeWidth={1} />
                <text
                  x={x(lap)}
                  y={innerH + 14}
                  textAnchor="middle"
                  className="font-mono"
                  fontSize={9}
                  fill="#1A1917"
                  opacity={0.45}
                >
                  {lap}
                </text>
              </g>
            ))}

          {nodes.map((node) => {
            const parent = node.parentId ? byId.get(node.parentId) : null;
            const x0 = parent ? x(node.divergenceLap) : x(1);
            const y0 = parent ? y(parent.deltaS) : y(node.deltaS);
            const x1 = x(totalLaps);
            const y1 = y(node.deltaS);
            const isRoot = node.parentId == null;
            const isSelected = node.id === selectedId;

            // An elbow rather than a curve: the fork lap must be readable off
            // the x axis, and a bezier smears it across several laps.
            const d = `M${x0},${y0} L${x0},${y1} L${x1},${y1}`;

            return (
              <g key={node.id}>
                <path
                  d={d}
                  fill="none"
                  stroke={
                    node.unavailable
                      ? "#C9C3B6"
                      : isRoot
                        ? "#1A1917"
                        : cautionStroke(node.extrapolatedLaps, worst)
                  }
                  strokeWidth={isRoot ? 2 : isSelected ? 2 : 1.25}
                  strokeDasharray={node.unavailable ? "2 3" : undefined}
                  opacity={node.unavailable ? 0.7 : 1}
                />
                {/* Fork marker at the divergence lap. */}
                {!isRoot && (
                  <circle
                    cx={x0}
                    cy={y0}
                    r={2.5}
                    fill="#F4F1EA"
                    stroke="#1A1917"
                    strokeWidth={1}
                  />
                )}
                {/* Traffic-driven branches get the same structural mark the small
                    multiples use, so the two panels agree on what a dot means. */}
                {node.cause === "traffic" && (
                  <circle cx={(x0 + x1) / 2} cy={y1} r={2} fill="#1A1917" />
                )}
                {/* Leader line, when the label had to be nudged off its branch. */}
                {Math.abs((labelY.get(node.id) ?? y1) - y1) > 1 && (
                  <line
                    x1={x1}
                    x2={x1 + 4}
                    y1={y1}
                    y2={labelY.get(node.id)}
                    stroke="#1A1917"
                    strokeWidth={0.5}
                    opacity={0.3}
                  />
                )}
                <text
                  x={x1 + 5}
                  y={(labelY.get(node.id) ?? y1) + 3}
                  className="font-mono"
                  fontSize={9}
                  fill={node.unavailable ? "#1A1917" : isRoot ? "#1A1917" : "#A33A2E"}
                  opacity={node.unavailable ? 0.45 : 1}
                  fontWeight={isSelected ? 600 : 400}
                  onClick={() => !node.unavailable && onSelect?.(node.id)}
                >
                  {node.label}
                </text>
                {/* Invisible hit area over the whole branch. */}
                {!node.unavailable && onSelect && (
                  <path
                    d={d}
                    fill="none"
                    stroke="transparent"
                    strokeWidth={10}
                    className="cursor-pointer"
                    onClick={() => onSelect(node.id)}
                  />
                )}
              </g>
            );
          })}
        </g>
      </svg>
    </figure>
  );
}
