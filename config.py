# config.py
import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = 'koito-annbata'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_BINDS = {
        'photos': f'sqlite:///{os.path.join(basedir, "instance", "photos.db")}',
        'users': f'sqlite:///{os.path.join(basedir, "instance", "users.db")}'
    }
    SQLALCHEMY_DATABASE_URI = SQLALCHEMY_BINDS['users']
