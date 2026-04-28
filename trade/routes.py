from flask import Blueprint, jsonify, abort
from flask_login import login_required, current_user
from models import User, WantPhoto, UserPhoto, Group, Photo
from extensions import db

trade_bp = Blueprint('trade', __name__, url_prefix='/trade')


@trade_bp.route('/match/<public_uuid>/<group_key>')
@login_required
def match_trade(public_uuid, group_key):

    target_user = User.query.filter_by(public_uuid=public_uuid).first_or_404()
    group = Group.query.filter_by(key=group_key).first_or_404()

    if not target_user.is_want_share_enabled(group_key):
        abort(404)

    # =========================
    # 🔥 必要データ（全部photo_idで統一）
    # =========================

    target_wants = WantPhoto.query.filter_by(
        user_id=target_user.id
    ).all()

    my_wants = WantPhoto.query.filter_by(
        user_id=current_user.id
    ).all()

    my_photos = UserPhoto.query.filter(
        UserPhoto.user_id == current_user.id,
        UserPhoto.available_quantity > 0
    ).all()

    target_photos = UserPhoto.query.filter(
        UserPhoto.user_id == target_user.id,
        UserPhoto.available_quantity > 0
    ).all()

    # =========================
    # 🔥 groupフィルタ（Photo経由）
    # =========================
    def filter_group(items):
        photo_ids = [x.photo_id for x in items]
        if not photo_ids:
            return []

        valid_ids = {
            p.id for p in db.session.query(Photo.id)
            .join(Group, Group.id == Photo.group_id)
            .filter(Group.id == group.id, Photo.id.in_(photo_ids))
            .all()
        }

        return [x for x in items if x.photo_id in valid_ids]

    target_wants = filter_group(target_wants)
    my_wants = filter_group(my_wants)
    my_photos = filter_group(my_photos)
    target_photos = filter_group(target_photos)

    # =========================
    # 🔥 キーはphoto_id
    # =========================
    target_want_ids = {w.photo_id for w in target_wants}
    my_want_ids = {w.photo_id for w in my_wants}

    my_available_map = {p.photo_id: p for p in my_photos}
    target_available_map = {p.photo_id: p for p in target_photos}

    # =========================
    # 🔥 表示用補助（Photo情報取得）
    # =========================
    photo_map = {
        p.id: p for p in db.session.query(Photo)
        .filter(Photo.id.in_(
            list(my_available_map.keys()) +
            list(target_available_map.keys())
        ))
        .all()
    }

    def to_dict(p):
        ph = photo_map.get(p.photo_id)
        return {
            "member": ph.member if ph else "",
            "costume": ph.costume if ph else "",
            "type": ph.photo_type if ph else "",
            "available": p.available_quantity
        }

    # =========================
    # 🔥 マッチング
    # =========================

    i_can_give = [
        to_dict(p)
        for pid, p in my_available_map.items()
        if pid in target_want_ids
    ]

    they_can_give = [
        to_dict(p)
        for pid, p in target_available_map.items()
        if pid in my_want_ids
    ]

    mutual_matches = []

    for my_pid, my_p in my_available_map.items():
        if my_pid not in target_want_ids:
            continue

        for their_pid, their_p in target_available_map.items():
            if their_pid not in my_want_ids:
                continue

            if (my_p.available_quantity or 0) > 0 and (their_p.available_quantity or 0) > 0:
                mutual_matches.append({
                    "give": to_dict(my_p),
                    "receive": to_dict(their_p)
                })

    return jsonify({
        "i_can_give": i_can_give,
        "they_can_give": they_can_give,
        "mutual": mutual_matches
    })