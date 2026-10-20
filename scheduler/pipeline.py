"""Load -> build CSP -> backtracking (feasible) -> min-conflicts (optimise) -> rows."""
import random

from .csp_solver import AC3, backtracking_search
from .data_loader import load_data
from .local_search import min_conflicts_optimize, total_cost
from .model import Timetable

FIELDS = ["course_id", "room_id", "slot_id", "instructor_id", "cohort_id", "day", "start_time", "end_time"]


def solve(data_dir="data", max_nodes=200000, ls_steps=4000, ls_seconds=10.0, verbose=True):
    log = print if verbose else (lambda *a, **k: None)
    data = load_data(data_dir)
    csp = Timetable(data)

    empty = [c for c in csp.variables if not csp.domains[c]]
    if empty:
        raise ValueError("No legal room/time placement for: " + ", ".join(empty))
    csp.support_pruning()
    feasible = AC3(csp)
    log(f"AC-3 preprocessing: {'ok' if feasible else 'domain wipe-out'}")

    if not feasible:
        raise ValueError("No feasible timetable: AC-3 found incompatible constraints")
    assignment = backtracking_search(csp, max_nodes=max_nodes)
    if assignment is None:
        log("backtracking found no complete schedule; repairing with min-conflicts")
        rng = random.Random(0)
        assignment = {c: rng.choice(csp.domains[c]) for c in csp.variables if csp.domains[c]}
    else:
        log(f"backtracking: complete schedule after {csp.nassigns} assignments")

    csp.curr_domains = None
    log(f"cost before local search: {total_cost(csp, assignment):.1f}")
    assignment, cost = min_conflicts_optimize(csp, assignment, max_steps=ls_steps, time_limit=ls_seconds)
    log(f"cost after local search:  {cost:.1f}")

    bad = {k: v for k, v in csp.violations(assignment).items() if v}
    log("hard-constraint violations:", bad if bad else "none")
    if bad:
        raise ValueError(f"No valid timetable found within search limits: {bad}")
    return csp, assignment


def to_rows(csp, assignment):
    d = csp.data
    rows = []
    for c, (s, r) in assignment.items():
        sl = d.slots[s]
        rows.append({"course_id": c, "room_id": r, "slot_id": s,
                     "instructor_id": ";".join(csp.instructors_of[c]),
                     "cohort_id": ";".join(csp.cohorts_of[c]),
                     "day": sl.day, "start_time": sl.start_text, "end_time": sl.end_text})
    day_order = list(dict.fromkeys(sl.day for sl in d.slots.values()))
    rows.sort(key=lambda x: (day_order.index(x["day"]), x["start_time"], x["course_id"]))
    return rows
