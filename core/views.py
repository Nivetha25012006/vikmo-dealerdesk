import json
from django.db.models import Q
from django.http import JsonResponse
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Product, Inventory, Dealer, Order
from .serializers import (
    ProductSerializer,
    ProductCreateSerializer,
    ProductUpdateSerializer,
    DealerSerializer,
    DealerCreateSerializer,
    OrderSerializer,
)
from .pagination import StandardResultsSetPagination
from .exceptions import (
    NotFoundAPIError,
    ValidationErrorAPIError,
    DuplicateAPIError,
)
from .services import (
    create_draft_order,
    update_draft_order_items,
    confirm_order,
    cancel_order,
    dispatch_order,
    deliver_order,
)


def health(request):
    """GET /api/health/ — the grader polls this until your app is ready."""
    return JsonResponse({"status": "ok"})


class ProductListView(APIView):
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        qs = Product.objects.select_related("inventory").all().order_by("sku")

        search = request.query_params.get("search")
        if search:
            search = search.strip()
            qs = qs.filter(
                Q(sku__icontains=search)
                | Q(name__icontains=search)
                | Q(brand__icontains=search)
            )

        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category.strip())

        vehicle = request.query_params.get("vehicle")
        if vehicle:
            qs = qs.filter(vehicle_fitment__icontains=vehicle.strip())

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        serializer = ProductSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = ProductCreateSerializer(data=request.data)
        if not serializer.is_valid():
            err_dict = serializer.errors
            details = [f"{k}: {v}" for k, v in err_dict.items()]
            raise ValidationErrorAPIError("; ".join(details), details=details)

        product = serializer.save()
        Inventory.objects.get_or_create(product=product, defaults={"quantity": 0})
        return Response(ProductSerializer(product).data, status=status.HTTP_201_CREATED)


class ProductDetailView(APIView):
    def get_object(self, sku):
        try:
            return Product.objects.select_related("inventory").get(sku=sku)
        except Product.DoesNotExist:
            raise NotFoundAPIError(f"Product with SKU '{sku}' not found.")

    def get(self, request, sku):
        product = self.get_object(sku)
        return Response(ProductSerializer(product).data, status=status.HTTP_200_OK)

    def patch(self, request, sku):
        product = self.get_object(sku)
        if "sku" in request.data and request.data["sku"] != product.sku:
            raise ValidationErrorAPIError("Product SKU cannot be changed.")

        serializer = ProductUpdateSerializer(product, data=request.data, partial=True)
        if not serializer.is_valid():
            err_dict = serializer.errors
            details = [f"{k}: {v}" for k, v in err_dict.items()]
            raise ValidationErrorAPIError("; ".join(details), details=details)

        updated_product = serializer.save()
        return Response(ProductSerializer(updated_product).data, status=status.HTTP_200_OK)


class InventoryUpdateView(APIView):
    def put(self, request, sku):
        try:
            product = Product.objects.get(sku=sku)
        except Product.DoesNotExist:
            raise NotFoundAPIError(f"Product with SKU '{sku}' not found.")

        qty = request.data.get("quantity")
        if qty is None or not isinstance(qty, int) or qty < 0:
            raise ValidationErrorAPIError("Inventory 'quantity' must be an integer >= 0.")

        inv, _ = Inventory.objects.get_or_create(product=product, defaults={"quantity": 0})
        inv.quantity = qty
        inv.save(update_fields=["quantity", "updated_at"])

        return Response({"sku": product.sku, "quantity": inv.quantity}, status=status.HTTP_200_OK)


class DealerListView(APIView):
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        qs = Dealer.objects.all().order_by("id")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        serializer = DealerSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = DealerCreateSerializer(data=request.data)
        if not serializer.is_valid():
            err_dict = serializer.errors
            details = [f"{k}: {v}" for k, v in err_dict.items()]
            raise ValidationErrorAPIError("; ".join(details), details=details)

        dealer = serializer.save()
        return Response(DealerSerializer(dealer).data, status=status.HTTP_201_CREATED)


class DealerDetailView(APIView):
    def get(self, request, pk):
        try:
            dealer = Dealer.objects.get(id=pk)
        except Dealer.DoesNotExist:
            raise NotFoundAPIError(f"Dealer with id {pk} not found.")
        return Response(DealerSerializer(dealer).data, status=status.HTTP_200_OK)


class OrderListView(APIView):
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        qs = Order.objects.prefetch_related("items", "items__product").select_related("dealer").all().order_by("-created_at", "-id")

        dealer_id = request.query_params.get("dealer_id")
        if dealer_id:
            try:
                qs = qs.filter(dealer_id=int(dealer_id))
            except ValueError:
                raise ValidationErrorAPIError("dealer_id query param must be an integer.")

        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param.strip().upper())

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        serializer = OrderSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        data = request.data
        if not isinstance(data, dict):
            raise ValidationErrorAPIError("Request body must be a JSON object.")

        dealer_id = data.get("dealer_id")
        if dealer_id is None:
            raise ValidationErrorAPIError("'dealer_id' is required.")

        items = data.get("items")
        if items is None:
            raise ValidationErrorAPIError("'items' list is required.")

        idempotency_key = request.headers.get("Idempotency-Key") or request.META.get("HTTP_IDEMPOTENCY_KEY")

        order, created = create_draft_order(
            dealer_id=dealer_id,
            items_data=items,
            idempotency_key=idempotency_key,
            request_body_raw=request.body,
        )

        resp_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(OrderSerializer(order).data, status=resp_status)


class OrderDetailView(APIView):
    def get_object(self, order_number):
        try:
            return Order.objects.prefetch_related("items", "items__product").select_related("dealer").get(order_number=order_number)
        except Order.DoesNotExist:
            raise NotFoundAPIError(f"Order '{order_number}' not found.")

    def get(self, request, order_number):
        order = self.get_object(order_number)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)

    def put(self, request, order_number):
        order = self.get_object(order_number)
        items = request.data.get("items")
        if items is None:
            raise ValidationErrorAPIError("'items' is required in request body.")

        updated_order = update_draft_order_items(order, items)
        return Response(OrderSerializer(updated_order).data, status=status.HTTP_200_OK)


class OrderConfirmView(APIView):
    def post(self, request, order_number):
        try:
            order = Order.objects.prefetch_related("items", "items__product").select_related("dealer").get(order_number=order_number)
        except Order.DoesNotExist:
            raise NotFoundAPIError(f"Order '{order_number}' not found.")

        confirmed = confirm_order(order)
        return Response(OrderSerializer(confirmed).data, status=status.HTTP_200_OK)


class OrderDispatchView(APIView):
    def post(self, request, order_number):
        try:
            order = Order.objects.prefetch_related("items", "items__product").select_related("dealer").get(order_number=order_number)
        except Order.DoesNotExist:
            raise NotFoundAPIError(f"Order '{order_number}' not found.")

        dispatched = dispatch_order(order)
        return Response(OrderSerializer(dispatched).data, status=status.HTTP_200_OK)


class OrderDeliverView(APIView):
    def post(self, request, order_number):
        try:
            order = Order.objects.prefetch_related("items", "items__product").select_related("dealer").get(order_number=order_number)
        except Order.DoesNotExist:
            raise NotFoundAPIError(f"Order '{order_number}' not found.")

        delivered = deliver_order(order)
        return Response(OrderSerializer(delivered).data, status=status.HTTP_200_OK)


class OrderCancelView(APIView):
    def post(self, request, order_number):
        try:
            order = Order.objects.prefetch_related("items", "items__product").select_related("dealer").get(order_number=order_number)
        except Order.DoesNotExist:
            raise NotFoundAPIError(f"Order '{order_number}' not found.")

        cancelled = cancel_order(order)
        return Response(OrderSerializer(cancelled).data, status=status.HTTP_200_OK)
