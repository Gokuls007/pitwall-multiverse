import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
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
    // Phase 6.3 retired the range input; the control is the pit tick, driven
    // here by keyboard because jsdom has no real pointer geometry.
    await waitFor(() => expect(screen.getByTestId("pit-tick")).toBeInTheDocument());
    screen.getByTestId("pit-tick").focus();
    await userEvent.keyboard("{Home}");

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

    const shown = () => screen.getByText(/pits on lap \d+/).textContent ?? "";
    const first = shown();
    screen.getByTestId("pit-tick").focus();
    await userEvent.keyboard("{ArrowLeft}");

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

describe("the pit stop as the control (Phase 6.3)", () => {
  it("exposes the tick as a slider carrying the teaching sentence, not a number", async () => {
    // The spec requires `aria-valuetext` to be the preview sentence: a screen
    // reader dragging this should hear the consequence of the decision, not the
    // coordinate it landed on.
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("pit-tick")).toBeInTheDocument());

    const tick = screen.getByTestId("pit-tick");
    expect(tick).toHaveAttribute("role", "slider");
    expect(tick).toHaveAttribute("tabindex", "0");
    const valueText = tick.getAttribute("aria-valuetext") ?? "";
    expect(valueText).toMatch(/lap \d+/i);
    expect(valueText).toMatch(/stint on/i);
    // Bounds come from the discovered valid range, not from 1..totalLaps.
    expect(Number(tick.getAttribute("aria-valuemin"))).toBeGreaterThanOrEqual(1);
    expect(Number(tick.getAttribute("aria-valuenow"))).toBeGreaterThan(0);
  });

  it("steps by candidate, and Home/End reach the range bounds", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("pit-tick")).toBeInTheDocument());
    const now = () => Number(screen.getByTestId("pit-tick").getAttribute("aria-valuenow"));
    const min = Number(screen.getByTestId("pit-tick").getAttribute("aria-valuemin"));
    const max = Number(screen.getByTestId("pit-tick").getAttribute("aria-valuemax"));

    screen.getByTestId("pit-tick").focus();
    const start = now();
    await userEvent.keyboard("{ArrowLeft}");
    await waitFor(() => expect(now()).toBeLessThan(start));

    await userEvent.keyboard("{End}");
    await waitFor(() => expect(now()).toBe(max));
    await userEvent.keyboard("{Home}");
    await waitFor(() => expect(now()).toBe(min));

    // Shift steps five candidates, not one.
    const atMin = now();
    await userEvent.keyboard("{Shift>}{ArrowRight}{/Shift}");
    await waitFor(() => expect(now()).toBeGreaterThan(atMin));
    const afterShift = now();
    await userEvent.keyboard("{Home}");
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(now()).toBeLessThan(afterShift));
  });

  it("never lands on a lap with no precomputed ensemble behind it", async () => {
    // The discovered valid range has holes — a candidate that would push a stint
    // past the following real stop is refused — so stepping must move by
    // candidate rather than by integer lap. If it stepped by integer, the handle
    // could sit on a lap with nothing to render and the chart would blank.
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("pit-tick")).toBeInTheDocument());
    screen.getByTestId("pit-tick").focus();

    for (let i = 0; i < 12; i += 1) {
      await userEvent.keyboard("{ArrowLeft}");
      // The preview sentence only renders from a loaded candidate, so its
      // presence is the assertion that the lap resolved to one.
      expect(screen.getByText(/pits on lap \d+/)).toBeInTheDocument();
    }
  });

  it("keeps the real-lap marker visible even when the tick is dragged far away", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("pit-tick")).toBeInTheDocument());
    screen.getByTestId("pit-tick").focus();
    await userEvent.keyboard("{Home}");

    // The zero-extrapolation point must stay on screen throughout: it is where
    // the user departed from the evidence.
    const timeline = screen.getByLabelText(/stint and compound timeline/i);
    const marks = [...timeline.querySelectorAll("text")].map((t) => t.textContent);
    expect(marks).toContain("real");
  });

  it("has retired the range input", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("pit-tick")).toBeInTheDocument());
    expect(document.querySelector('input[type="range"]')).toBeNull();
    // RESET TO REAL is explicitly retained.
    expect(screen.getByRole("button", { name: /reset to real/i })).toBeInTheDocument();
  });
});

describe("lap scrubbing under prefers-reduced-motion", () => {
  // Playback must be absent, not present-and-inert: an auto-advancing playhead is
  // exactly the unrequested motion the setting exists to refuse. The playhead
  // itself stays fully usable by drag and keyboard.
  beforeEach(() => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      onchange: null,
      dispatchEvent: () => false,
    }));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("removes the play control but keeps the playhead operable", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("playhead")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /^play$/i })).not.toBeInTheDocument();

    screen.getByTestId("playhead").focus();
    await userEvent.keyboard("{Home}");
    await waitFor(() => expect(screen.getByText(/order on lap/i)).toBeInTheDocument());
  });
});

describe("lap scrubbing (Phase 6.4)", () => {
  it("parks on the whole race until scrubbed, then reads an order off stored state", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("playhead")).toBeInTheDocument());

    // Parked: the finish-order distribution is shown, not a single lap's order.
    expect(screen.getByText(/real vs alternate/i)).toBeInTheDocument();
    expect(screen.queryByText(/^Order on lap/i)).not.toBeInTheDocument();

    screen.getByTestId("playhead").focus();
    await userEvent.keyboard("{Home}");
    await waitFor(() => expect(screen.getByText(/order on lap/i)).toBeInTheDocument());

    // The order is a plain list of positions at that lap, and the caption says
    // where it came from — the whole point of 6.4 is that it isn't interpolated.
    expect(screen.getByText(/read from the lap record/i)).toBeInTheDocument();
    // Full field, so it is the real order rather than a partial reconstruction.
    const items = screen.getAllByRole("listitem");
    expect(items.length).toBeGreaterThanOrEqual(19);
  });

  it("does not invent an alternate order for drivers whose positions aren't stored", async () => {
    // Only the focus driver's alternate position exists. Substituting it into the
    // real order would put two cars in one place, so the alternate is reported as
    // a displacement and the caveat is stated in the UI rather than assumed.
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("playhead")).toBeInTheDocument());
    screen.getByTestId("playhead").focus();
    await userEvent.keyboard("{End}");
    await waitFor(() => expect(screen.getByText(/order on lap/i)).toBeInTheDocument());

    expect(screen.getByText(/only this driver's alternate position is stored/i)).toBeInTheDocument();
  });

  it("keyboard-operates on the same conventions as the pit drag", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("playhead")).toBeInTheDocument());
    const head = screen.getByTestId("playhead");
    const now = () => Number(head.getAttribute("aria-valuenow"));
    const min = Number(head.getAttribute("aria-valuemin"));
    const max = Number(head.getAttribute("aria-valuemax"));

    head.focus();
    await userEvent.keyboard("{Home}");
    await waitFor(() => expect(now()).toBe(min));
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(now()).toBe(min + 1));
    await userEvent.keyboard("{Shift>}{ArrowRight}{/Shift}");
    await waitFor(() => expect(now()).toBe(min + 6));
    await userEvent.keyboard("{End}");
    await waitFor(() => expect(now()).toBe(max));
  });

  it("resets when the thing it is scrubbing changes", async () => {
    // "The order on lap 47" of a race that is no longer loaded is not a fact
    // about anything, so the playhead parks on any change of race/driver/stop.
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("playhead")).toBeInTheDocument());
    screen.getByTestId("playhead").focus();
    await userEvent.keyboard("{Home}");
    await waitFor(() => expect(screen.getByText(/order on lap/i)).toBeInTheDocument());

    await userEvent.selectOptions(screen.getByLabelText(/^driver$/i), "VER");
    await waitFor(() => expect(screen.queryByText(/order on lap/i)).not.toBeInTheDocument());
  });

  it("offers playback, and hides it entirely under prefers-reduced-motion", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("playhead")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^play$/i })).toBeInTheDocument();
  });
});
