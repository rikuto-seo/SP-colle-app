# sakamichi_photo_app/routes/share.py

from flask import Blueprint, render_template, abort
from flask_login import current_user
from sqlalchemy import func

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
    group = Group.query.filter_by(key=group_key).first_or_404()

    # =========================
    # 全体母数（分母）
    # =========================
    total_photos = (
        db.session.query(func.count(Photo.id))
        .join(Member)
        .filter(Member.group_id == group.id)
        .scalar()
    )

    # =========================
    # 所持数（分子）
    # =========================
    owned_photos = (
        db.session.query(func.sum(UserPhoto.quantity))
        .join(Photo)
        .join(Member)
        .filter(
            UserPhoto.user_id == user.id,
            Member.group_id == group.id
        )
        .scalar()
    ) or 0

    # =========================
    # メンバー別集計
    # =========================
    member_stats = (
        db.session.query(
            Member.name,
            func.coalesce(func.sum(UserPhoto.quantity), 0)
        )
        .join(Photo, Photo.member_id == Member.id)
        .outerjoin(
            UserPhoto,
            (UserPhoto.photo_id == Photo.id) &
            (UserPhoto.user_id == user.id)
        )
        .filter(Member.group_id == group.id)
        .group_by(Member.name)
        .all()
    )

    stats = {
        "total": total_photos,
        "owned": owned_photos,
        "rate": (owned_photos / total_photos * 100) if total_photos else 0,
        "member_stats": member_stats
    }

    return render_template(
        'shared_stats.html',
        user=user,
        stats=stats,
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