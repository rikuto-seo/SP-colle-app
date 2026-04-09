import os,csv
from flask_login import current_user
from models import UserPhoto
from collections import defaultdict
from flask import current_app

def load_required_types(group_key):
    base = os.path.join(current_app.root_path, 'members_csv', group_key)
    required = defaultdict(lambda: defaultdict(set))

    for filename in os.listdir(base):
        if not filename.endswith(".csv"):
            continue

        if filename == "members_master.csv":
            continue

        with open(os.path.join(base, filename), encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)

            for row in reader:
                if len(row) < 3:
                    continue

                member = row[0].strip()
                costume = row[1].strip()
                photo_type = row[2].strip()

                required[member][costume].add(photo_type)

    return required

def get_photos_by_group(group_key):
    folder_path = f'members_csv/{group_key}'
    photos_by_member = {}

    for filename in os.listdir(folder_path):
        if filename.endswith('.csv'):
            member_name = filename.replace('.csv', '')
            member_photos = []
            csv_path = os.path.join(folder_path, filename)
            with open(csv_path, encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if len(row) == 3:
                        member, costume, photo_type = row
                        member_photos.append({
                            'member': member,
                            'costume': costume,
                            'photo_type': photo_type
                        })
            photos_by_member[member_name] = member_photos

    return photos_by_member

def get_missing_photos(search_member='', search_costume='', group_key='hinatazaka'):
    """
    CSVを正として未所持写真を算出する
    """

    required = load_required_types(group_key)

    owned = {
        (
            p.member.strip(),
            p.costume.strip(),
            p.photo_type.strip()
        )
        for p in UserPhoto.query.filter_by(
            user_id=current_user.id,
            group_key=group_key
        ).all()
    }

    grouped = defaultdict(list)

    for member, costumes in required.items():

        if search_member and search_member not in member:
            continue

        for costume, types in costumes.items():

            if search_costume and search_costume not in costume:
                continue

            for photo_type in types:
                key = (member, costume, photo_type)
                if key not in owned:
                    grouped[member].append({
                        'costume': costume,
                        'type': photo_type
                    })

    return grouped
