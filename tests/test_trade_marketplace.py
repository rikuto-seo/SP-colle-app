"""Trade integration tests against an isolated SQLite DB, never app.py/.env."""
import ast
import json
import os
from pathlib import Path
import unittest
os.environ.setdefault('SECRET_KEY', 'isolated-test-only')
from flask import Flask, g, request, jsonify, redirect, template_rendered, url_for as flask_url_for
from flask_login import LoginManager
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from extensions import db, csrf
from models import User, Group, Member, Costume, PhotoType, Photo, UserPhoto, UserPhotoImage, WantPhoto, WantShare, WantMember
from trade.models import TradeListing, TradeOffer, TradeWant, TradeProposal, TradeMessage
from trade.routes import trade_bp
from routes.photo import photo_bp
from want import want_bp
from trade.service import reserved_counts, TradeError, assert_stock_floor

ROOT = Path(__file__).resolve().parents[1]


def make_app():
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.config.update(SECRET_KEY='trade-fixture-secret', SQLALCHEMY_DATABASE_URI='sqlite://',
        SQLALCHEMY_TRACK_MODIFICATIONS=False, WTF_CSRF_ENABLED=False, TESTING=True)
    db.init_app(app)
    csrf.init_app(app)
    manager = LoginManager(app)
    manager.login_view = 'fixture_login'
    manager.user_loader(lambda uid: db.session.get(User, int(uid)))
    app.add_url_rule('/fixture-login', 'fixture_login', lambda: 'fixture login')
    app.register_blueprint(trade_bp)
    app.register_blueprint(photo_bp)
    app.register_blueprint(want_bp)
    app.jinja_env.filters['normalize_type'] = lambda value, *args: value
    def safe_url(endpoint, **values):
        if endpoint in app.view_functions:
            return flask_url_for(endpoint, **values)
        return '/fixture-link/' + endpoint
    app.jinja_env.globals['url_for'] = safe_url
    with app.app_context():
        @event.listens_for(db.engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    return app


def seed():
    db.create_all()
    db.session.add_all([Group(id=1,key='hinatazaka',name='日向坂46'), Group(id=2,key='nogizaka',name='乃木坂46')])
    for uid in (100,200,300):
        db.session.add(User(id=uid, firebase_uid=f'fixture-{uid}', username=f'PRIVATE-NAME-{uid}',
            email=f'private-{uid}@example.invalid', twitter_id=f'privateSNS{uid}', plan_type='free',
            primary_group='hinatazaka', selected_groups='hinatazaka'))
    db.session.add_all([Member(id=1,name='メンバーA',group_id=1), Member(id=2,name='メンバーB',group_id=1),
                       Member(id=3,name='他グループ',group_id=2)])
    db.session.add_all([Costume(id=1,name='2026年 春の制服',group_id=1), Costume(id=2,name='ライブ衣装',group_id=1),
                       Costume(id=3,name='他グループ衣装',group_id=2)])
    db.session.add_all([PhotoType(id=1,name='ヨリ'),PhotoType(id=2,name='チュウ'),PhotoType(id=3,name='ヒキ')])
    db.session.flush()
    db.session.add_all([Photo(id=1001,member_id=1,costume_id=1,type_id=1),
        Photo(id=1002,member_id=2,costume_id=1,type_id=2), Photo(id=1003,member_id=2,costume_id=2,type_id=3),
        Photo(id=1004,member_id=3,costume_id=3,type_id=1)])
    db.session.flush()
    db.session.add_all([UserPhoto(user_id=100,photo_id=1001,quantity=2),
        UserPhoto(user_id=200,photo_id=1002,quantity=5),UserPhoto(user_id=200,photo_id=1003,quantity=2),
        UserPhoto(user_id=300,photo_id=1002,quantity=3)])
    db.session.commit()


class TradeMarketplaceTest(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.ctx = self.app.app_context(); self.ctx.push()
        seed()
        self.client = self.app.test_client()
        self.login(100)

    def tearDown(self):
        db.session.remove(); db.drop_all(); db.engine.dispose(); self.ctx.pop()

    def login(self, uid):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session['_user_id'] = str(uid); session['_fresh'] = True

    def listing(self, mode='any', wants=None, qty=2):
        data = dict(alias='交換用の名前', method='either', location='イベント会場',notes='同種優先',
            offers=[dict(photo_id=1001,quantity=qty,want_mode=mode,share_image=False,
                wants=wants or [dict(photo_id=1002,quantity=1,priority='high')])])
        response = self.client.post('/trade/hinatazaka/new', data={'payload':json.dumps(data)})
        self.assertEqual(response.status_code,302)
        return TradeListing.query.order_by(TradeListing.id.desc()).first()

    def publish(self, listing):
        return self.client.post(f'/trade/listing/{listing.public_id}/visibility',
            data={'action':'publish','confirm_public':'1'})

    def propose(self, listing, owner_qty=1, provides=None):
        self.login(200)
        response = self.client.post(f'/trade/listing/{listing.public_id}/propose', data={'payload':json.dumps(dict(
            alias='応募用の名前', method='mail', owner_items=[dict(photo_id=1001,quantity=owner_qty)],
            applicant_items=provides or [dict(photo_id=1002,quantity=owner_qty)],note='交換をお願いします。'))})
        self.assertEqual(response.status_code,302)
        return TradeProposal.query.order_by(TradeProposal.id.desc()).first()

    def action(self, proposal, action, uid=100):
        self.login(uid)
        return self.client.post(f'/trade/transaction/{proposal.public_id}',data={'action':action})

    def test_draft_opt_in_exact_bidirectional_search_and_privacy(self):
        listing = self.listing()
        self.assertEqual(listing.status,'draft')
        owner_url=f'/trade/listing/{listing.public_id}'
        self.assertIn('公開内容の確認', self.client.get(owner_url).get_data(as_text=True))
        self.login(200)
        self.assertEqual(self.client.get(owner_url).status_code,404)
        self.login(100)
        self.client.post(owner_url+'/visibility',data={'action':'publish'})
        self.assertEqual(listing.status,'draft')
        self.publish(listing)
        for uid in (None,200):
            if uid is None:
                g.pop('_login_user', None)
                with self.client.session_transaction() as session: session.clear()
            else: self.login(uid)
            for side,pid in [('offer',1001),('want',1002)]:
                html=self.client.get(f'/trade/hinatazaka?side={side}&photo_id={pid}').get_data(as_text=True)
                self.assertIn('交換用の名前',html)
                for secret in ['PRIVATE-NAME-100','private-100@','privateSNS100']:
                    self.assertNotIn(secret,html)
            self.assertNotIn('交換用の名前',self.client.get('/trade/hinatazaka?side=offer&photo_id=1003').get_data(as_text=True))
            self.assertNotIn('交換用の名前',self.client.get('/trade/nogizaka').get_data(as_text=True))
        self.login(100)
        self.client.post(owner_url+'/visibility',data={'action':'pause'})
        self.assertNotIn('交換用の名前',self.client.get('/trade/hinatazaka').get_data(as_text=True))

    def test_full_mail_lifecycle_inventory_once_and_private_messages(self):
        listing=self.listing(); self.publish(listing)
        db.session.add_all([WantPhoto(user_id=100,photo_id=1002),WantPhoto(user_id=200,photo_id=1001),
                            WantPhoto(user_id=100,photo_id=1003,is_infinite=True)])
        db.session.commit()
        proposal=self.propose(listing)
        self.action(proposal,'accept')
        self.assertEqual(proposal.status,'accepted')
        self.assertEqual(reserved_counts(100),{1001:1})
        self.assertEqual(reserved_counts(200),{1002:1})
        self.action(proposal,'received')
        self.assertIsNone(proposal.owner_received_at)
        self.action(proposal,'sent'); self.action(proposal,'sent',200)
        self.action(proposal,'received')
        self.assertEqual(proposal.status,'accepted')
        self.action(proposal,'received',200)
        self.assertEqual(proposal.status,'completed')
        self.assertEqual(UserPhoto.query.filter_by(user_id=100,photo_id=1001).one().quantity,1)
        self.assertEqual(UserPhoto.query.filter_by(user_id=200,photo_id=1001).one().quantity,1)
        self.assertEqual(UserPhoto.query.filter_by(user_id=100,photo_id=1002).one().quantity,1)
        self.assertEqual(UserPhoto.query.filter_by(user_id=200,photo_id=1002).one().quantity,4)
        self.assertEqual(WantPhoto.query.filter_by(photo_id=1001).count(),0)
        self.assertEqual(WantPhoto.query.filter_by(photo_id=1002).count(),0)
        self.assertEqual(WantPhoto.query.filter_by(photo_id=1003,is_infinite=True).count(),1)
        self.action(proposal,'received',200)
        self.assertEqual(UserPhoto.query.filter_by(user_id=200,photo_id=1001).one().quantity,1)
        self.assertEqual(reserved_counts(100),{})
        self.login(300)
        self.assertEqual(self.client.get(f'/trade/transaction/{proposal.public_id}').status_code,404)
        self.assertEqual(self.client.post(f'/trade/transaction/{proposal.public_id}',data={'action':'message','body':'intrusion'}).status_code,404)

    def test_overlapping_proposals_reservation_and_mutual_cancellation(self):
        listing=self.listing(qty=1); self.publish(listing)
        first=self.propose(listing)
        second=self.propose(listing)
        self.action(first,'accept')
        self.action(second,'accept')
        self.assertEqual(second.status,'pending')
        self.action(first,'cancel')
        self.assertEqual(first.status,'accepted')
        self.action(first,'agree_cancel')
        self.assertEqual(first.status,'accepted')
        self.action(first,'request_cancel',200)
        self.action(first,'agree_cancel')
        self.assertEqual(first.status,'cancelled')
        self.assertEqual(reserved_counts(100),{})
        self.action(second,'accept')
        self.assertEqual(second.status,'accepted')

    def test_all_required_photos_and_multi_copy_alternatives(self):
        listing=self.listing(mode='all', wants=[dict(photo_id=1002,quantity=2,priority='high'),dict(photo_id=1003,quantity=1,priority='normal')])
        self.publish(listing)
        self.propose(listing)
        self.assertEqual(TradeProposal.query.count(),0)
        proposal=self.propose(listing,provides=[dict(photo_id=1002,quantity=2),dict(photo_id=1003,quantity=1)])
        self.assertIsNotNone(proposal)
        self.action(proposal,'accept')
        self.assertEqual(reserved_counts(200),{1002:2,1003:1})

    def test_stock_edit_delete_and_give_cannot_break_reservations(self):
        listing=self.listing(); self.publish(listing)
        proposal=self.propose(listing,owner_qty=2)
        self.action(proposal,'accept')
        up=UserPhoto.query.filter_by(user_id=100,photo_id=1001).one()
        self.client.post(f'/update_user_photo/hinatazaka/{up.id}',data={'quantity':'0','available_quantity':'0'})
        self.assertEqual(db.session.get(UserPhoto,up.id).quantity,2)
        response=self.client.post(f'/update_user_photo/hinatazaka/{up.id}',data={'quantity':'0'},headers={'X-Requested-With':'XMLHttpRequest'})
        self.assertEqual(response.status_code,409)
        self.assertFalse(response.json['success'])
        self.client.post(f'/delete_user_photo/hinatazaka/{up.id}')
        self.assertIsNotNone(db.session.get(UserPhoto,up.id))
        self.client.post('/give/hinatazaka',data={'member':'メンバーA','costume':'2026年 春の制服','photo_type':'ヨリ','quantity':'1'})
        self.assertEqual(db.session.get(UserPhoto,up.id).quantity,2)
        with self.assertRaises(TradeError): assert_stock_floor(100,1001,0)

    def test_validation_scope_publication_overlap_and_csrf(self):
        listing=self.listing(qty=2); self.publish(listing)
        second=self.listing(qty=1); self.publish(second)
        self.assertEqual(second.status,'draft')
        self.login(200)
        self.assertEqual(self.client.post(f'/trade/listing/{listing.public_id}/visibility',data={'action':'pause'}).status_code,404)
        data=dict(alias='invalid',method='either',location='',notes='',offers=[dict(photo_id=1004,quantity=1,wants=[dict(photo_id=1002,quantity=1)])])
        self.client.post('/trade/hinatazaka/new',data={'payload':json.dumps(data)})
        self.assertEqual(TradeListing.query.count(),2)
        self.app.config['WTF_CSRF_ENABLED']=True
        self.assertEqual(self.client.post('/trade/hinatazaka/new',data={'payload':'{}'}).status_code,400)

    def test_edit_invalidates_pending_and_preserves_accepted(self):
        listing=self.listing(); self.publish(listing)
        proposal=self.propose(listing)
        self.login(100)
        response=self.client.get(f'/trade/listing/{listing.public_id}/edit')
        self.assertEqual(response.status_code,200)
        data=dict(alias='編集後',method='mail',location='',notes='',offers=[dict(photo_id=1001,quantity=2,wants=[dict(photo_id=1002,quantity=1)])])
        self.client.post(f'/trade/listing/{listing.public_id}/edit',data={'payload':json.dumps(data)})
        self.assertEqual(proposal.status,'rejected')
        self.publish(listing)
        proposal=self.propose(listing)
        self.action(proposal,'accept')
        self.assertEqual(self.client.get(f'/trade/listing/{listing.public_id}/edit').status_code,302)
        self.assertEqual(proposal.status,'accepted')

    def test_fully_reserved_offers_disappear_from_both_search_directions(self):
        listing=self.listing(qty=1); self.publish(listing)
        proposal=self.propose(listing); self.action(proposal,'accept')
        for side in ('offer','want'):
            html=self.client.get(f'/trade/hinatazaka?side={side}').get_data(as_text=True)
            self.assertNotIn('交換用の名前',html)

    def test_infinite_wish_registration_and_independent_publicity(self):
        self.client.post('/want/hinatazaka/add',data={'member':'メンバーB','costume':'','photo_type':'','is_infinite':'1'})
        self.assertEqual(WantMember.query.count(),1)
        self.assertIn('無限回収中',self.client.get('/want/hinatazaka').get_data(as_text=True))
        share=WantShare.query.filter_by(user_id=100).one()
        share.is_public=True; db.session.commit()
        self.assertFalse(share.want_public)
        self.client.post('/want/share_toggle/hinatazaka')
        self.assertTrue(share.want_public); self.assertTrue(share.is_public)
        self.client.post('/want/share_toggle/hinatazaka')
        self.assertFalse(share.want_public); self.assertTrue(share.is_public)
        self.client.post('/want/share_toggle/hinatazaka')
        uuid=db.session.get(User,100).public_uuid
        self.login(200)
        self.assertIn('無限回収中',self.client.get(f'/want/share/{uuid}/hinatazaka').get_data(as_text=True))
        result=self.client.get(f'/trade/match/{uuid}/hinatazaka').json
        # Old compatibility checker still respects the explicit available quantity.
        self.assertEqual(result['i_can_give'],[])
        up=UserPhoto.query.filter_by(user_id=200,photo_id=1002).one(); up.available_quantity=1; db.session.commit()
        self.assertEqual(len(self.client.get(f'/trade/match/{uuid}/hinatazaka').json['i_can_give']),1)
        self.assertEqual(self.client.post(f'/want/infinite/delete/{WantMember.query.one().id}').status_code,404)

    def test_images_are_shared_only_by_explicit_owner_consent(self):
        up=UserPhoto.query.filter_by(user_id=100,photo_id=1001).one()
        image=UserPhotoImage(user_id=100,user_photo_id=up.id,image_key='private-original.webp',thumbnail_key='private-thumb.webp')
        db.session.add(image); db.session.commit()
        listing=self.listing(); self.publish(listing)
        self.assertIsNone(listing.offers[0].image_id)
        proposal=self.propose(listing)
        self.assertTrue(all(i.image_id is None for i in proposal.items))
        self.action(proposal,'share_photos')
        item=next(i for i in proposal.items if i.side=='owner')
        self.assertEqual(item.image_id,image.id)
        self.assertIsNone(listing.offers[0].image_id)
        self.login(300)
        self.assertEqual(self.client.get(f'/trade/transaction/{proposal.public_id}').status_code,404)

    def test_bundle_requires_whole_offer_and_wants_set_and_closes_after_completion(self):
        db.session.add(UserPhoto(user_id=100,photo_id=1003,quantity=1)); db.session.commit()
        data=dict(alias='コンプ交換',method='meet',location='',notes='',bundle=True,offers=[
            dict(photo_id=1001,quantity=1,wants=[dict(photo_id=1002,quantity=2)]),
            dict(photo_id=1003,quantity=1,wants=[])])
        self.client.post('/trade/hinatazaka/new',data={'payload':json.dumps(data)})
        listing=TradeListing.query.one(); self.publish(listing)
        self.assertIn('コンプ交換',self.client.get('/trade/hinatazaka').get_data(as_text=True))
        self.login(200)
        base=dict(alias='セット応募',method='meet',owner_items=[dict(photo_id=1001,quantity=1)],applicant_items=[dict(photo_id=1002,quantity=2)])
        self.client.post(f'/trade/listing/{listing.public_id}/propose',data={'payload':json.dumps(base)})
        self.assertEqual(TradeProposal.query.count(),0)
        base['owner_items'].append(dict(photo_id=1003,quantity=1))
        self.client.post(f'/trade/listing/{listing.public_id}/propose',data={'payload':json.dumps(base)})
        proposal=TradeProposal.query.one()
        self.action(proposal,'accept')
        self.assertNotIn('コンプ交換',self.client.get('/trade/hinatazaka').get_data(as_text=True))
        self.action(proposal,'received'); self.action(proposal,'received',200)
        self.assertEqual(proposal.status,'completed'); self.assertEqual(listing.status,'closed')
        self.assertEqual(UserPhoto.query.filter_by(user_id=100,photo_id=1002).one().quantity,2)

    def test_any_conditions_cannot_reuse_one_copy_for_multiple_provided_photos(self):
        db.session.add(UserPhoto(user_id=100,photo_id=1003,quantity=1)); db.session.commit()
        data=dict(alias='複数交換',method='mail',location='',notes='',offers=[
            dict(photo_id=pid,quantity=1,wants=[dict(photo_id=1002,quantity=1)]) for pid in (1001,1003)])
        self.client.post('/trade/hinatazaka/new',data={'payload':json.dumps(data)})
        listing=TradeListing.query.one(); self.publish(listing); self.login(200)
        proposal_data=dict(alias='希望者',method='mail',owner_items=[dict(photo_id=pid,quantity=1) for pid in (1001,1003)],
                           applicant_items=[dict(photo_id=1002,quantity=1)])
        self.client.post(f'/trade/listing/{listing.public_id}/propose',data={'payload':json.dumps(proposal_data)})
        self.assertEqual(TradeProposal.query.count(),0)
        proposal_data['applicant_items'][0]['quantity']=2
        self.client.post(f'/trade/listing/{listing.public_id}/propose',data={'payload':json.dumps(proposal_data)})
        self.assertEqual(TradeProposal.query.count(),1)

    def test_guest_pages_redirect_and_data_apis_return_login_json(self):
        # Execute only the actual handler; importing app.py would initialize external services.
        source = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
        handler = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'unauthorized')
        handler.decorator_list = []
        namespace = dict(request=request, jsonify=jsonify, redirect=redirect, url_for=flask_url_for)
        exec(compile(ast.Module(body=[handler], type_ignores=[]), 'app.py:unauthorized', 'exec'), namespace)
        self.app.add_url_rule('/login', 'auth.login', lambda: 'login')
        self.app.login_manager.unauthorized_handler(namespace['unauthorized'])
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session.clear()
        for path in ('/trade/hinatazaka/new', '/trade/hinatazaka/mine', '/trade/hinatazaka/transactions'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.startswith('/login?next='))
        for path in ('/trade/hinatazaka/photos', '/trade/match/unknown/hinatazaka'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json['error'], 'login_required')

    def test_search_paginates_and_batches_photo_and_stock_queries(self):
        UserPhoto.query.filter_by(user_id=100, photo_id=1001).one().quantity = 50
        for index in range(24):
            listing = TradeListing(user_id=100, group_id=1, alias=f'募集{index}', status='open', method='mail')
            offer = TradeOffer(photo_id=1001, quantity=1, want_mode='any')
            offer.wants.append(TradeWant(photo_id=1002, quantity=1, priority='normal'))
            listing.offers.append(offer)
            db.session.add(listing)
        db.session.commit()
        selects = []
        def count_select(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith('SELECT'):
                selects.append(statement)
        event.listen(db.engine, 'before_cursor_execute', count_select)
        try:
            response = self.client.get('/trade/hinatazaka')
        finally:
            event.remove(db.engine, 'before_cursor_execute', count_select)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True).count('class="card trade-listing-card"'), 20)
        self.assertLessEqual(len(selects), 15)
        page2 = self.client.get('/trade/hinatazaka?page=2').get_data(as_text=True)
        self.assertEqual(page2.count('class="card trade-listing-card"'), 4)

    def test_gallery_shows_matched_photos_on_both_sides(self):
        db.session.add(UserPhoto(user_id=100, photo_id=1003, quantity=1))
        db.session.commit()
        data = dict(alias='交換ギャラリー', method='mail', offers=[
            dict(photo_id=1001, quantity=1, wants=[dict(photo_id=1002, quantity=1, priority='high'),
                                                  dict(photo_id=1003, quantity=2, priority='low')]),
            dict(photo_id=1003, quantity=1, wants=[dict(photo_id=1002, quantity=1)])])
        self.client.post('/trade/hinatazaka/new', data={'payload':json.dumps(data)})
        listing = TradeListing.query.one(); self.publish(listing)
        contexts = []
        def capture(_sender, template, context, **extra):
            contexts.append(context)
        template_rendered.connect(capture, self.app)
        try:
            response = self.client.get('/trade/hinatazaka?photo_id=1003')
            self.assertEqual(response.status_code, 200)
            preview = contexts[-1]['previews'][listing.id]
            self.assertEqual(preview['offer'].photo_id, 1003)
            self.client.get('/trade/hinatazaka?side=want&photo_id=1003')
            preview = contexts[-1]['previews'][listing.id]
            self.assertEqual(preview['offer'].photo_id, 1001)
            self.assertEqual(preview['want'].photo_id, 1003)
            self.assertEqual(preview['want'].quantity, 2)
            self.assertIsNone(preview['image_url'])
        finally:
            template_rendered.disconnect(capture, self.app)

    def test_gallery_bundle_tab_filters_public_listings(self):
        regular = self.listing(qty=1); self.publish(regular)
        bundle = self.listing(qty=1)
        bundle.bundle = True; bundle.alias = 'セット募集'; db.session.commit(); self.publish(bundle)
        html = self.client.get('/trade/hinatazaka?bundle=1').get_data(as_text=True)
        self.assertIn('セット募集', html)
        self.assertNotIn('交換用の名前', html)
        self.assertEqual(html.count('class="card trade-listing-card"'), 1)


if __name__ == '__main__': unittest.main()
