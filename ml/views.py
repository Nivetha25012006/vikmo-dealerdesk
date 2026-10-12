import csv
import math
import os
import statistics
from decimal import Decimal
from django.conf import settings
from django.http import Http404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.models import Product, Inventory
from core.exceptions import NotFoundAPIError


def get_forecast_file_path() -> str:
    return os.path.join(settings.BASE_DIR, "ml", "forecast.csv")


def load_forecast_data() -> dict[str, list[dict]]:
    """
    Returns map of sku -> list of {"week_start": "...", "forecast_units": float}
    """
    path = get_forecast_file_path()
    if not os.path.exists(path):
        return {}

    forecast_by_sku = {}
    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            sku = r["sku"].strip()
            week_start = r["week_start"].strip()
            units = float(r["forecast_units"])
            if sku not in forecast_by_sku:
                forecast_by_sku[sku] = []
            forecast_by_sku[sku].append({
                "week_start": week_start,
                "forecast_units": units,
            })
    return forecast_by_sku


def load_lead_times() -> dict[str, int]:
    path = os.path.join(settings.DATA_DIR, "lead_times.csv")
    if not os.path.exists(path):
        return {}

    lead_times = {}
    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            sku = r["sku"].strip()
            lead_times[sku] = int(r["lead_time_weeks"])
    return lead_times


def load_sales_history_recent() -> dict[str, list[float]]:
    """
    Load units_sold for each SKU from data/sales_history.csv ordered by week_start ascending.
    """
    path = os.path.join(settings.DATA_DIR, "sales_history.csv")
    if not os.path.exists(path):
        return {}

    sales_by_sku = {}
    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Sort chronologically
    rows.sort(key=lambda x: x["week_start"])
    for r in rows:
        sku = r["sku"].strip()
        units = float(r["units_sold"])
        if sku not in sales_by_sku:
            sales_by_sku[sku] = []
        sales_by_sku[sku].append(units)

    return sales_by_sku


class ForecastDetailView(APIView):
    def get(self, request, sku):
        forecast_data = load_forecast_data()
        sku_clean = sku.strip()
        if sku_clean not in forecast_data:
            raise NotFoundAPIError(f"Forecast not found for SKU '{sku_clean}'.")

        return Response({
            "sku": sku_clean,
            "forecast": forecast_data[sku_clean],
        }, status=status.HTTP_200_OK)


class ReorderSuggestionsView(APIView):
    def get(self, request):
        lead_times = load_lead_times()
        forecast_data = load_forecast_data()
        sales_history = load_sales_history_recent()

        # Live inventory from DB
        live_inventories = {
            inv.product_id: inv.quantity
            for inv in Inventory.objects.all()
        }

        results = []
        for sku, lead_time_weeks in lead_times.items():
            current_stock = live_inventories.get(sku, 0)
            sku_forecast = forecast_data.get(sku, [])

            # lead_time_demand = sum of forecast_units for first L forecast weeks
            l_demand = sum(f["forecast_units"] for f in sku_forecast[:lead_time_weeks])
            lead_time_demand = round(l_demand, 1)

            # sigma = sample std dev (n - 1) of units_sold over most recent 12 weeks of sales_history.csv
            past_sales = sales_history.get(sku, [])
            recent_12 = past_sales[-12:] if len(past_sales) >= 12 else past_sales
            if len(recent_12) >= 2:
                sigma = statistics.stdev(recent_12)
            else:
                sigma = 0.0

            # safety_stock = ceil(1.65 * sigma * sqrt(L))
            safety_stock = math.ceil(1.65 * sigma * math.sqrt(lead_time_weeks))

            # reorder_point = lead_time_demand + safety_stock
            reorder_point = round(lead_time_demand + safety_stock, 1)

            # reorder_qty = max(0, ceil(reorder_point - current_stock))
            reorder_qty = max(0, math.ceil(reorder_point - current_stock))

            results.append({
                "sku": sku,
                "current_stock": current_stock,
                "lead_time_weeks": lead_time_weeks,
                "lead_time_demand": lead_time_demand,
                "safety_stock": safety_stock,
                "reorder_point": reorder_point,
                "reorder_qty": reorder_qty,
            })

        return Response({"results": results}, status=status.HTTP_200_OK)
