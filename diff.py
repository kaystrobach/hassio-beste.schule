"""Grade-diff helpers used by the coordinator to detect changes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GradeDelta:
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    changed: list[dict] = field(default_factory=list)  # {old, new}

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def grade_key(g: dict) -> str:
    """Stable identifier across runs.

    Prefer the API-provided ID; if absent, fingerprint by descriptive
    fields so newly imported grades without IDs still diff sensibly.
    """
    if g.get("id"):
        return f"id:{g['id']}"
    return "fp:" + "|".join(
        [
            str((g.get("subject") or {}).get("id") or ""),
            str(g.get("given_at") or ""),
            str((g.get("collection") or {}).get("id") or ""),
            str(g.get("value") or ""),
        ]
    )


def grade_signature(g: dict) -> dict:
    """Subset used for change detection and event payloads."""
    return {
        "id": g.get("id"),
        "value": g.get("value"),
        "given_at": g.get("given_at"),
        "subject_id": (g.get("subject") or {}).get("id"),
        "subject_name": (g.get("subject") or {}).get("name"),
        "collection": (g.get("collection") or {}).get("name"),
        "teacher": _teacher_short(g.get("teacher") or {}),
    }


def _teacher_short(t: dict[str, Any]) -> str:
    if not t:
        return ""
    return ((t.get("forename") or "") + " " + (t.get("name") or "")).strip()


def diff_grades(old: list[dict], new: list[dict]) -> GradeDelta:
    """Compute add/remove/change between two snapshots of grade objects."""
    old_by_key = {grade_key(g): g for g in old}
    new_by_key = {grade_key(g): g for g in new}
    delta = GradeDelta()
    for k, g in new_by_key.items():
        if k not in old_by_key:
            delta.added.append(grade_signature(g))
        else:
            o = old_by_key[k]
            if grade_signature(o) != grade_signature(g):
                delta.changed.append(
                    {"old": grade_signature(o), "new": grade_signature(g)}
                )
    for k, g in old_by_key.items():
        if k not in new_by_key:
            delta.removed.append(grade_signature(g))
    return delta
