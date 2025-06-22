from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import current_user, login_required
from models import User, Friendship, db

friend_bp = Blueprint("friend", __name__, url_prefix="/friends")

# ----------------------
# フレンド一覧表示（チャットON/OFF含む）
# ----------------------
@friend_bp.route("/")
@login_required
def friend_list():
    friendships = Friendship.query.filter_by(user_id=current_user.id, status='accepted').all()
    return render_template("friend_list.html", friends=friendships)

@friend_bp.route("/toggle_chat/<int:friend_id>", methods=["POST"])
@login_required
def toggle_chat(friend_id):
    friendship = Friendship.query.filter_by(user_id=current_user.id, friend_id=friend_id, status='accepted').first()
    if friendship:
        friendship.chat_enabled = not friendship.chat_enabled
        db.session.commit()
        flash("チャット設定を更新しました。", "info")
    return redirect(url_for("friend.friend_list"))

# ----------------------
# フレンド申請関連
# ----------------------
@friend_bp.route("/search")
@login_required
def user_directory():
    users = User.query.filter(User.id != current_user.id).all()

    for user in users:
        # 現ユーザーがこの user に送った申請
        sent = Friendship.query.filter_by(user_id=current_user.id, friend_id=user.id).first()
        # この user が現ユーザーに送った申請
        received = Friendship.query.filter_by(user_id=user.id, friend_id=current_user.id).first()

        if sent:
            user.friend_status = sent.status
        elif received and received.status == 'accepted':
            # 逆申請がすでに承認されていた場合
            user.friend_status = 'accepted'
        else:
            user.friend_status = None  # まだ申請なし

    return render_template("user_directory.html", users=users)

@friend_bp.route("/add/<int:user_id>", methods=["POST"])
@login_required
def add_friend(user_id):
    if user_id == current_user.id:
        flash("自分をフレンドに追加できません。", "warning")
        return redirect(url_for("friend.user_directory"))

    existing = Friendship.query.filter_by(user_id=current_user.id, friend_id=user_id).first()
    
    if existing:
        if existing.status == 'rejected':
            # 再申請可能：状態をpendingに戻す
            existing.status = 'pending'
            db.session.commit()
            flash("再度フレンド申請を送信しました。", "success")
        else:
            flash("すでに申請済み、またはフレンドです。", "info")
    else:
        new_request = Friendship(user_id=current_user.id, friend_id=user_id, status='pending')
        db.session.add(new_request)
        db.session.commit()
        flash("フレンド申請を送信しました。", "success")

    return redirect(url_for("friend.user_directory"))

@friend_bp.route("/requests")
@login_required
def friend_requests():
    requests = Friendship.query.filter_by(friend_id=current_user.id, status='pending').all()
    return render_template("friend_requests.html", requests=requests)

@friend_bp.route("/approve/<int:friendship_id>", methods=["POST"])
@login_required
def approve_friend(friendship_id):
    req = Friendship.query.get_or_404(friendship_id)
    if req.friend_id != current_user.id:
        flash("権限がありません。", "danger")
        return redirect(url_for("friend.friend_requests"))
    req.status = 'accepted'
    db.session.commit()
    flash("フレンド申請を承認しました。", "success")
    return redirect(url_for("friend.friend_requests"))

@friend_bp.route("/reject/<int:friendship_id>", methods=["POST"])
@login_required
def reject_friend(friendship_id):
    req = Friendship.query.get_or_404(friendship_id)
    if req.friend_id != current_user.id:
        flash("権限がありません。", "danger")
        return redirect(url_for("friend.friend_requests"))
    db.session.delete(req)
    db.session.commit()
    flash("フレンド申請を拒否しました。", "info")
    return redirect(url_for("friend.friend_requests"))

@friend_bp.route("/sent_requests")
@login_required
def sent_friend_requests():
    sent = Friendship.query.filter_by(user_id=current_user.id, status='pending').all()
    return render_template("sent_requests.html", requests=sent)
