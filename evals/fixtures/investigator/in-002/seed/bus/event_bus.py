"""In-process event bus. Single-threaded; no retry logic."""

from collections import defaultdict


class EventBus:
    def __init__(self):
        self._subs = defaultdict(list)

    def subscribe(self, topic, handler):
        self._subs[topic].append(handler)

    def publish(self, topic, payload):
        """Publish `payload` to all subscribers of `topic`."""
        for handler in list(self._subs[topic]):
            handler(payload)
