import os
import csv

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CSV_BASE = os.path.join(BASE_DIR, "members_csv")


def get_members(group_key):
    group_dir = os.path.join(CSV_BASE, group_key)
    if not os.path.isdir(group_dir):
        return []

    return sorted([
        os.path.splitext(f)[0]
        for f in os.listdir(group_dir)
        if f.endswith(".csv")
    ])


def get_costumes_for_member(group_key, member):
    path = os.path.join(CSV_BASE, group_key, f"{member}.csv")
    if not os.path.exists(path):
        return []

    costumes = set()
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            costumes.add(row["costume"])

    return sorted(costumes)


def get_photo_types_for_member_and_costume(group_key, member, costume):
    path = os.path.join(CSV_BASE, group_key, f"{member}.csv")
    if not os.path.exists(path):
        return []

    types = set()
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["costume"] == costume:
                types.add(row["type"])

    return sorted(types)
