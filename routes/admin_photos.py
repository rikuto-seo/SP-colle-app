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

from extensions import db

from models import (
    Group,
    Member,
    Costume,
    Photo,
    PhotoType
)

admin_photos_bp = Blueprint(
    "admin_photos",
    __name__,
    url_prefix="/admin/photos"
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

    print("==== GROUP DEBUG ====")

    for g in groups:
        print(
            g,
            g.id,
            g.key,
            g.name
        )

    print("=====================")

    group_id = request.args.get("group_id", type=int)

    selected_group = None
    costumes = []
    members = []

    photo_types = (
        PhotoType.query
        .order_by(PhotoType.id.asc())
        .all()
    )

    if group_id:

        selected_group = Group.query.get_or_404(group_id)

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
                Member.display_order.asc(),
                Member.id.asc()
            )
            .all()
        )

    return render_template(
        "admin/photos.html",
        groups=groups,
        selected_group=selected_group,
        costumes=costumes,
        members=members,
        photo_types=photo_types,
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
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .filter(Member.group_id == group_id)
        .filter(Costume.group_id == group_id)
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

@admin_photos_bp.route("/create_costume", methods=["POST"])
@login_required
def create_costume():

    admin_required()

    print("FORM =", request.form)
    print("NAME =", request.form.get("name"))
    print("GROUP_ID =", request.form.get("group_id"))

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
# BULK CREATE
#

@admin_photos_bp.route("/bulk_create", methods=["POST"])
@login_required
def bulk_create():

    admin_required()

    data = request.get_json(silent=True)

    print("JSON =", data)

    if not data:

        return jsonify({
            "success": False,
            "error": "json required"
        }), 400

    member_ids = data.get("member_ids", [])
    type_ids = data.get("type_ids", [])
    costume_id = data.get("costume_id")

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

@admin_photos_bp.route("/<int:photo_id>", methods=["DELETE"])
@login_required
def delete_photo(photo_id):

    admin_required()

    photo = Photo.query.get_or_404(photo_id)

    db.session.delete(photo)

    db.session.commit()

    return jsonify({
        "success": True
    })
