import os
import time
from sqlalchemy import create_engine
from app import app, db, User, Photo  # appを明示的にimport

# ファイル削除前にロックが解除されるのを待つ関数
def wait_until_unlocked(path, timeout=10):
    for _ in range(timeout):
        try:
            os.remove(path)
            print(f"🗑️ {path} を削除しました。")
            return
        except PermissionError:
            print(f"⏳ {path} が使用中です。再試行します...")
            time.sleep(1)
    raise RuntimeError(f"❌ {path} を削除できませんでした。使用中の可能性があります。")

# 古いDBのエンジン作成
old_users_engine = create_engine('sqlite:///old_users.db')
old_photos_engine = create_engine('sqlite:///old_photos.db')

# 新しいDBの削除（再初期化）
if os.path.exists('instance/users.db'):
    wait_until_unlocked('instance/users.db')

if os.path.exists('instance/photos.db'):
    wait_until_unlocked('instance/photos.db')

# テーブルの移行関数（ID重複を避ける）
def migrate_table(old_table, new_model, engine):
    conn = engine.connect()
    results = conn.execute(old_table.select()).fetchall()
    for row in results:
        existing = new_model.query.get(row['id'])
        if not existing:
            new_obj = new_model(**dict(row))
            db.session.add(new_obj)
    db.session.commit()
    print(f"✅ {new_model.__name__} テーブルを移行しました。（{len(results)}件）")

# アプリケーションコンテキスト内で新DBを作成しデータを移行
with app.app_context():
    db.create_all()
    migrate_table(User.__table__, User, old_users_engine)
    migrate_table(Photo.__table__, Photo, old_photos_engine)

print("🎉 データ移行が完了しました！")
