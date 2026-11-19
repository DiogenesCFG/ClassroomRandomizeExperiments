# Ideas for next quarter

Improvements to the interface and functionality, roughly in order of impact. The top priorities below are not started.
Top three for next quarter: **1, 4 and 5**: they'd make building easier, make the data better, and make class day more instructive.

## Top priorities

1. **Write each question once and vary only what differs** (biggest win for students)
   - Today every question has a full copy per arm: students retype the same text 2 to 4 times, and "Copy from Control" is a workaround.
   - Instead: one base question, with per-arm overrides only for the parts that change (one sentence, a price).
   - Show exactly what differs between arms ("Treatment differs in: text"). That difference *is* the treatment, so this also teaches the concept.

2. **Live phone preview beside the editor**
   - Previews currently open in a separate tab.
   - A phone-sized panel that updates as students type, with an arm switcher.
   - Replace the "Not finished yet" paragraph with a **"Ready to run?" checklist** where clicking an item jumps to the field it's about.

3. **Starter templates**
   - Working two-arm surveys for the classics: anchoring, gain/loss framing, defaults, decoy pricing, social norms.
   - Students modify one instead of starting from a blank page.

4. ~~**Balanced randomization**~~ **Done (November 2026)**: "Enforce the split" (on by default) and custom percentages per arm
   in Survey options; see CLAUDE.md, "Arm Assignment".

5. **A teaching dashboard**
   - For each question: the difference between arms with a confidence interval and a p-value, in plain words
     ("Treatment answered $6.20 higher, 95% CI 1.1 to 11.3").
   - Projector mode: large type, no controls.
   - Optional auto-refresh with a live response counter.

6. **Three ways to run the surveys** (class-level setting, default = today's)
   - (a) **Instructor-paced** (today): a survey is open only while the instructor shows it; Next Survey closes it.
   - (b) **Instructor-paced, finish late**: Next Survey moves the screen on, but students still answering an earlier
     survey can finish and submit it (e.g. until the session ends). Small change: the open check in `submit` / `draft`
     and the phone page keeping its survey instead of switching.
   - (c) **Open whenever** (like Qualtrics / Google Forms): every survey the group marks ready can be answered from the
     lobby, optionally until a deadline. Overlaps with today's **early surveys** (group submits, classmates answer from
     "Open surveys" until a deadline), which could become this class-wide mode.
   - Switching a class that already has data to (b) or (c) lets late answers in after groups downloaded: say so in the setting.
7. **Join link as text**: the instructor home could show the students' join link (class code and password filled in,
   the same link as the live dashboard's QR code) with a Copy button, to paste in Canvas or an email. Not a link with the
   instructor password (it would give full control to anyone it's forwarded to); the read-only results link covers sharing results.

## Done (November 2026)

- **Results without going live**: the instructor's read-only results page (every survey's questions and real response
  charts; nothing opens on phones) and a private **results link** to share it without a password (create, replace, turn off).

## Done (October 2026)

- **New question types**: ranking, rating scales and grids, picture choice, budget split, price lists, Holt-Laury lottery choices.
- **Question rules**: required or optional, number limits, shuffled options, attention checks. **Survey options**: shuffled question order,
  an intro or consent screen. See CLAUDE.md, "Newer question types and rules".
- Possible follow-ups: "rank only the top N", several pictures per answer, a matrix of choice questions, excluding failed attention checks
  from the dashboard with one click.

## Smaller friction

- **Simultaneous editing**: teammates editing at the same time overwrite each other. A "Sofia is editing" notice would prevent lost work.
- **Long survey page**: folding helps, but a step-by-step flow (Idea → Arms → Questions → Extras → Check) would suit first-time students better.
- **Instructor home**: it has grown by accretion. One "next thing to do" panel (approvals waiting, students without a group,
  unfinished surveys) would beat scanning cards.
- **Visual consistency**: too many badge colors meaning different things. A pass on spacing and hierarchy would make it feel
  less clunky without changing behavior.
