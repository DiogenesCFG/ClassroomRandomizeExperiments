"""Random sample responses for the builder's "Preview dashboard" (never written to the database)."""
import json
import random

from models import rules

# Typed answers for a sample respondent who picks "Other"
SAMPLE_OTHER = ['(sample) it depends', '(sample) none of these', '(sample) somewhere in between']


def _choices(info):
    """An arm-question's options, plus "Other" when respondents can type their own answer."""
    return list(info.get('options', [])) + (['Other'] if info.get('allow_other') else [])


SAMPLE_TEXTS = [
    'I would probably go with the first option.',
    'Not sure, it depends on the price.',
    'Seems reasonable to me.',
    'I chose based on my gut feeling.',
    'The wording made me think twice.',
    'Definitely yes.',
    'Probably not.',
    'I would need more information.',
]


def _snap(value, lo, hi, step):
    value = min(max(value, lo), hi)
    snapped = lo + round((value - lo) / step) * step
    return round(min(max(snapped, lo), hi), 6)


def fake_responses(arms, questions, n, seed=None):
    """Generate n fake respondents' answers.

    arms/questions come from sockets.events._get_survey_with_arms_and_questions.
    Each arm gets its own random tilt so treatment differences are visible in the plots.
    Returns response dicts shaped like rows from the `response` table.
    """
    rng = random.Random(seed)
    rows = []
    if not arms or not questions:
        return rows

    # Per-(arm, question) tilt: option weights for choice questions, mean shift for numbers
    tilt = {}
    for arm in arms:
        for q in questions:
            opts = _choices(q['arm_texts'].get(arm['id'], {}))
            tilt[(arm['id'], q['id'])] = {
                'weights': [rng.uniform(0.2, 1.0) for _ in opts],
                'shift': rng.uniform(-1, 1),
            }

    for respondent in range(1, n + 1):
        arm = rng.choice(arms)
        given = {}  # question_index -> this sample respondent's answer, for display rules
        shown = set()
        for q in questions:
            # Display rules: skip questions this arm doesn't see, or whose condition isn't met
            if not rules.shown_in_arm(q, arm['arm_index']):
                continue
            cond = q.get('cond_question')
            if cond is not None and (cond not in shown or not rules.answer_matches(given.get(cond), q.get('cond_values') or [])):
                continue
            shown.add(q['question_index'])
            info = q['arm_texts'].get(arm['id'], {})
            t = tilt[(arm['id'], q['id'])]
            qtype = q['question_type']
            answer_text, answer_index, other_text = '', None, None
            if qtype == 'multiple_choice':
                opts = _choices(info)
                if not opts:
                    continue
                answer_index = rng.choices(range(len(opts)), weights=t['weights'])[0]
                answer_text = opts[answer_index]
                if answer_text == 'Other':
                    other_text = rng.choice(SAMPLE_OTHER)
            elif qtype == 'multiple_answer':
                opts = _choices(info)
                if not opts:
                    continue
                chosen = [o for o, w in zip(opts, t['weights']) if rng.random() < w * 0.7] or [rng.choice(opts)]
                answer_text = json.dumps(chosen)
                if 'Other' in chosen:
                    other_text = rng.choice(SAMPLE_OTHER)
            elif qtype == 'slider':
                lo = q.get('slider_min', 0) or 0
                hi = q.get('slider_max', 100) or 100
                step = q.get('slider_step', 1) or 1
                mid = (lo + hi) / 2 + t['shift'] * (hi - lo) / 6
                answer_text = str(_snap(rng.gauss(mid, (hi - lo) / 6), lo, hi, step))
            elif qtype == 'short_answer':
                answer_text = f'(sample) {rng.choice(SAMPLE_TEXTS)}'
            else:  # numeric
                answer_text = str(max(0, round(rng.gauss(50 + t['shift'] * 15, 15))))
            timed_out = 0
            if info.get('timer_seconds') and rng.random() < 0.15:
                # Some sample respondents run out of time: the group's default is recorded
                timed_out, other_text, default = 1, None, info.get('timer_default') or ''
                answer_index = None
                if qtype == 'multiple_answer':
                    answer_text = json.dumps([default]) if default else ''
                else:
                    answer_text = default
                    if qtype == 'multiple_choice' and default in info.get('options', []):
                        answer_index = info['options'].index(default)
            given[q['question_index']] = answer_text
            limit = info.get('timer_seconds')
            seconds = round(limit if timed_out else min(max(1.0, rng.gauss(9, 4)), limit or 120), 1)
            rows.append({'arm_id': arm['id'], 'question_id': q['id'], 'answer_text': answer_text,
                         'answer_index': answer_index, 'other_text': other_text, 'timed_out': timed_out,
                         'respondent': respondent, 'arm_label': arm['label'], 'arm_index': arm['arm_index'],
                         'seconds': seconds, 'left_page': 1 if rng.random() < 0.04 else 0})
    return rows
