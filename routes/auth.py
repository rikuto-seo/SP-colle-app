from flask import Blueprint, render_template, request, redirect, url_for, jsonify, current_app
from flask_login import login_user, current_user
from firebase_admin import auth as firebase_auth
from models import User
from extensions import db,csrf
import re

auth_bp = Blueprint('auth', __name__)

# =========================
# Pages
# =========================

@auth_bp.route('/login')
def login():
    return render_template('login.html')


@auth_bp.route('/register')
def register():
    return render_template('register.html')


# =========================
# 🔥 ホーム（最重要修正）
# =========================
@auth_bp.route('/')
def home():
    if current_user.is_authenticated:

        groups = current_user.get_selected_groups()

        # 🔥 未設定 → 初期選択へ
        if not groups:
            return redirect(url_for('user.select_group'))

        # 🔥 念のため整合性維持
        current_user.normalize_groups()
        db.session.commit()

        # 🔥 primary_group優先
        group = current_user.primary_group or groups[0]

        return redirect(url_for('photo.index', group_key=group))

    return redirect(url_for('auth.login'))


# =========================
# 🔥 API 認証
# =========================
@auth_bp.route('/api/me', methods=['POST'])
@csrf.exempt
def api_me():

    # -------------------------
    # 1. Authorization header
    # -------------------------
    auth_header = request.headers.get('Authorization', '')

    if not auth_header.startswith("Bearer "):
        return jsonify({'error': 'Invalid or missing Authorization header'}), 401

    token = auth_header.split(" ", 1)[1].strip()

    if not token:
        return jsonify({'error': 'Empty token'}), 401

    # -------------------------
    # 2. JSON safely取得
    # -------------------------
    data = request.get_json(silent=True) or {}
    passed_username = data.get('username')

    # -------------------------
    # 3. username validation
    # -------------------------
    if passed_username:
        if not re.match(r'^[\wぁ-んァ-ヶ一-龥ー\s.-]{1,20}$', passed_username):
            return jsonify({'error': 'Invalid username'}), 400

    try:
        # -------------------------
        # 4. Firebase token verify
        # -------------------------
        decoded_token = firebase_auth.verify_id_token(token)

        uid = decoded_token['uid']
        email = decoded_token.get('email')
        email_prefix = email.split('@')[0] if email else "user"

        # -------------------------
        # 5. DB lookup
        # -------------------------
        user = User.query.filter_by(firebase_uid=uid).first()

        # -------------------------
        # 6. 新規ユーザー作成
        # -------------------------
        if not user:
            user = User(
                firebase_uid=uid,
                email=email,
                username=passed_username or email_prefix
            )

            # 🔥 初期状態（超重要）
            user.set_selected_groups([])   # 空スタート
            user.primary_group = None

            db.session.add(user)
            db.session.commit()

        # -------------------------
        # 7. username更新
        # -------------------------
        elif passed_username:
            user.username = passed_username
            db.session.commit()

        # -------------------------
        # 🔥 8. 整合性チェック（重要）
        # -------------------------
        user.normalize_groups()
        db.session.commit()

        # -------------------------
        # 9. ログイン
        # -------------------------
        login_user(user, remember=True)

        return jsonify({'status': 'ok'})

    except firebase_auth.InvalidIdTokenError:
        return jsonify({'error': 'Invalid token'}), 401

    except firebase_auth.ExpiredIdTokenError:
        return jsonify({'error': 'Token expired'}), 401

    except Exception as e:
        current_app.logger.error(f"Auth error: {e}", exc_info=True)
        return jsonify({'error': 'Authentication failed'}), 500