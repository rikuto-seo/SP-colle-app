from flask import Blueprint, render_template, request, redirect, url_for, jsonify, current_app
from flask_login import login_user, current_user
from firebase_admin import auth as firebase_auth
from models import User
from extensions import db,csrf
from uuid import uuid4
import re,os,base64

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login')
def login():
    return render_template('login.html')

@auth_bp.route('/register')
def register():
    return render_template('register.html')

@auth_bp.route('/first-register')
def first_register():
    return render_template('first-register.html')

@auth_bp.route('/')
def home():
    if current_user.is_authenticated:

        groups = current_user.get_selected_groups()

        if not groups:
            return redirect(url_for('user.select_group'))

        current_user.normalize_groups()
        db.session.commit()

        group = current_user.primary_group or groups[0]

        return redirect(url_for('photo.index', group_key=group))

    return redirect(url_for('auth.login'))

@auth_bp.route('/api/setup/username', methods=['POST'])
@csrf.exempt
def setup_username():

    auth_header = request.headers.get('Authorization', '')

    if not auth_header.startswith("Bearer "):
        return jsonify({'error': 'Invalid Authorization header'}), 401

    token = auth_header.split(" ", 1)[1].strip()

    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()

    # バリデーション
    if not username:
        return jsonify({'error': 'ユーザー名を入力してください'}), 400

    if not re.match(r'^[\wぁ-んァ-ヶ一-龥ー\s.-]{1,20}$', username):
        return jsonify({'error': 'ユーザー名の形式が正しくありません'}), 400

    try:
        # Firebaseトークン検証
        decoded_token = firebase_auth.verify_id_token(token)
        uid = decoded_token['uid']

        user = User.query.filter_by(firebase_uid=uid).first()

        if not user:
            return jsonify({'error': 'ユーザーが存在しません'}), 404

        # ユーザー名更新
        user.username = username
        db.session.commit()

        return jsonify({'status': 'ok'})

    except firebase_auth.InvalidIdTokenError:
        return jsonify({'error': 'Invalid token'}), 401

    except firebase_auth.ExpiredIdTokenError:
        return jsonify({'error': 'Token expired'}), 401

    except Exception as e:
        current_app.logger.error(f"setup_username error: {e}", exc_info=True)
        return jsonify({'error': 'Server error'}), 500
    
@auth_bp.route('/api/setup/icon', methods=['POST'])
@csrf.exempt
def setup_icon():

    auth_header = request.headers.get('Authorization', '')

    if not auth_header.startswith("Bearer "):
        return jsonify({'error': 'Invalid Authorization header'}), 401

    token = auth_header.split(" ", 1)[1].strip()

    data = request.get_json(silent=True) or {}
    image_data = data.get('image')

    if not image_data:
        return jsonify({'error': '画像データがありません'}), 400

    try:
        # Firebase認証
        decoded_token = firebase_auth.verify_id_token(token)
        uid = decoded_token['uid']

        user = User.query.filter_by(firebase_uid=uid).first()

        if not user:
            return jsonify({'error': 'ユーザーが存在しません'}), 404

        # =========================
        # Base64 → 画像変換
        # =========================
        header, encoded = image_data.split(",", 1)
        binary = base64.b64decode(encoded)

        # 保存先
        filename = f"{uuid4().hex}.png"
        save_path = os.path.join("static", "uploads", filename)

        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        with open(save_path, "wb") as f:
            f.write(binary)

        # URL保存
        user.icon_url = f"/static/uploads/{filename}"
        db.session.commit()

        return jsonify({'status': 'ok', 'icon_url': user.icon_url})

    except Exception as e:
        current_app.logger.error(f"icon upload error: {e}", exc_info=True)
        return jsonify({'error': 'アップロード失敗'}), 500
    
@auth_bp.route('/api/create-user', methods=['POST'])
@csrf.exempt
def create_user():

    auth_header = request.headers.get('Authorization', '')

    if not auth_header.startswith("Bearer "):
        return jsonify({'error': 'Invalid Authorization header'}), 401

    token = auth_header.split(" ", 1)[1].strip()

    try:
        # Firebaseトークン検証
        decoded_token = firebase_auth.verify_id_token(token)

        uid = decoded_token['uid']
        email = decoded_token.get('email')

        # 既存ユーザー確認（冪等）
        user = User.query.filter_by(firebase_uid=uid).first()

        if not user:
            user = User(
                firebase_uid=uid,
                email=email,
                username=None,          # ← ここがポイント（未設定）
                primary_group=None,
            )

            user.set_selected_groups([])

            db.session.add(user)
            db.session.commit()

        # 🔐 ログイン状態にする
        login_user(user, remember=True)

        return jsonify({'status': 'ok'})

    except firebase_auth.InvalidIdTokenError:
        return jsonify({'error': 'Invalid token'}), 401

    except firebase_auth.ExpiredIdTokenError:
        return jsonify({'error': 'Token expired'}), 401

    except Exception as e:
        current_app.logger.error(f"create_user error: {e}", exc_info=True)
        return jsonify({'error': 'Server error'}), 500
    
@auth_bp.route('/api/me', methods=['POST'])
@csrf.exempt
def api_me():

    auth_header = request.headers.get('Authorization', '')

    if not auth_header.startswith("Bearer "):
        return jsonify({'error': 'Invalid Authorization header'}), 401

    token = auth_header.split(" ", 1)[1].strip()

    try:
        decoded_token = firebase_auth.verify_id_token(token)

        uid = decoded_token['uid']
        email = decoded_token.get('email')

        user = User.query.filter_by(firebase_uid=uid).first()

        if not user:
            user = User(
                firebase_uid=uid,
                email=email,
                username=None,
                primary_group=None,
            )
            user.set_selected_groups([])
            db.session.add(user)
            db.session.commit()

        login_user(user, remember=True)

        return jsonify({
            'status': 'ok',
            'is_setup_complete': bool(user.username and user.get_selected_groups())
        })

    except firebase_auth.InvalidIdTokenError:
        return jsonify({'error': 'Invalid token'}), 401

    except firebase_auth.ExpiredIdTokenError:
        return jsonify({'error': 'Token expired'}), 401

    except Exception as e:
        current_app.logger.error(f"Auth error: {e}", exc_info=True)
        return jsonify({'error': 'Authentication failed'}), 500
    
@auth_bp.route('/finish-login')
def finish_login():
    return render_template('finish-login.html')