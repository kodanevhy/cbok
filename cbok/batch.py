import eventlet
import importlib
import logging
import threading

from cbok import utils as cbok_utils

LOG = logging.getLogger(__name__)


class ProcessorMeta(type):
    registry = []

    def __new__(mcs, name, bases, attrs):
        cls = super().__new__(mcs, name, bases, attrs)
        if name != "Processor":
            ProcessorMeta.registry.append(cls())
        return cls


class Processor(metaclass=ProcessorMeta):
    def __init__(self, use_eventlet=False):
        self.threads = []
        self.use_eventlet = use_eventlet

    def startup(self):
        pass

    def run(self):
        self.startup()
        for func in self.threads:
            if self.use_eventlet:
                eventlet.spawn_n(func)
                LOG.debug(f"Spawned {func.__name__} with Eventlet")
            else:
                threading.Thread(target=func, daemon=True).start()
                LOG.debug(f"Spawned {func.__name__} in normal thread")


class AppCollector(Processor):
    """Collect common functions in gateway of any applications"""

    def startup(self):
        for app in cbok_utils.applications():
            try:
                module = importlib.import_module(f'cbok.apps.{app}.gateway')
                if hasattr(module, 'startup'):
                    self.threads.append(module.startup)
            except ModuleNotFoundError:
                LOG.debug(f"No startup function for {app}")


def run_all(use_eventlet=False):
    for processor in ProcessorMeta.registry:
        processor.use_eventlet = use_eventlet
        processor.run()
