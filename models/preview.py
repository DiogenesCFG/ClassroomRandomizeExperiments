"""Random sample responses for the builder's "Preview dashboard" (never written to the database)."""
import json
import random

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
            opts = q['arm_texts'].get(arm['id'], {}).get('options', [])
            tilt[(arm['id'], q['id'])] = {
                'weights': [rng.uniform(0.2, 1.0) for _ in opts],
                'shift': rng.uniform(-1, 1),
            }

    for _ in range(n):
        arm = rng.choice(arms)
        for q in questions:
            info = q['arm_texts'].get(arm['id'], {})
            t = tilt[(arm['id'], q['id'])]
            qtype = q['question_type']
            answer_text, answer_index = '', None
            if qtype == 'multiple_choice':
                opts = info.get('options', [])
                if not opts:
                    continue
                answer_index = rng.choices(range(len(opts)), weights=t['weights'])[0]
                answer_text = opts[answer_index]
            elif qtype == 'multiple_answer':
                opts = info.get('options', [])
                if not opts:
                    continue
                chosen = [o for o, w in zip(opts, t['weights']) if rng.random() < w * 0.7]
                answer_text = json.dumps(chosen or [rng.choice(opts)])
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
            rows.append({'arm_id': arm['id'], 'question_id': q['id'],
                         'answer_text': answer_text, 'answer_index': answer_index})
    return rows
