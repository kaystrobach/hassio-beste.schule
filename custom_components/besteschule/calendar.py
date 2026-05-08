"""Calendar platform for beste.schule integration."""
from __future__ import annotations

from datetime import datetime, time

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_JOURNAL, DOMAIN
from .coordinator import BesteSchuleCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the calendar platform."""
    coordinator: BesteSchuleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BesteSchuleCalendar(coordinator, entry)])


class BesteSchuleCalendar(
    CoordinatorEntity[BesteSchuleCoordinator], CalendarEntity
):
    """A calendar entity that shows journal entries."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-school"

    def __init__(
        self,
        coordinator: BesteSchuleCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator)
        self._attr_name = "Klassenbuch"
        self._attr_unique_id = f"{entry.entry_id}-calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"beste.schule – {coordinator.student_label}",
            manufacturer="beste.schule",
            model="API",
            configuration_url="https://beste.schule",
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        events = self._get_events()
        if not events:
            return None
        now = datetime.now()
        upcoming = [e for e in events if e.end > now]
        return min(upcoming, key=lambda e: e.start) if upcoming else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events between start_date and end_date."""
        events = self._get_events()
        return [
            e for e in events
            if e.start < end_date and e.end > start_date
        ]

    def _get_events(self) -> list[CalendarEvent]:
        """Convert journal days from coordinator into CalendarEvents."""
        days = self.coordinator.data.get(DATA_JOURNAL) or []
        events: list[CalendarEvent] = []

        for d in days:
            date_str = d.get("date")
            if not date_str:
                continue

            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            lessons = d.get("lessons") or []
            day_notes = d.get("notes") or []

            # If we have lessons, we could potentially create one event per lesson
            # if we had times. But we don't usually have exact times in the journal.
            # So we create one all-day event per day with all notes.

            summary_parts = []
            description_parts = []

            # Day-level notes
            for n in day_notes:
                text = (n.get("note") or n.get("text") or "").strip()
                if text:
                    description_parts.append(f"📌 {text}")

            # Lesson notes
            subjects = []
            for lesson in lessons:
                subj = ((lesson.get("subject") or {}).get("name")) or "—"
                subjects.append(subj)

                lesson_note_text = []
                for n in lesson.get("notes") or []:
                    text = (n.get("note") or n.get("text") or "").strip()
                    if text:
                        lesson_note_text.append(text)

                if lesson_note_text:
                    description_parts.append(f"**{subj}**:")
                    for lnt in lesson_note_text:
                        description_parts.append(f"  - {lnt}")

            if not description_parts and not subjects:
                continue

            summary = f"Journal: {', '.join(dict.fromkeys(subjects))}" if subjects else "Journal Eintrag"
            if len(summary) > 60:
                summary = summary[:57] + "..."

            events.append(
                CalendarEvent(
                    summary=summary,
                    start=dt,
                    end=dt, # All-day events in HA have same start/end date for one day
                    description="\n".join(description_parts),
                )
            )

        return events
