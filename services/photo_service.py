from collections import defaultdict
import re
from sqlalchemy import exists
from models import db, Member, Costume, PhotoType, Photo, UserPhoto, Group
from services.type_normalizer import get_type_resolver, get_type_order


def get_required_dict(group_id):
    rows = (
        db.session.query(
            Member.name,
            Costume.name,
            PhotoType.name
        )
        .join(Photo)
        .join(Costume)
        .join(PhotoType)
        .filter(Member.group_id == group_id)
        .all()
    )

    result = defaultdict(lambda: defaultdict(set))

    for m, c, t in rows:
        result[m][c].add(t)

    return result


def get_members(group_id):
    members = (
        Member.query
        .filter_by(group_id=group_id)
        .order_by(Member.generation, Member.display_order)
        .all()
    )
    return [m.name for m in members]


def get_costumes(group_id, member_name=None):
    q = (
        db.session.query(Costume.name)
        .join(Photo)
        .join(Member)
        .filter(Member.group_id == group_id)
    )

    if member_name:
        q = q.filter(Member.name == member_name)

    return sorted({c for (c,) in q.all()})


def get_types(group_id, member_name, costume_name):
    rows = (
        db.session.query(Costume.id, PhotoType.id, PhotoType.name)
        .select_from(Photo)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .filter(
            Member.group_id == group_id,
            Member.name == member_name,
            Costume.name == costume_name
        )
        .all()
    )

    resolver = get_type_resolver(group_id)

    def type_sort_key(row):
        costume_id, photo_type_id, photo_type = row
        # Use the collection's classification without changing option labels/values.
        category_order = get_type_order(resolver.resolve(costume_id, photo_type_id, costume_name, photo_type))
        natural_name = tuple(
            (1, int(part)) if part.isdigit() else (0, part)
            for part in re.split(r'(\d+)', photo_type)
        )
        return category_order, natural_name, photo_type

    return list(dict.fromkeys(row[2] for row in sorted(rows, key=type_sort_key)))


def get_owned_members(user_id, group_id):
    rows = (
        db.session.query(Member)
        .select_from(UserPhoto)
        .join(Photo, Photo.id == UserPhoto.photo_id)
        .join(Member, Member.id == Photo.member_id)
        .filter(
            UserPhoto.user_id == user_id,
            UserPhoto.quantity > 0,
            Member.group_id == group_id
        )
        .distinct()
        .order_by(Member.generation, Member.display_order)
        .all()
    )
    return [member.name for member in rows]


def get_owned_costumes(user_id, group_id, member_name):
    rows = (
        db.session.query(Costume.name)
        .select_from(UserPhoto)
        .join(Photo, Photo.id == UserPhoto.photo_id)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .filter(
            UserPhoto.user_id == user_id,
            UserPhoto.quantity > 0,
            Member.group_id == group_id,
            Member.name == member_name
        )
        .distinct()
        .all()
    )
    return sorted({costume for (costume,) in rows})


def get_owned_types(user_id, group_id, member_name, costume_name):
    rows = (
        db.session.query(PhotoType.name)
        .select_from(UserPhoto)
        .join(Photo, Photo.id == UserPhoto.photo_id)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .filter(
            UserPhoto.user_id == user_id,
            UserPhoto.quantity > 0,
            Member.group_id == group_id,
            Member.name == member_name,
            Costume.name == costume_name
        )
        .distinct()
        .all()
    )
    return sorted({photo_type for (photo_type,) in rows})


def get_missing_photos(user_id, group_id):
    rows = (
        db.session.query(
            Member.name,
            Costume.name,
            PhotoType.name
        )
        .join(Photo)
        .join(Costume)
        .join(PhotoType)
        .filter(Member.group_id == group_id)
        .filter(
            ~exists().where(
                (UserPhoto.user_id == user_id) &
                (UserPhoto.photo_id == Photo.id)
            )
        )
        .all()
    )

    grouped = defaultdict(list)

    for m, c, t in rows:
        grouped[m].append({
            "costume": c,
            "type": t
        })

    return grouped
