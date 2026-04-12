import os
import csv
import logging
from flask import render_template, request, redirect, url_for, flash, current_app, Blueprint, jsonify, abort
from flask_login import login_required, current_user
from models import Photo, UserPhoto
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from extensions import db
from forms import AddPhotoForm
from services.stats_service import get_costumes_from_member_csv, get_ordered_members, load_required_types
from datetime import date
from collections import defaultdict
from routes.core import group_required

photo_bp = Blueprint('photo', __name__)

GROUP_KEY_MAP = {
    'nogizaka': '乃木坂46',
    'sakurazaka': '櫻坂46',
    'hinatazaka': '日向坂46'
}


@photo_bp.route('/index/<group_key>', methods=['GET'])
@login_required
@group_required
def index(group_key):

    if group_key not in GROUP_KEY_MAP:
        abort(404)

    group_colors = {
        'nogizaka': 'bg-nogi',
        'sakurazaka': 'bg-sakura',
        'hinatazaka': 'bg-hinata'
    }
    group_color = group_colors.get(group_key, 'bg-default')

    selected_member = request.args.get('member', '').strip()
    selected_costume = request.args.get('costume', '').strip()
    query = request.args.get('query', '').strip()

    sort = request.args.get('sort', '').strip()
    order = request.args.get('order', 'desc')
    reverse = (order == 'desc')

    # =========================
    # ① ユーザーデータ取得（全件）
    # =========================
    user_photos = UserPhoto.query.filter_by(
        user_id=current_user.id,
        group_key=group_key
    ).all()

    # =========================
    # ② フィルタ適用
    # =========================
    filtered = []

    for p in user_photos:

        if selected_member and p.member != selected_member:
            continue

        if selected_costume and p.costume != selected_costume:
            continue

        if query:
            if query not in p.member and query not in p.costume:
                continue

        filtered.append(p)


    # =========================
    # ③ 所持タイプ集約
    # =========================
    owned_dict = defaultdict(lambda: defaultdict(set))

    for p in filtered:
        owned_dict[p.member][p.costume].add(p.photo_type)

    # =========================
    # ④ マスタ取得
    # =========================
    required_dict = load_required_types(group_key)

    # =========================
    # ⑤ カード生成（ここを修正）
    # =========================
    cards = []
    

    for member, costumes in owned_dict.items():

        for costume, owned_types in costumes.items():

            required_types = required_dict.get(member, {}).get(costume, set())

            owned_count = len(owned_types & required_types)
            total_count = len(required_types)

            # 🔥 ここでそのカード専用detailsを作る
            details = []

            for p in filtered:
                if p.member == member and p.costume == costume:
                    details.append({
                        "id": p.id,
                        "type": p.photo_type,
                        "quantity": p.quantity,
                        "available": p.available_quantity or 0,
                        "memo": p.memo,
                        "date": p.date.strftime('%Y-%m-%d') if p.date else "",
                        "is_favorite": 1 if p.is_favorite else 0
                    })

            has_favorite = any(d["is_favorite"] for d in details)

            # 検索フィルタ
            if query:
                if query not in member and query not in costume:
                    continue

            cards.append({
                "member": member,
                "costume": costume,
                "owned": owned_count,
                "total": total_count,
                "rate": (owned_count / total_count * 100) if total_count else 0,
                "is_complete": (owned_count == total_count and total_count > 0),
                "details": details,
                "has_favorite": has_favorite
            })

    # =========================
    # ⑥ ソート
    # =========================
    if sort == "rate":
        cards = sorted(cards, key=lambda x: x["rate"], reverse=reverse)

    elif sort == "name":
        ordered_members = get_ordered_members(group_key)
        order_map = {name: i for i, name in enumerate(ordered_members)}

        cards = sorted(
            cards,
            key=lambda x: order_map.get(x['member'], 999),
            reverse=reverse
        )

    elif sort == "count":
        cards = sorted(cards, key=lambda x: x["owned"], reverse=reverse)

    # デフォルト（おすすめ）
    else:
        cards = sorted(
            cards,
            key=lambda x: (x["is_complete"], x["rate"]),
            reverse=True
        )

    # =========================
    # ⑦ フィルタ用データ
    # =========================
    members = sorted(set(p.member for p in user_photos))
    costumes = sorted(set(p.costume for p in user_photos))

    # =========================
    # ⑧ ページネーション（手動）
    # =========================
    page = request.args.get('page', 1, type=int)
    per_page = 30

    total = len(cards)
    start = (page - 1) * per_page
    end = start + per_page
    display_cards = cards[start:end]

    # 疑似pagination（テンプレ互換）
    class SimplePagination:
        def __init__(self, page, per_page, total):
            self.page = page
            self.per_page = per_page
            self.total = total

        @property
        def pages(self):
            return (self.total + self.per_page - 1) // self.per_page

        @property
        def has_prev(self):
            return self.page > 1

        @property
        def has_next(self):
            return self.page < self.pages

        @property
        def prev_num(self):
            return self.page - 1

        @property
        def next_num(self):
            return self.page + 1

        def iter_pages(self):
            return range(1, self.pages + 1)

    pagination = SimplePagination(page, per_page, total)

    # =========================
    # ⑨ render
    # =========================
    return render_template(
        'index.html',
        group_key=group_key,
        group_color=group_color,
        cards=display_cards,
        members=members,
        costumes=costumes,
        selected_member=selected_member,
        selected_costume=selected_costume,
        query=query,
        sort=sort,
        order=order,
        pagination=pagination
    )


@photo_bp.route('/delete_user_photo/<group_key>/<int:photo_id>', methods=['POST'])
@login_required
@group_required
def delete_user_photo(group_key, photo_id):
    photo = UserPhoto.query.filter_by(
        id=photo_id,
        user_id=current_user.id
    ).first_or_404()

    if not photo:
        flash('写真が見つかりません。', 'error')
        current_app.logger.debug(
            f"[DEBUG] Photo with id={photo_id} not found.")
        return redirect(url_for('photo.index', group_key=group_key))
    if photo.user_id != current_user.id:
        flash('あなたの写真ではありません。', 'error')
        current_app.logger.debug(
            f"[DEBUG] Photo user_id={photo.user_id} does not match current_user.id={current_user.id}")
        return redirect(url_for('photo.index', group_key=group_key))
    expected_group = GROUP_KEY_MAP.get(group_key)
    if not expected_group:
        flash('無効なグループキーです。', 'error')
        return redirect(url_for('photo.index', group_key=group_key))
    if photo.group != expected_group:
        flash('グループキーが不正です。', 'error')
        current_app.logger.debug(
            f"[DEBUG] Photo group={photo.group} does not match expected_group={expected_group}")
        return redirect(url_for('photo.index', group_key=group_key))
    db.session.delete(photo)
    db.session.commit()
    flash('生写真を削除しました。', 'success')
    current_app.logger.debug(
        f"[DEBUG] Deleted photo id={photo_id} for user_id={current_user.id} group={group_key}")
    return redirect(url_for('photo.index', group_key=group_key))


@photo_bp.route('/add/<group_key>', methods=['GET', 'POST'])
@login_required
@group_required
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
        member_value = request.form.get('member', '')
        costume_value = request.form.get('costume', '')
        type_value = request.form.get('photo_type', '') 
        
        form.member.choices = [(member_value, member_value)]
        form.costume.choices = [(costume_value, costume_value)]
        form.photo_type.choices = [(type_value, type_value)] 
    else:
        form.member.choices = []
        form.costume.choices = []
        form.photo_type.choices = []

    if form.validate_on_submit():
        logging.info("✅ フォームバリデーション成功")

        try:
            member = form.member.data.strip()
            costume = form.costume.data.strip()
            photo_type = form.photo_type.data.strip()
            quantity = form.quantity.data
            memo = form.memo.data.strip()
            date_acquired = form.date_acquired.data

            # ★ トグル取得（ここでOK）
            continuous_mode = request.form.get('continuous_mode') == 'on'

            # =========================
            # Photoマスタ取得 or 作成
            # =========================
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
                flash('Photoの登録に失敗しました。', 'error')
                return redirect(url_for('photo.add', group_key=group_key))

            # =========================
            # UserPhoto処理
            # =========================
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

                flash(
                    f'{member}の{costume}（{photo_type}）は既に所持しています。'
                    f'所持数を{quantity}枚増やしました。'
                )

            else:
                new_user_photo = UserPhoto(
                    user_id=current_user.id,
                    photo_id=photo.id,
                    member=member,
                    costume=costume,
                    photo_type=photo_type,
                    group_key=group_key,
                    group=group_name,
                    has_owner=True,
                    memo=memo,
                    date=date_acquired,
                    quantity=quantity,
                    available_quantity=0
                )

                db.session.add(new_user_photo)
                db.session.commit()

                flash(f'{member}の{costume}（{photo_type}）が{quantity}枚追加されました！')

            # =========================
            # ★ リダイレクト分岐（ここが本体）
            # =========================
            if continuous_mode:
                return redirect(url_for(
                    'photo.add',
                    group_key=group_key,
                    member=member,
                    costume=costume
                ))
            else:
                return redirect(url_for('photo.index', group_key=group_key))

        except Exception:
            db.session.rollback()
            logging.exception("❌ 生写真追加処理で例外発生")
            flash('エラーが発生しました。', 'error')
            return redirect(url_for('photo.add', group_key=group_key))

    else:
        if request.method == 'POST':
            logging.warning(f"⚠️ フォームバリデーション失敗: {form.errors}")

    return render_template(
        'add.html',
        form=form,
        group_key=group_key,
        group_color=group_color
    )


@photo_bp.route('/get_members')
@login_required
def get_members():
    group = request.args.get('group')

    if group not in GROUP_KEY_MAP:
        return jsonify({'members': []})

    base_path = os.path.join(
        current_app.root_path,
        'members_csv',
        group
    )

    master_path = os.path.join(base_path, 'members_master.csv')

    try:
        # --- ① 存在するメンバーCSVを取得 ---
        existing_members = set()

        for filename in os.listdir(base_path):
            if not filename.endswith('.csv'):
                continue
            if filename == 'members_master.csv':
                continue

            name = filename.replace('.csv', '').strip()
            existing_members.add(name)

        # --- ② masterで順序取得 ---
        ordered_members = []

        if os.path.exists(master_path):
            with open(master_path, encoding='utf-8') as f:
                reader = csv.DictReader(f)

                members = []
                for row in reader:
                    members.append({
                        "member": row["member"].strip(),
                        "generation": int(row["generation"]),
                        "order": int(row["order"])
                    })

                members.sort(key=lambda x: (x["generation"], x["order"]))

                # --- ③ 存在するメンバーだけ残す ---
                ordered_members = [
                    m["member"]
                    for m in members
                    if m["member"] in existing_members
                ]

        return jsonify({'members': ordered_members})

    except Exception:
        current_app.logger.exception("メンバー取得失敗")
        return jsonify({'members': []})


@photo_bp.route('/get_costumes')
@login_required
def get_costumes():
    group = request.args.get('group')
    member = request.args.get('member')

    if group not in GROUP_KEY_MAP or not member:
        return jsonify({'costumes': []})

    if ".." in member or "/" in member:
        return jsonify({'costumes': []})

    try:
        costumes = get_costumes_from_member_csv(group, member)
        return jsonify({'costumes': costumes})

    except Exception:
        current_app.logger.exception(f"衣装取得失敗: {member}")
        return jsonify({'costumes': []})


@photo_bp.route('/get_types')
@login_required
def get_types():
    group = request.args.get('group')
    member = request.args.get('member')
    costume = request.args.get('costume')

    if group not in GROUP_KEY_MAP or not member or not costume:
        return jsonify({'types': []})

    # セキュリティ
    if ".." in member or "/" in member or ".." in costume or "/" in costume:
        return jsonify({'types': []})

    try:
        # ★ 既存サービスを使う
        from services.photo_service import load_required_types

        required = load_required_types(group)

        types = list(
            required.get(member, {}).get(costume, set())
        )

        # 表示安定化（重要）
        types.sort()

        return jsonify({'types': types})

    except Exception:
        current_app.logger.exception("type取得失敗")
        return jsonify({'types': []})


@photo_bp.route('/update_user_photo/<group_key>/<int:photo_id>', methods=['POST'])
@login_required
@group_required
def update_user_photo(group_key, photo_id):
    photo = UserPhoto.query.filter_by(
        id=photo_id,
        user_id=current_user.id
    ).first_or_404()

    if not photo or photo.user_id != current_user.id:
        flash('更新できませんでした', 'error')
        return redirect(url_for('photo.index', group_key=group_key))

    try:
        quantity = int(request.form.get('quantity', 1))
        available = int(request.form.get('available_quantity', 0))
        memo = request.form.get('memo', '').strip()

        # 🔥 お気に入り
        is_favorite = request.form.get("is_favorite") == "on"

        # 🔥 日付
        date_str = request.form.get('date')

        if date_str:
            photo.date = date.fromisoformat(date_str)
        else:
            photo.date = None

        # --- バリデーション ---
        if quantity < 0:
            quantity = 0

        if available < 0:
            available = 0

        if available > quantity:
            available = quantity

        photo.quantity = quantity
        photo.available_quantity = available
        photo.memo = memo

        photo.is_favorite = is_favorite

        db.session.commit()
        flash('更新しました', 'success')

    except Exception:
        db.session.rollback()
        flash('更新エラー', 'error')

    return redirect(url_for('photo.index', group_key=group_key))
