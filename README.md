# Orion 2 BMS Data Logging Stack

This project logs live Orion 2 BMS CAN data from a laptop and stores it as time-series data for visualization and monitoring. It supports two backends:

- **InfluxDB 3 + Grafana** — a fully local stack, great for on-site race day monitoring
- **Supabase + custom website** — a cloud-hosted stack, ideal for remote telemetry and custom dashboards

Both paths use the same CAN reading layer. You pick the backend that fits your use case.

This project was done for **Sunstang at Western University**. It was built with help from Cursor, Windsurf, and Claude, alongside good old-fashioned battery team work.

---

## Architecture

### Option A — InfluxDB 3 + Grafana (Local)
```
Orion 2 BMS (CAN) → USB CAN Adapter → Python Logger → InfluxDB 3 Core → Grafana Dashboard
```

### Option B — Supabase + Custom Website (Cloud)
```
Orion 2 BMS (CAN) → USB CAN Adapter → Python Logger → Supabase (PostgreSQL) → Custom Website / Dashboard
```

> **Note:** The Python loggers read CAN frames directly — they do **not** scrape the Orion Utility GUI. There are two InfluxDB loggers: one for raw CAN frames and one for decoded telemetry specific to the included dashboard JSON files. The raw logger is recommended as it is more flexible. For the Supabase path, there is one logger that decodes the Orion custom telemetry CAN message (`0x6B0`) before uploading.

---

## Requirements

### Hardware
- Orion 2 BMS on a CAN bus
- USB CAN adapter connected to your laptop
  - This setup assumes an adapter readable by `python-can` (SLCAN/serial style). This project used the CANdapter included with the Orion 2 BMS.
- Laptop with USB 3.0 port running Windows 10/11 (USB-C with an adapter is not ideal)

### Software (both paths)
- Python 3.10+ (3.13 works)

### Additional — InfluxDB + Grafana path
- InfluxDB 3 Core (Windows binary)
- Grafana (Windows installer)

### Additional — Supabase path
- A Supabase project (free tier works)
- Your project URL and `anon` API key from the Supabase dashboard

---

## Repo Layout

```
.
├── scripts/
│   ├── canAdapterToInfluxDB.py              # Logs raw CAN frames → InfluxDB
│   ├── canAdapterToInfluxDB_decoding.py     # Logs decoded CAN frames → InfluxDB
│   ├── canAdapterToSupabase.py              # Logs decoded CAN frames → Supabase
│   └── simulate_telemetry.py               # Simulates BMS data → Supabase (no hardware needed)
├── dashboards/
│   └── *.json                               # Grafana dashboard exports
├── .env.example
└── README.md
```

---

## Path A — InfluxDB 3 + Grafana (Local Stack)

### 1) Start InfluxDB 3 Core

1. Download and unzip the InfluxDB 3 Core Windows binary (you'll have `influxdb3.exe`)
2. Open PowerShell in that folder and start the server:
   ```powershell
   mkdir .\data -Force
   .\influxdb3.exe serve --object-store file --data-dir ".\data" --node-id local01
   ```
   Leave this window running.

3. In a **second** PowerShell window in the same folder, create an admin token (save it somewhere safe):
   ```powershell
   .\influxdb3.exe create token --admin
   ```

4. Set your token for this session:
   ```powershell
   $env:INFLUXDB3_AUTH_TOKEN="apiv3_PASTE_TOKEN_HERE"
   ```

5. Create a database (e.g. `sunstang`):
   ```powershell
   .\influxdb3.exe create database sunstang --token $env:INFLUXDB3_AUTH_TOKEN
   ```

---

### 2) Set Up Grafana

1. Install Grafana for Windows and start it:
   ```powershell
   Start-Service grafana
   ```

2. Open [http://localhost:3000](http://localhost:3000)
   - Login: `admin` / `admin` (then set a new password)

---

### 3) Connect Grafana → InfluxDB

In Grafana: **Connections → Data Sources → Add Data Source → InfluxDB**

Set:
- **URL**: `http://127.0.0.1:8181`
- **Query language**: InfluxQL (or SQL if your panels use SQL)
- **Database**: `sunstang`
- **Auth header**: `Authorization: Bearer apiv3_...`

Click **Save & Test**.

---

### 4) Python Logger Setup (InfluxDB)

1. Navigate to your repo folder:
   ```powershell
   cd "D:\PATH\TO\YOUR\REPO"
   ```

2. Create a virtual environment and install dependencies:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install python-can pyserial influxdb3-python
   ```

3. Confirm your CAN adapter's COM port:
   ```powershell
   .\.venv\Scripts\python.exe -m serial.tools.list_ports
   ```
   Note the `COM#` (e.g. `COM7`).

4. Set your InfluxDB token in this session:
   ```powershell
   $env:INFLUXDB3_AUTH_TOKEN="apiv3_PASTE_TOKEN_HERE"
   ```

---

### 5) Run the Logger (Raw CAN)

> **Important:** Close the Orion Utility before running — most adapters can only be opened by one program at a time.

```powershell
.\.venv\Scripts\python.exe .\scripts\canAdapterToInfluxDB.py
```

You should see periodic flush/write messages. Let it run for 10–30 seconds.

---

### 6) Verify Data in InfluxDB

From the InfluxDB folder:
```powershell
$env:INFLUXDB3_AUTH_TOKEN="apiv3_PASTE_TOKEN_HERE"
.\influxdb3.exe query --database sunstang --token $env:INFLUXDB3_AUTH_TOKEN "SELECT time, car_id, arb_id, dlc, data_hex FROM bms_can_raw ORDER BY time DESC LIMIT 10"
```

---

### 7) Import the Grafana Dashboard

In Grafana: **Dashboards → New → Import**

Upload the JSON file from the `dashboards/` folder and select your InfluxDB data source when prompted.

---

## Path B — Supabase + Custom Website (Cloud Stack)

### 1) Create a Supabase Project

1. Go to [https://supabase.com](https://supabase.com) and create a free account and new project.
2. From **Project Settings → API**, copy:
   - **Project URL** (e.g. `https://xyzxyz.supabase.co`)
   - **anon / public** API key

---

### 2) Create the Database Table

In the Supabase dashboard, open the **SQL Editor** and run:

```sql
CREATE TABLE bms_telemetry (
  id           BIGSERIAL PRIMARY KEY,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  pack_voltage NUMERIC,
  pack_current NUMERIC,
  soc          NUMERIC,
  avg_temp     NUMERIC,
  max_temp     NUMERIC,
  fault_flag   INTEGER
);
```

> You can add or remove columns to match your Orion CAN message layout.

---

### 3) Configure the Logger Script

Open `scripts/canAdapterToSupabase.py` and update the user settings at the top:

```python
COM_PORT       = "COM6"          # Your CAN adapter COM port
SERIAL_BAUD    = 115200
CAN_BITRATE    = 250000

SUPABASE_URL   = "https://YOUR-PROJECT.supabase.co/"
SUPABASE_KEY   = "your-anon-key-here"

TABLE_NAME     = "bms_telemetry"
TELEM_CAN_ID   = 0x6B0           # CAN ID of your Orion telemetry message
```

The script decodes a custom 8-byte Orion telemetry CAN message with this layout:

| Bytes | Field          | Type             | Scaling  |
|-------|----------------|------------------|----------|
| 0–1   | `pack_voltage` | uint16 LE        | ÷ 10 (V) |
| 2–3   | `pack_current` | int16 LE         | ÷ 10 (A) |
| 4     | `soc`          | uint8            | ÷ 2 (%)  |
| 5     | `avg_temp`     | uint8            | 1°C      |
| 6     | `max_temp`     | uint8            | 1°C      |
| 7     | `fault_flag`   | uint8 (bitfield) | —        |

If your CAN message layout differs, update `decode_custom_telem()` accordingly.

---

### 4) Python Logger Setup (Supabase)

1. Navigate to your repo folder:
   ```powershell
   cd "D:\PATH\TO\YOUR\REPO"
   ```

2. Create a virtual environment and install dependencies:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install python-can pyserial supabase
   ```

3. Confirm your CAN adapter COM port:
   ```powershell
   .\.venv\Scripts\python.exe -m serial.tools.list_ports
   ```

---

### 5) Run the Logger (Supabase)

> **Important:** Close the Orion Utility before running.

```powershell
.\.venv\Scripts\python.exe .\scripts\canAdapterToSupabase.py
```

You should see upload confirmations like:
```
[UPLOAD] Sent 10 points. Latest: 48.3V | 12.5A
```

---

### 6) Verify Data in Supabase

In the Supabase dashboard, open **Table Editor → bms_telemetry**. You should see rows appearing with recent timestamps.

You can also verify via the SQL editor:
```sql
SELECT * FROM bms_telemetry ORDER BY created_at DESC LIMIT 10;
```

---

## Simulator — Test Without Hardware

`scripts/simulate_telemetry.py` generates fake but physically plausible BMS data and pushes it to Supabase at 1 Hz. Use it to verify your Supabase connection, table schema, and any downstream website or dashboard — **no CAN adapter or BMS hardware required**.

### Setup

Open `scripts/simulate_telemetry.py` and confirm these match your Supabase project:

```python
SUPABASE_URL        = "https://YOUR-PROJECT.supabase.co/"
SUPABASE_KEY        = "your-anon-key-here"
TABLE_NAME          = "bms_telemetry"
UPDATE_RATE_SECONDS = 1.0     # How often to send a data point
```

Install dependencies (if not already done):
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install supabase
```

### Run the Simulator

```powershell
.\.venv\Scripts\python.exe .\scripts\simulate_telemetry.py
```

You'll see output like:
```
[INFO] Connecting to Supabase...
[INFO] Connected! Starting SIMULATION loop (1Hz)...
[SIM] 49.2V | 34.7A | 88.3% | 32.1C
[SIM] 47.8V | 55.2A | 88.1% | 32.2C
```

Press `Ctrl+C` to stop. Check your Supabase Table Editor to confirm rows are appearing in real time.

### What the Simulator Models

| Field          | Behaviour                                                     |
|----------------|---------------------------------------------------------------|
| `pack_voltage` | 44–52 V nominal, sags under high current, with slight noise   |
| `pack_current` | Random −10 A (regen) to +60 A (acceleration)                 |
| `soc`          | Slowly drains when current is positive; resets to 100% at 0% |
| `avg_temp`     | Slowly rises under load, cools when current is low            |
| `max_temp`     | `avg_temp` + small random offset                              |
| `fault_flag`   | Always `0` — for clean visual testing                        |

---

## CAN Data: Raw vs Decoded

### Raw mode (InfluxDB only)
Stores every frame as-is: `arb_id`, `dlc`, `data_hex`, `is_ext`. Flexible — works with any Orion firmware output. Use `canAdapterToInfluxDB.py`.

### Decoded telemetry mode
Interprets a specific CAN message into named fields (`pack_voltage`, `soc`, etc.). Requires your Orion to emit a telemetry message at the expected CAN ID with the expected byte layout.
- InfluxDB path: `canAdapterToInfluxDB_decoding.py`
- Supabase path: `canAdapterToSupabase.py`

---

## Troubleshooting

### "No module named can" / "No module named supabase"
You installed packages into a different Python environment than the one running your script. Always use the venv Python explicitly:
```powershell
.\.venv\Scripts\python.exe -m pip install python-can supabase pyserial
```

### "could not open port COMx"
- Adapter not plugged in, or wrong COM port
- Another app has the port open (close Orion Utility)
- List available ports:
  ```powershell
  .\.venv\Scripts\python.exe -m serial.tools.list_ports
  ```

### Supabase upload errors
- Double-check `SUPABASE_URL` and `SUPABASE_KEY` in the script
- Make sure the `bms_telemetry` table exists with the correct columns (see SQL above)
- Check that Row Level Security (RLS) allows anonymous inserts, or disable RLS on the table for development

### Grafana shows no data
- Check the Grafana time range (Last 5 / 15 minutes)
- Confirm your InfluxDB query returns recent rows
- Confirm the data source points to the correct URL, database, and token
