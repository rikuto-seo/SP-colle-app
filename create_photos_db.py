from app import app
from models import db, Photo

with app.app_context():
    # Flask-SQLAlchemy 3.2以降推奨のエンジン取得方法
    engine = db.engines['photos']
    Photo.__table__.create(bind=engine, checkfirst=True)
