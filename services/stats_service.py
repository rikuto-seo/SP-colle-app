from collections import defaultdict
from sqlalchemy import func
from models import db, Group, Member, Costume, PhotoType, Photo, UserPhoto
from services.type_normalizer import normalize_type


def build_member_comp_data(user_id, group_key, member_name):

    group = Group.query.filter_by(key=group_key).first_or_404()

    # =========================
    # 所持済み
    # =========================
    owned_rows = (
        db.session.query(
            Costume.name,
            PhotoType.name
        )
        .select_from(UserPhoto)
        .join(Photo, Photo.id == UserPhoto.photo_id)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .filter(
            UserPhoto.user_id == user_id,
            Member.group_id == group.id,
            Member.name == member_name
        )
        .all()
    )

    owned_dict = defaultdict(set)

    for costume, photo_type in owned_rows:
        normalized = normalize_type(
            member_name,
            costume,
            photo_type
        )
        owned_dict[costume].add(normalized)

    # =========================
    # 必要種類
    # =========================
    required_rows = (
        db.session.query(
            Costume.name,
            PhotoType.name
        )
        .select_from(Photo)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .filter(
            Member.group_id == group.id,
            Member.name == member_name
        )
        .all()
    )

    required_dict = defaultdict(set)

    for costume, photo_type in required_rows:
        normalized = normalize_type(
            member_name,
            costume,
            photo_type
        )
        required_dict[costume].add(normalized)

    # =========================
    # コンプ計算
    # =========================
    result = []

    for costume, required_types in required_dict.items():

        owned_types = owned_dict[costume]

        owned_count = len(
            required_types & owned_types
        )

        total = len(required_types)

        result.append({
            "costume": costume,
            "owned": owned_count,
            "total": total,
            "is_complete": (
                total > 0 and owned_count == total
            )
        })

    return sorted(
        result,
        key=lambda x: x["costume"]
    )

def build_stats_data(user_id, group_key):
    group = Group.query.filter_by(key=group_key).first_or_404()

    # =========================
    # メンバー順
    # =========================
    members = Member.query.filter_by(group_id=group.id).all()

    ordered_members = [
        m.name for m in sorted(
            members,
            key=lambda x: (x.generation or 0, x.display_order or 0)
        )
    ]

    # =========================
    # ユーザー所持
    # =========================
    rows = (
        db.session.query(
            Member.name,
            Costume.name,
            PhotoType.name,
            func.sum(UserPhoto.quantity).label("qty")
        )
        .join(Photo, Photo.id == UserPhoto.photo_id)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .filter(
            UserPhoto.user_id == user_id,
            Member.group_id == group.id
        )
        .group_by(Member.name, Costume.name, PhotoType.name)
        .all()
    )

    member_stats = defaultdict(int)
    type_stats = defaultdict(int)
    owned_dict = defaultdict(lambda: defaultdict(set))

    for m, c, t, qty in rows:
        normalized = normalize_type(m, c, t)

        member_stats[m] += qty
        type_stats[normalized] += qty
        owned_dict[m][c].add(normalized)

    # =========================
    # required（Photoそのもの）
    # =========================
    required_rows = (
        db.session.query(
            Member.name,
            Costume.name,
            PhotoType.name
        )
        .join(Photo, Photo.member_id == Member.id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .filter(Member.group_id == group.id)
        .all()
    )

    required_dict = defaultdict(lambda: defaultdict(set))
    for m, c, t in required_rows:
        normalized = normalize_type(m, c, t)
        required_dict[m][c].add(normalized)

    # =========================
    # コンプ
    # =========================
    comp_stats = {}
    comp_ranking = []

    for m in ordered_members:
        member_data = []
        comp_count = 0

        for c, req_types in required_dict.get(m, {}).items():
            owned = owned_dict[m][c]

            owned_count = len(req_types & owned)
            total = len(req_types)

            is_complete = (owned_count == total and total > 0)

            if is_complete:
                comp_count += 1

            member_data.append({
                "costume": c,
                "owned": owned_count,
                "total": total,
                "is_complete": is_complete
            })

        comp_stats[m] = member_data

        comp_ranking.append({
            "member": m,
            "complete_count": comp_count
        })

    comp_ranking.sort(key=lambda x: x["complete_count"], reverse=True)

    # =========================
    # 衣装進捗（quantity対応版）
    # =========================
    total_rows = (
        db.session.query(
            Costume.name,
            func.count(Photo.id)
        )
        .join(Photo)
        .join(Member)
        .filter(Member.group_id == group.id)
        .group_by(Costume.name)
        .all()
    )

    owned_rows = (
        db.session.query(
            Costume.name,
            func.sum(UserPhoto.quantity)
        )
        .join(Photo, Photo.id == UserPhoto.photo_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(Member, Member.id == Photo.member_id)
        .filter(
            UserPhoto.user_id == user_id,
            Member.group_id == group.id
        )
        .group_by(Costume.name)
        .all()
    )

    total_map = dict(total_rows)
    owned_map = dict(owned_rows)

    progress_list = []
    for c, total in total_map.items():
        owned = owned_map.get(c, 0) or 0

        progress_list.append({
            "costume": c,
            "owned": owned,
            "total": total,
            "rate": (owned / total * 100) if total else 0
        })

    return {
        "group": group,
        "member_stats": member_stats,
        "type_stats": dict(type_stats),  # ← Jinja用にdict化
        "comp_stats": comp_stats,
        "comp_ranking": comp_ranking,
        "progress_list": sorted(progress_list, key=lambda x: x["costume"]),
        "ordered_members": ordered_members
    }