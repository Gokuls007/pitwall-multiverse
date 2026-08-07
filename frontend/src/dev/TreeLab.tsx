/**
 * TreeLab — a dev-only harness for testing `MultiverseTree`'s legibility at
 * depths this project may or may not ship.
 *
 * Spec 7: "Test legibility with dummy data at depth 3+ before committing to a
 * layout." The point is to find out whether the layout survives a depth *before*
 * building data for it — if it cannot stay readable at depth 3, that settles the
 * question without a single extra simulation.
 *
 * Reachable at `?treelab` only. Deliberately not wired into the app: it renders
 * fabricated numbers, and fabricated numbers must never be one state change away
 * from the real interface.
 */

import { useState } from "react";
import MultiverseTree, { type TreeNode } from "../components/MultiverseTree";

const TOTAL_LAPS = 70;

/**
 * A synthetic tree with a given depth and branching factor.
 *
 * Fan-out is deliberately generous relative to what the fixture could support,
 * because the question is whether the *layout* holds, not whether this data does.
 */
function buildDummy(depth: number, branching: number): TreeNode[] {
  const nodes: TreeNode[] = [
    {
      id: "root",
      parentId: null,
      divergenceLap: 1,
      endPosition: 1,
      label: "reality",
      deltaS: 0,
      extrapolatedLaps: 0,
      cause: null,
    },
  ];

  let frontier = ["root"];
  for (let level = 1; level <= depth; level += 1) {
    const next: string[] = [];
    for (const parentId of frontier) {
      const parent = nodes.find((n) => n.id === parentId)!;
      for (let i = 0; i < branching; i += 1) {
        const id = `${parentId}.${i}`;
        // Each level forks later than its parent, as a real second decision must.
        const divergenceLap = Math.min(
          TOTAL_LAPS - 2,
          parent.divergenceLap + 12 + level * 4 + i * 2,
        );
        // Positions spread out with depth, which is the pessimistic case for
        // label collision.
        const endPosition = Math.max(
          1,
          Math.min(20, parent.endPosition + (i - (branching - 1) / 2) * (4 / level)),
        );
        // Extrapolation compounds with depth — the honest expectation, and the
        // thing that decides whether depth is worth building.
        const extrapolatedLaps = level === 1 ? i * 3 : 8 + level * 6 + i * 2;
        nodes.push({
          id,
          parentId,
          divergenceLap,
          endPosition,
          label: `L${divergenceLap} P${endPosition.toFixed(0)}`,
          deltaS: parent.deltaS + (i - (branching - 1) / 2) * (6 / level) + level * 1.5,
          extrapolatedLaps,
          cause: extrapolatedLaps > 0 ? "extrapolation" : null,
          unavailable: level === depth && i === branching - 1,
        });
        next.push(id);
      }
    }
    frontier = next;
  }
  return nodes;
}

export default function TreeLab() {
  const [depth, setDepth] = useState(3);
  const [branching, setBranching] = useState(3);
  const nodes = buildDummy(depth, branching);

  return (
    <main className="mx-auto min-h-screen max-w-[1100px] px-6 py-6">
      <h1 className="font-sans text-lg font-semibold uppercase tracking-[0.14em]">
        Tree layout lab — dummy data
      </h1>
      <p className="mt-1 max-w-prose font-serif text-[0.9rem] italic leading-snug text-caution">
        Every number on this page is fabricated. It exists to test whether the layout
        stays legible at a depth, not to say anything about a race.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-4 font-mono text-micro">
        <label className="flex items-center gap-2">
          depth
          <input
            type="range"
            min={1}
            max={4}
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
          />
          <output className="w-4">{depth}</output>
        </label>
        <label className="flex items-center gap-2">
          branching
          <input
            type="range"
            min={2}
            max={20}
            value={branching}
            onChange={(e) => setBranching(Number(e.target.value))}
          />
          <output className="w-4">{branching}</output>
        </label>
        <span className="text-ink/60">{nodes.length} nodes</span>
      </div>

      <div className="mt-4">
        <MultiverseTree nodes={nodes} totalLaps={TOTAL_LAPS} height={420} />
      </div>
    </main>
  );
}
