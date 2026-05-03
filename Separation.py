import csv
import unicodedata
from collections import defaultdict

from app import app
from extensions import db
from models import UserPhoto, Photo, Member, Costume, PhotoType

CSV_PATH = r"C:\Users\Teikyo\Desktop\my-all-directory\application-directory\sakamichi_photo_app\日向坂 生写真管理 a96ae5d42c2d820fa4380137fd36b89b_all.csv"
TARGET_USER_ID = 1

TYPE_MAPPING = {
    "ヨリ": "ヨリ",
    "チュウ": "チュウ",
    "ヒキ": "ヒキ",
    "座り": "座り",
}


def normalize(text: str) -> str:
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)

    return (
        text.replace(" ", "")
            .replace("　", "")
            .replace("「", "")
            .replace("」", "")
            .replace("（", "(")
            .replace("）", ")")
            .replace("・", "")
            .replace("-", "")
            .replace("ー", "")
            .replace("'", "")
            .lower()
    )


def find_costume(member, costume_name, costume_cache):
    target = normalize(costume_name)

    candidates = costume_cache.get(member.group_id, [])

    for c in candidates:
        if normalize(c.name) == target:
            return c

    for c in candidates:
        n = normalize(c.name)
        if target in n or n in target:
            return c

    return None


def main():
    missing_members = set()
    missing_costumes = set()
    missing_types = set()
    missing_photos = []

    # 🔥 ここが重要：集計バッファ
    aggregated = defaultdict(int)

    with app.app_context():

        type_cache = {t.name: t for t in PhotoType.query.all()}

        costume_cache = {}
        for c in Costume.query.all():
            costume_cache.setdefault(c.group_id, []).append(c)

        # ===== CSV読み込み & 集計 =====
        with open(CSV_PATH, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            for row in reader:
                member_name = (row.get("メンバー名前") or "").strip()
                costume_name = (row.get("シリーズ") or "").strip()

                if not member_name or not costume_name:
                    continue

                member = Member.query.filter_by(name=member_name).first()
                if not member:
                    missing_members.add(member_name)
                    continue

                costume = find_costume(member, costume_name, costume_cache)
                if not costume:
                    missing_costumes.add(costume_name)
                    continue

                for csv_col, type_name in TYPE_MAPPING.items():
                    val = row.get(csv_col)
                    if not val or not val.strip().isdigit():
                        continue

                    quantity = int(val.strip())
                    if quantity <= 0:
                        continue

                    photo_type = type_cache.get(type_name)
                    if not photo_type:
                        missing_types.add(type_name)
                        continue

                    key = (member.id, costume.id, photo_type.id)
                    aggregated[key] += quantity

        # ===== Photo補完 =====
        created_photos = 0

        for (member_id, costume_id, type_id), _ in aggregated.items():
            exists = Photo.query.filter_by(
                member_id=member_id,
                costume_id=costume_id,
                type_id=type_id
            ).first()

            if not exists:
                db.session.add(Photo(
                    member_id=member_id,
                    costume_id=costume_id,
                    type_id=type_id
                ))
                created_photos += 1

        db.session.flush()  # ← ID確定

        # ===== UserPhoto反映（冪等）=====
        updated = 0
        inserted = 0

        for (member_id, costume_id, type_id), quantity in aggregated.items():

            photo = Photo.query.filter_by(
                member_id=member_id,
                costume_id=costume_id,
                type_id=type_id
            ).first()

            if not photo:
                continue

            existing = UserPhoto.query.filter_by(
                user_id=TARGET_USER_ID,
                photo_id=photo.id
            ).first()

            if existing:
                # 🔥 冪等：上書き
                existing.quantity = quantity
                existing.available_quantity = quantity
                updated += 1
            else:
                db.session.add(UserPhoto(
                    user_id=TARGET_USER_ID,
                    photo_id=photo.id,
                    quantity=quantity,
                    available_quantity=quantity,
                    has_owner=True
                ))
                inserted += 1

        db.session.commit()

    # ===== レポート =====
    print("==== インポート結果 ====")
    print(f"inserted rows: {inserted}")
    print(f"updated rows: {updated}")
    print(f"created photos: {created_photos}")

    print("\n--- 存在しないメンバー ---")
    for m in sorted(missing_members):
        print(m)

    print("\n--- 存在しない衣装 ---")
    for c in sorted(missing_costumes):
        print(c)

    print("\n--- 存在しないPhotoType ---")
    for t in sorted(missing_types):
        print(t)


if __name__ == "__main__":
    main()