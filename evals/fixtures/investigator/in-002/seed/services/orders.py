"""Order service. Publishes order.created events."""

from bus.event_bus import EventBus

_bus = EventBus()


def place_order(order):
    # ... persistence elided ...
    _bus.publish("order.created", order)
    return order
