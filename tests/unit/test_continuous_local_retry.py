#!/usr/bin/env python3
"""Tests for continuous monitoring active retry behavior within a cycle (issue #84)."""

import time
from unittest.mock import MagicMock, patch
import pytest

from monitor import PecronMonitor


def make_test_monitor(make_config, model_name="E3800LFP", with_local=True):
    config = make_config(with_lan=True, with_auth=True)
    monitor = PecronMonitor(config)
    monitor.devices = [
        {
            "product_key": "p11uJn",
            "device_key": "AABBCCDDEEFF",
            "device_name": model_name,
            "product_name": model_name,
            "controls": {},
        }
    ]
    if with_local:
        monitor.local_transports = {"AABBCCDDEEFF": MagicMock()}
    else:
        monitor.local_transports = {}
    monitor.latest_data = {}
    return monitor


def test_continuous_run_retries_for_multi_packet_device(make_config):
    """Verify that multi-packet devices with local TCP configured enter the active retry cycle."""
    monitor = make_test_monitor(make_config, "E3800LFP", with_local=True)
    monitor.authenticate = MagicMock()
    monitor.connect_mqtt = MagicMock()
    monitor._request_status = MagicMock()

    # Simulate incomplete telemetry payloads
    monitor._has_telemetry_fields = MagicMock(return_value=False)

    # Force the main while loop to exit immediately after one iteration
    def fake_sleep(seconds):
        monitor._running = False

    with patch("monitor.time.sleep", side_effect=fake_sleep):
        monitor.run()

    # Should execute multiple retries: initial request + cycle request + retry loop calls
    assert monitor._request_status.call_count > 2


def test_continuous_run_no_retry_for_single_packet_device(make_config):
    """Verify that single-packet models never enter the retry cycle and avoid latency overhead."""
    monitor = make_test_monitor(make_config, "E1500LFP", with_local=True)
    monitor.authenticate = MagicMock()
    monitor.connect_mqtt = MagicMock()
    monitor._request_status = MagicMock()
    monitor._has_telemetry_fields = MagicMock(return_value=False)

    def fake_sleep(seconds):
        monitor._running = False

    with patch("monitor.time.sleep", side_effect=fake_sleep):
        monitor.run()

    # Exactly 2 calls: 1 initial cold call, 1 inside the loop cycle (retry loop skipped)
    assert monitor._request_status.call_count == 2


def test_continuous_run_no_retry_without_local_transport(make_config):
    """Verify that multi-packet devices operating strictly over cloud ignore local TCP retry passes."""
    monitor = make_test_monitor(make_config, "E3800LFP", with_local=False)
    monitor.authenticate = MagicMock()
    monitor.connect_mqtt = MagicMock()
    monitor._request_status = MagicMock()
    monitor._has_telemetry_fields = MagicMock(return_value=False)

    def fake_sleep(seconds):
        monitor._running = False

    with patch("monitor.time.sleep", side_effect=fake_sleep):
        monitor.run()

    # Skips retry loop entirely because local_transports is unconfigured for the device
    assert monitor._request_status.call_count == 2


def test_continuous_run_stops_early_if_telemetry_arrives(make_config):
    """Verify the active loop drops out immediately once valid telemetry data is captured."""
    monitor = make_test_monitor(make_config, "E3800LFP", with_local=True)
    monitor.authenticate = MagicMock()
    monitor.connect_mqtt = MagicMock()

    calls = {"n": 0}
    def fake_request_status():
        calls["n"] += 1
        # Populate mock complete data on the first inner retry cycle loop
        if calls["n"] >= 3:
            monitor.latest_data["AABBCCDDEEFF"] = {
                "host_packet_data_jdb": {"host_packet_voltage": 54.2}
            }

    monitor._request_status = MagicMock(side_effect=fake_request_status)

    # Let the internal logic process data changes cleanly
    def fake_sleep(seconds):
        if seconds == monitor.config.get("poll_interval"):
            monitor._running = False

    with patch("monitor.time.sleep", side_effect=fake_sleep):
        monitor.run()

    # Loop should exit gracefully once full telemetry lands instead of exhausting max_wait boundaries
    assert calls["n"] <= 4
