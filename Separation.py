import csv

from app import app
from extensions import db
from models import UserPhoto, Photo, Member, Costume, PhotoType

# ========= 設定 =========
CSV_PATH = r"C:\Users\Teikyo\Desktop\my-all-directory\application-directory\sakamichi_photo_app\日向坂 生写真管理 a96ae5d42c2d820fa4380137fd36b89b_all.csv"
TARGET_USER_ID = 1

TYPE_MAPPING = {
    "ヨリ": "ヨリ",
    "チュウ": "チュウ",
    "ヒキ": "ヒキ",
    "座り": "座り",
}
# ========================


# ===== 正規化関数（ここが今回のコア）=====
def normalize(text: str) -> str:
    if not text:
        return ""

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

    # ① 完全一致
    for c in candidates:
        if normalize(c.name) == target:
            return c

    # ② 部分一致（強め）
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

    inserted_count = 0

    with app.app_context():

        # ===== PhotoTypeキャッシュ =====
        type_cache = {t.name: t for t in PhotoType.query.all()}

        # ===== Costumeキャッシュ（group別）=====
        costume_cache = {}
        all_costumes = Costume.query.all()
        for c in all_costumes:
            costume_cache.setdefault(c.group_id, []).append(c)

        with open(CSV_PATH, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            for row in reader:
                member_name = (row.get("メンバー名前") or "").strip()
                costume_name = (row.get("シリーズ") or "").strip()

                if not member_name or not costume_name:
                    continue

                # ===== Member =====
                member = Member.query.filter_by(name=member_name).first()
                if not member:
                    missing_members.add(member_name)
                    continue

                # ===== Costume（正規化検索）=====
                costume = find_costume(member, costume_name, costume_cache)

                if not costume:
                    missing_costumes.add(costume_name)
                    continue

                # ===== typeごと処理 =====
                for csv_col, type_name in TYPE_MAPPING.items():

                    val = row.get(csv_col)
                    if not val:
                        continue

                    val = val.strip()
                    if not val.isdigit():
                        continue

                    quantity = int(val)
                    if quantity <= 0:
                        continue

                    # ===== PhotoType =====
                    photo_type = type_cache.get(type_name)
                    if not photo_type:
                        missing_types.add(type_name)
                        continue

                    # ===== Photo =====
                    photo = Photo.query.filter_by(
                        member_id=member.id,
                        costume_id=costume.id,
                        type_id=photo_type.id
                    ).first()

                    if not photo:
                        missing_photos.append(
                            (member_name, costume_name, type_name)
                        )
                        continue

                    # ===== UserPhoto =====
                    existing = UserPhoto.query.filter_by(
                        user_id=TARGET_USER_ID,
                        photo_id=photo.id
                    ).first()

                    if existing:
                        existing.quantity += quantity
                        existing.available_quantity += quantity
                    else:
                        up = UserPhoto(
                            user_id=TARGET_USER_ID,
                            photo_id=photo.id,
                            quantity=quantity,
                            available_quantity=quantity,
                            has_owner=True
                        )
                        db.session.add(up)

                    inserted_count += quantity

        db.session.commit()

    # ===== レポート =====
    print("==== インポート結果 ====")
    print(f"inserted (total枚数): {inserted_count}")

    print("\n--- 存在しないメンバー ---")
    for m in sorted(missing_members):
        print(m)

    print("\n--- 存在しない衣装 ---")
    for c in sorted(missing_costumes):
        print(c)

    print("\n--- 存在しないPhotoType ---")
    for t in sorted(missing_types):
        print(t)

    print("\n--- Photo未定義 (member / costume / type) ---")
    for m, c, t in missing_photos:
        print(f"{m} / {c} / {t}")


if __name__ == "__main__":
    main()