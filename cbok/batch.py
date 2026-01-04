import importlib
import inspect
import logging
import threading

from django.apps import apps

from cbok import utils as cbok_utils

LOG = logging.getLogger(__name__)


class BatchProcessor:

    def __init__(self):
        self.initial_tasks = []
        self.periodic_tasks = []

    def discover_gate_tasks(self):
        if not apps.ready:
            LOG.warning("Django apps not ready, skipping task discovery")
            return

        for app in cbok_utils.applications():
            try:
                gate_module = importlib.import_module(f'cbok.{app}.gate')

                for name, func in inspect.getmembers(gate_module, inspect.isfunction):
                    task_info = {
                        'app': app,
                        'name': name,
                        'func': func,
                        'module': gate_module
                    }

                    if name.startswith('periodic_') or getattr(func, 'periodic', False):
                        task_info['interval'] = getattr(func, 'interval', 60)
                        self.periodic_tasks.append(task_info)
                    else:
                        self.initial_tasks.append(task_info)

            except ModuleNotFoundError:
                LOG.debug(f"No gate module for {app}")
            except Exception as e:
                LOG.warning(f"Error loading gate for {app}: {e}")

    def run_initial_tasks(self):
        if not self.initial_tasks:
            return

        for task_info in self.initial_tasks:
            try:
                task_name = f"{task_info['app']}.{task_info['name']}"
                LOG.info(f"{task_name} spawned")
                threading.Thread(target=task_info['func'], daemon=True).start()
            except Exception as e:
                LOG.error(f"Failed to run initial task {task_name}: {e}")

    def run_periodic_tasks(self):
        if not self.periodic_tasks:
            return

        for task_info in self.periodic_tasks:
            try:
                task_name = f"{task_info['app']}.{task_info['name']}"
                interval = task_info['interval']

                def run_periodic():
                    import time
                    while True:
                        try:
                            task_info['func']()
                        except Exception as e:
                            LOG.exception(f"Error in periodic task {task_name}: {e}")
                        time.sleep(interval)

                LOG.info(f"{task_name} spawned")
                threading.Thread(target=run_periodic, daemon=True).start()

            except Exception as e:
                LOG.error(f"Failed to start periodic task {task_name}: {e}")

    def run_all(self):
        self.discover_gate_tasks()
        self.run_initial_tasks()
        self.run_periodic_tasks()
