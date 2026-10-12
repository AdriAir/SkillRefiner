"""Standard-library-only runtime checks for the Skill Refiner CLI."""

from __future__ import annotations

from importlib import metadata
import sys


REQUIRED_DISTRIBUTIONS = {
    "PyYAML": "6.0.3",
    "jsonschema": "4.25.1",
}


def runtime_issues(python_version=None, installed_versions=None):
    """Return actionable runtime problems without importing third-party code."""
    python_version = tuple(python_version or sys.version_info[:3])
    if python_version < (3, 12):
        actual = ".".join(str(part) for part in python_version)
        return ("Python 3.12 or newer is required (found " + actual + ").",)

    issues = []
    for distribution, expected in REQUIRED_DISTRIBUTIONS.items():
        if installed_versions is None:
            try:
                actual = metadata.version(distribution)
            except metadata.PackageNotFoundError:
                actual = None
        else:
            actual = installed_versions.get(distribution)

        if actual is None:
            issues.append("Required dependency " + distribution + "==" + expected + " is missing.")
        elif actual != expected:
            issues.append(
                "Required dependency " + distribution + "==" + expected
                + " is installed as " + actual + "."
            )
    return tuple(issues)
