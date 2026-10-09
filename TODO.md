# Ideas for next quarter

Improvements to the interface and functionality, roughly in order of impact. None of these are started.
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

4. **Balanced randomization** (a methods fix)
   - The hash-based assignment is stable but not balanced: 30 respondents in 2 arms can easily split 19 vs 11.
   - Assign in balanced blocks (e.g. shuffled pairs in order of arrival) and store each student's arm, so arms stay within 1 of each other.
   - Matters a lot with class-sized samples.

5. **A teaching dashboard**
   - For each question: the difference between arms with a confidence interval and a p-value, in plain words
     ("Treatment answered $6.20 higher, 95% CI 1.1 to 11.3").
   - Projector mode: large type, no controls.
   - Optional auto-refresh with a live response counter.

## New question types (most econ-relevant first)

- Multiple price list (a choice at each of several prices): the standard way to measure willingness to pay
- Lottery choices (Holt-Laury style) for risk preferences
- Budget split (share $100 between options)
- Likert / rating scales with labeled ends, and grids of them
- Ranking
- Choices shown as images

## Rules students could set per question or survey

- Required or optional
- Number limits (min / max, whole numbers only)
- Shuffled option order per respondent (to rule out order effects)
- Shuffled question order
- Attention checks
- An intro or consent screen before the questions

## Smaller friction

- **Simultaneous editing**: teammates editing at the same time overwrite each other. A "Sofia is editing" notice would prevent lost work.
- **Long survey page**: folding helps, but a step-by-step flow (Idea → Arms → Questions → Extras → Check) would suit first-time students better.
- **Instructor home**: it has grown by accretion. One "next thing to do" panel (approvals waiting, students without a group,
  unfinished surveys) would beat scanning cards.
- **Visual consistency**: too many badge colors meaning different things. A pass on spacing and hierarchy would make it feel
  less clunky without changing behavior.
