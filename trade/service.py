from collections import defaultdict
from datetime import datetime
from sqlalchemy import or_, and_, func, select, case
from sqlalchemy.orm import aliased
from extensions import db
from models import User, UserPhoto, Photo, Member, WantPhoto, UserPhotoImage
from trade.models import TradeListing, TradeOffer, TradeWant, TradeProposal, TradeProposalItem, TradeMessage

METHODS = {'mail': '郵送', 'meet': '現地・手渡し', 'either': 'どちらも可'}
STATUSES = {'draft': '下書き', 'open': '募集中', 'paused': '公開停止', 'closed': '募集終了',
            'pending': '交渉中', 'accepted': '交換確定', 'rejected': '見送り', 'cancelled': 'キャンセル', 'completed': '完了'}
PRIORITIES = {'high': '熱望', 'normal': '希望', 'low': '緩く希望'}


class TradeError(ValueError):
    pass


def lock_users(*ids):
    # All stock writers use the same parent-row lock, including empty collections.
    return db.session.execute(select(User).where(User.id.in_(sorted(set(ids))))
                              .order_by(User.id).with_for_update().execution_options(populate_existing=True)).scalars().all()


def reserved_counts(user_id, exclude=None):
    q = db.session.query(TradeProposalItem.photo_id, func.sum(TradeProposalItem.quantity))\
        .join(TradeProposal).join(TradeListing).filter(TradeProposal.status == 'accepted', or_(
            and_(TradeProposalItem.side == 'owner', TradeListing.user_id == user_id),
            and_(TradeProposalItem.side == 'applicant', TradeProposal.applicant_id == user_id)))
    if exclude is not None:
        q = q.filter(TradeProposal.id != exclude)
    return dict(q.group_by(TradeProposalItem.photo_id).all())


def stock_map(user_id):
    return {p.photo_id: p for p in UserPhoto.query.filter_by(user_id=user_id)
            .populate_existing().all()}


def assert_stock_floor(user_id, photo_id, quantity):
    if quantity < reserved_counts(user_id).get(photo_id, 0):
        raise TradeError('交換確定分が取り置きされています。取引が完了するまで、その枚数は減らせません。')


def searchable_stock(offer=TradeOffer, listing=TradeListing, bundle=False):
    """Correlated SQL predicates so pagination excludes unavailable offers."""
    other_listing = aliased(TradeListing)
    held = select(func.coalesce(func.sum(TradeProposalItem.quantity), 0)).join(TradeProposal).join(
        other_listing, other_listing.id == TradeProposal.listing_id).where(
            TradeProposal.status == 'accepted', TradeProposalItem.photo_id == offer.photo_id,
            or_(and_(TradeProposalItem.side == 'owner', other_listing.user_id == listing.user_id),
                and_(TradeProposalItem.side == 'applicant', TradeProposal.applicant_id == listing.user_id)))\
        .correlate(listing, offer).scalar_subquery()
    held_here = select(func.coalesce(func.sum(TradeProposalItem.quantity), 0)).join(TradeProposal).where(
        TradeProposal.status == 'accepted', TradeProposal.listing_id == listing.id,
        TradeProposalItem.photo_id == offer.photo_id, TradeProposalItem.side == 'owner')\
        .correlate(listing, offer).scalar_subquery()
    stock = select(UserPhoto.quantity).where(UserPhoto.user_id == listing.user_id,
        UserPhoto.photo_id == offer.photo_id).correlate(listing, offer).scalar_subquery()
    if bundle:
        return (offer.quantity > 0, held_here == 0, func.coalesce(stock, 0) - held >= offer.quantity)
    return (offer.quantity > held_here, func.coalesce(stock, 0) > held)


def available_for_listings(listings):
    """Fetch stock and reservations for a page, without loading entire collections."""
    if not listings:
        return {}
    user_ids = {listing.user_id for listing in listings}
    photo_ids = {offer.photo_id for listing in listings for offer in listing.offers}
    listing_ids = [listing.id for listing in listings]
    stock = {(uid, pid): qty for uid, pid, qty in db.session.query(
        UserPhoto.user_id, UserPhoto.photo_id, UserPhoto.quantity).filter(
            UserPhoto.user_id.in_(user_ids), UserPhoto.photo_id.in_(photo_ids)).all()}
    sender = case((TradeProposalItem.side == 'owner', TradeListing.user_id), else_=TradeProposal.applicant_id)
    held = {(uid, pid): qty for uid, pid, qty in db.session.query(
        sender, TradeProposalItem.photo_id, func.sum(TradeProposalItem.quantity))
        .join(TradeProposal, TradeProposal.id == TradeProposalItem.proposal_id)
        .join(TradeListing, TradeListing.id == TradeProposal.listing_id)
        .filter(TradeProposal.status == 'accepted', sender.in_(user_ids), TradeProposalItem.photo_id.in_(photo_ids))
        .group_by(sender, TradeProposalItem.photo_id).all()}
    held_here = {(lid, pid): qty for lid, pid, qty in db.session.query(
        TradeProposal.listing_id, TradeProposalItem.photo_id, func.sum(TradeProposalItem.quantity))
        .join(TradeProposal, TradeProposal.id == TradeProposalItem.proposal_id)
        .filter(TradeProposal.listing_id.in_(listing_ids), TradeProposal.status == 'accepted', TradeProposalItem.side == 'owner')
        .group_by(TradeProposal.listing_id, TradeProposalItem.photo_id).all()}
    return {listing.id: {offer.photo_id: max(0, min(
        offer.quantity - held_here.get((listing.id, offer.photo_id), 0),
        stock.get((listing.user_id, offer.photo_id), 0) - held.get((listing.user_id, offer.photo_id), 0)))
        for offer in listing.offers} for listing in listings}


def offer_available(listing):
    return available_for_listings([listing])[listing.id]


def positive(value):
    if isinstance(value, bool):
        raise TradeError('枚数は1〜999の整数で指定してください。')
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise TradeError('枚数は1〜999の整数で指定してください。')
    if str(number) != str(value) or not 1 <= number <= 999:
        raise TradeError('枚数は1〜999の整数で指定してください。')
    return number


def bounded(value, length, label, required=False):
    if not isinstance(value, str):
        raise TradeError(f'{label}を入力してください。')
    value = value.strip()
    if len(value) > length or (required and not value):
        raise TradeError(f'{label}は1〜{length}文字で入力してください。')
    return value


def checked_id(value):
    # Database IDs have no quantity limit.
    try:
        result = int(value)
    except (ValueError, TypeError):
        raise TradeError('写真を選択してください。')
    if isinstance(value, bool) or str(result) != str(value) or result < 1:
        raise TradeError('写真を選択してください。')
    return result


def photo_exists(photo_id, group_id):
    photo = db.session.query(Photo).join(Member).filter(Photo.id == checked_id(photo_id), Member.group_id == group_id).first()
    if not photo:
        raise TradeError('このグループの写真を選択してください。')
    return photo


def listing_data(listing, user_id, data):
    if not isinstance(data, dict):
        raise TradeError('募集内容を確認してください。')
    listing.alias = bounded(data.get('alias', ''), 30, '募集用の表示名', True)
    listing.location = bounded(data.get('location', ''), 100, '交換場所')
    listing.notes = bounded(data.get('notes', ''), 1000, '交換条件')
    if not isinstance(data.get('bundle', False), bool):
        raise TradeError('セット交換の指定を確認してください。')
    listing.bundle = data.get('bundle', False)
    listing.method = data.get('method')
    if listing.method not in METHODS:
        raise TradeError('交換方法を選択してください。')
    offers = data.get('offers')
    if not isinstance(offers, list) or not 1 <= len(offers) <= 30:
        raise TradeError('提供写真は1〜30種類選択してください。')
    stock = stock_map(user_id)
    reserved = reserved_counts(user_id)
    listing.offers.clear()
    db.session.flush()
    seen = set()
    for item in offers:
        if not isinstance(item, dict):
            raise TradeError('提供写真を確認してください。')
        photo = photo_exists(item.get('photo_id'), listing.group_id)
        quantity = positive(item.get('quantity'))
        if photo.id in seen:
            raise TradeError('同じ提供写真は一つにまとめてください。')
        seen.add(photo.id)
        if photo.id not in stock or quantity > stock[photo.id].quantity - reserved.get(photo.id, 0):
            raise TradeError('提供枚数が取り置きを除いた所持数を超えています。')
        mode = item.get('want_mode', 'any')
        if mode not in ('any', 'all'):
            raise TradeError('希望条件を確認してください。')
        offer = TradeOffer(photo_id=photo.id, quantity=quantity, want_mode=mode)
        if item.get('share_image') is True:
            image = UserPhotoImage.query.filter_by(user_photo_id=stock[photo.id].id, user_id=user_id).order_by(UserPhotoImage.id).first()
            offer.image_id = image.id if image else None
        wants = item.get('wants')
        if not isinstance(wants, list) or not (0 if listing.bundle else 1) <= len(wants) <= 100:
            raise TradeError('提供写真ごとに希望写真を1〜100種類選択してください。')
        seen_wants = set()
        for w in wants:
            if not isinstance(w, dict):
                raise TradeError('希望写真を確認してください。')
            wanted = photo_exists(w.get('photo_id'), listing.group_id)
            if wanted.id in seen_wants or wanted.id == photo.id:
                raise TradeError('希望写真の重複、または提供写真と同じ写真が指定されています。')
            seen_wants.add(wanted.id)
            priority = w.get('priority', 'normal')
            if priority not in PRIORITIES:
                raise TradeError('希望度を確認してください。')
            offer.wants.append(TradeWant(photo_id=wanted.id, quantity=positive(w.get('quantity')), priority=priority))
        listing.offers.append(offer)
    if not any(offer.wants for offer in listing.offers):
        raise TradeError('希望写真を選択してください。')
    listing.status = 'draft'


def publish(listing):
    if not listing.offers or not any(o.quantity for o in listing.offers):
        raise TradeError('提供写真が残っていません。')
    stock = stock_map(listing.user_id)
    # Do not advertise the same physical copies in separate open listings.
    other = dict(db.session.query(TradeOffer.photo_id, func.sum(TradeOffer.quantity))
        .join(TradeListing).filter(TradeListing.user_id == listing.user_id,
            TradeListing.status == 'open', TradeListing.id != listing.id)
        .group_by(TradeOffer.photo_id).all())
    reserved = reserved_counts(listing.user_id)
    covered = dict(db.session.query(TradeProposalItem.photo_id, func.sum(TradeProposalItem.quantity))
        .join(TradeProposal).join(TradeListing).filter(TradeListing.user_id == listing.user_id,
            or_(TradeListing.status == 'open', TradeListing.id == listing.id),
            TradeProposal.status == 'accepted', TradeProposalItem.side == 'owner')
        .group_by(TradeProposalItem.photo_id).all())
    for offer in listing.offers:
        owned = stock[offer.photo_id].quantity if offer.photo_id in stock else 0
        if offer.quantity + other.get(offer.photo_id, 0) + reserved.get(offer.photo_id, 0) - covered.get(offer.photo_id, 0) > owned:
            raise TradeError('他の募集や取り置きと合わせた提供枚数が所持数を超えています。')
    listing.status = 'open'


def parse_items(items, group_id):
    if not isinstance(items, list) or not 1 <= len(items) <= 30:
        raise TradeError('双方の交換写真を1〜30種類選択してください。')
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise TradeError('交換写真を確認してください。')
        photo = photo_exists(item.get('photo_id'), group_id)
        if photo.id in result:
            raise TradeError('同じ写真の枚数は一つにまとめてください。')
        result[photo.id] = positive(item.get('quantity'))
    return result


def validate_proposal(listing, owner_items, applicant_items, applicant_id):
    if listing.status != 'open':
        raise TradeError('この募集は現在公開されていません。')
    offers = {o.photo_id: o for o in listing.offers}
    if listing.bundle and owner_items != {o.photo_id: o.quantity for o in listing.offers if o.quantity > 0}:
        raise TradeError('この募集はセット交換です。提供写真一式を指定してください。')
    available = offer_available(listing)
    allowed = set()
    required_all = defaultdict(int)
    any_sets = []
    for pid, quantity in owner_items.items():
        if pid not in offers or quantity > available[pid]:
            raise TradeError('希望する提供写真の残り枚数が不足しています。')
        offer = offers[pid]
        units = {w.photo_id: w.quantity for w in offer.wants}
        allowed.update(units)
        if listing.bundle:
            for wanted_id, n in units.items():
                required_all[wanted_id] = max(required_all[wanted_id], n)
        elif offer.want_mode == 'all':
            for wanted_id, n in units.items():
                required_all[wanted_id] += n * quantity
        else:
            any_sets.extend([units] * quantity)
    if set(applicant_items) - allowed:
        raise TradeError('募集で指定されている希望写真から選択してください。')
    remaining = dict(applicant_items)
    for pid, quantity in required_all.items():
        if remaining.get(pid, 0) < quantity:
            raise TradeError('「すべて必要」の写真・枚数が不足しています。')
        remaining[pid] -= quantity
    # Allocate alternatives, avoiding double-counting a single copy across offers.
    visited = set()
    attempts = 0
    def allocate(index):
        nonlocal attempts
        attempts += 1
        if attempts > 10000:
            raise TradeError('希望の組み合わせが複雑です。交換案を分けて送ってください。')
        if index == len(any_sets):
            return True
        state = (index, tuple(sorted(remaining.items())))
        if state in visited:
            return False
        visited.add(state)
        for pid, quantity in any_sets[index].items():
            if remaining.get(pid, 0) >= quantity:
                remaining[pid] -= quantity
                if allocate(index + 1):
                    return True
                remaining[pid] += quantity
        return False
    if len(any_sets) > 30:
        raise TradeError('一度の提案は提供写真の合計30枚までです。')
    if not allocate(0):
        raise TradeError('希望条件を満たす写真・枚数が不足しています。')
    stock = stock_map(applicant_id)
    reserved = reserved_counts(applicant_id)
    for pid, quantity in applicant_items.items():
        if pid not in stock or quantity > stock[pid].quantity - reserved.get(pid, 0):
            raise TradeError('あなたの提供枚数が取り置きを除いた所持数を超えています。')


def log(proposal, body, sender=None):
    proposal.messages.append(TradeMessage(body=body, sender_id=sender))
    proposal.updated_at = datetime.utcnow()


def complete(proposal):
    """Called under both users' locks, once, after both receipt confirmations."""
    if proposal.status != 'accepted' or not proposal.owner_received_at or not proposal.applicant_received_at:
        return
    owner = proposal.listing.user_id
    applicant = proposal.applicant_id
    stocks = {uid: stock_map(uid) for uid in (owner, applicant)}
    other_reserved = {uid: reserved_counts(uid, proposal.id) for uid in (owner, applicant)}
    for item in proposal.items:
        sender = owner if item.side == 'owner' else applicant
        if item.photo_id not in stocks[sender] or stocks[sender][item.photo_id].quantity - item.quantity < other_reserved[sender].get(item.photo_id, 0):
            raise TradeError('所持数と取り置きに不整合があります。枚数を確認してください。')
    for item in proposal.items:
        sender, receiver = (owner, applicant) if item.side == 'owner' else (applicant, owner)
        source = stocks[sender][item.photo_id]
        source.quantity -= item.quantity
        source.available_quantity = min(source.available_quantity, source.quantity)
        target = stocks[receiver].get(item.photo_id)
        if target is None:
            target = UserPhoto(user_id=receiver, photo_id=item.photo_id, quantity=0, available_quantity=0)
            db.session.add(target)
            stocks[receiver][item.photo_id] = target
        target.quantity += item.quantity
        target.has_owner = True
        # Keep zero-count source rows and their images; never transfer an uploaded asset.
        WantPhoto.query.filter_by(user_id=receiver, photo_id=item.photo_id, is_infinite=False).delete()
        if item.side == 'owner':
            for offer in proposal.listing.offers:
                if offer.photo_id == item.photo_id:
                    offer.quantity = max(0, offer.quantity - item.quantity)
    proposal.status = 'completed'
    if not any(o.quantity for o in proposal.listing.offers):
        proposal.listing.status = 'closed'
    log(proposal, '双方の受取確認がそろいました。所持数と通常の希望リストを更新しました。')
