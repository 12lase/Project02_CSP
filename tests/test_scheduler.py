"""Project checks, independent of any course autograder."""
import csv
from itertools import combinations
from pathlib import Path

import pytest

from app import studentscheduler
from scheduler.data_loader import load_data
from scheduler.model import Timetable
from scheduler.pipeline import solve
from scheduler.local_search import min_conflicts_optimize

ROOT = Path(__file__).resolve().parents[1]


def write_csv(path, rows):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def dataset(tmp_path):
    rows = {
        'courses.csv': [dict(course_id=c, instructors='I', enrollment='20', room_type='Computer Lab', rooms_mentioned='R') for c in ('A', 'B')],
        'rooms.csv': [dict(room_id='R', building='X', physical_capacity='100', scheduling_capacity='25', room_type='Computer Lab', available_for_regular_classes='Yes')],
        'time_slots.csv': [dict(slot_id=s, day='Monday', start_time=start, end_time=end) for s, start, end in [('S1', '09:00', '10:00'), ('S2', '10:00', '11:00'), ('S3', '11:00', '12:00')]],
        'instructors.csv': [dict(instructor_id='I', instructor_name='I', courses='A;B', unavailable_slots='S1', preferred_slots='S3')],
        'student_cohorts.csv': [dict(cohort_id='H', size='20', mandatory_courses='A;B')],
        'constraints.csv': [dict(constraint_type='Hard', rule='enrollment <= scheduling_capacity', applies_to='All courses')],
    }
    for name, data in rows.items():
        write_csv(tmp_path / name, data)
    return tmp_path, rows


def check_independently(data, assignment):
    assert set(assignment) == set(data.courses)  # H6
    for c, (s, r) in assignment.items():
        course, room = data.courses[c], data.rooms[r]
        required = course.enrollment
        if required is None:
            sizes = [h.size for h in data.cohorts.values() if c in h.courses]
            required = sum(sizes) if sizes else None
        assert room.available
        assert required is None or room.capacity >= required  # H2
        assert not course.room_type or course.room_type.lower() in room.room_type.lower()
        teachers = [i for i in data.instructors.values() if c in i.courses or i.id in course.instructor_names or i.name in course.instructor_names]
        assert all(s not in i.unavailable for i in teachers)  # H4
    for a, b in combinations(assignment, 2):
        sa, ra = assignment[a]
        sb, rb = assignment[b]
        x, y = data.slots[sa], data.slots[sb]
        if x.day == y.day and x.start < y.end and y.start < x.end:
            assert ra != rb  # H1
            for i in data.instructors.values():
                taught = set(i.courses) | {c.id for c in data.courses.values() if i.id in c.instructor_names or i.name in c.instructor_names}
                assert not {a, b} <= taught  # H3
            assert not any({a, b} <= set(h.courses) for h in data.cohorts.values())  # H5


def test_provided_data_and_export(tmp_path):
    path = studentscheduler(ROOT / 'data', tmp_path, 'review')
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    data = load_data(ROOT / 'data')
    assert len(rows) == len(data.courses) == 65
    check_independently(data, {r['course_id']: (r['slot_id'], r['room_id']) for r in rows})
    for row in rows:
        slot = data.slots[row['slot_id']]
        assert (row['day'], row['start_time'], row['end_time']) == (slot.day, slot.start_text, slot.end_text)


def test_changed_dataset(dataset):
    directory, _ = dataset
    csp, result = solve(directory, ls_steps=20, verbose=False)
    check_independently(csp.data, result)
    assert {s for s, _ in result.values()} == {'S2', 'S3'}


@pytest.mark.parametrize('failure', ['capacity', 'type', 'availability', 'room_unavailable', 'overlap', 'missing_course'])
def test_impossible_datasets_do_not_export(dataset, tmp_path, failure):
    directory, rows = dataset
    if failure == 'capacity':
        rows['rooms.csv'][0]['scheduling_capacity'] = '19'
    elif failure == 'type':
        rows['rooms.csv'][0]['room_type'] = 'Classroom'
    elif failure == 'availability':
        rows['instructors.csv'][0]['unavailable_slots'] = 'Monday'
    elif failure == 'room_unavailable':
        rows['rooms.csv'][0]['available_for_regular_classes'] = 'No'
    elif failure == 'overlap':
        for slot in rows['time_slots.csv']:
            slot.update(start_time='09:00', end_time='11:00')
    else:
        rows['student_cohorts.csv'][0]['mandatory_courses'] += ';MISSING'
    for name, data in rows.items():
        write_csv(directory / name, data)
    output = tmp_path / 'output'
    with pytest.raises(ValueError):
        studentscheduler(directory, output, 'invalid')
    assert not (output / 'invalid_timetable.csv').exists()


def test_enrollment_is_not_capped_and_cohorts_are_summed(dataset):
    directory, rows = dataset
    for course in rows['courses.csv']:
        course['enrollment'] = ''
    rows['student_cohorts.csv'].append(dict(cohort_id='H2', size='10', mandatory_courses='A'))
    for name, data in rows.items():
        write_csv(directory / name, data)
    csp = Timetable(load_data(directory))
    assert csp.enrollment['A'] == 30
    assert csp.domains['A'] == []


@pytest.mark.parametrize('kind', ['H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'unknown'])
def test_validator_detects_each_hard_constraint(dataset, kind):
    directory, _ = dataset
    csp = Timetable(load_data(directory))
    placement = {'A': ('S2', 'R'), 'B': ('S3', 'R')}
    if kind in ('H1', 'H3', 'H5'):
        placement['B'] = placement['A']
    elif kind == 'H2':
        csp.data.rooms['R'].room_type = 'Classroom'
    elif kind == 'H4':
        placement['A'] = ('S1', 'R')
    elif kind == 'H6':
        del placement['B']
    else:
        placement['A'] = ('missing', 'R')
    assert csp.violations(placement)['H6' if kind == 'unknown' else kind]


def test_local_search_improves_preferences_and_preserves_feasibility(dataset):
    directory, _ = dataset
    csp = Timetable(load_data(directory))
    # Allow B to share the preferred slot, but with a distinct room/instructor/cohort.
    csp.data.instructors['I'].courses = ['A']
    csp.data.courses['B'].instructor_names = []
    csp.data.cohorts['H'].courses = ['A']
    from dataclasses import replace
    csp.data.rooms['R2'] = replace(csp.data.rooms['R'], id='R2')
    csp = Timetable(csp.data)
    initial = {'A': ('S2', 'R'), 'B': ('S1', 'R')}
    result, _ = min_conflicts_optimize(csp, initial, max_steps=100, noise=1.0)
    check_independently(csp.data, result)
    assert csp.soft_cost(result) < csp.soft_cost(initial)


def test_invalid_optimizer_output_is_rejected(dataset, monkeypatch):
    directory, _ = dataset
    monkeypatch.setattr('scheduler.pipeline.min_conflicts_optimize', lambda *a, **kw: ({}, 0))
    with pytest.raises(ValueError, match='No valid timetable'):
        solve(directory, verbose=False)


def test_explicit_room_exclusion(dataset):
    directory, rows = dataset
    rows['constraints.csv'] = [dict(constraint_type='Hard', rule="room_id != 'R'", applies_to='R')]
    write_csv(directory / 'constraints.csv', rows['constraints.csv'])
    with pytest.raises(ValueError, match='No legal'):
        solve(directory, verbose=False)


def test_unavailability_blocks_overlapping_slot_ids(dataset):
    directory, rows = dataset
    rows['time_slots.csv'][1].update(start_time='09:30', end_time='10:30')
    write_csv(directory / 'time_slots.csv', rows['time_slots.csv'])
    csp = Timetable(load_data(directory))
    assert all(s == 'S3' for s, _ in csp.domains['A'])
    assert csp.violations({'A': ('S2', 'R'), 'B': ('S3', 'R')})['H4']


def test_soft_rewards_cannot_buy_hard_violations(dataset):
    directory, _ = dataset
    csp = Timetable(load_data(directory))
    csp.data.weights['S1'] = 100000
    initial = {'A': ('S2', 'R'), 'B': ('S3', 'R')}
    result, _ = min_conflicts_optimize(csp, initial, max_steps=100, noise=0)
    check_independently(csp.data, result)
    assert csp.soft_cost(result) <= csp.soft_cost(initial)


def test_missing_dataset_is_explicit(dataset):
    directory, _ = dataset
    (directory / 'courses.csv').unlink()
    with pytest.raises(ValueError, match='Missing required dataset'):
        load_data(directory)


def test_unknown_hard_rule_is_not_silently_ignored(dataset):
    directory, rows = dataset
    rows['constraints.csv'][0]['rule'] = 'maximum classes per day = 1'
    write_csv(directory / 'constraints.csv', rows['constraints.csv'])
    with pytest.raises(ValueError, match='Unsupported hard constraint'):
        load_data(directory)


def test_failed_run_preserves_existing_output(dataset, tmp_path):
    directory, rows = dataset
    rows['rooms.csv'][0]['scheduling_capacity'] = '1'
    write_csv(directory / 'rooms.csv', rows['rooms.csv'])
    output = tmp_path / 'previous'
    output.mkdir()
    target = output / 'existing_timetable.csv'
    target.write_text('previous schedule\n')
    with pytest.raises(ValueError):
        studentscheduler(directory, output, 'existing')
    assert target.read_text() == 'previous schedule\n'
