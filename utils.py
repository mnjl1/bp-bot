import re
from datetime import datetime, timedelta
from html import escape
from textwrap import wrap
from messages import UA, EN, get_text
from constants import (MORNING_END, MIDDAY_END, limits,
                       REPORT_NOTE_COLUMN_WIDTH, REPORT_MESSAGE_LIMIT)


def get_period_of_day(date, lang):
    date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
    hour = date_obj.hour
    day_time = ''
    if hour < MORNING_END:
        day_time = get_text(lang, 'morning')
    elif hour >=MORNING_END and hour < MIDDAY_END:
        day_time = get_text(lang, 'midday')
    else: day_time = get_text(lang, 'evening')

    return day_time


def validate_reading(systolic, diastolic, pulse):
    values = {
    'systolic': systolic,
    'diastolic': diastolic,
    'pulse': pulse
    }

    for name, (min_value, max_value) in limits.items():
        if values[name] is not None:
            if not (min_value <= values[name] <= max_value):
                return
    return (systolic, diastolic, pulse)


def process_user_input(text):
    match = re.match(r'^(\d{2,3})/(\d{2,3})(?=$|[/\s])', text)
    if match is None:
        raise ValueError('Invalid reading format')
    systolic, diastolic = map(int, match.groups())
    remainder = text[match.end():]
    pulse = None
    if remainder.startswith('/'):
        remainder = remainder[1:]
        pulse_match = re.match(r'^(\d+)(?=$|[/\s])', remainder)
        if pulse_match is not None:
            if len(pulse_match[1]) not in (2, 3):
                raise ValueError('Invalid pulse format')
            pulse = int(pulse_match[1])
            remainder = remainder[pulse_match.end():]
            if remainder.startswith('/'):
                remainder = remainder[1:]
                if not remainder.strip():
                    raise ValueError('Missing note after slash')
        elif not remainder.strip():
            raise ValueError('Missing note after slash')
    # Keep the original note for length validation; normalize only after validation.
    note = remainder.lstrip() or None
    return ({'systolic': systolic, 'diastolic': diastolic, 'pulse': pulse}, note)


def convert_date(date):
    date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
    return date_obj.strftime('%d/%m/%y')


def get_report_date_range(today=None):
    """Thirty calendar days, using the existing server calendar convention."""
    today = today if today is not None else datetime.now().date()
    start = today - timedelta(days=29)
    end = today + timedelta(days=1)
    return start.strftime('%Y-%m-%d 00:00:00'), end.strftime('%Y-%m-%d 00:00:00')


def _report_size(text):
    # Count the escaped payload conservatively, including HTML wrappers.
    return len(text.encode('utf-16-le')) // 2


def format_report(records, start_timestamp, end_timestamp, lang):
    """Build HTML messages; averages and full notes use the same displayed rows."""
    start = datetime.strptime(start_timestamp, '%Y-%m-%d %H:%M:%S')
    end = datetime.strptime(end_timestamp, '%Y-%m-%d %H:%M:%S') - timedelta(days=1)
    title = get_text(lang, 'report_title').format(
        start=start.strftime('%d.%m.%Y'), end=end.strftime('%d.%m.%Y'))
    rows = []
    valid = []
    skipped = False
    for record in records:
        _, _, timestamp, systolic, diastolic, pulse, note = record
        try:
            date = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            values = (systolic, diastolic) + (() if pulse is None else (pulse,))
            if any(type(value) is not int for value in values):
                raise ValueError('Invalid reading values')
            if validate_reading(systolic, diastolic, pulse) is None:
                raise ValueError('Invalid reading values')
            if note is not None and not isinstance(note, str):
                raise ValueError('Invalid note')
        except (TypeError, ValueError):
            skipped = True
            continue
        date_period = date.strftime('%d.%m.%y') + ' ' + get_period_of_day(timestamp, lang)
        rows.append((date_period, str(systolic), str(diastolic),
                     '—' if pulse is None else str(pulse),
                     note if note and note.strip() else '—'))
        valid.append((systolic, diastolic, pulse))
    warning = get_text(lang, 'report_invalid') if skipped else ''
    if not rows:
        return [escape('\n'.join(filter(None, (
            title, get_text(lang, 'report_empty'), warning))))]

    headings = tuple(get_text(lang, key) for key in (
        'report_date', 'report_sys', 'report_dia', 'report_pulse', 'report_note'))
    widths = [max(len(row[column]) for row in [headings] + rows)
              for column in range(4)]

    def line(row):
        return (f'{row[0]:<{widths[0]}} {row[1]:>{widths[1]}} '
                f'{row[2]:>{widths[2]}} {row[3]:>{widths[3]}} {row[4]}')

    prefix = escape(title) + '\n<pre>' + escape(line(headings))
    current = prefix
    messages = []
    for row in rows:
        # Preserve words and spaces; existing line breaks also start a note line.
        note_lines = []
        for paragraph in row[4].expandtabs(4).split('\n'):
            note_lines.extend(wrap(paragraph, width=REPORT_NOTE_COLUMN_WIDTH,
                                   replace_whitespace=False, drop_whitespace=False) or [''])
        rendered_lines = [escape(line((*row[:4], note_lines[0])))]
        rendered_lines.extend(escape(line(('', '', '', '', text)))
                              for text in note_lines[1:])
        # Keep a reading together whenever it fits in one fresh message.
        block = '\n' + '\n'.join(rendered_lines)
        if (_report_size(current + block + '</pre>') > REPORT_MESSAGE_LIMIT
                and current != prefix):
            messages.append(current + '</pre>')
            current = prefix
        # A legacy note may exceed an entire message: split only at wrapped lines.
        for rendered in rendered_lines:
            if _report_size(current + '\n' + rendered + '</pre>') > REPORT_MESSAGE_LIMIT:
                messages.append(current + '</pre>')
                current = prefix
            current += '\n' + rendered
    messages.append(current + '</pre>')

    count = len(valid)
    pulses = [row[2] for row in valid if row[2] is not None]
    summary = [get_text(lang, 'report_averages'),
               f"{get_text(lang, 'report_avg_sys')}: {sum(row[0] for row in valid) / count:.0f}",
               f"{get_text(lang, 'report_avg_dia')}: {sum(row[1] for row in valid) / count:.0f}"]
    if pulses:
        summary.append(f"{get_text(lang, 'report_pulse')}: {sum(pulses) / len(pulses):.0f}")
    summary.append(f"{get_text(lang, 'report_count')}: {count}")
    if warning:
        summary.append(warning)
    summary_text = escape('\n'.join(summary))
    if _report_size(messages[-1] + '\n\n' + summary_text) <= REPORT_MESSAGE_LIMIT:
        messages[-1] += '\n\n' + summary_text
    else:
        messages.append(summary_text)
    return messages
