import os
import csv
import time
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

DATABASE_URL = "postgresql://spcolle_syjy_default:zEEdb8WBBcYTk1E1uwoTS6P42tDoCLy5@dpg-d7c9b4gsfn5c73cbbtf0-a.oregon-postgres.render.com/spcolle_syjy"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=30
)

BASE_DIR = os.path.join(os.path.dirname(__file__), "members_csv")

BATCH_SIZE = 20
RETRY_COUNT = 5


# -----------------------------
# ユーティリティ
# -----------------------------
def safe_str(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def fetch_map(conn, table, key_col="name"):
    result = conn.execute(
        text(f"SELECT id, {key_col} FROM {table}")
    ).mappings()

    return {
        row[key_col]: row["id"]
        for row in result
        if row[key_col] is not None
    }


def execute_with_retry(query, params):
    for attempt in range(RETRY_COUNT):
        try:
            with engine.begin() as conn:
                conn.execute(query, params)
            return
        except OperationalError:
            print(f"      DB retry {attempt + 1}/{RETRY_COUNT}")
            time.sleep(2)

    raise Exception("DB connection failed after retries")


# -----------------------------
# 🔥 追加：メンバー単位スキップ判定
# -----------------------------
def is_member_done(member_id):
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 1 FROM photos
            WHERE member_id = :m
            LIMIT 1
        """), {"m": member_id}).first()

    return result is not None


# -----------------------------
# 初期データ
# -----------------------------
def seed_groups():
    query = text("""
        INSERT INTO groups (key, name)
        VALUES (:key, :name)
        ON CONFLICT (key) DO NOTHING
    """)

    groups = [
        {"key": "hinatazaka", "name": "日向坂46"},
        {"key": "nogizaka", "name": "乃木坂46"},
        {"key": "sakurazaka", "name": "櫻坂46"},
    ]

    for g in groups:
        execute_with_retry(query, g)


def seed_photo_types():
    query = text("""
        INSERT INTO photo_types (name)
        VALUES (:name)
        ON CONFLICT (name) DO NOTHING
    """)

    for t in ["ヨリ", "チュウ", "ヒキ", "座り"]:
        execute_with_retry(query, {"name": t})


# -----------------------------
# members
# -----------------------------
def import_members(group_key):
    with engine.begin() as conn:
        group_id = conn.execute(
            text("SELECT id FROM groups WHERE key=:key"),
            {"key": group_key}
        ).scalar()

    path = os.path.join(BASE_DIR, group_key, "members_master.csv")

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            member = safe_str(row.get("member"))
            if not member:
                continue

            execute_with_retry(text("""
                INSERT INTO members
                (name, group_id, generation, display_order)
                VALUES (:name, :group_id, :gen, :order)
                ON CONFLICT (name, group_id) DO NOTHING
            """), {
                "name": member,
                "group_id": group_id,
                "gen": int(row["generation"]),
                "order": int(row["order"]),
            })


# -----------------------------
# costumes（NULL完全防止）
# -----------------------------
def insert_costumes(group_key):
    with engine.begin() as conn:
        group_id = conn.execute(
            text("SELECT id FROM groups WHERE key=:key"),
            {"key": group_key}
        ).scalar()

    costumes = set()
    group_dir = os.path.join(BASE_DIR, group_key)

    for file in os.listdir(group_dir):
        if not file.endswith(".csv") or file == "members_master.csv":
            continue

        path = os.path.join(group_dir, file)

        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                costume = safe_str(row.get("costume"))
                if costume:
                    costumes.add(costume)

    query = text("""
        INSERT INTO costumes (name, group_id)
        VALUES (:name, :group_id)
        ON CONFLICT (name, group_id) DO NOTHING
    """)

    for costume in costumes:
        execute_with_retry(query, {
            "name": costume,
            "group_id": group_id
        })


# -----------------------------
# 🔥 photos（完全再開対応）
# -----------------------------
def insert_photos(group_key):
    print(f"  → inserting photos ({group_key})")

    with engine.connect() as conn:
        member_map = fetch_map(conn, "members")
        costume_map = fetch_map(conn, "costumes")
        type_map = fetch_map(conn, "photo_types")

    group_dir = os.path.join(BASE_DIR, group_key)

    for file in os.listdir(group_dir):
        if not file.endswith(".csv") or file == "members_master.csv":
            continue

        member_name = safe_str(file.replace(".csv", ""))

        if member_name not in member_map:
            continue

        member_id = member_map[member_name]

        # 🔥 ここが最重要（再開）
        if is_member_done(member_id):
            print(f"    → {file} (skip)")
            continue

        print(f"    → {file}")

        path = os.path.join(group_dir, file)
        batch = []
        total = 0

        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                m = safe_str(row.get("member"))
                c = safe_str(row.get("costume"))
                t = safe_str(row.get("type"))

                if not m or not c or not t:
                    continue

                if m not in member_map:
                    continue
                if c not in costume_map:
                    continue
                if t not in type_map:
                    continue

                batch.append({
                    "m": member_map[m],
                    "c": costume_map[c],
                    "t": type_map[t],
                })

                if len(batch) >= BATCH_SIZE:
                    flush(batch)
                    total += len(batch)
                    print(f"      inserted: {total}")
                    batch.clear()

        if batch:
            flush(batch)
            total += len(batch)
            print(f"      inserted: {total}")

        time.sleep(0.3)


def flush(batch):
    query = text("""
        INSERT INTO photos (member_id, costume_id, type_id)
        VALUES (:m, :c, :t)
        ON CONFLICT (member_id, costume_id, type_id) DO NOTHING
    """)

    execute_with_retry(query, batch)


# -----------------------------
# メイン
# -----------------------------
def main():
    print("Seeding master data...")

    seed_groups()
    seed_photo_types()

    for group_key in ["sakurazaka"]:
        print(f"Processing {group_key}...")

        import_members(group_key)
        insert_costumes(group_key)
        insert_photos(group_key)

    print("Done.")


if __name__ == "__main__":
    main()