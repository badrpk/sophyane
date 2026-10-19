#!/usr/bin/env python3
"""Build a separate Sophyane-enabled Debian arm64 guest image."""

from __future__ import annotations

import argparse
from pathlib import Path

from sophyane.rsi.guest_image import GuestImageBuilder


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_image", type=Path)
    parser.add_argument("output_image", type=Path)
    parser.add_argument("--tool", default="virt-customize")
    parser.add_argument("--assets", type=Path, default=Path(__file__).parents[1] / "guest")
    args = parser.parse_args()
    manifest = GuestImageBuilder(args.source_image, args.output_image, args.tool, args.assets).build()
    print(manifest.manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
