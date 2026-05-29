from __future__ import annotations

from .data import SAMPLE_EVENTS, compute_free_slots
from .models import CalendarEvent, ToolCallRecord


class CalendarService:
    def __init__(self, events: tuple[CalendarEvent, ...] | None = None) -> None:
        self.events = events or SAMPLE_EVENTS
        self.tool_calls: list[ToolCallRecord] = []

    def log_call(
        self,
        tool: str,
        route: str,
        approved: bool,
        *,
        returned_fields: list[str] | None = None,
        payload_preview: str = "",
    ) -> None:
        self.tool_calls.append(
            ToolCallRecord(
                tool=tool,
                route=route,
                approved=approved,
                returned_fields=returned_fields or [],
                payload_preview=payload_preview,
            )
        )

    def get_freebusy(self, days: int) -> dict:
        return {"free_slots": compute_free_slots(self.events, days=days)}

    def get_events(self, days: int) -> dict:
        del days
        return {
            "events": [
                {
                    "title": event.title,
                    "start": event.start,
                    "end": event.end,
                    "attendees": list(event.attendees),
                    "notes": event.notes,
                    "sensitivity": event.sensitivity,
                }
                for event in self.events
            ]
        }

    def dispatch(self, path: str, days: int = 10) -> dict:
        if path == "/freebusy":
            free_slots = self.get_freebusy(days)
            self.log_call(
                tool="calendar.freebusy.read",
                route=f"{path}?days={days}",
                approved=True,
                returned_fields=["free_slots"],
                payload_preview=", ".join(free_slots["free_slots"][:3]),
            )
            return free_slots
        if path == "/events":
            events = self.get_events(days)
            preview = []
            for event in events["events"][:2]:
                attendees = ", ".join(event["attendees"][:2])
                preview.append(f'{event["start"]} {event["title"]} [{attendees}]')
            self.log_call(
                tool="calendar.events.read",
                route=f"{path}?days={days}",
                approved=True,
                returned_fields=["title", "start", "end", "attendees", "notes", "sensitivity"],
                payload_preview=" | ".join(preview),
            )
            return events
        return {"error": "not found"}
