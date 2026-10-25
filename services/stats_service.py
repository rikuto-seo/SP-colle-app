from collections import Counter, defaultdict

from models import db, Group, Member, Costume, PhotoType, Photo, UserPhoto
from services.type_normalizer import NORMALIZED_TYPES, get_type_resolver


def get_photo_inventory(user_id, group_id, member_name=None):
    """One row per Photo; only positive quantities count as ownership."""
    query = (
        db.session.query(
            Photo.id.label('photo_id'),
            Member.id.label('member_id'), Member.name.label('member'),
            Costume.id.label('costume_id'), Costume.name.label('costume'),
            PhotoType.id.label('photo_type_id'), PhotoType.name.label('type'),
            UserPhoto.quantity.label('quantity'),
        )
        .select_from(Photo)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .outerjoin(UserPhoto, (UserPhoto.photo_id == Photo.id)
                   & (UserPhoto.user_id == user_id) & (UserPhoto.quantity > 0))
        .filter(Member.group_id == group_id)
    )
    if member_name is not None:
        query = query.filter(Member.name == member_name)
    return query.all()


def _costume_labels(group_id):
    costumes = Costume.query.filter_by(group_id=group_id).all()
    names = Counter(c.name for c in costumes)
    return {
        c.id: f'{c.name}（衣装ID: {c.id}）' if names[c.name] > 1 else c.name
        for c in costumes
    }


def _completion_data(rows, labels):
    """Classification and duplicate quantities never change Photo identity."""
    required = defaultdict(set)
    owned = defaultdict(set)
    names = {}
    for row in rows:
        key = (row.member_id, row.costume_id)
        names[key] = row.costume
        required[key].add(row.photo_id)
        if row.quantity is not None and row.quantity > 0:
            owned[key].add(row.photo_id)

    by_member = defaultdict(list)
    for (member_id, costume_id), photo_ids in required.items():
        owned_count = len(photo_ids & owned[(member_id, costume_id)])
        by_member[member_id].append({
            'costume_id': costume_id,
            'costume': names[(member_id, costume_id)],
            'costume_label': labels[costume_id],
            'owned': owned_count,
            'total': len(photo_ids),
            'is_complete': owned_count == len(photo_ids),
        })
    for entries in by_member.values():
        entries.sort(key=lambda item: (item['costume'], item['costume_id']))
    return by_member


def build_member_comp_data(user_id, group_key, member_name):
    group = Group.query.filter_by(key=group_key).first_or_404()
    rows = get_photo_inventory(user_id, group.id, member_name)
    by_member = _completion_data(rows, _costume_labels(group.id))
    return [entry for entries in by_member.values() for entry in entries]


def build_stats_data(user_id, group_key):
    group = Group.query.filter_by(key=group_key).first_or_404()
    members = sorted(Member.query.filter_by(group_id=group.id).all(),
                     key=lambda m: (m.generation or 0, m.display_order or 0, m.id))
    rows = get_photo_inventory(user_id, group.id)
    labels = _costume_labels(group.id)
    completion = _completion_data(rows, labels)
    resolver = get_type_resolver(group.id)

    member_stats = defaultdict(int)
    type_stats = dict.fromkeys(NORMALIZED_TYPES, 0)
    unclassified = {}
    required_photos = defaultdict(set)
    owned_photos = defaultdict(set)
    costume_names = {}

    for row in rows:
        required_photos[row.costume_id].add(row.photo_id)
        costume_names[row.costume_id] = row.costume
        if row.quantity is None or row.quantity <= 0:
            continue
        owned_photos[row.costume_id].add(row.photo_id)
        member_stats[row.member] += row.quantity
        normalized = resolver.resolve(row.costume_id, row.photo_type_id, row.costume, row.type)
        if normalized in type_stats:
            type_stats[normalized] += row.quantity
        else:
            key = (row.costume_id, row.photo_type_id)
            item = unclassified.setdefault(key, {
                'costume_id': row.costume_id, 'costume': row.costume,
                'costume_label': labels[row.costume_id],
                'photo_type_id': row.photo_type_id, 'type': row.type,
                'quantity': 0, 'photo_count': 0,
            })
            item['quantity'] += row.quantity
            item['photo_count'] += 1

    comp_stats = {}
    comp_ranking = []
    for member in members:
        entries = completion.get(member.id, [])
        comp_stats[member.name] = entries
        comp_ranking.append({
            'member': member.name,
            'complete_count': sum(entry['is_complete'] for entry in entries),
        })
    comp_ranking.sort(key=lambda item: item['complete_count'], reverse=True)

    progress_list = []
    for costume_id, photo_ids in required_photos.items():
        owned_count = len(photo_ids & owned_photos[costume_id])
        progress_list.append({
            'costume_id': costume_id, 'costume': costume_names[costume_id],
            'costume_label': labels[costume_id],
            'owned': owned_count, 'total': len(photo_ids),
            'rate': owned_count / len(photo_ids) * 100,
        })

    unclassified_stats = sorted(unclassified.values(),
                                key=lambda item: (item['costume'], item['costume_id'], item['type']))
    return {
        'group': group,
        'member_stats': member_stats,
        'type_stats': type_stats,
        'unclassified_stats': unclassified_stats,
        'unclassified_quantity': sum(item['quantity'] for item in unclassified_stats),
        'comp_stats': comp_stats,
        'comp_ranking': comp_ranking,
        'progress_list': sorted(progress_list, key=lambda item: (item['costume'], item['costume_id'])),
        'ordered_members': [member.name for member in members],
    }
