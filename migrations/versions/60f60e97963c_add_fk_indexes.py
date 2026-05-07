"""add fk indexes

Revision ID: 60f60e97963c
Revises: 453568b63f39
Create Date: 2026-05-07 06:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '60f60e97963c'
down_revision = '453568b63f39'
branch_labels = None
depends_on = None


def upgrade():
    # Add indexes that should have been created in initial migration
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_courier_id ON orders(courier_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_restaurant_id ON orders(restaurant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_status ON orders(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_created_at ON orders(created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_delivery_logs_order_id ON delivery_logs(order_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_delivery_logs_user_id ON delivery_logs(user_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_delivery_logs_user_id")
    op.execute("DROP INDEX IF EXISTS ix_delivery_logs_order_id")
    op.execute("DROP INDEX IF EXISTS ix_orders_created_at")
    op.execute("DROP INDEX IF EXISTS ix_orders_status")
    op.execute("DROP INDEX IF EXISTS ix_orders_restaurant_id")
    op.execute("DROP INDEX IF EXISTS ix_orders_courier_id")
