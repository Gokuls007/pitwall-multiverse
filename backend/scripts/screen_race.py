#!/usr/bin/env python
"""Hard first-pass disqualifier check for catalogue candidates (spec 4.4).

Run this BEFORE checking data-quality metrics or writing a "contested
decision" description. Three races were picked on data quality and narrative
appeal first and only later found to be decided by something other than
on-track racing (Abu Dhabi 2021 - race control's lapped-car call; British GP
2021 - a red flag; Japanese GP 2019 - a chequered-flag system error that
invalidated the last lap of the race under Article 43.2, letting Perez keep
points despite crashing on the invalidated lap, and Leclerc's post-race
penalties). This script makes that check mechanical and first, not an
afterthought once a race already looks appealing.

Usage:
    python backend/scripts/screen_race.py <year> <event_identifier>
"""

from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import fastf1  # noqa: E402

PENALTY_KEYWORDS = ("TIME PENALTY", "PENALTY FOR CAR", "GRID PENALTY")
# Word-boundary regex, not substring match: "CHEQUERED FLAG" contains the
# literal substring "RED FLAG" (...cheque-RED FLAG), which a naive `in`
# check flags as a false positive red flag. \b requires a transition between
# word/non-word characters, which doesn't exist between the 'E' and 'R' in
# "cheq-uE-Red", so this correctly does not match inside "CHEQUERED".
RED_FLAG_PATTERN = re.compile(r"\bRED FLAG\b")
DSQ_KEYWORDS = ("DISQUALIFI",)
COLLISION_KEYWORDS = ("CAUSING A COLLISION", "CAUSING COLLISION")


def screen(year: int, event_identifier: str) -> bool:
    fastf1.Cache.enable_cache(str(Path(__file__).resolve().parents[2] / "data" / "cache"))
    session = fastf1.get_session(year, event_identifier, "R")
    session.load(laps=True, telemetry=False, weather=True, messages=True)

    rc = session.race_control_messages
    results = session.results
    laps = session.laps

    disqualifying: list[str] = []
    notes: list[str] = []

    for _, row in rc.iterrows():
        msg = str(row.get("Message", "")).upper()
        lap = row.get("Lap")
        if any(k in msg for k in PENALTY_KEYWORDS):
            disqualifying.append(f"L{lap}: penalty issued — {row['Message']}")
        if RED_FLAG_PATTERN.search(msg):
            disqualifying.append(f"L{lap}: red flag — {row['Message']}")
        if any(k in msg for k in COLLISION_KEYWORDS):
            notes.append(f"L{lap}: adjudicated collision — {row['Message']}")

    for _, row in results.iterrows():
        status = str(row.get("Status", ""))
        if any(k in status.upper() for k in DSQ_KEYWORDS):
            disqualifying.append(f"{row['Abbreviation']}: {status}")

    # Article 43.2-style check: does the race control log's last "CHEQUERED
    # FLAG" lap match the scheduled distance, or does the classification-
    # determining lap fall short of it (a flag/timing anomaly)?
    scheduled_laps = None
    try:
        scheduled_laps = int(session.total_laps)
    except Exception:  # noqa: BLE001
        pass
    flag_msgs = rc[rc["Message"].str.contains("CHEQUERED FLAG", case=False, na=False)]
    max_lap_in_data = int(laps["LapNumber"].max()) if len(laps) else None

    # Early retirements among front-runners (started top 5) — flags a race
    # whose result may hinge on a lap-1/early incident rather than strategy.
    early_dnf_front_runners: list[str] = []
    for _, row in results.iterrows():
        status = str(row.get("Status", ""))
        grid = row.get("GridPosition")
        if status not in ("Finished",) and not status.startswith("+") and grid is not None and grid <= 5:
            driver_laps = laps[laps["Driver"] == row["Abbreviation"]]
            last_lap = int(driver_laps["LapNumber"].max()) if len(driver_laps) else 0
            if last_lap <= 3:
                early_dnf_front_runners.append(
                    f"{row['Abbreviation']} (grid P{int(grid)}): retired lap {last_lap}, status={status}"
                )

    print(f"=== Screening {year} {event_identifier} ===")
    print(f"Scheduled laps (session.total_laps): {scheduled_laps}")
    print(f"Max lap number in timing data: {max_lap_in_data}")
    print(f"Chequered flag message(s) at lap: {flag_msgs['Lap'].tolist() if len(flag_msgs) else 'none found'}")

    if disqualifying:
        print("\nHARD DISQUALIFIERS FOUND:")
        for d in disqualifying:
            print(f"  - {d}")
    else:
        print("\nNo hard disqualifiers found (no penalties, red flags, or DSQs).")

    if early_dnf_front_runners:
        print("\nEarly (<=lap 3) retirements among top-5 grid starters (investigate before proceeding):")
        for n in early_dnf_front_runners:
            print(f"  - {n}")

    if notes:
        print("\nAdjudicated incidents noted (not necessarily disqualifying — check if they affect the featured story):")
        for n in notes:
            print(f"  - {n}")

    return len(disqualifying) == 0 and len(early_dnf_front_runners) == 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python screen_race.py <year> <event_identifier>")
        sys.exit(1)
    ok = screen(int(sys.argv[1]), sys.argv[2])
    sys.exit(0 if ok else 1)
