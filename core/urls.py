from django.urls import path
from core import views
from core.assistant.views import AssistantChatView
from ml.views import ForecastDetailView, ReorderSuggestionsView

urlpatterns = [
    # Health check
    path("health/", views.health, name="health"),

    # Products (§4)
    path("products/", views.ProductListView.as_view(), name="product-list"),
    path("products/<str:sku>/", views.ProductDetailView.as_view(), name="product-detail"),

    # Inventory (§5)
    path("inventory/<str:sku>/", views.InventoryUpdateView.as_view(), name="inventory-update"),

    # Dealers (§6)
    path("dealers/", views.DealerListView.as_view(), name="dealer-list"),
    path("dealers/<int:pk>/", views.DealerDetailView.as_view(), name="dealer-detail"),

    # Orders (§7)
    path("orders/", views.OrderListView.as_view(), name="order-list"),
    path("orders/<str:order_number>/", views.OrderDetailView.as_view(), name="order-detail"),
    path("orders/<str:order_number>/confirm/", views.OrderConfirmView.as_view(), name="order-confirm"),
    path("orders/<str:order_number>/dispatch/", views.OrderDispatchView.as_view(), name="order-dispatch"),
    path("orders/<str:order_number>/deliver/", views.OrderDeliverView.as_view(), name="order-deliver"),
    path("orders/<str:order_number>/cancel/", views.OrderCancelView.as_view(), name="order-cancel"),

    # Dealer Assistant (§9)
    path("assistant/chat/", AssistantChatView.as_view(), name="assistant-chat"),

    # Forecasting and Reorder (§10)
    path("forecast/<str:sku>/", ForecastDetailView.as_view(), name="forecast-detail"),
    path("reorder-suggestions/", ReorderSuggestionsView.as_view(), name="reorder-suggestions"),
]
