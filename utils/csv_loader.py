import csv
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CSV_DIR = os.path.join(BASE_DIR, "data")

def load_photos_csv(group_key):
    path = os.path.join(CSV_DIR, f"{group_key}.csv")
    rows = []

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    return rows
