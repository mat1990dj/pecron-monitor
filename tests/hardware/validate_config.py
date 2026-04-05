#!/usr/bin/env python3
"""Validate local hardware test configuration and optionally filter devices.

Usage:
    python3 tests/hardware/validate_config.py
    python3 tests/hardware/validate_config.py E1500LFP E3800LFP

Reads configuration from PECRON_HARDWARE_CONFIG or PECRON_HARDWARE_JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.hardware.config_loader import load_hardware_devices


def main(argv: list[str]) -> int:
    requested = set(argv[1:])
    devices = load_hardware_devices()
    if requested:
        devices = [device for device in devices if device["device_key"] in requested]
        if not devices:
            print(f"No configured devices matched: {', '.join(sorted(requested))}")
            return 1

    print(json.dumps(devices, indent=2, sort_keys=True))
    print(f"\nValidated {len(devices)} hardware device configuration(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
