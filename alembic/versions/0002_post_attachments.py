"""add post attachments

Revision ID: 0002_post_attachments
Revises: 0001_init
Create Date: 2026-02-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_post_attachments"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("local_rel_path", sa.String(length=1024), nullable=True),
        sa.Column("is_image", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("post_id", "source_url", name="uq_post_attachments_post_source_url"),
    )
    op.create_index(op.f("ix_post_attachments_id"), "post_attachments", ["id"], unique=False)
    op.create_index("ix_post_attachments_post_id", "post_attachments", ["post_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_post_attachments_post_id", table_name="post_attachments")
    op.drop_index(op.f("ix_post_attachments_id"), table_name="post_attachments")
    op.drop_table("post_attachments")
