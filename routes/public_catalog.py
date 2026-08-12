# routes/public_catalog.py
#
# ログイン不要の公開カタログ。
# admin_photos.py の一覧クエリを参考にしているが、
# 追加・削除系のエンドポイントは持たない(読み取り専用)。

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    abort
)

from sqlalchemy.orm import joinedload
from sqlalchemy import func

from extensions import db

from models import (
    Group,
    Member,
    Costume,
    Photo,
    PhotoType
)

public_catalog_bp = Blueprint(
    "public_catalog",
    __name__,
    url_prefix="/explore"
)


#
# INDEX
# グループ選択画面
#

@public_catalog_bp.route("", methods=["GET"])
def index():

    groups = (
        Group.query
        .order_by(Group.id.asc())
        .all()
    )

    return render_template(
        "public/index.html",
        group_list=groups,
    )


#
# COSTUME LIST
# グループを選んだあとの衣装一覧(検索可能)
#

@public_catalog_bp.route("/<group_key>", methods=["GET"])
def costume_list(group_key):

    group = (
        Group.query
        .filter_by(key=group_key)
        .first_or_404()
    )

    keyword = request.args.get("q", "", type=str).strip()

    page = request.args.get("page", default=1, type=int)
    per_page = 30

    # 衣装ごとの登録件数(何人×何種)を一緒に出す
    query = (
        Costume.query
        .filter_by(group_id=group.id)
    )

    if keyword:

        query = query.filter(
            Costume.name.ilike(f"%{keyword}%")
        )

    query = query.order_by(Costume.name.asc())

    pagination = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    costume_ids = [c.id for c in pagination.items]

    # 衣装ごとの人数・種類数をまとめて集計(N+1回避)
    stats_rows = (
        db_session_stats(costume_ids)
        if costume_ids else []
    )

    stats_map = {
        row.costume_id: {
            "member_count": row.member_count,
            "type_count": row.type_count,
        }
        for row in stats_rows
    }

    return render_template(
        "public/costume_list.html",
        group=group,
        costumes=pagination.items,
        pagination=pagination,
        keyword=keyword,
        stats_map=stats_map,
    )


def db_session_stats(costume_ids):

    return (
        db.session.query(
            Photo.costume_id.label("costume_id"),
            func.count(func.distinct(Photo.member_id)).label("member_count"),
            func.count(func.distinct(Photo.type_id)).label("type_count"),
        )
        .filter(Photo.costume_id.in_(costume_ids))
        .group_by(Photo.costume_id)
        .all()
    )


#
# COSTUME DETAIL
# その衣装の参加メンバー × 種類 一覧
#

@public_catalog_bp.route(
    "/<group_key>/costumes/<int:costume_id>",
    methods=["GET"]
)
def costume_detail(group_key, costume_id):

    group = (
        Group.query
        .filter_by(key=group_key)
        .first_or_404()
    )

    costume = (
        Costume.query
        .filter_by(id=costume_id, group_id=group.id)
        .first_or_404()
    )

    photos = (
        Photo.query
        .options(
            joinedload(Photo.member),
            joinedload(Photo.photo_type)
        )
        .filter(Photo.costume_id == costume_id)
        .join(Member, Member.id == Photo.member_id)
        .order_by(
            Member.generation.asc(),
            Member.display_order.asc(),
            Photo.type_id.asc(),
        )
        .all()
    )

    # メンバーごとにtypeをまとめる
    # { member: [type_name, type_name, ...] }
    members_map = {}

    for photo in photos:

        m = photo.member

        if m.id not in members_map:

            members_map[m.id] = {
                "member": m,
                "types": []
            }

        members_map[m.id]["types"].append(
            photo.photo_type.name
        )

    member_rows = sorted(
        members_map.values(),
        key=lambda r: (
            r["member"].generation or 0,
            r["member"].display_order or 0,
        )
    )

    # この衣装で使われている種類の一覧(列見出し用)
    all_types = []
    seen = set()

    for photo in photos:
        if photo.photo_type.id not in seen:
            seen.add(photo.photo_type.id)
            all_types.append(photo.photo_type.name)

    return render_template(
        "public/costume_detail.html",
        group=group,
        costume=costume,
        member_rows=member_rows,
        all_types=all_types,
        total_photos=len(photos),
    )


#
# MEMBER SEARCH (API)
# 衣装詳細ページ内のクライアント側フィルタが必要なら使う想定
# 今回はテンプレート側のJSでフィルタするため未使用だが、
# 将来的にAjax化する場合の入り口として残す
#

@public_catalog_bp.route(
    "/<group_key>/members/<int:member_id>/costumes",
    methods=["GET"]
)
def member_costumes(group_key, member_id):

    group = (
        Group.query
        .filter_by(key=group_key)
        .first_or_404()
    )

    member = (
        Member.query
        .filter_by(id=member_id, group_id=group.id)
        .first_or_404()
    )

    photos = (
        Photo.query
        .options(
            joinedload(Photo.costume),
            joinedload(Photo.photo_type)
        )
        .filter(Photo.member_id == member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .order_by(Costume.id.desc())
        .all()
    )

    costumes_map = {}

    for photo in photos:

        c = photo.costume

        if c.id not in costumes_map:

            costumes_map[c.id] = {
                "costume": c,
                "types": []
            }

        costumes_map[c.id]["types"].append(
            photo.photo_type.name
        )

    return render_template(
        "public/member_costumes.html",
        group=group,
        member=member,
        costume_rows=list(costumes_map.values()),
    )