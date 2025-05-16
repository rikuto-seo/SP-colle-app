import os
import csv
from app import app, db
from models import Photo

GROUPS = {
    'hinatazaka': '日向坂46',
    'nogizaka': '乃木坂46',
    'sakurazaka': '櫻坂46'
}

def import_photos_from_csv():
    with app.app_context():
        for group_key, group_name in GROUPS.items():
            dir_path = os.path.join("members_csv", group_key)
            if not os.path.isdir(dir_path):
                print(f"❌ ディレクトリが見つかりません: {dir_path}")
                continue

            for filename in os.listdir(dir_path):
                if filename.endswith(".csv"):
                    member = filename.replace(".csv", "")
                    csv_path = os.path.join(dir_path, filename)
                    with open(csv_path, encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            costume = row["costume"]
                            type_ = row["type"]

                            # 重複チェック
                            exists = Photo.query.filter_by(
                                group_key=group_key,
                                member=member,
                                costume=costume,
                                photo_type=type_
                            ).first()
                            if exists:
                                continue

                            photo = Photo(
                                group_key=group_key,
                                group=group_name,
                                member=member,
                                costume=costume,
                                photo_type=type_
                            )
                            db.session.add(photo)

        db.session.commit()
        print("✅ CSVからPhotoデータをインポートしました")

if __name__ == "__main__":
    import_photos_from_csv()
