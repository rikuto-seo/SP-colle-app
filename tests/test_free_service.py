"""Free-service regression checks with memory-only data and mocked auth/storage."""
import ast
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SECRET_KEY', 'free-service-isolated-test')
from flask import abort, g, request
from PIL import Image
from extensions import db
from models import GROUP_KEYS, Group, User, UserPhoto, UserPhotoImage
from test_trade_marketplace import make_app, seed
from routes.auth import auth_bp
from routes.billing import billing_bp
from routes.core import core_bp
from routes.user import user_bp
from routes.stats import stats_bp
from routes.share import share_bp
from routes.admin_photos import admin_photos_bp


class FreeServiceTest(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        for blueprint in (auth_bp, billing_bp, core_bp, user_bp, stats_bp, share_bp, admin_photos_bp):
            self.app.register_blueprint(blueprint)
        self.app.add_url_rule('/lp', 'lp', lambda: 'landing')
        # Execute the actual production guard without importing credentials/app.py.
        module = ast.parse((ROOT/'app.py').read_text(encoding='utf-8'))
        guard = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name=='validate_group')
        guard.decorator_list=[]
        namespace=dict(request=request, abort=abort)
        exec(compile(ast.Module(body=[guard], type_ignores=[]), 'app.py:validate_group', 'exec'), namespace)
        self.app.before_request(namespace['validate_group'])
        self.ctx=self.app.app_context(); self.ctx.push()
        seed()
        db.session.add(Group(id=3,key='sakurazaka',name='櫻坂46')); db.session.commit()
        self.client=self.app.test_client()
        self.login(100)

    def tearDown(self):
        db.session.remove(); db.drop_all(); db.engine.dispose(); self.ctx.pop()

    def login(self, uid):
        g.pop('_login_user',None)
        with self.client.session_transaction() as session:
            session.clear()
            if uid is not None:
                session['_user_id']=str(uid);session['_fresh']=True

    def png(self):
        stream=io.BytesIO()
        Image.new('RGB',(32,48),'blue').save(stream,format='PNG')
        stream.seek(0)
        return stream

    def test_legacy_accounts_all_get_every_group_without_setup(self):
        for plan in ('free','lite','standard','premium'):
            with self.subTest(plan=plan):
                # Core UPDATE deliberately emulates unmigrated stored records.
                db.session.execute(db.text("UPDATE users SET plan_type=:plan, selected_groups='', primary_group=NULL WHERE id=100"),{'plan':plan})
                db.session.commit();db.session.expire_all();g.pop('_login_user',None)
                user=db.session.get(User,100)
                self.assertEqual(user.effective_plan_type,'free')
                self.assertEqual(user.get_selected_groups(),GROUP_KEYS)
                for key in GROUP_KEYS:
                    self.assertEqual(self.client.get('/index/'+key).status_code,200)
                    self.assertEqual(self.client.get('/get_owned_members?group='+key).status_code,200)
                    self.assertEqual(self.client.get('/trade/'+key+'/new').status_code,200)
                response=self.client.get('/')
                self.assertEqual(response.location,'/index/nogizaka')
                self.assertFalse(user.can_access_group('unknown'))

    def test_initial_registration_finishes_without_group_selection(self):
        self.login(None)
        token=dict(uid='new-free-user',email='new@example.invalid')
        headers={'Authorization':'Bearer fixture-token'}
        with patch('routes.auth.firebase_auth.verify_id_token',return_value=token):
            response=self.client.post('/api/me',headers=headers)
            self.assertFalse(response.json['is_setup_complete'])
            user=User.query.filter_by(firebase_uid=token['uid']).one()
            self.assertEqual(user.get_selected_groups(),GROUP_KEYS)
            self.assertEqual(self.client.get('/').location,'/first-register')
            response=self.client.post('/api/setup/username',headers=headers,json={'username':'無料ユーザー'})
            self.assertEqual(response.status_code,200)
            self.assertTrue(self.client.post('/api/me',headers=headers).json['is_setup_complete'])
            self.assertEqual(self.client.get('/').location,'/index/nogizaka')
            first_register=self.client.get('/first-register').get_data(as_text=True)
            self.assertNotIn('/select-group',first_register)

    def test_legacy_preference_and_group_switch_remain(self):
        db.session.execute(db.text("UPDATE users SET selected_groups='sakurazaka', primary_group=NULL WHERE id=100"))
        db.session.commit();db.session.expire_all()
        self.assertEqual(self.client.get('/').location,'/index/sakurazaka')
        for key in GROUP_KEYS:
            response=self.client.get('/switch/'+key)
            self.assertEqual(response.location,'/index/'+key)
            self.assertEqual(db.session.get(User,100).primary_group,key)
        self.assertEqual(self.client.get('/switch/unknown').status_code,404)
        self.assertEqual(self.client.get('/index/unknown').status_code,404)

    def test_billing_cannot_create_resume_or_restore_paid_contracts(self):
        user=db.session.get(User,100)
        original_plan=user.plan_type
        with patch('stripe.checkout.Session.create') as checkout, patch('stripe.Subscription.modify') as modify:
            for url in ('/api/create-checkout-session','/api/resume-subscription','/api/downgrade'):
                response=self.client.post(url,json={'plan':'premium'})
                self.assertEqual(response.status_code,410)
                self.assertEqual(response.json['error'],'billing_retired')
            self.assertEqual(self.client.post('/stripe/webhook',json={'type':'checkout.session.completed'}).status_code,410)
            checkout.assert_not_called();modify.assert_not_called()
        self.assertEqual(user.plan_type,original_plan)
        self.assertEqual(self.client.get('/api/check-plan?plan=premium').json,{'ready':True,'plan':'free'})
        self.assertEqual(self.client.post('/api/save-groups',json={'groups':['hinatazaka']}).json['groups'],GROUP_KEYS)
        for path in ('/upgrade','/payment-success'):
            self.assertEqual(self.client.get(path).location,'/mypage')
        for path in ('/select-group','/force-select-group'):
            self.assertEqual(self.client.get(path).location,'/')

    def test_free_account_uploads_beyond_former_storage_limits(self):
        owned=UserPhoto.query.filter_by(user_id=100,photo_id=1001).one()
        db.session.add(UserPhotoImage(user_id=100,user_photo_id=owned.id,image_key='old.webp',
            thumbnail_key='old-thumb.webp',file_size=15*1024**3,thumbnail_file_size=20))
        db.session.commit()
        user=db.session.get(User,100)
        self.assertIsNone(user.get_image_storage_limit_bytes())
        self.assertFalse(user.is_image_storage_full())
        with patch('routes.photo.upload_bytes') as upload:
            response=self.client.post(f'/upload_user_photo_image/hinatazaka/{owned.id}',data={'image':(self.png(),'image.png')})
            self.assertEqual(response.status_code,302)
            self.assertEqual(upload.call_count,2)
            self.assertEqual(UserPhotoImage.query.filter_by(user_id=100).count(),2)
            response=self.client.post('/add/hinatazaka',data={'member':'メンバーA','costume':'2026年 春の制服',
                'photo_type':'ヨリ','quantity':'500','image':(self.png(),'image.png')})
            self.assertEqual(response.status_code,302)
            self.assertEqual(owned.quantity,502)
            self.assertEqual(UserPhotoImage.query.filter_by(user_id=100).count(),3)

    def test_free_access_preserves_ownership_admin_and_csrf_checks(self):
        others=UserPhoto.query.filter_by(user_id=200,photo_id=1002).one()
        with patch('routes.photo.upload_bytes') as upload:
            response=self.client.post(f'/upload_user_photo_image/hinatazaka/{others.id}',data={'image':(self.png(),'image.png')})
            self.assertEqual(response.status_code,404);upload.assert_not_called()
        self.assertEqual(self.client.get('/admin/photos').status_code,403)
        self.app.config['WTF_CSRF_ENABLED']=True
        self.assertEqual(self.client.post('/toggle_share/hinatazaka').status_code,400)
        self.login(None)
        self.assertEqual(self.client.get('/terms').status_code,200)
        self.assertEqual(self.client.get('/privacy').status_code,200)
        self.assertEqual(self.client.get('/legal').status_code,200)

    def test_mypage_includes_all_group_sharing_without_billing(self):
        response=self.client.get('/mypage')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        for phrase in ('3グループを無料','画像保存容量の上限はありません','乃木坂46','櫻坂46','日向坂46'):
            self.assertIn(phrase,html)
        for phrase in ('プラン変更','次回未設定','有料プランで利用','画像保存容量の残りが少なく'):
            self.assertNotIn(phrase,html)
        for key in GROUP_KEYS:
            self.assertEqual(self.client.post('/toggle_share/'+key).status_code,302)


if __name__=='__main__':unittest.main()
