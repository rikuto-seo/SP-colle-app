from flask import Blueprint, render_template, abort, jsonify
from flask_login import login_required, current_user
from sqlalchemy import exists

from models import db, Member, Costume, PhotoType, Photo, UserPhoto
from services.stats_service import (
    build_stats_data,
    build_member_comp_data
)
from services.type_normalizer import (
    normalize_type,
    get_type_order
)


stats_bp = Blueprint('stats', __name__)


GROUP_CONFIG = {
    'nogizaka': {
        'name': '乃木坂46',
        'color': 'bg-nogizaka'
    },
    'sakurazaka': {
        'name': '櫻坂46',
        'color': 'bg-sakurazaka'
    },
    'hinatazaka': {
        'name': '日向坂46',
        'color': 'bg-hinatazaka'
    }
}


def get_group_conf(group_key):

    conf = GROUP_CONFIG.get(
        group_key.strip().lower()
    )

    if not conf:
        abort(404)

    return conf


# =========================
# stats
# =========================
@stats_bp.route('/stats/<group_key>')
@login_required
def stats(group_key):

    conf = get_group_conf(group_key)

    data = build_stats_data(
        current_user.id,
        group_key
    )

    # =========================
    # 総所持数
    # =========================
    stats_owned = sum(
        data["member_stats"].values()
    )

    share_attr = f"is_{group_key}_shared"

    is_shared = getattr(
        current_user,
        share_attr,
        False
    )

    # =========================
    # メンバー順
    # =========================
    member_stats_ordered = [
        (
            m,
            data["member_stats"].get(m, 0)
        )
        for m in data["ordered_members"]
    ]

    # =========================
    # メンバー別所持数ランキング
    # =========================
    member_stats_sorted = sorted(
        data["member_stats"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    # =========================
    # 総コンプ数
    # =========================
    total_complete = sum(
        x["complete_count"]
        for x in data["comp_ranking"]
    )

    # =========================
    # 種類別統計
    #
    # build_stats_data() 側ですでに
    # ヨリ → チュウ → ヒキ → 座り
    # の順序になっているため、
    # ここでは sorted() しない。
    # =========================
    type_stats = list(
        data["type_stats"].items()
    )

    return render_template(
        'stats.html',

        group_key=group_key,
        group_name=conf['name'],
        group_color=conf['color'],

        stats_owned=stats_owned,

        member_stats=member_stats_ordered,
        member_stats_sorted=member_stats_sorted,

        type_stats=type_stats,

        progress_list=data["progress_list"],

        comp_ranking=data["comp_ranking"],
        ordered_members=data["ordered_members"],

        is_shared=is_shared,

        total_complete=total_complete
    )


# =========================
# member detail
# =========================
@stats_bp.route(
    "/stats/member/<group_key>/<member>"
)
@login_required
def member_detail(group_key, member):

    data = build_member_comp_data(
        current_user.id,
        group_key,
        member
    )

    return jsonify(data)


# =========================
# missing
# =========================
@stats_bp.route('/missing/<group_key>')
@login_required
def missing(group_key):

    conf = get_group_conf(group_key)

    data = build_stats_data(
        current_user.id,
        group_key
    )

    group = data["group"]

    # =========================
    # 未所持
    # =========================
    missing_rows = (
        db.session.query(
            Member.name,
            Costume.name,
            PhotoType.name
        )
        .join(
            Photo,
            Photo.member_id == Member.id
        )
        .join(
            Costume,
            Costume.id == Photo.costume_id
        )
        .join(
            PhotoType,
            PhotoType.id == Photo.type_id
        )
        .filter(
            Member.group_id == group.id
        )
        .filter(
            ~exists().where(
                (UserPhoto.user_id == current_user.id)
                &
                (UserPhoto.photo_id == Photo.id)
            )
        )
        .all()
    )

    # =========================
    # グルーピング
    #
    # ここでも必ず normalize_type()
    # を通す。
    # =========================
    grouped = {}

    for m, c, t in missing_rows:

        normalized = normalize_type(
            m,
            c,
            t
        )

        grouped.setdefault(
            m,
            []
        ).append({
            "costume": c,
            "type": normalized
        })

    # =========================
    # 種類順
    #
    # ヨリ → チュウ → ヒキ → 座り
    # =========================
    for member_name in grouped:

        grouped[member_name].sort(
            key=lambda x: (
                get_type_order(x["type"]),
                x["costume"]
            )
        )

    # =========================
    # メンバー順
    # =========================
    ordered_grouped = {
        m: grouped.get(m, [])
        for m in data["ordered_members"]
        if m in grouped
    }

    # =========================
    # 衣装一覧
    # =========================
    costume_list = [
        c.name
        for c in (
            Costume.query
            .filter_by(group_id=group.id)
            .order_by(Costume.name)
            .all()
        )
    ]

    return render_template(
        'missing.html',

        grouped_missing=ordered_grouped,

        member_list=data["ordered_members"],

        group_key=group_key,

        costume_list=costume_list,

        group_color=conf['color']
    )