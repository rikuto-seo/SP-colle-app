from flask import Blueprint, render_template, request, redirect, url_for, jsonify, current_app
from firebase_admin import auth as firebase_auth
from models import User
from extensions import db, csrf
from uuid import uuid4
import re
import os
import base64
from flask_login import login_user


auth_bp = Blueprint('auth', __name__)

def get_current_user():
    auth_header = request.headers.get('Authorization', '')

    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1].strip()

    try:
        decoded = firebase_auth.verify_id_token(token)
        uid = decoded['uid']
        return User.query.filter_by(firebase_uid=uid).first()
    except Exception:
        return None

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
    return redirect(url_for('auth.login'))

@auth_bp.route('/finish-login')
def finish_login():
    return render_template('finish-login.html')

@auth_bp.route('/api/create-user', methods=['POST'])
@csrf.exempt
def create_user():

    auth_header = request.headers.get('Authorization', '')

    if not auth_header.startswith("Bearer "):
        return jsonify({'error': 'Invalid Authorization header'}), 401

    token = auth_header.split(" ", 1)[1].strip()

    try:
        decoded_token = firebase_auth.verify_id_token(token)

        uid = decoded_token['uid']
        email = decoded_token.get('email')

        if email:
            email = email.lower()

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

    user = get_current_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401

    login_user(user, remember=True)

    is_setup_complete = bool(
        user.username and user.get_selected_groups()
    )

    return jsonify({
        'status': 'ok',
        'is_setup_complete': is_setup_complete
    })

@auth_bp.route('/api/setup/username', methods=['POST'])
@csrf.exempt
def setup_username():

    user = get_current_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()

    if not username:
        return jsonify({'error': 'ユーザー名を入力してください'}), 400

    if not re.match(r'^[\wぁ-んァ-ヶ一-龥ー\s.-]{1,20}$', username):
        return jsonify({'error': 'ユーザー名の形式が正しくありません'}), 400

    user.username = username
    db.session.commit()

    return jsonify({'status': 'ok'})

@auth_bp.route('/api/setup/icon', methods=['POST'])
@csrf.exempt
def setup_icon():

    user = get_current_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    image_data = data.get('image')

    if not image_data:
        return jsonify({'error': '画像データがありません'}), 400

    try:
        header, encoded = image_data.split(",", 1)
        binary = base64.b64decode(encoded)

        filename = f"{uuid4().hex}.png"
        save_path = os.path.join("static", "uploads", filename)

        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        with open(save_path, "wb") as f:
            f.write(binary)

        user.icon_url = f"/static/uploads/{filename}"
        db.session.commit()

        return jsonify({'status': 'ok', 'icon_url': user.icon_url})

    except Exception as e:
        current_app.logger.error(f"icon upload error: {e}", exc_info=True)
        return jsonify({'error': 'アップロード失敗'}), 500