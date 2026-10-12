import csv
from decimal import Decimal
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Product, Inventory, Dealer


class Command(BaseCommand):
    help = "Load catalogue.csv and dealers.csv into the database. Idempotent and safe to run twice."

    def handle(self, *args, **options):
        data_dir = settings.DATA_DIR  # <repo root>/data

        catalogue_path = data_dir / "catalogue.csv"
        dealers_path = data_dir / "dealers.csv"

        if not catalogue_path.exists():
            self.stdout.write(self.style.ERROR(f"catalogue.csv not found at {catalogue_path}"))
            return
        if not dealers_path.exists():
            self.stdout.write(self.style.ERROR(f"dealers.csv not found at {dealers_path}"))
            return

        # 1. Seed Dealers (25 dealers)
        existing_dealers = {d.dealer_code: d for d in Dealer.objects.all()}
        dealers_to_create = []
        dealers_to_update = []

        with open(dealers_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row["dealer_code"].strip()
                name = row["name"].strip()
                city = row.get("city", "").strip()
                phone = row.get("phone", "").strip()
                email = row.get("email", "").strip()
                gstin = row.get("gstin", "").strip()
                limit_str = row.get("credit_limit", "0.00").strip()
                credit_limit = Decimal(limit_str) if limit_str else Decimal("0.00")

                if code in existing_dealers:
                    d = existing_dealers[code]
                    d.name = name
                    d.city = city
                    d.phone = phone
                    d.email = email
                    d.gstin = gstin
                    d.credit_limit = credit_limit
                    dealers_to_update.append(d)
                else:
                    dealers_to_create.append(
                        Dealer(
                            dealer_code=code,
                            name=name,
                            city=city,
                            phone=phone,
                            email=email,
                            gstin=gstin,
                            credit_limit=credit_limit,
                        )
                    )

        with transaction.atomic():
            if dealers_to_create:
                Dealer.objects.bulk_create(dealers_to_create)
            if dealers_to_update:
                Dealer.objects.bulk_update(
                    dealers_to_update,
                    fields=["name", "city", "phone", "email", "gstin", "credit_limit"]
                )

        total_dealers = Dealer.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Dealers: {len(dealers_to_create)} created, {len(dealers_to_update)} updated (total: {total_dealers})"
        ))

        # 2. Seed Products and Inventory (600 products)
        existing_products = {p.sku: p for p in Product.objects.all()}
        existing_inventories = {inv.product_id: inv for inv in Inventory.objects.all()}

        products_to_create = []
        products_to_update = []
        inventories_to_create = []

        with open(catalogue_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sku = row["sku"].strip()
                name = row["name"].strip()
                category = row.get("category", "").strip()
                brand = row.get("brand", "").strip()
                vehicle_fitment = row.get("vehicle_fitment", "").strip()
                price = Decimal(row["price"].strip())
                starting_stock = int(row.get("stock", "0").strip())
                description = row.get("description", "").strip()

                if sku in existing_products:
                    p = existing_products[sku]
                    p.name = name
                    p.category = category
                    p.brand = brand
                    p.vehicle_fitment = vehicle_fitment
                    p.price = price
                    p.description = description
                    products_to_update.append(p)
                else:
                    products_to_create.append(
                        Product(
                            sku=sku,
                            name=name,
                            category=category,
                            brand=brand,
                            vehicle_fitment=vehicle_fitment,
                            price=price,
                            description=description,
                        )
                    )

                # ONLY create inventory if not already existing, to preserve live stock updates on re-seeding!
                if sku not in existing_inventories:
                    inventories_to_create.append(
                        Inventory(product_id=sku, quantity=starting_stock)
                    )

        with transaction.atomic():
            if products_to_create:
                Product.objects.bulk_create(products_to_create, batch_size=200)
            if products_to_update:
                Product.objects.bulk_update(
                    products_to_update,
                    fields=["name", "category", "brand", "vehicle_fitment", "price", "description"],
                    batch_size=200
                )
            if inventories_to_create:
                Inventory.objects.bulk_create(inventories_to_create, batch_size=200)

        total_products = Product.objects.count()
        total_inventories = Inventory.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Products: {len(products_to_create)} created, {len(products_to_update)} updated (total: {total_products})"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"Inventories: {len(inventories_to_create)} created (total: {total_inventories})"
        ))
