"""Detector protocol v1 entrypoint. No database, notification or model calls."""

import json
import sys

from cbok.alert.monitoring.contracts import evaluate_context


if __name__ == '__main__':
    print(json.dumps(evaluate_context(json.load(sys.stdin)), ensure_ascii=False, allow_nan=False))
