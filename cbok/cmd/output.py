"""Shared terminal output for CLI command results."""

import logging
import sys

from prettytable import PrettyTable


LOG = logging.getLogger(__name__)


def fail(message, exit_code=1, exc_info=False):
    """Record an error, show it without a log header, and exit."""
    LOG.error("%s", message, exc_info=exc_info)
    print(message, file=sys.stderr)
    raise SystemExit(exit_code)


def print_list(rows, fields):
    """Print rows as a left-aligned table with named columns."""
    table = PrettyTable()
    table.field_names = list(fields)
    table.align = "l"
    for row in rows:
        table.add_row(["-" if value is None else str(value).replace("\r", "")
                       for value in row])
    print(table)
