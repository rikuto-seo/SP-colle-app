from flask import Blueprint, render_template, abort, url_for, jsonify
from flask_login import login_required, current_user
from models import User, UserPhoto
import qrcode, base64, io
from forstats import get_all_photos, get_user_photo_ids, compute_collection_stats

share_bp = Blueprint('share', __name__)

ALLOWED_GROUPS = {"nogizaka", "sakurazaka", "hinatazaka"}

@share_bp.route('/shared/<int:user_id>/<group_key>')
def shared_stats(user_id, group_key):

    if group_key not in ALLOWED_GROUPS:
        abort(404)

    user = User.query.get_or_404(user_id)

    if not getattr(user, f'is_{group_key}_shared', False):
        abort(403)

    all_photos = get_all_photos(group_key)
    owned = get_user_photo_ids(user.id, group_key)
    stats = compute_collection_stats(all_photos, owned)

    return render_template('shared_stats.html', user=user, stats=stats)


@share_bp.route('/share/<group_key>/<public_uuid>')
def shared_collection(group_key, public_uuid):

    if group_key not in ALLOWED_GROUPS:
        abort(404)

    user = User.query.filter_by(public_uuid=public_uuid).first_or_404()

    if not getattr(user, f'is_{group_key}_shared', False):
        return render_template("shared_collection/not_shared.html")

    photos = UserPhoto.query.filter_by(
        user_id=user.id,
        group_key=group_key
    ).all()

    return render_template(
        "shared_collection/shared_view.html",
        photocards=photos
    )


@share_bp.route('/qr_image/<group_key>')
@login_required
def qr_image(group_key):

    if group_key not in ALLOWED_GROUPS:
        abort(404)

    url = url_for(
        'share.shared_collection',
        group_key=group_key,
        public_uuid=current_user.public_uuid,
        _external=True
    )

    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)

    return jsonify({
        'qr_base64': base64.b64encode(buf.read()).decode()
    })