"""Plugin loader. Invokes plugin-declared bus methods by name from config.

Each plugin manifest in config.yaml declares `bus_method` and `topic`;
the loader looks up the method on the shared EventBus instance at runtime.
This indirection was added so third-party plugins can emit events without
importing the bus class directly.
"""

import yaml

from bus.event_bus import EventBus

shared_bus = EventBus()


def load_and_emit(manifest_path):
    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)
    method_name = manifest["bus_method"]
    topic = manifest["topic"]
    payload = manifest.get("payload", {})
    # Resolve bus method dynamically by name. This is how plugins avoid
    # a hard compile-time coupling to the bus API.
    fn = getattr(shared_bus, method_name)
    fn(topic, payload)
