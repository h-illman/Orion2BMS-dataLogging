# ----- Standard library imports (built into Python) -----
import os                  # Lets us read environment variables (e.g., your Influx token)
import time                # Provides timestamps and delays
import struct              # Helps unpack bytes into integers/floats in a reliable way

# ----- Third-party library imports (you install these with pip) -----
import can                 # python-can library for reading CAN messages from an adapter
from influxdb_client_3 import InfluxDBClient3  # InfluxDB 3 Core Python client for writing data


# ================== USER SETTINGS ==================

# Your CANdapter shows up as a COM port in Windows Device Manager (ex: COM7).
COM_PORT = "COM6"

# Many SLCAN/Lawicel-style adapters use 115200 baud for the serial link to the PC.
# Note: This is NOT the CAN bus bitrate; it's the serial connection speed to the adapter.
SERIAL_BAUD = 115200

# CAN bus bitrate. Orion is commonly 500 kbit/s, but use whatever your bus is set to.
CAN_BITRATE = 500000

# InfluxDB 3 Core address. If InfluxDB is running on the same laptop, localhost is correct.
INFLUX_HOST = "http://127.0.0.1:8181"

# InfluxDB database name you created earlier.
INFLUX_DB = "sunstang"

# Token used to authenticate writes to InfluxDB.
# We read it from an environment variable so you don’t hardcode it into a file.
INFLUX_TOKEN = os.getenv("INFLUXDB3_AUTH_TOKEN", "").strip()

# Tags help you filter data later (ex: multiple cars / test sessions).
CAR_ID = "sunstang24"

# If True, we store every CAN frame as raw hex in Influx (good for debugging the pipeline).
WRITE_RAW_FRAMES = True

# OPTIONAL: If you make ONE custom Orion telemetry message that contains pack voltage/current/etc,
# you can enable decoding by turning this on and setting TELEM_CAN_ID to match your message.
# === Decoding mode ===
# This script can log:
#   1) RAW CAN frames -> measurement: bms_can_raw
#   2) DECODED telemetry -> measurement: bms_telemetry  (for your Race Dashboard)
#
# To produce decoded telemetry, the Orion 2 must transmit a custom CAN message that packs:
#   pack_voltage, pack_current, soc, avg_temp, max_temp, fault_flag
# into a single 8-byte frame. See decode_custom_telem() below for the exact byte layout.
#
# Set ORION_TELEM_CAN_ID (e.g., 0x6B0) and (optionally) ORION_TELEM_IS_EXT=1 in your .env.
ENABLE_TELEM_DECODE = True  # Leave True; if no telemetry frames are present, only raw frames are logged.

# Custom telemetry CAN ID (11-bit by default). You can override via env var ORION_TELEM_CAN_ID.
TELEM_CAN_ID = int(os.getenv("ORION_TELEM_CAN_ID", "0x6B0"), 0)

# Whether that telemetry frame uses an extended (29-bit) ID. Override via ORION_TELEM_IS_EXT=1.
TELEM_EXTENDED_ID = os.getenv("ORION_TELEM_IS_EXT", "0") in ("1", "true", "True", "yes", "YES")


# Measurement names (like tables). Grafana will query these.
RAW_MEASUREMENT = "bms_can_raw"       # Stores raw CAN frames
TELEM_MEASUREMENT = "bms_telemetry"   # Stores decoded telemetry fields

# Write batching settings to avoid writing one point at a time (faster + less overhead).
BATCH_SIZE = 200          # How many points we buffer before writing
FLUSH_INTERVAL_S = 1.0    # Max time we wait before forcing a write


# ======================================================


def now_ns() -> int:
    """
    Returns current time in nanoseconds.
    InfluxDB 3 Core supports nanosecond timestamps.
    """
    return time.time_ns()


def decode_custom_telem(payload: bytes) -> dict:
    """
    Decode your single custom telemetry CAN message (optional).

    Expected 8-byte payload layout (you must configure Orion to transmit this layout):
      bytes 0-1: pack_voltage (uint16 little-endian) in 0.1 V  -> value/10
      bytes 2-3: pack_current (int16  little-endian) in 0.1 A  -> value/10
      byte 4:    soc (uint8) in 0.5 %                          -> value/2
      byte 5:    avg_temp (uint8) degC
      byte 6:    max_temp (uint8) degC
      byte 7:    fault_flag (uint8) (0/1 or bitfield)
    """
    # If the message is shorter than 8 bytes, we cannot decode it reliably.
    if len(payload) < 8:
        return {}

    # Unpack pack voltage (unsigned 16-bit) starting at byte 0 (little endian).
    pv_raw = struct.unpack_from("<H", payload, 0)[0]

    # Unpack pack current (signed 16-bit) starting at byte 2 (little endian).
    pc_raw = struct.unpack_from("<h", payload, 2)[0]

    # Byte 4 is SOC.
    soc_raw = payload[4]

    # Byte 5 is average temperature.
    avg_t = payload[5]

    # Byte 6 is max temperature.
    max_t = payload[6]

    # Byte 7 is fault flag (or bitfield).
    fault = payload[7]

    # Convert to engineering units.
    return {
        "pack_voltage": pv_raw / 10.0,     # 0.1 V resolution
        "pack_current": pc_raw / 10.0,     # 0.1 A resolution
        "soc": soc_raw / 2.0,              # 0.5% resolution
        "avg_temp": float(avg_t),          # degC
        "max_temp": float(max_t),          # degC
        "fault_flag": int(fault),          # int field
    }


def lp_escape_str(s: str) -> str:
    """
    Minimal escaping for Influx line protocol string fields.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')


def to_line_protocol_raw(msg: can.Message, ts_ns: int) -> str:
    """
    Convert a raw CAN frame into InfluxDB line protocol.
    Stores arbitration ID + DLC + extended flag + data payload as hex.

    Example line protocol:
      bms_can_raw,car_id=sunstang24,source=candapter arb_id=123i,is_ext=0i,dlc=8i,data_hex="00112233..." 1234567890
    """
    # Convert message data bytes into a hex string for storage.
    data_hex = msg.data.hex()

    # Construct line protocol string.
    return (
        f"{RAW_MEASUREMENT},car_id={CAR_ID},source=candapter "
        f"arb_id={msg.arbitration_id}i,is_ext={int(msg.is_extended_id)}i,dlc={msg.dlc}i,"
        f"data_hex=\"{lp_escape_str(data_hex)}\" "
        f"{ts_ns}"
    )


def to_line_protocol_telem(fields: dict, ts_ns: int) -> str:
    """
    Convert decoded telemetry fields into InfluxDB line protocol.
    Integers get an 'i' suffix; floats are written as float fields.
    """
    # Build "field=value" parts.
    parts = []
    for k, v in fields.items():
        # Influx line protocol requires integers have trailing 'i'
        if isinstance(v, int):
            parts.append(f"{k}={v}i")
        else:
            parts.append(f"{k}={float(v)}")

    # Also write a human-friendly fault text field for Grafana.
    # (If you later decide to send a bitmask and want names, you can map it here.)
    fault_flag_val = int(fields.get("fault_flag", 0))
    fault_text = "OK" if fault_flag_val == 0 else f"0x{fault_flag_val:02X}"
    parts.append(f'fault_text="{fault_text}"')

    # Combine fields into one comma-separated field set.
    field_str = ",".join(parts)

    # Tags include car_id and source.
    return f"{TELEM_MEASUREMENT},car_id={CAR_ID},source=candapter_decoded {field_str} {ts_ns}"


def main():
    """
    Main program loop:
    - Connect to InfluxDB
    - Connect to CAN adapter
    - Read CAN messages continuously
    - Write raw frames and optionally decoded telemetry into InfluxDB
    """
    # Safety check: token must be present.
    if not INFLUX_TOKEN:
        raise SystemExit("Set INFLUXDB3_AUTH_TOKEN to your apiv3_... token first.")

    # Create a client connection to InfluxDB 3 Core.
    influx = InfluxDBClient3(host=INFLUX_HOST, database=INFLUX_DB, token=INFLUX_TOKEN)

    # python-can expects the SLCAN channel in the format "COMx@baud".
    # This baud is the serial baud, NOT the CAN bitrate.
    channel = f"{COM_PORT}@{SERIAL_BAUD}"

    # Create the CAN bus object. This opens the adapter so we can read frames.
    bus = can.Bus(interface="slcan", channel=channel, bitrate=CAN_BITRATE)

    # Print status so you know it’s connected.
    print(f"[OK] CAN connected: {channel} (CAN bitrate {CAN_BITRATE})")
    print(f"[OK] Influx target: {INFLUX_HOST}  db={INFLUX_DB}")
    print(f"[INFO] RAW logging: {WRITE_RAW_FRAMES}")
    print(f"[INFO] TELEM decode: {ENABLE_TELEM_DECODE} (ID=0x{TELEM_CAN_ID:X})")

    # Buffer for batched writes to InfluxDB.
    batch = []

    # Track the last time we flushed a batch.
    last_flush = time.time()

    # Track how many points we’ve written (just for feedback).
    total = 0

    # Loop forever, reading CAN frames.
    while True:
        # Receive one CAN message (blocking up to timeout seconds).
        msg = bus.recv(timeout=1.0)

        # If no message arrives, periodically flush any buffered data.
        if msg is None:
            if batch and (time.time() - last_flush) >= FLUSH_INTERVAL_S:
                influx.write(record=batch, write_precision="ns")  # Write buffered points
                total += len(batch)                              # Update total count
                print(f"[FLUSH] wrote {len(batch)} points (total={total})")
                batch.clear()                                    # Clear buffer after write
                last_flush = time.time()                         # Reset flush timer
            continue

        # Timestamp this message (in ns).
        ts_ns = now_ns()

        # Write raw frame to InfluxDB (debug-friendly).
        if WRITE_RAW_FRAMES:
            batch.append(to_line_protocol_raw(msg, ts_ns))

        # Optionally decode a custom telemetry CAN message.
        if ENABLE_TELEM_DECODE:
            # Check if this frame matches the telemetry message ID and frame type.
            if msg.arbitration_id == TELEM_CAN_ID and bool(msg.is_extended_id) == bool(TELEM_EXTENDED_ID):
                fields = decode_custom_telem(msg.data)  # Decode bytes to real units
                if fields:
                    batch.append(to_line_protocol_telem(fields, ts_ns))  # Add telemetry point to batch
                    print(f"[TELEM] V={fields.get('pack_voltage',0):.1f}V  SOC={fields.get('soc',0):.1f}%")

        # Flush if we hit batch size or if enough time has passed.
        if len(batch) >= BATCH_SIZE or (time.time() - last_flush) >= FLUSH_INTERVAL_S:
            influx.write(record=batch, write_precision="ns")  # Write points in batch to InfluxDB
            total += len(batch)                               # Count points written
            print(f"[FLUSH] wrote {len(batch)} points (total={total})")
            batch.clear()                                     # Reset buffer
            last_flush = time.time()                          # Reset flush timer


# Standard Python entry point guard.
# This ensures main() only runs when you execute this file directly.
if __name__ == "__main__":
    main()