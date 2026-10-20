"""Load and normalise the relational CSV datasets.

The loader is tolerant: optional columns (enrollment, unavailable_slots,
preferred_slots, room_type) are used when present and ignored otherwise, so
replacing the files in data/ keeps working.
"""
import csv
import json
import os
import re
from dataclasses import dataclass, field

DAY_PREFIX = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
              "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday"}


@dataclass
class Slot:
    id: str
    day: str
    start: int          # minutes since midnight
    end: int
    start_text: str
    end_text: str


@dataclass
class Room:
    id: str
    building: str
    capacity: int       # scheduling capacity (falls back to physical)
    room_type: str
    available: bool


@dataclass
class Instructor:
    id: str
    name: str
    courses: list
    unavailable: set = field(default_factory=set)
    preferred: set = field(default_factory=set)


@dataclass
class Course:
    id: str
    level: str
    instructor_names: list
    room_hints: list
    enrollment: int = None      # None = unknown
    room_type: str = ""


@dataclass
class Cohort:
    id: str
    size: int
    courses: list


@dataclass
class Data:
    slots: dict
    rooms: dict
    instructors: dict
    courses: dict
    cohorts: dict
    preferred_rooms: dict       # course_id -> set(room_id)
    weights: dict


def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(f)]


def _split(text):
    return [t.strip() for t in re.split(r"[;|]", text or "") if t.strip()]


def _minutes(hhmm):
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def _to_int(text, default=None):
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def expand_room_hints(text, room_ids):
    """'TECH 201/202/203/204; AUD 100' -> existing room ids."""
    found = []
    for token in _split(text):
        m = re.match(r"^(.*?)(\d+(?:/\d+)+)$", token)
        names = [m.group(1) + n for n in m.group(2).split("/")] if m else [token]
        found += [n for n in names if n in room_ids and n not in found]
    return found


def expand_slot_tokens(text, slots):
    """Slot ids, whole days ('Monday' / 'MON'), accepted."""
    out = set()
    for token in _split(text):
        if token in slots:
            out.add(token)
            continue
        day = DAY_PREFIX.get(token[:3].lower())
        if day:
            out |= {s.id for s in slots.values() if s.day == day}
    return out


def _parse_preferred_rooms(rows):
    """Preferred rows with rule "preferred_room = 'X'" -> {course: {room}}."""
    prefs = {}
    for r in rows:
        m = re.search(r"preferred_room\s*=\s*'([^']+)'", r.get("rule", ""))
        if m and r.get("constraint_type", "").lower().startswith("pref"):
            for course in _split(r.get("applies_to", "")):
                prefs.setdefault(course, set()).add(m.group(1))
    return prefs


def load_data(data_dir="data"):
    p = lambda name: os.path.join(data_dir, name)

    for name in ("courses.csv", "rooms.csv", "time_slots.csv", "instructors.csv", "student_cohorts.csv", "constraints.csv"):
        if not os.path.isfile(p(name)):
            raise ValueError(f"Missing required dataset: {name}")

    slots = {}
    for r in _read(p("time_slots.csv")):
        slots[r["slot_id"]] = Slot(r["slot_id"], r["day"], _minutes(r["start_time"]),
                                   _minutes(r["end_time"]), r["start_time"], r["end_time"])

    rooms = {}
    for r in _read(p("rooms.csv")):
        phys = _to_int(r.get("physical_capacity"), 0)
        cap = _to_int(r.get("scheduling_capacity"), phys)
        avail = r.get("available_for_regular_classes", "Yes").lower() in ("yes", "y", "true", "1")
        rooms[r["room_id"]] = Room(r["room_id"], r.get("building", ""), cap,
                                   r.get("room_type", ""), avail)

    instructors = {}
    for r in _read(p("instructors.csv")):
        iid = r.get("instructor_id") or r["instructor_name"]
        instructors[iid] = Instructor(iid, r.get("instructor_name", iid), _split(r.get("courses", "")),
                                      expand_slot_tokens(r.get("unavailable_slots", ""), slots),
                                      expand_slot_tokens(r.get("preferred_slots", ""), slots))

    courses = {}
    for r in _read(p("courses.csv")):
        courses[r["course_id"]] = Course(
            r["course_id"], r.get("level", ""), _split(r.get("instructors", "")),
            expand_room_hints(r.get("rooms_mentioned", ""), set(rooms)),
            _to_int(r.get("enrollment")), r.get("room_type", ""))

    cohorts = {}
    for r in _read(p("student_cohorts.csv")):
        cohorts[r["cohort_id"]] = Cohort(r["cohort_id"], _to_int(r.get("size"), 0),
                                         _split(r.get("mandatory_courses", "")))

    weights = {"S1": 10, "S2": 5, "S3": 8, "S4": 12, "S5": 6, "ROOM_PREF": 5, "HARD": 1000}
    cfg = p("sample_constraints.json")
    if os.path.exists(cfg):
        try:
            with open(cfg, encoding="utf-8") as f:
                for c in json.load(f).get("soft_constraints", []):
                    key = c["id"].split("_")[0]
                    if key in weights:
                        weights[key] = c["penalty_weight"]
        except (ValueError, KeyError):
            pass

    if not courses or not rooms or not slots:
        raise ValueError("Courses, rooms and time slots must be nonempty")
    if any(s.start >= s.end or s.start < 0 or s.end > 1440 for s in slots.values()):
        raise ValueError("Invalid time slot interval")
    if any(r.capacity < 0 for r in rooms.values()) or any(h.size < 0 for h in cohorts.values()):
        raise ValueError("Capacities and cohort sizes must be nonnegative")
    if any(c.enrollment is not None and c.enrollment < 0 for c in courses.values()):
        raise ValueError("Enrollment must be nonnegative")
    for h in cohorts.values():
        missing = set(h.courses) - courses.keys()
        if missing:
            raise ValueError(f"{h.id} requires unknown courses: {sorted(missing)}")

    # These rules are implemented directly by the model. Handle explicit room
    # exclusions as data as well, rather than relying only on availability flags.
    # Preference coverage: explicit preferred-room requests and utilization are
    # scored by the model. Activity suitability needs an explicit room_type;
    # the supplied mixed lecture/lab context is not a hard type declaration.
    # Historical placement and balancing sections cannot be scored because the
    # supplied schema has neither historical assignments nor section rosters.
    rules = _read(p("constraints.csv"))
    supported = {"enrollment <= scheduling_capacity",
                 "no overlapping meetings in same room",
                 "no overlapping meetings for same instructor",
                 "available_for_regular_classes = 'Yes'"}
    for rule in rules:
        if rule.get("constraint_type", "").lower() != "hard":
            continue
        text = rule.get("rule", "")
        excluded = re.fullmatch(r"room_id\s*!=\s*'([^']+)'", text)
        if excluded:
            if excluded.group(1) in rooms:
                rooms[excluded.group(1)].available = False
        elif text not in supported:
            raise ValueError(f"Unsupported hard constraint: {text}")

    return Data(slots, rooms, instructors, courses, cohorts,
                _parse_preferred_rooms(rules), weights)
