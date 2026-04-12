from flask import Blueprint, render_template, abort
from models import User, UserPhoto,WantShare
from routes.core import group_required
from forstats import get_all_photos, get_user_photo_ids, compute_collection_stats
from extensions import db

share_bp = Blueprint('share', __name__)

ALLOWED_GROUPS = {"nogizaka", "sakurazaka", "hinatazaka"}

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

    all_photos = get_all_photos(group_key)
    owned = get_user_photo_ids(user.id, group_key)
    stats = compute_collection_stats(all_photos, owned)

    return render_template('shared_stats.html', user=user, stats=stats)

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

    photos = UserPhoto.query.filter_by(
        user_id=user.id,
        group_key=group_key
    ).all()

    return render_template(
        "shared_collection/shared_view.html",
        photocards=photos,
        user=user
    )