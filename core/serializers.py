from decimal import Decimal
from rest_framework import serializers

from .models import Product, Inventory, Dealer, Order, OrderItem
from .services import format_money
from .exceptions import DuplicateAPIError, ValidationErrorAPIError


class ProductSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()
    stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "stock",
            "description",
        ]

    def get_price(self, obj) -> str:
        return format_money(obj.price)

    def get_stock(self, obj) -> int:
        return obj.stock


class ProductCreateSerializer(serializers.ModelSerializer):
    price = serializers.CharField()

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
        ]

    def validate_sku(self, value):
        if not value or not value.strip():
            raise ValidationErrorAPIError("SKU cannot be empty.")
        if Product.objects.filter(sku=value.strip()).exists():
            raise DuplicateAPIError(f"Product with SKU '{value}' already exists.")
        return value.strip()

    def validate_price(self, value):
        try:
            dec = Decimal(str(value))
        except Exception:
            raise ValidationErrorAPIError("Price must be a valid decimal number.")
        if dec <= Decimal("0.00"):
            raise ValidationErrorAPIError("Price must be greater than 0.")
        # check decimal places
        parts = str(value).split(".")
        if len(parts) == 2 and len(parts[1]) > 2:
            raise ValidationErrorAPIError("Price may have at most 2 decimal places.")
        return dec


class ProductUpdateSerializer(serializers.ModelSerializer):
    price = serializers.CharField(required=False)

    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
        ]

    def validate_price(self, value):
        if value is None:
            return value
        try:
            dec = Decimal(str(value))
        except Exception:
            raise ValidationErrorAPIError("Price must be a valid decimal number.")
        if dec <= Decimal("0.00"):
            raise ValidationErrorAPIError("Price must be greater than 0.")
        parts = str(value).split(".")
        if len(parts) == 2 and len(parts[1]) > 2:
            raise ValidationErrorAPIError("Price may have at most 2 decimal places.")
        return dec


class DealerSerializer(serializers.ModelSerializer):
    credit_limit = serializers.SerializerMethodField()

    class Meta:
        model = Dealer
        fields = [
            "id",
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
        ]

    def get_credit_limit(self, obj) -> str:
        return format_money(obj.credit_limit)


class DealerCreateSerializer(serializers.ModelSerializer):
    credit_limit = serializers.CharField(required=False, default="0.00")

    class Meta:
        model = Dealer
        fields = [
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
        ]

    def validate_dealer_code(self, value):
        if not value or not value.strip():
            raise ValidationErrorAPIError("dealer_code is required.")
        if Dealer.objects.filter(dealer_code=value.strip()).exists():
            raise DuplicateAPIError(f"Dealer with dealer_code '{value}' already exists.")
        return value.strip()

    def validate_name(self, value):
        if not value or not value.strip():
            raise ValidationErrorAPIError("name is required.")
        return value.strip()

    def validate_credit_limit(self, value):
        try:
            dec = Decimal(str(value))
        except Exception:
            raise ValidationErrorAPIError("credit_limit must be a valid decimal number.")
        if dec < Decimal("0.00"):
            raise ValidationErrorAPIError("credit_limit cannot be negative.")
        return dec


class OrderItemSerializer(serializers.ModelSerializer):
    unit_price = serializers.SerializerMethodField()
    line_subtotal = serializers.SerializerMethodField()
    line_tax = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "sku",
            "name",
            "quantity",
            "unit_price",
            "line_subtotal",
            "line_tax",
            "line_total",
        ]

    def get_unit_price(self, obj) -> str:
        return format_money(obj.unit_price)

    def get_line_subtotal(self, obj) -> str:
        return format_money(obj.line_subtotal)

    def get_line_tax(self, obj) -> str:
        return format_money(obj.line_tax)

    def get_line_total(self, obj) -> str:
        return format_money(obj.line_total)


class OrderSerializer(serializers.ModelSerializer):
    dealer_id = serializers.IntegerField(source="dealer.id")
    items = OrderItemSerializer(many=True, read_only=True)
    subtotal = serializers.SerializerMethodField()
    tax_total = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    class Meta:
        model = Order
        fields = [
            "order_number",
            "dealer_id",
            "status",
            "items",
            "subtotal",
            "tax_total",
            "grand_total",
            "created_at",
            "updated_at",
        ]

    def get_subtotal(self, obj) -> str:
        return format_money(obj.subtotal)

    def get_tax_total(self, obj) -> str:
        return format_money(obj.tax_total)

    def get_grand_total(self, obj) -> str:
        return format_money(obj.grand_total)
