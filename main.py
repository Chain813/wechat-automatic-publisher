"""Thin entrypoint for the publishing workflow."""

from core.runtime import configure_runtime
from core.workflow import run_main


if __name__ == "__main__":
    configure_runtime()
    run_main()
