"""Generic CSP machinery: backtracking with MRV + degree, LCV, forward checking, AC-3.

Adapted from aima-python's csp.py (MIT License, Copyright (c) 2016 aima-python
contributors). Changes: degree-heuristic tie-break for MRV, domain pruning
logged as whole-list snapshots (O(1) restore), a node limit, and a
problem-overridable `ruled_out_counts` so LCV scales to large domains.
"""
from collections import deque


class SearchLimit(Exception):
    pass


class CSP:
    """variables: list; domains: {var: [values]}; neighbors: {var: set(vars)};
    constraints(A, a, B, b) -> True when A=a, B=b are consistent."""

    def __init__(self, variables, domains, neighbors, constraints):
        self.variables = variables
        self.domains = domains
        self.neighbors = neighbors
        self.constraints = constraints
        self.curr_domains = None
        self.nassigns = 0

    def assign(self, var, val, assignment):
        assignment[var] = val
        self.nassigns += 1

    def unassign(self, var, assignment):
        assignment.pop(var, None)

    def nconflicts(self, var, val, assignment):
        return sum(1 for n in self.neighbors[var]
                   if n in assignment and not self.constraints(var, val, n, assignment[n]))

    def support_pruning(self):
        if self.curr_domains is None:
            self.curr_domains = {v: list(self.domains[v]) for v in self.variables}

    def suppose(self, var, value):
        """Fix var to value; return removal log for restore()."""
        self.support_pruning()
        removals = [(var, self.curr_domains[var])]
        self.curr_domains[var] = [value]
        return removals

    def restore(self, removals):
        for var, old in reversed(removals):
            self.curr_domains[var] = old

    def choices(self, var):
        return (self.curr_domains or self.domains)[var]

    def ruled_out_counts(self, var, assignment):
        """{value: number of neighbour values it would eliminate}. Brute force
        default; subclasses may override with something faster."""
        counts = {}
        for val in self.choices(var):
            n = 0
            for B in self.neighbors[var]:
                if B not in assignment:
                    n += sum(1 for b in self.choices(B) if not self.constraints(var, val, B, b))
            counts[val] = n
        return counts

    def tie_break(self, var, value):
        return 0


# ---- variable ordering -----------------------------------------------------

def mrv(assignment, csp):
    """Minimum remaining values; ties broken by degree (most unassigned neighbours)."""
    def key(var):
        degree = sum(1 for n in csp.neighbors[var] if n not in assignment)
        return (len(csp.choices(var)), -degree)
    return min((v for v in csp.variables if v not in assignment), key=key)


# ---- value ordering --------------------------------------------------------

def lcv(var, assignment, csp):
    """Least constraining value first; remaining ties by csp.tie_break."""
    counts = csp.ruled_out_counts(var, assignment)
    return sorted(csp.choices(var), key=lambda val: (counts[val], csp.tie_break(var, val)))


# ---- inference -------------------------------------------------------------

def no_inference(csp, var, value, assignment, removals):
    return True


def forward_checking(csp, var, value, assignment, removals):
    """Remove neighbour values inconsistent with var=value; fail on empty domain."""
    for B in csp.neighbors[var]:
        if B in assignment:
            continue
        old = csp.curr_domains[B]
        new = [b for b in old if csp.constraints(var, value, B, b)]
        if len(new) < len(old):
            removals.append((B, old))
            csp.curr_domains[B] = new
            if not new:
                return False
    return True


def revise(csp, Xi, Xj, removals):
    """Drop values of Xi with no supporting value in Xj."""
    old = csp.curr_domains[Xi]
    dj = csp.curr_domains[Xj]
    new = [x for x in old if any(csp.constraints(Xi, x, Xj, y) for y in dj)]
    if len(new) < len(old):
        if removals is not None:
            removals.append((Xi, old))
        csp.curr_domains[Xi] = new
        return True
    return False


def AC3(csp, queue=None, removals=None):
    """Arc consistency (AC-3). Returns False if some domain is wiped out."""
    csp.support_pruning()
    if queue is None:
        queue = deque((Xi, Xk) for Xi in csp.variables for Xk in csp.neighbors[Xi])
    else:
        queue = deque(queue)
    while queue:
        Xi, Xj = queue.popleft()
        if revise(csp, Xi, Xj, removals):
            if not csp.curr_domains[Xi]:
                return False
            queue.extend((Xk, Xi) for Xk in csp.neighbors[Xi] if Xk != Xj)
    return True


def mac(csp, var, value, assignment, removals):
    """Maintain arc consistency after assigning var=value."""
    return AC3(csp, [(X, var) for X in csp.neighbors[var] if X not in assignment], removals)


# ---- search ----------------------------------------------------------------

def backtracking_search(csp, select_unassigned_variable=mrv, order_domain_values=lcv,
                        inference=forward_checking, max_nodes=None):
    """Return a full consistent assignment, or None (no solution / node limit hit)."""
    csp.support_pruning()
    nodes = 0

    def backtrack(assignment):
        nonlocal nodes
        if len(assignment) == len(csp.variables):
            return assignment
        var = select_unassigned_variable(assignment, csp)
        for value in order_domain_values(var, assignment, csp):
            nodes += 1
            if max_nodes is not None and nodes > max_nodes:
                raise SearchLimit
            if csp.nconflicts(var, value, assignment) == 0:
                csp.assign(var, value, assignment)
                removals = csp.suppose(var, value)
                if inference(csp, var, value, assignment, removals):
                    result = backtrack(assignment)
                    if result is not None:
                        return result
                csp.restore(removals)
                csp.unassign(var, assignment)
        return None

    try:
        return backtrack({})
    except SearchLimit:
        return None
