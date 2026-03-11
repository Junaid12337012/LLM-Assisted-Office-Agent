# Office Agent Roadmap

This roadmap keeps the platform disciplined:

- Phase 1 builds the deterministic engine.
- Phase 2 makes runs reliable and reviewable.
- Phase 3 adds controlled AI orchestration.
- Phase 4 adds operator mode for daily supervised work.

## Roadmap Table

| Phase | Purpose | Core Deliverables | What Stays Out |
| --- | --- | --- | --- |
| 1 | Build the engine | command registry, workflow engine, desktop/browser/file controllers, logging, GUI command bar, one reliable workflow | AI planning, autonomous queues, broad OCR |
| 2 | Stabilize the system | validator, recovery rules, evidence capture, review queue, narrow OCR/document pipeline, better run history | free-form AI control, broad vision autonomy |
| 3 | Add the brain | natural-language interpreter, planner, tool gating, confidence rules, assistant plan preview, controlled multi-workflow selection | raw model-controlled clicks, bypassing workflows or policy |
| 4 | Run the day | operator/session manager, task queue, checkpoints, resume, exception queue, summaries, operator dashboard | uncontrolled all-day autonomy, risky action bypass |

## Phase Details

### Phase 1

Goal:
Build the deterministic automation core.

Ship:
- typed commands
- workflow definitions
- safe command execution
- desktop GUI and CLI
- run history and logs

Exit criteria:
- one to three workflows run end to end
- failures are visible in logs
- app starts fast and can be demoed locally

### Phase 2

Goal:
Make the core reliable under real office conditions.

Ship:
- validator after important steps
- recovery rules for common failures
- evidence capture on failures
- review queue for uncertain cases
- narrow OCR/document workflow

Exit criteria:
- uncertain runs go to review instead of silently failing
- common failures recover automatically
- every run leaves evidence and step history

### Phase 3

Goal:
Let the user type intent, while the platform still keeps control.

Ship:
- natural-language interpreter
- planner and confidence policy
- approved tool/workflow registry
- structured plan preview
- confirmation path for risky or ambiguous instructions

Exit criteria:
- natural requests map to known workflows
- risky requests require review
- plans remain structured and auditable

### Phase 4

Goal:
Operate a supervised daily work session, not just one workflow at a time.

Ship:
- `operator/session_manager.py`
- `operator/task_queue.py`
- `operator/checkpoint_manager.py`
- `operator/exception_queue.py`
- `operator/summary_manager.py`
- operator dashboard with queue, active task, blocked items, review items, pause/resume, and summary panels

Exit criteria:
- one click can start a multi-task work session
- interrupted sessions resume from the last safe checkpoint
- known failures recover without stopping the full day
- blocked items move to exception/review queues
- end-of-day summary is generated automatically

## Recommended Build Order For Phase 4

1. `task_queue.py`
2. `session_manager.py`
3. checkpoints and resume
4. exception queue
5. daily summary generation
6. AI-assisted prioritization and exception interpretation

## Data You Need Before Phase 4 Becomes Real

- your top recurring job types
- queue priority rules
- which actions always require approval
- which failures can be retried automatically
- what counts as a completed day
- what should appear in the daily summary

## Design Rules

- AI decides what to run, not how to bypass execution rules.
- Validation and policy stay inside your platform.
- Low-confidence decisions escalate instead of guessing.
- Every operator decision should be logged, reviewable, and resumable.

## Current Repo Status

- Phase 1 is implemented.
- Phase 2 MVP is implemented.
- Phase 3 MVP is implemented with a controlled local planner.
- Phase 4 foundation is now in progress with operator sessions, queue state, checkpoints, and an operator dashboard.
