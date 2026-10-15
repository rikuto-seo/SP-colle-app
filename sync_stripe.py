"""Compatibility entry point for the retired billing maintenance command.

Read-only by default; --apply explicitly ends verified legacy subscriptions.
"""
from tools.retire_legacy_subscriptions import main

if __name__ == '__main__':
    raise SystemExit(main())
