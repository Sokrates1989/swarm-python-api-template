"""
Module: release_profile_errors.py

Description:
    Defines the shared failure type used by Felix deployment-profile parsing,
    guided setup, and deployment-field validation.
"""


class SwarmReleaseProfileError(ValueError):
    """Reports an unsafe, inconsistent, malformed, or missing Swarm profile."""
