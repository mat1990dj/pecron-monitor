#!/usr/bin/env python3
"""Test the fixed read_status() against all 3 live devices."""

import sys
import logging
from local_transport import LocalTransport
from constants import SENSOR_FIELDS

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

DEVICES = {
    "E1500LFP": {
        "ip": "192.168.68.58",
        "auth_key": "RCYekGPSPydAZCgqfxUnqg==",
        "expected": {
            "battery_percent": 100,
            "voltage": 56.0,  # Approximate
            "temperature": 25,  # Approximate
        }
    },
    "E3800LFP": {
        "ip": "192.168.68.65",
        "auth_key": "qcrHxigPxyZampzANNgJOQ==",
        "expected": {
            "battery_percent": 100,
            "voltage": 50.0,  # Should NOW work!
            "temperature": 30,  # Should have temp
        }
    },
    "WB12200": {
        "ip": "192.168.68.51",
        "auth_key": "bmrPxdGIGHIby/6j2sRfyw==",
        "expected": {
            "battery_percent": 1,
            "voltage": 13.0,
            "temperature": 23,
        }
    }
}


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


def test_device(device_name, config):
    """Test a device and verify expected data."""
    print("\n" + "="*80)
    print(f"TESTING: {device_name}")
    print("="*80)

    transport = LocalTransport(config["ip"], config["auth_key"])

    if not transport.connect():
        print(f"❌ FAIL: Could not connect to {device_name}")
        return False

    print(f"✅ Connected to {device_name}")

    # Read status
    kv = transport.read_status()
    transport.disconnect()

    if not kv:
        print(f"❌ FAIL: No data received from {device_name}")
        return False

    # Extract sensors
    battery = extract_sensor(kv, "battery_percent")
    voltage = extract_sensor(kv, "voltage")
    temp = extract_sensor(kv, "temperature")

    print(f"\nReceived data:")
    print(f"  Battery:     {battery}%")
    print(f"  Voltage:     {voltage}V")
    print(f"  Temperature: {temp}°C")

    # Check expectations
    expected = config["expected"]
    failures = []

    if battery is None:
        failures.append("Battery % is missing")
    elif abs(battery - expected["battery_percent"]) > 5:
        failures.append(f"Battery % mismatch: got {battery}, expected ~{expected['battery_percent']}")

    if voltage is None or voltage == 0:
        failures.append("Voltage is missing or 0V")
    elif abs(voltage - expected["voltage"]) > 10:
        failures.append(f"Voltage out of range: got {voltage}V, expected ~{expected['voltage']}V")

    if temp is None:
        failures.append("Temperature is missing")
    elif abs(temp - expected["temperature"]) > 10:
        failures.append(f"Temperature out of range: got {temp}°C, expected ~{expected['temperature']}°C")

    # Check device-specific fields
    if device_name == "E3800LFP":
        battery_temp = extract_sensor(kv, "battery_temp")
        charging_plate_temp = extract_sensor(kv, "charging_plate_temp")
        inverter_temp = extract_sensor(kv, "inverter_temp")
        print(f"\n  E3800 temps:")
        print(f"    Battery:        {battery_temp}°C")
        print(f"    Charging plate: {charging_plate_temp}°C")
        print(f"    Inverter:       {inverter_temp}°C")

    if device_name == "WB12200":
        heating = extract_sensor(kv, "battery_heating_mode")
        charge_limit = extract_sensor(kv, "charging_limit_voltage")
        discharge_limit = extract_sensor(kv, "discharge_limiting_voltage")
        print(f"\n  WB12200 battery management:")
        print(f"    Heating mode:        {heating}")
        print(f"    Charge limit V:      {charge_limit}")
        print(f"    Discharge limit V:   {discharge_limit}")

    # Print raw kv for debugging
    print(f"\nRaw data keys: {sorted(kv.keys())}")

    if failures:
        print(f"\n❌ FAIL: {device_name} validation errors:")
        for err in failures:
            print(f"  - {err}")
        return False

    print(f"\n✅ PASS: {device_name} data is correct!")
    return True


def main():
    """Test all devices."""
    results = {}

    for device_name, config in DEVICES.items():
        try:
            results[device_name] = test_device(device_name, config)
        except Exception as e:
            print(f"\n❌ EXCEPTION testing {device_name}: {e}")
            import traceback
            traceback.print_exc()
            results[device_name] = False

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    for device, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{device:15s} {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
