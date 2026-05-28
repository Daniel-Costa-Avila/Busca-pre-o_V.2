import csv
import json
import os
from datetime import datetime

LOG_DIR = "logs"
CSV_FILE = os.path.join(LOG_DIR, "price_log.csv")
JSON_FILE = os.path.join(LOG_DIR, "price_log.json")

def init_logs():
    os.makedirs(LOG_DIR, exist_ok=True)

    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "produto", "canal", "url",
                "avista", "pix", "prazo",
                "status", "confiabilidade"
            ])

    if not os.path.exists(JSON_FILE):
        with open(JSON_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)


def log_price(data):
    data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # CSV
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(data.values())

    # JSON
    with open(JSON_FILE, "r+", encoding="utf-8") as f:
        content = json.load(f)
        content.append(data)
        f.seek(0)
        json.dump(content, f, ensure_ascii=False, indent=2)
