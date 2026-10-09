# Classroom Randomize Experiments

A web app for running randomized behavioral economics experiments in class. Student groups each design a survey with treatment/control arms; on class day each group presents while the class answers its survey on their phones and the results appear on the projected dashboard.

Guides: [student guide](docs/student-guide.pdf) and [instructor guide](docs/instructor-guide.pdf) (sources in `docs/student-guide/` and `docs/instructor-guide/`).

## How It Works

1. **The instructor creates a classroom** with a code (e.g., `ECON101`), a host password, a classroom password, and the class roster (a CSV; a Canvas gradebook export works as-is).
2. **Students join** with the code and classroom password, then sign in with their SIS ID. The first time, they confirm their first name and choose a password, so names and IDs in the data always match the roster.
3. **In their lobby**, one student per group creates the group and invites teammates, who accept from their own lobby. The group then builds its survey together; it autosaves, even unfinished.
4. **The instructor moves the class through phases** from the instructor home: Building, Locked (surveys and groups frozen, reviewers assigned), Feedback open, Feedback closed.
5. **On class day**, the instructor clicks **Start live session** and projects it. Students join from their lobby or the QR code. The instructor starts surveys one by one (**Next Survey** follows group order and skips what already ran); each student is randomly assigned to an arm and sees that arm's questions.
6. **Results**: the instructor clicks **Refresh Results** for charts and statistics by arm. Groups download their own anonymized data; the instructor downloads everything as a zip.

## Designing Surveys

Each survey is one experiment:

- **Arms** (1-4): treatment or control conditions. Each student always gets the same arm (deterministic SHA-256 assignment).
- **Questions** (up to the instructor's limit): shared across arms, but the text, image and answer options can differ per arm. That difference is the treatment.
- **Question types**: multiple choice, multiple answer, numeric, short answer (140 characters), slider.
- **Extras, all optional** (per question, under "Advanced options"): ask a question only in some arms, show it only after certain answers to an earlier question (follow-ups), a per-arm timer, an "Other" choice with a text box. `{{Q1}}` in a question's text shows the respondent's answer to Question 1.
- **Two-part surveys (optional)**: part 2 starts at a chosen question; each part runs in the live session, in class launched separately by the instructor, or remotely from the lobby between chosen dates. Part 2 is only for students who answered part 1, in the same arm.
- **Notifications (optional)**: per arm, messages with a time of day and chosen days, which respondents add to their calendar (.ics on iPhone and computers, Google Calendar links on Android) or receive as web push notifications. Floating local time by default, or a chosen time zone. The instructor approves them (and remote dates) first.

The survey page has collapsible sections, drag-to-reorder questions, a "Not finished yet" list, warnings (e.g. identical arms), previews of the respondent screen (per arm and part, with the break between parts and a test notification) and of the dashboard (with made-up answers and a matching example data file), and a flow chart of each arm's path.

## Key Features

- **Roster sign-in and teams**: SIS ID + own password; invites with accept/decline; limits on group size and groups per student; filters on the roster (signed up, in a group, group size, pending invites)
- **Class phases and peer feedback**: balanced, stable reviewer assignments (never one's own group), drafts and private notes, anonymous comments released after feedback closes, grading exports
- **Live session**: launch any survey or part on its own (from Manage Surveys), a sequence that skips what already ran, "Run again" to reset a survey, block designers from their own survey, QR code
- **Demo dashboard**: click through every survey's questions, images and sample charts without going live
- **Early deployment** of one-part surveys, and **other-platform** surveys (e.g. Google Forms) that still present and get feedback
- **Data**: per-question time on screen, left-page and timeout flags; anonymized group downloads in wide or long format; instructor exports (all responses, configs, roster key, designers, participation, feedback, notifications) and a zip with everything plus images
- **Dark/light mode**, image uploads (PNG/JPEG, 5 MB), image gallery, per-classroom isolation

## Architecture

Pure HTTP: students poll for survey state every 3 seconds and submit answers via POST; the instructor dashboard fetches results on demand. This was chosen over WebSockets for reliability on phones. Push notifications are sent by a background loop in the app process (`models/push.py`, pywebpush). SQLite (WAL mode) on a persistent disk; schema changes are additive migrations that run on startup. See [CLAUDE.md](CLAUDE.md) for a detailed developer reference.

## Local Development

```bash
python -m venv venv
source venv/Scripts/activate      # Windows Git Bash (venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
python run.py                     # http://localhost:5000
```

## Deploying to Render

The repo includes `render.yaml`. The app uses a persistent disk at `/data` for the SQLite database and uploaded images, and Gunicorn with one eventlet worker. Environment variables: `SECRET_KEY` (auto-generated), `DATABASE_PATH`, `UPLOAD_FOLDER`, `ASYNC_MODE`; optionally `VAPID_SUBJECT` (`mailto:you@example.edu`) as the contact for push services. Push keys are generated on first use and stored in the database. Back up the database (or download the instructor zip) before deploying, and don't deploy during class.

## Project Structure

```
app.py              Flask app factory (also starts the notification sender)
config.py           Configuration (SECRET_KEY, DATABASE path, UPLOAD_FOLDER)
run.py              Local dev entry point
schema.sql          Database schema (migrations in models/db.py)
models/
  db.py             Connections, additive migrations
  classroom.py      Classrooms and passwords
  survey.py         Survey CRUD, warnings, "not finished" checks
  rules.py          Display rules (shown in arms, follow-ups)
  reminders.py      Two-part surveys, notification plans, calendar files and links
  push.py           Web push: keys, subscriptions, scheduling, sending
  roster.py         Roster CSV parsing, student accounts, teams/invites
  feedback.py       Phases, reviewer assignments, comments, early surveys
  flow.py           Flow charts (Mermaid)
  preview.py        Made-up responses for previews
  download.py       CSV exports
routes/
  classroom.py      /c/create, /c/join, /c/<code>/lobby
  account.py        Sign-in, invites, tours
  roster.py         /c/<code>/host/roster/
  builder.py        /c/<code>/builder/ (survey page, autosave, previews, flow chart, downloads)
  reminders.py      Parts and notifications: plans, approval, calendar step, push, remote parts
  student.py        Live session state and answer submission
  host.py           Instructor home, live dashboard, demo dashboard, launch/run again
  feedback.py       Phases, View survey, comments, early surveys
  download.py       Instructor CSVs and the zip
sockets/            Helper functions for payloads/aggregation, arm assignment
templates/          Jinja2 templates
static/js/          builder.js, reminders-builder.js, student.js, reminders.js, host.js, sw.js (service worker), tour.js
docs/               Student and instructor guides (HTML sources + PDFs)
```

## Tech Stack

- **Backend:** Python, Flask, SQLite (WAL), pywebpush, tzdata
- **Frontend:** Bootstrap 5.3, Chart.js, Mermaid, SortableJS, Driver.js, qrcodejs
- **Production:** Gunicorn + eventlet on Render
