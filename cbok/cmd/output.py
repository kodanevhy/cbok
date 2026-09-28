"""Shared terminal output for CLI command results."""

from prettytable import PrettyTable


def print_list(rows, fields):
    """Print rows as a left-aligned table with named columns."""
    table = PrettyTable()
    table.field_names = list(fields)
    table.align = "l"
    for row in rows:
        table.add_row(["-" if value is None else str(value).replace("\r", "")
                       for value in row])
    print(table)
