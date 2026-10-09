"""Display rules for survey questions.

Each question can be limited to some arms (`show_arms`: list of arm positions, None = all
arms) and/or shown only when an earlier choice question was answered a certain way
(`cond_question`: that question's index, `cond_values`: the answers that reveal it).
Rules are stored on survey_question; question indexes (not ids) are used because saving
a survey recreates its questions.
"""
import json

CHOICE_TYPES = ('multiple_choice', 'multiple_answer')


def parse_rules(form, qi, n_arms):
    """Read a question's rules from the builder form."""
    shown = sorted({int(v) for v in form.getlist(f'questions[{qi}][show_arms]') if v.isdigit() and int(v) < n_arms})
    rules_present = form.get(f'questions[{qi}][rules_present]') == '1'
    show_arms = shown if rules_present and len(shown) < n_arms else None
    raw_cond = form.get(f'questions[{qi}][cond_question]', '').strip()
    cond_question = int(raw_cond) if raw_cond.isdigit() else None
    cond_values = [v.strip() for v in form.getlist(f'questions[{qi}][cond_values]') if v.strip()]
    return {'show_arms': show_arms, 'cond_question': cond_question,
            'cond_values': cond_values if cond_question is not None else []}


def to_columns(question):
    """Rule fields as stored in survey_question (show_arms, cond_question, cond_values)."""
    show_arms = question.get('show_arms')
    cond = question.get('cond_question')
    return (json.dumps(show_arms) if show_arms is not None else None,
            cond,
            json.dumps(question.get('cond_values') or []) if cond is not None else None)


def from_row(row):
    """Rule fields from a survey_question row (sqlite Row or dict)."""
    keys = row.keys()

    def load(name, default):
        if name not in keys or row[name] is None:
            return default
        try:
            return json.loads(row[name])
        except (TypeError, ValueError):
            return default

    return {'show_arms': load('show_arms', None),
            'cond_question': row['cond_question'] if 'cond_question' in keys else None,
            'cond_values': load('cond_values', [])}


def shown_in_arm(question, arm_index):
    arms = question.get('show_arms')
    return arms is None or arm_index in arms


def answer_matches(answer_text, values):
    """Does a stored answer (plain text, or a JSON list for multiple answer) match any value?"""
    if answer_text is None:
        return False
    chosen = [answer_text]
    if isinstance(answer_text, str) and answer_text.startswith('['):
        try:
            parsed = json.loads(answer_text)
            if isinstance(parsed, list):
                chosen = parsed
        except ValueError:
            pass
    return any(c in values for c in chosen)


def visible_questions(questions, arm_index, answers_by_index):
    """The questions a respondent in this arm sees, given their answers so far.

    questions: dicts with question_index + rule fields, in order.
    answers_by_index: question_index -> stored answer_text.
    """
    visible = []
    seen = set()
    for q in questions:
        if not shown_in_arm(q, arm_index):
            continue
        cond = q.get('cond_question')
        if cond is not None:
            if cond not in seen or not answer_matches(answers_by_index.get(cond), q.get('cond_values') or []):
                continue
        visible.append(q)
        seen.add(q['question_index'])
    return visible


def rule_problems(questions, arms):
    """"Still to do" items for rules that can't work. questions: parsed or stored, with
    'question_type', rule fields, and per-arm 'options'/'allow_other' under 'arms' (by position)."""
    todo = []
    if questions:
        for ai, arm in enumerate(arms):
            if not any(shown_in_arm(q, ai) for q in questions):
                todo.append(f'{arm.get("label") or f"Arm {ai + 1}"} sees no questions. Show at least one question in it.')
    for qi, q in enumerate(questions):
        name = f'Question {qi + 1}'
        show = q.get('show_arms')
        if show is not None and not show:
            todo.append(f'{name}: it is shown in no arm. Tick at least one arm under "Display rules".')
        cond = q.get('cond_question')
        if cond is None:
            continue
        if cond >= qi or cond < 0:
            todo.append(f'{name}: its condition must refer to an earlier question.')
            continue
        src = questions[cond]
        if src['question_type'] not in CHOICE_TYPES:
            todo.append(f'{name}: its condition refers to Question {cond + 1}, which is not a choice question.')
            continue
        if not q.get('cond_values'):
            todo.append(f'{name}: pick which answers to Question {cond + 1} show it.')
            continue
        available = set()
        for data in src.get('arms', {}).values():
            available.update(o.strip() for o in data.get('options', []) if o.strip())
            if data.get('allow_other'):
                available.add('Other')
        missing = [v for v in q['cond_values'] if v not in available]
        if missing:
            todo.append(f'{name}: its condition uses "{missing[0]}", which is no longer an answer to Question {cond + 1}.')
    return todo
