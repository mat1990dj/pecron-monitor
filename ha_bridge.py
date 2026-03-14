"""
Home Assistant MQTT bridge for pecron-monitor.

Publishes Home Assistant MQTT auto-discovery config and state updates.
"""

import json
import logging
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from helpers import _truthy, _get_kv, _get_kv_single, _fmt_dhm
from constants import SENSOR_FIELDS

log = logging.getLogger("pecron")


class HomeAssistantBridge:
    """Publishes Home Assistant MQTT auto-discovery config and state updates."""

    def __init__(self, ha_config: dict, devices: list):
        self.ha_config = ha_config
        self.devices = devices
        self.client = None
        self.discovery_prefix = ha_config.get("discovery_prefix", "homeassistant")
        self._connected = False

        # Cache last-known-good values per device so partial payloads don't zero-out entities
        self._state_cache = {}  # device_key -> dict of last published fields
        # Cache last-known values per device so partial payloads (host-only vs SOC-only)
        # don't clobber sensors to 0/unknown in Home Assistant.
        self._last_state = {}  # device_key -> dict

    def connect(self):
        host = self.ha_config.get("mqtt_host", "localhost")
        port = self.ha_config.get("mqtt_port", 1883)
        user = self.ha_config.get("mqtt_user", "")
        pw = self.ha_config.get("mqtt_password", "")

        self.client = mqtt.Client(
            client_id="pecron_ha_bridge",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        if user:
            self.client.username_pw_set(user, pw)

        def on_connect(client, ud, flags, rc, props=None):
            if rc == mqtt.CONNACK_ACCEPTED:
                self._connected = True
                log.info("Home Assistant MQTT bridge connected to %s:%d", host, port)
                self._publish_discovery()
                # Subscribe to command topics
                for device in self.devices:
                    dk = device["device_key"]
                    for ctrl in ["ac", "dc", "ups"]:
                        client.subscribe(f"pecron/{dk}/{ctrl}/set", qos=1)

        def on_message(client, ud, msg):
            # Handle HA commands
            parts = msg.topic.split("/")
            if len(parts) == 4 and parts[3] == "set":
                dk = parts[1]
                ctrl = parts[2]
                payload = msg.payload.decode().upper()
                self._handle_command(dk, ctrl, payload)

        self.client.on_connect = on_connect
        self.client.on_message = on_message
        self.client.connect(host, port)
        self.client.loop_start()

    def _handle_command(self, device_key: str, control: str, payload: str):
        """Called when HA sends a command. Delegates to the monitor."""
        # This will be wired up by PecronMonitor
        if hasattr(self, 'command_callback'):
            self.command_callback(device_key, control, payload == "ON")

    def _publish_discovery(self):
        """Publish HA MQTT auto-discovery messages."""
        for device in self.devices:
            dk = device["device_key"]
            name = device["device_name"]
            dev_info = {
                "identifiers": [f"pecron_{dk}"],
                "name": f"Pecron {name}",
                "manufacturer": "Pecron",
                "model": name,
            }

            # Battery sensor
            self._pub_config("sensor", dk, "battery", {
                "name": "Battery (SOC)",
                "device_class": "battery",
                "unit_of_measurement": "%",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.soc_percent }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_battery",
            })


            # Host pack battery sensor
            self._pub_config("sensor", dk, "host_battery", {
                "name": "Host Battery",
                "device_class": "battery",
                "unit_of_measurement": "%",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.host_percent }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_host_battery",
            })

            # Voltage sensor
            self._pub_config("sensor", dk, "voltage", {
                "name": "Voltage",
                "device_class": "voltage",
                "unit_of_measurement": "V",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.voltage }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_voltage",
            })

            # Temperature sensor (primary/host pack temp)
            self._pub_config("sensor", dk, "temperature", {
                "name": "Temperature",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.temperature }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_temperature",
            })

            # E3800-specific temperature sensors (3 separate sensors)
            self._pub_config("sensor", dk, "battery_temp", {
                "name": "Battery Temperature",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.battery_temp }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_battery_temp",
            })

            self._pub_config("sensor", dk, "charging_plate_temp", {
                "name": "Charging Plate Temperature",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.charging_plate_temp }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_charging_plate_temp",
            })

            self._pub_config("sensor", dk, "inverter_temp", {
                "name": "Inverter Temperature",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.inverter_temp }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_inverter_temp",
            })

            # Power in/out sensors
            for key, label in [("total_input", "Input Power"), ("total_output", "Output Power")]:
                self._pub_config("sensor", dk, key, {
                    "name": label,
                    "device_class": "power",
                    "unit_of_measurement": "W",
                    "state_topic": f"pecron/{dk}/state",
                    "value_template": f"{{{{ value_json.{key}_power }}}}",
                    "device": dev_info,
                    "unique_id": f"pecron_{dk}_{key}",
                })

            # AC input power sensor (separate from DC)
            self._pub_config("sensor", dk, "ac_input", {
                "name": "AC Input Power",
                "device_class": "power",
                "unit_of_measurement": "W",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.ac_input_power }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_ac_input",
            })

            # DC input power sensor (separate from AC)
            self._pub_config("sensor", dk, "dc_input", {
                "name": "DC Input Power",
                "device_class": "power",
                "unit_of_measurement": "W",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.dc_input_power }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_dc_input",
            })

            # Remaining time sensor
            # Remaining time sensor (H:M)
            self._pub_config("sensor", dk, "remaining_time", {
                "name": "Remaining Time",
                "icon": "mdi:timer-outline",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.remain_hm }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_remaining_time",
            })

            # AC switch
            self._pub_config("switch", dk, "ac", {
                "name": "AC Output",
                "icon": "mdi:power-plug",
                "command_topic": f"pecron/{dk}/ac/set",
                "optimistic": True,
                "assumed_state": True,
                "payload_on": "ON", "payload_off": "OFF",
                "state_on": "ON", "state_off": "OFF",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_ac",
            })

            # DC switch
            self._pub_config("switch", dk, "dc", {
                "name": "DC Output",
                "icon": "mdi:usb-port",
                "command_topic": f"pecron/{dk}/dc/set",
                "optimistic": True,
                "assumed_state": True,
                "payload_on": "ON", "payload_off": "OFF",
                "state_on": "ON", "state_off": "OFF",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_dc",
            })

            # UPS switch
            self._pub_config("switch", dk, "ups", {
                "name": "UPS Mode",
                "icon": "mdi:shield-battery",
                "command_topic": f"pecron/{dk}/ups/set",
                "optimistic": True,
                "assumed_state": True,
                "payload_on": "ON", "payload_off": "OFF",
                "state_on": "ON", "state_off": "OFF",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_ups",
            })

        log.info("Published Home Assistant discovery configs")

    def _pub_config(self, component: str, dk: str, key: str, config: dict):
        topic = f"{self.discovery_prefix}/{component}/pecron_{dk}/{key}/config"
        self.client.publish(topic, json.dumps(config), qos=1, retain=True)

    def publish_state(self, device_key: str, kv: dict):
        """Publish current state to HA.

        The device sends multiple payload "shapes" (e.g., host packet vs overall packet).
        Some shapes omit fields and/or carry placeholder zeros; without caching, HA entities
        will flap between valid values and 0/unknown. We therefore merge updates into a
        per-device cache and only overwrite fields when the source field is present.
        """
        if not self._connected:
            return

        cache = self._state_cache.setdefault(device_key, {})

        def _get_first_present(paths):
            """
            Return (present, value) for the first path that exists in this payload shape.
            'present' means the field path resolved to a non-None value (0 is valid).
            """
            for p in paths:
                val = _get_kv_single(kv, p)
                if val is not None:
                    return True, val
            return False, None

        # Identify payload shape (host packet vs overall packet)
        host_dict = kv.get("host_packet_data_jdb")
        packet_has_host = isinstance(host_dict, dict) and bool(host_dict)

        # ---- Core sensors ----
        # For these, only overwrite when their source field exists in the payload shape.
        # Accept 0 as a real reading *only if the source path is present*.
        present, v = _get_first_present(SENSOR_FIELDS["voltage"])
        if present:
            try:
                cache["voltage"] = round(float(v), 1)
            except (TypeError, ValueError):
                pass

        present, v = _get_first_present(SENSOR_FIELDS["temperature"])
        if present:
            try:
                cache["temperature"] = int(float(v))
            except (TypeError, ValueError):
                pass

        # E3800-specific temperature sensors
        present, v = _get_first_present(SENSOR_FIELDS["battery_temp"])
        if present:
            try:
                cache["battery_temp"] = int(float(v))
            except (TypeError, ValueError):
                pass

        present, v = _get_first_present(SENSOR_FIELDS["charging_plate_temp"])
        if present:
            try:
                cache["charging_plate_temp"] = int(float(v))
            except (TypeError, ValueError):
                pass

        present, v = _get_first_present(SENSOR_FIELDS["inverter_temp"])
        if present:
            try:
                cache["inverter_temp"] = int(float(v))
            except (TypeError, ValueError):
                pass

        present, v = _get_first_present(SENSOR_FIELDS["total_input_power"])
        if present and (not packet_has_host or float(v) != 0.0):
            try:
                cache["total_input_power"] = int(float(v))
            except (TypeError, ValueError):
                pass

        present, v = _get_first_present(SENSOR_FIELDS["total_output_power"])
        if present and (not packet_has_host or float(v) != 0.0):
            try:
                cache["total_output_power"] = int(float(v))
            except (TypeError, ValueError):
                pass

        # AC and DC input power (separate sensors for E3800 and others)
        present, v = _get_first_present(SENSOR_FIELDS["ac_input_power"])
        if present and (not packet_has_host or float(v) != 0.0):
            try:
                cache["ac_input_power"] = int(float(v))
            except (TypeError, ValueError):
                pass

        present, v = _get_first_present(SENSOR_FIELDS["dc_input_power"])
        if present and (not packet_has_host or float(v) != 0.0):
            try:
                cache["dc_input_power"] = int(float(v))
            except (TypeError, ValueError):
                pass

        present, v = _get_first_present(SENSOR_FIELDS["remain_time"])
        if present and (not packet_has_host or float(v) != 0.0):
            try:
                cache["remain_minutes"] = int(float(v))
            except (TypeError, ValueError):
                pass

        # Human-friendly remaining time for UI
        cache["remain_hm"] = _fmt_dhm(cache.get("remain_minutes"))

        # ---- Switch states ----
        # Some payloads don't include these; cache last known.
        def _update_switch(field_key, out_key):
            present, v = _get_first_present(SENSOR_FIELDS[field_key])
            if present:
                cache[out_key] = "ON" if _truthy(v) else "OFF"

        _update_switch("ac_switch", "ac_switch")
        _update_switch("dc_switch", "dc_switch")
        _update_switch("ups_mode", "ups_mode")

        # AC output sensors
        present, v = _get_first_present(SENSOR_FIELDS["ac_output_power"])
        if present:
            try:
                cache["ac_output_power"] = int(float(v))
            except (TypeError, ValueError):
                pass

        present, v = _get_first_present(SENSOR_FIELDS["ac_output_voltage"])
        if present:
            try:
                cache["ac_output_voltage"] = int(float(v))
            except (TypeError, ValueError):
                pass

        # ---- SOC vs Host % ----
        # Your device alternates two payload shapes:
        #   * host packet (has host_packet_data_jdb.*) -> host %
        #   * overall packet (no host_packet_data_jdb) -> overall SOC %
        #
        # IMPORTANT: when host_packet_data_jdb is present, battery_percentage mirrors host %,
        # so we *must not* treat it as SOC in that shape.
        if packet_has_host:
            present, v = _get_first_present([("host_packet_data_jdb", "host_packet_electric_percentage")])
            if present:
                try:
                    cache["host_percent"] = int(float(v))
                except (TypeError, ValueError):
                    pass
        else:
            present, v = _get_first_present([("battery_percentage",)])
            if present:
                try:
                    cache["soc_percent"] = int(float(v))
                except (TypeError, ValueError):
                    pass

        # Ensure keys exist for HA templates (but don't force unknown -> 0)
        cache.setdefault("host_percent", None)
        cache.setdefault("soc_percent", None)
        cache.setdefault("remain_hm", _fmt_dhm(cache.get("remain_minutes")))

        self.client.publish(f"pecron/{device_key}/state", json.dumps(cache), qos=1, retain=True)

    def disconnect(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
