import os, bcrypt, csv,io,random,base64,shutil,re,logging
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, current_app, abort, send_file,Blueprint
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from models import db, Photo, User, UserPhoto, Message,Friendship
from config import Config
from collections import defaultdict
from itertools import groupby
from operator import attrgetter
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.orm import joinedload
from datetime import datetime
from sqlalchemy.exc import IntegrityError
import qrcode
from io import BytesIO
from utils import (
    get_costumes_for_member,
    load_photos_from_csv,
    build_image_path,
    get_all_photos,
    get_user_photo_ids,
    compute_collection_stats
)
from datetime import timedelta
from forms import IconUploadForm,LoginForm,AddPhotoForm
from PIL import Image
from chat_routes import chat_bp
from friend import friend_bp
from sqlalchemy import or_

app = Flask(__name__)
app.permanent_session_lifetime = timedelta(minutes=10)

app.register_blueprint(chat_bp)
# アプリ作成後にBlueprint登録
app.register_blueprint(friend_bp)

# コンフィグ設定
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL") or 'sqlite:///instance/main.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'koito-annbata'
app.config.from_object(Config)
app.config['WTF_CSRF_ENABLED'] = False

# Cache設定（シンプルなメモリキャッシュ）
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})

# DBと連携
db.init_app(app)
migrate = Migrate(app, db)

# ログインマネージャー
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)


# DB作成とサンプルユーザー作成
with app.app_context():
    db.create_all()
    #if not User.query.filter_by(username='testuser').first():
     #   user = User(username='testuser')
      #  user.set_password('testpassword')
       # db.session.add(user)
        #db.session.commit()

@app.context_processor
def inject_endpoint():
    from flask import request
    return dict(endpoint=request.endpoint)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/group/<group_key>')
def group(group_key):
    info = {
        'nogizaka': {'name': '乃木坂46', 'color': '#800080', 'description': '清楚で可憐な乃木坂46。', 'image': 'nogizaka_banner.jpg'},
        'sakurazaka': {'name': '櫻坂46', 'color': '#FF69B4', 'description': '強さと儚さを併せ持つ櫻坂46。', 'image': 'sakurazaka_banner.jpg'},
        'hinatazaka': {'name': '日向坂46', 'color': '#87CEFA', 'description': '笑顔とハッピーオーラの日向坂46！', 'image': 'hinatazaka_banner.jpg'}
    }
    if group_key not in info:
        return 'グループが見つかりません', 404
    return render_template('group.html',endpoint=request.endpoint, group_key=group_key, **info[group_key], image_url=url_for('static', filename=f'images/{info[group_key]["image"]}'))

@app.route('/stats/<group_key>')
@login_required
def stats(group_key):
    group_key = group_key.strip().lower()

    group_colors = {
        'nogizaka': 'bg-nogizaka',
        'sakurazaka': 'bg-sakurazaka',
        'hinatazaka': 'bg-hinatazaka'
    }

    if group_key not in group_colors:
        return "不正なグループキーです", 404

    group_color = group_colors[group_key]

    # ✅ 共有状態を取得
    share_status_map = {
        'nogizaka': current_user.is_nogizaka_shared,
        'sakurazaka': current_user.is_sakurazaka_shared,
        'hinatazaka': current_user.is_hinatazaka_shared
    }
    is_shared = share_status_map[group_key]

    all_photos = load_photos_from_csv(group_key)
    if not all_photos:
        return "グループのデータが見つかりません", 404

    owned = set(
        (p.member.strip(), p.costume.strip(), p.photo_type.strip())
        for p in UserPhoto.query.filter_by(user_id=current_user.id, group_key=group_key).all()
    )

    print("[DEBUG] 所持しているUserPhoto:")
    for photo in UserPhoto.query.filter_by(user_id=current_user.id, group_key=group_key).all():
        print(f"member='{photo.member}' costume='{photo.costume}' type='{photo.photo_type}'")

    all_costumes = set(p.costume.strip() for p in all_photos)
    costume_stats = {costume: {'owned': 0, 'total': 0} for costume in all_costumes}

    member_stats = defaultdict(int)
    type_stats = defaultdict(int)

    # ✅ コンプ集計用：メンバー×衣装で種類を集める
    costume_dict = defaultdict(lambda: defaultdict(set))
    owned_dict = defaultdict(lambda: defaultdict(set))

    for p in all_photos:
        member = p.member.strip()
        costume = p.costume.strip()
        photo_type = p.photo_type.strip()

        costume_dict[member][costume].add(photo_type)
        if (member, costume, photo_type) in owned:
            owned_dict[member][costume].add(photo_type)
            member_stats[member] += 1
            type_stats[photo_type] += 1
            costume_stats[costume]['owned'] += 1
        costume_stats[costume]['total'] += 1

    # ✅ comp_stats を構築
    comp_stats = {}
    for member, costumes in costume_dict.items():
        comp_stats[member] = []
        for costume, types in sorted(costumes.items()):
            total = len(types)
            owned_types = owned_dict[member][costume]
            owned = len(owned_types)
            comp_stats[member].append({
                'costume': costume,
                'owned': owned,
                'total': total,
                'is_complete': owned == total
            })

    # 🔃 衣装別進捗
    progress = sorted([
        {
            'costume': c,
            'owned': d['owned'],
            'total': d['total'],
            'rate': d['owned'] / d['total'] * 100 if d['total'] else 0
        }
        for c, d in costume_stats.items()
    ], key=lambda x: x['costume'])

    # ✅ comp_ranking を構築
    comp_ranking_list = []
    for member, costumes in comp_stats.items():
        complete_count = sum(1 for item in costumes if item['is_complete'])
        comp_ranking_list.append({
            'member': member,
            'complete_count': complete_count
        })

    comp_ranking = sorted(comp_ranking_list, key=lambda x: x['complete_count'], reverse=True)

    if group_key == 'nogizaka':
        is_shared = current_user.is_nogizaka_shared
    elif group_key == 'sakurazaka':
        is_shared = current_user.is_sakurazaka_shared
    elif group_key == 'hinatazaka':
        is_shared = current_user.is_hinatazaka_shared
    else:
        is_shared = False

    return render_template(
        'stats.html',
        endpoint=request.endpoint,
        group_key=group_key,
        group_name={'nogizaka': '乃木坂46', 'sakurazaka': '櫻坂46', 'hinatazaka': '日向坂46'}[group_key],
        member_stats=sorted(member_stats.items()),
        type_stats=sorted(type_stats.items()),
        progress_list=progress,
        comp_stats=comp_stats,
        comp_ranking=comp_ranking,
        group_color=group_colors,
        is_shared=is_shared  # ✅ 追加ポイント
    )

@app.route('/get_members')
def get_members():
    group = request.args.get('group')
    folder = os.path.join('members_csv', group)
    return jsonify({'members': [f.replace('.csv', '') for f in os.listdir(folder) if f.endswith('.csv')]})

@app.route('/get_costumes')
def get_costumes():
    group = request.args.get('group')
    member = request.args.get('member')
    return jsonify({'costumes': get_costumes_for_member(group, member)})

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()

        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            return redirect(url_for('index', group_key='nogizaka'))

        flash('ユーザー名またはパスワードが間違っています。', 'error')
        # フラッシュメッセージ表示のためGETにリダイレクトせずに、フォーム再表示へ
        # return redirect(url_for('login')) ではなくこのままrender_templateに行く
    return render_template('login.html', form=form)

@app.route('/<group_key>/dashboard')
def dashboard(group_key):
    group_names = {
        'nogizaka': '乃木坂46',
        'sakurazaka': '櫻坂46',
        'hinatazaka': '日向坂46'
    }
    group_name = group_names.get(group_key, 'グループ不明')
    return render_template('dashboard.html',endpoint=request.endpoint, group_key=group_key, group_name=group_name)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('そのユーザー名はすでに使われています', 'error')
            return redirect(url_for('register'))

        # ✅ パスワード強度チェック
        if len(password) < 6:
            flash('パスワードは6文字以上にしてください。', 'error')
            return redirect(url_for('register'))
        if not re.search(r"[A-Za-z]", password):
            flash('パスワードには英字を含めてください。', 'error')
            return redirect(url_for('register'))
        if not re.search(r"[0-9]", password):
            flash('パスワードには数字を含めてください。', 'error')
            return redirect(url_for('register'))
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
            flash('パスワードには記号を含めてください。', 'error')
            return redirect(url_for('register'))

        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash('ユーザー登録が完了しました！ログインしてください', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
def home():
    if current_user.is_authenticated:
        group = current_user.default_group or 'nogizaka'
        return redirect(url_for('index', group_key=group))
    else:
        return redirect(url_for('login'))

def get_photos_by_group(group_key):
    folder_path = f'members_csv/{group_key}'  # 例: members_csv/hinatazaka
    photos_by_member = {}

    for filename in os.listdir(folder_path):
        if filename.endswith('.csv'):
            member_name = filename.replace('.csv', '')
            member_photos = []
            csv_path = os.path.join(folder_path, filename)
            with open(csv_path, encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader,None)
                for row in reader:
                    if len(row) == 3:
                        member, costume, photo_type = row
                        member_photos.append({
                            'member': member,
                            'costume': costume,
                            'photo_type': photo_type
                        })
            photos_by_member[member_name] = member_photos

    return photos_by_member

@app.route('/gallery/<group_key>', methods=['GET'])
@login_required
def gallery(group_key):
    group_key = group_key.strip()

    # GETパラメータから絞り込み条件を取得
    selected_member = request.args.get('member', '').strip()
    selected_costume = request.args.get('costume', '').strip()

    # グループごとの全写真取得
    all_photos_by_member = get_photos_by_group(group_key)

    # メンバー一覧と衣装一覧を収集
    member_list = sorted(all_photos_by_member.keys())
    costume_set = set()
    for photos in all_photos_by_member.values():
        for photo in photos:
            costume_set.add(photo['costume'].strip())
    costume_list = sorted(costume_set)

    # フィルタリング処理
    photos_by_member = {}
    for member, photos in all_photos_by_member.items():
        if selected_member and member != selected_member:
            continue
        filtered_photos = []
        for photo in photos:
            if selected_costume and photo['costume'].strip() != selected_costume:
                continue
            # 画像パスと存在チェック
            image_rel_path = build_image_path(photo['member'], photo['costume'], photo['photo_type'], group_key)
            image_abs_path = os.path.join(current_app.static_folder, image_rel_path)
            photo['image_exists'] = os.path.exists(image_abs_path)
            photo['image_path'] = image_rel_path
            filtered_photos.append(photo)
        if filtered_photos:
            photos_by_member[member] = filtered_photos

    group_colors = {
        'hinatazaka': 'bg-hinata',
        'sakurazaka': 'bg-sakura',
        'nogizaka': 'bg-nogi'
    }
    group_color = group_colors.get(group_key, 'bg-default')

    return render_template(
        'gallery.html',
        endpoint=request.endpoint,
        photos_by_member=photos_by_member,
        group_key=group_key,
        group_color=group_color,
        member_list=member_list,
        costume_list=costume_list,
        selected_member=selected_member,
        selected_costume=selected_costume
    )

@app.route('/index/<group_key>', methods=['GET'])
@login_required
def index(group_key):
    group_colors = {
        'nogizaka': 'bg-nogi',
        'sakurazaka': 'bg-sakura',
        'hinatazaka': 'bg-hinata'
    }
    group_color = group_colors.get(group_key, 'bg-default')

    selected_member = request.args.get('member', '').strip()
    selected_costume = request.args.get('costume', '').strip()
    selected_type = request.args.get('type', '').strip()
    query = request.args.get('query', '').strip()

    q = UserPhoto.query.filter_by(user_id=current_user.id, group_key=group_key)

    if selected_member:
        q = q.filter(UserPhoto.member == selected_member)
    if selected_costume:
        q = q.filter(UserPhoto.costume == selected_costume)
    if selected_type:
        q = q.filter(UserPhoto.photo_type == selected_type)
    if query:
        like_pattern = f"%{query}%"
        q = q.filter(
            or_(
                UserPhoto.member.ilike(like_pattern),
                UserPhoto.costume.ilike(like_pattern)
            )
        )

    photos_raw = q.all()
    print(f"[DEBUG] photos_raw count: {len(photos_raw)}")
    for p in photos_raw:
        print(f"[DEBUG] Photo: id={p.id}, member={p.member}, costume={p.costume}, type={p.photo_type}")

    photos = []
    for p in photos_raw:
        image_rel_path = build_image_path(p.member, p.costume, p.photo_type, group_key)
        image_abs_path = os.path.join(current_app.static_folder, image_rel_path)
        image_exists = os.path.exists(image_abs_path)

        photo_dict = {
            'id': p.id,
            'member': p.member,
            'costume': p.costume,
            'photo_type': p.photo_type,
            'quantity': p.quantity,
            'date': p.date,
            'memo': p.memo,
            'image_exists': image_exists,
            'image_path': image_rel_path,
        }
        photos.append(photo_dict)

    # フィルター用データはDBの全写真から作る
    all_photos = UserPhoto.query.filter_by(user_id=current_user.id, group_key=group_key).all()
    members = sorted(set(p.member for p in all_photos))
    costumes = sorted(set(p.costume for p in all_photos))
    types = sorted(set(p.photo_type for p in all_photos))

    return render_template(
        'index.html',
        group_key=group_key,
        group_color=group_color,
        photos=photos,
        members=members,
        costumes=costumes,
        types=types,
        selected_member=selected_member,
        selected_costume=selected_costume,
        selected_type=selected_type,
        query=query,
        endpoint=request.endpoint
    )

GROUP_KEY_MAP = {
    'nogizaka': '乃木坂46',
    'sakurazaka': '櫻坂46',
    'hinatazaka': '日向坂46'
}

@app.route('/delete_user_photo/<group_key>/<int:photo_id>', methods=['POST'])
@login_required
def delete_user_photo(group_key, photo_id):
    photo = UserPhoto.query.get(photo_id)
    if not photo:
        flash('写真が見つかりません。', 'error')
        app.logger.debug(f"[DEBUG] Photo with id={photo_id} not found.")
        return redirect(url_for('index', group_key=group_key))

    if photo.user_id != current_user.id:
        flash('あなたの写真ではありません。', 'error')
        app.logger.debug(f"[DEBUG] Photo user_id={photo.user_id} does not match current_user.id={current_user.id}")
        return redirect(url_for('index', group_key=group_key))

    expected_group = GROUP_KEY_MAP.get(group_key)
    if not expected_group:
        flash('無効なグループキーです。', 'error')
        return redirect(url_for('index', group_key=group_key))

    if photo.group != expected_group:
        flash('グループキーが不正です。', 'error')
        app.logger.debug(f"[DEBUG] Photo group={photo.group} does not match expected_group={expected_group}")
        return redirect(url_for('index', group_key=group_key))

    db.session.delete(photo)
    db.session.commit()
    flash('生写真を削除しました。', 'success')
    app.logger.debug(f"[DEBUG] Deleted photo id={photo_id} for user_id={current_user.id} group={group_key}")

    return redirect(url_for('index', group_key=group_key))

@app.route('/add/<group_key>', methods=['GET', 'POST'])
@login_required
def add(group_key):
    group_colors = {
        'nogizaka': 'bg-nogi',
        'sakurazaka': 'bg-sakura',
        'hinatazaka': 'bg-hinata'
    }
    group_names = {
        'nogizaka': '乃木坂46',
        'sakurazaka': '櫻坂46',
        'hinatazaka': '日向坂46'
    }

    group_color = group_colors.get(group_key, 'bg-default')
    group_name = group_names.get(group_key, '不明')

    form = AddPhotoForm()

    if request.method == 'POST':
        # POST時は送信された値をchoicesにセット（member, costumeは動的なので送信値だけ）
        member_value = request.form.get('member', '')
        costume_value = request.form.get('costume', '')
        photo_type_value = request.form.get('photo_type', '')

        form.member.choices = [(member_value, member_value)]
        form.costume.choices = [(costume_value, costume_value)]

        # photo_type は固定選択肢を常にセット
        form.photo_type.choices = [
            ('ヨリ', 'ヨリ'),
            ('チュウ', 'チュウ'),
            ('ヒキ', 'ヒキ'),
            ('座り', '座り')
        ]

    else:
        # GET時は空の選択肢をセット
        form.member.choices = []
        form.costume.choices = []
        form.photo_type.choices = [
            ('ヨリ', 'ヨリ'),
            ('チュウ', 'チュウ'),
            ('ヒキ', 'ヒキ'),
            ('座り', '座り')
        ]

    if form.validate_on_submit():
        logging.info("✅ フォームバリデーション成功")
        try:
            member = form.member.data.strip()
            costume = form.costume.data.strip()
            photo_type = form.photo_type.data.strip()
            quantity = form.quantity.data
            memo = form.memo.data.strip()
            date_acquired = form.date_acquired.data
            has_owner = True

            # Photoマスタを取得または作成
            photo = Photo.query.filter_by(
                group_key=group_key,
                member=member,
                costume=costume,
                photo_type=photo_type
            ).first()

            if not photo:
                try:
                    photo = Photo(
                        group_key=group_key,
                        group=group_name,
                        member=member,
                        costume=costume,
                        photo_type=photo_type
                    )
                    db.session.add(photo)
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    photo = Photo.query.filter_by(
                        group_key=group_key,
                        member=member,
                        costume=costume,
                        photo_type=photo_type
                    ).first()

            if not photo:
                flash('Photoの登録に失敗しました。データベースを確認してください。', 'error')
                logging.error('Photo登録に失敗: DBを確認してください')
                return redirect(url_for('add', group_key=group_key))

            # すでに所持しているか確認（photo_id基準）
            existing = UserPhoto.query.filter_by(
                user_id=current_user.id,
                photo_id=photo.id
            ).first()

            if existing:
                existing.quantity += quantity
                existing.memo = memo
                if date_acquired:
                    existing.date = date_acquired
                db.session.commit()
                flash(f'{member}の{costume}（{photo_type}）は既に所持しています。所持数を{quantity}枚増やしました。')
                logging.info(f'{member}の{costume}（{photo_type}）の数量を{quantity}枚増加')
            else:
                new_user_photo = UserPhoto(
                    user_id=current_user.id,
                    photo_id=photo.id,
                    member=member,
                    costume=costume,
                    photo_type=photo_type,
                    group_key=group_key,
                    group=group_name,
                    has_owner=has_owner,
                    memo=memo,
                    date=date_acquired,
                    quantity=quantity
                )
                db.session.add(new_user_photo)
                db.session.commit()
                flash(f'{member}の{costume}（{photo_type}）が{quantity}枚追加されました！')
                logging.info(f'新規生写真追加: {member}の{costume}（{photo_type}）{quantity}枚')

            return redirect(url_for('index', group_key=group_key))

        except Exception as e:
            db.session.rollback()
            logging.exception("❌ 生写真追加処理で例外発生")
            flash('エラーが発生しました。管理者に連絡してください。', 'error')
            return redirect(url_for('add', group_key=group_key))

    else:
        if request.method == 'POST':
            logging.warning(f"⚠️ フォームバリデーション失敗: {form.errors}")

    return render_template('add.html', form=form, group_key=group_key, group_color=group_color)

def get_missing_photos(search_member='', search_costume='', group_key='hinata'):

    # デバッグ: Photoテーブルの中身を確認
    all_photos = Photo.query.all()
    print("All Photos in DB:")
    for p in all_photos:
        print(f"id={p.id}, group_key={p.group_key}, member={p.member}, costume={p.costume}, type={p.photo_type}")

    # 未所持で、ユーザーがまだ所有していない生写真を取得
    query = Photo.query.filter_by(group_key=group_key)
    
    # ユーザーが所持している生写真（`has_owner=True`）のIDを取得
    owned_photos = db.session.query(UserPhoto).filter_by(user_id=current_user.id, has_owner=True).all()
    owned_photos_ids = {(photo.member, photo.costume, photo.photo_type) for photo in owned_photos}

    # デバッグ: 所持している写真（owned_photos_ids）の内容を表示
    print(f"Owned Photos (IDs): {owned_photos_ids}")
    
    # メンバー名の検索がある場合
    if search_member:
        query = query.filter(Photo.member.ilike(f'%{search_member}%'))

    # 衣装名の検索がある場合
    if search_costume:
        query = query.filter(Photo.costume.ilike(f'%{search_costume}%'))

    results = query.all()

    # デバッグ: フィルタリング前の結果を表示
    print(f"Results Before Filtering: {[photo.id for photo in results]}")

    # 未所持の写真をフィルタリング（ユーザーが所有していない写真のみ）
    results = [photo for photo in results if (photo.member, photo.costume, photo.photo_type) not in owned_photos_ids]

    # デバッグ: フィルタリング後の結果を表示
    print(f"Results After Filtering: {[photo.id for photo in results]}")

    # 結果をメンバーごとにグループ化
    grouped = {}
    for photo in results:
        member = photo.member
        if member not in grouped:
            grouped[member] = []
        grouped[member].append({
            'costume': photo.costume,
            'type': photo.photo_type
        })

    return grouped

@app.route('/missing/<group_key>', methods=['GET'])
@login_required
def missing(group_key):  # ←ここを追加！
    search_member = request.args.get('member', '')
    search_costume = request.args.get('costume', '')

    group_colors = {
        'nogizaka': 'bg-nogi',
        'sakurazaka': 'bg-sakura',
        'hinatazaka': 'bg-hinata'
    }.get(group_key, 'bg-default')

    grouped = get_missing_photos(search_member, search_costume, group_key)

    # 衣装一覧を抽出
    costume_set = set()
    for photos in grouped.values():
        for photo in photos:
            costume = (photo.get('costume') or '').strip()
            if costume:
                costume_set.add(costume)
    costume_list = sorted(costume_set)

    return render_template(
        'missing.html',
        endpoint=request.endpoint,
        grouped_missing=grouped,
        group_key=group_key,
        group_color=group_colors,
        search_member=search_member,
        search_costume=search_costume,
        costume_list=costume_list
    )

@app.route('/shared/<int:user_id>/<group_key>')
def shared_stats(user_id, group_key):
    user = User.query.get_or_404(user_id)
    group_key = group_key.lower()

    if group_key not in ['nogizaka', 'sakurazaka', 'hinatazaka']:
        abort(404)

    all_photos = get_all_photos(group_key)
    owned_photo_ids = get_user_photo_ids(user.id, group_key)
    stats = compute_collection_stats(all_photos, owned_photo_ids)

    return render_template('shared_stats.html',
                           user=user,
                           group_key=group_key,
                           stats=stats,
                           all_photos=all_photos,
                           owned_photo_ids=owned_photo_ids)

@app.route('/toggle_share/<group_key>', methods=['POST'])
@login_required
def toggle_share(group_key):
    group_key = group_key.lower()
    if group_key not in ['nogizaka', 'sakurazaka', 'hinatazaka']:
        abort(404)

    try:
        current_user.toggle_share_setting(group_key)
    except ValueError:
        abort(400)

    # 変更をDBに保存
    db.session.commit()
    return redirect(url_for('mypage'))

@app.route("/share/<group_key>/<username>")
def shared_collection(group_key, username):
    group_key = group_key.lower()
    if group_key not in ['nogizaka', 'sakurazaka', 'hinatazaka']:
        abort(404)

    user = User.query.filter_by(username=username).first_or_404()

    # 共有設定を判定
    is_shared = False
    if group_key == 'nogizaka':
        is_shared = user.is_nogizaka_shared
    elif group_key == 'sakurazaka':
        is_shared = user.is_sakurazaka_shared
    elif group_key == 'hinatazaka':
        is_shared = user.is_hinatazaka_shared

    if not is_shared:
        return render_template("shared_collection/not_shared.html", username=username)

    # UserPhotoのgroupフィールドがgroup_keyのものを取得
    user_photos = UserPhoto.query.filter_by(user_id=user.id, group=group_key).all()

    return render_template(
        "shared_collection/shared_view.html",
        username=username,
        photocards=user_photos,
        group_name=group_key.capitalize()
    )

@app.route('/qr_image/<group_key>')
@login_required
def qr_image(group_key):
    group_key = group_key.lower()
    if group_key not in ['nogizaka', 'sakurazaka', 'hinatazaka']:
        abort(404)

    share_url = url_for('shared_collection', group_key=group_key, username=current_user.username, _external=True)

    qr_img = qrcode.make(share_url)
    buf = io.BytesIO()
    qr_img.save(buf, format='PNG')
    buf.seek(0)

    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    return jsonify({'qr_base64': img_base64})

@app.before_request
def make_session_permanent():
    session.permanent = True


@app.route('/confirm_delete_account', methods=['GET', 'POST'])
@login_required
def confirm_delete_account():
    user = current_user
    group_key = user.group_key or "nogizaka"

    if request.method == 'POST':
        password = request.form.get('password')

        if not password:
            flash("パスワードを入力してください。")
            return redirect(url_for('confirm_delete_account'))

        if not user.check_password(password):
            flash("パスワードが違います。")
            return redirect(url_for('confirm_delete_account'))

        session['pending_delete_password'] = password
        session['pending_delete_group_key'] = group_key

        return redirect(url_for('confirm_delete_final'))

    return render_template('confirm_delete_account.html', group_key=group_key)


@app.route('/confirm_delete_final', methods=['GET', 'POST'])
@login_required
def confirm_delete_final():
    password = session.get('pending_delete_password')
    group_key = session.get('pending_delete_group_key', 'nogizaka')

    if not password:
        flash("不正な操作です。もう一度お試しください。")
        return redirect(url_for('confirm_delete_account'))

    if request.method == 'POST':
        user = current_user

        if not user.check_password(password):
            flash("認証エラーが発生しました。")
            return redirect(url_for('confirm_delete_account'))

        db.session.delete(user)
        db.session.commit()
        logout_user()
        session.clear()

        flash("アカウントを削除しました。ご利用ありがとうございました。")
        return redirect(url_for('index', group_key=group_key))

    return render_template('confirm_delete_final.html', group_key=group_key)

@app.route("/mypage")
@login_required
def mypage():
    def make_qr_base64(group_key):
        share_url = url_for('shared_collection', group_key=group_key, username=current_user.username, _external=True)
        qr_img = qrcode.make(share_url)
        buf = io.BytesIO()
        qr_img.save(buf, format='PNG')
        buf.seek(0)
        return base64.b64encode(buf.read()).decode('utf-8')

    qr_codes = {
        'nogizaka': make_qr_base64('nogizaka'),
        'sakurazaka': make_qr_base64('sakurazaka'),
        'hinatazaka': make_qr_base64('hinatazaka')
    }

    share_statuses = {
        'nogizaka': current_user.is_nogizaka_shared,
        'sakurazaka': current_user.is_sakurazaka_shared,
        'hinatazaka': current_user.is_hinatazaka_shared
    }

    # default_groupがNoneなら 'nogizaka' など安全な値を設定
    default_group = current_user.default_group or 'nogizaka'

    return render_template(
        "mypage.html",
        user=current_user,
        group_key=default_group,
        default_group=default_group,
        is_shared=share_statuses.get(default_group, False),
        qr_codes=qr_codes,
        share_statuses=share_statuses,
    )

@app.route('/mypage/icon', methods=['GET', 'POST'])
@login_required
def icon_setting():
    form = IconUploadForm()

    if request.method == 'POST':
        cropped_data = request.form.get('cropped_data')

        if cropped_data:
            try:
                # base64ヘッダーを除去
                header, encoded = cropped_data.split(',', 1)
                binary_data = base64.b64decode(encoded)

                # 画像として読み込み
                image = Image.open(BytesIO(binary_data))

                # 保存パスを準備
                user_folder = os.path.join(app.root_path, 'static', 'uploads', 'icons', f'user_{current_user.id}')
                os.makedirs(user_folder, exist_ok=True)

                # 保存ファイル名を統一（例：icon.png）
                filename = 'icon.png'
                save_path = os.path.join(user_folder, filename)

                # PNGで保存
                image.save(save_path, format='PNG')

                # DBに相対パスを保存
                current_user.icon_filename = f'user_{current_user.id}/{filename}'
                db.session.commit()

                flash('アイコンを更新しました。', 'success')
                return redirect(url_for('mypage'))
            except Exception as e:
                flash('画像の処理に失敗しました。', 'danger')
                print(f"[エラー] {e}")
        else:
            flash('画像がトリミングされていません。', 'warning')

    return render_template('icon_setting.html', form=form)

@app.route('/mypage/icon/delete', methods=['POST'])
@login_required
def delete_icon():
    if current_user.icon_filename:
        icon_path = os.path.join(app.root_path, 'static', 'uploads', 'icons', current_user.icon_filename)
        try:
            if os.path.exists(icon_path):
                os.remove(icon_path)
        except Exception as e:
            app.logger.error(f"アイコン削除失敗: {e}")

        # DBのフィールドをリセット
        current_user.icon_filename = None
        db.session.commit()

        flash('アイコンを削除しました。', 'info')

    return redirect(url_for('icon_setting'))

@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        new_username = request.form.get('username')
        email = request.form.get('email')

        if new_username:
            current_user.username = new_username
        if email:
            current_user.email = email

        db.session.commit()
        flash('プロフィールを更新しました', 'success')
        return redirect(url_for('mypage'))

    return render_template('edit_profile.html', user=current_user)

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not current_user.check_password(current_password):
            flash('現在のパスワードが正しくありません。', 'error')
            return redirect(url_for('change_password'))

        if new_password != confirm_password:
            flash('新しいパスワードと確認用パスワードが一致しません。', 'error')
            return redirect(url_for('change_password'))

        if len(new_password) < 6:
            flash('パスワードは6文字以上にしてください。', 'error')
            return redirect(url_for('change_password'))

        # ✅ パスワード強度チェック
        if not re.search(r"[A-Za-z]", new_password):
            flash('パスワードには英字を含めてください。', 'error')
            return redirect(url_for('change_password'))

        if not re.search(r"[0-9]", new_password):
            flash('パスワードには数字を含めてください。', 'error')
            return redirect(url_for('change_password'))

        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", new_password):
            flash('パスワードには記号を含めてください。', 'error')
            return redirect(url_for('change_password'))

        current_user.set_password(new_password)
        db.session.commit()
        flash('パスワードを変更しました。', 'success')
        return redirect(url_for('mypage'))

    return render_template('change_password.html')

@app.route('/set_default_group', methods=['GET', 'POST'])
@login_required
def set_default_group():
    groups = ['nogizaka', 'sakurazaka', 'hinatazaka']  # 例: グループ一覧

    if request.method == 'POST':
        selected_group = request.form.get('group')
        if selected_group not in groups:
            flash('無効なグループが選択されました。')
            return redirect(url_for('set_default_group'))

        current_user.default_group = selected_group
        db.session.commit()
        flash(f'初期表示グループを「{selected_group}」に設定しました。')
        return redirect(url_for('mypage'))

    return render_template('set_default_group.html', groups=groups, current_default=current_user.default_group)

@app.route('/toggle_dark_mode', methods=['POST'])
@login_required
def toggle_dark_mode():

    current_user.dark_mode = not current_user.dark_mode
    db.session.commit()
    flash('ダークモード設定を更新しました。')

    # 前のページに戻す（referrerがなければmypage）
    return redirect(request.referrer or url_for('mypage'))

@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    user_id = current_user.id
    user_folder = os.path.join(app.root_path, 'static', 'uploads', 'icons', f'user_{user_id}')

    # DBからユーザー削除処理など
    # 例: db.session.delete(current_user), db.session.commit() など

    # フォルダ削除（存在する場合のみ）
    if os.path.exists(user_folder):
        shutil.rmtree(user_folder)  # フォルダごと削除

    # ログアウトやリダイレクト処理
    logout_user()
    flash('アカウントを削除しました。', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # ←これが大事！
    app.run(debug=True)


