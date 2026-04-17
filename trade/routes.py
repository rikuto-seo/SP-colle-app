from flask import Blueprint, jsonify, abort
from flask_login import login_required, current_user
from models import User, WantPhoto, UserPhoto

trade_bp = Blueprint('trade', __name__, url_prefix='/trade')


@trade_bp.route('/match/<public_uuid>/<group_key>')
@login_required
def match_trade(public_uuid, group_key):
    target_user = User.query.filter_by(public_uuid=public_uuid).first_or_404()

    if not target_user.is_want_share_enabled(group_key):
        abort(404)

    target_wants = WantPhoto.query.filter_by(
        user_id=target_user.id,
        group_key=group_key
    ).all()

    my_photos = UserPhoto.query.filter(
        UserPhoto.user_id == current_user.id,
        UserPhoto.group_key == group_key,
        UserPhoto.available_quantity > 0
    ).all()

    target_photos = UserPhoto.query.filter(
        UserPhoto.user_id == target_user.id,
        UserPhoto.group_key == group_key,
        UserPhoto.available_quantity > 0
    ).all()

    my_wants = WantPhoto.query.filter_by(
        user_id=current_user.id,
        group_key=group_key
    ).all()

    print("=== DEBUG ===")
    print("my_photos:", len(my_photos))
    print("target_photos:", len(target_photos))
    print("my_wants:", len(my_wants))
    print("target_wants:", len(target_wants))

    print("=== FULL DEBUG ===")
    print("current_user.id:", current_user.id)
    print("group_key:", group_key)

    all_my = UserPhoto.query.all()
    print("ALL UserPhoto:", [
        (p.user_id, p.group_key, p.member, p.available_quantity)
        for p in all_my
    ])

    def key(p):
        return (p.member, p.costume, p.photo_type)

    my_available_map = {key(p): p for p in my_photos}
    target_available_map = {key(p): p for p in target_photos}

    target_want_keys = {key(w) for w in target_wants}
    my_want_keys = {key(w) for w in my_wants}

    i_can_give = []
    for k, p in my_available_map.items():
        if k in target_want_keys:
            i_can_give.append({
                "member": p.member,
                "costume": p.costume,
                "type": p.photo_type,
                "available": p.available_quantity
            })

    they_can_give = []
    for k, p in target_available_map.items():
        if k in my_want_keys:
            they_can_give.append({
                "member": p.member,
                "costume": p.costume,
                "type": p.photo_type,
                "available": p.available_quantity
            })

    mutual_matches = []
    for my_item in i_can_give:
        for their_item in they_can_give:
            mutual_matches.append({
                "give": my_item,
                "receive": their_item
            })

    return jsonify({
        "i_can_give": i_can_give,
        "they_can_give": they_can_give,
        "mutual": mutual_matches
    })