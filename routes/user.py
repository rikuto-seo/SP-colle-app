from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort,make_response
from flask_login import login_required, current_user, logout_user
import os,io,qrcode,shutil,base64,time,stripe
from PIL import Image
from io import BytesIO
from extensions import db
from forms import IconUploadForm
from firebase_admin import auth as firebase_auth,storage
from models import WantShare
from datetime import datetime


stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
user_bp = Blueprint('user', __name__)

ALLOWED_GROUPS = ['nogizaka', 'sakurazaka', 'hinatazaka']

def is_free():
    return current_user.plan_type == "free"

def is_lite():
    return current_user.plan_type == "lite"

def is_standard():
    return current_user.plan_type == "standard"

def is_premium():
    return current_user.plan_type == "premium"

@user_bp.route("/mypage")
@login_required
def mypage():

    current_user.normalize_groups()
    db.session.commit()

    selected_groups = current_user.get_selected_groups()

    if not selected_groups:
        return redirect(url_for('user.select_group'))

    if len(selected_groups) > current_user.get_allowed_group_count():
        return redirect(url_for('user.force_group_select'))

    selected_group = request.args.get('group')
    if selected_group not in selected_groups:
        selected_group = selected_groups[0]

    next_billing = None
    cancel_at_period_end = False

    if current_user.stripe_subscription_id:
        try:
            sub = stripe.Subscription.retrieve(
                current_user.stripe_subscription_id
            )

            period_end = sub.get("current_period_end")

            if period_end:
                next_billing = datetime.fromtimestamp(period_end)

            cancel_at_period_end = sub.get("cancel_at_period_end", False)

        except Exception as e:
            current_app.logger.error(f"Stripe取得失敗: {e}")

    def make_qr(group_key):
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

        share_url = url_for(
            'share.shared_collection',
            group_key=group_key,
            public_uuid=share.public_uuid,
            _external=True
        )

        qr_img = qrcode.make(share_url)
        buf = io.BytesIO()
        qr_img.save(buf, format='PNG')
        buf.seek(0)

        return base64.b64encode(buf.read()).decode('utf-8')

    qr_codes = {}
    for g in selected_groups:
        share = WantShare.get_or_create(current_user.id, g)

        qr_codes[g] = make_qr(g) if share.is_public else ""

    share_statuses = {}
    for g in selected_groups:
        share = WantShare.query.filter_by(
            user_id=current_user.id,
            group_key=g
        ).first()

        share_statuses[g] = share.is_public if share else False

    if current_user.icon_url:
        icon_url = f"{current_user.icon_url}?v={int(time.time())}"
    else:
        icon_url = url_for('static', filename='images/default_icon.png')

    return render_template(
        "mypage.html",
        user=current_user,
        icon_url=icon_url,
        group_key=selected_group,
        qr_codes=qr_codes,
        share_statuses=share_statuses,
        selected_group=selected_group,
        selected_groups=selected_groups,
        next_billing=next_billing,
        cancel_at_period_end=cancel_at_period_end,

        is_free=is_free(),
        is_lite=is_lite(),
        is_standard=is_standard(),
        is_premium=is_premium()
    )

@user_bp.route('/mypage/icon', methods=['GET', 'POST'])
@login_required
def icon_setting():
    form = IconUploadForm()

    if request.method == 'POST':
        cropped_data = request.form.get('cropped_data')

        if not cropped_data:
            flash('画像がトリミングされていません。', 'warning')
            return redirect(request.url)

        try:
            header, encoded = cropped_data.split(',', 1)
            binary_data = base64.b64decode(encoded)

            image = Image.open(BytesIO(binary_data))

            if image.format not in ['PNG', 'JPEG']:
                raise ValueError("Invalid format")

            bucket = storage.bucket('sakamichi-photo-app.firebasestorage.app')

            filename = f'icons/{current_user.firebase_uid}_{int(time.time())}.png'
            blob = bucket.blob(filename)

            blob.upload_from_string(binary_data, content_type='image/png')
            blob.make_public()

            new_icon_url = blob.public_url

            if current_user.icon_url:
                try:
                    old_path = current_user.icon_url.split('.com/')[1]
                    old_blob = bucket.blob(old_path)
                    if old_blob.exists():
                        old_blob.delete()
                except Exception as e:
                    current_app.logger.warning(f"旧アイコン削除失敗: {e}")

            current_user.icon_url = new_icon_url
            db.session.commit()

            flash('アイコンを更新しました。', 'success')
            return redirect(url_for('user.mypage'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"[アイコン更新エラー] {e}")
            flash('画像の処理に失敗しました。', 'danger')

    return render_template('icon_setting.html', form=form)

@user_bp.route('/mypage/icon/delete', methods=['POST'])
@login_required
def delete_icon():
    try:
        bucket = storage.bucket('sakamichi-photo-app.firebasestorage.app')

        if current_user.icon_url:
            path = current_user.icon_url.split('.com/')[1]
            blob = bucket.blob(path)

            if blob.exists():
                blob.delete()

        current_user.icon_url = None
        db.session.commit()

        flash('アイコンを削除しました。', 'info')

    except Exception as e:
        current_app.logger.error(f"アイコン削除失敗: {e}")
        flash('削除に失敗しました。', 'danger')

    return redirect(url_for('user.icon_setting'))

@user_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if new_password != confirm_password:
            flash('新しいパスワードと確認用パスワードが一致しません。', 'danger')
            return redirect(url_for('user.change_password'))

        try:
            firebase_auth.update_user(
                uid=current_user.firebase_uid,
                password=new_password
            )
            flash('パスワードを変更しました。', 'success')
            return redirect(url_for('user.mypage'))
        except Exception as e:
            current_app.logger.error(f"[パスワード変更エラー] {e}")
            flash('パスワードの変更に失敗しました。', 'danger')

    return render_template('change_password.html')

@user_bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    from flask_wtf import FlaskForm
    form = FlaskForm()

    if request.method == 'POST':
        new_name = request.form.get('username', '').strip()
        twitter_id = request.form.get('twitter_id', '').strip()
        instagram_id = request.form.get('instagram_id', '').strip()

        try:
            if new_name:
                firebase_auth.update_user(
                    current_user.firebase_uid,
                    display_name=new_name
                )
                current_user.username = new_name

            if twitter_id != '':
                current_user.twitter_id = twitter_id.replace('@', '')

            if instagram_id != '':
                current_user.instagram_id = instagram_id

            db.session.commit()
            flash('プロフィールを更新しました！', 'success')
            return redirect(url_for('user.mypage'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Profile update error: {e}")
            flash('更新に失敗しました。', 'danger')
            return redirect(url_for('user.edit_profile'))

    return render_template('edit_profile.html', user=current_user, form=form)

@user_bp.route('/confirm_delete_account', methods=['GET', 'POST'])
@login_required
def confirm_delete_account():
    if request.method == 'POST':
        return redirect(url_for('user.confirm_delete_final'))
    return render_template('confirm_delete_account.html')

@user_bp.route('/confirm_delete_final', methods=['GET', 'POST'])
@login_required
def confirm_delete_final():
    if request.method == 'POST':
        user_folder = os.path.join(
            current_app.root_path, 'static', 'uploads', 'icons', f'user_{current_user.firebase_uid}'
        )
        try:
            firebase_auth.delete_user(current_user.firebase_uid)

            if os.path.exists(user_folder):
                shutil.rmtree(user_folder)

            if current_user.stripe_subscription_id:
                try:
                    stripe.Subscription.delete(current_user.stripe_subscription_id)
                except Exception as e:
                    current_app.logger.error(f"Stripe解約失敗: {e}")

            db.session.delete(current_user)
            db.session.commit()

            logout_user()
            flash('アカウントを完全に削除しました。', 'success')
            return redirect(url_for('photo.index'))
        except Exception as e:
            current_app.logger.error(f"[アカウント削除エラー] {e}")
            flash('削除中にエラーが発生しました。', 'danger')

    return render_template('confirm_delete_final.html')

@user_bp.route('/toggle_share/<group_key>', methods=['POST'])
@login_required
def toggle_share(group_key):

    if group_key not in ALLOWED_GROUPS:
        abort(404)

    selected_groups = current_user.get_selected_groups()
    if group_key not in selected_groups:
        abort(403)

    if len(selected_groups) > current_user.get_allowed_group_count():
        abort(403)

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

    share.is_public = not share.is_public

    db.session.add(share)
    db.session.commit()

    return redirect(url_for('user.mypage', group=group_key))

@user_bp.route('/toggle_dark_mode', methods=['POST'])
@login_required
def toggle_dark_mode():
    current_user.dark_mode = not current_user.dark_mode
    db.session.commit()
    return redirect(request.referrer or url_for('user.mypage'))

@user_bp.route('/upgrade')
@login_required
def upgrade():
    return render_template(
        'upgrade.html',
        current_plan=current_user.plan_type
    )

@user_bp.route("/payment-success")
def payment_success():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    res = make_response(render_template("payment_success.html"))

    res.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    res.headers["Pragma"] = "no-cache"
    res.headers["Expires"] = "0"

    return res

@user_bp.route('/select-group', methods=['GET', 'POST'])
@login_required
def select_group():

    if current_user.primary_group:
        return redirect(url_for('photo.index', group_key=current_user.primary_group))

    if request.method == 'POST':
        group = request.form.get('group')

        if group not in ALLOWED_GROUPS:
            abort(400)

        current_user.set_selected_groups([group])
        current_user.normalize_groups()

        db.session.commit()

        return redirect(url_for('photo.index', group_key=group))

    return render_template('select_group.html', force_select_mode=True)

@user_bp.route("/force-select-group", methods=["GET", "POST"])
@login_required
def force_group_select():

    allowed = current_user.get_allowed_group_count()
    current_selected = current_user.get_selected_groups()

    if len(current_selected) == allowed:
        return redirect(url_for("user.mypage"))

    if request.method == "POST":
        selected = request.form.getlist("groups")

        if not all(g in ALLOWED_GROUPS for g in selected):
            abort(400)

        if len(selected) != allowed:
            flash(f"{allowed}グループ必ず選択してください", "danger")
            return redirect(url_for("user.force_group_select"))

        current_user.set_selected_groups(selected)
        current_user.normalize_groups()
        db.session.commit()

        return redirect(url_for("photo.index", group_key=selected[0]))

    return render_template(
        "force_select_group.html",
        allowed=allowed,
        current_selected=current_selected
    )

@user_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))