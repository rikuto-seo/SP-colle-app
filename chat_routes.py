from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user, login_required
from models import User, Message, db
from sqlalchemy.orm import joinedload
from forms import ChatForm

chat_bp = Blueprint('chat', __name__, url_prefix='/chat')

@chat_bp.route('/<int:user_id>', methods=['GET', 'POST'])
@login_required
def chat_with(user_id):
    other_user = User.query.get_or_404(user_id)
    form = ChatForm()  # フォーム生成

    if form.validate_on_submit():  # CSRFチェックを含むフォーム検証
        content = form.content.data.strip()
        if content:
            msg = Message(sender_id=current_user.id, receiver_id=other_user.id, content=content)
            db.session.add(msg)
            db.session.commit()
            return redirect(url_for('chat.chat_with', user_id=user_id))
        else:
            flash('メッセージを入力してください。')

    # メッセージを送信者をjoinedloadで一緒に読み込み
    messages = Message.query.options(
        joinedload(Message.sender)
    ).filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == other_user.id)) |
        ((Message.sender_id == other_user.id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()

    return render_template('chat_room.html', other_user=other_user, messages=messages, form=form)

@chat_bp.route('/', methods=['GET'])
@login_required
def chat_list():
    # 自分がメッセージ送信or受信した相手ユーザーを抽出する例
    user_id = current_user.id

    # メッセージの送信者または受信者が自分のユーザーIDであるメッセージを全取得
    messages = Message.query.filter(
        (Message.sender_id == user_id) | (Message.receiver_id == user_id)
    ).order_by(Message.timestamp.desc()).all()

    # 相手ユーザーIDの集合を作る（重複排除）
    user_ids = set()
    for msg in messages:
        if msg.sender_id != user_id:
            user_ids.add(msg.sender_id)
        if msg.receiver_id != user_id:
            user_ids.add(msg.receiver_id)

    # Userオブジェクトを取得
    chat_partners = User.query.filter(User.id.in_(user_ids)).all()

    return render_template('chat_list.html', chat_partners=chat_partners)
