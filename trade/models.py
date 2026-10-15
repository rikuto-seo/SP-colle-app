"""Explicit opt-in listings and private, stock-backed trade agreements."""
import uuid
from datetime import datetime
from extensions import db


class TradeListing(db.Model):
    __tablename__ = 'trade_listings'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    alias = db.Column(db.String(30), nullable=False)
    method = db.Column(db.String(12), nullable=False, default='either')
    location = db.Column(db.String(100), nullable=False, default='')
    notes = db.Column(db.String(1000), nullable=False, default='')
    bundle = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(12), nullable=False, default='draft', index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    group = db.relationship('Group')
    offers = db.relationship('TradeOffer', cascade='all, delete-orphan', order_by='TradeOffer.id')
    __table_args__ = (db.CheckConstraint("status IN ('draft','open','paused','closed')", name='trade_listing_status'),
                      db.CheckConstraint("method IN ('mail','meet','either')", name='trade_listing_method'))


class TradeOffer(db.Model):
    __tablename__ = 'trade_offers'
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('trade_listings.id', ondelete='CASCADE'), nullable=False, index=True)
    photo_id = db.Column(db.Integer, db.ForeignKey('photos.id'), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    want_mode = db.Column(db.String(8), nullable=False, default='any')
    image_id = db.Column(db.Integer, db.ForeignKey('user_photo_images.id', ondelete='SET NULL'))
    photo = db.relationship('Photo')
    image = db.relationship('UserPhotoImage')
    wants = db.relationship('TradeWant', cascade='all, delete-orphan', order_by='TradeWant.id')
    __table_args__ = (db.UniqueConstraint('listing_id', 'photo_id'),
                      db.CheckConstraint('quantity >= 0', name='trade_offer_quantity'),
                      db.CheckConstraint("want_mode IN ('any','all')", name='trade_offer_want_mode'))


class TradeWant(db.Model):
    __tablename__ = 'trade_wants'
    id = db.Column(db.Integer, primary_key=True)
    offer_id = db.Column(db.Integer, db.ForeignKey('trade_offers.id', ondelete='CASCADE'), nullable=False, index=True)
    photo_id = db.Column(db.Integer, db.ForeignKey('photos.id'), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    priority = db.Column(db.String(12), nullable=False, default='normal')
    photo = db.relationship('Photo')
    __table_args__ = (db.UniqueConstraint('offer_id', 'photo_id'),
                      db.CheckConstraint('quantity > 0', name='trade_want_quantity'),
                      db.CheckConstraint("priority IN ('high','normal','low')", name='trade_want_priority'))


class TradeProposal(db.Model):
    __tablename__ = 'trade_proposals'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    listing_id = db.Column(db.Integer, db.ForeignKey('trade_listings.id', ondelete='CASCADE'), nullable=False, index=True)
    applicant_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    alias = db.Column(db.String(30), nullable=False)
    method = db.Column(db.String(12), nullable=False)
    status = db.Column(db.String(12), nullable=False, default='pending', index=True)
    owner_sent_at = db.Column(db.DateTime)
    applicant_sent_at = db.Column(db.DateTime)
    owner_received_at = db.Column(db.DateTime)
    applicant_received_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    listing = db.relationship('TradeListing')
    items = db.relationship('TradeProposalItem', cascade='all, delete-orphan', order_by='TradeProposalItem.id')
    messages = db.relationship('TradeMessage', cascade='all, delete-orphan', order_by='TradeMessage.id')
    __table_args__ = (db.CheckConstraint("status IN ('pending','accepted','rejected','cancelled','completed')", name='trade_proposal_status'),
                      db.CheckConstraint("method IN ('mail','meet')", name='trade_proposal_method'))


class TradeProposalItem(db.Model):
    __tablename__ = 'trade_proposal_items'
    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey('trade_proposals.id', ondelete='CASCADE'), nullable=False, index=True)
    photo_id = db.Column(db.Integer, db.ForeignKey('photos.id'), nullable=False)
    side = db.Column(db.String(12), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    image_id = db.Column(db.Integer, db.ForeignKey('user_photo_images.id', ondelete='SET NULL'))
    photo = db.relationship('Photo')
    image = db.relationship('UserPhotoImage')
    __table_args__ = (db.UniqueConstraint('proposal_id', 'side', 'photo_id'),
                      db.CheckConstraint('quantity > 0', name='trade_proposal_item_quantity'),
                      db.CheckConstraint("side IN ('owner','applicant')", name='trade_proposal_item_side'))


class TradeMessage(db.Model):
    __tablename__ = 'trade_messages'
    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey('trade_proposals.id', ondelete='CASCADE'), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    body = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
