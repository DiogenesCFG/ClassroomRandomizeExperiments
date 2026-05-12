# Classroom Randomize Experiments

A web app for running randomized behavioral economics experiments in class. Student groups each design a survey with treatment/control arms, then all experiments run live with the class participating on their phones.

## How It Works

1. **Host creates a classroom** with a code (e.g., `ECON101`) and a host password
2. **Student groups join** using the code and build their surveys (each with 2-4 treatment/control arms)
3. **On class day**, the host opens the dashboard and students join the live session on their phones
4. **The host activates surveys one by one** — each student is randomly assigned to an arm and sees that arm's question
5. **Results update live** on the host dashboard with charts and statistics

## Key Features

- **Deterministic random assignment** — students are assigned to arms using a SHA-256 hash of their ID + survey ID, so assignments are stable across page refreshes
- **Multiple question types** — multiple choice (grouped bar charts) and numeric (mean comparison + stats table)
- **Real-time updates** — host dashboard shows live results via WebSockets as students submit answers
- **Per-classroom isolation** — multiple classrooms can run independently
- **CSV export** — download all responses, survey configs, and participant lists

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
- A persistent disk at `/data` for the SQLite database
- Gunicorn with eventlet for WebSocket support
- Environment variables: `SECRET_KEY` (auto-generated), `DATABASE_PATH`, `ASYNC_MODE`

## Project Structure

```
app.py              Flask app factory + SocketIO init
config.py           Configuration (SECRET_KEY, DATABASE path)
run.py              Local dev entry point
schema.sql          Database schema (7 tables)
models/
  classroom.py      Classroom CRUD
  survey.py         Survey CRUD with password protection
  participant.py    Student login/registration
  response.py       Answer storage and aggregation
  download.py       CSV export
routes/
  classroom.py      /c/create, /c/join, /c/<code>/lobby
  builder.py        /c/<code>/builder/ (survey creation)
  student.py        /c/<code>/student/ (login + live session)
  host.py           /c/<code>/host/ (dashboard)
  download.py       /c/<code>/download/ (CSV files)
sockets/
  events.py         All SocketIO event handlers
  assignment.py     Deterministic arm assignment (SHA-256)
templates/          Jinja2 HTML templates
static/
  js/builder.js     Dynamic survey form
  js/student.js     Student SocketIO client
  js/host.js        Host dashboard + Chart.js
  css/style.css     Custom styles
```

## Tech Stack

- **Backend:** Python, Flask, Flask-SocketIO
- **Database:** SQLite (WAL mode)
- **Frontend:** Bootstrap 5, Chart.js, Socket.IO client
- **Production:** Gunicorn + eventlet
