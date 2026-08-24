#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_MODULES = (
    "agora.evaluation.professor",
    "agora.evaluation.kat",
)


def measure(module: str) -> float:
    script = (
        "import platform, resource; "
        f"import {module}; "
        "rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; "
        "print(rss / (1048576 if platform.system() == 'Darwin' else 1024))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure retrieval-pipeline import RSS in isolated processes."
    )
    parser.add_argument("--modules", nargs="+", default=list(DEFAULT_MODULES))
    parser.add_argument("--output")
    args = parser.parse_args()
    pipelines = {
        module.rsplit(".", 1)[-1]: {
            "module": module,
            "import_peak_rss_mb": measure(module),
        }
        for module in args.modules
    }
    payload = {
        "measured_at": datetime.now(UTC).date().isoformat(),
        "environment": {
            "platform": f"{platform.system().lower()}-{platform.machine().lower()}",
            "python": platform.python_version(),
            "venv_symlink": Path(".venv").is_symlink(),
        },
        "pipelines": pipelines,
    }
    text = json.dumps(payload, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
