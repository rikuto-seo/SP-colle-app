import json
from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, select
from sqlalchemy.orm import joinedload, selectinload, aliased
from extensions import db
from models import Group, Member, Costume, PhotoType, Photo, UserPhoto, UserPhotoImage
from trade.routes import trade_bp
from trade.models import TradeListing, TradeOffer, TradeWant, TradeProposal, TradeProposalItem
from trade.service import (TradeError, METHODS, STATUSES, PRIORITIES, lock_users, reserved_counts,
    stock_map, listing_data, publish, offer_available, available_for_listings, parse_items, validate_proposal, log, complete, bounded, searchable_stock)


def group_or_404(key):
    return Group.query.filter_by(key=key).first_or_404()


def render(name, group, **ctx):
    return render_template('trade/' + name + '.html', group_key=group.key, group=group,
        methods=METHODS, statuses=STATUSES, priorities=PRIORITIES, **ctx)


def owned_listing(public_id):
    return TradeListing.query.filter_by(public_id=public_id, user_id=current_user.id).first_or_404()


def private_proposal(public_id):
    proposal = TradeProposal.query.filter_by(public_id=public_id).first_or_404()
    if current_user.id not in (proposal.applicant_id, proposal.listing.user_id):
        abort(404)
    return proposal


def payload():
    try:
        raw = request.form.get('payload', '')
        if len(raw) > 80000:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise TradeError('写真・枚数を選択してから保存してください。')


def thumbnail(offer):
    if not offer.image:
        return None
    from services.r2_storage import get_thumbnail_url
    try:
        return get_thumbnail_url(offer.image.thumbnail_key)
    except RuntimeError:
        return None


@trade_bp.app_template_global()
def trade_thumbnail(offer):
    return thumbnail(offer)


@trade_bp.app_template_filter('trade_time')
def trade_time(value):
    return (value + timedelta(hours=9)).strftime('%Y/%m/%d %H:%M') if value else ''


def listing_preview(listing, available, side, filters, keyword):
    """Show the actual matched pair, rather than an unrelated first photo."""
    def matches(photo):
        for key, actual in [('member', photo.member_id), ('costume', photo.costume_id),
                            ('type', photo.type_id), ('photo_id', photo.id)]:
            selected = filters.get(key)
            if selected and selected != str(actual):
                return False
        labels = [photo.member.name.casefold(), photo.costume.name.casefold(), photo.photo_type.name.casefold()]
        return all(any(word.casefold() in label for label in labels) for word in keyword.split()[:5])

    offers = [offer for offer in listing.offers if available[offer.photo_id] > 0]
    if not offers:
        return None
    matched = [offer for offer in offers if (matches(offer.photo) if side == 'offer'
               else any(matches(want.photo) for want in offer.wants))]
    candidates = matched or offers
    offer = next((item for item in candidates if item.image_id), candidates[0])
    wants = list(offer.wants)
    if listing.bundle:
        unique = {}
        for item in listing.offers:
            for want in item.wants:
                if want.photo_id not in unique or want.quantity > unique[want.photo_id].quantity:
                    unique[want.photo_id] = want
        wants = list(unique.values())
    wants.sort(key=lambda want: (0 if side == 'want' and matches(want.photo) else 1,
                                {'high':0, 'normal':1, 'low':2}[want.priority], want.id))
    return dict(offer=offer, want=wants[0] if wants else None, offer_more=len(offers)-1,
                want_more=max(0, len(wants)-1), image_url=thumbnail(offer))


@trade_bp.route('/<group_key>')
def search(group_key):
    group = group_or_404(group_key)
    side = 'want' if request.args.get('side') == 'want' else 'offer'
    query = TradeListing.query.filter_by(group_id=group.id, status='open')
    query = query.join(TradeOffer)
    query = query.filter(*searchable_stock())
    bundle_offer = aliased(TradeOffer)
    missing_bundle_stock = select(bundle_offer.id).where(bundle_offer.listing_id == TradeListing.id,
        ~and_(*searchable_stock(bundle_offer, TradeListing, True))).correlate(TradeListing).exists()
    query = query.filter(or_(TradeListing.bundle.is_(False), ~missing_bundle_stock))

    if side == 'want':
        query = query.join(TradeWant).join(Photo, Photo.id == TradeWant.photo_id)
    else:
        query = query.join(Photo, Photo.id == TradeOffer.photo_id).filter(TradeOffer.quantity > 0)
    query = query.join(Member).join(Costume).join(PhotoType)
    for param, column in [('member', Member.id), ('costume', Costume.id), ('type', PhotoType.id), ('photo_id', Photo.id)]:
        value = request.args.get(param, type=int)
        if value is not None:
            query = query.filter(column == value)
    keyword = request.args.get('q', '').strip()[:100]
    if keyword:
        for word in keyword.split()[:5]:
            pattern = '%' + word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            query = query.filter(or_(Member.name.ilike(pattern, escape='\\'), Costume.name.ilike(pattern, escape='\\'), PhotoType.name.ilike(pattern, escape='\\')))
    method = request.args.get('method', '')
    if method in ('mail', 'meet'):
        query = query.filter(TradeListing.method.in_([method, 'either']))
    bundle = request.args.get('bundle') == '1'
    if bundle:
        query = query.filter(TradeListing.bundle.is_(True))
    # SQL pagination and distinct listings; no cross-product trade cards.
    photo_details = (joinedload(Photo.member), joinedload(Photo.costume), joinedload(Photo.photo_type))
    query = query.options(
        selectinload(TradeListing.offers).joinedload(TradeOffer.photo).options(*photo_details),
        selectinload(TradeListing.offers).joinedload(TradeOffer.image),
        selectinload(TradeListing.offers).selectinload(TradeOffer.wants).joinedload(TradeWant.photo).options(*photo_details))
    pagination = query.distinct().order_by(TradeListing.updated_at.desc(), TradeListing.id.desc()).paginate(
        page=request.args.get('page', 1, type=int), per_page=20, error_out=False)
    listings = pagination.items
    availability = available_for_listings(listings)
    members = Member.query.filter_by(group_id=group.id).order_by(Member.generation, Member.display_order, Member.id).all()
    costumes = Costume.query.filter_by(group_id=group.id).order_by(Costume.name).all()
    types = PhotoType.query.join(Photo).join(Member).filter(Member.group_id == group.id).distinct().all()
    args = {key:str(value) for key in ('member','costume','type','photo_id')
            if (value := request.args.get(key,type=int)) is not None}
    if keyword:
        args['q'] = keyword
    if side == 'want':
        args['side'] = side
    if method in ('mail','meet'):
        args['method'] = method
    if bundle:
        args['bundle'] = '1'
    def browse_url(**changes):
        values = dict(args)
        values.update(changes)
        return url_for('trade.search', group_key=group.key, **{key:value for key,value in values.items() if value is not None})
    tags = []
    if keyword:
        tags.append(dict(label=keyword, url=browse_url(q=None)))
    for key, values in [('member', members), ('costume', costumes), ('type', types)]:
        selected = next((item for item in values if str(item.id) == args.get(key)), None)
        if selected:
            tags.append(dict(label=selected.name, url=browse_url(**{key:None})))
    if args.get('photo_id'):
        tags.append(dict(label='指定した写真', url=browse_url(photo_id=None)))
    if side == 'want':
        tags.append(dict(label='求の写真から', url=browse_url(side=None)))
    if method in ('mail','meet'):
        tags.append(dict(label=METHODS[method], url=browse_url(method=None)))
    if bundle:
        tags.append(dict(label='セット交換', url=browse_url(bundle=None)))
    selected_member = args.get('member')
    selected_member_id = request.args.get('member',type=int)
    quick_members = sorted(members, key=lambda item: item.id != selected_member_id) if selected_member_id is not None else members
    return render('search', group, listings=listings, pagination=pagination, side=side,
        members=members, costumes=costumes, types=types, args=args, keyword=keyword,
        availability=availability, filter_tags=tags, bundle=bundle,
        browse_links=dict(new=url_for('trade.search',group_key=group.key),
                          mail=browse_url(method='mail',bundle=None), meet=browse_url(method='meet',bundle=None),
                          bundle=browse_url(method=None,bundle='1')),
        member_links=[dict(label='すべて', active=not selected_member, url=browse_url(member=None))] +
                     [dict(label=item.name, active=selected_member==str(item.id),
                           url=browse_url(member=item.id,photo_id=None)) for item in quick_members],
        previews={listing.id:listing_preview(listing,availability[listing.id],side,args,keyword) for listing in listings},
        next_url=browse_url(page=pagination.next_num) if pagination.has_next else None)


@trade_bp.after_request
def private_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@trade_bp.route('/<group_key>/photos')
@login_required
def photos(group_key):
    group = group_or_404(group_key)
    q = Photo.query.join(Member).join(Costume).join(PhotoType).filter(
        Member.group_id == group.id, Costume.group_id == group.id)
    owned = request.args.get('owned') == '1'
    stock = stock_map(current_user.id) if owned else {}
    reserved = reserved_counts(current_user.id) if owned else {}
    if owned:
        q = q.join(UserPhoto, UserPhoto.photo_id == Photo.id).filter(UserPhoto.user_id == current_user.id, UserPhoto.quantity > 0)
    # Only offer combinations that actually exist in Photo, within the current scope.
    members = q.with_entities(Member.id, Member.name, Member.generation, Member.display_order).distinct().order_by(
        Member.generation, Member.display_order, Member.id).all()
    member = request.args.get('member', type=int)
    if member not in {row.id for row in members}:
        member = None
    if member:
        q = q.filter(Member.id == member)
    costumes = q.with_entities(Costume.id, Costume.name).distinct().order_by(Costume.name, Costume.id).all()
    costume = request.args.get('costume', type=int)
    if costume not in {row.id for row in costumes}:
        costume = None
    if costume:
        q = q.filter(Costume.id == costume)
    types = q.with_entities(PhotoType.id, PhotoType.name).distinct().order_by(PhotoType.name, PhotoType.id).all()
    photo_type = request.args.get('type', type=int)
    if photo_type not in {row.id for row in types}:
        photo_type = None
    if photo_type:
        q = q.filter(PhotoType.id == photo_type)
    for word in request.args.get('q', '').strip()[:100].split()[:5]:
        pattern = '%' + word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        q = q.filter(or_(Member.name.ilike(pattern, escape='\\'), Costume.name.ilike(pattern, escape='\\'), PhotoType.name.ilike(pattern, escape='\\')))
    pag = q.options(joinedload(Photo.member), joinedload(Photo.costume), joinedload(Photo.photo_type)).order_by(
        Member.generation, Member.display_order, Member.id, Costume.name, Photo.id).paginate(
            page=request.args.get('page', 1, type=int), per_page=40, error_out=False)
    items = []
    for ph in pag.items:
        available = max(0, stock[ph.id].quantity - reserved.get(ph.id, 0)) if owned else None
        items.append(dict(id=ph.id, **photo_fields(ph),
                          available=available, has_image=bool(stock[ph.id].images) if owned else False))
    return jsonify(items=items, has_next=pag.has_next, page=pag.page,
        options={key:[dict(id=row.id, name=row.name) for row in values]
                 for key, values in [('member',members), ('costume',costumes), ('type',types)]},
        filters=dict(member=str(member or ''), costume=str(costume or ''), type=str(photo_type or '')))


def choices(group):
    return dict(members=Member.query.filter_by(group_id=group.id).order_by(Member.generation, Member.display_order, Member.id).all(),
        costumes=Costume.query.filter_by(group_id=group.id).order_by(Costume.name).all(),
        types=PhotoType.query.join(Photo).join(Member).filter(Member.group_id == group.id).distinct().all())


def editor_data(listing):
    return dict(alias=listing.alias, method=listing.method, location=listing.location, notes=listing.notes, bundle=listing.bundle,
        offers=[dict(photo_id=o.photo_id, **photo_fields(o.photo), quantity=o.quantity,
                     want_mode=o.want_mode, share_image=bool(o.image_id),
                     wants=[dict(photo_id=w.photo_id, **photo_fields(w.photo), quantity=w.quantity, priority=w.priority) for w in o.wants])
                for o in listing.offers if o.quantity > 0])


def photo_label(photo):
    return f'{photo.member.name} / {photo.costume.name} / {photo.photo_type.name}'


def photo_fields(photo):
    return dict(label=photo_label(photo), member=photo.member.name,
                costume=photo.costume.name, type=photo.photo_type.name)


@trade_bp.route('/<group_key>/new', methods=['GET', 'POST'])
@login_required
def new_listing(group_key):
    group = group_or_404(group_key)
    data = dict(alias='募集者', method='either', location='', notes='', bundle=False, offers=[])
    if request.method == 'POST':
        try:
            data = payload()
            lock_users(current_user.id)
            listing = TradeListing(user_id=current_user.id, group_id=group.id)
            db.session.add(listing)
            listing_data(listing, current_user.id, data)
            db.session.commit()
            return redirect(url_for('trade.listing_detail', public_id=listing.public_id))
        except TradeError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    return render('editor', group, initial=data, listing=None, **choices(group))


@trade_bp.route('/listing/<public_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_listing(public_id):
    listing = owned_listing(public_id)
    group = listing.group
    if TradeProposal.query.filter_by(listing_id=listing.id, status='accepted').first():
        flash('交換確定中の取引があるため編集できません。公開停止と取引管理は利用できます。', 'warning')
        return redirect(url_for('trade.listing_detail', public_id=public_id))
    data = editor_data(listing)
    if request.method == 'POST':
        try:
            data = payload()
            lock_users(current_user.id)
            listing = db.session.get(TradeListing, listing.id, populate_existing=True)
            if TradeProposal.query.filter_by(listing_id=listing.id, status='accepted').first():
                raise TradeError('交換確定中の取引があるため編集できません。')
            for proposal in TradeProposal.query.filter_by(listing_id=listing.id, status='pending').all():
                proposal.status = 'rejected'
                log(proposal, '募集内容が変更されたため、この提案は見送りになりました。')
            listing_data(listing, current_user.id, data)
            db.session.commit()
            return redirect(url_for('trade.listing_detail', public_id=public_id))
        except TradeError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    return render('editor', group, initial=data, listing=listing, **choices(group))


@trade_bp.route('/listing/<public_id>')
def listing_detail(public_id):
    listing = TradeListing.query.filter_by(public_id=public_id).first_or_404()
    is_owner = current_user.is_authenticated and current_user.id == listing.user_id
    if listing.status != 'open' and not is_owner:
        abort(404)
    return render('listing', listing.group, listing=listing, is_owner=is_owner,
        available=offer_available(listing), **(choices(listing.group) if current_user.is_authenticated else {}))


@trade_bp.route('/listing/<public_id>/visibility', methods=['POST'])
@login_required
def visibility(public_id):
    listing = owned_listing(public_id)
    try:
        lock_users(current_user.id)
        listing = db.session.get(TradeListing, listing.id, populate_existing=True)
        if request.form.get('action') == 'publish':
            if request.form.get('confirm_public') != '1':
                raise TradeError('公開される内容を確認し、チェックを入れてください。')
            publish(listing)
        elif request.form.get('action') == 'pause':
            listing.status = 'paused'
        else:
            raise TradeError('公開操作を確認してください。')
        db.session.commit()
        flash('募集の公開設定を更新しました。', 'success')
    except TradeError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(url_for('trade.listing_detail', public_id=public_id))


@trade_bp.route('/<group_key>/mine')
@login_required
def mine(group_key):
    group = group_or_404(group_key)
    pag = TradeListing.query.filter_by(user_id=current_user.id, group_id=group.id).order_by(
        TradeListing.updated_at.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=20, error_out=False)
    return render('mine', group, listings=pag.items, pagination=pag, args={})


@trade_bp.route('/listing/<public_id>/propose', methods=['POST'])
@login_required
def propose(public_id):
    listing = TradeListing.query.filter_by(public_id=public_id, status='open').first_or_404()
    if listing.user_id == current_user.id:
        abort(400)
    try:
        data = payload()
        lock_users(listing.user_id, current_user.id)
        listing = db.session.get(TradeListing, listing.id, populate_existing=True)
        owner_items = parse_items(data.get('owner_items'), listing.group_id)
        applicant_items = parse_items(data.get('applicant_items'), listing.group_id)
        validate_proposal(listing, owner_items, applicant_items, current_user.id)
        method = data.get('method')
        if method not in ('mail', 'meet') or listing.method not in (method, 'either'):
            raise TradeError('募集に合う交換方法を選択してください。')
        proposal = TradeProposal(listing_id=listing.id, applicant_id=current_user.id,
            alias=bounded(data.get('alias', ''), 30, '相談用の表示名', True), method=method)
        for side, items in [('owner', owner_items), ('applicant', applicant_items)]:
            for pid, qty in items.items():
                proposal.items.append(TradeProposalItem(side=side, photo_id=pid, quantity=qty))
        log(proposal, '交換案が届きました。承認時に双方の写真を取り置きします。')
        note = bounded(data.get('note', ''), 2000, 'メッセージ')
        if note:
            log(proposal, note, current_user.id)
        db.session.add(proposal)
        db.session.commit()
        return redirect(url_for('trade.transaction', public_id=proposal.public_id))
    except TradeError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return redirect(url_for('trade.listing_detail', public_id=public_id))


@trade_bp.route('/<group_key>/transactions')
@login_required
def transactions(group_key):
    group = group_or_404(group_key)
    pag = TradeProposal.query.join(TradeListing).filter(TradeListing.group_id == group.id,
        or_(TradeListing.user_id == current_user.id, TradeProposal.applicant_id == current_user.id))\
        .order_by(TradeProposal.updated_at.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=20, error_out=False)
    return render('transactions', group, transactions=pag.items, pagination=pag, args={})


@trade_bp.route('/transaction/<public_id>', methods=['GET', 'POST'])
@login_required
def transaction(public_id):
    proposal = private_proposal(public_id)
    owner_side = proposal.listing.user_id == current_user.id
    if request.method == 'POST':
        try:
            lock_users(proposal.listing.user_id, proposal.applicant_id)
            proposal = db.session.get(TradeProposal, proposal.id, populate_existing=True)
            db.session.get(TradeListing, proposal.listing_id, populate_existing=True)
            action = request.form.get('action')
            if action == 'message':
                if proposal.status not in ('pending', 'accepted'):
                    raise TradeError('終了した取引にはメッセージを送れません。')
                log(proposal, bounded(request.form.get('body', ''), 2000, 'メッセージ', True), current_user.id)
            elif action == 'accept':
                if not owner_side or proposal.status != 'pending':
                    raise TradeError('この提案は承認できません。')
                sides = {side: {i.photo_id: i.quantity for i in proposal.items if i.side == side} for side in ('owner', 'applicant')}
                validate_proposal(proposal.listing, sides['owner'], sides['applicant'], proposal.applicant_id)
                proposal.status = 'accepted'
                log(proposal, '交換内容を確定し、双方の写真を取り置きしました。')
            elif action == 'share_photos':
                if proposal.status not in ('pending', 'accepted'):
                    raise TradeError('終了した取引の写真は共有できません。')
                side = 'owner' if owner_side else 'applicant'
                for item in proposal.items:
                    if item.side == side:
                        image = UserPhotoImage.query.join(UserPhoto).filter(UserPhotoImage.user_id == current_user.id,
                            UserPhoto.user_id == current_user.id, UserPhoto.photo_id == item.photo_id).order_by(UserPhotoImage.id).first()
                        item.image_id = image.id if image else None
                log(proposal, ('募集者' if owner_side else '応募者') + 'が登録済みの実物画像をこの取引内で共有しました。')
            elif action in ('reject', 'cancel'):
                if proposal.status != 'pending' or (action == 'reject' and not owner_side):
                    raise TradeError('確定済みの交換は一方だけでは取り消せません。')
                proposal.status = 'rejected' if action == 'reject' else 'cancelled'
                log(proposal, '提案を見送りました。' if action == 'reject' else '提案を取り消しました。')
            elif action == 'request_cancel':
                if proposal.status != 'accepted' or proposal.owner_received_at or proposal.applicant_received_at:
                    raise TradeError('受取確認後は取り消せません。')
                marker = f'キャンセル申請:{current_user.id}'
                if not any(m.sender_id is None and m.body == marker for m in proposal.messages):
                    log(proposal, marker)
            elif action == 'agree_cancel':
                other = proposal.applicant_id if owner_side else proposal.listing.user_id
                if proposal.status != 'accepted' or proposal.owner_received_at or proposal.applicant_received_at or not any(m.sender_id is None and m.body == f'キャンセル申請:{other}' for m in proposal.messages):
                    raise TradeError('相手からのキャンセル申請が必要です。')
                proposal.status = 'cancelled'
                log(proposal, '双方がキャンセルに合意しました。取り置きを解除しました。')
            elif action in ('sent', 'received'):
                if proposal.status != 'accepted':
                    raise TradeError('交換確定後に操作してください。')
                side = 'owner' if owner_side else 'applicant'
                field = f'{side}_{action}_at'
                if action == 'received':
                    other_side = 'applicant' if owner_side else 'owner'
                    if proposal.method == 'mail' and not getattr(proposal, f'{other_side}_sent_at'):
                        raise TradeError('相手の発送連絡後に受取確認をしてください。')
                if not getattr(proposal, field):
                    setattr(proposal, field, datetime.utcnow())
                    log(proposal, ('募集者' if owner_side else '応募者') + ('が発送を連絡しました。' if action == 'sent' else 'が受取を確認しました。'))
                complete(proposal)
            else:
                raise TradeError('操作を確認してください。')
            db.session.commit()
            flash('取引を更新しました。', 'success')
        except TradeError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
        return redirect(url_for('trade.transaction', public_id=public_id))
    other = proposal.applicant_id if owner_side else proposal.listing.user_id
    cancellation_requested = any(m.sender_id is None and m.body == f'キャンセル申請:{other}' for m in proposal.messages)
    return render('transaction', proposal.listing.group, proposal=proposal, owner_side=owner_side,
        cancellation_requested=cancellation_requested)
