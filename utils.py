import os
import csv
from models import Photo, UserPhoto
from collections import defaultdict

# 指定メンバーの衣装一覧を取得
def get_costumes_for_member(group, member):
    group_mapping = {
        "hinata": "hinatazaka",
        "nogizaka": "nogizaka",
        "sakurazaka": "sakurazaka"
    }
    group_folder = group_mapping.get(group, group)
    path = os.path.join('members_csv', group_folder, f'{member}.csv')

    try:
        with open(path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            costumes = {row['costume'].strip() for row in reader if 'costume' in row}
            return sorted(costumes)
    except FileNotFoundError:
        print(f"File not found: {path}")
        return []

# 全写真の一覧をCSVから読み込む
def load_photos_from_csv(group_key):
    folder = os.path.join('members_csv', group_key)
    photos = []
    if not os.path.exists(folder):
        return photos

    for fname in os.listdir(folder):
        if fname.endswith('.csv'):
            with open(os.path.join(folder, fname), encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not all(k in row for k in ('member', 'costume', 'type')):
                        continue
                    photos.append(Photo(
                        member=row['member'].strip(),
                        costume=row['costume'].strip(),
                        photo_type=row['type'].strip(),
                        group_key=group_key
                    ))
    return photos

# 画像のファイルパスを構築
def build_image_path(member, costume, type_, group_key):
    filename = f"{member}_{costume}_{type_}.jpg"
    return f"member_images/{group_key}/{member}/{filename}"

# 全写真（Photoモデル）の取得（CSV経由）
def get_all_photos(group_key):
    return load_photos_from_csv(group_key)

# ユーザーが所持している写真ID一覧を取得
def get_user_photo_ids(user_id, group_key):
    records = UserPhoto.query.filter_by(owner_id=user_id, group=group_key).all()
    return set((r.member, r.costume, r.photo_type) for r in records)

# コレクション統計を算出（所持数・コンプ数など）
def compute_collection_stats(all_photos, owned_photo_ids):
    total = len(all_photos)
    owned = sum(1 for photo in all_photos if
                (photo.member, photo.costume, photo.photo_type) in owned_photo_ids)

    # メンバーごとのコンプ状況
    member_costume_map = defaultdict(lambda: defaultdict(set))
    for photo in all_photos:
        member_costume_map[photo.member][photo.costume].add(photo.photo_type)

    member_costume_owned_map = defaultdict(lambda: defaultdict(set))
    for member, costume, photo_type in owned_photo_ids:
        member_costume_owned_map[member][costume].add(photo_type)

    completed_sets = 0
    total_sets = 0

    for member in member_costume_map:
        for costume in member_costume_map[member]:
            required = member_costume_map[member][costume]
            owned = member_costume_owned_map[member][costume]
            total_sets += 1
            if required == owned:
                completed_sets += 1

    completion_rate = round((owned / total) * 100, 1) if total > 0 else 0
    fullset_rate = round((completed_sets / total_sets) * 100, 1) if total_sets > 0 else 0

    return {
        'total_photos': total,
        'owned_photos': owned,
        'completion_rate': completion_rate,
        'completed_sets': completed_sets,
        'total_sets': total_sets,
        'fullset_rate': fullset_rate
    }
