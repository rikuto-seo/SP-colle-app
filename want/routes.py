from flask import render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
import io, base64, qrcode
from sqlalchemy import exists
from extensions import db
from models import (
    User, WantPhoto, UserPhoto, WantShare,
    Photo, Member, Costume, PhotoType, Group
)
from . import want_bp
from utils.qr import generate_qr_base64

# photo側のサービス等がある場合はそれを利用するのも手ですが、ここでは単体で完結させます
ALLOWED_GROUPS = {"nogizaka", "sakurazaka", "hinatazaka"}

# =========================
# index (表示用)
# =========================
@want_bp.route('/<group_key>')
@login_required
def index(group_key):
    if group_key not in ALLOWED_GROUPS:
        abort(404)

    group = Group.query.filter_by(key=group_key).first_or_404()

    # JOINを明示してグループに属する欲しいものだけ取得
    wants = (
        db.session.query(WantPhoto)
        .join(Photo)
        .join(Member)
        .filter(
            WantPhoto.user_id == current_user.id,
            Member.group_id == group.id
        )
        .all()
    )

    share = WantShare.get_or_create(current_user.id, group_key)
    public_url = None
    qr_base64 = None

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


# =========================
# add (追加処理)
# =========================
@want_bp.route('/<group_key>/add', methods=['GET', 'POST'])
@login_required
def add_want(group_key):
    group = Group.query.filter_by(key=group_key).first_or_404()

    if request.method == 'POST':
        member_name = request.form.get('member')
        costume_name = request.form.get('costume')
        type_name = request.form.get('photo_type')
        is_infinite = request.form.get('is_infinite') == '1'

        if not all([member_name, costume_name, type_name]):
            flash('すべての項目を選択してください', 'error')
            return redirect(url_for('want.add_want', group_key=group_key))

        # 対象のPhotoレコードを特定
        photo = (
            db.session.query(Photo)
            .join(Member)
            .join(Costume)
            .join(PhotoType)
            .filter(
                Member.name == member_name,
                Costume.name == costume_name,
                PhotoType.name == type_name,
                Member.group_id == group.id
            )
            .first()
        )

        if not photo:
            flash('該当する写真が見つかりません', 'error')
            return redirect(url_for('want.add_want', group_key=group_key))

        # 重複チェック
        existing = WantPhoto.query.filter_by(
            user_id=current_user.id,
            photo_id=photo.id
        ).first()

        if existing:
            # すでに登録されている場合は設定だけ更新するか、何もしない
            existing.is_infinite = is_infinite
            flash('登録済みの内容を更新しました')
        else:
            new_want = WantPhoto(
                user_id=current_user.id,
                photo_id=photo.id,
                is_infinite=is_infinite
            )
            db.session.add(new_want)
            flash('欲しい写真を追加しました', 'success')

        db.session.commit()
        return redirect(url_for('want.index', group_key=group_key))

    # GET: 選択肢の表示用データ
    # photo側と同様にそのグループのデータのみ抽出
    members = (
        Member.query.filter_by(group_id=group.id)
        .order_by(Member.generation, Member.display_order)
        .all()
    )
    
    # 衣装もそのグループに紐づくものだけ
    costumes = (
        Costume.query.filter_by(group_id=group.id)
        .order_by(Costume.name)
        .all()
    )

    return render_template(
        'want/add.html',
        group_key=group_key,
        members=[m.name for m in members],
        costumes=[c.name for c in costumes]
    )

# =========================
# API: 選択肢の動的取得 (AJAX用)
# =========================
@want_bp.route('/get_types')
@login_required
def get_types():
    group_key = request.args.get('group')
    member_name = request.args.get('member')
    costume_name = request.args.get('costume')

    group = Group.query.filter_by(key=group_key).first()
    if not group:
        return jsonify({'types': []})

    # 特定のメンバー・衣装に紐づくタイプのみを抽出
    types = (
        db.session.query(PhotoType.name)
        .join(Photo)
        .join(Member)
        .join(Costume)
        .filter(
            Member.name == member_name,
            Costume.name == costume_name,
            Member.group_id == group.id
        )
        .distinct()
        .order_by(PhotoType.name)
        .all()
    )

    return jsonify({'types': [t[0] for t in types]})

# =========================
# delete
# =========================
@want_bp.route('/delete/<int:want_id>', methods=['POST'])
@login_required
def delete_want(want_id):

    want = WantPhoto.query.filter_by(
        id=want_id,
        user_id=current_user.id
    ).first_or_404()

    db.session.delete(want)
    db.session.commit()

    return redirect(request.referrer or url_for('want.index', group_key="nogizaka"))


# =========================
# public share
# =========================
@want_bp.route('/share/<public_uuid>/<group_key>')
def public_want(public_uuid, group_key):

    if group_key not in ALLOWED_GROUPS:
        abort(404)

    user = User.query.filter_by(public_uuid=public_uuid).first_or_404()
    group = Group.query.filter_by(key=group_key).first_or_404()

    if not user.is_want_share_enabled(group_key):
        return render_template(
            'want/public_private.html',
            owner=user,
            group_key=group_key
        )

    viewer_id = current_user.id if current_user.is_authenticated else None

    wants = (
        db.session.query(
            WantPhoto,
            exists().where(
                (UserPhoto.user_id == viewer_id) &
                (UserPhoto.photo_id == WantPhoto.photo_id)
            ).label("is_owned")
        )
        .join(Photo)
        .join(Member)
        .filter(
            WantPhoto.user_id == user.id,
            Member.group_id == group.id
        )
        .all()
    )

    result = []
    for w, owned in wants:
        result.append({
            "want": w,
            "is_owned": False if w.is_infinite else bool(owned)
        })

    return render_template(
        'want/public_base.html',
        owner=user,
        wants=result,
        group_key=group_key,
        uuid=public_uuid,
        is_check=(viewer_id is not None)
    )


# =========================
# redirect
# =========================
@want_bp.route('/share_redirect/<group_key>')
def public_want_redirect(group_key):

    if group_key not in ALLOWED_GROUPS:
        abort(404)

    public_uuid = request.args.get('uuid')

    if not public_uuid:
        return redirect(url_for('photo.index', group_key=group_key))

    return redirect(url_for(
        'want.public_want',
        public_uuid=public_uuid,
        group_key=group_key
    ))


# =========================
# share setting
# =========================
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


# =========================
# QR
# =========================
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


# =========================
# toggle
# =========================
@want_bp.route('/share_toggle/<group_key>', methods=['POST'])
@login_required
def toggle_want_share(group_key):

    share = WantShare.get_or_create(current_user.id, group_key)
    share.is_public = not share.is_public
    db.session.commit()

    return redirect(url_for('want.index', group_key=group_key))