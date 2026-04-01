import os
import csv
from flask import render_template, request
from models import Photo, UserPhoto
from collections import defaultdict
from services.photo_service import load_required_types
from flask_login import current_user

# =========================
# 🔥 安全ユーティリティ
# =========================
def safe_str(val):
    return (val or "").strip()

# =========================
# メイン
# =========================
def build_stats(current_user, group_key):
    group_key = safe_str(group_key).lower()

    group_colors = {
        'nogizaka': 'bg-nogizaka',
        'sakurazaka': 'bg-sakurazaka',
        'hinatazaka': 'bg-hinatazaka'
    }

    if group_key not in group_colors:
        return "不正なグループキーです", 404

    group_color = group_colors[group_key]

    # ✅ 共有状態（安全化）
    share_status_map = {
        'nogizaka': getattr(current_user, 'is_nogizaka_shared', False),
        'sakurazaka': getattr(current_user, 'is_sakurazaka_shared', False),
        'hinatazaka': getattr(current_user, 'is_hinatazaka_shared', False)
    }
    is_shared = share_status_map[group_key]

    all_photos = Photo.query.filter_by(group_key=group_key).all()

    member_stats = defaultdict(int)
    type_stats = defaultdict(int)

    user_photos = UserPhoto.query.filter_by(
        user_id=current_user.id,
        group_key=group_key
    ).all()

    # =========================
    # 集計
    # =========================
    for p in user_photos:
        member = safe_str(p.member)
        costume = safe_str(p.costume)
        photo_type = safe_str(p.photo_type)

        if not member or not costume or not photo_type:
            continue

        member_stats[member] += p.quantity
        type_stats[photo_type] += p.quantity

    # =========================
    # コンプ集計
    # =========================
    required_dict = load_required_types(group_key)

    owned_dict = defaultdict(lambda: defaultdict(set))

    for p in user_photos:
        member = safe_str(p.member)
        costume = safe_str(p.costume)
        ptype = safe_str(p.photo_type)

        if not member or not costume or not ptype:
            continue

        owned_dict[member][costume].add(ptype)

    comp_stats = {}
    for member, costumes in required_dict.items():
        comp_stats[member] = []
        for costume, required_types in costumes.items():
            owned_types = owned_dict[member][costume]

            comp_stats[member].append({
                "costume": costume,
                "owned": len(owned_types),
                "total": len(required_types),
                "is_complete": required_types.issubset(owned_types)
            })

    # =========================
    # 衣装進捗
    # =========================
    all_costumes = set(
        safe_str(p.costume) for p in all_photos if safe_str(p.costume)
    )

    costume_stats = {c: {'owned': 0, 'total': 0} for c in all_costumes}

    for p in user_photos:
        c = safe_str(p.costume)
        if not c:
            continue

        if c in costume_stats:
            costume_stats[c]['owned'] += p.quantity

    progress = sorted([
        {
            'costume': c,
            'owned': d['owned'],
            'total': d['total'],
            'rate': d['owned'] / d['total'] * 100 if d['total'] else 0
        }
        for c, d in costume_stats.items()
    ], key=lambda x: x['costume'])

    # =========================
    # コンプランキング
    # =========================
    comp_ranking_list = []
    for member, costumes in comp_stats.items():
        complete_count = sum(1 for item in costumes if item['is_complete'])
        comp_ranking_list.append({
            'member': member,
            'complete_count': complete_count
        })

    # =========================
    # 並び順適用
    # =========================
    ordered_members = get_ordered_members(group_key)

    member_stats_ordered = [
        (m, member_stats.get(m, 0))
        for m in ordered_members
    ]

    comp_stats_ordered = {
        m: comp_stats.get(m, [])
        for m in ordered_members
    }

    comp_ranking = sorted(
        [r for r in comp_ranking_list if r["member"] in ordered_members],
        key=lambda x: x['complete_count'],
        reverse=True
    )

    # =========================
    # render
    # =========================
    return render_template(
        'stats.html',
        endpoint=request.endpoint,
        group_key=group_key,
        group_name={
            'nogizaka': '乃木坂46',
            'sakurazaka': '櫻坂46',
            'hinatazaka': '日向坂46'
        }[group_key],
        member_stats=member_stats_ordered,
        type_stats=sorted(type_stats.items()),
        progress_list=progress,
        comp_stats=comp_stats_ordered,
        comp_ranking=comp_ranking,
        group_color=group_color,
        is_shared=is_shared
    )

# =========================
# CSV系
# =========================
def load_member_master(group_key):
    path = os.path.join("members_csv", group_key, "members_master.csv")

    members = []

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            member = safe_str(row.get("member"))
            if not member:
                continue

            try:
                generation = int(row.get("generation") or 0)
                order = int(row.get("order") or 0)
            except:
                continue

            members.append({
                "member": member,
                "generation": generation,
                "order": order
            })

    members.sort(key=lambda x: (x["generation"], x["order"]))
    return members

def get_existing_members(group_key):
    base_path = os.path.join("members_csv", group_key)

    members = set()

    for filename in os.listdir(base_path):
        if not filename.endswith(".csv"):
            continue
        if filename == "members_master.csv":
            continue

        member_name = safe_str(filename.replace(".csv", ""))
        if member_name:
            members.add(member_name)

    return members

def get_ordered_members(group_key):
    master = load_member_master(group_key)
    existing_members = get_existing_members(group_key)

    return [
        m["member"]
        for m in master
        if m["member"] in existing_members
    ]

def get_all_costumes_in_order(group_key):
    base_path = os.path.join("members_csv", group_key)

    costumes = []
    seen = set()

    for filename in os.listdir(base_path):
        if not filename.endswith(".csv"):
            continue
        if filename == "members_master.csv":
            continue

        path = os.path.join(base_path, filename)

        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                c = safe_str(row.get("costume"))

                if not c:
                    continue

                if c not in seen:
                    seen.add(c)
                    costumes.append(c)

    return costumes

def get_costumes_from_member_csv(group_key, member):
    path = os.path.join("members_csv", group_key, f"{member}.csv")

    costumes = []
    seen = set()

    if not os.path.exists(path):
        return []

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            costume = safe_str(row.get("costume"))

            if not costume:
                continue

            if costume not in seen:
                seen.add(costume)
                costumes.append(costume)

    return costumes