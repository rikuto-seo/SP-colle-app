# routes/admin_photos.py

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    abort
)

from flask_login import (
    login_required,
    current_user
)

from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from extensions import db

from models import (
    Group,
    Member,
    Costume,
    Photo,
    PhotoType,
    CostumeTypeNormalization
)


admin_photos_bp = Blueprint(
    "admin_photos",
    __name__,
    url_prefix="/admin/photos"
)


#
# 統計上の種類
#

NORMALIZED_TYPES = (
    "ヨリ",
    "チュウ",
    "ヒキ",
    "座り",
)


#
# 管理者チェック
#

def admin_required():

    if not current_user.is_authenticated:
        abort(403)

    # あなただけ許可
    if current_user.id != 1:
        abort(403)


#
# INDEX
#

@admin_photos_bp.route("", methods=["GET"])
@login_required
def index():

    admin_required()

    groups = (
        Group.query
        .order_by(Group.id.asc())
        .all()
    )

    group_id = request.args.get(
        "group_id",
        type=int
    )

    selected_group = None
    costumes = []
    members = []

    photo_types = (
        PhotoType.query
        .order_by(PhotoType.id.asc())
        .all()
    )

    if group_id:

        selected_group = Group.query.get_or_404(
            group_id
        )

        costumes = (
            Costume.query
            .filter_by(group_id=group_id)
            .order_by(Costume.id.desc())
            .all()
        )

        members = (
            Member.query
            .filter_by(group_id=group_id)
            .order_by(
                Member.generation.asc(),
                Member.display_order.asc()
            )
            .all()
        )

    return render_template(
        "admin/photos.html",
        group_list=groups,
        selected_group=selected_group,
        costumes=costumes,
        members=members,
        photo_types=photo_types,
        normalized_types=NORMALIZED_TYPES,
    )


#
# LIST
# アコーディオン開いた時のみ呼ばれる
#

@admin_photos_bp.route("/list", methods=["GET"])
@login_required
def photo_list():

    admin_required()

    group_id = request.args.get(
        "group_id",
        type=int
    )

    page = request.args.get(
        "page",
        default=1,
        type=int
    )

    per_page = request.args.get(
        "per_page",
        default=200,
        type=int
    )

    if not group_id:

        return jsonify({
            "items": [],
            "has_next": False,
            "total": 0
        })

    query = (
        Photo.query
        .options(
            joinedload(Photo.member),
            joinedload(Photo.costume),
            joinedload(Photo.photo_type)
        )
        .join(
            Member,
            Member.id == Photo.member_id
        )
        .join(
            Costume,
            Costume.id == Photo.costume_id
        )
        .filter(
            Member.group_id == group_id
        )
        .filter(
            Costume.group_id == group_id
        )
    )

    pagination = (
        query
        .order_by(
            Costume.id.desc(),
            Member.display_order.asc(),
            Photo.type_id.asc(),
            Photo.id.asc()
        )
        .paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
    )

    result = []

    for photo in pagination.items:

        result.append({
            "id": photo.id,
            "member_name": photo.member.name,
            "costume_name": photo.costume.name,
            "type_name": photo.photo_type.name
        })

    return jsonify({
        "items": result,
        "has_next": pagination.has_next,
        "total": pagination.total
    })


#
# CREATE COSTUME
#

@admin_photos_bp.route(
    "/create_costume",
    methods=["POST"]
)
@login_required
def create_costume():

    admin_required()

    print("FORM =", request.form)
    print("NAME =", request.form.get("name"))
    print("GROUP_ID =", request.form.get("group_id"))
    print(request.form)

    name = request.form.get(
        "name",
        ""
    ).strip()

    group_id = request.form.get(
        "group_id",
        type=int
    )

    if not name:

        return jsonify({
            "success": False,
            "error": "costume name required"
        }), 400

    if not group_id:

        return jsonify({
            "success": False,
            "error": "group_id required"
        }), 400

    exists = (
        Costume.query
        .filter_by(
            name=name,
            group_id=group_id
        )
        .first()
    )

    if exists:

        return jsonify({
            "success": True,
            "costume_id": exists.id,
            "already_exists": True
        })

    costume = Costume(
        name=name,
        group_id=group_id
    )

    db.session.add(costume)
    db.session.commit()

    return jsonify({
        "success": True,
        "costume_id": costume.id
    })


#
# CREATE TYPE
#
# PhotoTypeを新規作成する。
#
# 例:
#
#   01
#   02
#   03
#   04
#
# などのPhotoTypeを管理画面から追加する。
#
# PhotoType自体には
# 「ヨリ」「チュウ」「ヒキ」「座り」
# の意味を持たせない。
#
# 統計上の分類は、
# CostumeTypeNormalizationで
# 衣装ごとに別途設定する。
#

@admin_photos_bp.route(
    "/create_type",
    methods=["POST"]
)
@login_required
def create_type():

    admin_required()

    #
    # JSON / form の両方に対応
    #
    # 管理画面側の実装によって
    # request.form / request.get_json()
    # のどちらでも利用できるようにする。
    #

    data = request.get_json(
        silent=True
    )

    if isinstance(data, dict):

        name = data.get(
            "name",
            ""
        )

    else:

        name = request.form.get(
            "name",
            ""
        )

    #
    # 文字列として処理
    #

    if name is None:

        name = ""

    if not isinstance(name, str):

        return jsonify({
            "success": False,
            "error": "type name must be a string"
        }), 400

    name = name.strip()

    #
    # 空文字チェック
    #

    if not name:

        return jsonify({
            "success": False,
            "error": "type name required"
        }), 400

    #
    # 既存Type確認
    #
    # PhotoType.name はDB上でもuniqueだが、
    # 先に確認して正常系として返す。
    #

    exists = (
        PhotoType.query
        .filter_by(
            name=name
        )
        .first()
    )

    if exists:

        return jsonify({
            "success": True,
            "type_id": exists.id,
            "type_name": exists.name,
            "already_exists": True
        })

    #
    # 新規作成
    #

    photo_type = PhotoType(
        name=name
    )

    db.session.add(
        photo_type
    )

    try:

        db.session.commit()

    except IntegrityError:

        #
        # 同時リクエスト等によって
        # unique制約に引っかかった場合。
        #

        db.session.rollback()

        exists = (
            PhotoType.query
            .filter_by(
                name=name
            )
            .first()
        )

        if exists:

            return jsonify({
                "success": True,
                "type_id": exists.id,
                "type_name": exists.name,
                "already_exists": True
            })

        return jsonify({
            "success": False,
            "error": "failed to create type"
        }), 500

    return jsonify({
        "success": True,
        "type_id": photo_type.id,
        "type_name": photo_type.name,
        "already_exists": False
    })


#
# GET TYPE NORMALIZATIONS
#
# 指定した衣装に設定されている
# PhotoType → 統計上の種類
# を取得する
#

@admin_photos_bp.route(
    "/type_normalizations/<int:costume_id>",
    methods=["GET"]
)
@login_required
def get_type_normalizations(costume_id):

    admin_required()

    costume = Costume.query.get_or_404(
        costume_id
    )

    normalizations = (
        CostumeTypeNormalization.query
        .options(
            joinedload(
                CostumeTypeNormalization.photo_type
            )
        )
        .filter_by(
            costume_id=costume.id
        )
        .order_by(
            CostumeTypeNormalization.photo_type_id.asc()
        )
        .all()
    )

    result = {}

    for normalization in normalizations:

        result[str(
            normalization.photo_type_id
        )] = normalization.normalized_type

    return jsonify({
        "success": True,
        "costume_id": costume.id,
        "costume_name": costume.name,
        "normalizations": result
    })


#
# SAVE TYPE NORMALIZATIONS
#
# 指定した衣装について
# PhotoType → 統計上の種類
# を保存する
#

@admin_photos_bp.route(
    "/type_normalizations/<int:costume_id>",
    methods=["POST"]
)
@login_required
def save_type_normalizations(costume_id):

    admin_required()

    costume = Costume.query.get_or_404(
        costume_id
    )

    data = request.get_json(
        silent=True
    )

    if not data:

        return jsonify({
            "success": False,
            "error": "json required"
        }), 400

    normalizations = data.get(
        "normalizations",
        {}
    )

    if not isinstance(
        normalizations,
        dict
    ):

        return jsonify({
            "success": False,
            "error": "normalizations must be an object"
        }), 400

    #
    # PhotoTypeのIDを整数に変換し、
    # 値が許可された統計種類か確認
    #

    normalized_data = {}

    for photo_type_id, normalized_type in normalizations.items():

        try:
            photo_type_id = int(
                photo_type_id
            )
        except (TypeError, ValueError):

            return jsonify({
                "success": False,
                "error": "invalid photo_type_id"
            }), 400

        if normalized_type not in NORMALIZED_TYPES:

            return jsonify({
                "success": False,
                "error": (
                    f"invalid normalized_type: "
                    f"{normalized_type}"
                )
            }), 400

        normalized_data[
            photo_type_id
        ] = normalized_type

    #
    # 指定されたPhotoTypeが実在するか確認
    #

    if normalized_data:

        photo_types = (
            PhotoType.query
            .filter(
                PhotoType.id.in_(
                    normalized_data.keys()
                )
            )
            .all()
        )

        existing_type_ids = {
            photo_type.id
            for photo_type in photo_types
        }

        invalid_type_ids = (
            set(normalized_data.keys())
            - existing_type_ids
        )

        if invalid_type_ids:

            return jsonify({
                "success": False,
                "error": (
                    "invalid photo_type_id: "
                    + ", ".join(
                        map(
                            str,
                            sorted(invalid_type_ids)
                        )
                    )
                )
            }), 400

    #
    # 既存設定を取得
    #

    existing_rows = (
        CostumeTypeNormalization.query
        .filter_by(
            costume_id=costume.id
        )
        .all()
    )

    existing_by_type_id = {
        row.photo_type_id: row
        for row in existing_rows
    }

    #
    # 今回送信された設定を保存
    #
    # 同じPhotoTypeについて既存行があれば更新。
    # なければ新規作成。
    #

    for photo_type_id, normalized_type in normalized_data.items():

        row = existing_by_type_id.get(
            photo_type_id
        )

        if row:

            row.normalized_type = normalized_type

        else:

            db.session.add(
                CostumeTypeNormalization(
                    costume_id=costume.id,
                    photo_type_id=photo_type_id,
                    normalized_type=normalized_type
                )
            )

    #
    # 今回送信されなかった既存設定は削除
    #
    # これにより「未設定」に戻すことができる。
    #

    submitted_type_ids = set(
        normalized_data.keys()
    )

    for row in existing_rows:

        if row.photo_type_id not in submitted_type_ids:

            db.session.delete(row)

    db.session.commit()

    return jsonify({
        "success": True,
        "costume_id": costume.id,
        "saved": len(normalized_data)
    })


#
# BULK CREATE
#

@admin_photos_bp.route(
    "/bulk_create",
    methods=["POST"]
)
@login_required
def bulk_create():

    admin_required()

    data = request.get_json(
        silent=True
    )

    print("JSON =", data)

    if not data:

        return jsonify({
            "success": False,
            "error": "json required"
        }), 400

    member_ids = data.get(
        "member_ids",
        []
    )

    type_ids = data.get(
        "type_ids",
        []
    )

    costume_id = data.get(
        "costume_id"
    )

    if (
        not member_ids
        or
        not type_ids
        or
        not costume_id
    ):

        return jsonify({
            "success": False,
            "error": "invalid payload"
        }), 400

    created = 0
    skipped = 0

    existing = {
        (
            p.member_id,
            p.costume_id,
            p.type_id
        )
        for p in Photo.query.filter(
            Photo.costume_id == costume_id,
            Photo.member_id.in_(member_ids),
            Photo.type_id.in_(type_ids)
        ).all()
    }

    new_rows = []

    for member_id in member_ids:

        for type_id in type_ids:

            key = (
                member_id,
                costume_id,
                type_id
            )

            if key in existing:

                skipped += 1
                continue

            new_rows.append(
                Photo(
                    member_id=member_id,
                    costume_id=costume_id,
                    type_id=type_id
                )
            )

            created += 1

    if new_rows:

        db.session.bulk_save_objects(
            new_rows
        )

        db.session.commit()

    return jsonify({
        "success": True,
        "created": created,
        "skipped": skipped
    })


#
# DELETE
#

@admin_photos_bp.route(
    "/<int:photo_id>",
    methods=["DELETE"]
)
@login_required
def delete_photo(photo_id):

    admin_required()

    photo = Photo.query.get_or_404(
        photo_id
    )

    db.session.delete(photo)

    db.session.commit()

    return jsonify({
        "success": True
    })