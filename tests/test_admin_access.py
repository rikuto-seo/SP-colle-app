"""Admin authorization regressions with memory-only data and mocked Firebase.

Never imports app.py or connects to production services.
"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SECRET_KEY', 'admin-access-isolated-test')

from flask import g, jsonify
from flask_wtf.csrf import generate_csrf
from extensions import db
from models import User, Group, Member, Costume, Photo, PhotoType, CostumeTypeNormalization
from routes.admin_photos import admin_photos_bp
from routes.auth import auth_bp
from test_trade_marketplace import make_app, seed


class AdminAccessTest(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.app.register_blueprint(auth_bp)
        self.app.register_blueprint(admin_photos_bp)
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.app.add_url_rule('/test/csrf', 'test_csrf', lambda: jsonify(token=generate_csrf()))
        # A new admin endpoint with no per-view checks must inherit the guard.
        self.app.add_url_rule('/admin/photos/guard-regression', 'admin_photos.guard_regression',
                              lambda: 'admin-only', methods=['GET', 'POST'])
        self.ctx = self.app.app_context()
        self.ctx.push()
        seed()
        db.session.add(User(id=1, firebase_uid='owner-firebase-uid',
                            email='owner@example.invalid', username='Owner'))
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()

    def login(self, uid):
        g.pop('_login_user', None)
        g.pop('csrf_token', None)
        with self.client.session_transaction() as session:
            session.clear()
            if uid is not None:
                session['_user_id'] = str(uid)
                session['_fresh'] = True

    def csrf_headers(self):
        return {'X-CSRFToken': self.client.get('/test/csrf').json['token']}

    def snapshot(self):
        return {
            model.__tablename__: [
                tuple(getattr(row, column.name) for column in model.__table__.columns)
                for row in model.query.order_by(model.id).all()
            ]
            for model in (User, Group, Member, Costume, Photo, PhotoType, CostumeTypeNormalization)
        }

    def test_every_admin_route_rejects_guests_and_every_other_user(self):
        rules = [rule for rule in self.app.url_map.iter_rules()
                 if rule.endpoint.startswith('admin_photos.')]
        self.assertEqual(len(rules), 9)  # All eight production routes and the future-route probe.
        before = self.snapshot()
        for uid in (None, 100, 200, 300, 999999):
            self.login(uid)
            headers = self.csrf_headers()
            for rule in rules:
                path = str(rule).replace('<int:costume_id>', '1').replace('<int:photo_id>', '1004')
                for method in sorted(rule.methods):
                    with self.subTest(user=uid, path=path, method=method):
                        response = self.client.open(path, method=method, headers=headers)
                        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_request_fields_and_headers_cannot_claim_admin_id(self):
        self.login(100)
        headers = {**self.csrf_headers(), 'X-User-ID': '1', 'X-Admin': 'true',
                   'Authorization': 'Bearer owner-firebase-uid'}
        payload = dict(id=1, user_id=1, is_admin=True, firebase_uid='owner-firebase-uid', name='forged')
        before = self.snapshot()
        response = self.client.post('/admin/photos/create_type?user_id=1&is_admin=true',
                                    json=payload, headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_disabling_login_decorators_does_not_disable_admin_guard(self):
        self.app.config['LOGIN_DISABLED'] = True
        for uid in (None, 100):
            self.login(uid)
            self.assertEqual(self.client.get('/admin/photos').status_code, 403)
            self.assertEqual(self.client.get('/admin/photos/guard-regression').status_code, 403)

    def test_id_one_can_use_all_admin_pages_and_mutations(self):
        self.login(1)
        headers = self.csrf_headers()
        for path in ('/admin/photos', '/admin/photos/list?group_id=1',
                     '/admin/photos/type_normalizations/1', '/admin/photos/guard-regression'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        response = self.client.post('/admin/photos/create_costume',
            data={'name': 'Admin test costume', 'group_id': 1}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        response = self.client.post('/admin/photos/create_type', json={'name': 'Admin test cut'}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        response = self.client.post('/admin/photos/type_normalizations/1',
            json={'normalizations': {'1': 'ヨリ'}}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CostumeTypeNormalization.query.filter_by(costume_id=1, photo_type_id=1).one().normalized_type, 'ヨリ')
        response = self.client.post('/admin/photos/bulk_create',
            json={'costume_id': 1, 'member_ids': [1], 'type_ids': [2]}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['created'], 1)
        response = self.client.delete('/admin/photos/1004', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db.session.get(Photo, 1004))

    def test_admin_mutations_still_require_csrf(self):
        self.login(1)
        before = self.snapshot()
        self.assertEqual(self.client.post('/admin/photos/create_type', json={'name': 'No CSRF'}).status_code, 400)
        self.assertEqual(self.client.delete('/admin/photos/1004').status_code, 400)
        self.assertEqual(self.snapshot(), before)

    def test_menu_link_is_only_rendered_for_id_one(self):
        for uid in (None, 1, 100, 200, 300):
            self.login(uid)
            response = self.client.get('/trade/hinatazaka')
            self.assertEqual(response.status_code, 200)
            self.assertEqual('href="/admin/photos"' in response.get_data(as_text=True), uid == 1)

    def test_matching_email_never_rebinds_or_logs_into_admin_account(self):
        for path in ('/api/create-user', '/api/me'):
            for verified in (None, False, True):
                with self.subTest(path=path, email_verified=verified):
                    self.login(None)
                    token = dict(uid='different-firebase-uid', email='OWNER@example.invalid')
                    if verified is not None:
                        token['email_verified'] = verified
                    with patch('routes.auth.firebase_auth.verify_id_token', return_value=token):
                        response = self.client.post(path, headers={'Authorization': 'Bearer fixture-token'})
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(db.session.get(User, 1).firebase_uid, 'owner-firebase-uid')
                    self.assertIsNone(User.query.filter_by(firebase_uid=token['uid']).first())
                    with self.client.session_transaction() as session:
                        self.assertNotEqual(session.get('_user_id'), '1')
                    self.assertEqual(self.client.get('/admin/photos').status_code, 403)

    def test_existing_normal_login_cannot_be_promoted_by_claiming_owner_email(self):
        for path in ('/api/create-user', '/api/me'):
            self.login(100)
            with patch('routes.auth.firebase_auth.verify_id_token', return_value=dict(
                    uid='other-firebase-uid', email='owner@example.invalid', email_verified=True)):
                response = self.client.post(path, headers={'Authorization': 'Bearer fixture-token'})
            self.assertEqual(response.status_code, 401)
            with self.client.session_transaction() as session:
                self.assertEqual(session['_user_id'], '100')
            self.assertEqual(self.client.get('/admin/photos').status_code, 403)
            self.assertEqual(db.session.get(User, 1).firebase_uid, 'owner-firebase-uid')

    def test_original_owner_identity_can_still_log_in(self):
        self.login(None)
        with patch('routes.auth.firebase_auth.verify_id_token', return_value=dict(
                uid='owner-firebase-uid', email='owner@example.invalid', email_verified=True)):
            self.assertEqual(self.client.post('/api/create-user', headers={'Authorization': 'Bearer fixture-token'}).status_code, 200)
            response = self.client.post('/api/me', headers={'Authorization': 'Bearer fixture-token'})
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session['_user_id'], '1')
        self.assertEqual(self.client.get('/admin/photos').status_code, 200)

    def test_new_and_existing_normal_users_cannot_choose_id_one(self):
        for uid, email in [('fixture-100', 'private-100@example.invalid'),
                           ('new-regular-user', 'new-user@example.invalid')]:
            self.login(None)
            with patch('routes.auth.firebase_auth.verify_id_token', return_value=dict(uid=uid, email=email)):
                response = self.client.post('/api/me', headers={'Authorization': 'Bearer fixture-token'},
                    json={'id': 1, 'user_id': 1, 'is_admin': True})
            self.assertEqual(response.status_code, 200)
            with self.client.session_transaction() as session:
                self.assertNotEqual(session['_user_id'], '1')
            self.assertEqual(self.client.get('/admin/photos').status_code, 403)


if __name__ == '__main__':
    unittest.main()
