from flask import Flask, session,request
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_caching import Cache
from datetime import timedelta
import os, firebase_admin,json
from firebase_admin import credentials
from config import Config
from extensions import db,csrf
from models import User
from dotenv import load_dotenv
load_dotenv()

# Blueprint
from routes.photo import photo_bp
from routes.stats import stats_bp
from routes.core import core_bp
from routes.share import share_bp
from routes.auth import auth_bp
from want import want_bp
from routes.user import user_bp
from trade.routes import trade_bp
from routes.billing import billing_bp

app = Flask(__name__)
app.permanent_session_lifetime = timedelta(minutes=60)

# config
db_url = os.environ.get("DATABASE_URL")

if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY")
app.config.from_object(Config)
app.config['WTF_CSRF_ENABLED'] = True

app.config['SESSION_COOKIE_SECURE'] = True
app.config['REMEMBER_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

cred_json = os.environ.get("FIREBASE_KEY_JSON")
cred_path = os.environ.get("FIREBASE_KEY_PATH")

if not firebase_admin._apps:
    if cred_json:
        # Render（本番）
        cred = credentials.Certificate(json.loads(cred_json))
    elif cred_path:
        # ローカル
        cred = credentials.Certificate(cred_path)
    else:
        raise ValueError("Firebase credentials not set")

    firebase_admin.initialize_app(cred, {
        'storageBucket': 'sakamichi-photo-app.appspot.app'
    })

# extensions
db.init_app(app)
migrate = Migrate(app, db)
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})

csrf.init_app(app)

# login
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# =========================
# セッション
# =========================
@app.before_request
def make_session_permanent():
    session.permanent = True


# =========================
# 共通注入
# =========================
@app.context_processor
def inject_common():
    from flask import request, url_for
    from flask_login import current_user

    if current_user.is_authenticated:
        icon_url = current_user.icon_url or url_for('static', filename='images/default_icon.png')
    else:
        icon_url = url_for('static', filename='images/default_icon.png')

    return dict(
        endpoint=request.endpoint,
        icon_url=icon_url
    )


# =========================
# 🔥 ダウングレード検知
# =========================
@app.before_request
def enforce_plan_limit():
    from flask_login import current_user
    from flask import redirect, url_for

    if not current_user.is_authenticated:
        return

    exempt = [
        'user.force_group_select',
        'user.upgrade',
        'auth.logout',
        'auth.login',
        'static',
        'billing.stripe_webhook',
        'billing.check_plan', 
        'user.payment_success',
    ]

    if request.endpoint in exempt:
        return

    selected = current_user.get_selected_groups()
    allowed = current_user.get_allowed_group_count()

    # 🔥 超過していたら強制選択
    if len(selected) > allowed:
        return redirect(url_for('user.force_group_select'))


# =========================
# 🔥 グループアクセス制御
# =========================
@app.before_request
def enforce_group_access():
    from flask_login import current_user
    from flask import request, redirect, url_for

    if not current_user.is_authenticated:
        return

    exempt = [
        'user.select_group',
        'user.force_group_select',
        'user.upgrade',
        'auth.logout',
        'auth.login',
        'static',
        'billing.stripe_webhook',
        'billing.check_plan', 
        'user.payment_success',
    ]

    if request.endpoint in exempt:
        return

    group_key = request.view_args.get('group_key') if request.view_args else None

    if not group_key:
        return

    if not current_user.can_access_group(group_key):
        return redirect(url_for('user.upgrade'))

print("DB URL:", db_url)

# Blueprint登録
app.register_blueprint(photo_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(core_bp)
app.register_blueprint(share_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(want_bp)
app.register_blueprint(user_bp)
app.register_blueprint(trade_bp)
app.register_blueprint(billing_bp)

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")