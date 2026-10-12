import django
from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import django.core.validators


def get_check_constraint():
    if django.VERSION >= (5, 1):
        return models.CheckConstraint(
            condition=models.Q(quantity__gte=0),
            name='inventory_quantity_non_negative'
        )
    return models.CheckConstraint(
        check=models.Q(quantity__gte=0),
        name='inventory_quantity_non_negative'
    )


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='DailyOrderSequence',
            fields=[
                ('date_str', models.CharField(max_length=8, primary_key=True, serialize=False)),
                ('last_seq', models.PositiveIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='Dealer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('dealer_code', models.CharField(db_index=True, max_length=64, unique=True)),
                ('name', models.CharField(max_length=255)),
                ('city', models.CharField(blank=True, default='', max_length=100)),
                ('phone', models.CharField(blank=True, default='', max_length=50)),
                ('email', models.EmailField(blank=True, default='', max_length=254)),
                ('gstin', models.CharField(blank=True, default='', max_length=50)),
                ('credit_limit', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['id'],
            },
        ),
        migrations.CreateModel(
            name='Product',
            fields=[
                ('sku', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255)),
                ('category', models.CharField(db_index=True, max_length=100)),
                ('brand', models.CharField(db_index=True, max_length=100)),
                ('vehicle_fitment', models.CharField(db_index=True, max_length=255)),
                ('price', models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))])),
                ('description', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['sku'],
            },
        ),
        migrations.CreateModel(
            name='ConversationSession',
            fields=[
                ('session_id', models.CharField(max_length=128, primary_key=True, serialize=False)),
                ('messages', models.JSONField(default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('dealer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='chat_sessions', to='core.dealer')),
            ],
        ),
        migrations.CreateModel(
            name='Order',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order_number', models.CharField(db_index=True, max_length=64, unique=True)),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('CONFIRMED', 'Confirmed'), ('DISPATCHED', 'Dispatched'), ('DELIVERED', 'Delivered'), ('CANCELLED', 'Cancelled')], db_index=True, default='DRAFT', max_length=20)),
                ('subtotal', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('tax_total', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('grand_total', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('idempotency_key', models.CharField(blank=True, db_index=True, max_length=255, null=True, unique=True)),
                ('idempotency_request_hash', models.CharField(blank=True, max_length=64, null=True)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('dealer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='orders', to='core.dealer')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.CreateModel(
            name='Inventory',
            fields=[
                ('product', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='inventory', serialize=False, to='core.product')),
                ('quantity', models.IntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name='inventory',
            constraint=get_check_constraint(),
        ),
        migrations.CreateModel(
            name='OrderItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sku', models.CharField(max_length=64)),
                ('name', models.CharField(max_length=255)),
                ('quantity', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=12)),
                ('line_subtotal', models.DecimalField(decimal_places=2, max_digits=12)),
                ('line_tax', models.DecimalField(decimal_places=2, max_digits=12)),
                ('line_total', models.DecimalField(decimal_places=2, max_digits=12)),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='core.order')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='order_items', to='core.product')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
        migrations.AddConstraint(
            model_name='orderitem',
            constraint=models.UniqueConstraint(fields=('order', 'product'), name='unique_order_product'),
        ),
    ]
