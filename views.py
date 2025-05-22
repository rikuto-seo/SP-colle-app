# app.py または views.py (Flaskのルート定義ファイル)

from flask import Flask, render_template, abort
from models import User, Photocard  # SQLAlchemyモデルを使う想定

app = Flask(__name__)

@app.route('/share/<username>')
def shared_collection_view(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        abort(404)  # ユーザーがいなければ404

    # 公開設定のチェック（例：is_nogizaka_sharedというBooleanカラムがUserモデルにある想定）
    if not user.is_nogizaka_shared:
        return render_template('shared_collection/not_shared.html', username=username)

    # 対象ユーザーのコレクションを取得
    photocards = Photocard.query.filter_by(owner_id=user.id, group='乃木坂46').all()

    return render_template('shared_collection/shared_view.html', username=username, photocards=photocards)
