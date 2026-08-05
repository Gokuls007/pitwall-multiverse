import { describe, expect, it } from "vitest";
import { teamLineColor, teamLineContrast, teammateDash } from "./teamColors";

// The whole reason this module exists: spec 11.2 mandates team colours, spec
// 11.1 says legibility wins conflicts, and several real liveries are far too
// light to read as a thin line on the paper background. These tests pin the
// resolution so a future palette change can't quietly break it.

describe("team line colours on paper", () => {
  it("brings every known team above the 3:1 non-text contrast floor", () => {
    const teams = [
      "Mercedes", // #00D2BE -- the worst offender, very light cyan
      "Ferrari",
      "Red Bull Racing",
      "McLaren",
      "Racing Point", // pale pink
      "Renault", // #FFF500, near-white yellow
      "Haas F1 Team",
      "Williams",
      "Alpine",
      "Aston Martin",
      "AlphaTauri",
      "Toro Rosso",
      "Alfa Romeo Racing",
    ];
    for (const team of teams) {
      expect(teamLineContrast(team), `${team} must clear 3:1 on paper`).toBeGreaterThanOrEqual(3);
    }
  });

  it("clears the floor for an unknown team via the fallback", () => {
    expect(teamLineContrast("Some New Team 2027")).toBeGreaterThanOrEqual(3);
  });

  it("preserves hue identity rather than substituting a generic dark colour", () => {
    // Mercedes is cyan: after darkening, blue+green must still dominate red.
    const merc = teamLineColor("Mercedes");
    const r = parseInt(merc.slice(1, 3), 16);
    const g = parseInt(merc.slice(3, 5), 16);
    const b = parseInt(merc.slice(5, 7), 16);
    expect(g).toBeGreaterThan(r);
    expect(b).toBeGreaterThan(r);

    // Ferrari is red: red must still dominate.
    const fer = teamLineColor("Ferrari");
    const fr = parseInt(fer.slice(1, 3), 16);
    const fg = parseInt(fer.slice(3, 5), 16);
    expect(fr).toBeGreaterThan(fg);
  });

  it("gives teammates a second, colour-independent channel", () => {
    // Colour-blind users and anyone reading a printout need the pair to
    // separate without relying on hue at all.
    expect(teammateDash(0)).toBeUndefined();
    expect(teammateDash(1)).toBeDefined();
    expect(teammateDash(0)).not.toBe(teammateDash(1));
  });
});
