from collections import defaultdict
from sqlalchemy import exists
from models import db, Member, Costume, PhotoType, Photo, UserPhoto, Group


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
        db.session.query(PhotoType.name)
        .join(Photo)
        .join(Member)
        .join(Costume)
        .filter(
            Member.group_id == group_id,
            Member.name == member_name,
            Costume.name == costume_name
        )
        .all()
    )

    return sorted({t for (t,) in rows})


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