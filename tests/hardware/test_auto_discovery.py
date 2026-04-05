#!/usr/bin/env python3
"""Test auto-discovery of locally configured Pecron devices on the LAN."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lan_scan import discover_devices
from tests.hardware.config_loader import load_hardware_devices


def test_discovery():
    """Test that configured devices are discovered at their configured LAN IPs."""
    test_devices = load_hardware_devices()

    print("\n" + "=" * 60)
    print("Testing Auto-Discovery of Pecron Devices")
    print("=" * 60)

    devices = [
        {"device_key": device["device_key"], "auth_key": device["auth_key"]}
        for device in test_devices
    ]

    print(f"\nSearching for {len(devices)} devices on the local /24...")
    for device in devices:
        print(f"  - {device['device_key']}")

    discovered = discover_devices(devices, timeout=0.5)

    print("\n" + "=" * 60)
    print("Discovery Results")
    print("=" * 60)

    all_passed = True
    for test_device in test_devices:
        device_key = test_device["device_key"]
        lan_ip = test_device["lan_ip"]

        if device_key in discovered:
            actual_ip = discovered[device_key]
            if actual_ip == lan_ip:
                print(f"✅ {device_key}: found at {actual_ip} (correct)")
            else:
                print(f"⚠️  {device_key}: found at {actual_ip} (expected {lan_ip})")
                all_passed = False
        else:
            print(f"❌ {device_key}: NOT FOUND (expected {lan_ip})")
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        return 0

    print("❌ SOME TESTS FAILED")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(test_discovery())
