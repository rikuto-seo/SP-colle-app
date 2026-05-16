# routes/admin_photos.py

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify
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
# INDEX
#

@admin_photos_bp.route("", methods=["GET"])
def index():

    groups = (
        Group.query
        .order_by(Group.id.asc())
        .all()
    )

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
def photo_list():

    group_id = request.args.get("group_id", type=int)

    if not group_id:
        return jsonify([])

    photos = (
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
        .order_by(
            Costume.id.desc(),
            Member.display_order.asc(),
            Photo.type_id.asc(),
            Photo.id.asc()
        )
        .all()
    )

    result = []

    for photo in photos:

        result.append({
            "id": photo.id,
            "member": photo.member.name,
            "costume": photo.costume.name,
            "type": photo.photo_type.name
        })

    return jsonify(result)

#
# CREATE COSTUME
#

@admin_photos_bp.route("/create_costume", methods=["POST"])
def create_costume():

    name = request.form.get("name", "").strip()

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
def bulk_create():

    data = request.get_json()

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

    for member_id in member_ids:

        for type_id in type_ids:

            exists = (
                Photo.query
                .filter_by(
                    member_id=member_id,
                    costume_id=costume_id,
                    type_id=type_id
                )
                .first()
            )

            if exists:
                skipped += 1
                continue

            photo = Photo(
                member_id=member_id,
                costume_id=costume_id,
                type_id=type_id
            )

            db.session.add(photo)

            created += 1

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
def delete_photo(photo_id):

    photo = Photo.query.get_or_404(photo_id)

    db.session.delete(photo)

    db.session.commit()

    return jsonify({
        "success": True
    })