"""Thin entrypoint for the publishing workflow."""

from core.shared.runtime import configure_runtime
from core.engine import run_main


if __name__ == "__main__":
    configure_runtime()
    run_main()
