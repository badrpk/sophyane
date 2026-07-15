#!/usr/bin/env python3
"""Python example using Sophyane Hardware API (in-process)."""

from sophyane.hardware_api import create_default_api
from sophyane.hardware_registry import format_hardware_report


def main() -> None:
    api = create_default_api()
    print("health:", api.health())
    print("backends:", api.backends())
    print(format_hardware_report())
    reply = api.chat("Say hi in three words", edge=True)
    print("chat:", reply)


if __name__ == "__main__":
    main()
