# src/orders/handlers.py (relevant excerpt)
# Route registered at GET /orders in src/orders/__init__.py.

from flask import jsonify, request
from src.db.session import get_session
from src.orders.models import Order
from src.customers.models import Customer
from src.orders.serializers import order_to_dict


def load_customer_inline(session, customer_id: int) -> Customer:
    # NOTE: this is the hydration path - one round trip per call.
    return session.query(Customer).filter(Customer.id == customer_id).one()


def list_orders():
    session = get_session()
    limit = int(request.args.get("limit", 50))

    orders = (
        session.query(Order)
        .order_by(Order.created_at.desc())
        .limit(limit)
        .all()
    )

    out = []
    for order in orders:
        customer = load_customer_inline(session, order.customer_id)
        out.append(order_to_dict(order, customer))

    return jsonify(out)
