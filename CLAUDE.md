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

- `classroom` -- code, name, hashed host password, hashed classroom password (for student access), `classroom_password_plain` (recoverable plaintext for display/QR), `block_designers` flag; limits `max_groups_per_student` (NULL = no limit), `max_group_size` (default 5, NULL = no limit), `max_questions_per_survey` (default 3, NULL = no limit, host exempt); phase flags `surveys_locked`, `feedback_open`, `feedback_released`; `reviews_required` (default 2); `reminders_until` (latest date for reminders and part 2, NULL = no limit)
- `survey` -- title, group_number, is_active flag, belongs to classroom; `went_live` (activated at least once), early deployment (`early_allowed`, `early_open`, `early_deadline_utc`, `early_deadline_label`), other platform (`external`, `external_note`); two parts and notifications (`part2_from`, `part1_when`/`part2_when`, `partN_open_date`/`_close_date`/`_open_utc`/`_close_utc`, `part2_time`, `active_part`, `part1_ran`/`part2_ran`, `reminder_plan`, `reminders_approved`, see below)
- `survey_arm` -- treatment/control arms per survey
- `survey_question` -- questions per survey (supports multiple), includes `slider_min`/`slider_max`/`slider_step` for slider type
- `arm_question` -- per-arm question text variants, optional `image_filename` for uploaded images
- `arm_question_option` -- multiple choice options per arm-question
- `participant` -- student name + ID, belongs to classroom (created from the roster on sign-in)
- `roster_student` -- class roster: `sis_id`, `full_name` (as in the uploaded file, e.g. "Last, First"), `first_name` (shown in the sign-in confirmation), `password_hash` (NULL = not signed up / reset), `hidden` (removed from class but kept for past data), `anon_id` (random respondent ID for anonymized downloads), `tours_seen`
- `group_member` -- survey designers; `roster_student_id` links to the roster, `name`/`sis_code` are copied from it so exports and block-designers work unchanged
- `team_invite` -- pending invitations to join a survey's group
- `review_assignment` -- which groups each student must comment on (stable once made)
- `feedback` -- peer comments, one per student per survey (`sent_at` NULL = private draft)
- `reminder_action` -- each reminder action by a respondent: `method` ics (downloaded the file) | google (opened a Google Calendar link; `item` = which) | done (said they added them) | push / push_off (notifications on/off), with `device` and `arm_index`
- `push_subscription`, `push_message` -- push notifications (see below); `app_setting` -- server-wide settings (VAPID keys, site address)
- `response` -- answer records (participant, survey, arm, question, answer_text, answer_index); `seconds` (time the question was on screen with the page in view, measured on the phone), `left_page` (1 if they switched app/tab while on it), `other_text` (typed answer after choosing "Other")

New columns are added by the `ALTER TABLE` migrations in `init_db()` (`models/db.py`), which run on every startup, so existing databases (e.g. on Render) upgrade automatically.

The `response` table has a unique index preventing duplicate answers per participant per question. Indexes on `(survey_id, arm_id, question_id)` for fast aggregation.

Two database connection functions exist in `models/db.py`:
- `get_db()` -- uses Flask request context (`g` object), auto-closed on teardown
- `get_socket_db()` -- standalone connection for SocketIO handlers (outside request context)

## Question Types

Five question types are supported. The type is stored per-question in `survey_question.question_type`:

- **multiple_choice** -- single-select buttons, grouped bar chart on dashboard
- **multiple_answer** -- multi-select toggle buttons, stored as JSON array in `answer_text` (e.g., `["Option A","Option C"]`), grouped bar chart on dashboard (same as MC but counts can exceed n since each student can select multiple)
- **numeric** -- number input, histogram + stats table (mean, median, std, min, max) on dashboard. Bins are computed client-side in `host.js` using adaptive logic: exact bins for small integer ranges (≤19 distinct values), grouped bins (~10) for larger/decimal ranges
- **short_answer** -- text input (140 char limit); on the dashboard one column per arm, identical answers grouped (case, spaces and trailing punctuation ignored) with a count, most common first (`groupAnswers` in `host.js`)
- **slider** -- range slider input with configurable min/max/step, histogram + stats table on dashboard. Config stored in `survey_question.slider_min`, `slider_max`, `slider_step` columns. The student sees a draggable slider with live value display. Response stored as numeric string in `answer_text`. Histogram bins are computed client-side in `host.js` from the slider config and raw values.

**"Other" choice**: `arm_question.allow_other` (per arm, choice types only; builder button "+ Add \"Other\""). Respondents pick **Other** and must type something; the answer is stored as `Other` (MC) or with `"Other"` in the JSON list (MA), the typed text in `response.other_text` (`OTHER_LABEL` in `sockets/events.py`). The dashboard counts Other as an option and lists the typed answers under the chart (`renderOtherAnswers` in `host.js`); the anonymized download shows `Other: <typed>`; configs list it as an option. It counts toward the 2 options a choice question needs.

**Answer timing**: `student.js` runs a clock per question (`timeSpent`/`leftPage`), paused while the page is hidden (`visibilitychange`), and sends `seconds` and `left_page` with each answer; `_clean_seconds` in `routes/student.py` sanity-checks it. The host's response exports add `other_text, seconds, left_page`; the anonymized download adds `Qn seconds` / `Qn left page` columns after the answers. Older answers have these blank.

**Question timers** (per arm): `arm_question.timer_seconds` (NULL = none, 1-600; builder "Timer" switch per arm-question, `timer_on` + fields parsed by `_parse_timer`), `timer_display` (`both` | `countdown` | `bar` | `hidden`), `timer_default` (answer recorded on timeout; '' = no answer; for choices it must match an option, for numbers/sliders be a valid number, else it's a "Still to do" item via `timer_default_problem`). The payload carries `timer: {seconds, display, default}`. In `student.js` a timed question gets a wall-clock deadline the first time it's shown (kept in `localStorage` per participant/survey/arm/question so reloads don't restart it; previews don't store it); it keeps running while the app is in the background or the student goes back. On timeout an answer already given stands (sliders count only if moved); otherwise the default is recorded with `response.timed_out = 1`, the question locks and the next one shows after 1.5s. The dashboard shows "Timed out: X of N" per arm; exports add `timed_out` (host) / `Qn timed out` (anonymized); View survey describes each arm's timer.

**Display rules** (`models/rules.py`, "Display rules" box per question in the builder): `survey_question.show_arms` (JSON list of arm positions that see it; NULL = all) and `cond_question` + `cond_values` (shown only if that earlier choice question, by index, was answered with one of these; "Other" can be a value). Indexes, not ids, because saving recreates questions. The phone payload only contains the arm's questions, each with `condition: {question_index, values}`; `student.js` (`isVisible`, `nextVisible`, `updateNav`) skips hidden ones, numbers questions among those shown, re-evaluates after every choice and submits only visible answers; `{{Qn}}` piping uses design numbering. `_is_fully_answered` replays the rules on stored answers (finished = every question the respondent was shown is answered). Missing text in an arm that doesn't see a question isn't a to-do; broken rules are (`rule_problems`: shown in no arm, an arm with no questions, condition on a later/non-choice question, no or stale answers). The dashboard drops arms that didn't see a question (`not_shown`) but keeps arm colors by position (`colorOf` / `color_index` in `host.js`); sample data and View survey follow the rules. In the builder, `refreshRules()` in `builder.js` keeps the arm boxes and the condition lists in sync (conditions track questions by a per-block `data-uid`).

Types that need answer options (multiple_choice, multiple_answer) store them in `arm_question_option`. Types without options (numeric, short_answer, slider) have no rows there. The builder form shows/hides the options section and slider config section based on type. See `typeHasOptions()` in `builder.js`.

## Navigation

A context processor in `routes/__init__.py` (`nav_links`) adds navbar buttons on every page with a classroom `code` in its URL: **My lobby** + **Sign out** for a signed-in student, **Instructor home** + **Log out** (`POST /c/<code>/host/logout`) for the host; a browser can show both.

## Classroom Access

Two separate passwords protect each classroom:
- **Host password** -- required to access the host dashboard (`/c/host-join`). Only the instructor should know this.
- **Classroom password** -- required for students to join via `/c/join`. The instructor shares this with the class. This prevents unauthorized users from guessing classroom codes.

Both passwords are hashed with SHA-256 and stored in the `classroom` table. The classroom password is also stored in plaintext (`classroom_password_plain`) so the host can see it on the dashboard and it can be embedded in the QR code URL. The classroom creation form requires both passwords to be typed twice (confirm fields) with server-side validation. Every password box gets a show/hide eye button from `static/js/password-toggle.js` (loaded in `base.html`), which wraps the input in an input-group and moves its valid/invalid feedback inside. Classroom codes are unique, uppercased, exact-match; a taken code is refused with a message naming it.

## Roster and Teams

- **Roster upload** (`routes/roster.py`, `models/roster.py`): host uploads a CSV at classroom creation or on `/c/<code>/host/roster/`. Columns are guessed from headers (`guess_mapping`). When the ID and name columns are recognized, `import_or_preview()` saves the roster straight away and the roster page shows which columns were used, with "Looks right" / "Undo and choose columns"; the CSV and the added IDs are kept for a day in `instance/roster_uploads/` so the undo can reopen the preview. Otherwise the column-choice preview (`host/roster_import.html`) appears, re-posting the CSV text in a hidden textarea. Canvas gradebook exports work as-is ("Points Possible" and "Student, Test" rows are skipped). Combined names are split at the first comma (`split_full_name`). Re-uploading upserts by SIS ID and keeps passwords and groups; optional "remove students not in this file".
- **Roster page**: add a student, one-click password reset (clears the hash; next sign-in goes through first-time setup), remove/restore (hidden flag), max groups per student, max members per group. Columns for group, group size and pending invites (`list_roster`), and client-side filters (name/ID, signed up, in a group / pending invite / alone / no group and no invite, group size fewer than / exactly / more than N). Hover boxes (`teams_overview` in `models/roster.py`): a group number shows its members and pending invites; "N pending" shows which group invited the student, who sent it, its members and who else was invited. Any element with `data-bs-toggle="tooltip"` gets a Bootstrap tooltip lazily on hover/focus (script in `base.html`; `.tooltip-inner` keeps line breaks). Manage Surveys (`builder/list.html`) has the same kind of filters (title or member, member count, status) and a member-count column (`member_count`, `invite_count`, `invite_names` from `list_surveys`; hovering "+N invited" lists the names).
- **Teams**: "Create your group" (`/c/<code>/builder/new`, `builder/new_group.html`) only asks for an optional title and teammates; it creates the survey with placeholder arms (Control/Treatment) and one empty question, adds the creator as a member, assigns the next group number (only the host can change group numbers) and sends the invites, then opens the survey page, whose Group Members card sits at the top. Members invite classmates by name (`<datalist>` picker in `builder.js`); invitees accept/decline in their lobby. Invites can always be sent while the group has room, but accepting is blocked if it would exceed `max_groups_per_student` or the group already has `max_group_size` members (a full group also can't send invites; lowering the limit never removes anyone). Members can leave with a confirm, except the last member. Only group members (or the host) can edit, delete, or download a survey -- there are no survey passwords.
- **Lobby "My groups" table**: group #, title, member count (hover/tap for names), design warnings, response count with a download link.
- **Edit lock**: `classroom.surveys_locked`, set from the instructor home's Class phase panel (`POST /c/<code>/host/phase`, which also handles the required-comments count and the question limit). Blocks students' survey create/edit/autosave/delete and group invite/accept/leave; the host can still edit. Previews and downloads keep working.

## Class Phases, Peer Feedback, Early Surveys

All in `routes/feedback.py` and `models/feedback.py`.

- **Class phase** (instructor home): Building -> Locked -> Feedback open -> Feedback closed. "Next step" moves forward (with a confirm); individual switches set `surveys_locked`, `feedback_open`, `feedback_released` independently, with warnings for odd combinations. `class_phase()` derives the current step. Nothing is deleted when moving back.
- **When comments open** (`survey_commentable()`): a survey takes comments, and classmates can view/preview it, once it has gone live: `survey.went_live` (set the first time the host activates it, never cleared) or `early_open`. It stays open after the host moves on or unlocks surveys, and closes with the rest when feedback closes; sending still requires the Feedback open phase. Other-platform surveys open when surveys are locked. Assigned groups only appear once surveys are locked (`feedback_started()`); before that the lobby shows a stand-in, plus drafts/extras on surveys that already ran early. Refused notes make `get_note` return `not_live`, which hides the note box.
- **Review assignments** (`review_assignment`): created when surveys are locked (or comments opened, or the required count changes after that) by `ensure_assignments()`. Each active student gets `classroom.reviews_required` groups, never their own. Each try is round-based (most-constrained students first, random among the least-reviewed groups) plus a rebalancing pass so group loads differ by at most ~1, then a swap pass that trades targets between students to remove teammate overlaps without changing loads. Up to `ATTEMPTS` randomized tries (capped at `TIME_BUDGET` seconds) keep the best: even loads first, then no two members of a group reviewing the same group (achieved in tests for 100 students / 30 groups of 1-5 with up to 5 required; beyond that it's impossible and overlaps are minimized). Existing assignments are never reshuffled; invalid ones (student joined that group) are dropped and replaced. Late roster additions are topped up on their first lobby visit. The first `reviews_required` assignments (by id) are "required"; the rest are optional.
- **Comments** (`feedback`, one per student per survey): `sent_at` NULL = private draft. Drafts can be saved once the survey has gone live; sending/editing a sent comment requires `feedback_open`. Required comments can't be deleted; extras can. Own-group comments are refused. Groups see sent comments only when `feedback_released`, anonymized as "Reviewer N" (`received_feedback`).
- **Live notes**: after submitting a live survey, the student page offers a collapsed "Add a note" box (`/c/<code>/feedback/<id>/note`) that saves a private draft; `student.js` fires a `survey-submitted` event.
- **View survey** (`/c/<code>/survey/<id>/view`): all arms side by side; open to classmates once the survey has gone live (see above), so nobody sees the arms before answering. Respondent previews follow the same rule (`_can_preview` in `builder.py`).
- **Early surveys**: host allows per survey (`survey.early_allowed`, Manage Surveys page). Group submits with a deadline date (`early_open`, `early_deadline_utc` = end of that day in the group's browser time zone, `early_deadline_label`); this locks the survey for the group (`_locked_for(classroom, survey)`) until the host unlocks it. Classmates answer from the lobby's "Open surveys" (`/c/<code>/student/open/<id>`, same `session.html` with `POLL_ONCE`). The survey still runs in the live sequence. `student.submit_answer_http` only accepts answers for the active survey or an early survey before its deadline.
- **Other-platform surveys** (`survey.external`, `external_note`): a group registers normally and ticks "We're running our survey on another platform" in the builder (e.g. Google Forms, randomized and emailed by the group itself). Arms and questions then become optional: their fieldset (`#in-app-design`) is disabled so it isn't validated or posted, and `_save_edit` only saves the title and note, leaving any stored arms/questions untouched (unticking brings them back). The group keeps its group number, presents in order and gets review assignments; View survey shows their note. In the live session it's listed but not clickable, `activate` refuses it and `next` skips it. It can't open early and has no warnings. Exports keep a placeholder row in `all_responses`, `surveys_config` and `survey_participation`, and `survey_designers` has a `runs` column.
- **First-visit tours** (Driver.js 1.9.0 from jsDelivr + `static/js/tour.js`): the lobby and the survey page dim the page and walk through its parts. Each template defines `window.pageTour(auto)` with its steps; steps whose element isn't on the page are skipped, so one list covers every page state. Shown once per student, recorded in `roster_student.tours_seen` via `POST /c/<code>/tour/<name>/seen` (names: `lobby`, `builder`, `builder_edit`). The survey-page tour runs on the edit page the first time (recorded as `builder_edit`); students who saw the old create-page tour (`builder`) get only the steps marked `edit: true`. It never starts for the host or on a locked page. "Show me around" links replay them.
- **Presentation order**: the lobby lists every survey by group number (the live-session order) with its members, highlighting the student's own group.
- **Grading exports**: `feedback.csv` (every comment plus required-but-missing rows) and `feedback_summary.csv` (required sent / required, extras) via the dashboard and the zip.

## Survey Builder Aids

- **Page layout** (`templates/builder/form.html`, `static/js/builder.js`): the question, arm-version and timer-row markup is written once as Jinja macros (`question_block`, `arm_block`, `timer_row`, plus `info()` and `collapse_head()`) and also rendered into `<template id="tpl-question|tpl-arm|tpl-timer-row">`; the script clones those (`fromTemplate`, `syncQuestionArms`) and `reindexAll()` renames the fields, so there's no HTML-string copy of the form in JS. Group Members / Survey details / Arms / Questions and each question collapse (`initCollapsing`, `setCollapsed`; state in `sessionStorage` per survey; Members starts collapsed once the group has 2+ members). Each question header shows a summary and badges (`updateSummaries`: shown-in arms, condition, timers, Other). **Display rules and timers live in a per-question "Advanced options" Bootstrap modal inside the question block** (so its fields stay in the form); controls that must work on a locked page (collapse toggles, Advanced button, modal close) are `<span>`/`<a>`, not `<button>`, because the locked page disables its fieldset. Condition values are also rendered server-side so the page saves correctly before the script runs. `ⓘ` icons (`.info-tip`) get Bootstrap tooltips on hover/focus (tap on phones). `#q-N` in the URL opens and highlights question N (used by the flow chart).
- **Flow chart** (`/c/<code>/builder/<id>/flow`, `models/flow.py`, `builder/flow.html`): one Mermaid flowchart per arm (Start, the questions that arm can reach, a diamond before each follow-up with yes/no edges, End), with ⏱ timer, + Other and image marks; question text is escaped for Mermaid labels. Clicking a question opens it in the builder (members/host) or on View survey (classmates). Same access as the respondent preview. Linked from the survey page, the lobby's group row and View survey.

- **Unfinished surveys save**: `_validate` only blocks real mistakes (bad group number, slider min >= max or step <= 0, over the question limit). Missing pieces (question text, fewer than 2 options) are listed by `missing_parts()` / `survey_incomplete()` in `models/survey.py` as "Not finished yet" on the survey page, "Not finished" in the lobby and the host's survey lists, and block early deployment. A blank title or arm name gets a placeholder (`_fill_defaults`). The form is `novalidate`.
- **Autosave** (edit page only, `builder.js` + `POST /c/<code>/builder/<id>/autosave`): saves the whole form ~1.5s after any change and returns `todo`. Forms with a blocking mistake aren't saved; the status bar shows the first error. Uploaded images are only stored once the form is valid. Autosave is refused once the survey has responses (saving recreates arms/questions, which deletes responses) or when locked.
- **Discard all changes from this session**: the form as first loaded in the browser tab is kept in `sessionStorage`; discarding posts it back through the autosave endpoint. No versions are stored server-side. Replaced images stay on disk for 24h (`_cleanup_orphan_uploads`) so a discard can still reference them.
- **Copy from {first arm}**: per arm-question button copying the first arm's text, options, "Other" choice and saved image.
- **Start over** (`POST /c/<code>/builder/<id>/start-over`, in the survey page's Danger zone): resets arms/questions to `blank_design()` (Control/Treatment, one empty MC question), keeping title, group and members. Refused when locked or once the survey has responses; the session's Discard can undo it in the same tab.
- **Warnings** (`survey_warnings` in `models/survey.py`): flags one-arm surveys and pairs of arms identical in every question. Images are compared by file content hash, so the same picture uploaded twice counts as identical.
- **Reordering questions**: drag a question by its handle in the header (SortableJS 1.15.2 from jsDelivr, `Sortable.create` in `builder.js`, off on locked pages); `reindexAll()` renumbers fields and display rules follow their questions by `data-uid`.
- **Preview survey** (`/c/<code>/builder/<id>/preview?arm=N&part=P`): the real student page (`student/session.html` with `preview=True`, which sets `POLL_ONCE` so `student.js` loads one assignment instead of polling) for a chosen arm (and part); submit is a no-op. After part 1 of a two-part survey it shows a "Break between the parts" card (how part 2 runs, the arm's notifications, Continue to part 2).
- **Preview dashboard** (`/c/<code>/builder/<id>/preview-dashboard?n=30&seed=...`): the dashboard's results area and `host.js`, fed random sample responses from `models/preview.py` through `_aggregate_responses` (split out of `_get_aggregated_results`). Nothing is written to the database. The `seed` fixes the sample, so **Download example answers** (`.../preview-dashboard/example.csv`) contains the same made-up answers as the charts, written by `anon_responses_csv` (the same writer as the real anonymized download) with `EXAMPLE-001`-style IDs, times, left-page and timed-out flags. "New random sample" reloads without a seed.
- **Demo dashboard** (`/c/<code>/host/demo?survey=ID`, instructor home): the dashboard preview with a sidebar of every survey, so the host can click through all questions, images and sample charts without going live (`preview_dashboard_context` in `builder.py`).
- **Long format**: the anonymized download (and the example answers) also come as one row per respondent and question (`?format=long`, `anon_responses_long_csv`: respondent_id, arm, part, question, label, type, answer, seconds, left_page, timed_out, answered_at).
- **Anonymized downloads**: each roster student has a random `anon_id` (e.g. `R-7KQ2PX`, unique, generated on import and backfilled at startup). Students download their survey's responses as one row per respondent keyed by `anon_id` (`export_survey_responses_anon_csv`); names/IDs and the participation export are host-only. The host's all-responses and participants (roster) exports include `respondent_id` as the key.

## Two-Part Surveys, Notifications and Push

All in `models/reminders.py`, `models/push.py` and `routes/reminders.py`. Both are optional: by default a survey has one part, no notifications, and runs in the live session.

- **Two parts** ("Two-part survey (optional)" card in the survey form, `#two-part-card`): `survey.part2_from` = index of the first part-2 question (NULL = one part; the switch and "Part 2 starts at" are in the form, `refreshParts()` in `builder.js` tracks the start question by `data-uid`; part-2 questions get a "Part 2" badge and a dashed divider). Each part has a "when", `part1_when` / `part2_when`: `live` (in the live session's sequence; default for part 1), `class` (in class, launched separately by the host), `remote` (answered from the lobby between `partN_open_date`/`_close_date`, i.e. `partN_open_utc`/`_close_utc` in the group's time zone; default for part 2). The whens and dates have no `name` in the form: `reminders-builder.js` saves them with the notifications (JSON `parts`), so they can change after the survey has responses. `part_when()`, `sequence_part()` (the part the live sequence runs, or None), `remote_parts()`, `part_window()` (none | waiting | upcoming | open | closed; a remote part only opens once approved). Part 2 is only for students who answered part 1, in the same arm (the live session returns state `skip` to others, shown in the blocked panel). `submit_answer_http` works out the part from the question ids (mixed parts refused) and accepts it if that part is the one running live (`survey.active_part`), an open remote part, or (one-part only) an early-open survey. Remote parts are answered at `/c/<code>/student/part/<id>/<part>` (`session.html` with `remote_part`), listed in the lobby's "Surveys to answer from here, and notifications" card. To-dos (`part_problems`): each part needs a question in every arm; a part-2 question can't depend on a part-1 answer; both parts can't be `live`. Two-part surveys can't use early deployment. Exports mark parts (`part` column; anonymized headers say "part 2"); the dashboard tabs and the flow chart show the parts.
- **Running parts** (`routes/host.py`): `activate` takes `{survey_id, part}` and `_launch()` sets `is_active`, `active_part` and `partN_ran` (first time). **Next Survey** runs the next survey (by group number) whose sequence part hasn't run, so surveys or parts launched on their own earlier are skipped. Manage Surveys' "Running it" column has **Launch** per part (opens `/c/<code>/host/dashboard?survey=ID&part=N`, the live dashboard with only that survey) and **Run again** (`POST /host/survey/<id>/run-again`, host password: deletes its responses, notification sign-ups and ran flags so it runs again). The live dashboard shows "part N" and "ran" badges.
- **Notifications** ("Notifications (optional)" card, `builder/_reminders_card.html` + `static/js/reminders-builder.js`, independent of parts): `survey.reminder_plan`, JSON by arm position: `{"tz": "", "arms": [{"note", "rules": [{message, time, dates: [yyyy-mm-dd, ...]}]}]}` (older `start/end/every` rules are converted by `_rule_dates`). Per arm (collapsible): the note respondents read before turning them on, and notifications (collapsible, "+ Add notification"), each with its message, time of day and days picked on a month calendar (tap days; "Quick fill" adds a range every day / 2 days / week / weekday). Autosaved as JSON to `POST /c/<code>/builder/<id>/reminders`, separately from the survey form. Arms follow the form through `arms-changed` events from `builder.js`. `tz` is '' (floating: 12:00 arrives at noon wherever the phone is) or an IANA zone (validated with `zoneinfo`; `tzdata` is a dependency for Windows). `runs()` splits a notification's days into evenly spaced runs, each one repeating calendar event. Problems (`plan_problems`: missing message/days/time, days after the instructor's `reminders_until`, more than 60 sends per arm, remote parts' dates) join the survey's to-do list.
- **Approval**: needed for notifications and remote parts. `reminders_approved` stores `plan_hash()` of what the host approved (plan, time zone, remote parts' dates); `approval_state()` is none | pending | approved | changed. Approve/withdraw on View survey (`#reminders`) or the survey page (`POST /c/<code>/host/survey/<id>/reminders`); the instructor home and Manage Surveys list what's waiting. Until approved, respondents get no notifications and remote parts stay closed.
- **Respondent's step** (`static/js/reminders.js`, `RemindersPanel.load`): after submitting part 1 (or a one-part survey) (`survey-submitted` event in `session.html`) and from the lobby (`/c/<code>/reminders/<id>`), until they answer part 2. `GET .../reminders/<id>/panel` returns the arm's note and events. iPhone (iPads detected by touch): the `.ics` file opened inline ("Add All"); Android: one Google Calendar "add event" link per reminder (recurring via `recur=RRULE`, `ctz` with a time zone), going through `.../google/<key>` so it's logged, plus "Get notifications instead"; computers: `.ics` download. "Other ways" shows all; "Done" is self-reported. Each rule is one VEVENT with `RRULE:FREQ=DAILY;INTERVAL=n;COUNT=c` and an alarm at the event time; with a time zone, times carry `TZID` and the file has a generated `VTIMEZONE` (`_vtimezone`, including daylight-saving changes). A remote part 2 adds "Part 2 ... is open" on its open date at `part2_time`. `?arm=N` previews an arm (group, host, classmates once live) without logging; the preview offers "Send me a test notification" (`POST .../push-test?arm=N`, sent right away, nothing stored).
- **Push notifications** (`models/push.py`): `static/js/sw.js`, served at `/sw.js`, is the service worker. Turning them on (`POST .../reminders/<id>/push` with the browser subscription and the phone's time zone; `{off: true}` turns them off) stores a `push_subscription` and schedules every future reminder as a `push_message` row with its UTC time (floating reminders use the phone's zone). `start_sender()` (called in `create_app`; `PUSH_SENDER=0` disables it, e.g. in tests) runs a background loop every minute: `send_due()` claims each due message, skips it if the plan is no longer approved or it's over 3 hours late, and sends it with `pywebpush`; 404/410 deactivates the subscription. A tap opens `/c/<code>/reminders/push/<id>/<token>`, which records `clicked_at` and goes to the lobby. The VAPID keys are generated on first use and kept in `app_setting`; the VAPID contact is `VAPID_SUBJECT` or the site's https address. iPhones only get notifications for sites added to the Home Screen, so it isn't offered there otherwise.
- **Data**: anonymized download adds `reminders file downloaded` / `reminders Google links opened` / `reminders said added` / `reminders notifications on` / `delivered` / `opened`; host `reminder_actions.csv` (Data card, zip), `reminder_notifications.csv` and `reminder_plans.csv` (zip). Clearing responses and saving a survey over its responses also delete its `reminder_action` and push rows.

## Guides

`docs/student-guide/student-guide.html` and `docs/instructor-guide/instructor-guide.html` are the sources of `docs/student-guide.pdf` and `docs/instructor-guide.pdf` (Chrome headless `--print-to-pdf`, command in each file's header). Their screenshots come from a demo classroom: `tools/guide_screenshots/` (`make_demo.py` builds it, `serve.py` runs it on port 5055, `shoot.py` captures named shots with headless Chrome over the DevTools protocol). Update the guides when a student- or instructor-facing flow changes.

## Image Uploads

Survey builders can attach images (PNG, JPEG only -- PDF was removed) to individual arm-questions. Images are:
- Stored on disk in `UPLOAD_FOLDER` (locally: `instance/uploads/`, on Render: `/data/uploads/` on the persistent disk)
- Named with a UUID prefix to avoid collisions: `{uuid4}_{original_filename}`
- Limited to 5MB per file via Flask's `MAX_CONTENT_LENGTH`
- Served via `GET /uploads/<filename>` route in `app.py`
- Deleted from disk right away when a survey or classroom is deleted; images replaced while editing are removed by `_cleanup_orphan_uploads` once unused for 24h

In the student view, images render as `<img>` tags above the question text. In the host dashboard, images appear as thumbnails in the arms detail section. The host can also view all uploaded images across surveys from `GET /c/<code>/host/images` (the image gallery).

The builder form uses `enctype="multipart/form-data"`. On edit, existing images are preserved via a hidden `existing_image` form field unless a new file is uploaded.

## Block Designers

The host can toggle "Block designers from own survey" on the live-session page. When enabled, students whose SIS ID appears in the `group_member` table for the active survey are shown a "blocked" state instead of the survey questions. This prevents designers from biasing their own experiment. The toggle calls `POST /c/<code>/host/toggle-block-designers`, which flips the `block_designers` column on the `classroom` table. The student state endpoint checks this flag and returns `state: 'blocked_designer'` for matching students.

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
- Surveys can be saved unfinished (blank question text, too few options), so code that reads a survey must not assume every arm-question has text or 2+ options. Use `survey_incomplete()` to check; the host can still activate an unfinished survey (it's only flagged).
- There is no automated test suite in the repo; changes have been checked with throwaway Flask test-client scripts (a fresh database per run via `DATABASE_PATH`/`UPLOAD_FOLDER`, `PUSH_SENDER=0`). A useful one parses the survey page like a browser, posts it back to autosave and checks the stored survey is unchanged.
- Editing files through shell heredocs mangles backslashes (`\n`, `\'`, `\00b7`): one such edit once put a NUL byte in `style.css` and broke a JS string. Prefer the editor tools, and check inline `<script>`s parse after edits.
- `update_survey` deletes the survey's existing responses (arms/questions are recreated). Autosave refuses to save a survey with responses, and the explicit save asks for confirmation, but the host can still do it. Lock edits after class.
