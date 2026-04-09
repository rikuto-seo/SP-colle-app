from collections import defaultdict
from flask import Blueprint, render_template, request, abort
from flask_login import login_required, current_user
from models import UserPhoto
from services.photo_service import load_required_types, get_missing_photos
from services.stats_service import get_ordered_members, get_all_costumes_in_order
stats_bp = Blueprint('stats', __name__)


GROUP_CONFIG = {
    'nogizaka': {'name': '乃木坂46', 'color': 'bg-nogizaka'},
    'sakurazaka': {'name': '櫻坂46', 'color': 'bg-sakurazaka'},
    'hinatazaka': {'name': '日向坂46', 'color': 'bg-hinatazaka'}
}


def get_group_conf(group_key):
    """グループ設定を取得。存在しない場合は404を返す"""
    conf = GROUP_CONFIG.get(group_key.strip().lower())
    if not conf:
        abort(404, "不正なグループキーです")
    return conf


@stats_bp.route('/stats/<group_key>')
@login_required
def stats(group_key):
    conf = get_group_conf(group_key)

    share_attr = f"is_{group_key}_shared"
    is_shared = getattr(current_user, share_attr, False)

    required_dict = load_required_types(group_key)

    user_photos = UserPhoto.query.filter_by(
        user_id=current_user.id, group_key=group_key).all()

    total_photos = sum(p.quantity for p in user_photos)

    member_stats = defaultdict(int) 
    type_stats = defaultdict(int) 
    owned_dict = defaultdict(lambda: defaultdict(set))

    for p in user_photos:
        m, c, t = p.member.strip(), p.costume.strip(), p.photo_type.strip()

        member_stats[m] += p.quantity
        type_stats[t] += p.quantity
        owned_dict[m][c].add(t)

    comp_stats = {}
    comp_ranking_list = []
    costume_progress_map = defaultdict(lambda: {"owned": 0, "total": 0})

    ordered_members = get_ordered_members(group_key)

    for member in ordered_members:
        costumes = required_dict.get(member, {})

        member_comp_count = 0
        member_results = []

        for costume, required_types in costumes.items():
            owned_types = owned_dict[member][costume]

            valid_owned_types = required_types.intersection(owned_types)
            owned_count = len(valid_owned_types)
            total_count = len(required_types)

            is_complete = (owned_count == total_count and total_count > 0)
            if is_complete:
                member_comp_count += 1

            member_results.append({
                "costume": costume,
                "owned": owned_count,
                "total": total_count,
                "is_complete": is_complete
            })

            costume_progress_map[costume]["owned"] += owned_count
            costume_progress_map[costume]["total"] += total_count

        comp_stats[member] = member_results

        comp_ranking_list.append({
            'member': member,
            'complete_count': member_comp_count
        })

    comp_ranking = sorted(
        comp_ranking_list, key=lambda x: x['complete_count'], reverse=True)

    total_complete = sum(x['complete_count'] for x in comp_ranking_list)

    ordered_costumes = get_all_costumes_in_order(group_key)

    progress_list = []
    for c in ordered_costumes:
        data = costume_progress_map.get(c, {"owned": 0, "total": 0})

        progress_list.append({
            'costume': c,
            'owned': data["owned"],
            'total': data["total"],
            'rate': (data["owned"] / data["total"] * 100) if data["total"] > 0 else 0
        })

    member_stats_ordered = [
        (m, member_stats.get(m, 0))
        for m in ordered_members
    ]

    return render_template(
        'stats.html',
        endpoint=request.endpoint,
        group_key=group_key,
        group_name=conf['name'],
        group_color=conf['color'],
        member_stats=member_stats_ordered,
        type_stats=sorted(type_stats.items()),
        progress_list=progress_list,
        comp_stats=comp_stats,
        comp_ranking=comp_ranking,
        is_shared=is_shared,
        total_photos=total_photos,
        total_complete=total_complete
    )


@stats_bp.route('/missing/<group_key>', methods=['GET'])
@login_required
def missing(group_key):
    conf = get_group_conf(group_key)

    search_member = request.args.get('member', '').strip()
    search_costume = request.args.get('costume', '').strip()

    # --- 未所持データ ---
    grouped = get_missing_photos(search_member, search_costume, group_key)

    # --- 並び順取得（masterベース） ---
    ordered_members = get_ordered_members(group_key)

    # --- 表示用：順序付き＆存在するメンバーのみ ---
    ordered_grouped_missing = {
        m: grouped.get(m, [])
        for m in ordered_members
        if m in grouped
    }

    # --- セレクトボックス用メンバー ---
    member_list = ordered_members

    # --- 衣装リスト（CSVベース） ---
    required_dict = load_required_types(group_key)
    costume_set = set()
    for member_data in required_dict.values():
        for c in member_data.keys():
            costume_set.add(c)

    return render_template(
        'missing.html',
        endpoint=request.endpoint,
        grouped_missing=ordered_grouped_missing,
        member_list=member_list,
        group_key=group_key,
        group_color=conf['color'],
        search_member=search_member,
        search_costume=search_costume,
        costume_list=get_all_costumes_in_order(group_key)
    )
