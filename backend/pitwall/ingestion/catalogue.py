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
        year=2019,
        event_name="Hungarian Grand Prix",
        fastf1_event_identifier="Hungary",
        circuit="Hungaroring",
        contested_decision=(
            "Verstappen led comfortably on a long final stint. Mercedes gambled on a "
            "second stop for Hamilton on lap 48 for a fresh set against Verstappen's "
            "worn tyres, and Hamilton hunted him down to pass for the win in the closing "
            "laps. A pure pit-strategy decision with no stewarding or incident involved — "
            "the argument is entirely 'should Red Bull have covered the extra stop.'"
        ),
        decision_points=(
            DecisionPointHint(
                "pit_stop", "HAM", 48, "Hamilton's gamble second stop that set up the chase"
            ),
            DecisionPointHint(
                "pit_stop", "VER", 67, "Verstappen's own late stop, arguably too late to react"
            ),
        ),
    ),
    CatalogueEntry(
        year=2019,
        event_name="Mexican Grand Prix",
        fastf1_event_identifier="Mexico",
        circuit="Autódromo Hermanos Rodríguez",
        contested_decision=(
            "Leclerc took pole but slid to P4; Vettel, alongside him on the front row, "
            "finished P2. The two Ferraris ran different strategies — Vettel one-stopped, "
            "Leclerc pitted twice — raising the question of whether the second stop cost "
            "Leclerc more track position than the tyre offset was worth."
        ),
        decision_points=(
            DecisionPointHint("pit_stop", "LEC", 43, "Leclerc's second stop"),
            DecisionPointHint(
                "pit_stop", "VET", 37, "Vettel's single stop — the alternate one-stop reference"
            ),
        ),
    ),
    CatalogueEntry(
        year=2019,
        event_name="Australian Grand Prix",
        fastf1_event_identifier="Australia",
        circuit="Albert Park Circuit",
        contested_decision=(
            "A modest story, described honestly rather than dressed up: Bottas made a "
            "strong start from P2 to lead by lap 1 and controlled the race to the flag on "
            "a single soft-to-medium stop, with Hamilton never able to close the gap. "
            "There is no dramatic pit battle here — the counterfactual value is in "
            "testing whether a different stop lap for either driver would have let "
            "Hamilton close in, not in relitigating a contested decision that didn't "
            "really happen on the day."
        ),
        decision_points=(
            DecisionPointHint("pit_stop", "BOT", 23, "Bottas' only stop, from the race lead"),
            DecisionPointHint(
                "pit_stop", "HAM", 15, "Hamilton's own stop — earlier than Bottas'"
            ),
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
        event_name="Spanish Grand Prix",
        fastf1_event_identifier="Spain",
        circuit="Circuit de Barcelona-Catalunya",
        contested_decision=(
            "Verstappen passed Hamilton at the start and controlled the race from the "
            "front. Mercedes reacted with an early second stop for Hamilton on lap 42 for "
            "a fresh set, while Red Bull left Verstappen out on ageing tyres until lap 60 — "
            "handing Hamilton a ~24-lap tyre-life advantage he used to reel in and pass "
            "Verstappen for the win in the closing laps. A brief early safety car (laps "
            "8-10) is unrelated to the winning decision, unlike British GP 2021's red flag."
        ),
        decision_points=(
            DecisionPointHint(
                "pit_stop", "HAM", 42, "Hamilton's early second stop that set up the chase"
            ),
            DecisionPointHint(
                "pit_stop", "VER", 60, "Verstappen's much later second stop, arguably too late"
            ),
        ),
    ),
)


def get_entry(race_key: str) -> CatalogueEntry:
    for entry in CATALOGUE:
        if entry.race_key == race_key:
            return entry
    raise KeyError(f"No catalogue entry with race_key={race_key!r}")
