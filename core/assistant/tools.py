import re
from decimal import Decimal
from django.db.models import Q
from core.models import Product, Inventory
from core.services import create_draft_order as create_order_service


def search_parts(query: str, vehicle: str = None, category: str = None) -> list[dict]:
    """
    Search the PostgreSQL product catalogue using keyword matching and vehicle fitment.
    Returns matching products with live price and stock.
    """
    qs = Product.objects.select_related("inventory").all()

    if vehicle:
        v_clean = vehicle.strip()
        qs = qs.filter(Q(vehicle_fitment__icontains=v_clean) | Q(vehicle_fitment__iexact="Universal"))

    if category:
        qs = qs.filter(category__icontains=category.strip())

    if query:
        # Tokenize query for flexible lexical matching
        tokens = [t for t in re.split(r"\s+", query.strip()) if len(t) > 1]
        if tokens:
            q_filter = Q()
            for token in tokens:
                q_filter |= (
                    Q(sku__icontains=token)
                    | Q(name__icontains=token)
                    | Q(category__icontains=token)
                    | Q(brand__icontains=token)
                    | Q(vehicle_fitment__icontains=token)
                    | Q(description__icontains=token)
                )
            qs = qs.filter(q_filter)

    results = []
    # Limit results to top 10 relevant items
    for p in qs[:10]:
        stock_qty = p.inventory.quantity if hasattr(p, "inventory") else 0
        results.append({
            "sku": p.sku,
            "name": p.name,
            "category": p.category,
            "brand": p.brand,
            "vehicle_fitment": p.vehicle_fitment,
            "price": f"{p.price:.2f}",
            "stock": stock_qty,
        })
    return results


def check_stock(sku: str) -> dict:
    """
    Fetch live stock and current price for a specific product SKU.
    """
    if not sku:
        return {"error": "SKU parameter is required"}

    sku_clean = sku.strip()
    try:
        p = Product.objects.select_related("inventory").get(sku__iexact=sku_clean)
        stock_qty = p.inventory.quantity if hasattr(p, "inventory") else 0
        return {
            "sku": p.sku,
            "name": p.name,
            "price": f"{p.price:.2f}",
            "stock": stock_qty,
            "in_stock": stock_qty > 0,
        }
    except Product.DoesNotExist:
        return {"sku": sku_clean, "error": f"Product with SKU '{sku_clean}' not found in catalogue"}


def create_draft_order(dealer_id: int, items: list[dict]) -> tuple[dict, dict | None]:
    """
    Create a DRAFT order for dealer_id with given items.
    Returns (result_dict, action_dict).
    """
    if not dealer_id:
        return {"error": "dealer_id is required"}, None

    if not items or not isinstance(items, list):
        return {"error": "items list is required and must not be empty"}, None

    try:
        order, created = create_order_service(dealer_id=dealer_id, items_data=items)
        action = {
            "type": "draft_order_created",
            "order_number": order.order_number,
        }
        result = {
            "order_number": order.order_number,
            "status": order.status,
            "subtotal": f"{order.subtotal:.2f}",
            "tax_total": f"{order.tax_total:.2f}",
            "grand_total": f"{order.grand_total:.2f}",
            "items_count": len(items),
            "message": f"DRAFT order {order.order_number} created successfully.",
        }
        return result, action
    except Exception as e:
        return {"error": str(e)}, None
