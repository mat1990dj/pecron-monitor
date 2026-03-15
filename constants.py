"""
Configuration constants for pecron-monitor.

Contains region configurations, known product mappings, default control definitions,
and sensor field mappings used across all Pecron device models.
"""

# ---------------------------------------------------------------------------
# Region configurations
# ---------------------------------------------------------------------------
REGIONS = {
    "na": {
        "name": "North America",
        "base_url": "https://iot-api.landecia.com",
        "mqtt_host": "iot-south.landecia.com",
        "mqtt_port": 8443,
        "mqtt_path": "/ws/v2",
        "user_domain": "U.DM.10351.1",
        "user_domain_secret": "HARsQXfeex8vxyaPRAM8fyjqqVuH2uxAGQ3inJ8XxTiB",
    },
    "eu": {
        "name": "Europe",
        "base_url": "https://iot-api.acceleronix.io",
        "mqtt_host": "iot-south.quecteleu.com",
        "mqtt_port": 8443,
        "mqtt_path": "/ws/v2",
        "user_domain": "C.DM.10351.1",
        "user_domain_secret": "FA5ZHXSka8y9GHvU91Hz1vWvaDSHE2mGW5B7bpn3fXTW",
    },
    "cn": {
        "name": "China",
        "base_url": "https://iot-api.quectelcn.com",
        "mqtt_host": "iot-south.quectelcn.com",
        "mqtt_port": 8443,
        "mqtt_path": "/ws/v2",
        "user_domain": "C.DM.5903.1",
        "user_domain_secret": "EufftRJSuWuVY7c6txzGifV9bJcfXHAFa7hXY5doXSn7",
    },
}

# ---------------------------------------------------------------------------
# Known product name mappings
# ---------------------------------------------------------------------------
KNOWN_PRODUCTS = {
    "E1500LFP": "E1500 LFP",
    "E300LFP": "E300 LFP",
    "E600LFP": "E600 LFP",
    "E2000LFP": "E2000 LFP",
    "E3000LFP": "E3000 LFP",
}

# ---------------------------------------------------------------------------
# Data point IDs (from Quectel TSL — Thing Specification Language)
# These are universal for each Pecron product model.
# The TSL is fetched dynamically; these are E1500LFP defaults as fallback.
# ---------------------------------------------------------------------------
DEFAULT_CONTROLS = {
    # Common controls (E1500, E2000, E3000, WB12200)
    "ac_switch_hm":           {"id": 40, "type": "BOOL", "desc": "AC output", "access": "RW"},
    "dc_switch_hm":           {"id": 38, "type": "BOOL", "desc": "DC output", "access": "RW"},
    "ups_status_hm":          {"id": 27, "type": "BOOL", "desc": "UPS mode", "access": "RW"},
    "auto_light_flag_as":     {"id": 43, "type": "BOOL", "desc": "Auto screen light", "access": "RW"},
    "machine_screen_light_as":{"id": 45, "type": "ENUM", "desc": "Screen brightness", "access": "RW"},
    # E3800/E3600-specific controls
    "eco_quite_mode_as":      {"id": 44, "type": "BOOL", "desc": "Eco/quiet mode", "access": "RW"},
    "ups_start_charge_value_as": {"id": 46, "type": "INT", "desc": "UPS charge threshold %", "access": "RW"},
    "ac_charging_power_ios":  {"id": 50, "type": "INT", "desc": "AC charging power", "access": "RW"},
    "device_touch_locking_as":{"id": 42, "type": "BOOL", "desc": "Touch panel lock", "access": "RW"},
    "device_standy_times_as": {"id": 51, "type": "INT", "desc": "Standby timeout", "access": "RW"},
    # WB12200-specific controls
    "battery_heating_mode":   {"id": 91, "type": "INT", "desc": "Battery heating mode", "access": "RW"},
    "charging_limit_voltage": {"id": 92, "type": "INT", "desc": "Charging limit voltage", "access": "RW"},
    "discharge_limiting_voltage": {"id": 93, "type": "INT", "desc": "Discharge limit voltage", "access": "RW"},
    "charging_current_limit": {"id": 94, "type": "INT", "desc": "Charging current limit", "access": "RW"},
    "discharge_limiting_current": {"id": 95, "type": "INT", "desc": "Discharge current limit", "access": "RW"},
}

# ---------------------------------------------------------------------------
# Common sensor field mappings — works across all known Pecron models.
# Each sensor maps to a list of paths to try (first match wins).
# Some models (E1500LFP) nest battery/voltage in host_packet_data_jdb,
# while others (E300LFP) report them at the top level.
# ---------------------------------------------------------------------------
SENSOR_FIELDS = {
    "battery_percent": [
        ("host_packet_data_jdb", "host_packet_electric_percentage"),
        ("battery_percentage",),
    ],
    "voltage": [
        ("host_packet_data_jdb", "host_packet_voltage"),
    ],
    "temperature": [
        ("host_packet_data_jdb", "host_packet_temp"),
        ("battery_temp",),  # E3800 uses separate temp sensors
    ],
    # E3800-specific temperature sensors (3 separate sensors)
    "battery_temp": [("battery_temp",)],
    "charging_plate_temp": [("charging_plate_temp",)],
    "inverter_temp": [("inverter_temp",)],
    "charge_status": [
        ("host_packet_data_jdb", "host_packet_status"),
    ],
    "total_input_power": [("total_input_power",)],
    "total_output_power": [("total_output_power",)],
    "remain_time": [("remain_time",)],
    "remain_charging_time": [("remain_charging_time",)],
    "ac_output_power": [("ac_data_output_hm", "ac_output_power")],
    "ac_output_voltage": [("ac_data_output_hm", "ac_output_voltage")],
    "dc_output_power": [("dc_data_output_hm", "dc_output_power")],
    "ac_input_power": [("ac_data_input_hm", "ac_power")],
    "dc_input_power": [("dc_data_input_hm", "dc_input_power")],
    "ac_switch": [("ac_switch_hm",), ("host_packet_data_jdb","host_packet_ac_switch"), ("host_packet_data_jdb","ac_switch")],
    "dc_switch": [("dc_switch_hm",), ("host_packet_data_jdb","host_packet_dc_switch"), ("host_packet_data_jdb","dc_switch")],
    "ups_mode": [("ups_status_hm",), ("host_packet_data_jdb","host_packet_ups_status"), ("host_packet_data_jdb","ups_status")],
    # E3800-specific fields
    "device_status_hm": [("device_status_hm",)],
    "add_bat_status_hm": [("add_bat_status_hm",)],
    # WB12200-specific battery management fields
    "battery_heating_mode": [("battery_heating_mode",)],
    "charging_limit_voltage": [("charging_limit_voltage",)],
    "discharge_limiting_voltage": [("discharge_limiting_voltage",)],
    "charging_current_limit": [("charging_current_limit",)],
    "discharge_limiting_current": [("discharge_limiting_current",)],
}
