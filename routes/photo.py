#route/photo.py

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    Blueprint,
    jsonify,
    abort,
)
from flask_login import login_required, current_user
from extensions import db
from datetime import date
from collections import defaultdict
from routes.core import group_required

from sqlalchemy import func, case
from sqlalchemy.orm import joinedload

from models import (
    Group,
    Member,
    Costume,
    PhotoType,
    Photo,
    UserPhoto,
    UserPhotoImage,
)

from services.r2_storage import (
    create_image_variants,
    generate_object_keys,
    upload_bytes,
    delete_image_variants,
    get_image_url,
    get_thumbnail_url,
)

photo_bp = Blueprint('photo', __name__)

GROUP_KEY_MAP = {
    'nogizaka': '乃木坂46',
    'sakurazaka': '櫻坂46',
    'hinatazaka': '日向坂46'
}


# =========================================================
# R2画像削除用ヘルパー
# =========================================================

def _delete_user_photo_images_from_r2(user_photo):
    """
    UserPhotoに紐づくUserPhotoImageのR2オブジェクトを削除する。

    DB削除前に呼び出すことで、R2側に画像だけ残ることを防ぐ。
    R2削除に失敗した場合は例外を送出する。
    """

    for image in list(user_photo.images):
        delete_image_variants(
            image.image_key,
            image.thumbnail_key
        )


# =========================================================
# 生写真一覧
# =========================================================

@photo_bp.route('/index/<group_key>')
@login_required
@group_required
def index(group_key):

    group = Group.query.filter_by(
        key=group_key
    ).first_or_404()

    page = request.args.get(
        "page",
        1,
        type=int
    )

    per_page = 30

    selected_member = request.args.get(
        "member",
        ""
    ).strip()

    selected_costume = request.args.get(
        "costume",
        ""
    ).strip()

    query = request.args.get(
        "query",
        ""
    ).strip()

    favorite_only = (
        request.args.get("favorite") == "1"
    )

    # =====================================================
    # 並び順
    #
    # comp     = コンプ率
    # quantity = 枚数
    # favorite = お気に入り優先
    # name     = 名前の順
    #
    # デフォルトは「名前の順」
    # =====================================================

    sort = request.args.get(
        "sort",
        "name"
    ).strip()

    allowed_sorts = {
        "comp",
        "quantity",
        "favorite",
        "name"
    }

    if sort not in allowed_sorts:
        sort = "name"

    # =====================================================
    # 集計用SQL式
    # =====================================================

    total_types_expr = func.count(
        Photo.id
    )

    owned_types_expr = func.count(
        func.distinct(
            case(
                (
                    UserPhoto.quantity > 0,
                    Photo.type_id
                )
            )
        )
    )

    # お気に入りが1件でもあれば1
    favorite_expr = func.max(
        case(
            (
                UserPhoto.is_favorite.is_(True),
                1
            ),
            else_=0
        )
    )

    # コンプ率用
    #
    # Float化することで、
    # PostgreSQL等でも整数除算にならないようにする。
    # =====================================================

    from sqlalchemy import cast, Float

    comp_rate_expr = (
        cast(
            owned_types_expr,
            Float
        )
        /
        func.nullif(
            total_types_expr,
            0
        )
    )

    # =========================================================
    # Member × Costume 集計
    # =========================================================

    summary_query = (
        db.session.query(
            Member.id.label(
                "member_id"
            ),

            Member.name.label(
                "member_name"
            ),

            Member.generation.label(
                "member_generation"
            ),

            Member.display_order.label(
                "member_display_order"
            ),

            Costume.id.label(
                "costume_id"
            ),

            Costume.name.label(
                "costume_name"
            ),

            total_types_expr.label(
                "total_types"
            ),

            owned_types_expr.label(
                "owned_types"
            ),

            favorite_expr.label(
                "has_favorite"
            )
        )

        .select_from(Photo)

        .join(
            Member,
            Member.id == Photo.member_id
        )

        .join(
            Costume,
            Costume.id == Photo.costume_id
        )

        .outerjoin(
            UserPhoto,
            (
                UserPhoto.photo_id == Photo.id
            )
            &
            (
                UserPhoto.user_id
                == current_user.id
            )
        )

        .filter(
            Member.group_id == group.id
        )

        .group_by(
            Member.id,
            Member.name,
            Member.generation,
            Member.display_order,
            Costume.id,
            Costume.name
        )
    )

    # =========================================================
    # フィルタ
    # =========================================================

    if selected_member:

        summary_query = summary_query.filter(
            Member.name.ilike(
                f"%{selected_member}%"
            )
        )

    if selected_costume:

        summary_query = summary_query.filter(
            Costume.name.ilike(
                f"%{selected_costume}%"
            )
        )

    if query:

        summary_query = summary_query.filter(
            db.or_(
                Member.name.ilike(
                    f"%{query}%"
                ),
                Costume.name.ilike(
                    f"%{query}%"
                )
            )
        )

    # =========================================================
    # お気に入りのみ
    # =========================================================

    if favorite_only:

        favorite_exists = (
            db.session.query(
                UserPhoto.id
            )

            .join(
                Photo,
                Photo.id == UserPhoto.photo_id
            )

            .filter(
                UserPhoto.user_id
                == current_user.id,

                UserPhoto.is_favorite.is_(True),

                Photo.member_id
                == Member.id,

                Photo.costume_id
                == Costume.id
            )

            .exists()
        )

        summary_query = summary_query.filter(
            favorite_exists
        )

    # =========================================================
    # 通常時のみ所持データ有りを表示
    # =========================================================

    summary_query = summary_query.having(
        func.count(
            UserPhoto.id
        ) > 0
    )

    # =========================================================
    # 並び順
    # =========================================================

    if sort == "comp":

        # コンプ率の高い順
        # 同率の場合：
        #   所持種類数
        #   メンバー順
        #   衣装名
        #
        summary_query = summary_query.order_by(
            comp_rate_expr.desc(),

            owned_types_expr.desc(),

            func.coalesce(
                Member.generation,
                0
            ),

            func.coalesce(
                Member.display_order,
                0
            ),

            Member.name,

            Costume.name
        )

    elif sort == "quantity":

        # 枚数（一覧上の所持種類数）の多い順
        #
        summary_query = summary_query.order_by(
            owned_types_expr.desc(),

            comp_rate_expr.desc(),

            func.coalesce(
                Member.generation,
                0
            ),

            func.coalesce(
                Member.display_order,
                0
            ),

            Member.name,

            Costume.name
        )

    elif sort == "favorite":

        # お気に入り優先
        #
        summary_query = summary_query.order_by(
            favorite_expr.desc(),

            func.coalesce(
                Member.generation,
                0
            ),

            func.coalesce(
                Member.display_order,
                0
            ),

            Member.name,

            Costume.name
        )

    else:

        # =====================================================
        # 名前の順
        #
        # stats_service.py と同じ考え方
        #
        # (generation or 0, display_order or 0)
        # =====================================================

        summary_query = summary_query.order_by(

            func.coalesce(
                Member.generation,
                0
            ),

            func.coalesce(
                Member.display_order,
                0
            ),

            Member.name,

            Costume.name
        )

    # =========================================================
    # ページネーション
    # =========================================================

    pagination_obj = summary_query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    display_rows = pagination_obj.items

    # =========================================================
    # 詳細取得
    # =========================================================

    target_pairs = [
        (
            r.member_id,
            r.costume_id
        )
        for r in display_rows
    ]

    member_ids = list({
        r.member_id
        for r in display_rows
    })

    costume_ids = list({
        r.costume_id
        for r in display_rows
    })

    details_rows = []

    if member_ids and costume_ids:

        details_rows = (
            db.session.query(
                UserPhoto
            )

            .join(Photo)

            .options(
                joinedload(
                    UserPhoto.photo
                )
                .joinedload(
                    Photo.photo_type
                ),

                joinedload(
                    UserPhoto.images
                )
            )

            .filter(
                UserPhoto.user_id
                == current_user.id,

                Photo.member_id.in_(
                    member_ids
                ),

                Photo.costume_id.in_(
                    costume_ids
                )
            )

            .all()
        )

    details_map = defaultdict(list)

    for up in details_rows:

        key = (
            up.photo.member_id,
            up.photo.costume_id
        )

        images = []

        for image in up.images:

            try:

                images.append({
                    "id": image.id,

                    "image_url":
                        get_image_url(
                            image.image_key
                        ),

                    "thumbnail_url":
                        get_thumbnail_url(
                            image.thumbnail_key
                        ),

                    "width":
                        image.width,

                    "height":
                        image.height,
                })

            except Exception:

                current_app.logger.exception(
                    "Failed to generate image URL: "
                    "user_photo_image_id=%s",
                    image.id
                )

        details_map[key].append({

            "id":
                up.id,

            "type":
                up.photo.photo_type.name,

            "quantity":
                up.quantity,

            "available":
                up.available_quantity,

            "memo":
                up.memo or "",

            "date":
                (
                    up.date.strftime(
                        "%Y-%m-%d"
                    )
                    if up.date
                    else ""
                ),

            "is_favorite":
                bool(
                    up.is_favorite
                ),

            "images":
                images,

            "image_count":
                len(images),
        })

    # =========================================================
    # カード生成
    # =========================================================

    cards = []

    for row in display_rows:

        details = details_map.get(
            (
                row.member_id,
                row.costume_id
            ),
            []
        )

        cards.append({

            "member":
                row.member_name,

            "costume":
                row.costume_name,

            "owned":
                row.owned_types,

            "total":
                row.total_types,

            "rate":
                round(
                    (
                        row.owned_types
                        /
                        row.total_types
                        *
                        100
                    ),
                    1
                )
                if row.total_types
                else 0,

            "is_complete":
                (
                    row.owned_types
                    == row.total_types
                ),

            "details":
                details,

            "has_favorite":
                bool(
                    row.has_favorite
                )
        })

    # =========================================================
    # TomSelect用
    # =========================================================

    members = (
        db.session.query(
            Member.name
        )

        .filter_by(
            group_id=group.id
        )

        .distinct()

        .order_by(
            Member.name
        )

        .all()
    )

    costumes = (
        db.session.query(
            Costume.name
        )

        .filter_by(
            group_id=group.id
        )

        .distinct()

        .order_by(
            Costume.name
        )

        .all()
    )

    members_list = [
        m[0]
        for m in members
    ]

    costumes_list = [
        c[0]
        for c in costumes
    ]

    # =========================================================
    # ページネーション用引数
    # =========================================================

    args = request.args.to_dict()

    args.pop(
        "page",
        None
    )

    current_filters = {

        "query":
            query,

        "member":
            selected_member,

        "costume":
            selected_costume,

        "sort":
            sort
    }

    # =========================================================
    # 表示
    # =========================================================

    return render_template(

        "index.html",

        group_key=group_key,

        cards=cards,

        pagination=pagination_obj,

        members=members_list,

        costumes=costumes_list,

        args=args,

        current_filters=current_filters,

        selected_member=
            selected_member,

        selected_costume=
            selected_costume,

        query=query,

        favorite_only=
            favorite_only,

        selected_sort=
            sort,

        current_url=
            request.full_path
    )

# =========================================================
# 生写真削除
# =========================================================

@photo_bp.route(
    '/delete_user_photo/<group_key>/<int:photo_id>',
    methods=['POST']
)
@login_required
@group_required
def delete_user_photo(group_key, photo_id):

    group = Group.query.filter_by(
        key=group_key
    ).first_or_404()

    photo = (
        UserPhoto.query
        .options(joinedload(UserPhoto.images))
        .filter_by(
            id=photo_id,
            user_id=current_user.id
        )
        .first_or_404()
    )

    # 所有チェック
    if photo.user_id != current_user.id:
        flash('あなたの写真ではありません。', 'error')
        current_app.logger.debug(
            "[DEBUG] user mismatch: "
            "photo.user_id=%s, current_user.id=%s",
            photo.user_id,
            current_user.id
        )
        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # グループ整合性チェック
    if photo.photo.member.group_id != group.id:
        flash('グループキーが不正です。', 'error')
        current_app.logger.debug(
            "[DEBUG] group mismatch: "
            "photo_group_id=%s, expected_group_id=%s",
            photo.photo.member.group_id,
            group.id
        )
        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # R2画像を先に削除
    try:
        _delete_user_photo_images_from_r2(photo)
    except Exception:
        current_app.logger.exception(
            "Failed to delete R2 images before deleting UserPhoto: "
            "user_photo_id=%s",
            photo.id
        )
        flash(
            '画像の削除に失敗したため、生写真を削除できませんでした。',
            'error'
        )
        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # DB削除
    try:
        db.session.delete(photo)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Failed to delete UserPhoto: id=%s",
            photo_id
        )
        flash('生写真の削除に失敗しました。', 'error')
        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    flash('生写真を削除しました。', 'success')

    current_app.logger.debug(
        "[DEBUG] Deleted photo id=%s, user_id=%s, group_key=%s",
        photo_id,
        current_user.id,
        group_key
    )

    return redirect(
        url_for(
            'photo.index',
            group_key=group_key
        )
    )


# =========================================================
# 実物画像削除
# =========================================================

@photo_bp.route(
    '/delete_user_photo_image/<group_key>/<int:image_id>',
    methods=['POST']
)
@login_required
@group_required
def delete_user_photo_image(group_key, image_id):

    group = Group.query.filter_by(
        key=group_key
    ).first_or_404()

    # =====================================================
    # 対象画像取得
    # =====================================================

    image = (
        UserPhotoImage.query
        .options(
            joinedload(
                UserPhotoImage.user_photo
            )
            .joinedload(
                UserPhoto.photo
            )
            .joinedload(
                Photo.member
            )
        )
        .filter_by(
            id=image_id,
            user_id=current_user.id
        )
        .first_or_404()
    )

    user_photo = image.user_photo

    # =====================================================
    # 所有チェック
    # =====================================================

    if image.user_id != current_user.id:

        flash(
            'あなたの実物画像ではありません。',
            'error'
        )

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    if user_photo.user_id != current_user.id:

        flash(
            'あなたの生写真ではありません。',
            'error'
        )

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # =====================================================
    # グループ整合性チェック
    # =====================================================

    if user_photo.photo.member.group_id != group.id:

        flash(
            'グループキーが不正です。',
            'error'
        )

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # =====================================================
    # R2から画像を削除
    # =====================================================

    try:

        delete_image_variants(
            image.image_key,
            image.thumbnail_key
        )

    except Exception:

        current_app.logger.exception(
            "Failed to delete R2 objects for "
            "UserPhotoImage: id=%s, "
            "user_photo_id=%s",
            image.id,
            user_photo.id
        )

        flash(
            '画像ファイルの削除に失敗したため、'
            '実物画像を削除できませんでした。',
            'error'
        )

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # =====================================================
    # DBから画像レコードを削除
    # =====================================================

    try:

        db.session.delete(image)
        db.session.commit()

    except Exception:

        db.session.rollback()

        current_app.logger.exception(
            "Failed to delete UserPhotoImage DB record: "
            "id=%s",
            image_id
        )

        flash(
            '実物画像の削除に失敗しました。',
            'error'
        )

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # =====================================================
    # 完了
    # =====================================================

    flash(
        '実物画像を削除しました。',
        'success'
    )

    current_app.logger.debug(
        "[DEBUG] Deleted UserPhotoImage "
        "id=%s, user_id=%s, user_photo_id=%s, "
        "group_key=%s",
        image_id,
        current_user.id,
        user_photo.id,
        group_key
    )

    return redirect(
        url_for(
            'photo.index',
            group_key=group_key
        )
    )


# =========================================================
# 実物画像アップロード
# =========================================================

@photo_bp.route(
    '/upload_user_photo_image/<group_key>/<int:photo_id>',
    methods=['POST']
)
@login_required
@group_required
def upload_user_photo_image(group_key, photo_id):

    group = Group.query.filter_by(
        key=group_key
    ).first_or_404()

    photo = (
        UserPhoto.query
        .filter_by(
            id=photo_id,
            user_id=current_user.id
        )
        .first_or_404()
    )

    # グループ整合性チェック
    if photo.photo.member.group_id != group.id:
        flash('グループキーが不正です。', 'error')
        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # =====================================================
    # フォーム
    # =====================================================

    from forms import UserPhotoImageUploadForm

    form = UserPhotoImageUploadForm()

    if not form.validate_on_submit():
        for errors in form.errors.values():
            for error in errors:
                flash(error, 'error')

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    uploaded_file = form.image.data

    if uploaded_file is None:
        flash('画像ファイルを選択してください。', 'error')
        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # =====================================================
    # ファイル読み込み
    # =====================================================

    try:
        file_bytes = uploaded_file.read()
    except Exception:
        current_app.logger.exception(
            "Failed to read uploaded image"
        )
        flash('画像ファイルの読み込みに失敗しました。', 'error')
        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    if not file_bytes:
        flash('画像ファイルが空です。', 'error')
        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # =====================================================
    # WebP変換
    #
    # ここで実際にR2へ保存されるサイズを計算する。
    # 容量制限は「元画像」ではなく、
    # display + thumbnail の合計サイズで判定。
    # =====================================================

    try:
        variants = create_image_variants(file_bytes)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )
    except Exception:
        current_app.logger.exception(
            "Failed to create image variants"
        )
        flash('画像の処理に失敗しました。', 'error')
        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    image_bytes = variants["image_bytes"]
    thumbnail_bytes = variants["thumbnail_bytes"]

    additional_bytes = (
        len(image_bytes)
        + len(thumbnail_bytes)
    )

    # =====================================================
    # ユーザー容量チェック
    # =====================================================

    if not current_user.can_upload_image():
        flash(
            '現在のプランでは実物画像をアップロードできません。',
            'error'
        )
        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    if not current_user.can_upload_image_bytes(
        additional_bytes
    ):
        remaining_bytes = (
            current_user.get_remaining_image_storage_bytes()
        )

        remaining_mb = max(
            0,
            round(
                remaining_bytes / (1024 * 1024),
                1
            )
        )

        flash(
            f'画像容量の上限を超えるためアップロードできません。'
            f'残り容量は約{remaining_mb}MBです。',
            'error'
        )

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # =====================================================
    # R2オブジェクトキー作成
    # =====================================================

    image_key, thumbnail_key = generate_object_keys(
        user_id=current_user.id,
        user_photo_id=photo.id,
    )

    image_uploaded = False
    thumbnail_uploaded = False

    try:

        # -------------------------------------------------
        # R2へ表示用画像を保存
        # -------------------------------------------------

        upload_bytes(
            image_bytes,
            image_key,
            variants["mime_type"]
        )

        image_uploaded = True

        # -------------------------------------------------
        # R2へサムネイルを保存
        # -------------------------------------------------

        upload_bytes(
            thumbnail_bytes,
            thumbnail_key,
            variants["mime_type"]
        )

        thumbnail_uploaded = True

        # -------------------------------------------------
        # DBへメタデータ保存
        # -------------------------------------------------

        image_record = UserPhotoImage(
            user_id=current_user.id,
            user_photo_id=photo.id,
            image_key=image_key,
            thumbnail_key=thumbnail_key,
            file_size=len(image_bytes),
            thumbnail_file_size=len(thumbnail_bytes),
            mime_type=variants["mime_type"],
            width=variants["width"],
            height=variants["height"],
        )

        db.session.add(image_record)
        db.session.commit()

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            "Failed to save user photo image: "
            "user_id=%s, user_photo_id=%s",
            current_user.id,
            photo.id
        )

        # R2側に保存済みならロールバック
        if image_uploaded or thumbnail_uploaded:
            try:
                delete_image_variants(
                    image_key if image_uploaded else None,
                    thumbnail_key if thumbnail_uploaded else None
                )
            except Exception:
                current_app.logger.exception(
                    "Failed to rollback R2 objects: "
                    "image_key=%s, thumbnail_key=%s",
                    image_key,
                    thumbnail_key
                )

        flash(
            '画像のアップロードに失敗しました。',
            'error'
        )

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    flash(
        '実物画像をアップロードしました。',
        'success'
    )

    return redirect(
        url_for(
            'photo.index',
            group_key=group_key
        )
    )


# =========================================================
# 生写真追加
# =========================================================

@photo_bp.route('/add/<group_key>', methods=['GET', 'POST'])
@login_required
@group_required
def add(group_key):

    group = Group.query.filter_by(
        key=group_key
    ).first_or_404()

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
            quantity = int(
                request.form.get(
                    'quantity',
                    1
                )
            )
        except (TypeError, ValueError):
            quantity = 1

        # バリデーション
        if not member or not costume or not type_name:
            flash('入力が不正です', 'error')
            return redirect(
                url_for(
                    'photo.add',
                    group_key=group_key
                )
            )

        # 対象photo取得
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
            flash(
                '該当する写真が見つかりません',
                'error'
            )
            return redirect(
                url_for(
                    'photo.add',
                    group_key=group_key
                )
            )

        # =====================================================
        # 実物画像取得
        #
        # 画像は任意項目なので、
        # ファイルが選択されていない場合は従来通り追加する。
        # =====================================================

        uploaded_file = request.files.get('image')

        has_image = bool(
            uploaded_file
            and uploaded_file.filename
        )

        variants = None
        image_bytes = None
        thumbnail_bytes = None

        # =====================================================
        # 画像処理
        # =====================================================

        if has_image:

            try:
                file_bytes = uploaded_file.read()
            except Exception:
                current_app.logger.exception(
                    "Failed to read uploaded image "
                    "while adding UserPhoto"
                )

                flash(
                    '画像ファイルの読み込みに失敗しました。',
                    'error'
                )

                return redirect(
                    url_for(
                        'photo.add',
                        group_key=group_key,
                        member=member,
                        costume=costume
                    )
                )

            if not file_bytes:

                flash(
                    '画像ファイルが空です。',
                    'error'
                )

                return redirect(
                    url_for(
                        'photo.add',
                        group_key=group_key,
                        member=member,
                        costume=costume
                    )
                )

            # -------------------------------------------------
            # WebP変換
            # -------------------------------------------------

            try:
                variants = create_image_variants(
                    file_bytes
                )
            except ValueError as exc:

                flash(
                    str(exc),
                    'error'
                )

                return redirect(
                    url_for(
                        'photo.add',
                        group_key=group_key,
                        member=member,
                        costume=costume
                    )
                )

            except Exception:

                current_app.logger.exception(
                    "Failed to create image variants "
                    "while adding UserPhoto"
                )

                flash(
                    '画像の処理に失敗しました。',
                    'error'
                )

                return redirect(
                    url_for(
                        'photo.add',
                        group_key=group_key,
                        member=member,
                        costume=costume
                    )
                )

            image_bytes = variants["image_bytes"]
            thumbnail_bytes = variants["thumbnail_bytes"]

            additional_bytes = (
                len(image_bytes)
                + len(thumbnail_bytes)
            )

            # -------------------------------------------------
            # アップロード可能か確認
            # -------------------------------------------------

            if not current_user.can_upload_image():

                flash(
                    '現在のプランでは実物画像をアップロードできません。',
                    'error'
                )

                return redirect(
                    url_for(
                        'photo.add',
                        group_key=group_key,
                        member=member,
                        costume=costume
                    )
                )

            # -------------------------------------------------
            # 容量チェック
            #
            # DBを変更する前にチェックする。
            # -------------------------------------------------

            if not current_user.can_upload_image_bytes(
                additional_bytes
            ):

                remaining_bytes = (
                    current_user
                    .get_remaining_image_storage_bytes()
                )

                remaining_mb = max(
                    0,
                    round(
                        remaining_bytes
                        / (1024 * 1024),
                        1
                    )
                )

                flash(
                    f'画像容量の上限を超えるため'
                    f'アップロードできません。'
                    f'残り容量は約{remaining_mb}MBです。',
                    'error'
                )

                return redirect(
                    url_for(
                        'photo.add',
                        group_key=group_key,
                        member=member,
                        costume=costume
                    )
                )

        # =====================================================
        # 既存チェック
        # =====================================================

        existing = UserPhoto.query.filter_by(
            user_id=current_user.id,
            photo_id=photo.id
        ).first()

        user_photo = existing

        if existing:

            # -------------------------------------------------
            # 既存の生写真
            # -------------------------------------------------

            existing.quantity += quantity

        else:

            # -------------------------------------------------
            # 新規の生写真
            # -------------------------------------------------

            user_photo = UserPhoto(
                user_id=current_user.id,
                photo_id=photo.id,
                quantity=quantity
            )

            db.session.add(user_photo)

            # -------------------------------------------------
            # UserPhoto.idを取得する
            #
            # R2のオブジェクトキーに使用するため、
            # ここでflushする。
            # -------------------------------------------------

            try:
                db.session.flush()

            except Exception:

                db.session.rollback()

                current_app.logger.exception(
                    "Failed to create UserPhoto "
                    "while adding photo"
                )

                flash(
                    '生写真の追加に失敗しました。',
                    'error'
                )

                return redirect(
                    url_for(
                        'photo.add',
                        group_key=group_key,
                        member=member,
                        costume=costume
                    )
                )

        # =====================================================
        # R2への画像保存
        # =====================================================

        image_key = None
        thumbnail_key = None

        image_uploaded = False
        thumbnail_uploaded = False

        if has_image:

            # -------------------------------------------------
            # R2オブジェクトキー生成
            # -------------------------------------------------

            image_key, thumbnail_key = generate_object_keys(
                user_id=current_user.id,
                user_photo_id=user_photo.id,
            )

            try:

                # -------------------------------------------------
                # 表示用画像
                # -------------------------------------------------

                upload_bytes(
                    image_bytes,
                    image_key,
                    variants["mime_type"]
                )

                image_uploaded = True

                # -------------------------------------------------
                # サムネイル
                # -------------------------------------------------

                upload_bytes(
                    thumbnail_bytes,
                    thumbnail_key,
                    variants["mime_type"]
                )

                thumbnail_uploaded = True

                # -------------------------------------------------
                # DBへ画像メタデータ保存
                # -------------------------------------------------

                image_record = UserPhotoImage(
                    user_id=current_user.id,
                    user_photo_id=user_photo.id,
                    image_key=image_key,
                    thumbnail_key=thumbnail_key,
                    file_size=len(image_bytes),
                    thumbnail_file_size=len(
                        thumbnail_bytes
                    ),
                    mime_type=variants["mime_type"],
                    width=variants["width"],
                    height=variants["height"],
                )

                db.session.add(image_record)

            except Exception:

                db.session.rollback()

                current_app.logger.exception(
                    "Failed to save image while adding "
                    "UserPhoto: user_id=%s, "
                    "user_photo_id=%s",
                    current_user.id,
                    user_photo.id
                )

                # -------------------------------------------------
                # R2ロールバック
                # -------------------------------------------------

                if image_uploaded or thumbnail_uploaded:

                    try:

                        delete_image_variants(
                            image_key
                            if image_uploaded
                            else None,
                            thumbnail_key
                            if thumbnail_uploaded
                            else None
                        )

                    except Exception:

                        current_app.logger.exception(
                            "Failed to rollback R2 objects "
                            "while adding UserPhoto: "
                            "image_key=%s, "
                            "thumbnail_key=%s",
                            image_key,
                            thumbnail_key
                        )

                flash(
                    '画像のアップロードに失敗したため、'
                    '生写真を追加できませんでした。',
                    'error'
                )

                return redirect(
                    url_for(
                        'photo.add',
                        group_key=group_key,
                        member=member,
                        costume=costume
                    )
                )

        # =====================================================
        # UserPhoto + UserPhotoImageを確定
        # =====================================================

        try:

            db.session.commit()

        except Exception:

            db.session.rollback()

            current_app.logger.exception(
                "Failed to commit UserPhoto addition: "
                "user_id=%s, photo_id=%s",
                current_user.id,
                photo.id
            )

            # -------------------------------------------------
            # DB保存失敗時のR2ロールバック
            # -------------------------------------------------

            if image_uploaded or thumbnail_uploaded:

                try:

                    delete_image_variants(
                        image_key
                        if image_uploaded
                        else None,
                        thumbnail_key
                        if thumbnail_uploaded
                        else None
                    )

                except Exception:

                    current_app.logger.exception(
                        "Failed to rollback R2 objects "
                        "after UserPhoto commit failure: "
                        "image_key=%s, "
                        "thumbnail_key=%s",
                        image_key,
                        thumbnail_key
                    )

            flash(
                '生写真の追加に失敗しました。',
                'error'
            )

            return redirect(
                url_for(
                    'photo.add',
                    group_key=group_key,
                    member=member,
                    costume=costume
                )
            )

        # =====================================================
        # 完了
        # =====================================================

        if has_image:

            flash(
                '生写真と実物画像を追加しました。',
                'success'
            )

        else:

            flash(
                '追加しました',
                'success'
            )

        # =====================================================
        # 連続追加モード対応
        # =====================================================

        if request.form.get(
            "continuous_mode"
        ) == "on":

            return redirect(
                url_for(
                    'photo.add',
                    group_key=group_key,
                    member=member,
                    costume=costume
                )
            )

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # =========================
    # GET（画面表示）
    # =========================

    return render_template(
        'add.html',
        form=form,
        group_key=group_key
    )


# =========================================================
# 生写真をあげる
# =========================================================

@photo_bp.route('/give/<group_key>', methods=['GET', 'POST'])
@login_required
@group_required
def give(group_key):

    group = Group.query.filter_by(
        key=group_key
    ).first_or_404()

    from forms import GiveawayPhotoForm
    form = GiveawayPhotoForm()

    if form.validate_on_submit():

        user_photo = (
            db.session.query(UserPhoto)
            .options(
                joinedload(UserPhoto.images)
            )
            .join(Photo, Photo.id == UserPhoto.photo_id)
            .join(Member, Member.id == Photo.member_id)
            .join(Costume, Costume.id == Photo.costume_id)
            .join(PhotoType, PhotoType.id == Photo.type_id)
            .filter(
                UserPhoto.user_id == current_user.id,
                Member.group_id == group.id,
                Member.name == form.member.data,
                Costume.name == form.costume.data,
                PhotoType.name == form.photo_type.data
            )
            .first()
        )

        if (
            not user_photo
            or user_photo.quantity < form.quantity.data
        ):
            flash(
                '所持していない写真、または所持枚数を超える枚数はあげられません。',
                'error'
            )

            return redirect(
                url_for(
                    'photo.give',
                    group_key=group_key
                )
            )

        user_photo.quantity -= form.quantity.data

        user_photo.available_quantity = min(
            user_photo.available_quantity,
            user_photo.quantity
        )

        # 枚数0ならUserPhoto自体を削除
        if user_photo.quantity == 0:

            # R2画像も削除
            try:
                _delete_user_photo_images_from_r2(
                    user_photo
                )
            except Exception:
                current_app.logger.exception(
                    "Failed to delete R2 images when "
                    "giving away all photos: user_photo_id=%s",
                    user_photo.id
                )

                db.session.rollback()

                flash(
                    '画像の削除に失敗したため、写真をあげる処理を中止しました。',
                    'error'
                )

                return redirect(
                    url_for(
                        'photo.give',
                        group_key=group_key
                    )
                )

            db.session.delete(user_photo)

        try:
            db.session.commit()

        except Exception:
            db.session.rollback()

            current_app.logger.exception(
                'Failed to give away photo'
            )

            flash(
                '生写真をあげる処理に失敗しました。',
                'error'
            )

            return redirect(
                url_for(
                    'photo.give',
                    group_key=group_key
                )
            )

        flash(
            '生写真をあげました。',
            'success'
        )

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    if request.method == 'POST':

        for errors in form.errors.values():
            for error in errors:
                flash(error, 'error')

    return render_template(
        'give.html',
        form=form,
        group_key=group_key
    )


# =========================================================
# メンバー取得
# =========================================================

@photo_bp.route('/get_members')
@login_required
def get_members():

    group = request.args.get('group')

    g = Group.query.filter_by(
        key=group
    ).first()

    if not g:
        return jsonify({
            "members": []
        })

    from services.photo_service import get_members

    return jsonify({
        "members": get_members(g.id)
    })


# =========================================================
# 衣装取得
# =========================================================

@photo_bp.route('/get_costumes')
@login_required
def get_costumes():

    group = request.args.get('group')
    member = request.args.get('member')

    g = Group.query.filter_by(
        key=group
    ).first()

    if not g:
        return jsonify({
            "costumes": []
        })

    from services.photo_service import get_costumes

    return jsonify({
        "costumes": get_costumes(
            g.id,
            member
        )
    })


# =========================================================
# 種類取得
# =========================================================

@photo_bp.route('/get_types')
@login_required
def get_types():

    group = request.args.get('group')
    member = request.args.get('member')
    costume = request.args.get('costume')

    g = Group.query.filter_by(
        key=group
    ).first()

    if not g:
        return jsonify({
            "types": []
        })

    from services.photo_service import get_types

    return jsonify({
        "types": get_types(
            g.id,
            member,
            costume
        )
    })


# =========================================================
# 所持メンバー取得
# =========================================================

def _owned_group_from_request():

    group_key = request.args.get(
        'group'
    )

    group = Group.query.filter_by(
        key=group_key
    ).first()

    if not group:
        abort(404)

    if not current_user.can_access_group(
        group_key
    ):
        abort(403)

    return group


@photo_bp.route('/get_owned_members')
@login_required
def get_owned_members():

    group = _owned_group_from_request()

    from services.photo_service import (
        get_owned_members as find_owned_members
    )

    return jsonify({
        'members': find_owned_members(
            current_user.id,
            group.id
        )
    })


# =========================================================
# 所持衣装取得
# =========================================================

@photo_bp.route('/get_owned_costumes')
@login_required
def get_owned_costumes():

    group = _owned_group_from_request()

    member = request.args.get(
        'member',
        ''
    ).strip()

    if not member:
        return jsonify({
            'costumes': []
        })

    from services.photo_service import (
        get_owned_costumes as find_owned_costumes
    )

    return jsonify({
        'costumes': find_owned_costumes(
            current_user.id,
            group.id,
            member
        )
    })


# =========================================================
# 所持種類取得
# =========================================================

@photo_bp.route('/get_owned_types')
@login_required
def get_owned_types():

    group = _owned_group_from_request()

    member = request.args.get(
        'member',
        ''
    ).strip()

    costume = request.args.get(
        'costume',
        ''
    ).strip()

    if not member or not costume:
        return jsonify({
            'types': []
        })

    from services.photo_service import (
        get_owned_types as find_owned_types
    )

    return jsonify({
        'types': find_owned_types(
            current_user.id,
            group.id,
            member,
            costume
        )
    })


# =========================================================
# 生写真情報更新
# =========================================================

@photo_bp.route(
    '/update_user_photo/<group_key>/<int:photo_id>',
    methods=['POST']
)
@login_required
@group_required
def update_user_photo(group_key, photo_id):

    photo = UserPhoto.query.filter_by(
        id=photo_id,
        user_id=current_user.id
    ).first_or_404()

    if not photo or photo.user_id != current_user.id:

        flash(
            '更新できませんでした',
            'error'
        )

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    # グループ整合性チェック
    group = Group.query.filter_by(
        key=group_key
    ).first_or_404()

    if photo.photo.member.group_id != group.id:
        flash(
            'グループキーが不正です。',
            'error'
        )

        return redirect(
            url_for(
                'photo.index',
                group_key=group_key
            )
        )

    try:

        quantity = int(
            request.form.get(
                'quantity',
                1
            )
        )

        available = int(
            request.form.get(
                'available_quantity',
                0
            )
        )

        memo = request.form.get(
            'memo',
            ''
        ).strip()

        # お気に入り
        is_favorite = (
            request.form.get(
                "is_favorite"
            ) == "on"
        )

        # 日付
        date_str = request.form.get(
            'date'
        )

        if date_str:
            photo.date = date.fromisoformat(
                date_str
            )
        else:
            photo.date = None

        # バリデーション
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

        # =================================================
        # 枚数0の場合
        # =================================================

        if quantity == 0:

            photo = (
                UserPhoto.query
                .options(
                    joinedload(UserPhoto.images)
                )
                .filter_by(
                    id=photo_id,
                    user_id=current_user.id
                )
                .first()
            )

            if photo:

                try:
                    _delete_user_photo_images_from_r2(
                        photo
                    )
                except Exception:
                    db.session.rollback()

                    current_app.logger.exception(
                        "Failed to delete R2 images "
                        "when quantity became zero: "
                        "user_photo_id=%s",
                        photo.id
                    )

                    flash(
                        '画像の削除に失敗したため、更新できませんでした。',
                        'error'
                    )

                    return redirect(
                        url_for(
                            'photo.index',
                            group_key=group_key
                        )
                    )

                db.session.delete(photo)

        db.session.commit()

        flash(
            '更新しました',
            'success'
        )

    except Exception:

        db.session.rollback()

        current_app.logger.exception(
            'Failed to update UserPhoto: id=%s',
            photo_id
        )

        flash(
            '更新エラー',
            'error'
        )

    return redirect(
        url_for(
            'photo.index',
            group_key=group_key
        )
    )