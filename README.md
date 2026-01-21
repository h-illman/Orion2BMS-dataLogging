# Orion 2 BMS Telemetry/Data Logging System (CAN → InfluxDB 3 Core → Grafana)

This project logs live Orion 2 BMS CAN data to a laptop, stores it as time-series in InfluxDB 3 Core, and visualizes it in Grafana dashboards. Done for Sunstang Solar Car Project at Western University.

## Architecture
**Orion 2 BMS (CAN)** → **USB CAN adapter** → **Python logger script** → **InfluxDB 3 Core** → **Grafana dashboard**

> Note: The Python logger reads CAN frames directly. It does **not** scrape the Orion Utility GUI. 

---

## Requirements

### Hardware
- Orion 2 BMS on a CAN bus
- USB CAN adapter connected to your laptop  
  - This repo assumes an adapter that can be read by `python-can` (often SLCAN/serial style).  
- Laptop (Windows 10/11 recommended)

### Software
- Python 3.10+ (3.13 works)
- InfluxDB 3 Core (Windows binary)
- Grafana (Windows installer)
