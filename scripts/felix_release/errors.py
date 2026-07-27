"""Public safe-failure type for the strict Felix release package.

Callers use this exception to distinguish expected fail-closed operational
errors from programming defects without exposing captured command output.
"""


class FelixReleaseError(RuntimeError):
    """Report a safely handled preflight, deploy, health, or rollback failure."""
