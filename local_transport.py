"""
Local transports for Pecron Monitor — TCP/6607 and BLE with AES-CBC encryption.

Connects to Pecron device on LAN (WiFi TCP) or via Bluetooth Low Energy,
performs handshake (random exchange + SHA-256 login), then sends/receives
encrypted TTLV commands. Produces the same kv dict structure as MQTT
so existing _process_data() works unchanged.

This module is optional — pecron_monitor.py works without it (cloud-only mode).

Requires: pycryptodome (pip install pycryptodome)
Optional: bleak (pip install bleak) — for BLE transport
"""

import base64
import hashlib
import logging
import socket
import struct
import threading
import time
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

log = logging.getLogger("pecron")


# ===========================================================================
# TTLV codec (local TCP variant — AES-CBC encrypted payloads)
# ===========================================================================

def _ttlv_crc(data: bytes) -> int:
    return sum(data) & 0xFF


def _ttlv_byte_stuff(raw: bytes) -> bytes:
    out = bytearray(raw[:2])
    i = 2
    while i < len(raw):
        out.append(raw[i])
        if i < len(raw) - 1 and raw[i] == 0xAA and raw[i + 1] in (0x55, 0xAA):
            out.append(0x55)
        i += 1
    return bytes(out)


def _ttlv_byte_unstuff(raw: bytes) -> bytes:
    out = bytearray(raw[:2])
    i = 2
    while i < len(raw):
        if i < len(raw) - 1 and raw[i] == 0xAA and raw[i + 1] == 0x55:
            out.append(0xAA)
            i += 2
        else:
            out.append(raw[i])
            i += 1
    return bytes(out)


def _ttlv_build_packet(cmd: int, payload: bytes = b"", packet_id: int = 1) -> bytes:
    inner = struct.pack(">HH", packet_id, cmd) + payload
    crc = _ttlv_crc(inner)
    length = len(inner) + 1
    return _ttlv_byte_stuff(
        b"\xaa\xaa" + struct.pack(">H", length) + bytes([crc]) + inner
    )


def _ttlv_build_bytes_field(tag_id: int, data: bytes) -> bytes:
    tag_word = ((tag_id << 3) & 0xFFF8) | 3
    return struct.pack(">H", tag_word) + struct.pack(">H", len(data)) + data


def _ttlv_parse_packet(data: bytes) -> dict:
    data = _ttlv_byte_unstuff(data)
    if len(data) < 9 or data[0] != 0xAA or data[1] != 0xAA:
        return {"error": "bad packet", "raw": data.hex()}
    pkt_len = struct.unpack(">H", data[2:4])[0]
    pid = struct.unpack(">H", data[5:7])[0]
    cmd = struct.unpack(">H", data[7:9])[0]
    payload = data[9:4 + pkt_len] if len(data) >= 4 + pkt_len else data[9:]
    return {"cmd": cmd, "packet_id": pid, "payload": payload}


def _ttlv_parse_fields(payload: bytes) -> list:
    """Parse TTLV fields from decrypted payload. Returns list of (id, type, value)."""
    fields = []
    i = 0
    while i < len(payload) - 1:
        tag_word = struct.unpack(">H", payload[i:i + 2])[0]
        tag_id = (tag_word >> 3) & 0x1FFF
        tag_type = tag_word & 0x07
        i += 2

        if tag_type in (0, 1):  # Boolean
            fields.append((tag_id, "BOOL", tag_type == 1))
        elif tag_type == 2:  # Number
            if i >= len(payload):
                break
            meta = payload[i]
            i += 1
            sign = (meta >> 7) & 1
            decimals = (meta >> 3) & 0x0F
            byte_count = (meta & 0x07) + 1
            if i + byte_count > len(payload):
                break
            val = int.from_bytes(payload[i:i + byte_count], "big")
            i += byte_count
            if sign:
                val = -val
            if decimals > 0:
                val = val / (10 ** decimals)
            fields.append((tag_id, "NUM", val))
        elif tag_type in (3, 5):  # Bytes
            if i + 2 > len(payload):
                break
            dlen = struct.unpack(">H", payload[i:i + 2])[0]
            i += 2
            fields.append((tag_id, "BYTES", payload[i:i + dlen]))
            i += dlen
        elif tag_type == 4:  # Struct/Array header
            if i + 2 > len(payload):
                break
            count = struct.unpack(">H", payload[i:i + 2])[0]
            i += 2
            fields.append((tag_id, "STRUCT", count))
        else:
            break

    return fields


# ===========================================================================
# TSL ID → kv dict translation
# Maps local TTLV numeric IDs back to the same nested dict keys that the
# cloud MQTT path uses, so _process_data() works unchanged.
# ===========================================================================

# Top-level property ID → TSL code
TSL_TOP = {
    1: "battery_percentage",
    2: "remain_time",
    3: "remain_charging_time",
    4: "total_input_power",
    5: "total_output_power",
    27: "ups_status_hm",
    28: "dc_data_input_hm",
    29: "ac_data_input_hm",
    30: "dc_data_output_hm",
    31: "ac_data_output_hm",
    32: "ac_output_voltage_io",
    33: "ac_output_frequency_io",
    34: "noastime_io",
    35: "host_packet_data_jdb",
    36: "charging_pack_data_jdb",
    37: "device_status_hm",
    38: "dc_switch_hm",
    39: "add_bat_status_hm",
    40: "ac_switch_hm",
    43: "auto_light_flag_as",
    45: "machine_screen_light_as",
    47: "battery_temp",  # E3800 temperature sensors
    48: "charging_plate_temp",
    49: "inverter_temp",
    52: "device_manual",
    100: "high_frequency_reporting",
}

# Struct sub-field mappings: parent_code → {sub_id: sub_code}
TSL_STRUCT = {
    "host_packet_data_jdb": {
        1: "host_packet_electric_percentage",
        2: "host_packet_voltage",
        3: "host_packet_current",
        4: "host_packet_temp",
        5: "host_packet_status",
    },
    "ac_data_output_hm": {
        1: "ac_output_hz",
        2: "ac_output_voltage",
        3: "ac_output_pf",
        4: "ac_output_power",
    },
    "dc_data_output_hm": {
        1: "dc_output_power",
    },
    "ac_data_input_hm": {
        1: "ac_power",
    },
    "dc_data_input_hm": {
        1: "dc_input_power",
    },
    "charging_pack_data_jdb": {
        # Array element struct fields
        1: "charging_pack_num",
        2: "charging_pack_battery",
        3: "charging_pack_voltage",
        4: "charging_pack_current",
        5: "charging_pack_temp",
        6: "charging_pack_status",
    },
}

# SENSOR_FIELDS expects these nested paths for the cloud MQTT format:
#   battery_percent → ("host_packet_data_jdb", "host_packet_electric_percentage")
#   voltage → ("host_packet_data_jdb", "host_packet_voltage")
# etc. So we rebuild that same nested dict structure.


def _fields_to_kv(fields: list) -> dict:
    """Convert parsed TTLV fields into the nested kv dict matching MQTT format."""
    kv = {}
    i = 0
    while i < len(fields):
        fid, ftype, fval = fields[i]
        code = TSL_TOP.get(fid)

        if code is None:
            i += 1
            continue

        if ftype == "STRUCT":
            # fval is the count of sub-fields
            sub_map = TSL_STRUCT.get(code, {})
            sub_dict = {}
            count = fval
            j = i + 1
            consumed = 0
            while j < len(fields) and consumed < count:
                sid, stype, sval = fields[j]
                sub_code = sub_map.get(sid, f"field_{sid}")
                if stype == "STRUCT":
                    # Nested struct (e.g., array elements in charging_pack)
                    # For arrays, collect into a list
                    if code == "charging_pack_data_jdb":
                        # Array of pack structs
                        packs = kv.get(code, [])
                        pack = {}
                        elem_count = sval
                        k = j + 1
                        ec = 0
                        while k < len(fields) and ec < elem_count:
                            eid, etype, eval_ = fields[k]
                            elem_code = sub_map.get(eid, f"field_{eid}")
                            if etype not in ("STRUCT",):
                                pack[elem_code] = eval_
                                ec += 1
                            k += 1
                        packs.append(pack)
                        kv[code] = packs
                        j = k
                        consumed += 1
                        continue
                    j += 1
                    consumed += 1
                    continue
                sub_dict[sub_code] = sval
                j += 1
                consumed += 1
            kv[code] = sub_dict
            i = j
        elif ftype == "BOOL":
            kv[code] = fval
        elif ftype == "NUM":
            kv[code] = fval
        elif ftype == "BYTES":
            try:
                kv[code] = fval.decode("utf-8")
            except Exception:
                kv[code] = fval.hex()
        else:
            kv[code] = fval

        i += 1

    return kv


# ===========================================================================
# LocalTransport
# ===========================================================================

class LocalTransport:
    """TCP transport for Pecron devices on LAN (port 6607)."""

    def __init__(self, device_ip: str, auth_key_b64: str, timeout: float = 10.0):
        self.device_ip = device_ip
        self.device_port = 6607
        self.auth_key = base64.b64decode(auth_key_b64)
        self.auth_key_b64 = auth_key_b64
        self.timeout = timeout

        self._sock = None
        self._iv = None  # Set after handshake
        self._encrypted = False
        self._packet_id = 0
        self._lock = threading.Lock()
        self._connected = False
        self._has_connected_once = False

    @property
    def connected(self) -> bool:
        return self._connected and self._encrypted

    def _next_pid(self) -> int:
        self._packet_id = (self._packet_id + 1) % 65535
        return self._packet_id

    def connect(self) -> bool:
        """Perform TCP connect + WiFi handshake (random exchange + login)."""
        try:
            self.disconnect()
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.device_ip, self.device_port))
            self._connected = True
            if not self._has_connected_once:
                log.info("Local TCP connected to %s:%d", self.device_ip, self.device_port)
            else:
                log.debug("Local TCP reconnected to %s:%d", self.device_ip, self.device_port)

            # Step 1: Request random (IV)
            pkt = _ttlv_build_packet(0x7032, b"", self._next_pid())
            self._sock.sendall(pkt)

            resp = self._recv_packet()
            parsed = _ttlv_parse_packet(resp)
            if parsed.get("cmd") != 0x7033:
                log.error("Expected cmd 0x7033, got 0x%04x", parsed.get("cmd", 0))
                self.disconnect()
                return False

            # Extract random string from TTLV field id=1
            fields = _ttlv_parse_fields(parsed["payload"])
            random_str = None
            for fid, ftype, fval in fields:
                if fid == 1 and isinstance(fval, bytes):
                    random_str = fval.decode("utf-8")
                    break
            if not random_str:
                log.error("No random/IV in 0x7033 response")
                self.disconnect()
                return False

            log.debug("Got random/IV: %s", random_str)

            # Step 2: Login with SHA-256 hash
            auth_hex = self.auth_key.hex()
            login_hash = hashlib.sha256(
                f"{auth_hex};{random_str}".encode("utf-8")
            ).hexdigest()
            login_payload = _ttlv_build_bytes_field(2, login_hash.encode("utf-8"))
            pkt = _ttlv_build_packet(0x7034, login_payload, self._next_pid())
            self._sock.sendall(pkt)

            resp = self._recv_packet()
            parsed = _ttlv_parse_packet(resp)
            if parsed.get("cmd") != 0x7035:
                log.error("Login failed — expected 0x7035, got 0x%04x", parsed.get("cmd", 0))
                self.disconnect()
                return False

            # Check login result (field id=3, value=0 means success)
            fields = _ttlv_parse_fields(parsed["payload"])
            for fid, ftype, fval in fields:
                if ftype == "NUM" and fval != 0:
                    log.error("Login rejected (result=%s)", fval)
                    self.disconnect()
                    return False

            # Set up encryption
            iv_bytes = random_str.encode("utf-8")
            if len(iv_bytes) < 16:
                iv_bytes = iv_bytes.ljust(16, b"\x00")
            elif len(iv_bytes) > 16:
                iv_bytes = iv_bytes[:16]
            self._iv = iv_bytes
            self._encrypted = True
            if not self._has_connected_once:
                log.info("Local TCP handshake complete — encryption active")
                self._has_connected_once = True
            else:
                log.debug("Local TCP handshake complete")
            return True

        except Exception as e:
            log.error("Local connect failed: %s", e)
            self.disconnect()
            return False

    def disconnect(self):
        self._connected = False
        self._encrypted = False
        self._iv = None
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _recv_packet(self) -> bytes:
        """Read one TTLV packet from socket."""
        buf = b""
        # Sync to 0xAA 0xAA
        while True:
            b = self._sock.recv(1)
            if not b:
                raise ConnectionError("Connection closed")
            buf += b
            if len(buf) >= 2 and buf[-2:] == b"\xaa\xaa":
                buf = b"\xaa\xaa"
                break
            if len(buf) > 200:
                raise ValueError("No sync found")

        # Read length (2 bytes) — careful with byte stuffing
        len_raw = b""
        while len(len_raw) < 2:
            b = self._sock.recv(1)
            if not b:
                raise ConnectionError("Connection closed")
            buf += b
            if buf[-2] == 0xAA and b[0] == 0x55:
                continue
            len_raw += b

        pkt_len = struct.unpack(">H", len_raw)[0]
        remaining = pkt_len
        while remaining > 0:
            chunk = self._sock.recv(min(remaining, 4096))
            if not chunk:
                raise ConnectionError("Connection closed")
            buf += chunk
            remaining -= len(chunk)

        return buf

    def _decrypt(self, data: bytes) -> bytes:
        cipher = AES.new(self.auth_key, AES.MODE_CBC, self._iv)
        return unpad(cipher.decrypt(data), 16)

    def _encrypt(self, data: bytes) -> bytes:
        cipher = AES.new(self.auth_key, AES.MODE_CBC, self._iv)
        return cipher.encrypt(pad(data, 16))

    def read_status(self) -> dict:
        """Send read command and return kv dict matching MQTT format."""
        if not self.connected:
            return {}

        with self._lock:
            try:
                # Send cmd 0x0011 (read)
                pkt = _ttlv_build_packet(0x0011, b"", self._next_pid())
                self._sock.sendall(pkt)

                # Read ACK (0x0012) — typically empty encrypted payload
                resp = self._recv_packet()
                parsed = _ttlv_parse_packet(resp)

                # Read the actual data response (0x0014)
                resp2 = self._recv_packet()
                parsed2 = _ttlv_parse_packet(resp2)

                payload = parsed2.get("payload", b"")
                if not payload:
                    # Maybe the first response was the data
                    payload = parsed.get("payload", b"")

                if not payload:
                    log.warning("No payload in local read response")
                    return {}

                decrypted = self._decrypt(payload)
                fields = _ttlv_parse_fields(decrypted)
                kv = _fields_to_kv(fields)
                return kv

            except Exception as e:
                log.debug("Local read ended: %s", e)
                self._connected = False
                return {}

    def send_control(self, data_point_id: int, value, ctrl_type: str = "BOOL") -> bool:
        """Send a control command over local TCP."""
        if not self.connected:
            return False

        with self._lock:
            try:
                ctrl_type = ctrl_type.upper()
                if ctrl_type == "BOOL":
                    tag = (data_point_id << 3) | (1 if value else 0)
                    raw_payload = struct.pack(">H", tag)
                else:
                    tag = (data_point_id << 3) | 2
                    raw_payload = struct.pack(">H", tag) + bytes([int(value)])

                enc_payload = self._encrypt(raw_payload)
                pkt = _ttlv_build_packet(0x0013, enc_payload, self._next_pid())
                self._sock.sendall(pkt)

                resp = self._recv_packet()
                parsed = _ttlv_parse_packet(resp)
                log.info("Local control response: cmd=0x%04x", parsed.get("cmd", 0))
                return True

            except Exception as e:
                log.error("Local control failed: %s", e)
                self._connected = False
                return False


# ===========================================================================
# BLE Transport
# ===========================================================================

try:
    import asyncio
    from bleak import BleakScanner, BleakClient
    HAS_BLE = True
except ImportError:
    HAS_BLE = False

BLE_CHAR_UUID = "00009c40-0000-1000-8000-00805f9b34fb"
BLE_DEVICE_PREFIX = "QUEC_BLE"


class BLETransport:
    """Bluetooth Low Energy transport for Pecron devices.

    Scans for nearby Pecron BLE devices, connects, and performs the same
    TTLV handshake as TCP. No WiFi or internet required.

    Requires: bleak (pip install bleak)
    """

    def __init__(self, auth_key_b64: str, device_address: str = None,
                 device_key: str = None, scan_timeout: float = 10.0):
        """
        Args:
            auth_key_b64: Base64-encoded AES key (from cloud API or config).
            device_address: BLE MAC address (e.g. "68:24:99:E3:FF:AA").
                           If None, scans for a device matching device_key.
            device_key: Device key (e.g. "682499E40D61"). Used to find the
                       device by BLE name (QUEC_BLE_XXXX) if address not given.
            scan_timeout: How long to scan for BLE devices (seconds).
        """
        if not HAS_BLE:
            raise ImportError("bleak is required for BLE transport: pip install bleak")

        self.auth_key = base64.b64decode(auth_key_b64)
        self.auth_key_b64 = auth_key_b64
        self.device_address = device_address
        self.device_key = device_key
        self.scan_timeout = scan_timeout

        # BLE name suffix is last 4 chars of device key
        self._ble_suffix = device_key[-4:].upper() if device_key else None

        self._client = None
        self._iv = None
        self._encrypted = False
        self._packet_id = 0
        self._lock = threading.Lock()
        self._connected = False

        # Async notification handling
        self._rx_buf = bytearray()
        self._rx_packets = []
        self._rx_event = None  # Set in async context

    @property
    def connected(self) -> bool:
        return self._connected and self._encrypted

    def _next_pid(self) -> int:
        self._packet_id = (self._packet_id + 1) % 65535
        return self._packet_id

    def _on_notify(self, sender, data: bytearray):
        """BLE notification callback — reassemble TTLV packets from fragments."""
        self._rx_buf.extend(data)
        while len(self._rx_buf) >= 9:
            # Find sync
            idx = -1
            for j in range(len(self._rx_buf) - 1):
                if self._rx_buf[j] == 0xAA and self._rx_buf[j + 1] == 0xAA:
                    idx = j
                    break
            if idx < 0:
                break
            if idx > 0:
                del self._rx_buf[:idx]
            us = _ttlv_byte_unstuff(bytes(self._rx_buf))
            if len(us) < 4:
                break
            pkt_len = struct.unpack(">H", us[2:4])[0]
            total = 4 + pkt_len
            if len(us) < total:
                break
            pkt = us[:total]
            rs = _ttlv_byte_stuff(pkt)
            del self._rx_buf[:len(rs)]
            self._rx_packets.append(pkt)
            if self._rx_event:
                self._rx_event.set()

    async def _wait_packet(self, timeout: float = 5.0) -> bytes:
        """Wait for a complete reassembled packet."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self._rx_packets:
                return self._rx_packets.pop(0)
            self._rx_event = asyncio.Event()
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(self._rx_event.wait(), min(remaining, 1.0))
            except asyncio.TimeoutError:
                pass
        return self._rx_packets.pop(0) if self._rx_packets else None

    async def _async_connect(self) -> bool:
        """Async BLE connect + handshake."""
        # Scan for the device
        target = None
        stop_event = asyncio.Event()

        def on_detect(device, adv_data):
            nonlocal target
            if self.device_address and device.address == self.device_address:
                target = device
                stop_event.set()
            elif self._ble_suffix and device.name and device.name.endswith(self._ble_suffix):
                target = device
                self.device_address = device.address
                stop_event.set()

        log.info("BLE scanning for Pecron device...")
        scanner = BleakScanner(detection_callback=on_detect)
        await scanner.start()
        try:
            await asyncio.wait_for(stop_event.wait(), self.scan_timeout)
        except asyncio.TimeoutError:
            await scanner.stop()
            log.warning("BLE scan timeout — device not found")
            return False

        log.info("BLE found %s @ %s", target.name, target.address)

        # Connect while scanner is still active (keeps BlueZ cache warm)
        self._client = BleakClient(target, timeout=15.0)
        try:
            await self._client.connect()
        except Exception as e:
            log.error("BLE connect failed: %s", e)
            await scanner.stop()
            return False
        await scanner.stop()

        self._connected = True
        log.info("BLE connected (MTU=%s)", self._client.mtu_size)

        # Subscribe to notifications
        self._rx_buf.clear()
        self._rx_packets.clear()
        await self._client.start_notify(BLE_CHAR_UUID, self._on_notify)
        await asyncio.sleep(0.3)

        # Handshake: request random
        pkt = _ttlv_build_packet(0x7032, b"", self._next_pid())
        await self._client.write_gatt_char(BLE_CHAR_UUID, pkt, response=True)

        resp = await self._wait_packet(5.0)
        if not resp:
            log.error("BLE: no response to random request")
            await self._disconnect_async()
            return False

        parsed = _ttlv_parse_packet(resp)
        if parsed.get("cmd") != 0x7033:
            log.error("BLE: expected 0x7033, got 0x%04x", parsed.get("cmd", 0))
            await self._disconnect_async()
            return False

        fields = _ttlv_parse_fields(parsed["payload"])
        random_str = None
        for fid, ftype, fval in fields:
            if fid == 1 and isinstance(fval, bytes):
                random_str = fval.decode("utf-8")
        if not random_str:
            log.error("BLE: no random/IV in response")
            await self._disconnect_async()
            return False

        log.debug("BLE IV: %s", random_str)

        # Login
        auth_hex = self.auth_key.hex()
        login_hash = hashlib.sha256(
            f"{auth_hex};{random_str}".encode("utf-8")
        ).hexdigest()
        login_payload = _ttlv_build_bytes_field(2, login_hash.encode("utf-8"))
        pkt = _ttlv_build_packet(0x7034, login_payload, self._next_pid())
        await self._client.write_gatt_char(BLE_CHAR_UUID, pkt, response=True)

        resp = await self._wait_packet(5.0)
        if not resp:
            log.error("BLE: no login response")
            await self._disconnect_async()
            return False

        parsed = _ttlv_parse_packet(resp)
        if parsed.get("cmd") != 0x7035:
            log.error("BLE login failed")
            await self._disconnect_async()
            return False

        # Set up encryption
        iv_bytes = random_str.encode("utf-8")
        if len(iv_bytes) < 16:
            iv_bytes = iv_bytes.ljust(16, b"\x00")
        elif len(iv_bytes) > 16:
            iv_bytes = iv_bytes[:16]
        self._iv = iv_bytes
        self._encrypted = True
        log.info("BLE handshake complete — encryption active")
        return True

    async def _disconnect_async(self):
        if self._client:
            try:
                await self._client.stop_notify(BLE_CHAR_UUID)
            except Exception:
                pass
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._connected = False
        self._encrypted = False
        self._iv = None

    def connect(self) -> bool:
        """Connect to the Pecron device over BLE (synchronous wrapper)."""
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(self._async_connect())
            # Keep the loop for later use
            self._loop = loop
            return result
        except Exception as e:
            log.error("BLE connect error: %s", e)
            return False

    def disconnect(self):
        """Disconnect from BLE device."""
        if hasattr(self, '_loop') and self._loop:
            try:
                self._loop.run_until_complete(self._disconnect_async())
                self._loop.close()
            except Exception:
                pass
        self._connected = False
        self._encrypted = False

    async def _async_read_status(self) -> dict:
        """Read status over BLE (async)."""
        self._rx_packets.clear()
        self._rx_buf.clear()

        pkt = _ttlv_build_packet(0x0011, b"", self._next_pid())
        await self._client.write_gatt_char(BLE_CHAR_UUID, pkt, response=True)

        # BLE is slower — wait for fragments to arrive
        await asyncio.sleep(4)

        # Process packets
        for pkt_data in self._rx_packets:
            parsed = _ttlv_parse_packet(pkt_data)
            payload = parsed.get("payload", b"")
            if not payload or parsed.get("cmd") == 0x0012:
                continue  # Skip ACK
            try:
                cipher = AES.new(self.auth_key, AES.MODE_CBC, self._iv)
                decrypted = unpad(cipher.decrypt(payload), 16)
                fields = _ttlv_parse_fields(decrypted)
                return _fields_to_kv(fields)
            except Exception as e:
                log.error("BLE decrypt failed: %s", e)

        self._rx_packets.clear()
        return {}

    def read_status(self) -> dict:
        """Read device status over BLE (synchronous wrapper)."""
        if not self.connected:
            return {}
        with self._lock:
            try:
                return self._loop.run_until_complete(self._async_read_status())
            except Exception as e:
                log.error("BLE read failed: %s", e)
                self._connected = False
                return {}

    def send_control(self, data_point_id: int, value, ctrl_type: str = "BOOL") -> bool:
        """Send a control command over BLE."""
        if not self.connected:
            return False
        with self._lock:
            try:
                ctrl_type = ctrl_type.upper()
                if ctrl_type == "BOOL":
                    tag = (data_point_id << 3) | (1 if value else 0)
                    raw_payload = struct.pack(">H", tag)
                else:
                    tag = (data_point_id << 3) | 2
                    raw_payload = struct.pack(">H", tag) + bytes([int(value)])

                enc_payload = AES.new(self.auth_key, AES.MODE_CBC, self._iv).encrypt(
                    pad(raw_payload, 16)
                )
                pkt = _ttlv_build_packet(0x0013, enc_payload, self._next_pid())

                async def _write():
                    await self._client.write_gatt_char(BLE_CHAR_UUID, pkt, response=True)
                    await asyncio.sleep(1)

                self._loop.run_until_complete(_write())
                return True
            except Exception as e:
                log.error("BLE control failed: %s", e)
                self._connected = False
                return False


def scan_ble_devices(timeout: float = 10.0) -> list:
    """Scan for nearby Pecron BLE devices. Returns list of (address, name) tuples."""
    if not HAS_BLE:
        return []
    results = []

    async def _scan():
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
        for addr, (dev, adv) in devices.items():
            if dev.name and dev.name.startswith(BLE_DEVICE_PREFIX):
                results.append((dev.address, dev.name))
        return results

    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_scan())
        loop.close()
    except Exception as e:
        log.debug("BLE scan failed: %s", e)
    return results


def get_auth_key(token: str, region: dict, pk: str, dk: str) -> str:
    """Fetch the device authKey from Quectel cloud (one-time, can be cached).
    
    Tries read-only getAuthKey first, then regenerateAuthKey as fallback.
    Some device models/accounts only support one or the other.
    """
    import urllib.parse
    import urllib.request
    import json

    last_error = None
    for endpoint in ["getAuthKey", "regenerateAuthKey"]:
        url = region["base_url"] + f"/v2/binding/enduserapi/{endpoint}"
        data = urllib.parse.urlencode({"pk": pk, "dk": dk}).encode()
        req = urllib.request.Request(url, data=data)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Authorization", token)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read())
            if body.get("code") == 200:
                log.debug("Got authKey via %s", endpoint)
                return body["data"]["authKey"]
            last_error = body.get("msg", body)
            log.debug("%s failed: %s", endpoint, last_error)
        except Exception as e:
            last_error = str(e)
            log.debug("%s request failed: %s", endpoint, e)
    raise RuntimeError(f"Failed to get authKey: {last_error}")
