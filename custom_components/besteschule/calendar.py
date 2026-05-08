"""Calendar platform for beste.schule integration."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional, Union

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
        """Initialize."""
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
    def event(self) -> Optional[CalendarEvent]:
        """Return the next upcoming event."""
        events = self._get_events()
        if not events:
            return None
        now = datetime.now()
        upcoming = []
        for e in events:
            # Handle both date and datetime
            e_end = e.end
            if isinstance(e_end, date) and not isinstance(e_end, datetime):
                # All-day events: end is date. We treat it as end of that day.
                e_end_dt = datetime.combine(e_end, time(23, 59, 59))
            else:
                e_end_dt = e_end

            if e_end_dt > now:
                upcoming.append(e)

        if not upcoming:
            return None

        def get_start(e: CalendarEvent) -> datetime:
            s = e.start
            if isinstance(s, date) and not isinstance(s, datetime):
                return datetime.combine(s, time(0, 0))
            return s

        return min(upcoming, key=get_start)

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

        status_emojis = {
            "hold": "✅",
            "initial": "❓",
        }

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

            # Create individual events for each lesson
            for lesson in lessons:
                subj = ((lesson.get("subject") or {}).get("name")) or "—"
                status = lesson.get("status")
                emoji = status_emojis.get(status, "")

                summary = f"{emoji} {subj}".strip()

                # Extract times
                lesson_time = lesson.get("time") or {}
                time_from_str = lesson_time.get("from")
                time_to_str = lesson_time.get("to")

                start_dt: Union[datetime, date]
                end_dt: Union[datetime, date]

                if time_from_str and time_to_str:
                    try:
                        start_t = datetime.strptime(time_from_str, "%H:%M").time()
                        end_t = datetime.strptime(time_to_str, "%H:%M").time()
                        start_dt = datetime.combine(dt, start_t)
                        end_dt = datetime.combine(dt, end_t)
                    except ValueError:
                        start_dt = dt
                        end_dt = dt
                else:
                    start_dt = dt
                    end_dt = dt

                description_parts = []
                # Lesson notes
                for n in lesson.get("notes") or []:
                    text = (n.get("note") or n.get("text") or "").strip()
                    if text:
                        description_parts.append(f"• {text}")

                # Add teacher and room if available
                teachers = [f"{t.get('forename')} {t.get('name')}" for t in (lesson.get("teachers") or [])]
                if teachers:
                    description_parts.append(f"Lehrer: {', '.join(teachers)}")

                rooms = [r.get("local_id") for r in (lesson.get("rooms") or []) if r.get("local_id")]
                if rooms:
                    description_parts.append(f"Raum: {', '.join(rooms)}")

                events.append(
                    CalendarEvent(
                        summary=summary,
                        start=start_dt,
                        end=end_dt,
                        description="\n".join(description_parts),
                        location=", ".join(rooms) if rooms else None,
                    )
                )

            # Create separate all-day events for day-level notes
            for n in day_notes:
                text = (n.get("description") or n.get("note") or n.get("text") or "").strip()
                if not text:
                    continue

                # The sample JSON shows "description" for notes
                type_name = (n.get("type") or {}).get("name") or "Notiz"

                events.append(
                    CalendarEvent(
                        summary=f"📌 {type_name}: {text}",
                        start=dt,
                        end=dt,
                        description=text,
                    )
                )

        return events
