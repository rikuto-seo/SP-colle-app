from flask import Blueprint, jsonify, abort
from flask_login import login_required, current_user
from models import User, WantPhoto, UserPhoto, Group, Photo, Member
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
    # 🔥 必要データ取得
    # =========================
    target_wants = WantPhoto.query.filter_by(user_id=target_user.id).all()
    my_wants = WantPhoto.query.filter_by(user_id=current_user.id).all()

    my_photos = UserPhoto.query.filter(
        UserPhoto.user_id == current_user.id,
        UserPhoto.available_quantity > 0
    ).all()

    target_photos = UserPhoto.query.filter(
        UserPhoto.user_id == target_user.id,
        UserPhoto.available_quantity > 0
    ).all()

    # =========================
    # 🔥 groupフィルタ（正しい経路：Photo → Member → Group）
    # =========================
    def filter_group(items):
        photo_ids = [x.photo_id for x in items]
        if not photo_ids:
            return []

        valid_ids = {
            pid for (pid,) in db.session.query(Photo.id)
            .join(Member, Member.id == Photo.member_id)
            .filter(
                Member.group_id == group.id,
                Photo.id.in_(photo_ids)
            )
            .all()
        }

        return [x for x in items if x.photo_id in valid_ids]

    target_wants = filter_group(target_wants)
    my_wants = filter_group(my_wants)
    my_photos = filter_group(my_photos)
    target_photos = filter_group(target_photos)

    # =========================
    # 🔥 IDセット化
    # =========================
    target_want_ids = {w.photo_id for w in target_wants}
    my_want_ids = {w.photo_id for w in my_wants}

    my_available_map = {p.photo_id: p for p in my_photos}
    target_available_map = {p.photo_id: p for p in target_photos}

    # =========================
    # 🔥 表示用Photoまとめ取得（N+1防止）
    # =========================
    all_photo_ids = set(my_available_map.keys()) | set(target_available_map.keys())

    photo_map = {
        p.id: p for p in db.session.query(Photo)
        .join(Member)
        .filter(Photo.id.in_(all_photo_ids))
        .all()
    }

    def to_dict(p):
        ph = photo_map.get(p.photo_id)
        return {
            "member": ph.member.name if ph else "",
            "costume": ph.costume.name if ph else "",
            "type": ph.photo_type.name if ph else "",
            "available": p.available_quantity
        }

    # =========================
    # 🔥 マッチング
    # =========================

    # 自分が渡せる
    i_can_give = [
        to_dict(p)
        for pid, p in my_available_map.items()
        if pid in target_want_ids
    ]

    # 相手が渡せる
    they_can_give = [
        to_dict(p)
        for pid, p in target_available_map.items()
        if pid in my_want_ids
    ]

    # 相互トレード
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