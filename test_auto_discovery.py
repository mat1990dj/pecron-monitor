#!/usr/bin/env python3
"""
Test auto-discovery of Pecron devices on LAN.

Tests that:
1. Devices are found at correct IPs on 192.168.68.0/24
2. Auth key matching correctly identifies each device
3. Discovery works when lan_ip is not in config (pure discovery mode)
"""

import sys
from lan_scan import discover_devices

# Test devices (live on 192.168.68.0/24)
TEST_DEVICES = [
    {
        "device_key": "E1500LFP",
        "auth_key": "RCYekGPSPydAZCgqfxUnqg==",
        "expected_ip": "192.168.68.58"
    },
    {
        "device_key": "E3800LFP",
        "auth_key": "qcrHxigPxyZampzANNgJOQ==",
        "expected_ip": "192.168.68.65"
    },
    {
        "device_key": "WB12200",
        "auth_key": "bmrPxdGIGHIby/6j2sRfyw==",
        "expected_ip": "192.168.68.51"
    }
]


def test_discovery():
    """Test that all 3 devices are discovered at correct IPs."""
    print("\n" + "=" * 60)
    print("Testing Auto-Discovery of Pecron Devices")
    print("=" * 60)

    # Prepare devices for discovery (without lan_ip — pure discovery mode)
    devices = [
        {"device_key": d["device_key"], "auth_key": d["auth_key"]}
        for d in TEST_DEVICES
    ]

    print(f"\nSearching for {len(devices)} devices on 192.168.68.0/24...")
    print(f"  - {devices[0]['device_key']}")
    print(f"  - {devices[1]['device_key']}")
    print(f"  - {devices[2]['device_key']}")

    # Run discovery
    discovered = discover_devices(devices, timeout=0.5)

    print("\n" + "=" * 60)
    print("Discovery Results")
    print("=" * 60)

    # Check results
    all_passed = True
    for test_device in TEST_DEVICES:
        dk = test_device["device_key"]
        expected_ip = test_device["expected_ip"]

        if dk in discovered:
            actual_ip = discovered[dk]
            if actual_ip == expected_ip:
                print(f"✅ {dk}: found at {actual_ip} (correct)")
            else:
                print(f"⚠️  {dk}: found at {actual_ip} (expected {expected_ip})")
                all_passed = False
        else:
            print(f"❌ {dk}: NOT FOUND (expected {expected_ip})")
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(test_discovery())
