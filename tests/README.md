# Tests

```
tests/
├── conftest.py          Shared fixtures; mocks paho.mqtt globally
├── unit/                Pure-function and isolated-unit tests (run by default)
├── contract/            SENSOR_FIELDS + schema tests against real captures
├── fixtures/
│   ├── mqtt_payloads/   Captured device JSON payloads (one file per model)
│   └── ttlv_packets/    Captured raw TTLV bytes (hex-encoded, one file per frame)
└── hardware/            Live-device tests — NOT collected by default
```

## Running

```bash
pip install -e ".[test]"        # installs runtime + test deps
pytest                          # unit + contract tests
pytest --cov=. --cov-report=term-missing
pytest -k protocol              # filter by keyword
pytest -m "not slow"            # skip slow tests
```

The unit tests import production modules like `monitor.py`, so runtime dependencies
must be installed before running `pytest`.

Hardware tests require real devices on the LAN and are excluded from
automatic collection. They load device definitions from local-only environment
variables so live IPs and auth keys never need to be committed.

Start from the committed example file:

```bash
cp tests/hardware/hardware-devices.example.json tests/hardware/hardware-devices.local.json
# edit the copied file with your real device_key, auth_key, and lan_ip values
export PECRON_HARDWARE_CONFIG=tests/hardware/hardware-devices.local.json
python3 tests/hardware/test_all_devices.py
python3 tests/hardware/test_auto_discovery.py
```

Or provide the JSON inline:

```bash
export PECRON_HARDWARE_JSON='[{"device_key":"AABBCCDDEEFF","auth_key":"base64key==","lan_ip":"192.168.1.100"}]'
python3 tests/hardware/validate_config.py
```

## Adding real captures

The contract tests run against synthetic payloads by default. To tighten them
against your actual devices:

**MQTT payload (per model)**

```bash
python3 pecron_monitor.py --raw > /tmp/raw.txt
# Extract the "RAW JSON DATA" block and save as:
#   tests/fixtures/mqtt_payloads/<MODEL>.json
```

Then register it in `tests/contract/test_sensor_fields.py`:

```python
REAL_CAPTURES = {
    "E1500LFP": "E1500LFP.json",
    "E300LFP": "E300LFP.json",
}
```

**TTLV frame (per command type)**

Capture the raw bytes sent over port 6607 with tcpdump/wireshark, then:

```bash
echo "aaaa00051200010011" > tests/fixtures/ttlv_packets/status_request.hex
```

The golden tests in `test_protocol.py` will pick it up automatically.
