import csv
import os
import math
from decimal import Decimal
from django.test import TestCase, SimpleTestCase
from django.conf import settings
from rest_framework.test import APIClient

from core.models import Product, Inventory
from ml.views import load_forecast_data, load_lead_times


class ForecastCSVTests(SimpleTestCase):
    def setUp(self):
        self.csv_path = os.path.join(settings.BASE_DIR, "ml", "forecast.csv")
        self.lead_times_path = os.path.join(settings.DATA_DIR, "lead_times.csv")

    def test_forecast_csv_contract_compliance(self):
        self.assertTrue(os.path.exists(self.csv_path), "ml/forecast.csv must exist")

        with open(self.csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.assertEqual(reader.fieldnames, ["sku", "week_start", "forecast_units"])
            rows = list(reader)

        self.assertEqual(len(rows), 160, "ml/forecast.csv must have exactly 160 rows")

        expected_weeks = {"2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"}
        with open(self.lead_times_path, mode="r", encoding="utf-8") as f:
            expected_skus = {r["sku"].strip() for r in csv.DictReader(f)}

        self.assertEqual(len(expected_skus), 40)

        seen_pairs = set()
        for r in rows:
            sku = r["sku"].strip()
            week = r["week_start"].strip()
            units = float(r["forecast_units"])

            self.assertIn(sku, expected_skus)
            self.assertIn(week, expected_weeks)
            self.assertGreaterEqual(units, 0.0, "forecast_units must be non-negative")

            pair = (sku, week)
            self.assertNotIn(pair, seen_pairs, f"Duplicate pair found: {pair}")
            seen_pairs.add(pair)

        self.assertEqual(len(seen_pairs), 160)


class MLForecastingAndReorderAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.lead_times_path = os.path.join(settings.DATA_DIR, "lead_times.csv")

    def test_forecast_api_detail_and_404(self):
        with open(self.lead_times_path, mode="r", encoding="utf-8") as f:
            first_sku = next(csv.DictReader(f))["sku"].strip()

        resp = self.client.get(f"/api/forecast/{first_sku}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["sku"], first_sku)
        self.assertEqual(len(data["forecast"]), 4)
        weeks = [x["week_start"] for x in data["forecast"]]
        self.assertEqual(weeks, ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"])

        # 404 for invalid SKU
        resp_404 = self.client.get("/api/forecast/INVALID-0000/")
        self.assertEqual(resp_404.status_code, 404)
        self.assertEqual(resp_404.json().get("error", {}).get("code"), "NOT_FOUND")

    def test_reorder_suggestions_api_shape_and_formulas(self):
        # Create a sample product in DB with known stock
        with open(self.lead_times_path, mode="r", encoding="utf-8") as f:
            sample_sku = next(csv.DictReader(f))["sku"].strip()

        p, _ = Product.objects.get_or_create(
            sku=sample_sku,
            defaults={
                "name": "Test Sample Part",
                "category": "Brakes",
                "brand": "Endurance",
                "vehicle_fitment": "Universal",
                "price": Decimal("500.00"),
            }
        )
        inv, _ = Inventory.objects.get_or_create(product=p, defaults={"quantity": 15})
        inv.quantity = 15
        inv.save()

        resp = self.client.get("/api/reorder-suggestions/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 40)

        # Find sample SKU result
        sample_res = next((r for r in data["results"] if r["sku"] == sample_sku), None)
        self.assertIsNotNone(sample_res)

        # Verify fields and exact formula:
        # reorder_point = lead_time_demand + safety_stock
        # reorder_qty = max(0, ceil(reorder_point - current_stock))
        self.assertEqual(sample_res["current_stock"], 15)
        self.assertAlmostEqual(
            sample_res["reorder_point"],
            round(sample_res["lead_time_demand"] + sample_res["safety_stock"], 1)
        )
        expected_qty = max(0, math.ceil(sample_res["reorder_point"] - sample_res["current_stock"]))
        self.assertEqual(sample_res["reorder_qty"], expected_qty)
