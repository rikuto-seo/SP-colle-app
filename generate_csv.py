from pathlib import Path
import csv
from collections import defaultdict

base_path = Path("static/member_images")
output_dir = Path("members_csv")
output_dir.mkdir(parents=True, exist_ok=True)

group_keys = ["hinatazaka", "nogizaka", "sakurazaka"]

# タイプの並び順
type_order = ["ヨリ", "チュウ", "ヒキ", "座り"]

for group_key in group_keys:
    group_dir = base_path / group_key
    output_group_dir = output_dir / group_key
    output_group_dir.mkdir(parents=True, exist_ok=True)

    for member_dir in group_dir.iterdir():
        if not member_dir.is_dir():
            continue

        member_name = member_dir.name
        costume_dict = defaultdict(dict)

        for image_file in member_dir.glob("*.*"):
            if image_file.suffix.lower() not in [".jpg", ".jpeg", ".png"]:
                continue

            base = image_file.stem
            parts = base.split("_")

            if len(parts) < 3:
                print(f"❌ スキップ: パーツ不足 {base}")
                continue

            name = parts[0]
            type_ = parts[-1]
            costume = "_".join(parts[1:-1])

            if name != member_name:
                print(f"⚠️ スキップ: メンバー名不一致 (フォルダ: {member_name}, ファイル名: {name})")
                continue

            costume_dict[costume][type_] = type_

        # CSV 書き出し
        csv_path = output_group_dir / f"{member_name}.csv"
        rows_written = 0

        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["member", "costume", "type"])

            for costume, type_dict in costume_dict.items():
                for t in type_order:
                    if t in type_dict:
                        writer.writerow([member_name, costume.replace("_", " "), t])
                        rows_written += 1

        if rows_written == 0:
            print(f"⚠️ データなし: {member_name}")
        else:
            print(f"✅ 書き込み完了: {csv_path}")
