# sakamichi_photo_app/want/routes.py
from flask import render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
import io, base64, qrcode
from extensions import db
from models import User, WantPhoto, UserPhoto, WantShare
from . import want_bp
from utils.qr import generate_qr_base64

ALLOWED_GROUPS = {"nogizaka", "sakurazaka", "hinatazaka"}

def normalize(v):
    return v if v not in ("", None) else None

@want_bp.route('/<group_key>')
@login_required
def index(group_key):

    if group_key not in ALLOWED_GROUPS:
        abort(404)

    wants = WantPhoto.query.filter_by(
        user_id=current_user.id,
        group_key=group_key
    ).all()

    share = WantShare.get_or_create(current_user.id, group_key)

    qr_base64 = None
    public_url = None

    if share.is_public:
        public_url = url_for(
            'want.public_want',
            public_uuid=current_user.public_uuid,
            group_key=group_key,
            _external=True
        )
        qr_base64 = generate_qr_base64(public_url)

    return render_template(
        'want/index.html',
        group_key=group_key,
        wants=wants,
        public_url=public_url,
        qr_base64=qr_base64
    )


@want_bp.route('/<group_key>/add', methods=['GET', 'POST'])
@login_required
def add_want(group_key):

    if group_key not in ALLOWED_GROUPS:
        abort(404)

    if request.method == 'POST':

        member = normalize(request.form.get("member"))
        costume = normalize(request.form.get("costume"))
        photo_type = normalize(request.form.get("photo_type"))
        is_infinite = bool(request.form.get("is_infinite"))

        want = WantPhoto(
            user_id=current_user.id,
            group_key=group_key,
            member=member,
            costume=costume,
            photo_type=photo_type,
            is_infinite=is_infinite
        )

        db.session.add(want)

        try:
            db.session.commit()
            flash('欲しい写真を追加しました')
        except Exception:
            db.session.rollback()
            flash('すでに登録されています')

        return redirect(url_for('want.index', group_key=group_key))

    return render_template(
        'want/add.html',
        group_key=group_key
    )

@want_bp.route('/get_members')
@login_required
def get_members():
    from models import Photo

    group_key = request.args.get('group')

    members = (
        db.session.query(Photo.member)
        .filter_by(group_key=group_key)
        .distinct()
        .order_by(Photo.member)
        .all()
    )

    return jsonify({'members': [m[0] for m in members]})

@want_bp.route('/get_costumes')
@login_required
def get_costumes():
    from models import Photo

    group_key = request.args.get('group')
    member = request.args.get('member')

    query = db.session.query(Photo.costume).filter_by(group_key=group_key)

    if member:
        query = query.filter_by(member=member)

    costumes = query.distinct().order_by(Photo.costume).all()

    return jsonify({'costumes': [c[0] for c in costumes]})

@want_bp.route('/get_types')
@login_required
def get_types():
    from models import Photo

    group_key = request.args.get('group')
    member = request.args.get('member')
    costume = request.args.get('costume')

    query = db.session.query(Photo.photo_type).filter_by(group_key=group_key)

    if member:
        query = query.filter_by(member=member)

    if costume:
        query = query.filter_by(costume=costume)

    types = query.distinct().order_by(Photo.photo_type).all()

    return jsonify({'types': [t[0] for t in types]})

@want_bp.route('/delete/<int:want_id>', methods=['POST'])
@login_required
def delete_want(want_id):
    want = WantPhoto.query.filter_by(
        id=want_id,
        user_id=current_user.id
    ).first_or_404()

    group_key = want.group_key

    db.session.delete(want)
    db.session.commit()

    return redirect(url_for('want.index', group_key=group_key))

@want_bp.route('/share/<public_uuid>/<group_key>')
def public_want(public_uuid, group_key):

    if group_key not in ALLOWED_GROUPS:
        abort(404)

    user = User.query.filter_by(public_uuid=public_uuid).first_or_404()

    if not user.is_want_share_enabled(group_key):
        abort(404)

    wants = WantPhoto.query.filter_by(
        user_id=user.id,
        group_key=group_key
    ).all()

    # 初期化
    for w in wants:
        w.is_owned = False

    is_check = (
        current_user.is_authenticated
        and request.args.get('check') == '1'
    )

    if is_check:
        my_photos = UserPhoto.query.filter_by(
            user_id=current_user.id,
            group_key=group_key
        ).all()

        def is_match(want, photo):
            if want.member and want.member != photo.member:
                return False
            if want.costume and want.costume != photo.costume:
                return False
            if want.photo_type and want.photo_type != photo.photo_type:
                return False
            return True

        for want in wants:
            want.is_owned = any(is_match(want, p) for p in my_photos)

    return render_template(
        'want/public_base.html',
        owner=user,
        wants=wants,
        group_key=group_key,
        uuid=public_uuid,
        is_check=is_check
    )

@want_bp.route('/share_setting/<group_key>', methods=['GET', 'POST'])
@login_required
def share_setting(group_key):

    share = WantShare.get_or_create(current_user.id, group_key)

    if request.method == 'POST':
        share.is_public = not share.is_public
        db.session.commit()
        flash('公開設定を更新しました')

        return redirect(url_for('want.share_setting', group_key=group_key))

    return render_template(
        'want/share_setting.html',
        group_key=group_key,
        share=share
    )

@want_bp.route('/qr_image/<group_key>')
@login_required
def want_qr_image(group_key):

    url = url_for(
        'want.public_want',
        public_uuid=current_user.public_uuid,
        group_key=group_key,
        _external=True
    )

    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)

    return {
        'qr_base64': base64.b64encode(buf.read()).decode()
    }

@want_bp.route('/share_toggle/<group_key>', methods=['POST'])
@login_required
def toggle_want_share(group_key):
    share = WantShare.get_or_create(current_user.id, group_key)
    share.is_public = not share.is_public
    db.session.commit()
    return redirect(url_for('want.index', group_key=group_key))