from flask import Flask, request,jsonify,redirect, url_for, request
from flask_login import current_user
from flask_migrate import Migrate
from flask_caching import Cache
from datetime import timedelta
import os, firebase_admin, json
from firebase_admin import credentials
from config import Config
from extensions import db, csrf, login_manager
from werkzeug.middleware.proxy_fix import ProxyFix
from models import User
from dotenv import load_dotenv
load_dotenv()

from routes.photo import photo_bp
from routes.stats import stats_bp
from routes.core import core_bp
from routes.share import share_bp
from routes.auth import auth_bp
from want import want_bp
from routes.user import user_bp
from trade.routes import trade_bp
from routes.billing import billing_bp
from routes.admin_photos import admin_photos_bp
from flask import render_template
from routes.public_catalog import public_catalog_bp

app = Flask(__name__)
app.permanent_session_lifetime = timedelta(minutes=60)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY")
app.config.from_object(Config)
app.config['WTF_CSRF_ENABLED'] = True

# Cookie設定（クロスドメイン対応）
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'

app.config['REMEMBER_COOKIE_SECURE'] = True
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SAMESITE'] = 'None'

db_url = os.environ.get("DATABASE_URL")

if db_url:
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    # 🔥 これ追加
    if "sslmode=" not in db_url:
        db_url += "?sslmode=require"

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "pool_size": 10,       # 同時接続の基本数
    "max_overflow": 20,    # 溢れた時の予備接続数
}

# Firebase init
cred_json = os.environ.get("FIREBASE_KEY_JSON")
cred_path = os.environ.get("FIREBASE_KEY_PATH")

if not firebase_admin._apps:
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    elif cred_path:
        cred = credentials.Certificate(cred_path)
    else:
        raise ValueError("Firebase credentials not set")

    firebase_admin.initialize_app(cred)

db.init_app(app)
migrate = Migrate(app, db)
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})
csrf.init_app(app)

login_manager.init_app(app)
login_manager.login_view = "auth.login"

@login_manager.user_loader
def load_user(user_id):
    if not user_id:
        return None
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
    
@login_manager.unauthorized_handler
def unauthorized():
    # API系（trade）はJSONで返す
    if request.path.startswith("/trade/"):
        return jsonify({
            "error": "login_required",
            "redirect": url_for("auth.login", next=request.url)
        }), 401

    # 通常ページはリダイレクト
    return redirect(url_for("auth.login", next=request.url))

# =========================
# Firebaseベース user取得（テンプレート・before_request）
# （@login_required はセッション上の Flask-Login と user_loader を使用）
# =========================
from firebase_admin import auth as firebase_auth

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

# =========================
# 🔥 context_processor 修正
# =========================
@app.context_processor
def inject_common():
    from flask import url_for

    # Prefer Flask-Login session user for normal page requests.
    user = current_user if current_user.is_authenticated else get_current_user()

    if user and user.icon_url:
        icon_url = user.icon_url
    else:
        icon_url = url_for('static', filename='images/default_icon.png')

    return dict(
        icon_url=icon_url
    )

@app.before_request
def enforce_group_and_plan():

    from flask import redirect, url_for

    # 🔥 追加（最重要）
    try:
        user = current_user
    except Exception:
        return

    # 🔒 除外
    if request.path.startswith((
        "/static",
        "/api/",
        "/stripe/webhook",
        "/finish-login"
    )):
        return

    if request.endpoint in [
        "user.force_group_select",
        "auth.login",
        "auth.logout"
    ]:
        return

    # ✅ ここから user を使う
    if not user.is_authenticated:
        return

    # ↓ 以下そのまま
    if not user.is_owner_account():
        selected = user.get_selected_groups() or []
        allowed = user.get_allowed_group_count()

        if len(selected) != allowed:
            return redirect(url_for("user.force_group_select"))

    group_key = request.view_args.get("group_key") if request.view_args else None

    if group_key and not user.can_access_group(group_key):
        return redirect(url_for("user.upgrade"))

from services.type_normalizer import normalize_type

@app.template_filter('normalize_type')
def normalize_type_filter(photo_type, member, costume):
    return normalize_type(member, costume, photo_type)

@app.route("/lp")
def lp():
    return render_template("lp.html")

app.register_blueprint(photo_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(core_bp)
app.register_blueprint(share_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(want_bp)
app.register_blueprint(user_bp)
app.register_blueprint(trade_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(admin_photos_bp)
app.register_blueprint(public_catalog_bp)

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")