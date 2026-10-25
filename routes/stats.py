from flask import Blueprint, render_template, abort, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import exists

from models import db, Group, Member, Costume, PhotoType, Photo, UserPhoto
from services.stats_service import (
    build_stats_data,
    build_member_comp_data
)
from services.type_normalizer import (
    get_type_resolver,
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
            m["name"],
            data["member_stats"].get(m["id"], 0)
        )
        for m in data["ordered_members"]
    ]

    # =========================
    # メンバー別所持数ランキング
    # =========================
    member_stats_sorted = sorted(
        [(m["name"], data["member_stats"].get(m["id"], 0)) for m in data["ordered_members"]],
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
        unclassified_stats=data["unclassified_stats"],
        unclassified_quantity=data["unclassified_quantity"],

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


@stats_bp.route('/stats/member/<group_key>/id/<int:member_id>')
@login_required
def member_detail_by_id(group_key, member_id):
    return jsonify(build_member_comp_data(current_user.id, group_key, member_id=member_id))


# Missing rows retain Photo identity and are grouped by member ID.
@stats_bp.route('/missing/<group_key>')
@login_required
def missing(group_key):
    conf = get_group_conf(group_key)
    group = Group.query.filter_by(key=group_key).first_or_404()
    members = sorted(Member.query.filter_by(group_id=group.id).all(),
                     key=lambda m: (m.generation or 0, m.display_order or 0, m.id))
    costumes = Costume.query.filter_by(group_id=group.id).order_by(Costume.name, Costume.id).all()
    member_id = request.args.get('member_id', type=int)
    costume_id = request.args.get('costume_id', type=int)
    if member_id is not None and member_id not in {m.id for m in members}:
        abort(404)
    if costume_id is not None and costume_id not in {c.id for c in costumes}:
        abort(404)
    query = (
        db.session.query(Photo.id, Member.id, Costume.name, Costume.id, PhotoType.id, PhotoType.name)
        .select_from(Photo)
        .join(Member, Member.id == Photo.member_id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .filter(Member.group_id == group.id)
        .filter(~exists().where((UserPhoto.user_id == current_user.id)
                               & (UserPhoto.photo_id == Photo.id) & (UserPhoto.quantity > 0)))
    )
    if member_id is not None:
        query = query.filter(Photo.member_id == member_id)
    if costume_id is not None:
        query = query.filter(Photo.costume_id == costume_id)
    resolver = get_type_resolver(group.id)
    grouped = {}
    for photo_id, mid, costume, cid, tid, raw_type in query.all():
        grouped.setdefault(mid, []).append(dict(photo_id=photo_id, member_id=mid, costume_id=cid,
            costume=costume, type=raw_type, normalized_type=resolver.resolve(cid, tid, costume, raw_type)))
    for photos in grouped.values():
        photos.sort(key=lambda p: (get_type_order(p['normalized_type']), p['costume'], p['costume_id'], p['photo_id']))
    return render_template('missing.html',
        grouped_missing={m.id: grouped[m.id] for m in members if m.id in grouped},
        member_names={m.id: m.name for m in members},
        member_options=[dict(id=m.id, name=m.name) for m in members],
        costume_options=[dict(id=c.id, name=c.name) for c in costumes],
        selected_member_id=member_id, selected_costume_id=costume_id,
        group_key=group_key, group_color=conf['color'])
