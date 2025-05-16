import os
from app import db, User, Photo
from sqlalchemy import create_engine

# 古いDBのエンジン作成
old_users_engine = create_engine('sqlite:///old_users.db')
old_photos_engine = create_engine('sqlite:///old_photos.db')

# 新しいDBの削除（再初期化）
if os.path.exists('instance/users.db'):
    os.remove('instance/users.db')

if os.path.exists('instance/photos.db'):
    os.remove('instance/photos.db')

# 新しいDBを作成
db.create_all()

# テーブルの移行関数（ID重複を避ける）
def migrate_table(old_table, new_model, engine):
    conn = engine.connect()
    results = conn.execute(old_table.select()).fetchall()
    for row in results:
        # IDがすでに存在しない場合のみ挿入
        existing = new_model.query.get(row['id'])
        if not existing:
            new_obj = new_model(**dict(row))
            db.session.add(new_obj)
    db.session.commit()

# 新しいデータベースに古いデータを移行
with db.app.app_context():
    migrate_table(User.__table__, User, old_users_engine)
    migrate_table(Photo.__table__, Photo, old_photos_engine)

print("データ移行が完了しました！")
