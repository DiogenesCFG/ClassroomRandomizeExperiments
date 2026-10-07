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

### Student Sign-in (roster)
1. Student joins at `/c/join` with classroom code + classroom password
2. `/c/<code>/signin` (`routes/account.py`): student types their SIS ID. Unknown or removed IDs get "ID not found. Try again or contact your instructor."
3. First time: "Are you {first name}?" confirmation, then they choose a password (stored with werkzeug's salted hash in `roster_student.password_hash`). Later: SIS ID + password.
4. Signed-in student lands in the lobby (`/c/<code>/lobby`): live-session card (polls `/c/<code>/live` every 5s), pending group invites, and their group(s)
5. Session key `roster_student_<classroom_id>` identifies the student; `ensure_participant_session()` maps them to a `participant` row (name = roster full name, student_id = SIS ID) so the live-session code is unchanged

### Student Submission
1. Student opens `/c/<code>/student/session` on phone (requires roster sign-in)
2. `student.js` polls `/c/<code>/student/state` every 3s
3. When a survey is active, the state endpoint returns the assignment (arm + questions)
4. Student answers and clicks Submit -> `POST /c/<code>/student/submit`
5. Server inserts into `response` table, returns `{ok: true}`
6. On failure, an alert pops up telling the student to retry

### Host Pages
After logging in, the host lands on the **instructor home** (`/c/<code>/host/home`, `host/home.html`): class phase switches, peer-feedback progress, roster/surveys/data cards, and a collapsed danger zone. Its **Start live session** button opens the live-session page (`/c/<code>/host/dashboard`, `host/dashboard.html`), which only has what class needs: survey list, Next/Reset, results, QR code, classroom code/password, block-designers toggle.

### Live Session
1. Host opens `/c/<code>/host/dashboard` (Start live session)
2. On page load, `host.js` calls `GET /c/<code>/host/state` to get current results
3. Host clicks survey in sidebar -> `POST /c/<code>/host/activate` -> returns aggregated results
4. Host clicks "Refresh Results" -> `GET /c/<code>/host/state` -> recounts all votes from DB
5. Host clicks "Next Survey" -> `POST /c/<code>/host/next` -> advances and returns new results

### Arm Assignment
Deterministic via SHA-256: `hash(student_id + ":" + survey_id) % num_arms`. This means a student always gets the same arm for the same survey, even across page refreshes. See `sockets/assignment.py`.

## Database

SQLite with WAL mode. Key tables:

- `classroom` -- code, name, hashed host password, hashed classroom password (for student access), `classroom_password_plain` (recoverable plaintext for display/QR), `block_designers` flag
- `survey` -- title, group_number, is_active flag, belongs to classroom
- `survey_arm` -- treatment/control arms per survey
- `survey_question` -- questions per survey (supports multiple), includes `slider_min`/`slider_max`/`slider_step` for slider type
- `arm_question` -- per-arm question text variants, optional `image_filename` for uploaded images
- `arm_question_option` -- multiple choice options per arm-question
- `participant` -- student name + ID, belongs to classroom (created from the roster on sign-in)
- `roster_student` -- class roster: `sis_id`, `full_name` (as in the uploaded file, e.g. "Last, First"), `first_name` (shown in the sign-in confirmation), `password_hash` (NULL = not signed up / reset), `hidden` (removed from class but kept for past data)
- `group_member` -- survey designers; `roster_student_id` links to the roster, `name`/`sis_code` are copied from it so exports and block-designers work unchanged
- `team_invite` -- pending invitations to join a survey's group
- `classroom.max_groups_per_student` -- NULL = no limit
- `classroom.max_group_size` -- members per group, default 5, NULL = no limit
- `response` -- answer records (participant, survey, arm, question, answer_text, answer_index)

The `response` table has a unique index preventing duplicate answers per participant per question. Indexes on `(survey_id, arm_id, question_id)` for fast aggregation.

Two database connection functions exist in `models/db.py`:
- `get_db()` -- uses Flask request context (`g` object), auto-closed on teardown
- `get_socket_db()` -- standalone connection for SocketIO handlers (outside request context)

## Question Types

Five question types are supported. The type is stored per-question in `survey_question.question_type`:

- **multiple_choice** -- single-select buttons, grouped bar chart on dashboard
- **multiple_answer** -- multi-select toggle buttons, stored as JSON array in `answer_text` (e.g., `["Option A","Option C"]`), grouped bar chart on dashboard (same as MC but counts can exceed n since each student can select multiple)
- **numeric** -- number input, histogram + stats table (mean, median, std, min, max) on dashboard. Bins are computed client-side in `host.js` using adaptive logic: exact bins for small integer ranges (≤19 distinct values), grouped bins (~10) for larger/decimal ranges
- **short_answer** -- text input (140 char limit), response table on dashboard listing all answers by arm
- **slider** -- range slider input with configurable min/max/step, histogram + stats table on dashboard. Config stored in `survey_question.slider_min`, `slider_max`, `slider_step` columns. The student sees a draggable slider with live value display. Response stored as numeric string in `answer_text`. Histogram bins are computed client-side in `host.js` from the slider config and raw values.

Types that need answer options (multiple_choice, multiple_answer) store them in `arm_question_option`. Types without options (numeric, short_answer, slider) have no rows there. The builder form shows/hides the options section and slider config section based on type. See `typeHasOptions()` in `builder.js`.

## Classroom Access

Two separate passwords protect each classroom:
- **Host password** -- required to access the host dashboard (`/c/host-join`). Only the instructor should know this.
- **Classroom password** -- required for students to join via `/c/join`. The instructor shares this with the class. This prevents unauthorized users from guessing classroom codes.

Both passwords are hashed with SHA-256 and stored in the `classroom` table. The classroom password is also stored in plaintext (`classroom_password_plain`) so the host can see it on the dashboard and it can be embedded in the QR code URL. The classroom creation form requires both passwords to be typed twice (confirm fields) with server-side validation. Every password box gets a show/hide eye button from `static/js/password-toggle.js` (loaded in `base.html`), which wraps the input in an input-group and moves its valid/invalid feedback inside. Classroom codes are unique, uppercased, exact-match; a taken code is refused with a message naming it.

## Roster and Teams

- **Roster upload** (`routes/roster.py`, `models/roster.py`): host uploads a CSV at classroom creation or on `/c/<code>/host/roster/`. Columns are guessed from headers (`guess_mapping`) and confirmed on a preview page (`host/roster_import.html`) that re-posts the CSV text in a hidden textarea (no server-side temp file). Canvas gradebook exports work as-is ("Points Possible" and "Student, Test" rows are skipped). Combined names are split at the first comma (`split_full_name`). Re-uploading upserts by SIS ID and keeps passwords and groups; optional "remove students not in this file".
- **Roster page**: add a student, one-click password reset (clears the hash; next sign-in goes through first-time setup), remove/restore (hidden flag), max groups per student, max members per group.
- **Teams**: creating a survey adds the creator as a member and assigns the next group number automatically (only the host can change group numbers). Members invite classmates by name (`<datalist>` picker in `builder.js`); invitees accept/decline in their lobby. Invites can always be sent while the group has room, but accepting is blocked if it would exceed `max_groups_per_student` or the group already has `max_group_size` members (a full group also can't send invites; lowering the limit never removes anyone). Members can leave with a confirm, except the last member. Only group members (or the host) can edit, delete, or download a survey -- there are no survey passwords.
- **Lobby "My groups" table**: group #, title, member count (hover/tap for names), design warnings, response count with a download link.
- **Edit lock**: `classroom.surveys_locked`, set from the dashboard's Class phase panel (`POST /c/<code>/host/phase`). Blocks students' survey create/edit/autosave/delete and group invite/accept/leave; the host can still edit. Previews and downloads keep working.

## Class Phases, Peer Feedback, Early Surveys

All in `routes/feedback.py` and `models/feedback.py`.

- **Class phase** (dashboard): Building -> Locked -> Feedback open -> Feedback closed. "Next step" moves forward (with a confirm); individual switches set `surveys_locked`, `feedback_open`, `feedback_released` independently, with warnings for odd combinations. `class_phase()` derives the current step. Nothing is deleted when moving back.
- **When comments open** (`survey_commentable()`): a survey takes comments, and classmates can view/preview it, once it has gone live: `survey.went_live` (set the first time the host activates it, never cleared) or `early_open`. It stays open after the host moves on or unlocks surveys, and closes with the rest when feedback closes; sending still requires the Feedback open phase. Other-platform surveys open when surveys are locked. Assigned groups only appear once surveys are locked (`feedback_started()`); before that the lobby shows a stand-in, plus drafts/extras on surveys that already ran early. Refused notes make `get_note` return `not_live`, which hides the note box.
- **Review assignments** (`review_assignment`): created when surveys are locked (or comments opened, or the required count changes after that) by `ensure_assignments()`. Each active student gets `classroom.reviews_required` groups, never their own. Each try is round-based (most-constrained students first, random among the least-reviewed groups) plus a rebalancing pass so group loads differ by at most ~1, then a swap pass that trades targets between students to remove teammate overlaps without changing loads. Up to `ATTEMPTS` randomized tries (capped at `TIME_BUDGET` seconds) keep the best: even loads first, then no two members of a group reviewing the same group (achieved in tests for 100 students / 30 groups of 1-5 with up to 5 required; beyond that it's impossible and overlaps are minimized). Existing assignments are never reshuffled; invalid ones (student joined that group) are dropped and replaced. Late roster additions are topped up on their first lobby visit. The first `reviews_required` assignments (by id) are "required"; the rest are optional.
- **Comments** (`feedback`, one per student per survey): `sent_at` NULL = private draft. Drafts can be saved once the survey has gone live; sending/editing a sent comment requires `feedback_open`. Required comments can't be deleted; extras can. Own-group comments are refused. Groups see sent comments only when `feedback_released`, anonymized as "Reviewer N" (`received_feedback`).
- **Live notes**: after submitting a live survey, the student page offers a collapsed "Add a note" box (`/c/<code>/feedback/<id>/note`) that saves a private draft; `student.js` fires a `survey-submitted` event.
- **View survey** (`/c/<code>/survey/<id>/view`): all arms side by side; open to classmates once the survey has gone live (see above), so nobody sees the arms before answering. Respondent previews follow the same rule (`_can_preview` in `builder.py`).
- **Early surveys**: host allows per survey (`survey.early_allowed`, Manage Surveys page). Group submits with a deadline date (`early_open`, `early_deadline_utc` = end of that day in the group's browser time zone, `early_deadline_label`); this locks the survey for the group (`_locked_for(classroom, survey)`) until the host unlocks it. Classmates answer from the lobby's "Open surveys" (`/c/<code>/student/open/<id>`, same `session.html` with `POLL_ONCE`). The survey still runs in the live sequence. `student.submit_answer_http` only accepts answers for the active survey or an early survey before its deadline.
- **Other-platform surveys** (`survey.external`, `external_note`): a group registers normally and ticks "We're running our survey on another platform" in the builder (e.g. Google Forms, randomized and emailed by the group itself). Arms and questions then become optional: their fieldset (`#in-app-design`) is disabled so it isn't validated or posted, and `_save_edit` only saves the title and note, leaving any stored arms/questions untouched (unticking brings them back). The group keeps its group number, presents in order and gets review assignments; View survey shows their note. In the live session it's listed but not clickable, `activate` refuses it and `next` skips it. It can't open early and has no warnings. Exports keep a placeholder row in `all_responses`, `surveys_config` and `survey_participation`, and `survey_designers` has a `runs` column.
- **First-visit tours** (Driver.js 1.9.0 from jsDelivr + `static/js/tour.js`): the lobby and the survey page dim the page and walk through its parts. Each template defines `window.pageTour(auto)` with its steps; steps whose element isn't on the page are skipped, so one list covers every page state. Shown once per student, recorded in `roster_student.tours_seen` via `POST /c/<code>/tour/<name>/seen` (names: `lobby`, `builder`, `builder_edit`). The survey-page tour runs in full on whichever page a student opens first; someone who saw it on the create page gets a short edit-only version (steps marked `edit: true`) on their first edit-page visit. It never starts for the host or on a locked page. "Show me around" links replay them.
- **Presentation order**: the lobby lists every survey by group number (the live-session order) with its members, highlighting the student's own group.
- **Grading exports**: `feedback.csv` (every comment plus required-but-missing rows) and `feedback_summary.csv` (required sent / required, extras) via the dashboard and the zip.

## Survey Builder Aids

- **Autosave** (edit page only, `builder.js` + `POST /c/<code>/builder/<id>/autosave`): saves the whole form ~1.5s after any change. Invalid forms aren't saved; the status bar shows the first error. Uploaded images are only stored once the form is valid. Autosave is refused once the survey has responses (saving recreates arms/questions, which deletes responses) or when locked.
- **Discard all changes from this session**: the form as first loaded in the browser tab is kept in `sessionStorage`; discarding posts it back through the autosave endpoint. No versions are stored server-side. Replaced images stay on disk for 24h (`_cleanup_orphan_uploads`) so a discard can still reference them.
- **Copy from {first arm}**: per arm-question button copying the first arm's text, options and saved image.
- **Warnings** (`survey_warnings` in `models/survey.py`): flags one-arm surveys and pairs of arms identical in every question. Images are compared by file content hash, so the same picture uploaded twice counts as identical.
- **Preview survey** (`/c/<code>/builder/<id>/preview?arm=N`): the real student page (`student/session.html` with `PREVIEW_MODE`) for a chosen arm; submit is a no-op.
- **Preview dashboard** (`/c/<code>/builder/<id>/preview-dashboard?n=30`): the dashboard's results area and `host.js`, fed random sample responses from `models/preview.py` through `_aggregate_responses` (split out of `_get_aggregated_results`). Nothing is written to the database.
- **Anonymized downloads**: each roster student has a random `anon_id` (e.g. `R-7KQ2PX`, unique, generated on import and backfilled at startup). Students download their survey's responses as one row per respondent keyed by `anon_id` (`export_survey_responses_anon_csv`); names/IDs and the participation export are host-only. The host's all-responses and participants (roster) exports include `respondent_id` as the key.

## Image Uploads

Survey builders can attach images (PNG, JPEG only -- PDF was removed) to individual arm-questions. Images are:
- Stored on disk in `UPLOAD_FOLDER` (locally: `instance/uploads/`, on Render: `/data/uploads/` on the persistent disk)
- Named with a UUID prefix to avoid collisions: `{uuid4}_{original_filename}`
- Limited to 5MB per file via Flask's `MAX_CONTENT_LENGTH`
- Served via `GET /uploads/<filename>` route in `app.py`
- Cleaned up from disk when surveys are updated (old images removed) or deleted

In the student view, images render as `<img>` tags above the question text. In the host dashboard, images appear as thumbnails in the arms detail section. The host can also view all uploaded images across surveys from `GET /c/<code>/host/images` (the image gallery).

The builder form uses `enctype="multipart/form-data"`. On edit, existing images are preserved via a hidden `existing_image` form field unless a new file is uploaded.

## Block Designers

The host can toggle "Block survey designers" on the dashboard. When enabled, students whose SIS ID appears in the `group_member` table for the active survey are shown a "blocked" state instead of the survey questions. This prevents designers from biasing their own experiment. The toggle calls `POST /c/<code>/host/toggle-block-designers`, which flips the `block_designers` column on the `classroom` table. The student state endpoint checks this flag and returns `state: 'blocked_designer'` for matching students.

## QR Code

The host dashboard displays a QR code that encodes the join URL (`/c/join?code=XXX&password=YYY`). The join page reads the `code` and `password` query parameters and pre-fills the form fields. Generated client-side using the [qrcodejs](https://github.com/davidshimjs/qrcodejs) library via CDN. The QR container has a forced white background so it remains scannable in dark mode.

## Dark / Light Mode

The navbar has a Light/Dark switch (`toggleTheme()` in `base.html`); the choice is saved in `localStorage` (`theme`), and without one the app follows the browser's `prefers-color-scheme`. The inline script in `base.html` runs before the page renders to prevent a flash of the wrong theme. Light mode is warm rather than white: `style.css` overrides Bootstrap's `--bs-body-bg` (cards, menus, inputs, tables) and related variables with off-white tones, and the page background is a shade darker. Dark mode uses Bootstrap's built-in dark theme with minor CSS overrides for survey list items.

## Key Design Decisions

- **HTTP over WebSockets**: SocketIO was unreliable on student phones and caused 20+ second hangs. Pure HTTP polling + POST is simpler and works reliably.
- **Manual refresh over auto-update**: The host clicks "Refresh Results" instead of seeing live updates. This avoids expensive server-side aggregation on every student submission (which was a major bottleneck with 30+ students).
- **Deterministic arm assignment**: SHA-256 hash ensures stable assignment without storing it in the database.
- **SQLite**: Simple deployment (no external DB server), WAL mode handles concurrent reads well. Single-writer is acceptable since writes are small INSERTs.

## Gotchas

- `sockets/events.py` functions are used as imports by route handlers even though the SocketIO event handlers themselves are unused. Don't delete the file without moving the helper functions.
- The `handleResultsUpdate` function in `host.js` has a fast-path (update charts in place) and a full-rebuild path. The fast path only activates when the same survey refreshes. Switching surveys always triggers a full rebuild -- don't set `activeSurveyId` before calling `handleResultsUpdate` or the fast path will silently fail.
- Student polling is 3 seconds. This means there's up to a 3-second delay between the host activating a survey and students seeing it.
- The QR code container must have a forced white background (`background:#ffffff`) or it becomes invisible in dark mode. Don't remove this inline style.
- `classroom_password_plain` is only populated for classrooms created after this feature was added. Older classrooms will show an empty password on the dashboard.
- Classrooms created before the roster feature have no roster, so their students can't sign in. The host dashboard and downloads still work for them.
- `update_survey` deletes the survey's existing responses (arms/questions are recreated). Autosave refuses to save a survey with responses, and the explicit save asks for confirmation, but the host can still do it. Lock edits after class.
