# sakamichi_photo_app/want/routes.py
from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from extensions import db
from models import User,WantPhoto, UserPhoto, WantShare
from . import want_bp
from utils.qr import generate_qr_base64

@want_bp.route('/<group_key>')
@login_required
def index(group_key):
    wants = WantPhoto.query.filter_by(
        user_id=current_user.id,
        group_key=group_key
    ).all()

    qr_base64 = None
    public_url = None

    if current_user.is_want_shared(group_key):
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
    if request.method == 'POST':
        want = WantPhoto(
            user_id=current_user.id,
            group_key=group_key,
            member=request.form['member'],
            costume=request.form['costume'],
            photo_type=request.form['photo_type']
        )
        db.session.add(want)

        try:
            db.session.commit()
            flash('欲しい写真を追加しました')
        except Exception:
            db.session.rollback()
            flash('すでに登録されています')

        return redirect(url_for('want.index', group_key=group_key))

    # ✅ 正しい：Photoマスタから取得
    from models import Photo

    photos = Photo.query.filter_by(
        group_key=group_key
    ).all()

    members = sorted({p.member for p in photos})
    costumes = sorted({p.costume for p in photos})
    photo_types = sorted({p.photo_type for p in photos})


    members = sorted({p.member for p in photos})
    costumes = sorted({p.costume for p in photos})
    photo_types = sorted({p.photo_type for p in photos})

    return render_template(
        'want/add.html',
        group_key=group_key,
        members=members,
        costumes=costumes,
        photo_types=photo_types
    )

@want_bp.route('/get_types')
@login_required
def get_types():
    from models import Photo

    group_key = request.args.get('group')
    member = request.args.get('member')
    costume = request.args.get('costume')

    types = (
        db.session.query(Photo.photo_type)
        .filter_by(
            group_key=group_key,
            member=member,
            costume=costume
        )
        .distinct()
        .order_by(Photo.photo_type)
        .all()
    )

    return {
        'types': [t[0] for t in types]
    }

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
    # 公開用のユーザーを取得
    user = User.query.filter_by(public_uuid=public_uuid).first_or_404()

    # 公開設定がOFFなら404
    if not user.is_want_share_enabled(group_key):
        abort(404)

    # 欲しい写真リスト
    wants = WantPhoto.query.filter_by(
        user_id=user.id,
        group_key=group_key
    ).all()

    # 照合チェックフラグ
    is_check = (
        current_user.is_authenticated
        and request.args.get('check') == '1'
    )

    # 自分の所持写真との照合
    if is_check:
        owned_keys = {
            (p.member, p.costume, p.photo_type)
            for p in UserPhoto.query.filter_by(
                user_id=current_user.id,
                group_key=group_key
            ).all()
        }

        for want in wants:
            want.is_owned = (
                want.member,
                want.costume,
                want.photo_type
            ) in owned_keys

    # 統合テンプレートでレンダリング
    return render_template(
        'want/public_base.html',  # ← public.html ではなく統合版
        owner=user,
        wants=wants,
        group_key=group_key,
        uuid=public_uuid,
        is_check=is_check
    )

@want_bp.route('/share_setting/<group_key>', methods=['GET', 'POST'])
@login_required
def share_setting(group_key):
    share = WantShare.query.filter_by(
        user_id=current_user.id,
        group_key=group_key
    ).first()

    if not share:
        share = WantShare(
            user_id=current_user.id,
            group_key=group_key,
            is_public=False
        )
        db.session.add(share)
        db.session.commit()

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

@want_bp.route('/share_toggle/<group_key>', methods=['POST'])
@login_required
def toggle_want_share(group_key):
    current_user.toggle_want_share(group_key)
    db.session.commit()
    return redirect(url_for('want.index', group_key=group_key))
