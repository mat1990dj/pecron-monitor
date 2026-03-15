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

            # === E3800-specific automation controls ===
            # These only appear if the device has these capabilities
            # (HA will just show "unavailable" if the device doesn't report them)

            # Eco/Quiet mode switch
            self._pub_config("switch", dk, "eco_mode", {
                "name": "Eco Mode",
                "icon": "mdi:leaf",
                "command_topic": f"pecron/{dk}/eco_mode/set",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.eco_quite_mode_as }}",
                "state_on": "ON", "state_off": "OFF",
                "payload_on": "ON", "payload_off": "OFF",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_eco_mode",
            })

            # Touch panel lock
            self._pub_config("switch", dk, "touch_lock", {
                "name": "Touch Panel Lock",
                "icon": "mdi:lock",
                "command_topic": f"pecron/{dk}/touch_lock/set",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.device_touch_locking_as }}",
                "state_on": "ON", "state_off": "OFF",
                "payload_on": "ON", "payload_off": "OFF",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_touch_lock",
            })

            # AC charging power level
            self._pub_config("sensor", dk, "ac_charging_power", {
                "name": "AC Charging Power Setting",
                "icon": "mdi:flash",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.ac_charging_power_ios }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_ac_charging_power",
            })

            # UPS charge threshold
            self._pub_config("sensor", dk, "ups_charge_threshold", {
                "name": "UPS Charge Threshold",
                "icon": "mdi:battery-charging",
                "unit_of_measurement": "%",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.ups_start_charge_value_as }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_ups_charge_threshold",
            })

            # Standby timeout
            self._pub_config("sensor", dk, "standby_timeout", {
                "name": "Standby Timeout",
                "icon": "mdi:timer-sand",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.device_standy_times_as }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_standby_timeout",
            })

            # Bypass mode
            self._pub_config("switch", dk, "bypass", {
                "name": "Bypass Mode",
                "icon": "mdi:transfer",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.bypass_enable }}",
                "state_on": "ON", "state_off": "OFF",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_bypass",
            })

            # AC output power sensor
            self._pub_config("sensor", dk, "ac_output", {
                "name": "AC Output Power",
                "device_class": "power",
                "unit_of_measurement": "W",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.ac_output_power }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_ac_output",
            })

            # AC output voltage sensor
            self._pub_config("sensor", dk, "ac_output_voltage", {
                "name": "AC Output Voltage",
                "device_class": "voltage",
                "unit_of_measurement": "V",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.ac_output_voltage }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_ac_output_voltage",
            })

            # === WB12200 battery management sensors ===
            self._pub_config("sensor", dk, "charging_limit_voltage", {
                "name": "Charging Limit Voltage",
                "device_class": "voltage",
                "icon": "mdi:battery-charging-high",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.charging_limit_voltage }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_charging_limit_voltage",
            })

            self._pub_config("sensor", dk, "discharge_limit_voltage", {
                "name": "Discharge Limit Voltage",
                "device_class": "voltage",
                "icon": "mdi:battery-low",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.discharge_limiting_voltage }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_discharge_limit_voltage",
            })

            self._pub_config("sensor", dk, "charging_current_limit", {
                "name": "Charging Current Limit",
                "device_class": "current",
                "unit_of_measurement": "A",
                "icon": "mdi:current-dc",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.charging_current_limit }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_charging_current_limit",
            })

            self._pub_config("sensor", dk, "discharge_current_limit", {
                "name": "Discharge Current Limit",
                "device_class": "current",
                "unit_of_measurement": "A",
                "icon": "mdi:current-dc",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.discharge_limiting_current }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_discharge_current_limit",
            })

            self._pub_config("sensor", dk, "battery_heating", {
                "name": "Battery Heating Mode",
                "icon": "mdi:radiator",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.battery_heating_mode }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_battery_heating",
            })

            # Beep/voice switch (WB12200)
            self._pub_config("switch", dk, "beep", {
                "name": "Beep/Voice Alert",
                "icon": "mdi:volume-high",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.beep_voice_us }}",
                "state_on": "ON", "state_off": "OFF",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_beep",
            })

            # Fault alarm sensor
            self._pub_config("sensor", dk, "fault_alarm", {
                "name": "Fault Alarm",
                "icon": "mdi:alert-circle",
                "state_topic": f"pecron/{dk}/state",
                "value_template": "{{ value_json.FAULT_ALARM_ENUM }}",
                "device": dev_info,
                "unique_id": f"pecron_{dk}_fault_alarm",
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
        # ALWAYS publish input power values (including 0) — 0W is valid, "Unknown" is not
        present, v = _get_first_present(SENSOR_FIELDS["ac_input_power"])
        if present:
            try:
                cache["ac_input_power"] = int(float(v))
            except (TypeError, ValueError):
                pass

        present, v = _get_first_present(SENSOR_FIELDS["dc_input_power"])
        if present:
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

        # ---- E3800 automation controls ----
        for field in ("eco_quite_mode_as", "device_touch_locking_as", "bypass_enable"):
            v = kv.get(field)
            if v is not None:
                cache[field] = "ON" if _truthy(v) else "OFF"

        for field in ("ac_charging_power_ios", "ups_start_charge_value_as",
                       "device_standy_times_as"):
            v = kv.get(field)
            if v is not None:
                cache[field] = v

        # ---- WB12200 battery management ----
        for field in ("battery_heating_mode", "charging_limit_voltage",
                       "discharge_limiting_voltage", "charging_current_limit",
                       "discharge_limiting_current", "FAULT_ALARM_ENUM"):
            v = kv.get(field)
            if v is not None:
                cache[field] = v

        for field in ("beep_voice_us", "battery_indicator_us"):
            v = kv.get(field)
            if v is not None:
                cache[field] = "ON" if _truthy(v) else "OFF"

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
