# CLAUDE.md

## Project Overview

Classroom Randomize Experiments -- a Flask web app for running randomized behavioral economics experiments in university classrooms. A teacher (host) creates a classroom, student groups build surveys with treatment/control arms, and on class day students answer on their phones while the host views results on a dashboard.

## Commands

```bash
# Local dev
python run.py                    # Starts Flask on localhost:5000

# Production (Render)
gunicorn --worker-class eventlet -w 1 app:app  # See render.yaml

# Database
flask init-db                    # Reset database from schema.sql
```

## Architecture

### Pure HTTP -- No WebSockets on the Client

The app originally used Flask-SocketIO for real-time updates but this was removed from the client side because SocketIO connections were unreliable on phones and caused severe slowdowns. The current architecture:

- **Students** poll `GET /c/<code>/student/state` every 3 seconds to detect survey activation, and submit answers via `POST /c/<code>/student/submit`
- **Host** fetches results on demand by clicking "Refresh Results", which calls `GET /c/<code>/host/state`
- **Host actions** (activate, next, reset) are HTTP POST endpoints that return results directly in the response

### Legacy SocketIO Code

`sockets/events.py` still contains SocketIO event handlers and `app.py` still initializes Flask-SocketIO. These are **not used by any client** but the helper functions in `events.py` (`_get_aggregated_results`, `_build_assignment_payload`, `_is_fully_answered`, `_get_survey_with_arms_and_questions`) are imported by `routes/host.py` and `routes/student.py`. The `host.py` routes still call `socketio.emit()` to notify student rooms of survey activation/deactivation, but since students no longer connect via SocketIO, these broadcasts go to empty rooms and are effectively no-ops.

## Data Flow

### Student Submission
1. Student opens `/c/<code>/student/session` on phone
2. `student.js` polls `/c/<code>/student/state` every 3s
3. When a survey is active, the state endpoint returns the assignment (arm + questions)
4. Student answers and clicks Submit -> `POST /c/<code>/student/submit`
5. Server inserts into `response` table, returns `{ok: true}`
6. On failure, an alert pops up telling the student to retry

### Host Dashboard
1. Host opens `/c/<code>/host/dashboard`
2. On page load, `host.js` calls `GET /c/<code>/host/state` to get current results
3. Host clicks survey in sidebar -> `POST /c/<code>/host/activate` -> returns aggregated results
4. Host clicks "Refresh Results" -> `GET /c/<code>/host/state` -> recounts all votes from DB
5. Host clicks "Next Survey" -> `POST /c/<code>/host/next` -> advances and returns new results

### Arm Assignment
Deterministic via SHA-256: `hash(student_id + ":" + survey_id) % num_arms`. This means a student always gets the same arm for the same survey, even across page refreshes. See `sockets/assignment.py`.

## Database

SQLite with WAL mode. Key tables:

- `classroom` -- code, name, hashed host password, hashed classroom password (for student access)
- `survey` -- title, group_number, is_active flag, belongs to classroom
- `survey_arm` -- treatment/control arms per survey
- `survey_question` -- questions per survey (supports multiple), includes `slider_min`/`slider_max`/`slider_step` for slider type
- `arm_question` -- per-arm question text variants, optional `image_filename` for uploaded images
- `arm_question_option` -- multiple choice options per arm-question
- `participant` -- student name + ID, belongs to classroom
- `response` -- answer records (participant, survey, arm, question, answer_text, answer_index)

The `response` table has a unique index preventing duplicate answers per participant per question. Indexes on `(survey_id, arm_id, question_id)` for fast aggregation.

Two database connection functions exist in `models/db.py`:
- `get_db()` -- uses Flask request context (`g` object), auto-closed on teardown
- `get_socket_db()` -- standalone connection for SocketIO handlers (outside request context)

## Question Types

Five question types are supported. The type is stored per-question in `survey_question.question_type`:

- **multiple_choice** -- single-select buttons, grouped bar chart on dashboard
- **multiple_answer** -- multi-select toggle buttons, stored as JSON array in `answer_text` (e.g., `["Option A","Option C"]`), grouped bar chart on dashboard (same as MC but counts can exceed n since each student can select multiple)
- **numeric** -- number input, mean bar chart + stats table (mean, median, std, min, max) on dashboard
- **short_answer** -- text input (140 char limit), response table on dashboard listing all answers by arm
- **slider** -- range slider input with configurable min/max/step, histogram + stats table on dashboard. Config stored in `survey_question.slider_min`, `slider_max`, `slider_step` columns. The student sees a draggable slider with live value display. Response stored as numeric string in `answer_text`. Histogram bins are computed client-side in `host.js` from the slider config and raw values.

Types that need answer options (multiple_choice, multiple_answer) store them in `arm_question_option`. Types without options (numeric, short_answer, slider) have no rows there. The builder form shows/hides the options section and slider config section based on type. See `typeHasOptions()` in `builder.js`.

## Classroom Access

Two separate passwords protect each classroom:
- **Host password** -- required to access the host dashboard (`/c/host-join`). Only the instructor should know this.
- **Classroom password** -- required for students to join via `/c/join`. The instructor shares this with the class. This prevents unauthorized users from guessing classroom codes.

Both passwords are hashed with SHA-256 and stored in the `classroom` table. The classroom password is set during classroom creation and cannot be changed after (would require a new feature).

## Image Uploads

Survey builders can attach images (PNG, JPEG, PDF) to individual arm-questions. Images are:
- Stored on disk in `UPLOAD_FOLDER` (locally: `instance/uploads/`, on Render: `/data/uploads/` on the persistent disk)
- Named with a UUID prefix to avoid collisions: `{uuid4}_{original_filename}`
- Limited to 2MB per file via Flask's `MAX_CONTENT_LENGTH`
- Served via `GET /uploads/<filename>` route in `app.py`
- Cleaned up from disk when surveys are updated (old images removed) or deleted

In the student view, images render as `<img>` tags above the question text (or as a "View PDF" link for PDFs). In the host dashboard, images appear as thumbnails in the arms detail section.

The builder form uses `enctype="multipart/form-data"`. On edit, existing images are preserved via a hidden `existing_image` form field unless a new file is uploaded.

## Key Design Decisions

- **HTTP over WebSockets**: SocketIO was unreliable on student phones and caused 20+ second hangs. Pure HTTP polling + POST is simpler and works reliably.
- **Manual refresh over auto-update**: The host clicks "Refresh Results" instead of seeing live updates. This avoids expensive server-side aggregation on every student submission (which was a major bottleneck with 30+ students).
- **Deterministic arm assignment**: SHA-256 hash ensures stable assignment without storing it in the database.
- **SQLite**: Simple deployment (no external DB server), WAL mode handles concurrent reads well. Single-writer is acceptable since writes are small INSERTs.

## Gotchas

- `sockets/events.py` functions are used as imports by route handlers even though the SocketIO event handlers themselves are unused. Don't delete the file without moving the helper functions.
- The `handleResultsUpdate` function in `host.js` has a fast-path (update charts in place) and a full-rebuild path. The fast path only activates when the same survey refreshes. Switching surveys always triggers a full rebuild -- don't set `activeSurveyId` before calling `handleResultsUpdate` or the fast path will silently fail.
- Student polling is 3 seconds. This means there's up to a 3-second delay between the host activating a survey and students seeing it.
