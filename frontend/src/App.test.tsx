import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { clearFixtureCache } from "./lib/raceFixtures";

/**
 * Phase 6.2's acceptance criterion is about the *app*, not the loader module:
 * "loading a driver fetches exactly one file." The loader's own unit test
 * proved the function does that; it did not prove anything reachable from
 * `main.tsx` calls it. That gap was real — the production build tree-shook the
 * loader entirely, emitting zero fixture assets — so it is asserted here,
 * through the rendered UI, by counting fetches.
 *
 * `fetch` is served from disk rather than stubbed with synthetic shapes, so
 * these tests fail if the generator's output stops matching what the UI reads.
 */

const FIXTURE_DIR = resolve(__dirname, "fixtures/races");
const originalFetch = globalThis.fetch;
let fetchSpy: ReturnType<typeof vi.fn>;

/** Vite resolves the glob to URLs like "/src/fixtures/races/X.json". */
function serveFromDisk(url: string) {
  const name = url.split("?")[0].split("/").pop()!;
  return JSON.parse(readFileSync(resolve(FIXTURE_DIR, name), "utf8"));
}

/** Filenames requested so far, so assertions can name what was fetched. */
function requested(): string[] {
  return fetchSpy.mock.calls.map((c) => String(c[0]).split("?")[0].split("/").pop()!);
}

beforeEach(() => {
  // The loader's cache is module-level, so without this an earlier test warms
  // the base file and the fetch-count assertions below see zero requests.
  clearFixtureCache();
  fetchSpy = vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => serveFromDisk(url),
  }));
  globalThis.fetch = fetchSpy as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("App", () => {
  it("renders the product name", () => {
    render(<App />);
    expect(screen.getByText(/PIT WALL MULTIVERSE/i)).toBeInTheDocument();
  });

  it("loads one base file and one driver file, and renders from them", async () => {
    render(<App />);

    // The header only fills in once the base file has arrived, so waiting on
    // it also asserts that the fetched payload is the shape the UI reads.
    await waitFor(() =>
      expect(screen.getByText(/Hungarian Grand Prix/)).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByText(/time the decision cost or saved/i)).toBeInTheDocument(),
    );

    // HAM, not VER: the opening driver is whoever has a defensible candidate.
    expect(requested().sort()).toEqual(["2019_hungarian__HAM.json", "2019_hungarian__base.json"]);
  });

  it("fetches exactly one additional file when the driver changes", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByText(/Hungarian Grand Prix/)).toBeInTheDocument());
    const before = fetchSpy.mock.calls.length;

    // A driver other than the one already open, so the fetch count is meaningful.
    await userEvent.selectOptions(screen.getByLabelText(/^driver$/i), "VER");
    await waitFor(() => expect(fetchSpy.mock.calls.length).toBe(before + 1));

    expect(requested().at(-1)).toBe("2019_hungarian__VER.json");
    // No re-fetch of the base file: the field data is shared across drivers.
    expect(requested().filter((n) => n.endsWith("__base.json"))).toHaveLength(1);
  });

  it("does not offer 'base' as a driver", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByText(/Hungarian Grand Prix/)).toBeInTheDocument());
    const options = within(screen.getByLabelText(/^driver$/i)).getAllByRole("option");
    expect(options.map((o) => o.textContent)).not.toContain("base");
    expect(options.length).toBeGreaterThanOrEqual(19);
  });

  it("opens on a defensible candidate rather than the biggest number", async () => {
    // The largest effect in VER's decision space is -52s from moving his lap-67
    // stop to lap 40, and it is an artifact: his SOFT degradation was fitted
    // from two laps and came out as exactly 0.0 s/lap. Opening there would
    // headline a broken number. The opening view must be a real counterfactual
    // that stays inside the model's evidence.
    render(<App />);
    await waitFor(() => expect(screen.getByText(/instead of lap/i)).toBeInTheDocument());

    // Not VER, who has no defensible candidate at Hungary at all: every way of
    // moving either of his stops runs his HARD stint to age 43 against the 42
    // he reached, or leans on a SOFT cell fitted from two laps. HAM does.
    expect((screen.getByLabelText(/^driver$/i) as HTMLSelectElement).value).toBe("HAM");
    // No caution is raised, because the opening candidate triggers none.
    expect(screen.queryByText(/past this race's plausibility bound/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/degradation was fitted from/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/extrapolation, not interpolation/i)).not.toBeInTheDocument();
  });

  it("names the cause when a candidate is an artifact, not just that it is one", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByText(/instead of lap/i)).toBeInTheDocument());

    // VER's lap-67 stop dragged to lap 1: 69 laps on a compound he ran twice,
    // so his own degradation is unfittable and the answer leans entirely on the
    // cross-driver pooled estimate. This used to be far worse — before the
    // degradation fallback chain was corrected, moving that stop to lap 40 alone
    // read -52s, because the cell had fallen through to a rate of exactly zero.
    // It now reads -16s and is inside the bound, which is why this test has to
    // reach for a genuinely extreme candidate to find a live artifact.
    await userEvent.selectOptions(screen.getByLabelText(/^driver$/i), "VER");
    await waitFor(() => expect(screen.getByLabelText(/stop to move/i)).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText(/stop to move/i), "67");
    await waitFor(() => expect(screen.getByRole("slider")).toBeInTheDocument());
    fireEvent.change(screen.getByRole("slider"), { target: { value: "1" } });

    await waitFor(() =>
      expect(screen.getByText(/past this race's plausibility bound/i)).toBeInTheDocument(),
    );
    // The cause, named: too few of his own laps, so the cell is pooled.
    expect(screen.getByText(/ran only 2 laps on the SOFT/i)).toBeInTheDocument();
    expect(screen.getByText(/cross-driver pooled estimate/i)).toBeInTheDocument();
  });

  it("splits the effect into pace and traffic rather than reporting one number", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByText(/instead of lap/i)).toBeInTheDocument());
    expect(screen.getByText(/net by the finish/i)).toBeInTheDocument();
    expect(screen.getByText(/of which pace/i)).toBeInTheDocument();
    expect(screen.getByText(/of which traffic/i)).toBeInTheDocument();
  });

  it("moving the pit lap re-reads a precomputed ensemble rather than recomputing", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByText(/instead of lap/i)).toBeInTheDocument());
    const before = fetchSpy.mock.calls.length;

    // Drive the slider by value rather than by keystroke: the assertion is
    // about where the ensemble comes from, not about range-input key handling.
    const slider = screen.getByRole("slider") as HTMLInputElement;
    const shown = () => screen.getByText(/pits on lap \d+/).textContent ?? "";
    const first = shown();
    fireEvent.change(slider, { target: { value: slider.min } });

    await waitFor(() => expect(shown()).not.toBe(first));
    // The whole decision space came in the driver's single file, so changing
    // the decision costs no network at all.
    expect(fetchSpy.mock.calls.length).toBe(before);
  });

  it("shows the field without needing any driver's candidate file", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByText(/Hungarian Grand Prix/)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /full field/i }));
    await waitFor(() =>
      expect(screen.getByText(/gap to leader — race as it happened/i)).toBeInTheDocument(),
    );
  });

  it("labels a race excluded from the gate aggregate instead of hiding it", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByText(/Hungarian Grand Prix/)).toBeInTheDocument());

    await userEvent.selectOptions(screen.getByLabelText(/^race$/i), "2019_monaco");
    await waitFor(() => expect(screen.getByText(/Monaco Grand Prix/)).toBeInTheDocument());
    // The caveat is stated in place; Monaco stays selectable.
    expect(screen.getByText(/Excluded from the Part 8.3 gate aggregate/)).toBeInTheDocument();
  });
});
