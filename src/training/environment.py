from __future__ import annotations

import importlib
import platform
import subprocess
import sys
from pathlib import Path


def _version(
    module_name: str,
) -> str | None:
    try:
        module = importlib.import_module(
            module_name
        )

        return str(
            getattr(
                module,
                "__version__",
                "UNKNOWN",
            )
        )

    except Exception:
        return None


def capture_code_revision(
    project_root: Path,
) -> str:
    try:
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "HEAD",
            ],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )

        value = (
            result.stdout.strip()
        )

        return (
            value
            or "UNAVAILABLE"
        )

    except Exception:
        return "UNAVAILABLE"


def capture_environment() -> dict:
    return {
        "python": (
            sys.version.split()[0]
        ),
        "python_executable": (
            sys.executable
        ),
        "platform": (
            platform.platform()
        ),
        "numpy": (
            _version("numpy")
        ),
        "pandas": (
            _version("pandas")
        ),
        "sqlalchemy": (
            _version("sqlalchemy")
        ),
        "sklearn": (
            _version("sklearn")
        ),
        "joblib": (
            _version("joblib")
        ),
        "xgboost": (
            _version("xgboost")
        ),
        "tensorflow": (
            _version("tensorflow")
        ),
    }