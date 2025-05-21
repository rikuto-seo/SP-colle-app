import os,bcrypt,csv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, current_app
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from models import db, Photo, User, UserPhoto
from config import Config
from collections import defaultdict
from itertools import groupby
from operator import attrgetter
from werkzeug.security import check_password_hash
from sqlalchemy.orm import joinedload
from datetime import datetime
from sqlalchemy.exc import IntegrityError

app = Flask(__name__)

# コンフィグ設定
basedir = os.path.abspath(os.path.dirname(__file__))
#app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/main.db'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'koito-annbata'
app.config.from_object(Config)

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
    if not User.query.filter_by(username='testuser').first():
        user = User(username='testuser')
        user.set_password('testpassword')
        db.session.add(user)
        db.session.commit()

@app.context_processor
def inject_endpoint():
    from flask import request
    return dict(endpoint=request.endpoint)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_costumes_for_member(group, member):
    # グループ名を実際のフォルダ名にマッピング
    group_mapping = {
        "hinata": "hinatazaka",  # hinataをhinatazakaにマッピング
        "nogizaka": "nogizaka",
        "sakurazaka": "sakurazaka"
    }

    # グループ名を実際のフォルダ名に変換
    group_folder = group_mapping.get(group, group)
    
    # CSVファイルのパスを構成
    path = os.path.join('members_csv', group_folder, f'{member}.csv')

    print(f"Looking for path: {path}")  # パス確認用
    try:
        with open(path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            costumes = {row['costume'].strip() for row in reader if 'costume' in row}
            return sorted(costumes)
    except FileNotFoundError:
        print(f"File not found: {path}")  # ファイルが見つからない場合
        return []

def load_photos_from_csv(group_key):
    folder = os.path.join('members_csv', group_key)
    photos = []
    if not os.path.exists(folder):
        return photos
    for fname in os.listdir(folder):
        if fname.endswith('.csv'):
            with open(os.path.join(folder, fname), encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not all(k in row for k in ('member', 'costume', 'type')):
                        continue
                    photos.append(Photo(
                        member=row['member'].strip(),
                        costume=row['costume'].strip(),
                        photo_type=row['type'].strip(),
                        group_key=group_key
                    ))
    return photos

def build_image_path(member, costume, type_, group_key):
    filename = f"{member}_{costume}_{type_}.jpg"
    return f"member_images/{group_key}/{member}/{filename}"

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
    
    all_photos = load_photos_from_csv(group_key)
    if not all_photos:
        return "グループのデータが見つかりません", 404

    owned = set(
        (p.member.strip(), p.costume.strip(), p.photo_type.strip())
        for p in UserPhoto.query.filter_by(user_id=current_user.id, group=group_key).all()
    )

    print("[DEBUG] 所持しているUserPhoto:")
    for photo in UserPhoto.query.filter_by(user_id=current_user.id, group=group_key).all():
        print(f"member='{photo.member}' costume='{photo.costume}' type='{photo.photo_type}'")

    all_costumes = set(p.costume.strip() for p in all_photos)
    costume_stats = {costume: {'owned': 0, 'total': 0} for costume in all_costumes}

    member_stats = defaultdict(int)
    type_stats = defaultdict(int)

    # ✅ コンプ集計用：メンバー×衣装で種類を集める
    costume_dict = defaultdict(lambda: defaultdict(set))  # costume_dict[member][costume] = set of all types
    owned_dict = defaultdict(lambda: defaultdict(set))    # owned_dict[member][costume] = set of owned types

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

    group_colors = {
        'nogizaka': 'bg-nogizaka',
        'sakurazaka': 'bg-sakurazaka',
        'hinatazaka': 'bg-hinatazaka'
    }

    # ✅ comp_ranking を構築
    comp_ranking_list = []
    for member, costumes in comp_stats.items():
        complete_count = sum(1 for item in costumes if item['is_complete'])
        comp_ranking_list.append({
            'member': member,
            'complete_count': complete_count
        })

    # コンプ数降順にソート
    comp_ranking = sorted(comp_ranking_list, key=lambda x: x['complete_count'], reverse=True)

    return render_template(
        'stats.html',
        endpoint=request.endpoint,
        group_key=group_key,
        group_name={'nogizaka': '乃木坂46', 'sakurazaka': '櫻坂46', 'hinatazaka': '日向坂46'}[group_key],
        member_stats=sorted(member_stats.items()),
        type_stats=sorted(type_stats.items()),
        progress_list=progress,
        comp_stats=comp_stats,  # 🔑 追加
        comp_ranking=comp_ranking,
        group_color=group_colors
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
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()

        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('index', group_key='nogizaka'))

        # ログイン失敗時にエラーメッセージを 'error' として渡す
        flash('ユーザー名またはパスワードが間違っています。', 'error')
        return redirect(url_for('login'))

    return render_template('login.html')

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
            flash('そのユーザー名はすでに使われています')
            return redirect(url_for('register'))

        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash('ユーザー登録が完了しました！ログインしてください')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
def home():
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
    group_names = {
        'nogizaka': '乃木坂46',
        'sakurazaka': '櫻坂46',
        'hinatazaka': '日向坂46'
    }

    group_color = group_colors.get(group_key, 'bg-default')
    group_name = group_names.get(group_key, '不明')

    user_photos = UserPhoto.query.options(
        joinedload(UserPhoto.photo)
    ).join(
        Photo, UserPhoto.photo_id == Photo.id
    ).filter(
        UserPhoto.user_id == current_user.id,
        Photo.group_key == group_key
    ).all()
    query = request.args.get('query', '').strip().lower()
    member = request.args.get('member', '').strip()
    costume = request.args.get('costume', '').strip()
    photo_type = request.args.get('type', '').strip()

    if query:
        user_photos = [p for p in user_photos if query in p.member.lower() or query in p.costume.lower()]
    if member:
        user_photos = [p for p in user_photos if p.member == member]
    if costume:
        user_photos = [p for p in user_photos if p.costume == costume]
    if photo_type:
        user_photos = [p for p in user_photos if p.photo_type == photo_type]

    # 画像パスを追加
    for p in user_photos:
        image_rel_path = build_image_path(p.member, p.costume, p.photo_type, group_key)
        image_abs_path = os.path.join(current_app.static_folder, image_rel_path)
        p.image_exists = os.path.exists(image_abs_path)
        p.image_path = image_rel_path

    members = sorted(set(p.member for p in user_photos))
    costumes = sorted(set(p.costume for p in user_photos))
    types = sorted(set(p.photo_type for p in user_photos))

    return render_template(
        'index.html',
        group_key=group_key,
        group_name=group_name,
        group_color=group_color,
        photos=user_photos,
        members=members,
        costumes=costumes,
        types=types,
        endpoint=request.endpoint
    )

@app.route('/delete_user_photo/<int:photo_id>/<group_key>', methods=['POST'])
@login_required
def delete_user_photo(photo_id, group_key):
    photo = UserPhoto.query.get(photo_id)
    
    if not photo or photo.user_id != current_user.id or photo.group != group_key:
        flash('該当の生写真が見つかりません。', 'error')
        return redirect(url_for('index', group_key=group_key))

    # 画像ファイルを削除（任意）
    image_rel_path = build_image_path(photo.member, photo.costume, photo.photo_type, group_key)
    image_abs_path = os.path.join(current_app.static_folder, image_rel_path)
    if os.path.exists(image_abs_path):
        os.remove(image_abs_path)

    # DBから削除
    db.session.delete(photo)
    db.session.commit()
    
    flash('生写真を削除しました。', 'success')
    return redirect(url_for('index', group_key=group_key))

from sqlalchemy.exc import IntegrityError

@app.route('/add/<group_key>', methods=['GET', 'POST'])
@login_required
def add(group_key):
    group_colors = {
        'nogizaka': 'bg-nogi',
        'sakurazaka': 'bg-sakura',
        'hinatazaka': 'bg-hinata'
    }
    group_color = group_colors.get(group_key, 'bg-default')

    if request.method == 'POST':
        member = request.form['member'].strip()
        costume = request.form['costume'].strip()
        type_ = request.form['type'].strip()
        quantity = int(request.form['quantity'])
        memo = request.form.get('memo', '').strip()

        # 取得日
        date_acquired_str = request.form.get('date_acquired')
        date_acquired = None
        if date_acquired_str:
            try:
                date_acquired = datetime.strptime(date_acquired_str, '%Y-%m-%d').date()
            except ValueError:
                flash('取得日の形式が正しくありません。YYYY-MM-DD形式で入力してください。', 'error')
                return redirect(url_for('add', group_key=group_key))

        has_owner_raw = request.form.get('has_owner', 'yes')
        has_owner = True if has_owner_raw == 'yes' else False

        # 既に所持しているか確認
        existing_photo = UserPhoto.query.filter_by(
            user_id=current_user.id,
            group=group_key,
            member=member,
            costume=costume,
            photo_type=type_
        ).first()

        if existing_photo:
            existing_photo.quantity += quantity
            db.session.commit()
            flash(f'{member}の{costume}（{type_}）は既に所持しています。所持数を{quantity}枚増やしました。')
        else:
            group_names = {
                'nogizaka': '乃木坂46',
                'sakurazaka': '櫻坂46',
                'hinatazaka': '日向坂46'
            }
            group_name = group_names.get(group_key, '不明')

            # Photo を探すか新規作成
            photo = Photo.query.filter_by(
                group_key=group_key,
                member=member,
                costume=costume,
                photo_type=type_
            ).first()

            if not photo:
                try:
                    photo = Photo(
                        group_key=group_key,
                        group=group_name,
                        member=member,
                        costume=costume,
                        photo_type=type_
                    )
                    db.session.add(photo)
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    photo = Photo.query.filter_by(
                        group_key=group_key,
                        member=member,
                        costume=costume,
                        photo_type=type_
                    ).first()

            # それでも見つからなければ中断
            if not photo:
                flash('Photoの登録に失敗しました。データベースを確認してください。', 'error')
                return redirect(url_for('add', group_key=group_key))

            try:
                new_user_photo = UserPhoto(
                    user_id=current_user.id,
                    photo_id=photo.id,
                    group=group_key,
                    member=member,
                    costume=costume,
                    photo_type=type_,
                    has_owner=has_owner,
                    memo=memo,
                    date=date_acquired,
                    quantity=quantity
                )
                db.session.add(new_user_photo)
                db.session.commit()
                flash(f'{member}の{costume}（{type_}）が{quantity}枚追加されました！')
            except IntegrityError:
                db.session.rollback()
                flash('同じ生写真がすでに登録されています。', 'error')

        return redirect(url_for('index', group_key=group_key))

    return render_template('add.html', endpoint=request.endpoint, group_key=group_key, group_color=group_color)

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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # ←これが大事！
    app.run(debug=True)


