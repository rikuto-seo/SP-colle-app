# sakamichi_photo_app/routes/share.py

from flask import Blueprint, render_template, abort, request

from models import (
    User,
    UserPhoto,
    Photo,
    Member,
    Costume,
    PhotoType,
    WantShare,
    Group
)
from routes.core import group_required
from extensions import db
from services.stats_service import build_stats_data, get_photo_inventory

share_bp = Blueprint('share', __name__)

ALLOWED_GROUPS = {"nogizaka", "sakurazaka", "hinatazaka"}


# =========================================
# 統計（共有ページ）
# =========================================
@share_bp.route('/shared/<group_key>/<public_uuid>')
@group_required
def shared_stats(group_key, public_uuid):

    if group_key not in ALLOWED_GROUPS:
        abort(404)

    share = WantShare.query.filter_by(
        public_uuid=public_uuid,
        group_key=group_key
    ).first_or_404()

    if not share.is_public:
        return render_template("shared_collection/not_shared.html")

    user = User.query.get_or_404(share.user_id)
    data = build_stats_data(user.id, group_key)
    page = get_photo_inventory(user.id, data['group'].id).order_by(Photo.id).paginate(
        page=request.args.get('page', 1, type=int), per_page=100, error_out=False)
    inventory = page.items
    owned_photo_ids = {row.photo_id for row in inventory if row.quantity and row.quantity > 0}
    all_photos = [dict(id=row.photo_id, member_id=row.member_id, member=row.member, costume=row.costume,
                       costume_id=row.costume_id, photo_type=row.type) for row in inventory]
    total = sum(row['total'] for row in data['progress_list'])
    owned = sum(row['owned'] for row in data['progress_list'])
    stats = {
        'total_count': total,
        'owned_count': owned,
        'percent': owned / total * 100 if total else 0,
        'quantity': sum(data['member_stats'].values()),
        'complete_count': sum(item['complete_count'] for item in data['comp_ranking']),
    }

    return render_template(
        'shared_stats.html',
        user=user,
        stats=stats,
        all_photos=all_photos, owned_photo_ids=owned_photo_ids, pagination=page, share_uuid=public_uuid,
        type_stats=list(data['type_stats'].items()),
        unclassified_stats=data['unclassified_stats'],
        unclassified_quantity=data['unclassified_quantity'],
        group_key=group_key
    )


# =========================================
# コレクション共有
# =========================================
@share_bp.route('/share/<group_key>/<public_uuid>')
@group_required
def shared_collection(group_key, public_uuid):

    if group_key not in ALLOWED_GROUPS:
        abort(404)

    share = WantShare.query.filter_by(
        public_uuid=public_uuid,
        group_key=group_key
    ).first_or_404()

    if not share.is_public:
        return render_template("shared_collection/not_shared.html")

    user = User.query.get_or_404(share.user_id)
    group = Group.query.filter_by(key=group_key).first_or_404()

    # =========================
    # DB JOINで完全取得
    # =========================
    photos = (
        db.session.query(
            UserPhoto,
            Member.name,
            Costume.name,
            PhotoType.name
        )
        .join(Photo, Photo.id == UserPhoto.photo_id)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .filter(
            UserPhoto.user_id == user.id,
            UserPhoto.quantity > 0,
            Member.group_id == group.id
        )
        .all()
    )

    # テンプレート用整形
    photocards = []
    for p, member, costume, ptype in photos:
        photocards.append({
            "id": p.id,
            "member": member,
            "costume": costume,
            "type": ptype,
            "quantity": p.quantity,
            "available": p.available_quantity,
            "memo": p.memo,
            "date": p.date,
            "is_favorite": p.is_favorite
        })

    return render_template(
        "shared_collection/shared_view.html",
        photocards=photocards,
        user=user,
        group_key=group_key
    )
