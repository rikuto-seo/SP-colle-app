"""Dependent trade choices use real catalogue rows, never a master cross product."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SECRET_KEY', 'trade-picker-isolated-test')
from flask import g, template_rendered
from extensions import db
from models import Member, Costume, PhotoType, Photo, UserPhoto
from test_trade_marketplace import make_app, seed


class TradePickerTest(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.ctx = self.app.app_context(); self.ctx.push()
        seed()
        a, b = db.session.get(Member, 1), db.session.get(Member, 2)
        a.name = '松田好花'; a.generation = 2; a.display_order = 8
        b.generation = 2; b.display_order = 2
        for mid, name, generation, order in [(10,'先の期',1,9), (11,'同じ期の先頭',2,1), (12,'次の期',3,0)]:
            db.session.add(Member(id=mid, name=name, group_id=1, generation=generation, display_order=order))
        db.session.add_all([Costume(id=10,name='2018.winter',group_id=1), Costume(id=11,name='カンフー衣装',group_id=1),
                           Costume(id=12,name='写真のない衣装',group_id=1)])
        db.session.add_all([PhotoType(id=10,name='01'), PhotoType(id=11,name='ヨリ（カンフー）'),
                           PhotoType(id=12,name='写真のない種類')])
        db.session.flush()
        for mid in (10,11,12):
            db.session.add(Photo(id=2000+mid, member_id=mid, costume_id=1, type_id=1))
        db.session.add_all([Photo(id=3000,member_id=1,costume_id=10,type_id=10),
                           Photo(id=3001,member_id=1,costume_id=11,type_id=11)])
        db.session.flush()
        db.session.add_all([UserPhoto(user_id=100,photo_id=2010,quantity=1),
                           UserPhoto(user_id=100,photo_id=1003,quantity=1)])
        db.session.commit()
        self.client = self.app.test_client()
        g.pop('_login_user',None)
        with self.client.session_transaction() as session:
            session['_user_id']='100'; session['_fresh']=True

    def tearDown(self):
        db.session.remove(); db.drop_all(); db.engine.dispose(); self.ctx.pop()

    def photos(self, **args):
        response = self.client.get('/trade/hinatazaka/photos',query_string=args)
        self.assertEqual(response.status_code,200)
        return response.json

    def test_members_follow_generation_then_display_order_in_catalogue_and_stock(self):
        self.assertEqual([x['id'] for x in self.photos(owned=0)['options']['member']], [10,11,2,1,12])
        self.assertEqual([x['id'] for x in self.photos(owned=1)['options']['member']], [10,2,1])
        self.assertEqual([x['id'] for x in self.photos(owned=1)['items']], [2010,1003,1001])

    def test_costumes_and_types_only_include_existing_combinations(self):
        data = self.photos(owned=0, member=1)
        self.assertEqual({x['id'] for x in data['options']['costume']}, {1,10,11})
        data = self.photos(owned=0, member=1, costume=10)
        self.assertEqual(data['options']['type'], [{'id':10,'name':'01'}])
        self.assertEqual([x['id'] for x in data['items']], [3000])
        self.assertNotIn('ヨリ（カンフー）', [x['name'] for x in data['options']['type']])
        data = self.photos(owned=0, member=1, costume=11)
        self.assertEqual(data['options']['type'], [{'id':11,'name':'ヨリ（カンフー）'}])

    def test_stale_invalid_filters_are_cleared_to_a_real_combination(self):
        data = self.photos(owned=0,member=1,costume=10,type=11)
        self.assertEqual(data['filters'],dict(member='1',costume='10',type=''))
        self.assertEqual([x['id'] for x in data['items']], [3000])
        data = self.photos(owned=0,member=1,costume=2,type=3)
        self.assertEqual(data['filters']['costume'],'')
        self.assertTrue(all(x['member']=='松田好花' for x in data['items']))

    def test_wants_can_select_unowned_photos_but_offers_cannot(self):
        self.assertEqual([x['id'] for x in self.photos(owned=0,member=1,costume=10)['items']],[3000])
        data = self.photos(owned=1,member=1,costume=10)
        self.assertEqual(data['options']['costume'],[{'id':1,'name':'2026年 春の制服'}])
        self.assertEqual([x['id'] for x in data['items']],[1001])

    def test_labels_are_returned_separately_without_normalizing_or_splitting(self):
        db.session.get(Costume,11).name='カンフー / 別衣装'; db.session.commit()
        item=self.photos(owned=0,member=1,costume=11)['items'][0]
        self.assertEqual((item['member'],item['costume'],item['type']),('松田好花','カンフー / 別衣装','ヨリ（カンフー）'))

    def test_choices_cover_the_catalogue_beyond_the_first_page(self):
        for index in range(55):
            db.session.add(Member(id=100+index,name=f'追加メンバー{index}',group_id=1,generation=4,display_order=index))
        db.session.flush()
        for index in range(55):
            db.session.add(Photo(id=4000+index,member_id=100+index,costume_id=1,type_id=1))
        db.session.commit()
        data=self.photos(owned=0)
        self.assertEqual(len(data['items']),40)
        self.assertTrue(data['has_next'])
        self.assertEqual(len(data['options']['member']),60)

    def test_editor_and_trade_search_also_use_defined_member_order(self):
        contexts=[]
        def record(_sender,template,context,**extra): contexts.append(context)
        template_rendered.connect(record,self.app)
        try:
            for path in ('/trade/hinatazaka/new','/trade/hinatazaka'):
                self.assertEqual(self.client.get(path).status_code,200)
                self.assertEqual([m.id for m in contexts[-1]['members']],[10,11,2,1,12])
        finally:
            template_rendered.disconnect(record,self.app)


if __name__=='__main__': unittest.main()
