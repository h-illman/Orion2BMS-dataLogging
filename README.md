# Orion 2 BMS Data Logging Stack

This project allows you to log live Orion 2 BMS CAN data to a laptop, store it as time-series data using InfluxDB, and visualize it with Grafana! Inside is both the script for sending directly from CANbus to Grafana (via wired connection) and the script for sending over WiFi. Note that sending over WiFi takes additional stuff, like a proper telemetry board setup. For the sake of this project, I assume you have that figured out already and can make alterations to the code as needed for your setup. This is the perfect jumping off point for anybody who is trying to make an effective dashboard to monitor everything they'd need to know about a battery pack. This project was done for Sunstang at Western Unviersity and used tools like Cursor and Windsurf alongside some Claude writing, but was also done the good old fashioned way by the battery team.

## Architecture
**Orion 2 BMS (CAN)** → **USB CAN adapter** → **Python logger** → **InfluxDB 3 Core** → **Grafana dashboard**
**Orion 2 BMS (CAN)** → **ESP32 telemetry board** → **WiFi** → **Laptop** → **Python logger** → **InfluxDB 3 Core** → **Grafana dashboard**

> Note: The Python logger reads CAN frames directly. It does **not** scrape the Orion Utility GUI. Furthermore, there are two versopns loggers. One logger allows you to read raw CAN data, and the other allows you to read decoded data specific to the dashboard JSON files. The raw one is the reccomended version, as it allows you to make your own set up work, but if you want to directly copy you can use the other. For the sake of this readme, I will use the raw.

---

## Requirements

### Hardware
- Orion 2 BMS on a CAN bus
- USB CAN adapter connected to your laptop  
  - This setup assumes an adapter that can be read by `python-can` (often SLCAN/serial style). This setup used the CANdapter included with the Orion 2 BMS.
- Laptop with USB 3.0 port running Windows 10/11. As far as I am aware, USB-C would not work and using an adapter is not ideal. 

### Software
- Python 3.10+ (3.13 works)
- InfluxDB 3 Core (Windows binary)
- Grafana (Windows installer)

---

## Repo layout (suggested)
```

.
├─ scripts/
│  ├─ canAdapterToInfluxDB.py            # logs raw CAN frames into InfluxDB
│  ├─ canAdapterToInfluxDB_decoding      # logs decoded CAN frames into InfluxDB
├─ dashboards/
│  └─ sunstang_bms_race_dashboard.json      # Grafana dashboard export
├─ .env.example
└─ README.md

````

---

## Quickstart (Windows)

## 1) InfluxDB 3 Core (local)
1. Download + unzip InfluxDB 3 Core Windows binary (you should have `influxdb3.exe`)
2. Open PowerShell in that folder and start the server:
   ```powershell
   mkdir .\data -Force
   .\influxdb3.exe serve --object-store file --data-dir ".\data" --node-id local01


Leave this window running.

3. In a **second** PowerShell in the same folder, create an admin token (copy it somewhere safe):

   ```powershell
   .\influxdb3.exe create token --admin
   ```

4. Set your token for this PowerShell session:

   ```powershell
   $env:INFLUXDB3_AUTH_TOKEN="apiv3_PASTE_TOKEN_HERE"
   ```

5. Create a database (example: `sunstang`):

   ```powershell
   .\influxdb3.exe create database sunstang --token $env:INFLUXDB3_AUTH_TOKEN
   ```

---

## 2) Grafana (local)

1. Install Grafana (Windows)
2. Start it:

   ```powershell
   Start-Service grafana
   ```
3. Open:

   * [http://localhost:3000](http://localhost:3000)
4. Log in:

   * user: `admin`
   * password: `admin`
     (then set a new password)

---

## 3) Connect Grafana → InfluxDB

In Grafana:

* **Connections → Data sources → Add data source → InfluxDB**
* Set:

  * **URL**: `http://127.0.0.1:8181`
  * **Query language**: InfluxQL (or SQL if your panels use SQL)
  * **Database**: `sunstang`
  * **Auth header**: `Authorization: Bearer apiv3_...`
* Click **Save & Test**

---

## 4) Python logger setup

1. Go to your repo folder:

   ```powershell
   cd "D:\PATH\TO\YOUR\REPO"
   ```

2. Create a venv + install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install python-can pyserial influxdb3-python
   ```

3. Confirm the CAN adapter COM port:

   ```powershell
   .\.venv\Scripts\python.exe -m serial.tools.list_ports
   ```

   Note the `COM#` (ex: `COM7`).

4. Set your Influx token (same PowerShell session you will run the script from):

   ```powershell
   $env:INFLUXDB3_AUTH_TOKEN="apiv3_PASTE_TOKEN_HERE"
   ```

---

## 5) Run the logger (raw CAN frames)

**Important:** Close the Orion Utility while logging (many adapters can be opened by only one program at a time).

Run:

```powershell
.\.venv\Scripts\python.exe .\scripts\canAdapterToInfluxDB.py
```

You should see periodic flush/write prints. Let it run for 10–30 seconds.

---

## 6) Verify data landed in InfluxDB

From the InfluxDB folder:

```powershell
$env:INFLUXDB3_AUTH_TOKEN="apiv3_PASTE_TOKEN_HERE"
.\influxdb3.exe query --database sunstang --token $env:INFLUXDB3_AUTH_TOKEN "SELECT time, car_id, arb_id, dlc, data_hex FROM bms_can_raw ORDER BY time DESC LIMIT 10"
```

---

## 7) Import the dashboard

In Grafana:

* **Dashboards → New → Import**
* Upload the JSON in `dashboards/`
* Select your InfluxDB data source when prompted

---

## Telemetry fields vs raw CAN

### Raw mode (always works if CAN reading works)

Stores every frame as:

* `arb_id`, `dlc`, `data_hex`, `is_ext`

### Decoded telemetry mode (recommended for “pack_voltage”, “avg_temp”, etc.)

You must configure the Orion CAN output so that your logger can decode signals reliably:

* Either emit a single custom telemetry CAN message with a known layout
* Or decode Orion’s default broadcast frames (requires the exact CAN IDs + byte layouts)

---

## Troubleshooting

### “No module named can”

You installed packages in a different Python than the one running your script.
Use the venv python explicitly:

```powershell
.\.venv\Scripts\python.exe -m pip install python-can influxdb3-python pyserial
```

### “could not open port COMx”

* Adapter not plugged in
* Wrong COM port
* Another app has the port open (close Orion Utility / monitors)
* Confirm ports:

  ```powershell
  .\.venv\Scripts\python.exe -m serial.tools.list_ports
  ```

### Grafana shows no data

* Check Grafana time range (Last 5/15 minutes)
* Confirm InfluxDB query returns recent rows
* Confirm Grafana data source points to the right URL + database + token
