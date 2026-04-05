"""
tests/hardware/ — tests that require a live Pecron device on the LAN.

These are NOT collected by default. They exist as runnable scripts for manual
integration verification. To run them:

    python3 tests/hardware/test_all_devices.py
    python3 tests/hardware/test_auto_discovery.py

Or explicitly with pytest:

    pytest tests/hardware/ --override-ini="python_files=test_*.py" -p no:cacheprovider

Update the IP addresses and auth keys inside each script to match your devices
before running.
"""

# Skip collection of everything in this directory by pytest unless explicitly requested.
collect_ignore_glob = ["test_*.py"]
