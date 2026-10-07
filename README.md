# Classroom Randomize Experiments

A web app for running randomized behavioral economics experiments in class. Student groups each design a survey with treatment/control arms, then all experiments run live with the class participating on their phones.

## How It Works

1. **Host creates a classroom** with a code (e.g., `ECON101`), a host password, a classroom password, and the class roster (a CSV; a Canvas gradebook export works as-is)
2. **Students join** with the code and classroom password, then sign in with their SIS ID. The first time, they confirm their first name and choose a password, so names and IDs in your data always match the roster.
3. **In their lobby**, one student per group creates the survey (each with 1-4 treatment/control arms) and invites teammates, who accept the invite from their own lobby
4. **On class day**, the host clicks **Start live session** on the instructor home and projects that page. Students join the live session from their lobby (or scan the QR code shown on the dashboard)
5. **The host activates surveys one by one** -- each student is randomly assigned to an arm and sees that arm's questions
6. **Students submit answers via HTTP** -- the host clicks "Refresh Results" to see updated charts and statistics

## Designing Surveys

Each survey is designed by a student group and represents one experiment. A survey has:

- **Arms** (2-4): Each arm is a treatment or control condition. Every student is randomly assigned to exactly one arm per survey. Arms let you vary what different groups of students see -- for example, one arm might frame a question as a gain while another frames it as a loss.
- **Questions** (1 or more): Each survey can have multiple questions. Questions are shared across arms, but the *question text, images, and answer options can differ per arm*. This is how you introduce the experimental manipulation -- the same question slot shows different wording depending on which arm the student was assigned to.
- **Question types**: Multiple choice (single select), multiple answer (multi-select), numeric (free number input), short answer (free text, 140 char limit), and slider (draggable range with configurable min/max/step).
- **Images**: Builders can attach an image (PNG or JPEG, max 5MB) to any arm-question. The image appears above the question text when the student takes the survey.

For example, a survey testing anchoring bias might have:
- 2 arms: "High anchor" and "Low anchor"
- 1 question: "How much would you pay for this product?" (numeric type)
- The High anchor arm's question text includes "Most people pay $500" while the Low anchor arm says "Most people pay $50"
- Both arms collect the same numeric answer, but the framing differs

## Key Features

- **Deterministic random assignment** -- students are assigned to arms using a SHA-256 hash of their ID + survey ID, so assignments are stable across page refreshes
- **Multiple question types** -- multiple choice, multiple answer, numeric, short answer, and slider (with histograms on the dashboard)
- **Image uploads** -- survey builders can attach images (PNG or JPEG, max 5MB) to individual arm-questions
- **Classroom password** -- students need both the classroom code and a password to join, preventing unauthorized access
- **Class roster** -- students sign in with an SIS ID from your roster plus their own password. Manage it from the dashboard's Roster page: re-upload the CSV, add late students, remove students who drop (their past answers are kept), and reset a forgotten password with one click
- **Teams** -- group members are invited and must accept. The host sets the maximum number of groups per student (empty = no limit). Only members can edit their group's survey
- **Survey builder aids** -- edits autosave (with "Discard all changes from this session"), "Copy from Control" for each arm, warnings when two arms are identical, a respondent preview for each arm, and a dashboard preview filled with random sample responses
- **Lock survey edits** -- one switch on the dashboard freezes students' surveys and groups once experiments are deployed; previews and downloads keep working
- **Peer feedback** -- once surveys are locked, each student is assigned groups to comment on (balanced so every group gets about the same number of reviewers, never their own). Comments open and close from the dashboard; groups read them anonymously after feedback closes. Students can jot private notes right after answering a live survey. Exports for grading included
- **Early deployment** -- the instructor can let a group run its survey before class; classmates answer it from their lobby until the group's deadline, and it still runs live for the presentation
- **Anonymized data for students** -- groups download their own survey's responses with each respondent shown only as a random ID; the instructor's exports include the key linking IDs to names
- **QR code** -- the host dashboard displays a QR code that links to the join page with the classroom code and password pre-filled, so students can scan and join instantly
- **Dark/light mode** -- the UI automatically follows the browser's color scheme preference
- **Block designers** -- the host can toggle a setting to prevent survey designers from participating in their own survey, avoiding bias
- **Image gallery** -- the host can browse all uploaded images across surveys from a single page
- **Manual refresh** -- host clicks "Refresh Results" to recount all submitted votes and update charts
- **Per-classroom isolation** -- multiple classrooms can run independently
- **CSV export** -- download all responses, survey configs, and participant lists, or everything (all CSVs + uploaded images) as a single .zip

The current implementation has, for simplicity, there's the following limits:

| | Minimum | Maximum |
| --- | --- | --- |
| Surveys per classroom | no limit | no limit |
| Arms per survey | 1 (server-enforced, defaults to 2) | 4 (client side only in builder.js:113) |
| Questions per survey | 1 (server enforced) | no limit | 
| Options per MC question | 2 (server-enforced) | 5 (client side only, in builder.js:229) | 
| Group members | 1 (server-enforced) | no limit |

To change the max arms or max options, edit the numbers in `static/js/builder.js` — the cap on arms is at line 113 (`armCount >= 4`) and the cap on options is at line 229 (`optCount >= 5`). There is no server-side maximum, so changing these two lines is all that's needed.


## Architecture

The app uses a pure HTTP architecture. Students poll for survey state every 3 seconds and submit answers via POST. The host dashboard fetches results on demand via a Refresh button. This approach was chosen over WebSockets for reliability -- SocketIO connections were unreliable on phones and caused slow page loads.

## Local Development

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows Git Bash)
source venv/Scripts/activate

# Install dependencies
pip install -r requirements.txt

# Run the app
python run.py
```

Visit `http://localhost:5000`.

## Deploying to Render

The repo includes `render.yaml` for one-click deployment. The app uses:
- A persistent disk at `/data` for the SQLite database and uploaded images
- Gunicorn with eventlet as the async worker
- Environment variables: `SECRET_KEY` (auto-generated), `DATABASE_PATH`, `UPLOAD_FOLDER`, `ASYNC_MODE`

## Project Structure

```
app.py              Flask app factory + server init
config.py           Configuration (SECRET_KEY, DATABASE path)
run.py              Local dev entry point
schema.sql          Database schema
models/
  db.py             Database connections, migrations
  classroom.py      Classroom CRUD
  survey.py         Survey CRUD with password protection
  participant.py    Participant records (live-session identity)
  roster.py         Roster CSV parsing, student accounts, teams/invites
  response.py       Answer storage and aggregation
  download.py       CSV export
routes/
  classroom.py      /c/create, /c/join, /c/<code>/lobby
  account.py        /c/<code>/signin, signout, live status, team invites/leave
  roster.py         /c/<code>/host/roster/ (upload, preview, add, reset, remove)
  builder.py        /c/<code>/builder/ (survey creation)
  student.py        /c/<code>/student/ (login + live session + HTTP submit)
  host.py           /c/<code>/host/ (dashboard + activate/next/reset/state/gallery)
  download.py       /c/<code>/download/ (CSV files)
sockets/
  events.py         Helper functions for aggregation and assignment
  assignment.py     Deterministic arm assignment (SHA-256)
templates/          Jinja2 HTML templates
static/
  js/builder.js     Dynamic survey form
  js/student.js     Student HTTP client (polling + submit)
  js/host.js        Host dashboard + Chart.js (manual refresh)
  css/style.css     Custom styles
```

## Tech Stack

- **Backend:** Python, Flask
- **Database:** SQLite (WAL mode)
- **Frontend:** Bootstrap 5.3.3 (with native dark mode), Chart.js, qrcodejs
- **Production:** Gunicorn + eventlet
