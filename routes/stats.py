from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from sqlalchemy import exists
from models import db, Member, Costume, PhotoType, Photo, UserPhoto
from services.stats_service import build_stats_data

stats_bp = Blueprint('stats', __name__)

GROUP_CONFIG = {
    'nogizaka': {'name': '乃木坂46', 'color': 'bg-nogizaka'},
    'sakurazaka': {'name': '櫻坂46', 'color': 'bg-sakurazaka'},
    'hinatazaka': {'name': '日向坂46', 'color': 'bg-hinatazaka'}
}


def get_group_conf(group_key):
    conf = GROUP_CONFIG.get(group_key.strip().lower())
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

    data = build_stats_data(current_user.id, group_key)

    # --- ここで総所持数を計算 ---
    stats_owned = sum(data["member_stats"].values())
    # -----------------------

    share_attr = f"is_{group_key}_shared"
    is_shared = getattr(current_user, share_attr, False)

    member_stats_ordered = [
        (m, data["member_stats"].get(m, 0))
        for m in data["ordered_members"]
    ]

    member_stats_sorted = sorted(
        data["member_stats"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    total_complete = sum(
        x["complete_count"] for x in data["comp_ranking"]
    )

    return render_template(
        'stats.html',
        group_key=group_key,
        group_name=conf['name'],
        group_color=conf['color'],
        stats_owned=stats_owned,  # ← ここを追加！
        member_stats=member_stats_ordered,
        member_stats_sorted=member_stats_sorted,
        type_stats=sorted(data["type_stats"].items()),
        progress_list=data["progress_list"],
        comp_stats=data["comp_stats"],
        comp_ranking=data["comp_ranking"],
        is_shared=is_shared,
        total_complete=total_complete
    )

# =========================
# missing（完全修正版）
# =========================
@stats_bp.route('/missing/<group_key>')
@login_required
def missing(group_key):
    conf = get_group_conf(group_key)

    data = build_stats_data(current_user.id, group_key)
    group = data["group"]

    # =========================
    # 未所持（最適化版）
    # =========================
    missing_rows = (
        db.session.query(
            Member.name,
            Costume.name,
            PhotoType.name
        )
        .join(Photo, Photo.member_id == Member.id)
        .join(Costume, Costume.id == Photo.costume_id)
        .join(PhotoType, PhotoType.id == Photo.type_id)
        .filter(Member.group_id == group.id)
        .filter(
            ~exists().where(
                (UserPhoto.user_id == current_user.id) &
                (UserPhoto.photo_id == Photo.id)
            )
        )
        .all()
    )

    # =========================
    # グルーピング
    # =========================
    grouped = {}
    for m, c, t in missing_rows:
        grouped.setdefault(m, []).append({
            "costume": c,
            "type": t
        })

    # =========================
    # 順序適用
    # =========================
    ordered_grouped = {
        m: grouped.get(m, [])
        for m in data["ordered_members"]
        if m in grouped
    }

    return render_template(
        'missing.html',
        grouped_missing=ordered_grouped,
        member_list=data["ordered_members"],
        group_key=group_key,
        group_color=conf['color']
    )