"""Min-Conflicts local search over a complete timetable.

Cost = HARD_WEIGHT * (hard clashes) + soft penalties, so the same loop repairs
infeasible starts and then polishes soft quality. Each step re-places one
course on its minimum-cost (slot, room); a little random noise escapes plateaus
and the best assignment seen is returned.
"""
import random
import time


def _hard_pairs(csp, assignment):
    n, seen = 0, list(assignment.items())
    for k, (a, (sa, ra)) in enumerate(seen):
        for b, (sb, rb) in seen[k + 1:]:
            if sb in csp.overlaps[sa] and (ra == rb or (a, b) in csp.shared):
                n += 1
    return n


def total_cost(csp, assignment):
    return csp.data.weights["HARD"] * _hard_pairs(csp, assignment) + csp.soft_cost(assignment)


def min_conflicts_optimize(csp, assignment, max_steps=4000, time_limit=10.0, noise=0.03, seed=0):
    if set(assignment) != set(csp.variables):
        raise ValueError("Local search requires a complete assignment")
    if any(value not in csp.domains[c] for c, value in assignment.items()):
        raise ValueError("Local search requires placements from legal domains")
    if not assignment:
        return {}, 0.0
    rng = random.Random(seed)
    cur = dict(assignment)
    w_hard = csp.data.weights["HARD"]
    cohorts = csp.data.cohorts

    by_slot = {}
    for c, (s, _) in cur.items():
        by_slot.setdefault(s, set()).add(c)

    def hard(c, val):
        s, r = val
        n = 0
        for o in csp.overlaps[s]:
            for v in by_slot.get(o, ()):
                if v != c and (cur[v][1] == r or (c, v) in csp.shared):
                    n += 1
        return n

    def local(c, val):
        cost = w_hard * hard(c, val) + csp.course_cost(c, val)
        for h in csp.cohorts_of[c]:
            placement = {x: cur[x] for x in cohorts[h].courses if x in cur and x != c}
            placement[c] = val
            cost += csp.cohort_cost(h, placement)
        return cost

    def move(c, val):
        by_slot[cur[c][0]].discard(c)
        cur[c] = val
        by_slot.setdefault(val[0], set()).add(c)

    total = total_cost(csp, cur)
    best, best_total = dict(cur), total
    best_rank = (_hard_pairs(csp, cur), csp.soft_cost(cur))
    start = time.monotonic()

    for _ in range(max_steps):
        if time.monotonic() - start > time_limit:
            break
        conflicted = [c for c, v in cur.items() if hard(c, v) > 0]
        if conflicted and rng.random() < 0.7:
            var = rng.choice(conflicted)
        else:
            var = rng.choice(list(cur))
        old_val, old_cost = cur[var], local(var, cur[var])

        # Once feasible, never trade a hard constraint for a soft improvement.
        candidates = csp.domains[var]
        if not conflicted:
            candidates = [v for v in candidates if hard(var, v) == 0]
        if rng.random() < noise:
            new_val = rng.choice(candidates)
        else:
            scored = [(local(var, v), v) for v in candidates]
            low = min(s for s, _ in scored)
            new_val = rng.choice([v for s, v in scored if s == low])

        new_cost = local(var, new_val)
        move(var, new_val)
        total += new_cost - old_cost
        rank = (_hard_pairs(csp, cur), csp.soft_cost(cur))
        if rank < best_rank:
            best, best_total, best_rank = dict(cur), total_cost(csp, cur), rank

    return best, best_total
