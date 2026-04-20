"""Notification fan-out. Publishes user.notified events."""

from bus.event_bus import EventBus

_event_bus = EventBus()


def send(user_id, message):
    _event_bus.publish("user.notified", {"user_id": user_id, "message": message})
