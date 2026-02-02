#sakamichi_photo_app\want\__init__.py
from flask import Blueprint

want_bp = Blueprint(
    'want',
    __name__,
    url_prefix='/want'
)

from . import routes
