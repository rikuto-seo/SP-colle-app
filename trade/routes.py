from flask import Blueprint, jsonify, abort
from flask_login import login_required, current_user
from models import User, WantPhoto, UserPhoto

trade_bp = Blueprint('trade', __name__, url_prefix='/trade')

def is_match(want, photo):
    if want.member and want.member != photo.member:
        return False
    if want.costume and want.costume != photo.costume:
        return False
    if want.photo_type and want.photo_type != photo.photo_type:
        return False
    return True


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

    my_wants = WantPhoto.query.filter_by(
        user_id=current_user.id,
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

    i_can_give = []

    for p in my_photos:
        for w in target_wants:
            if is_match(w, p):
                i_can_give.append({
                    "member": p.member,
                    "costume": p.costume,
                    "type": p.photo_type,
                    "available": p.available_quantity
                })
                break

    they_can_give = []

    for p in target_photos:
        for w in my_wants:
            if is_match(w, p):
                they_can_give.append({
                    "member": p.member,
                    "costume": p.costume,
                    "type": p.photo_type,
                    "available": p.available_quantity
                })
                break

    mutual_matches = []

    for my_p in my_photos:
        for their_w in target_wants:
            if not is_match(their_w, my_p):
                continue

            for their_p in target_photos:
                for my_w in my_wants:
                    if is_match(my_w, their_p):
                        mutual_matches.append({
                            "give": {
                                "member": my_p.member,
                                "costume": my_p.costume,
                                "type": my_p.photo_type
                            },
                            "receive": {
                                "member": their_p.member,
                                "costume": their_p.costume,
                                "type": their_p.photo_type
                            }
                        })

    return jsonify({
        "i_can_give": i_can_give,
        "they_can_give": they_can_give,
        "mutual": mutual_matches
    })