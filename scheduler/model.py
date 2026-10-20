"""Timetabling problem formulation.

Variables : one per course.
Domains   : (slot_id, room_id) pairs left after unary filtering
            (room availability H-room, capacity H2, instructor availability H4).
Binary    : H1 room clash, H3 instructor clash, H5 cohort clash. Clashes are
            decided on real time overlap, because some slots overlap in time.
Soft      : S1 instructor preference, S2 oversized room, S3 dead hours,
            S4 >2 back-to-back, S5 building transit, plus preferred rooms.
"""
import math
from collections import Counter

from .csp_solver import CSP

BACK_TO_BACK_MIN = 10   # gap (minutes) at or under which two classes are "consecutive"
OVERSIZE_SLACK = 30     # spare seats tolerated before S2 applies


class Timetable(CSP):
    def __init__(self, data):
        self.data = data
        self.warnings = []
        slots, rooms = data.slots, data.rooms

        self.overlaps = {a: frozenset(b for b, sb in slots.items()
                                      if sb.day == sa.day and sa.start < sb.end and sb.start < sa.end)
                         for a, sa in slots.items()}

        name_to_id = {i.name: i.id for i in data.instructors.values()}
        self.instructors_of = {}
        for c in data.courses.values():
            ids = {name_to_id.get(n, n) for n in c.instructor_names}
            ids |= {i.id for i in data.instructors.values() if c.id in i.courses}
            self.instructors_of[c.id] = sorted(ids)

        self.cohorts_of = {c: [h.id for h in data.cohorts.values() if c in h.courses]
                           for c in data.courses}
        self.enrollment = {c.id: self._estimate_enrollment(c) for c in data.courses.values()}

        domains = {c: self._domain(data.courses[c]) for c in data.courses}
        variables = sorted(data.courses, key=lambda c: len(domains[c]))

        groups = {}
        for c in data.courses:
            for key in [("i", i) for i in self.instructors_of[c]] + [("h", h) for h in self.cohorts_of[c]]:
                groups.setdefault(key, []).append(c)
        self.shared = set()
        for members in groups.values():
            self.shared |= {(a, b) for a in members for b in members if a != b}

        room_vars = {}
        for c, dom in domains.items():
            for r in {r for _, r in dom}:
                room_vars.setdefault(r, []).append(c)
        neighbors = {c: set() for c in data.courses}
        for a, b in self.shared:
            neighbors[a].add(b)
        for members in room_vars.values():
            for a in members:
                neighbors[a] |= {b for b in members if b != a}

        super().__init__(variables, domains, neighbors, self._consistent)

    # ---- construction helpers --------------------------------------------

    def _estimate_enrollment(self, course):
        """Use explicit enrollment or the sum of distinct mandatory cohorts.

        Courses without either source remain unknown; never infer class size
        from the capacity of a room we would like to use.
        """
        if course.enrollment is not None:
            return course.enrollment
        sizes = [self.data.cohorts[h].size for h in self.cohorts_of[course.id]]
        if sizes:
            return sum(sizes)
        self.warnings.append(f"{course.id}: enrollment unknown; capacity cannot be verified")
        return None

    def _domain(self, course):
        d = self.data
        enroll = self.enrollment[course.id]

        def fits(r):
            room = d.rooms[r]
            if not room.available or (enroll is not None and room.capacity < enroll):
                return False
            return not course.room_type or course.room_type.lower() in room.room_type.lower()

        rooms = [r for r in course.room_hints if fits(r)]
        if not rooms:
            rooms = [r for r in d.rooms if fits(r)]
            self.warnings.append(f"{course.id}: no suitable hinted room, using any fitting room")
        if not rooms:
            self.warnings.append(f"{course.id}: no room fits enrollment {enroll}")

        banned = set()
        for i in self.instructors_of[course.id]:
            if i in d.instructors:
                for unavailable in d.instructors[i].unavailable:
                    banned.update(self.overlaps[unavailable])
        return [(s, r) for s in d.slots if s not in banned for r in rooms]

    def _consistent(self, A, a, B, b):
        if A == B or b[0] not in self.overlaps[a[0]]:
            return True
        return a[1] != b[1] and (A, B) not in self.shared

    # ---- LCV speed-up ----------------------------------------------------

    def ruled_out_counts(self, var, assignment):
        counts = dict.fromkeys(self.choices(var), 0)
        for B in self.neighbors[var]:
            if B in assignment:
                continue
            dom = self.choices(B)
            by_slot = Counter(s for s, _ in dom)
            by_pair = Counter(dom)
            shared = (var, B) in self.shared
            for val in counts:
                s, r = val
                counts[val] += sum(by_slot[o] if shared else by_pair[(o, r)] for o in self.overlaps[s])
        return counts

    def tie_break(self, var, value):
        return self.course_cost(var, value)

    # ---- soft penalties --------------------------------------------------

    def course_cost(self, c, val):
        """Penalties that depend only on this course's own placement (S1, S2, room requests)."""
        d, w = self.data, self.data.weights
        slot, room = val
        cost = 0.0
        for i in self.instructors_of[c]:
            pref = d.instructors[i].preferred if i in d.instructors else None
            if pref and slot not in pref:
                cost += w["S1"]
        enroll = self.enrollment[c]
        if enroll is not None:
            spare = d.rooms[room].capacity - enroll - OVERSIZE_SLACK
            if spare > 0:
                cost += w["S2"] * (spare // 10 + 1)
        wanted = d.preferred_rooms.get(c)
        if wanted and room not in wanted:
            cost += w["ROOM_PREF"]
        return cost

    def cohort_cost(self, cohort_id, placement):
        """S3/S4/S5 for one cohort. placement: {course: (slot, room)} (missing = unscheduled)."""
        d, w = self.data, self.data.weights
        by_day = {}
        for c in d.cohorts[cohort_id].courses:
            if c in placement:
                s, r = placement[c]
                sl = d.slots[s]
                by_day.setdefault(sl.day, []).append((sl.start, sl.end, d.rooms[r].building))
        cost = 0.0
        for meetings in by_day.values():
            meetings.sort()
            run = 1
            for (s0, e0, b0), (s1, e1, b1) in zip(meetings, meetings[1:]):
                gap = s1 - e0
                if gap > BACK_TO_BACK_MIN:
                    cost += w["S3"] * math.ceil(gap / 60)
                    run = 1
                else:
                    run += 1
                    if run > 2:
                        cost += w["S4"]
                    if b0 != b1:
                        cost += w["S5"]
        return cost

    def soft_cost(self, assignment):
        total = sum(self.course_cost(c, v) for c, v in assignment.items())
        return total + sum(self.cohort_cost(h, assignment) for h in self.data.cohorts)

    # ---- independent verification ---------------------------------------

    def violations(self, assignment):
        """Re-check H1-H6 straight from the raw data; returns {code: [messages]}."""
        d = self.data
        out = {k: [] for k in ("H1", "H2", "H3", "H4", "H5", "H6")}
        for c in d.courses:
            if c not in assignment:
                out["H6"].append(f"{c} not scheduled")
        items = []
        for c, value in sorted(assignment.items()):
            if c not in d.courses:
                out["H6"].append(f"unknown course {c}")
                continue
            if (not isinstance(value, (tuple, list)) or len(value) != 2
                    or value[0] not in d.slots or value[1] not in d.rooms):
                out["H6"].append(f"{c} has invalid placement {value}")
                continue
            items.append((c, value))
        for n, (a, (sa, ra)) in enumerate(items):
            room = d.rooms[ra]
            if not room.available or (self.enrollment[a] is not None and room.capacity < self.enrollment[a]):
                out["H2"].append(f"{a} in {ra}")
            required_type = d.courses[a].room_type
            if required_type and required_type.lower() not in room.room_type.lower():
                out["H2"].append(f"{a} requires {required_type}, got {room.room_type}")
            for i in self.instructors_of[a]:
                if i in d.instructors and self.overlaps[sa] & d.instructors[i].unavailable:
                    out["H4"].append(f"{a}/{i} at {sa}")
            for b, (sb, rb) in items[n + 1:]:
                if sb not in self.overlaps[sa]:
                    continue
                if ra == rb:
                    out["H1"].append(f"{a},{b} in {ra}")
                if set(self.instructors_of[a]) & set(self.instructors_of[b]):
                    out["H3"].append(f"{a},{b}")
                if set(self.cohorts_of[a]) & set(self.cohorts_of[b]):
                    out["H5"].append(f"{a},{b}")
        return out
