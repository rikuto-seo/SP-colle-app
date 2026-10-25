from collections import Counter

from flask import abort
from sqlalchemy import func

from models import db, Group, Member, Costume, PhotoType, Photo, UserPhoto
from services.type_normalizer import NORMALIZED_TYPES, get_type_resolver


def _owned_join(user_id):
    return ((UserPhoto.photo_id == Photo.id) & (UserPhoto.user_id == user_id)
            & (UserPhoto.quantity > 0))


def get_photo_inventory(user_id, group_id):
    """Paginate this query before materializing photos for display."""
    return (
        db.session.query(
            Photo.id.label('photo_id'), Member.id.label('member_id'), Member.name.label('member'),
            Costume.id.label('costume_id'), Costume.name.label('costume'),
            PhotoType.id.label('photo_type_id'), PhotoType.name.label('type'),
            UserPhoto.quantity.label('quantity'),
        )
        .select_from(Photo)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .outerjoin(UserPhoto, _owned_join(user_id))
        .filter(Member.group_id == group_id)
    )


def _costume_labels(group_id):
    costumes = Costume.query.filter_by(group_id=group_id).all()
    names = Counter(c.name for c in costumes)
    return {c.id: f'{c.name}（衣装ID: {c.id}）' if names[c.name] > 1 else c.name for c in costumes}


def _completion_query(user_id, group_id):
    # UserPhoto is unique per (user_id, photo_id), so each joined row is one
    # distinct Photo. Classification is deliberately absent from this query.
    return (
        db.session.query(
            Photo.member_id.label('member_id'), Photo.costume_id.label('costume_id'),
            Costume.name.label('costume'), func.count(Photo.id).label('total'),
            func.count(UserPhoto.photo_id).label('owned'),
            func.coalesce(func.sum(UserPhoto.quantity), 0).label('quantity'),
        )
        .select_from(Photo)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .outerjoin(UserPhoto, _owned_join(user_id))
        .filter(Member.group_id == group_id)
        .group_by(Photo.member_id, Photo.costume_id, Costume.name)
    )


def _completion_entry(row, labels):
    return {
        'member_id': row.member_id, 'costume_id': row.costume_id, 'costume': row.costume,
        'costume_label': labels.get(row.costume_id, row.costume),
        'owned': row.owned, 'total': row.total, 'is_complete': row.total > 0 and row.owned == row.total,
    }


def build_member_comp_data(user_id, group_key, member_name=None, *, member_id=None):
    group = Group.query.filter_by(key=group_key).first_or_404()
    members = Member.query.filter_by(group_id=group.id)
    if member_id is None:
        matches = members.filter_by(name=member_name).all()
        if not matches:
            abort(404)
        if len(matches) != 1:
            abort(409, description='Member name is ambiguous; use member ID.')
        member_id = matches[0].id
    else:
        members.filter_by(id=member_id).first_or_404()
    rows = _completion_query(user_id, group.id).filter(Photo.member_id == member_id).all()
    labels = _costume_labels(group.id)
    return sorted((_completion_entry(row, labels) for row in rows),
                  key=lambda item: (item['costume'], item['costume_id']))


def build_stats_data(user_id, group_key):
    group = Group.query.filter_by(key=group_key).first_or_404()
    members = sorted(Member.query.filter_by(group_id=group.id).all(),
                     key=lambda m: (m.generation or 0, m.display_order or 0, m.id))
    labels = _costume_labels(group.id)
    rows = _completion_query(user_id, group.id).all()
    member_stats = dict.fromkeys((m.id for m in members), 0)
    comp_stats = {m.id: [] for m in members}
    progress = {}
    for row in rows:
        member_stats[row.member_id] += row.quantity
        comp_stats[row.member_id].append(_completion_entry(row, labels))
        item = progress.setdefault(row.costume_id, {
            'costume_id': row.costume_id, 'costume': row.costume,
            'costume_label': labels.get(row.costume_id, row.costume), 'owned': 0, 'total': 0,
        })
        item['owned'] += row.owned
        item['total'] += row.total
    for entries in comp_stats.values():
        entries.sort(key=lambda item: (item['costume'], item['costume_id']))
    for item in progress.values():
        item['rate'] = item['owned'] / item['total'] * 100
    comp_ranking = [dict(member_id=m.id, member=m.name,
                        complete_count=sum(item['is_complete'] for item in comp_stats[m.id])) for m in members]
    comp_ranking.sort(key=lambda item: item['complete_count'], reverse=True)

    # Sum by costume/type in SQL, resolving a classification once per pair
    # instead of allocating all member/costume/type Photos in Python.
    type_rows = (
        db.session.query(Photo.costume_id.label('costume_id'), Costume.name.label('costume'),
            Photo.type_id.label('photo_type_id'), PhotoType.name.label('type'),
            func.sum(UserPhoto.quantity).label('quantity'), func.count(Photo.id).label('photo_count'))
        .select_from(UserPhoto)
        .join(Photo, Photo.id == UserPhoto.photo_id)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .filter(UserPhoto.user_id == user_id, UserPhoto.quantity > 0, Member.group_id == group.id)
        .group_by(Photo.costume_id, Costume.name, Photo.type_id, PhotoType.name)
        .all()
    )
    resolver = get_type_resolver(group.id)
    type_stats = dict.fromkeys(NORMALIZED_TYPES, 0)
    unclassified = []
    for row in type_rows:
        normalized = resolver.resolve(row.costume_id, row.photo_type_id, row.costume, row.type)
        if normalized in type_stats:
            type_stats[normalized] += row.quantity
        else:
            unclassified.append(dict(row._mapping, costume_label=labels.get(row.costume_id, row.costume)))
    return {
        'group': group, 'member_stats': member_stats, 'type_stats': type_stats,
        'unclassified_stats': sorted(unclassified, key=lambda r: (r['costume'], r['costume_id'], r['type'])),
        'unclassified_quantity': sum(item['quantity'] for item in unclassified),
        'comp_stats': comp_stats, 'comp_ranking': comp_ranking,
        'progress_list': sorted(progress.values(), key=lambda r: (r['costume'], r['costume_id'])),
        'ordered_members': [dict(id=m.id, name=m.name) for m in members],
        'member_names': {m.id: m.name for m in members},
    }
