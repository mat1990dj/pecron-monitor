#!/usr/bin/env python3
"""Test read_status() against locally configured live devices.

Device configuration is loaded from a local JSON file or environment variable so
live IPs and auth keys are never committed to source control.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from constants import SENSOR_FIELDS
from local_transport import LocalTransport
from tests.hardware.config_loader import load_hardware_devices

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")


def extract_sensor(kv, sensor_name):
    """Extract sensor value using SENSOR_FIELDS fallback chain."""
    paths = SENSOR_FIELDS.get(sensor_name, [])
    for path in paths:
        val = kv
        for key in path:
            if isinstance(val, dict):
                val = val.get(key)
            else:
                val = None
                break
        if val is not None:
            return val
    return None


def test_device(device):
    """Test a device and verify expected data."""
    device_key = device["device_key"]
    lan_ip = device["lan_ip"]
    print("\n" + "=" * 80)
    print(f"TESTING: {device_key}")
    print("=" * 80)

    transport = LocalTransport(lan_ip, device["auth_key"])

    if not transport.connect():
        print(f"❌ FAIL: Could not connect to {device_key} at {lan_ip}")
        return False

    print(f"✅ Connected to {device_key} at {lan_ip}")

    kv = transport.read_status()
    transport.disconnect()

    if not kv:
        print(f"❌ FAIL: No data received from {device_key}")
        return False

    battery = extract_sensor(kv, "battery_percent")
    voltage = extract_sensor(kv, "voltage")
    temp = extract_sensor(kv, "temperature")

    print("\nReceived data:")
    print(f"  Battery:     {battery}%")
    print(f"  Voltage:     {voltage}V")
    print(f"  Temperature: {temp}°C")

    failures = []
    if battery is None:
        failures.append("Battery % is missing")
    if voltage is None or voltage == 0:
        failures.append("Voltage is missing or 0V")
    if temp is None:
        failures.append("Temperature is missing")

    print(f"\nRaw data keys: {sorted(kv.keys())}")

    if failures:
        print(f"\n❌ FAIL: {device_key} validation errors:")
        for err in failures:
            print(f"  - {err}")
        return False

    print(f"\n✅ PASS: {device_key} data is present")
    return True


def main():
    """Test all locally configured hardware devices."""
    devices = load_hardware_devices()
    results = {}

    for device in devices:
        device_key = device["device_key"]
        try:
            results[device_key] = test_device(device)
        except Exception as exc:
            print(f"\n❌ EXCEPTION testing {device_key}: {exc}")
            import traceback

            traceback.print_exc()
            results[device_key] = False

    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    for device_key, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{device_key:15s} {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
