"""Legacy QR matching remains separate from listing trades and respects privacy."""
import ast
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flask import g, request, jsonify, redirect, url_for
from flask_wtf.csrf import generate_csrf
from test_trade_marketplace import make_app, seed
from extensions import db
from models import User, UserPhoto, WantPhoto, WantShare, WantMember
from trade.models import TradeListing, TradeOffer, TradeWant, TradeProposal, TradeProposalItem


class Links(HTMLParser):
    def __init__(self, markup):
        super().__init__(); self.active=[]; self.feed(markup)
    def handle_starttag(self, tag, attrs):
        values=dict(attrs)
        if tag=='a' and 'aria-current' in values and values.get('href','').startswith('/trade/'):
            self.active.append(values['href'])


class QrCheckTest(unittest.TestCase):
    def setUp(self):
        self.app=make_app()
        self.app.config['WTF_CSRF_ENABLED']=True
        source=ast.parse((ROOT/'app.py').read_text(encoding='utf-8'))
        handler=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='unauthorized')
        handler.decorator_list=[]
        namespace=dict(request=request,jsonify=jsonify,redirect=redirect,url_for=url_for)
        exec(compile(ast.Module(body=[handler],type_ignores=[]),'app.py:unauthorized','exec'),namespace)
        self.app.login_manager.unauthorized_handler(namespace['unauthorized'])
        self.app.add_url_rule('/login','auth.login',lambda:'login')
        self.app.add_url_rule('/test/csrf','test_csrf',lambda:jsonify(token=generate_csrf()))
        self.ctx=self.app.app_context();self.ctx.push()
        seed()
        UserPhoto.query.filter_by(user_id=100,photo_id=1001).one().available_quantity=2
        UserPhoto.query.filter_by(user_id=200,photo_id=1002).one().available_quantity=3
        UserPhoto.query.filter_by(user_id=200,photo_id=1003).one().available_quantity=1
        db.session.add_all([WantPhoto(user_id=100,photo_id=1002),WantPhoto(user_id=200,photo_id=1001),
            WantShare(user_id=200,group_key='hinatazaka',want_public=True,is_public=False)])
        db.session.commit()
        self.target=db.session.get(User,200)
        self.target_uuid=self.target.public_uuid
        self.share=WantShare.query.filter_by(user_id=200,group_key='hinatazaka').one()
        self.client=self.app.test_client();self.login(100)

    def tearDown(self):
        db.session.remove();db.drop_all();db.engine.dispose();self.ctx.pop()

    def login(self,uid):
        g.pop('_login_user',None);g.pop('csrf_token',None)
        with self.client.session_transaction() as session:
            session.clear()
            if uid is not None:session['_user_id']=str(uid);session['_fresh']=True

    def check(self,url,**kwargs):
        token=self.client.get('/test/csrf').json['token']
        return self.client.post('/trade/qr/hinatazaka/check',json={'url':url},headers={'X-CSRFToken':token},**kwargs)

    def public_url(self,key='hinatazaka'):
        return f'https://spcolle.com/want/share/{self.target_uuid}/{key}'

    def accepted(self,owner_qty,applicant_qty):
        listing=TradeListing(user_id=100,group_id=1,alias='Fixture listing',method='mail',status='open')
        offer=TradeOffer(photo_id=1001,quantity=owner_qty,want_mode='all')
        offer.wants.append(TradeWant(photo_id=1002,quantity=applicant_qty//owner_qty,priority='normal'))
        listing.offers.append(offer);db.session.add(listing);db.session.flush()
        proposal=TradeProposal(listing_id=listing.id,applicant_id=200,alias='Fixture applicant',method='mail',status='accepted')
        proposal.items.extend([TradeProposalItem(side='owner',photo_id=1001,quantity=owner_qty),
                               TradeProposalItem(side='applicant',photo_id=1002,quantity=applicant_qty)])
        db.session.add(proposal);db.session.commit()

    def test_sidebar_has_separate_entry_and_no_marketplace_navigation(self):
        html=self.client.get('/trade/qr/hinatazaka').get_data(as_text=True)
        self.assertIn('QR交換チェック',html)
        self.assertIn('id="qr-file"',html)
        self.assertNotIn('class="trade-nav"',html)
        self.assertEqual(Links(html).active,['/trade/qr/hinatazaka'])
        html=self.client.get('/trade/hinatazaka').get_data(as_text=True)
        self.assertIn('href="/trade/qr/hinatazaka"',html)
        self.assertIn('class="trade-nav"',html)

    def test_wish_qr_returns_both_sides_and_only_matched_photo_information(self):
        response=self.check(self.public_url())
        self.assertEqual(response.status_code,200)
        data=response.json
        self.assertEqual(data['group'],dict(key='hinatazaka',name='日向坂46'))
        self.assertEqual(data['i_can_give'],[dict(member='メンバーA',costume='2026年 春の制服',type='ヨリ',available=2)])
        self.assertEqual(data['they_can_give'],[dict(member='メンバーB',costume='2026年 春の制服',type='チュウ',available=3)])
        self.assertEqual(len(data['mutual']),1)
        for private in ('PRIVATE-NAME','private-200@','privateSNS','ライブ衣装'):
            self.assertNotIn(private,response.get_data(as_text=True))
        self.assertEqual(TradeListing.query.count(),0)
        self.assertEqual(TradeProposal.query.count(),0)

    def test_old_redirect_and_relative_links_still_work(self):
        for value in [f'https://spcolle.com/want/share_redirect/hinatazaka?uuid={self.target_uuid}',
                      f'/want/share/{self.target_uuid}/hinatazaka',
                      f'https://www.spcolle.com/want/share/{self.target_uuid}/hinatazaka?check=1']:
            self.assertEqual(self.check(value).status_code,200)

    def test_collection_qr_uses_share_uuid_and_both_publication_settings(self):
        url=f'https://spcolle.com/share/hinatazaka/{self.share.public_uuid}'
        self.assertEqual(self.check(url).status_code,404)
        self.share.is_public=True;db.session.commit()
        self.assertEqual(self.check(url).status_code,200)
        self.assertEqual(self.check(url.replace('/share/','/shared/')).status_code,200)
        self.share.want_public=False;db.session.commit()
        self.assertEqual(self.check(url).status_code,404)
        self.assertEqual(self.check(self.public_url()).status_code,404)

    def test_private_wishes_and_own_qr_are_rejected_without_publishing(self):
        self.share.want_public=False;db.session.commit()
        response=self.check(self.public_url())
        self.assertEqual(response.status_code,404)
        self.assertNotIn('i_can_give',response.json)
        self.assertFalse(self.share.want_public)
        self.assertFalse(self.share.is_public)
        own=db.session.get(User,100).public_uuid
        self.assertEqual(self.check(f'https://spcolle.com/want/share/{own}/hinatazaka').status_code,400)
        self.assertIsNone(WantShare.query.filter_by(user_id=100).first())

    def test_qr_group_is_detected_and_other_groups_never_mix(self):
        db.session.add_all([WantShare(user_id=200,group_key='nogizaka',want_public=True,is_public=False),
            UserPhoto(user_id=200,photo_id=1004,quantity=1,available_quantity=1),WantPhoto(user_id=100,photo_id=1004)])
        db.session.commit()
        response=self.check(self.public_url('nogizaka'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['group']['key'],'nogizaka')
        self.assertEqual(response.json['i_can_give'],[])
        self.assertEqual([p['member'] for p in response.json['they_can_give']],['他グループ'])

    def test_foreign_or_malformed_qr_never_becomes_a_redirect_or_request(self):
        for value in ['',None,[],{},'x'*2001,'https://example.com/want/share/'+self.target_uuid+'/hinatazaka',
            '//evil.example/want/share/'+self.target_uuid+'/hinatazaka',
            'https://spcolle.com.evil.example/want/share/'+self.target_uuid+'/hinatazaka',
            'https://attacker@spcolle.com/want/share/'+self.target_uuid+'/hinatazaka',
            'javascript:alert(1)','data:text/html,example','https://spcolle.com/trade/hinatazaka',
            'https://spcolle.com/want/share/invalid/hinatazaka',self.public_url('unknown')]:
            with self.subTest(value=str(value)[:90]):
                response=self.check(value)
                self.assertEqual(response.status_code,400)
                self.assertNotIn('Location',response.headers)

    def test_csrf_and_login_are_required_for_checking(self):
        self.assertEqual(self.client.post('/trade/qr/hinatazaka/check',json={'url':self.public_url()}).status_code,400)
        self.login(None)
        self.assertEqual(self.client.get('/trade/qr/hinatazaka').status_code,302)
        response=self.check(self.public_url())
        self.assertEqual(response.status_code,401)
        self.assertIn('/trade/qr/hinatazaka',response.json['redirect'])
        self.assertNotIn('/check',response.json['redirect'])

    def test_reserved_quantities_are_clamped_for_both_participants(self):
        self.accepted(1,4)
        response=self.check(self.public_url())
        self.assertEqual(response.json['i_can_give'][0]['available'],1)
        self.assertEqual(response.json['they_can_give'][0]['available'],1)
        old=self.client.get(f'/trade/match/{self.target_uuid}/hinatazaka').json
        self.assertEqual(old['i_can_give'],response.json['i_can_give'])
        self.assertEqual(old['they_can_give'],response.json['they_can_give'])

    def test_fully_reserved_photos_do_not_appear_as_give_or_mutual(self):
        self.accepted(2,2)
        data=self.check(self.public_url()).json
        self.assertEqual(data['i_can_give'],[])
        self.assertEqual(data['mutual'],[])

    def test_member_infinite_wishes_are_included(self):
        WantPhoto.query.filter_by(user_id=200,photo_id=1001).delete()
        db.session.add_all([WantMember(user_id=200,member_id=1),WantMember(user_id=100,member_id=2)])
        db.session.commit()
        data=self.check(self.public_url()).json
        self.assertEqual(len(data['i_can_give']),1)
        self.assertEqual(len(data['they_can_give']),2)
        self.assertEqual(data['mutual_total'],2)


if __name__=='__main__':unittest.main()
