"""Question types and question rules.

Every type's question-level settings (required, shuffling, number limits, scale size,
budget total, attention check...) live in survey_question.settings (JSON) and its per-arm
content beyond the question text and options (scale labels, pictures, price-list rows,
lottery amounts) in arm_question.config (JSON). Both are NULL for older questions, which
then get the defaults below, so existing surveys behave exactly as before.

Stored answers (response.answer_text):
  multiple_choice / picture_choice  the option text (answer_index = its position)
  multiple_answer                   JSON list of option texts
  numeric / slider / rating         the number as text (rating: answer_index = point position)
  short_answer                      the text
  ranking                           JSON list of item texts, top-ranked first
  rating_grid                       JSON object {statement: value}
  budget                            JSON object {item: amount}
  price_list / lottery              JSON list of "A"/"B", one per row (answer_index = number of A choices)
  skipped optional question         '' (so "answered every question shown" still works)
"""
import json
import random
import re

# The Type menu, most commonly used first
TYPE_GROUPS = [
    ('Basic', [('multiple_choice', 'Multiple choice'), ('multiple_answer', 'Multiple answer'),
               ('numeric', 'Number'), ('short_answer', 'Short answer'), ('slider', 'Slider')]),
    ('Rankings and scales', [('ranking', 'Ranking'), ('rating', 'Rating scale'),
                             ('rating_grid', 'Rating grid'), ('picture_choice', 'Picture choice')]),
    ('Economics', [('budget', 'Budget split'), ('price_list', 'Price list (willingness to pay)'),
                   ('lottery', 'Lottery choices (risk)')]),
]
TYPE_NAMES = {k: v for _, group in TYPE_GROUPS for k, v in group}
SHORT_NAMES = dict(TYPE_NAMES, price_list='Price list', lottery='Lottery choices')

OTHER_TYPES = ('multiple_choice', 'multiple_answer')                      # can add an "Other" choice
OPTION_TYPES = ('multiple_choice', 'multiple_answer', 'ranking', 'rating_grid', 'budget')  # typed option rows
STORED_OPTION_TYPES = OPTION_TYPES + ('picture_choice',)                 # rows in arm_question_option
CHOICE_TYPES = ('multiple_choice', 'multiple_answer', 'picture_choice')  # conditions can use their answers
SCALE_TYPES = ('rating', 'rating_grid')
LIST_TYPES = ('price_list', 'lottery')
SHUFFLE_TYPES = ('multiple_choice', 'multiple_answer', 'ranking', 'picture_choice', 'budget', 'rating_grid')
ATTENTION_TYPES = ('multiple_choice', 'multiple_answer', 'picture_choice', 'rating')
JSON_TYPES = ('ranking', 'rating_grid', 'budget', 'price_list', 'lottery')

MAX_OPTIONS = {'multiple_choice': 5, 'multiple_answer': 5}  # others: MAX_ITEMS
MAX_ITEMS = 8
MAX_PICTURES = 8
MAX_LIST_ROWS = 20

LOTTERY_DEFAULT = {'a_high': '2.00', 'a_low': '1.60', 'b_high': '3.85', 'b_low': '0.10', 'rows': 10, 'unit': '$'}

# Label presets for rating scales (builder's "Fill labels" menu)
SCALE_PRESETS = {
    'agree': ['Strongly disagree', 'Disagree', 'Somewhat disagree', 'Neither agree nor disagree',
              'Somewhat agree', 'Agree', 'Strongly agree'],
    'likely': ['Extremely unlikely', 'Very unlikely', 'Somewhat unlikely', 'Neither likely nor unlikely',
               'Somewhat likely', 'Very likely', 'Extremely likely'],
    'satisfied': ['Very dissatisfied', 'Dissatisfied', 'Somewhat dissatisfied', 'Neither satisfied nor dissatisfied',
                  'Somewhat satisfied', 'Satisfied', 'Very satisfied'],
    'important': ['Not at all important', 'Slightly important', 'Moderately important', 'Very important',
                  'Extremely important'],
    'often': ['Never', 'Rarely', 'Sometimes', 'Often', 'Always'],
}

DEFAULT_SETTINGS = {
    'required': True, 'shuffle': False, 'keep_last': False, 'keep_place': False,
    'min': None, 'max': None, 'integer': False,             # numeric limits
    'points': 5, 'start': 1,                                 # rating scales
    'total': 100, 'budget_integer': True,                    # budget split
    'single_switch': True,                                   # price list / lottery
    'attention': False, 'correct': [],                       # attention check
}


def _load(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def settings_of(q):
    """A question's settings with defaults filled in (q: dict/row with 'settings', raw JSON or dict)."""
    raw = q.get('settings') if isinstance(q, dict) else (q['settings'] if 'settings' in q.keys() else None)
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in _load(raw).items() if k in DEFAULT_SETTINGS})
    out['points'] = min(max(int(out['points'] or 5), 2), 11)
    out['start'] = 0 if out['start'] == 0 else 1
    return out


def config_of(data):
    """An arm-question's type-specific content (data: dict with 'config', raw JSON or dict)."""
    return _load((data or {}).get('config'))


def settings_json(settings, qtype):
    """What to store for a question: only the keys that mean something for its type."""
    keep = ['required', 'keep_place']
    if qtype in SHUFFLE_TYPES:
        keep += ['shuffle', 'keep_last']
    if qtype == 'numeric':
        keep += ['min', 'max', 'integer']
    if qtype in SCALE_TYPES:
        keep += ['points', 'start']
    if qtype == 'budget':
        keep += ['total', 'budget_integer']
    if qtype in LIST_TYPES:
        keep += ['single_switch']
    if qtype in ATTENTION_TYPES:
        keep += ['attention', 'correct']
    return json.dumps({k: settings.get(k, DEFAULT_SETTINGS[k]) for k in keep})


def config_json(config, qtype):
    if qtype in SCALE_TYPES:
        return json.dumps({'labels': config.get('labels') or []})
    if qtype == 'picture_choice':
        return json.dumps({'pictures': config.get('pictures') or []})
    if qtype == 'price_list':
        return json.dumps({k: config.get(k, '' if k != 'values' else []) for k in ('a', 'b', 'values')})
    if qtype == 'lottery':
        return json.dumps({k: config.get(k, LOTTERY_DEFAULT[k]) for k in LOTTERY_DEFAULT})
    return None


def pipe_sources(text):
    """Question numbers (1-based) a text pipes answers from with {{Qn}}."""
    return {int(n) for n in re.findall(r'\{\{Q(\d+)\}\}', text or '', flags=re.I)}


# --- What respondents see ---

def scale_values(settings):
    return list(range(settings['start'], settings['start'] + settings['points']))


def scale_labels(settings, config):
    labels = list(config.get('labels') or [])
    labels = (labels + [''] * settings['points'])[:settings['points']]
    return [str(l or '').strip() for l in labels]


def point_label(value, label):
    return f'{value} ({label})' if label else str(value)


def picture_labels(config):
    """The answer each picture records: its caption, or "Picture N"."""
    return [(p.get('caption') or '').strip() or f'Picture {i + 1}' for i, p in enumerate(config.get('pictures') or [])]


def _num(text):
    try:
        return float(str(text).replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def _money(unit, text):
    value = _num(text)
    shown = f'{value:,.2f}' if value is not None else str(text)
    return f'{unit}{shown}'


def list_rows(qtype, config):
    """The rows of a price list or lottery list: [{'a', 'b', 'label'}] (label names the row on charts)."""
    rows = []
    if qtype == 'price_list':
        a, b = config.get('a') or '', config.get('b') or ''
        for v in config.get('values') or []:
            rows.append({'a': a.replace('{value}', v), 'b': b.replace('{value}', v), 'label': v})
    elif qtype == 'lottery':
        c = {k: config.get(k) if config.get(k) not in (None, '') else LOTTERY_DEFAULT[k] for k in LOTTERY_DEFAULT}
        try:
            n = min(max(int(c['rows']), 2), MAX_LIST_ROWS)
        except (TypeError, ValueError):
            n = 10
        unit = c['unit'] or ''
        for k in range(1, n + 1):
            def option(high, low):
                if k == n:
                    return f'{_money(unit, high)} for sure'
                return f'{k}/{n} chance of {_money(unit, high)}, {n - k}/{n} chance of {_money(unit, low)}'
            rows.append({'a': option(c['a_high'], c['a_low']), 'b': option(c['b_high'], c['b_low']),
                         'label': f'{k}/{n}'})
    return rows


def shuffled(n, key, keep_last=False):
    """A respondent's order for n options (stable for the same key)."""
    order = list(range(n))
    if n < 2:
        return order
    rng = random.Random(key) if key is not None else random.Random()
    if keep_last:
        head = order[:-1]
        rng.shuffle(head)
        return head + [n - 1]
    rng.shuffle(order)
    return order


def question_order(questions, key, survey_id):
    """Shuffle the questions a respondent sees. Questions marked "keep in place", and those tied to
    others by a display condition or {{Qn}} piping, stay where they are; the others trade places.
    questions: payload-ready dicts with question_index, cond_question, settings, and texts."""
    tied = set()
    for q in questions:
        if q.get('cond_question') is not None:
            tied.update({q['question_index'], q['cond_question']})
        for text in q.get('_texts', []):
            sources = {n - 1 for n in pipe_sources(text)}
            if sources:
                tied.update(sources | {q['question_index']})
    movable = [i for i, q in enumerate(questions)
               if q['question_index'] not in tied and not settings_of(q)['keep_place']]
    order = list(range(len(questions)))
    if len(movable) > 1:
        rng = random.Random(f'{key}:{survey_id}:order') if key is not None else random.Random()
        moved = movable[:]
        rng.shuffle(moved)
        for slot, src in zip(movable, moved):
            order[slot] = src
    return [questions[i] for i in order]


# --- Reading answers ---

def parse_answer(qtype, answer_text):
    """A stored answer as Python data (lists/dicts for the JSON types), or None if blank/unreadable."""
    if answer_text in (None, ''):
        return None
    if qtype in JSON_TYPES or qtype == 'multiple_answer':
        try:
            return json.loads(answer_text)
        except (TypeError, ValueError):
            return None
    return answer_text


def _fmt(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def readable(qtype, answer_text):
    """An answer as one readable cell (exports, piping)."""
    data = parse_answer(qtype, answer_text)
    if data is None:
        return answer_text or ''
    if qtype == 'ranking' and isinstance(data, list):
        return ' > '.join(map(str, data))
    if qtype in ('rating_grid', 'budget') and isinstance(data, dict):
        return '; '.join(f'{k}: {_fmt(v)}' for k, v in data.items())
    if qtype in LIST_TYPES and isinstance(data, list):
        return ' '.join(map(str, data))
    return answer_text


def switch_row(choices):
    """1-based row of the first B choice (where the respondent switched), or '' if they never did."""
    for i, c in enumerate(choices):
        if c == 'B':
            return i + 1
    return ''


def detail_columns(qtype, answer_text):
    """Extra per-answer columns for the wide download: [(name, value)]."""
    data = parse_answer(qtype, answer_text)
    if data is None:
        return []
    if qtype == 'ranking' and isinstance(data, list):
        return [(f'rank of {item}', i + 1) for i, item in enumerate(data)]
    if qtype in ('rating_grid', 'budget') and isinstance(data, dict):
        return [(str(k), _fmt(v)) for k, v in data.items()]
    if qtype in LIST_TYPES and isinstance(data, list):
        switches = sum(1 for a, b in zip(data, data[1:]) if a != b)
        return [('A choices', sum(1 for c in data if c == 'A')), ('switch row', switch_row(data)),
                ('switches', switches)]
    return []


def attention_result(qtype, settings, answer_text):
    """True/False for an attention-check question's answer, None if it isn't one (or wasn't answered)."""
    if not settings.get('attention') or qtype not in ATTENTION_TYPES or answer_text in (None, ''):
        return None
    correct = [str(c) for c in settings.get('correct') or []]
    if qtype == 'multiple_answer':
        chosen = parse_answer(qtype, answer_text)
        return isinstance(chosen, list) and sorted(map(str, chosen)) == sorted(correct)
    return str(answer_text) in correct


def attention_values(qtype, settings, arm_datas):
    """The answers an attention check can be set to: options across arms, or the scale's values."""
    if qtype == 'rating':
        return [str(v) for v in scale_values(settings)]
    values = []
    for data in arm_datas:
        opts = picture_labels(config_of(data)) if qtype == 'picture_choice' else data.get('options', [])
        for o in opts:
            o = (o or '').strip()
            if o and o not in values:
                values.append(o)
    return values


# --- Still to do ---

def type_problems(q, data):
    """What one arm's version of a question still needs for its type (messages without the name)."""
    qtype = q['question_type']
    settings = settings_of(q)
    config = config_of(data)
    options = [o for o in data.get('options', []) if (o or '').strip()]
    todo = []
    if qtype == 'ranking' and len(options) < 2:
        todo.append('add at least 2 items to rank.')
    if qtype == 'budget' and len(options) < 2:
        todo.append('add at least 2 items to split the budget between.')
    if qtype == 'rating_grid':
        if not options:
            todo.append('add at least one statement (row).')
        elif len({o.strip().lower() for o in options}) < len(options):
            todo.append('two statements are the same; each row needs its own text.')
    if qtype in ('ranking', 'budget') and len({o.strip().lower() for o in options}) < len(options):
        todo.append('two items are the same; each needs its own text.')
    if qtype in SCALE_TYPES:
        labels = scale_labels(settings, config)
        if not labels[0] or not labels[-1]:
            todo.append('label both ends of the scale (e.g. "Strongly disagree" and "Strongly agree").')
    if qtype == 'picture_choice':
        pictures = config.get('pictures') or []
        if len([p for p in pictures if p.get('image')]) < 2:
            todo.append('add at least 2 pictures.')
        elif any(not p.get('image') for p in pictures):
            todo.append('a picture choice has no picture yet.')
        labels = picture_labels(config)
        if len(set(labels)) < len(labels):
            todo.append('two pictures have the same caption.')
    if qtype == 'price_list':
        if not (config.get('a') or '').strip() or not (config.get('b') or '').strip():
            todo.append('write both options of the price list.')
        if len(config.get('values') or []) < 2:
            todo.append('add at least 2 values (prices) to the price list.')
        elif '{value}' not in (config.get('a') or '') + (config.get('b') or ''):
            todo.append('put {value} in option A or B, where the price goes.')
    if qtype == 'lottery':
        c = {k: config.get(k, LOTTERY_DEFAULT[k]) for k in LOTTERY_DEFAULT}
        if any(_num(c[k]) is None for k in ('a_high', 'a_low', 'b_high', 'b_low')):
            todo.append('the lottery amounts must be numbers.')
        elif _num(c['a_high']) < _num(c['a_low']) or _num(c['b_high']) < _num(c['b_low']):
            todo.append('in each lottery option, the high amount must be at least the low amount.')
    return todo


def rule_problems(q, arm_datas):
    """Question-level rule problems (attention check without a correct answer...)."""
    settings = settings_of(q)
    todo = []
    if settings['attention'] and q['question_type'] in ATTENTION_TYPES:
        available = attention_values(q['question_type'], settings, arm_datas)
        if not settings['correct']:
            todo.append('it is an attention check: tick its correct answer(s) under Advanced options.')
        elif any(c not in available for c in settings['correct']):
            todo.append('its attention check uses an answer that is no longer an option.')
    return todo


def timer_default_problem(q, data, default):
    """Timer defaults for the newer types (None = fine). Older types are checked in models/survey.py."""
    qtype = q['question_type']
    if qtype == 'rating':
        if default not in [str(v) for v in scale_values(settings_of(q))]:
            return f'the answer recorded when time runs out ("{default}") must be a point of the scale, or left empty.'
    elif qtype == 'picture_choice':
        if default not in picture_labels(config_of(data)):
            return f'the answer recorded when time runs out ("{default}") must be one of the picture captions, or left empty.'
    elif qtype in JSON_TYPES:
        return 'for this question type, leave "If time runs out, record" empty (no answer is recorded).'
    return None


# --- Results (dashboard) ---

def _stats(values):
    if not values:
        return None
    s = sorted(values)
    mean = sum(values) / len(values)
    return {'mean': round(mean, 2), 'median': round(s[len(s) // 2], 2), 'min': round(min(values), 2),
            'max': round(max(values), 2), 'std': round((sum((x - mean) ** 2 for x in values) / len(values)) ** 0.5, 2)}


def aggregate(qtype, settings, info, responses):
    """One arm's results for the newer types (not picture_choice, which is charted like multiple choice).

    Returns {'n', 'by_label': {label: value}, 'labels': [labels in this arm's order], 'cells': {column: text}}
    for the dashboard's generic chart and table (see view_for)."""
    answers = [parse_answer(qtype, r['answer_text']) for r in responses]
    answers = [a for a in answers if a is not None]
    out = {'n': len(answers), 'by_label': {}, 'labels': [], 'cells': {}}
    config = config_of(info)
    if qtype == 'rating':
        labels = scale_labels(settings, config)
        values = []
        for a in answers:
            try:
                values.append(float(a))
            except (TypeError, ValueError):
                pass
        for v, lab in zip(scale_values(settings), labels):
            key = point_label(v, lab)
            out['labels'].append(key)
            out['by_label'][key] = sum(1 for x in values if x == v)
        st = _stats(values)
        out['cells'] = {k: (st[k.lower()] if st else '') for k in ('Mean', 'Median', 'Min', 'Max')}
        out['cells']['Std Dev'] = st['std'] if st else ''
    elif qtype == 'rating_grid':
        rows = [o for o in info.get('options', [])]
        out['labels'] = rows
        for row in rows:
            vals = [float(a[row]) for a in answers if isinstance(a, dict) and isinstance(a.get(row), (int, float))]
            out['by_label'][row] = round(sum(vals) / len(vals), 2) if vals else None
            out['cells'][row] = out['by_label'][row] if vals else ''
    elif qtype == 'ranking':
        items = list(info.get('options', []))
        out['labels'] = items
        firsts = {}
        for item in items:
            ranks = [a.index(item) + 1 for a in answers if isinstance(a, list) and item in a]
            out['by_label'][item] = round(sum(ranks) / len(ranks), 2) if ranks else None
            firsts[item] = sum(1 for a in answers if isinstance(a, list) and a and a[0] == item)
        if answers and items:
            top = max(items, key=lambda i: firsts[i])
            out['cells']['Most often ranked first'] = f'{top} ({round(100 * firsts[top] / len(answers))}%)'
        else:
            out['cells']['Most often ranked first'] = ''
    elif qtype == 'budget':
        items = list(info.get('options', []))
        out['labels'] = items
        for item in items:
            vals = [float(a[item]) for a in answers if isinstance(a, dict) and isinstance(a.get(item), (int, float))]
            out['by_label'][item] = round(sum(vals) / len(vals), 2) if vals else None
            out['cells'][item] = out['by_label'][item] if vals else ''
    elif qtype in LIST_TYPES:
        rows = list_rows(qtype, config)
        lists = [a for a in answers if isinstance(a, list)]
        out['points'] = []  # price list with numeric values: (value, % A) for a shared price axis
        for i, row in enumerate(rows):
            key = row['label'] if qtype == 'lottery' else f'{i + 1}: {row["label"]}'
            out['labels'].append(key)
            picked = [a[i] for a in lists if i < len(a)]
            out['by_label'][key] = round(100 * sum(1 for c in picked if c == 'A') / len(picked), 1) if picked else None
            out['points'].append({'x': _num(row['label']), 'y': out['by_label'][key]})
        a_counts = [sum(1 for c in a if c == 'A') for a in lists]
        out['cells']['Mean A choices'] = round(sum(a_counts) / len(a_counts), 2) if a_counts else ''
        out['cells']['Switched more than once'] = sum(1 for a in lists if sum(1 for x, y in zip(a, a[1:]) if x != y) > 1)
    return out


def view_for(qtype, settings):
    """How the dashboard draws a newer type: chart kind, axis titles, table columns."""
    if qtype == 'rating':
        return {'kind': 'bar', 'title': 'Responses by Arm', 'x_title': 'Point on the scale', 'y_title': 'Count',
                'columns': ['Mean', 'Median', 'Std Dev', 'Min', 'Max'], 'integer_y': True}
    if qtype == 'rating_grid':
        lo, hi = scale_values(settings)[0], scale_values(settings)[-1]
        return {'kind': 'bar', 'title': 'Average rating by statement', 'x_title': 'Statement',
                'y_title': f'Average ({lo} to {hi})', 'y_min': lo, 'y_max': hi, 'columns': 'labels'}
    if qtype == 'ranking':
        return {'kind': 'bar', 'title': 'Average rank (1 = ranked first; lower is better)', 'x_title': 'Item',
                'y_title': 'Average rank', 'y_min': 1, 'columns': ['Most often ranked first']}
    if qtype == 'budget':
        return {'kind': 'bar', 'title': f'Average amount given (of {_fmt(settings["total"])})', 'x_title': 'Item',
                'y_title': 'Average amount', 'y_min': 0, 'columns': 'labels'}
    if qtype in LIST_TYPES:
        return {'kind': 'line', 'title': 'Share choosing option A in each row', 'y_title': '% choosing A',
                'x_title': 'Chance of the high amount' if qtype == 'lottery' else 'Row (value)', 'y_min': 0, 'y_max': 100,
                'columns': ['Mean A choices', 'Switched more than once']}
    return None


def condition_values(q):
    """The answers a display condition on this question can use: options across arms (picture
    captions for picture choice), plus "Other" when an arm has it."""
    values = attention_values(q['question_type'], settings_of(q), q.get('arms', {}).values())
    if any(d.get('allow_other') for d in q.get('arms', {}).values()) and 'Other' not in values:
        values.append('Other')
    return values
