"""Tiny module with a deliberate bug, used by the debug-preset integration test.

`add` is wrong on purpose (subtracts instead of adds) so the committed test fails. The
integration test reproduces the failure via the deploy verify command, then patches the
root cause and confirms the verify passes — the debug preset's reproduce -> patch ->
re-verify loop, exercised deterministically without an LLM.
"""


def add(a: int, b: int) -> int:
    return a - b  # BUG: should be a + b


def subtract(a: int, b: int) -> int:
    return a - b
