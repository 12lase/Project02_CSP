# Project 2 Report: University Class Scheduling & Timetable Optimization

> \[!IMPORTANT\] **AUTOGRADER COMPLIANCE INSTRUCTIONS:** This report is parsed automatically by the autograder. To ensure you receive full credit for your work: 1. **Do not modify** the section headers (`## ...`) or bold field keys (e.g., `**Name:**`, `**Total Courses Configured:**`, `**Video Presentation Link:**`, etc.). 2. **Write your answers directly after** the colon `:` of each field, replacing the placeholder text completely (including the outer brackets `[` and `]`). 3. **Maintain the file structure**. Changing headers, bold titles, or deleting lines can cause the autograder to miss your responses and award 0 marks.

------------------------------------------------------------------------

## Student Information

- **Name:** Tio Oguntade
- **UID (netID):** togun9
- **UIN:** 670893152

------------------------------------------------------------------------

## Section 1: Dataset & University Configuration

- **Total Courses Configured:** 65
- **Total Rooms Configured:** 20
- **Total Time Slots Configured:** 50

------------------------------------------------------------------------

## Section 2: Local Verification & Implemented Solvers

*Check the algorithms and features you successfully ran and verified by placing an `x` in the brackets (e.g., `[x]`):* - \[x\] DataLoader & CSV Parsing - \[x\] Hard Constraint Validation Engine - \[x\] Soft Penalty & Quality Evaluation Engine - \[x\] CSP Backtracking with MRV + LCV + Forward Checking - \[x\] Min-Conflicts CSP Local Search - \[x\] Timetable CSV Export (<studentid>\_timetable.csv)

------------------------------------------------------------------------

## Section 3: Video Presentation & Project Structure

- **Video Presentation Link:** [CS411 Project 2](https://1drv.ms/f/c/1c11c2f2d34565f5/IgA8bdjDQwVVSbscSdcMDLnaARS_GDNhNMDA170B-Ad_k2M?e=JWCFO9)
- **Project Directory Structure:** `app.py` contains the `studentscheduler()` entry point and exports the timetable CSV. The `data/` folder contains the input CSV datasets, constraint configuration, and generated timetable. The `scheduler/` package contains `data_loader.py` for reading the datasets, `model.py` for constraints and penalty evaluation, `csp_solver.py` for backtracking and heuristics, `local_search.py` for Min-Conflicts optimization, and `pipeline.py` for connecting these stages. The `tests/` folder contains scheduler validation tests. `requirements.txt` lists Python dependencies, and `report.md` contains the project report.

``` text
.
├── app.py                      # Main entry point containing studentscheduler()
├── data/                       # Input datasets and generated timetable
│   ├── courses.csv             # Course catalog, instructors, and room hints
│   ├── instructors.csv         # Instructor profiles and course assignments
│   ├── rooms.csv               # Rooms, capacities, types, and availability
│   ├── time_slots.csv          # Weekly slots with days and start/end times
│   ├── student_cohorts.csv     # Cohort sizes and mandatory courses
│   ├── constraints.csv         # Hard constraints and scheduling preferences
│   ├── sample_constraints.json # Constraint descriptions and penalty weights
│   └── togun9_timetable.csv    # Generated timetable
├── scheduler/                  # Scheduling implementation
│   ├── __init__.py             # Package initialization
│   ├── data_loader.py          # CSV parsing and input validation
│   ├── model.py                # CSP model, constraints, and soft penalties
│   ├── csp_solver.py           # Backtracking, MRV, degree, LCV, FC, and AC-3
│   ├── local_search.py         # Min-Conflicts optimization
│   └── pipeline.py             # Loading, solving, validation, and output rows
├── tests/                      # Automated scheduler checks
│   └── test_scheduler.py       # Constraint, export, and failure-case tests
├── report.md                   # Project report
├── requirements.txt            # Python dependencies (pandas, pytest)
├── Project_Guidelines.md       # Project requirements and marking scheme
└── README.md                   # Starter guide
```

------------------------------------------------------------------------

## Section 4: Discussion & Problem Formulation

*Provide your written analysis for each point by replacing the bracket placeholders below:*

- **How did you formulate the variables, domains, and constraints for this scheduling problem?**

  The variables represent the courses we are trying to schedule. In this case, we are changing each course's time and room assignment to find a feasible schedule. The domain for each course includes the combinations of time (`slot_id`) and room (`room_id`) that remain after filtering out unsuitable rooms and unavailable instructor times. The constraints are split into hard constraints, like avoiding overlapping classes for instructors and student cohorts, preventing room double-bookings, respecting room capacity and type, and scheduling every course, and soft constraints, like instructor preferences, oversized rooms, student gaps, fatigue, and travel between buildings. One limitation is that 45 courses have no enrollment data, so their room capacity cannot be fully verified. For courses without explicit enrollment but with mandatory cohorts, I used the combined cohort sizes as an estimate.

- **Compare CSP Backtracking (with heuristics) vs Local Search (Min-Conflicts) in terms of scalability, completeness, and solution quality.**

  | Aspect | CSP Backtracking (with heuristics) | Local Search (Min-Conflicts) |
  |------------------------|------------------------|------------------------|
  | Scalability | Can struggle with larger models because the number of combinations grows quickly. MRV, degree, LCV, and forward checking help reduce the search. | Can work better with larger models by adjusting assignments instead of exploring every combination, but it can get stuck. |
  | Completeness | Can give a definite answer about whether a solution exists if allowed to finish an exhaustive search. My implementation has a node limit, so reaching that limit does not prove there is no solution. | Can reach its step or time limit without finding a valid solution. That does not mean no solution exists. |
  | Solution quality | Finds a feasible schedule but does not guarantee a low soft penalty score. | Looks for a lower soft penalty score, but does not guarantee the lowest possible score. |

  In my run, backtracking found a feasible schedule with a penalty score of 314. Min-Conflicts local search then reduced it to 160 while preserving the hard constraints.

- **How can modern AI / LLM techniques be combined with CSP solvers for real-world automated university scheduling?**

  I feel AI can be useful when patterns in previous schedules suggest which assignments to try first. This could help the solver find an answer faster down a promising path. An LLM could also turn an instructor's request into a structured preference or explain why certain classes conflict. Basically, AI could help guide the search and make the system easier to use, while the CSP solver still checks that the schedule follows the rules. Predictions alone should not remove possible assignments or decide that there is no solution, because they could be wrong.