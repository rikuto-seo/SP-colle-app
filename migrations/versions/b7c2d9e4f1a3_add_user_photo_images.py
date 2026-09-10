from alembic import op
import sqlalchemy as sa


revision = 'b7c2d9e4f1a3'
down_revision = '8df413af40bd'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_photo_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('user_photo_id', sa.Integer(), nullable=False),
        sa.Column('image_key', sa.String(length=500), nullable=False),
        sa.Column('thumbnail_key', sa.String(length=500), nullable=False),
        sa.Column(
            'file_size',
            sa.BigInteger(),
            nullable=False,
            server_default='0',
        ),
        sa.Column(
            'thumbnail_file_size',
            sa.BigInteger(),
            nullable=False,
            server_default='0',
        ),
        sa.Column(
            'mime_type',
            sa.String(length=100),
            nullable=False,
            server_default='image/webp',
        ),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_photo_id'],
            ['user_photos.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('image_key'),
        sa.UniqueConstraint('thumbnail_key'),
        sa.CheckConstraint(
            'file_size >= 0',
            name='ck_user_photo_images_file_size_nonnegative',
        ),
        sa.CheckConstraint(
            'thumbnail_file_size >= 0',
            name='ck_user_photo_images_thumbnail_file_size_nonnegative',
        ),
    )

    op.create_index(
        'ix_user_photo_images_user_id',
        'user_photo_images',
        ['user_id'],
        unique=False,
    )

    op.create_index(
        'ix_user_photo_images_user_photo_id',
        'user_photo_images',
        ['user_photo_id'],
        unique=False,
    )

    op.create_index(
        'ix_user_photo_images_user_created',
        'user_photo_images',
        ['user_id', 'created_at'],
        unique=False,
    )

    op.create_index(
        'ix_user_photo_images_user_photo_created',
        'user_photo_images',
        ['user_photo_id', 'created_at'],
        unique=False,
    )


def downgrade():
    op.drop_index(
        'ix_user_photo_images_user_photo_created',
        table_name='user_photo_images',
    )
    op.drop_index(
        'ix_user_photo_images_user_created',
        table_name='user_photo_images',
    )
    op.drop_index(
        'ix_user_photo_images_user_photo_id',
        table_name='user_photo_images',
    )
    op.drop_index(
        'ix_user_photo_images_user_id',
        table_name='user_photo_images',
    )
    op.drop_table('user_photo_images')
