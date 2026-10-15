"""Add opt-in trade listings and private agreements. No existing data is published."""
from alembic import op
import sqlalchemy as sa

revision = "d8f1c3a6e902"
down_revision = "c4e8a7b91d26"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('want_shares', sa.Column('want_public', sa.Boolean(), nullable=False, server_default=sa.false()))
    # Preserve existing wish-list visibility, then allow independent toggles.
    op.execute('UPDATE want_shares SET want_public = is_public')
    op.create_table('want_members',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('member_id', sa.Integer(), sa.ForeignKey('members.id'), nullable=False),
        sa.UniqueConstraint('user_id', 'member_id'))
    op.create_table('trade_listings',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('public_id', sa.String(length=36), nullable=False, unique=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id'), nullable=False),
        sa.Column('alias', sa.String(length=30), nullable=False),
        sa.Column('method', sa.String(length=12), nullable=False),
        sa.Column('location', sa.String(length=100), nullable=False),
        sa.Column('notes', sa.String(length=1000), nullable=False),
        sa.Column('bundle', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('draft','open','paused','closed')", name='trade_listing_status'),
        sa.CheckConstraint("method IN ('mail','meet','either')", name='trade_listing_method'),
    )
    op.create_index('ix_trade_listings_status', 'trade_listings', ['status'])
    op.create_index('ix_trade_listings_user_id', 'trade_listings', ['user_id'])
    op.create_table('trade_offers',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('listing_id', sa.Integer(), sa.ForeignKey('trade_listings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('photo_id', sa.Integer(), sa.ForeignKey('photos.id'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('want_mode', sa.String(length=8), nullable=False),
        sa.Column('image_id', sa.Integer(), sa.ForeignKey('user_photo_images.id', ondelete='SET NULL'), nullable=True),
        sa.CheckConstraint('quantity >= 0', name='trade_offer_quantity'),
        sa.CheckConstraint("want_mode IN ('any','all')", name='trade_offer_want_mode'),
        sa.UniqueConstraint('listing_id', 'photo_id'),
    )
    op.create_index('ix_trade_offers_listing_id', 'trade_offers', ['listing_id'])
    op.create_index('ix_trade_offers_photo_id', 'trade_offers', ['photo_id'])
    op.create_table('trade_wants',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('offer_id', sa.Integer(), sa.ForeignKey('trade_offers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('photo_id', sa.Integer(), sa.ForeignKey('photos.id'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('priority', sa.String(length=12), nullable=False),
        sa.CheckConstraint('quantity > 0', name='trade_want_quantity'),
        sa.CheckConstraint("priority IN ('high','normal','low')", name='trade_want_priority'),
        sa.UniqueConstraint('offer_id', 'photo_id'),
    )
    op.create_index('ix_trade_wants_offer_id', 'trade_wants', ['offer_id'])
    op.create_index('ix_trade_wants_photo_id', 'trade_wants', ['photo_id'])
    op.create_table('trade_proposals',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('public_id', sa.String(length=36), nullable=False, unique=True),
        sa.Column('listing_id', sa.Integer(), sa.ForeignKey('trade_listings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('applicant_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('alias', sa.String(length=30), nullable=False),
        sa.Column('method', sa.String(length=12), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('owner_sent_at', sa.DateTime(), nullable=True),
        sa.Column('applicant_sent_at', sa.DateTime(), nullable=True),
        sa.Column('owner_received_at', sa.DateTime(), nullable=True),
        sa.Column('applicant_received_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('pending','accepted','rejected','cancelled','completed')", name='trade_proposal_status'),
        sa.CheckConstraint("method IN ('mail','meet')", name='trade_proposal_method'),
    )
    op.create_index('ix_trade_proposals_applicant_id', 'trade_proposals', ['applicant_id'])
    op.create_index('ix_trade_proposals_listing_id', 'trade_proposals', ['listing_id'])
    op.create_index('ix_trade_proposals_status', 'trade_proposals', ['status'])
    op.create_table('trade_proposal_items',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('proposal_id', sa.Integer(), sa.ForeignKey('trade_proposals.id', ondelete='CASCADE'), nullable=False),
        sa.Column('photo_id', sa.Integer(), sa.ForeignKey('photos.id'), nullable=False),
        sa.Column('side', sa.String(length=12), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('image_id', sa.Integer(), sa.ForeignKey('user_photo_images.id', ondelete='SET NULL')),
        sa.CheckConstraint('quantity > 0', name='trade_proposal_item_quantity'),
        sa.CheckConstraint("side IN ('owner','applicant')", name='trade_proposal_item_side'),
        sa.UniqueConstraint('proposal_id', 'side', 'photo_id'),
    )
    op.create_index('ix_trade_proposal_items_proposal_id', 'trade_proposal_items', ['proposal_id'])
    op.create_table('trade_messages',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('proposal_id', sa.Integer(), sa.ForeignKey('trade_proposals.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sender_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('body', sa.String(length=2000), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_trade_messages_proposal_id', 'trade_messages', ['proposal_id'])


def downgrade():
    op.drop_table('want_members')
    with op.batch_alter_table('want_shares') as batch:
        batch.drop_column('want_public')
    op.drop_table('trade_messages')
    op.drop_table('trade_proposal_items')
    op.drop_table('trade_proposals')
    op.drop_table('trade_wants')
    op.drop_table('trade_offers')
    op.drop_table('trade_listings')
