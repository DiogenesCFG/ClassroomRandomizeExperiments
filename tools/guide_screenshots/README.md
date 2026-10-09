# Guide screenshots

Rebuilds the images in `docs/student-guide/img/` and `docs/instructor-guide/img/` from a demo classroom.

```bash
# 1. A fresh demo database (24 students, 6 groups, a two-part survey with notifications)
export DATABASE_PATH=/tmp/guide/app.db UPLOAD_FOLDER=/tmp/guide/up PUSH_SENDER=0 PYTHONPATH=.
python tools/guide_screenshots/make_demo.py
# 2. Serve it on port 5055 (leave running)
python tools/guide_screenshots/serve.py &
# 3. Screenshots with headless Chrome (path in shoot.py); optional names to retake only some
python tools/guide_screenshots/shoot.py /tmp/guide/out [07_editor_top ...]
```

Then copy the PNGs into the docs folders (`i0N_*` files go to the instructor guide without the `i`) and regenerate the PDFs:

```bash
chrome --headless --no-pdf-header-footer --print-to-pdf=docs/student-guide.pdf docs/student-guide/student-guide.html
chrome --headless --no-pdf-header-footer --print-to-pdf=docs/instructor-guide.pdf docs/instructor-guide/instructor-guide.html
```

Dates in the demo are relative to today. Chart.js animations don't run in headless Chrome, so the chart shots redraw with animation off first.
