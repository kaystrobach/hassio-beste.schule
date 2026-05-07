"""Pure-functional formatters: API JSON in → markdown out.

These are intentionally simple. The goal is human-readable output that
renders cleanly inside an HA Markdown card via
`{{ state_attr('sensor.besteschule_<name>_grades', 'markdown') }}`.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable


def _grade_value(g: dict) -> str:
    v = g.get("value")
    return "" if v is None else str(v)


def _subject_name(g: dict) -> str:
    s = g.get("subject") or {}
    return s.get("name") or s.get("local_id") or "—"


def _teacher_name(g: dict) -> str:
    t = g.get("teacher") or {}
    if not t:
        return ""
    forename = t.get("forename") or ""
    name = t.get("name") or ""
    return (forename + " " + name).strip() or t.get("local_id") or ""


def _collection_label(g: dict) -> str:
    c = g.get("collection") or {}
    return c.get("name") or c.get("type") or ""


def _given_at(g: dict) -> str:
    return (g.get("given_at") or "")[:10]


# ---------- grades --------------------------------------------------------


def grades_to_markdown(
    grades: Iterable[dict],
    *,
    student_label: str,
    fetched_at: datetime,
) -> str:
    grades = sorted(
        grades,
        key=lambda g: (_subject_name(g).lower(), _given_at(g)),
    )

    by_subject: dict[str, list[dict]] = defaultdict(list)
    for g in grades:
        by_subject[_subject_name(g)].append(g)

    lines: list[str] = [
        f"## Noten — {student_label}",
        f"_Stand: {fetched_at:%Y-%m-%d %H:%M}_",
        "",
    ]

    if not grades:
        lines.append("_Keine Noten vorhanden._")
        return "\n".join(lines)

    lines += [
        "| Fach | Note | Datum | Art | Lehrer*in |",
        "| --- | --- | --- | --- | --- |",
    ]
    for subject in sorted(by_subject.keys(), key=str.lower):
        for g in by_subject[subject]:
            lines.append(
                "| {fach} | {note} | {datum} | {art} | {lehrer} |".format(
                    fach=_md_escape(subject),
                    note=_md_escape(_grade_value(g)),
                    datum=_md_escape(_given_at(g)),
                    art=_md_escape(_collection_label(g)),
                    lehrer=_md_escape(_teacher_name(g)),
                )
            )
    avg = average(grades)
    if avg is not None:
        lines += ["", f"**Durchschnitt:** {avg:.2f} ({len(list(grades))} Noten)"]
    return "\n".join(lines)


def finalgrades_to_markdown(
    finals: Iterable[dict],
    *,
    student_label: str,
    fetched_at: datetime,
) -> str:
    finals = list(finals)
    lines = [
        f"## Endnoten — {student_label}",
        f"_Stand: {fetched_at:%Y-%m-%d %H:%M}_",
        "",
    ]
    if not finals:
        lines.append("_Keine Endnoten vorhanden._")
        return "\n".join(lines)

    # Group by interval (Halbjahr).
    by_interval: dict[str, list[dict]] = defaultdict(list)
    for f in finals:
        iv = f.get("interval") or {}
        label = iv.get("name") or f"Halbjahr {f.get('interval_id', '?')}"
        by_interval[label].append(f)

    for interval_label in sorted(by_interval.keys()):
        lines += [f"### {interval_label}", "", "| Fach | Endnote |", "| --- | --- |"]
        for f in sorted(
            by_interval[interval_label],
            key=lambda x: _subject_name(x).lower(),
        ):
            value = f.get("value") or f.get("value_calc") or ""
            lines.append(
                "| {fach} | {note} |".format(
                    fach=_md_escape(_subject_name(f)),
                    note=_md_escape(str(value)),
                )
            )
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------- journal feed --------------------------------------------------


def journal_to_markdown(
    days: Iterable[dict],
    *,
    student_label: str,
    fetched_at: datetime,
    max_entries: int = 50,
) -> str:
    # Sort newest first.
    days = sorted(days, key=lambda d: d.get("date") or "", reverse=True)
    lines = [
        f"## Klassenbuch — {student_label}",
        f"_Stand: {fetched_at:%Y-%m-%d %H:%M}_",
        "",
    ]
    if not days:
        lines.append("_Keine Klassenbucheinträge im Zeitraum._")
        return "\n".join(lines)

    shown = 0
    for d in days:
        date = d.get("date", "")
        lines.append(f"### {date}")
        # Day-level notes.
        for n in d.get("notes") or []:
            text = (n.get("note") or n.get("text") or "").strip()
            if text:
                lines.append(f"- 📌 {_md_escape(text)}")
                shown += 1
        # Lessons (each one usually has subject + maybe notes).
        for lesson in d.get("lessons") or []:
            subj = ((lesson.get("subject") or {}).get("name")) or "—"
            nr = lesson.get("nr") or ""
            status = lesson.get("status") or ""
            head = f"- **{_md_escape(subj)}**"
            if nr:
                head += f" (Stunde {_md_escape(str(nr))})"
            if status and status.lower() not in ("normal", "regular", ""):
                head += f" — _{_md_escape(status)}_"
            lines.append(head)
            for n in lesson.get("notes") or []:
                text = (n.get("note") or n.get("text") or "").strip()
                if text:
                    lines.append(f"    - {_md_escape(text)}")
                    shown += 1
            shown += 1
        lines.append("")
        if shown >= max_entries:
            lines.append("_…weitere Einträge gekürzt._")
            break
    return "\n".join(lines).rstrip()


# ---------- helpers -------------------------------------------------------


def average(grades: Iterable[dict]) -> float | None:
    """Numeric average of grades whose `value` parses as a German school grade.

    Accepts plain `1`..`6` and tendencies like `1+`, `2-`, `3+/-`.
    """
    total, count = 0.0, 0
    for g in grades:
        n = _parse_grade(g.get("value"))
        if n is not None:
            total += n
            count += 1
    return None if count == 0 else total / count


def _parse_grade(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    base = s[0]
    if not base.isdigit():
        return None
    n = float(base)
    if "+" in s and "-" not in s:
        n -= 0.25
    elif "-" in s and "+" not in s:
        n += 0.25
    return n


def _md_escape(text: str) -> str:
    return (
        str(text)
        .replace("|", "\\|")
        .replace("\n", " ")
        .replace("\r", "")
        .strip()
    )
