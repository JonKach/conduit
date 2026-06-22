"""shift to shortuuid for agent and thread
Revision ID: 90162e451b02
Revises: d619dfdc8e7e
Create Date: 2026-06-22 00:08:16.603407
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

revision = '90162e451b02'
down_revision = 'd619dfdc8e7e'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the FK constraint before altering types
    op.drop_constraint('thread_agent_id_fkey', 'thread', type_='foreignkey')

    op.alter_column('agent', 'id',
               existing_type=sa.UUID(),
               type_=sqlmodel.sql.sqltypes.AutoString(),
               existing_nullable=False,
               postgresql_using='id::text')

    op.alter_column('thread', 'id',
               existing_type=sa.UUID(),
               type_=sqlmodel.sql.sqltypes.AutoString(),
               existing_nullable=False,
               postgresql_using='id::text')

    op.alter_column('thread', 'agent_id',
               existing_type=sa.UUID(),
               type_=sqlmodel.sql.sqltypes.AutoString(),
               existing_nullable=False,
               postgresql_using='agent_id::text')

    # Recreate the FK now that both sides are VARCHAR
    op.create_foreign_key(
        'thread_agent_id_fkey',
        'thread', 'agent',
        ['agent_id'], ['id'],
        ondelete='CASCADE'
    )


def downgrade():
    op.drop_constraint('thread_agent_id_fkey', 'thread', type_='foreignkey')

    op.alter_column('thread', 'agent_id',
               existing_type=sqlmodel.sql.sqltypes.AutoString(),
               type_=sa.UUID(),
               existing_nullable=False,
               postgresql_using='agent_id::uuid')

    op.alter_column('thread', 'id',
               existing_type=sqlmodel.sql.sqltypes.AutoString(),
               type_=sa.UUID(),
               existing_nullable=False,
               postgresql_using='id::uuid')

    op.alter_column('agent', 'id',
               existing_type=sqlmodel.sql.sqltypes.AutoString(),
               type_=sa.UUID(),
               existing_nullable=False,
               postgresql_using='id::uuid')

    op.create_foreign_key(
        'thread_agent_id_fkey',
        'thread', 'agent',
        ['agent_id'], ['id'],
        ondelete='CASCADE'
    )