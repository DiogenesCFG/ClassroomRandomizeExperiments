"""The flow of a survey per arm, as Mermaid flowchart text (drawn by mermaid.js in flow.html).

Each arm is its own chart: Start -> the questions that arm sees, in order -> End. A follow-up
question (display rule "only if Qn = ...") gets a diamond in front of it: "yes" leads to the
question, "no" skips to whatever comes next.
"""
from models import reminders, rules

TYPE_NAMES = {'multiple_choice': 'Multiple choice', 'multiple_answer': 'Multiple answer',
              'numeric': 'Number', 'short_answer': 'Short answer', 'slider': 'Slider'}
TIMER_SHOWN = {'both': '', 'countdown': ', countdown', 'bar': ', bar', 'hidden': ', hidden'}


def _text(value, limit=None):
    """Make text safe inside a quoted Mermaid label."""
    value = ' '.join(str(value or '').split())
    if limit and len(value) > limit:
        value = value[:limit - 1].rstrip() + '…'
    return (value.replace('#', '#35;').replace('"', '#quot;').replace('<', '#lt;').replace('>', '#gt;')
                 .replace('[', '#91;').replace(']', '#93;').replace('{', '#123;').replace('}', '#125;'))


def _node_label(q, data):
    lines = [f'<b>Q{q["question_index"] + 1}' + (f' · {_text(q.get("label"), 30)}' if q.get('label') else '') + '</b>',
             _text(data.get('question_text') or '(no text yet)', 60),
             f'<i>{TYPE_NAMES.get(q["question_type"], q["question_type"])}</i>']
    marks = []
    if data.get('timer_seconds'):
        marks.append(f'⏱ {data["timer_seconds"]}s{TIMER_SHOWN.get(data.get("timer_display") or "both", "")}')
    if data.get('allow_other') and q['question_type'] in rules.CHOICE_TYPES:
        marks.append('+ Other')
    if data.get('image_filename'):
        marks.append('\U0001f5bc image')
    if marks:
        lines.append(' · '.join(marks))
    return '<br/>'.join(lines)


def arm_flow(survey, arm, link=None):
    """Mermaid text for one arm. link(question_index) -> URL for clicking a question box, or None."""
    shown = [q for q in survey['questions'] if rules.shown_in_arm(q, arm['arm_index'])]
    seen = set()
    steps = []  # questions this arm can reach, in order (a condition on a question the arm never sees can't be met)
    for q in shown:
        cond = q.get('cond_question')
        if cond is not None and cond not in seen:
            continue
        steps.append(q)
        seen.add(q['question_index'])

    out = ['flowchart TD', '    start(["Start"])', '    finish(["End: submitted"])']
    entry = []
    for i, q in enumerate(steps):
        node = f'q{q["question_index"]}'
        out.append(f'    {node}["{_node_label(q, q["arms"].get(arm["arm_index"], {}))}"]')
        if q.get('cond_question') is not None:
            values = ' or '.join(_text(v, 25) for v in q.get('cond_values') or []) or '?'
            out.append(f'    d{q["question_index"]}{{"Q{q["cond_question"] + 1} = {values}?"}}')
            entry.append(f'd{q["question_index"]}')
        else:
            entry.append(node)

    # Two-part survey: a "Part 2" step between the parts
    part2 = reminders.part2_start(survey)
    first2 = next((i for i, q in enumerate(steps) if part2 is not None and q['question_index'] >= part2), None)
    if first2 is not None:
        def when(part):
            text = {'live': 'in class, live session', 'class': 'in class, launched separately',
                    'remote': 'remote, in the lobby'}[reminders.part_when(survey, part)]
            opens = reminders.part_dates(survey, part)[0]
            if reminders.part_when(survey, part) == 'remote' and opens:
                text += ', opens ' + reminders.nice_date(opens)
            return _text(text)
        out[1] = f'    start(["Start: part 1, {when(1)}"])'
        out.append(f'    part2(["Part 2: {when(2)}"])')
        out.append(f'    part2 --> {entry[first2]}')

    def next_entry(i):
        if first2 is not None and i + 1 == first2:
            return 'part2'
        return entry[i + 1] if i + 1 < len(steps) else 'finish'

    out.append(f'    start --> {("part2" if first2 == 0 else entry[0]) if steps else "finish"}')
    for i, q in enumerate(steps):
        node = f'q{q["question_index"]}'
        if q.get('cond_question') is not None:
            out.append(f'    d{q["question_index"]} -->|yes| {node}')
            out.append(f'    d{q["question_index"]} -->|no| {next_entry(i)}')
        out.append(f'    {node} --> {next_entry(i)}')
        if link:
            out.append(f'    click {node} href "{link(q["question_index"])}"')
    out.append('    classDef cond fill:#fff4d6,stroke:#c9a227,color:#3d3100')
    out.append('    classDef ends fill:#e7f1ff,stroke:#5b8def,color:#0b2a5b')
    out.append('    class start,finish' + (',part2' if first2 is not None else '') + ' ends')
    conds = [f'd{q["question_index"]}' for q in steps if q.get('cond_question') is not None]
    if conds:
        out.append(f'    class {",".join(conds)} cond')
    return '\n'.join(out), len(steps)


def survey_flows(survey, link=None):
    """[{'arm': label, 'chart': mermaid text, 'questions': count}] for each arm."""
    flows = []
    for arm in sorted(survey['arms'], key=lambda a: a['arm_index']):
        chart, count = arm_flow(survey, arm, link)
        flows.append({'arm': arm['label'], 'chart': chart, 'questions': count})
    return flows
