from flask import Blueprint, jsonify, abort, render_template, request
from flask_login import login_required, current_user
from models import User, WantPhoto, UserPhoto, Group, Photo, Member, WantMember, WantShare, GROUP_KEYS
from extensions import db
from sqlalchemy.orm import joinedload
from urllib.parse import urlsplit, parse_qs
from uuid import UUID
from trade.service import reserved_counts

trade_bp = Blueprint('trade', __name__, url_prefix='/trade')


@trade_bp.route('/match/<public_uuid>/<group_key>')
@login_required
def match_trade(public_uuid, group_key):

    target_user = User.query.filter_by(public_uuid=public_uuid).first_or_404()
    group = Group.query.filter_by(key=group_key).first_or_404()

    if not target_user.is_want_share_enabled(group_key):
        abort(404)

    return jsonify(match_data(target_user, group))


def match_data(target_user, group):
    # =========================
    # 🔥 必要データ取得
    # =========================
    target_wants = WantPhoto.query.filter_by(user_id=target_user.id).all()
    my_wants = WantPhoto.query.filter_by(user_id=current_user.id).all()

    my_photos = UserPhoto.query.filter(
        UserPhoto.user_id == current_user.id,
        UserPhoto.available_quantity > 0
    ).all()

    target_photos = UserPhoto.query.filter(
        UserPhoto.user_id == target_user.id,
        UserPhoto.available_quantity > 0
    ).all()

    # =========================
    # 🔥 groupフィルタ（正しい経路：Photo → Member → Group）
    # =========================
    def filter_group(items):
        photo_ids = [x.photo_id for x in items]
        if not photo_ids:
            return []

        valid_ids = {
            pid for (pid,) in db.session.query(Photo.id)
            .join(Member, Member.id == Photo.member_id)
            .filter(
                Member.group_id == group.id,
                Photo.id.in_(photo_ids)
            )
            .all()
        }

        return [x for x in items if x.photo_id in valid_ids]

    target_wants = filter_group(target_wants)
    my_wants = filter_group(my_wants)
    my_photos = filter_group(my_photos)
    target_photos = filter_group(target_photos)

    # =========================
    # 🔥 IDセット化
    # =========================
    target_want_ids = {w.photo_id for w in target_wants}
    my_want_ids = {w.photo_id for w in my_wants}
    for user_id, ids in [(target_user.id, target_want_ids), (current_user.id, my_want_ids)]:
        member_ids = db.session.query(WantMember.member_id).filter(WantMember.user_id == user_id).subquery()
        ids.update(pid for (pid,) in db.session.query(Photo.id).join(Member).filter(
            Member.group_id == group.id, Photo.member_id.in_(db.select(member_ids))).all())


    my_held = reserved_counts(current_user.id)
    target_held = reserved_counts(target_user.id)
    available = {
        (p.user_id, p.photo_id): max(0, min(p.available_quantity, p.quantity - held.get(p.photo_id, 0)))
        for rows, held in [(my_photos, my_held), (target_photos, target_held)] for p in rows
    }
    my_available_map = {p.photo_id: p for p in my_photos if available[(p.user_id, p.photo_id)] > 0}
    target_available_map = {p.photo_id: p for p in target_photos if available[(p.user_id, p.photo_id)] > 0}

    # =========================
    # 🔥 表示用Photoまとめ取得（N+1防止）
    # =========================
    all_photo_ids = set(my_available_map.keys()) | set(target_available_map.keys())

    photo_map = {
        p.id: p for p in db.session.query(Photo)
        .join(Member)
        .filter(Photo.id.in_(all_photo_ids))
        .options(joinedload(Photo.member), joinedload(Photo.costume), joinedload(Photo.photo_type))
        .all()
    }

    def to_dict(p):
        ph = photo_map.get(p.photo_id)
        return {
            "member": ph.member.name if ph else "",
            "costume": ph.costume.name if ph else "",
            "type": ph.photo_type.name if ph else "",
            "available": available[(p.user_id, p.photo_id)]
        }

    # =========================
    # 🔥 マッチング
    # =========================

    def ordered(rows):
        return sorted(rows, key=lambda p: (
            photo_map[p.photo_id].member.generation or 0,
            photo_map[p.photo_id].member.display_order or 0,
            photo_map[p.photo_id].member_id, photo_map[p.photo_id].costume.name, p.photo_id))

    give_rows = ordered([p for pid, p in my_available_map.items() if pid in target_want_ids])
    receive_rows = ordered([p for pid, p in target_available_map.items() if pid in my_want_ids])
    # 自分が渡せる
    i_can_give = [
        to_dict(p)
        for p in give_rows
    ]

    # 相手が渡せる
    they_can_give = [
        to_dict(p)
        for p in receive_rows
    ]

    # 相互トレード
    mutual_matches = []

    for my_p in give_rows:
        for their_p in receive_rows:
            mutual_matches.append({"give": to_dict(my_p), "receive": to_dict(their_p)})
            if len(mutual_matches) >= 100:
                break
        if len(mutual_matches) >= 100:
            break

    return {
        "i_can_give": i_can_give,
        "they_can_give": they_can_give,
        "mutual": mutual_matches,
        "mutual_total": len(give_rows) * len(receive_rows)
    }


@trade_bp.route('/qr/<group_key>')
@login_required
def qr_check(group_key):
    if group_key not in GROUP_KEYS:
        abort(404)
    group = Group.query.filter_by(key=group_key).first_or_404()
    return render_template('trade/qr_check.html', group_key=group_key, group=group)


def qr_target(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError('相手の共有QRコードか共有URLを指定してください。')
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ('', 'http', 'https') or parsed.username or parsed.password:
        raise ValueError('SP Colleの共有QRコードを読み取ってください。')
    if parsed.netloc and parsed.netloc.lower() not in {request.host.lower(), 'spcolle.com', 'www.spcolle.com'}:
        raise ValueError('SP Colleの共有QRコードを読み取ってください。')
    if parsed.scheme and not parsed.netloc:
        raise ValueError('共有URLの形式を確認してください。')
    parts = parsed.path.strip('/').split('/')
    collection = False
    if len(parts) == 4 and parts[:2] == ['want', 'share']:
        public_id, key = parts[2:]
    elif len(parts) == 3 and parts[:2] == ['want', 'share_redirect']:
        key = parts[2]
        values = parse_qs(parsed.query).get('uuid', [])
        public_id = values[0] if len(values) == 1 else ''
    elif len(parts) == 3 and parts[0] in ('share', 'shared'):
        key, public_id = parts[1:]
        collection = True
    else:
        raise ValueError('欲しい写真リストか所持一覧の共有QRコードを読み取ってください。')
    if key not in GROUP_KEYS:
        raise ValueError('このグループのQRコードには対応していません。')
    try:
        public_id = str(UUID(public_id))
    except (ValueError, AttributeError):
        raise ValueError('共有URLの形式を確認してください。')
    group = Group.query.filter_by(key=key).first_or_404()
    if collection:
        share = WantShare.query.filter_by(public_uuid=public_id, group_key=key, is_public=True).first_or_404()
        target = db.session.get(User, share.user_id)
    else:
        target = User.query.filter_by(public_uuid=public_id).first_or_404()
    if target is None:
        abort(404)
    return target, group


@trade_bp.route('/qr/<group_key>/check', methods=['POST'])
@login_required
def check_qr(group_key):
    if group_key not in GROUP_KEYS:
        abort(404)
    data = request.get_json(silent=True)
    try:
        target, group = qr_target(data.get('url') if isinstance(data, dict) else None)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if target.id == current_user.id:
        return jsonify(error='自分のQRコードです。交換相手のQRコードを読み取ってください。'), 400
    share = WantShare.query.filter_by(user_id=target.id, group_key=group.key, want_public=True).first()
    if not share:
        return jsonify(error='相手の欲しい写真リストは非公開です。相手に公開してもらってください。'), 404
    return jsonify(**match_data(target, group), group=dict(key=group.key, name=group.name))


# Register the listing/search/transaction screens on the existing blueprint.
from . import marketplace  # noqa: E402,F401
