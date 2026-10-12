import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
import pytz
from django.db import transaction
from django.db.models import F
from django.conf import settings
from django.utils import timezone

from .models import (
    Product,
    Inventory,
    Dealer,
    Order,
    OrderItem,
    DailyOrderSequence,
)
from .exceptions import (
    ValidationErrorAPIError,
    NotFoundAPIError,
    InsufficientStockAPIError,
    InvalidTransitionAPIError,
    OrderLockedAPIError,
    IdempotencyConflictAPIError,
)

GST_RATE = Decimal("0.18")
CENT = Decimal("0.01")


def round_money(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(amount: Decimal) -> str:
    return f"{round_money(amount):.2f}"


def generate_next_order_number() -> str:
    """
    Generate order number in format ORD-YYYYMMDD-NNNN using Asia/Kolkata date.
    Atomic increment via DailyOrderSequence to guarantee uniqueness under concurrency.
    """
    kolkata_tz = pytz.timezone("Asia/Kolkata")
    now_kolkata = timezone.now().astimezone(kolkata_tz)
    date_str = now_kolkata.strftime("%Y%m%d")

    with transaction.atomic():
        seq_obj, _ = DailyOrderSequence.objects.select_for_update().get_or_create(
            date_str=date_str,
            defaults={"last_seq": 0}
        )
        seq_obj.last_seq += 1
        seq_obj.save(update_fields=["last_seq"])
        seq_num = seq_obj.last_seq

    return f"ORD-{date_str}-{seq_num:04d}"


def calculate_line_item(unit_price: Decimal, quantity: int) -> dict:
    """
    line_subtotal = unit_price * quantity
    line_tax = line_subtotal * 0.18, rounded to 2 decimals using ROUND_HALF_UP (per line)
    line_total = line_subtotal + line_tax
    """
    line_subtotal = round_money(unit_price * quantity)
    line_tax = round_money(line_subtotal * GST_RATE)
    line_total = line_subtotal + line_tax
    return {
        "unit_price": unit_price,
        "quantity": quantity,
        "line_subtotal": line_subtotal,
        "line_tax": line_tax,
        "line_total": line_total,
    }


def validate_order_items(items_data: list) -> list:
    if not items_data or not isinstance(items_data, list):
        raise ValidationErrorAPIError("Order must contain at least one item.", details=["items list is required and cannot be empty."])

    seen_skus = set()
    validated = []
    for idx, item in enumerate(items_data):
        if not isinstance(item, dict):
            raise ValidationErrorAPIError("Each item must be a JSON object.")
        sku = item.get("sku")
        qty = item.get("quantity")
        if not sku or not isinstance(sku, str):
            raise ValidationErrorAPIError(f"Item #{idx+1} is missing a valid 'sku'.")
        if qty is None or not isinstance(qty, int) or qty < 1:
            raise ValidationErrorAPIError(f"Item #{idx+1} ('{sku}') quantity must be an integer >= 1.")
        if sku in seen_skus:
            raise ValidationErrorAPIError(f"Duplicate SKU '{sku}' found in order items. A SKU may only appear once.")
        seen_skus.add(sku)
        validated.append({"sku": sku, "quantity": qty})

    return validated


def create_draft_order(dealer_id: int, items_data: list, idempotency_key: str = None, request_body_raw: bytes = None) -> tuple[Order, bool]:
    """
    Creates a DRAFT order.
    Returns (order, created_boolean).
    Handles Idempotency-Key if provided.
    """
    # 1. Check idempotency if key provided
    req_hash = None
    if idempotency_key:
        req_hash = hashlib.sha256(request_body_raw or b"").hexdigest()
        existing = Order.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if existing.idempotency_request_hash == req_hash:
                return existing, False
            else:
                raise IdempotencyConflictAPIError("Same Idempotency-Key reused with a different request body.")

    # 2. Validate dealer
    try:
        dealer = Dealer.objects.get(id=dealer_id)
    except Dealer.DoesNotExist:
        raise ValidationErrorAPIError(f"Dealer with id {dealer_id} does not exist.")

    # 3. Validate items
    validated_items = validate_order_items(items_data)

    # 4. Fetch products
    skus = [it["sku"] for it in validated_items]
    products_by_sku = {p.sku: p for p in Product.objects.filter(sku__in=skus)}
    for it in validated_items:
        if it["sku"] not in products_by_sku:
            raise ValidationErrorAPIError(f"Unknown SKU: '{it['sku']}'. Product does not exist.")

    with transaction.atomic():
        order_number = generate_next_order_number()

        subtotal = Decimal("0.00")
        tax_total = Decimal("0.00")
        grand_total = Decimal("0.00")

        order = Order(
            order_number=order_number,
            dealer=dealer,
            status=Order.STATUS_DRAFT,
            subtotal=Decimal("0.00"),
            tax_total=Decimal("0.00"),
            grand_total=Decimal("0.00"),
            idempotency_key=idempotency_key,
            idempotency_request_hash=req_hash,
        )
        order.save()

        order_items = []
        for it in validated_items:
            product = products_by_sku[it["sku"]]
            calc = calculate_line_item(product.price, it["quantity"])
            subtotal += calc["line_subtotal"]
            tax_total += calc["line_tax"]
            grand_total += calc["line_total"]

            order_items.append(
                OrderItem(
                    order=order,
                    product=product,
                    sku=product.sku,
                    name=product.name,
                    quantity=it["quantity"],
                    unit_price=calc["unit_price"],
                    line_subtotal=calc["line_subtotal"],
                    line_tax=calc["line_tax"],
                    line_total=calc["line_total"],
                )
            )

        OrderItem.objects.bulk_create(order_items)

        order.subtotal = subtotal
        order.tax_total = tax_total
        order.grand_total = grand_total
        order.save(update_fields=["subtotal", "tax_total", "grand_total"])

    return order, True


def update_draft_order_items(order: Order, items_data: list) -> Order:
    """
    PUT /api/orders/{order_number}/ replaces all items.
    Only permitted while order is DRAFT.
    """
    if order.status != Order.STATUS_DRAFT:
        raise OrderLockedAPIError(f"Order {order.order_number} is in status '{order.status}'. Only DRAFT orders can be edited.")

    validated_items = validate_order_items(items_data)
    skus = [it["sku"] for it in validated_items]
    products_by_sku = {p.sku: p for p in Product.objects.filter(sku__in=skus)}
    for it in validated_items:
        if it["sku"] not in products_by_sku:
            raise ValidationErrorAPIError(f"Unknown SKU: '{it['sku']}'. Product does not exist.")

    with transaction.atomic():
        order.items.all().delete()

        subtotal = Decimal("0.00")
        tax_total = Decimal("0.00")
        grand_total = Decimal("0.00")

        order_items = []
        for it in validated_items:
            product = products_by_sku[it["sku"]]
            calc = calculate_line_item(product.price, it["quantity"])
            subtotal += calc["line_subtotal"]
            tax_total += calc["line_tax"]
            grand_total += calc["line_total"]

            order_items.append(
                OrderItem(
                    order=order,
                    product=product,
                    sku=product.sku,
                    name=product.name,
                    quantity=it["quantity"],
                    unit_price=calc["unit_price"],
                    line_subtotal=calc["line_subtotal"],
                    line_tax=calc["line_tax"],
                    line_total=calc["line_total"],
                )
            )

        OrderItem.objects.bulk_create(order_items)

        order.subtotal = subtotal
        order.tax_total = tax_total
        order.grand_total = grand_total
        order.save(update_fields=["subtotal", "tax_total", "grand_total", "updated_at"])

    return order


def confirm_order(order: Order) -> Order:
    """
    Transitions DRAFT -> CONFIRMED.
    All-or-nothing stock deduction with row-level locks on Inventory.
    Locks unit_price at current value.
    """
    if order.status != Order.STATUS_DRAFT:
        raise InvalidTransitionAPIError(f"Cannot confirm order in status '{order.status}'. Only DRAFT orders can be confirmed.")

    with transaction.atomic():
        # Lock inventory rows for all SKUs in the order, ordered by SKU to avoid deadlocks
        items = list(order.items.select_related("product").all())
        if not items:
            raise ValidationErrorAPIError("Cannot confirm an order with no items.")

        skus = sorted([item.sku for item in items])
        inventories = {
            inv.product_id: inv
            for inv in Inventory.objects.select_for_update().filter(product_id__in=skus)
        }

        short_lines = []
        for item in items:
            inv = inventories.get(item.sku)
            available = inv.quantity if inv else 0
            if available < item.quantity:
                short_lines.append({
                    "sku": item.sku,
                    "name": item.name,
                    "requested": item.quantity,
                    "available": available,
                })

        if short_lines:
            # Build contract error format
            # message: "Insufficient stock for <product name>. Available: X, Requested: Y"
            msgs = [
                f"Insufficient stock for {sl['name']}. Available: {sl['available']}, Requested: {sl['requested']}"
                for sl in short_lines
            ]
            details = [
                {"sku": sl["sku"], "requested": sl["requested"], "available": sl["available"]}
                for sl in short_lines
            ]
            raise InsufficientStockAPIError(message="; ".join(msgs), details=details)

        # Deduct stock
        for item in items:
            inv = inventories[item.sku]
            inv.quantity -= item.quantity
            inv.save(update_fields=["quantity", "updated_at"])

        order.status = Order.STATUS_CONFIRMED
        order.save(update_fields=["status", "updated_at"])

    return order


def cancel_order(order: Order) -> Order:
    """
    DRAFT -> CANCELLED (no stock change)
    CONFIRMED -> CANCELLED (restores stock exactly once)
    DISPATCHED or DELIVERED -> 409 INVALID_TRANSITION
    """
    if order.status in (Order.STATUS_DISPATCHED, Order.STATUS_DELIVERED, Order.STATUS_CANCELLED):
        raise InvalidTransitionAPIError(f"Cannot cancel order in status '{order.status}'.")

    with transaction.atomic():
        if order.status == Order.STATUS_CONFIRMED:
            items = list(order.items.select_related("product").all())
            skus = sorted([item.sku for item in items])
            inventories = {
                inv.product_id: inv
                for inv in Inventory.objects.select_for_update().filter(product_id__in=skus)
            }
            for item in items:
                inv = inventories.get(item.sku)
                if inv:
                    inv.quantity += item.quantity
                    inv.save(update_fields=["quantity", "updated_at"])

        order.status = Order.STATUS_CANCELLED
        order.save(update_fields=["status", "updated_at"])

    return order


def dispatch_order(order: Order) -> Order:
    """CONFIRMED -> DISPATCHED"""
    if order.status != Order.STATUS_CONFIRMED:
        raise InvalidTransitionAPIError(f"Cannot dispatch order in status '{order.status}'. Only CONFIRMED orders can be dispatched.")

    order.status = Order.STATUS_DISPATCHED
    order.save(update_fields=["status", "updated_at"])
    return order


def deliver_order(order: Order) -> Order:
    """DISPATCHED -> DELIVERED"""
    if order.status != Order.STATUS_DISPATCHED:
        raise InvalidTransitionAPIError(f"Cannot deliver order in status '{order.status}'. Only DISPATCHED orders can be delivered.")

    order.status = Order.STATUS_DELIVERED
    order.save(update_fields=["status", "updated_at"])
    return order
