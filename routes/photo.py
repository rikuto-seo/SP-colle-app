from flask import render_template, request, redirect, url_for, flash, current_app, Blueprint, jsonify, abort
from flask_login import login_required, current_user
from extensions import db
from datetime import date
from collections import defaultdict
from routes.core import group_required

from sqlalchemy import func, case

from models import Group, Member, Costume, PhotoType, Photo, UserPhoto
from collections import defaultdict
from sqlalchemy.orm import joinedload

photo_bp = Blueprint('photo', __name__)

GROUP_KEY_MAP = {
    'nogizaka': '乃木坂46',
    'sakurazaka': '櫻坂46',
    'hinatazaka': '日向坂46'
}


@photo_bp.route('/index/<group_key>')
@login_required
@group_required
def index(group_key):

    group = Group.query.filter_by(key=group_key).first_or_404()

    page = request.args.get("page", 1, type=int)
    per_page = 30

    selected_member = request.args.get("member", "").strip()
    selected_costume = request.args.get("costume", "").strip()
    query = request.args.get("query", "").strip()
    favorite_only = request.args.get("favorite") == "1"

    # =========================
    # Member × Costume 集計
    # =========================

    summary_query = (
        db.session.query(
            Member.id.label("member_id"),
            Member.name.label("member_name"),
            Costume.id.label("costume_id"),
            Costume.name.label("costume_name"),
            func.count(Photo.id).label("total_types"),
            func.count(
                func.distinct(
                    case(
                        (UserPhoto.quantity > 0, Photo.type_id)
                    )
                )
            ).label("owned_types")
        )
        .select_from(Photo)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .outerjoin(
            UserPhoto,
            (UserPhoto.photo_id == Photo.id)
            & (UserPhoto.user_id == current_user.id)
        )
        .filter(Member.group_id == group.id)
        .group_by(
            Member.id,
            Member.name,
            Costume.id,
            Costume.name
        )
    )

    # =========================
    # フィルタ
    # =========================

    if selected_member:
        summary_query = summary_query.filter(
            Member.name.ilike(f"%{selected_member}%")
        )

    if selected_costume:
        summary_query = summary_query.filter(
            Costume.name.ilike(f"%{selected_costume}%")
        )

    if query:
        summary_query = summary_query.filter(
            db.or_(
                Member.name.ilike(f"%{query}%"),
                Costume.name.ilike(f"%{query}%")
            )
        )

    if favorite_only:

        favorite_exists = (
            db.session.query(UserPhoto.id)
            .join(Photo, Photo.id == UserPhoto.photo_id)
            .filter(
                UserPhoto.user_id == current_user.id,
                UserPhoto.is_favorite.is_(True),
                Photo.member_id == Member.id,
                Photo.costume_id == Costume.id
            )
            .exists()
        )

        summary_query = summary_query.filter(
            favorite_exists
        )

    # =========================
    # 通常時のみ所持データ有りを表示
    # =========================

    summary_query = summary_query.having(
        func.count(UserPhoto.id) > 0
    )

    summary_query = summary_query.order_by(
        Member.name,
        Costume.name
    )

    pagination_obj = summary_query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    display_rows = pagination_obj.items

    # =========================
    # 詳細取得
    # =========================

    target_pairs = [
        (r.member_id, r.costume_id)
        for r in display_rows
    ]

    member_ids = list({
        r.member_id for r in display_rows
    })

    costume_ids = list({
        r.costume_id for r in display_rows
    })

    details_rows = (
        db.session.query(UserPhoto)
        .join(Photo)
        .options(
            joinedload(UserPhoto.photo)
            .joinedload(Photo.photo_type)
        )
        .filter(
            UserPhoto.user_id == current_user.id,
            Photo.member_id.in_(member_ids),
            Photo.costume_id.in_(costume_ids)
        )
        .all()
    )

    details_map = defaultdict(list)

    for up in details_rows:

        key = (
            up.photo.member_id,
            up.photo.costume_id
        )

        details_map[key].append({
            "id": up.id,
            "type": up.photo.photo_type.name,
            "quantity": up.quantity,
            "available": up.available_quantity,
            "memo": up.memo or "",
            "date": (
                up.date.strftime("%Y-%m-%d")
                if up.date else ""
            ),
            "is_favorite": bool(up.is_favorite)
        })

    # =========================
    # カード生成
    # =========================

    cards = []

    for row in display_rows:

        details = details_map.get(
            (row.member_id, row.costume_id),
            []
        )

        cards.append({
            "member": row.member_name,
            "costume": row.costume_name,
            "owned": row.owned_types,
            "total": row.total_types,
            "rate": round(
                (
                    row.owned_types
                    / row.total_types
                    * 100
                ),
                1
            ) if row.total_types else 0,
            "is_complete":
                row.owned_types == row.total_types,
            "details": details,
            "has_favorite":
                any(
                    d["is_favorite"]
                    for d in details
            )
        })

    # =========================
    # TomSelect用
    # =========================

    members = (
        db.session.query(Member.name)
        .filter_by(group_id=group.id)
        .distinct()
        .order_by(Member.name)
        .all()
    )

    costumes = (
        db.session.query(Costume.name)
        .filter_by(group_id=group.id)
        .distinct()
        .order_by(Costume.name)
        .all()
    )

    members_list = [m[0] for m in members]
    costumes_list = [c[0] for c in costumes]

    # =========================
    # ページネーション用引数
    # =========================

    args = request.args.to_dict()
    args.pop("page", None)

    current_filters = {
        "query": query,
        "member": selected_member,
        "costume": selected_costume
    }

    return render_template(
        "index.html",
        group_key=group_key,
        cards=cards,
        pagination=pagination_obj,
        members=members_list,
        costumes=costumes_list,
        args=args,
        current_filters=current_filters,
        selected_member=selected_member,
        selected_costume=selected_costume,
        query=query,
        favorite_only=favorite_only,
        current_url=request.full_path
    )


@photo_bp.route('/delete_user_photo/<group_key>/<int:photo_id>', methods=['POST'])
@login_required
@group_required
def delete_user_photo(group_key, photo_id):

    # グループ取得（これを基準にする）
    group = Group.query.filter_by(key=group_key).first_or_404()

    # ユーザーの写真取得
    photo = UserPhoto.query.filter_by(
        id=photo_id,
        user_id=current_user.id
    ).first_or_404()

    # 所有チェック（実質不要だが安全のため残すならOK）
    if photo.user_id != current_user.id:
        flash('あなたの写真ではありません。', 'error')
        current_app.logger.debug(
            f"[DEBUG] user mismatch: photo.user_id={photo.user_id}, current_user.id={current_user.id}"
        )
        return redirect(url_for('photo.index', group_key=group_key))

    # グループ整合性チェック（正しい参照経路）
    if photo.photo.member.group_id != group.id:
        flash('グループキーが不正です。', 'error')
        current_app.logger.debug(
            f"[DEBUG] group mismatch: photo_group_id={photo.photo.member.group_id}, expected_group_id={group.id}"
        )
        return redirect(url_for('photo.index', group_key=group_key))

    # 削除
    db.session.delete(photo)
    db.session.commit()

    flash('生写真を削除しました。', 'success')
    current_app.logger.debug(
        f"[DEBUG] Deleted photo id={photo_id}, user_id={current_user.id}, group_key={group_key}"
    )

    return redirect(url_for('photo.index', group_key=group_key))


@photo_bp.route('/add/<group_key>', methods=['GET', 'POST'])
@login_required
@group_required
def add(group_key):

    group = Group.query.filter_by(key=group_key).first_or_404()

    from forms import AddPhotoForm
    form = AddPhotoForm()

    # =========================
    # POST（登録処理）
    # =========================
    if request.method == 'POST':

        member = request.form.get('member')
        costume = request.form.get('costume')
        type_name = request.form.get('photo_type')

        # 安全にint化
        try:
            quantity = int(request.form.get('quantity', 1))
        except (TypeError, ValueError):
            quantity = 1

        # 🔒 バリデーション
        if not member or not costume or not type_name:
            flash('入力が不正です', 'error')
            return redirect(url_for('photo.add', group_key=group_key))

        # 🔥 対象photo取得
        photo = (
            db.session.query(Photo)
            .join(Member)
            .join(Costume)
            .join(PhotoType)
            .filter(
                Member.name == member,
                Costume.name == costume,
                PhotoType.name == type_name,
                Member.group_id == group.id
            )
            .first()
        )

        if not photo:
            flash('該当する写真が見つかりません', 'error')
            return redirect(url_for('photo.add', group_key=group_key))

        # 🔥 既存チェック
        existing = UserPhoto.query.filter_by(
            user_id=current_user.id,
            photo_id=photo.id
        ).first()

        if existing:
            existing.quantity += quantity
        else:
            db.session.add(UserPhoto(
                user_id=current_user.id,
                photo_id=photo.id,
                quantity=quantity
            ))

        db.session.commit()
        flash('追加しました', 'success')

        # 🔁 連続追加モード対応
        if request.form.get("continuous_mode") == "on":
            return redirect(url_for(
                'photo.add',
                group_key=group_key,
                member=member,
                costume=costume
            ))

        return redirect(url_for('photo.index', group_key=group_key))

    # =========================
    # GET（画面表示）
    # =========================
    return render_template(
        'add.html',
        form=form,
        group_key=group_key
    )


@photo_bp.route('/get_members')
@login_required
def get_members():
    group = request.args.get('group')
    g = Group.query.filter_by(key=group).first()
    if not g:
        return jsonify({"members": []})

    from services.photo_service import get_members
    return jsonify({"members": get_members(g.id)})


@photo_bp.route('/get_costumes')
@login_required
def get_costumes():
    group = request.args.get('group')
    member = request.args.get('member')

    g = Group.query.filter_by(key=group).first()
    if not g:
        return jsonify({"costumes": []})

    from services.photo_service import get_costumes
    return jsonify({"costumes": get_costumes(g.id, member)})


@photo_bp.route('/get_types')
@login_required
def get_types():
    group = request.args.get('group')
    member = request.args.get('member')
    costume = request.args.get('costume')

    g = Group.query.filter_by(key=group).first()
    if not g:
        return jsonify({"types": []})

    from services.photo_service import get_types
    return jsonify({"types": get_types(g.id, member, costume)})


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
