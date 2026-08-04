"""The curated race catalogue (spec Part 4.4).

Five hand-picked races, not a general "any race" tool. Each entry names a
genuinely contested strategic decision fans still argue about, was run in dry
conditions (so v1 avoids the compound-crossover complexity of a drying track),
and has been checked against FastF1 for data completeness (Phase 1: verified
20/20 drivers present in both `laps` and `results`, TrackStatus SC/VSC codes
decode as expected, laps run entirely on slick compounds).

Stored as structured data, not scattered through code, per 4.4.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionPointHint:
    """A specific decision point to surface in the UI for this race."""

    kind: str  # "pit_stop" | "safety_car" | "compound"
    driver: str | None
    lap: int
    description: str


@dataclass(frozen=True)
class CatalogueEntry:
    year: int
    event_name: str
    fastf1_event_identifier: str  # what to pass to fastf1.get_session as the `gp` arg
    circuit: str
    contested_decision: str
    decision_points: tuple[DecisionPointHint, ...]

    @property
    def race_key(self) -> str:
        slug = self.event_name.lower().replace("grand prix", "").strip()
        slug = "_".join(slug.split())
        return f"{self.year}_{slug}"


CATALOGUE: tuple[CatalogueEntry, ...] = (
    CatalogueEntry(
        year=2021,
        event_name="Abu Dhabi Grand Prix",
        fastf1_event_identifier="Abu Dhabi",
        circuit="Yas Marina Circuit",
        contested_decision=(
            "A late safety car for Latifi's crash (lap 53) bunched the field. Race "
            "control's decision on which lapped cars were allowed to unlap themselves "
            "before a one-lap restart directly set up Verstappen's pass on Hamilton for "
            "the championship. The most argued-over single call in modern F1."
        ),
        decision_points=(
            DecisionPointHint("safety_car", None, 53, "Shift or remove the lap-53 safety car"),
            DecisionPointHint("pit_stop", "VER", 53, "Verstappen pits for softs under the SC"),
        ),
    ),
    CatalogueEntry(
        year=2018,
        event_name="Australian Grand Prix",
        fastf1_event_identifier="Australia",
        circuit="Albert Park Circuit",
        contested_decision=(
            "Alonso's McLaren stopped on track triggered a Virtual Safety Car. Ferrari "
            "reacted instantly and pitted Vettel, who was running behind Hamilton; the VSC "
            "made the stop almost free and Vettel emerged ahead, taking a win Hamilton had "
            "been leading on pace."
        ),
        decision_points=(
            DecisionPointHint(
                "pit_stop", "VET", 26, "Vettel's VSC-window pit stop that won him the race"
            ),
            DecisionPointHint("safety_car", None, 26, "Shift or remove the VSC period"),
        ),
    ),
    CatalogueEntry(
        year=2019,
        event_name="Singapore Grand Prix",
        fastf1_event_identifier="Singapore",
        circuit="Marina Bay Street Circuit",
        contested_decision=(
            "Leclerc led Vettel on track, but Ferrari pitted Vettel first. The undercut "
            "vaulted Vettel past his own teammate when Leclerc pitted a lap later — a "
            "strategy call that visibly favoured one Ferrari driver over the other."
        ),
        decision_points=(
            DecisionPointHint(
                "pit_stop", "VET", 20, "Vettel pitted first, undercutting race leader Leclerc"
            ),
            DecisionPointHint("pit_stop", "LEC", 21, "Leclerc's reactive stop the following lap"),
        ),
    ),
    CatalogueEntry(
        year=2019,
        event_name="Monaco Grand Prix",
        fastf1_event_identifier="Monaco",
        circuit="Circuit de Monaco",
        contested_decision=(
            "A mix-up with Hamilton's prepared tyre sets left Mercedes without a fresh "
            "set to give him at his stop, forcing him to nurse a single set of hards to "
            "the flag while Verstappen closed in — at a circuit where overtaking is "
            "nearly impossible, so the stop itself was the whole race."
        ),
        decision_points=(
            DecisionPointHint(
                "pit_stop", "HAM", 13, "Hamilton's stop onto the hard tyre he'd run to the end"
            ),
            DecisionPointHint("compound", "HAM", 13, "An alternate compound choice at the stop"),
        ),
    ),
    CatalogueEntry(
        year=2021,
        event_name="British Grand Prix",
        fastf1_event_identifier="Great Britain",
        circuit="Silverstone Circuit",
        contested_decision=(
            "A first-lap collision between Verstappen and Hamilton brought out a red flag. "
            "Hamilton took a 10-second penalty for the incident but still won from the "
            "restart, re-fitting fresh tyres for what was effectively a second sprint to "
            "the flag."
        ),
        decision_points=(
            DecisionPointHint("safety_car", None, 1, "The lap-1 red flag stoppage"),
            DecisionPointHint(
                "pit_stop", "HAM", 1, "Hamilton's tyre choice at the red-flag restart"
            ),
        ),
    ),
)


def get_entry(race_key: str) -> CatalogueEntry:
    for entry in CATALOGUE:
        if entry.race_key == race_key:
            return entry
    raise KeyError(f"No catalogue entry with race_key={race_key!r}")
