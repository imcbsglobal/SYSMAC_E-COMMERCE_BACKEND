from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.utils.html import format_html
from decimal import Decimal
from django.utils import timezone


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    USER_TYPES = (
        ('admin', 'Admin'),
        ('user', 'Regular User'),
    )

    email = models.EmailField(unique=True)
    # Required for regular users at signup (enforced in SignupSerializer),
    # left null/blank for admins created via createsuperuser so that flow
    # doesn't need to change. unique=True + null=True lets multiple admins
    # have no phone while still preventing two accounts sharing one number.
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    user_type = models.CharField(max_length=10, choices=USER_TYPES, default='user')
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    # Google OAuth fields
    google_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    profile_picture = models.URLField(blank=True, null=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_admin(self):
        return self.user_type == 'admin' or self.is_superuser


class CustomProduct(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    main_image = models.ImageField(upload_to='products/', blank=True, null=True)
    company = models.CharField(max_length=100, blank=True, null=True)
    brand = models.CharField(max_length=100, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    unit = models.CharField(max_length=50, blank=True, null=True)
    product = models.CharField(max_length=100, blank=True, null=True, verbose_name="Product Type")
    stock_quantity = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_bestseller = models.BooleanField(default=False, verbose_name="Bestseller")
    bestseller_order = models.PositiveIntegerField(default=0, blank=True, null=True,
                                                  help_text="Order in bestseller slider (0 = not shown)")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Wishlist(models.Model):
    """
    Model to track user's wishlist items.
    Can store either custom products (through ForeignKey) or API products (through product code).
    """

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='wishlist_items',
        verbose_name='User'
    )

    product = models.ForeignKey(
        CustomProduct,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='wishlisted_by',
        verbose_name='Custom Product'
    )

    api_product_code = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name='API Product Code',
        help_text='Product code from external API'
    )

    added_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Added Date'
    )

    class Meta:
        unique_together = [
            ('user', 'product'),  # A user can't wishlist same custom product multiple times
            ('user', 'api_product_code')  # A user can't wishlist same API product multiple times
        ]
        verbose_name = 'Wishlist Item'
        verbose_name_plural = 'Wishlist Items'
        ordering = ['-added_at']  # Newest items first

    def __str__(self):
        if self.product:
            return f"{self.user.email} - {self.product.name}"
        return f"{self.user.email} - API Product {self.api_product_code}"

    def clean(self):
        """
        Validate that either product or api_product_code is set, but not both
        """
        if not self.product and not self.api_product_code:
            raise ValidationError("Either product or API product code must be set")

        if self.product and self.api_product_code:
            raise ValidationError("Cannot set both product and API product code")

    def save(self, *args, **kwargs):
        self.full_clean()  # Run validation before saving
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        """Get display name for the product"""
        if self.product:
            return self.product.name
        return f"API Product {self.api_product_code}"

    @property
    def product_type(self):
        """Get product type for templates"""
        return 'custom' if self.product else 'api'


class CartItem(models.Model):
    # Fixed: Changed User to CustomUser
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='cart_items')

    # For custom products
    product = models.ForeignKey('CustomProduct', on_delete=models.CASCADE, null=True, blank=True)

    # For API products
    api_product_code = models.CharField(max_length=100, null=True, blank=True)
    api_product_name = models.CharField(max_length=255, null=True, blank=True)
    api_product_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Ensure a user can't have duplicate items in cart
        unique_together = [
            ['user', 'product'],  # For custom products
            ['user', 'api_product_code'],  # For API products
        ]

    def __str__(self):
        if self.product:
            return f"{self.user.email} - {self.product.name} (Custom)"
        elif self.api_product_code:
            return f"{self.user.email} - {self.api_product_name} (API)"
        return f"{self.user.email} - Unknown Product"

    @property
    def get_price(self):
        """Get the price of the item"""
        if self.product:
            return self.product.price
        elif self.api_product_price:
            return self.api_product_price
        return Decimal('0.00')

    @property
    def get_name(self):
        """Get the name of the item"""
        if self.product:
            return self.product.name
        elif self.api_product_name:
            return self.api_product_name
        return "Unknown Product"


# Optional: Add a Cart model if needed for your views
class Cart(models.Model):
    """
    Optional Cart model - you can use this if your views expect a Cart model,
    or you can modify your views to work directly with CartItem
    """
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart for {self.user.email}"

    @property
    def total_items(self):
        return self.user.cart_items.count()

    @property
    def total_price(self):
        total = Decimal('0.00')
        for item in self.user.cart_items.all():
            total += item.get_price * item.quantity
        return total


class EditedAPIProduct(models.Model):
    original_code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    product = models.CharField(max_length=100, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    unit = models.CharField(max_length=50, blank=True, null=True)
    tax_code = models.CharField(max_length=50, blank=True, null=True)
    company = models.CharField(max_length=100, blank=True, null=True)
    brand = models.CharField(max_length=100, blank=True, null=True)
    text6 = models.CharField(max_length=100, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    original_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    image = models.ImageField(upload_to='api_products/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_bestseller = models.BooleanField(default=False, verbose_name="Bestseller")
    bestseller_order = models.PositiveIntegerField(default=0, blank=True, null=True,
                                                  help_text="Order in bestseller slider (0 = not shown)")

    def __str__(self):
        return f"{self.name} (Edited)"


# NOTE: kept as-is, UNUSED — nothing in api_views.py imports or queries this.
# It predates the sync-tool integration below and is a different table from
# acc_product. Left in place untouched so its DB table isn't dropped
# out from under you; safe to delete later once you've confirmed nothing
# else depends on it.
class Product(models.Model):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    product_type = models.CharField(max_length=100, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    unit = models.CharField(max_length=50, blank=True, null=True)
    tax_code = models.CharField(max_length=50, blank=True, null=True)
    company = models.CharField(max_length=100, blank=True, null=True)
    brand = models.CharField(max_length=100, blank=True, null=True)
    text6 = models.CharField(max_length=100, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    image = models.URLField(blank=True, null=True)  # Store API image URL
    is_active = models.BooleanField(default=True)
    is_bestseller = models.BooleanField(default=False)
    last_synced = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


# models.py - Update your Banner model if needed
class Banner(models.Model):
    title = models.CharField(max_length=200, blank=True, null=True)
    subtitle = models.CharField(max_length=300, blank=True, null=True)
    image = models.ImageField(upload_to="banners/")
    link = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]
        verbose_name = "Banner"
        verbose_name_plural = "Banners"

    def __str__(self):
        return self.title if self.title else f"Banner {self.id}"

    def image_preview(self):
        if self.image:
            return format_html('<img src="{}" style="max-height: 100px; max-width: 200px;" />', self.image.url)
        return "No Image"
    image_preview.short_description = 'Preview'


class ProductImage(models.Model):
    custom_product = models.ForeignKey(
        'CustomProduct',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='additional_images'
    )
    api_product = models.ForeignKey(
        'EditedAPIProduct',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='additional_images'
    )
    image = models.ImageField(upload_to='product_images/')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        if self.custom_product:
            return f"Image for {self.custom_product.name}"
        return f"Image for {self.api_product.name}"

    def clean(self):
        if not self.custom_product and not self.api_product:
            raise ValidationError("Either custom_product or api_product must be set")
        if self.custom_product and self.api_product:
            raise ValidationError("Cannot set both custom_product and api_product")


# In models.py - Replace your existing Brand model with this updated version
class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)
    logo = models.ImageField(upload_to="brands/", blank=True, null=True)
    image_url = models.URLField(blank=True, null=True, help_text="Alternative to uploading: paste image URL")
    website = models.URLField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "Brand"
        verbose_name_plural = "Brands"

    def __str__(self):
        return self.name

    def get_image_url(self):
        """Return the appropriate image URL - either uploaded file or URL"""
        if self.logo:
            return self.logo.url
        elif self.image_url:
            return self.image_url
        return ''

    def logo_preview(self):
        image_url = self.get_image_url()
        if image_url:
            return format_html('<img src="{}" style="max-height: 60px; max-width: 120px;" />', image_url)
        return "No Logo"
    logo_preview.short_description = 'Logo Preview'


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    online_name = models.CharField(max_length=100, blank=True, null=True, help_text="Name shown to customers on the website")
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    image_url = models.URLField(blank=True, null=True, help_text="Alternative to uploading: paste image URL")
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    product_types = models.TextField(blank=True, help_text="Comma-separated product-type strings that belong to this category")

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "Category"
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name

    def get_image_url(self):
        """Return the appropriate image URL - either uploaded file or URL"""
        if self.image:
            return self.image.url
        elif self.image_url:
            return self.image_url
        return ''

    def image_preview(self):
        image_url = self.get_image_url()
        if image_url:
            return format_html('<img src="{}" style="max-height: 60px; max-width: 120px;" />', image_url)
        return "No Image"
    image_preview.short_description = 'Image Preview'

    def product_count(self):
        """Get count of products in this category"""
        custom_count = CustomProduct.objects.filter(category__iexact=self.name, is_active=True).count()
        api_count = EditedAPIProduct.objects.filter(category__iexact=self.name, is_active=True).count()
        return custom_count + api_count

    def get_products(self):
        """Get all products in this category"""
        custom_products = CustomProduct.objects.filter(category__iexact=self.name, is_active=True)
        api_products = EditedAPIProduct.objects.filter(category__iexact=self.name, is_active=True)
        return {'custom': custom_products, 'api': api_products}

    def get_product_type_list(self):
        """Return a Python list of product-type strings."""
        return [pt.strip() for pt in self.product_types.split(",") if pt.strip()]


# ── Deal of the Day ──────────────────────────────────────────────────────
class DealOfTheDay(models.Model):
    """
    Admin-picked Sysmac (API) product offered as a time-boxed deal on the
    storefront homepage.

    Only `product_code` + the timing window are stored here — live product
    details (name/price/image) are looked up fresh from the Sysmac catalogue
    (honoring any EditedAPIProduct override) whenever a deal is shaped for a
    response, so the deal always reflects the current price/name/image
    instead of a stale snapshot.

    Multiple deals can exist at once (e.g. one active now, others scheduled
    for later) — whether a deal is currently live is computed from
    start_at/end_at, not stored as a flag.
    """
    product_code = models.CharField(max_length=100, db_index=True)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck to cancel a deal early without deleting it"
    )
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deals_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_at']
        verbose_name = 'Deal of the Day'
        verbose_name_plural = 'Deals of the Day'

    def __str__(self):
        return f"{self.product_code} ({self.start_at:%Y-%m-%d %H:%M} → {self.end_at:%Y-%m-%d %H:%M})"

    def clean(self):
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError("End time must be after start time")

    @property
    def status(self):
        """One of 'cancelled' | 'scheduled' | 'active' | 'expired'."""
        if not self.is_active:
            return 'cancelled'
        now = timezone.now()
        if now < self.start_at:
            return 'scheduled'
        if now > self.end_at:
            return 'expired'
        return 'active'


# ── Orders (manual / WhatsApp workflow) ──────────────────────────────────
class Order(models.Model):
    """
    There's no in-app checkout — customers send product details over
    WhatsApp and an admin manually creates the matching Order here against
    the customer's EXISTING account (looked up by email/phone). Only two
    admin-driven transitions exist after that: Confirmed (admin has called
    the customer and verified the order) and Delivered. 'pending' is the
    default the order sits in the moment it's created, before that first
    confirmation call happens.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('delivered', 'Delivered'),
    )

    order_number = models.CharField(max_length=20, unique=True, blank=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='orders')

    # Contact number for the confirmation call — defaults to the
    # customer's profile phone at creation time but can be overridden
    # (e.g. they ordered for delivery to someone else / a different number).
    contact_phone = models.CharField(max_length=15)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True, null=True, help_text="e.g. details copied from the WhatsApp order")

    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='orders_created', help_text="Admin who manually created this order"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Order'
        verbose_name_plural = 'Orders'

    def __str__(self):
        return self.order_number or f"Order #{self.pk}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.order_number:
            # Human-readable reference both admin and customer can use on a
            # call — assigned only once the row has a real id.
            self.order_number = f"ORD-{self.id:06d}"
            super().save(update_fields=['order_number'])

    @property
    def total(self):
        return sum((item.line_total for item in self.items.all()), Decimal('0.00'))


class OrderItem(models.Model):
    """
    Mirrors CartItem's custom-vs-Sysmac(API) product split, but snapshots
    name/price at order time (name/price/quantity stay fixed even if the
    underlying product is later edited, deactivated, or removed).
    """
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('CustomProduct', on_delete=models.SET_NULL, null=True, blank=True)
    api_product_code = models.CharField(max_length=100, null=True, blank=True)

    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.name} x{self.quantity}"

    @property
    def line_total(self):
        return self.price * self.quantity


# ══════════════════════════════════════════════════════════════════════════
# ── Sync-tool tables ─────────────────────────────────────────────────────
# The following models map to tables populated by the external sync tool,
# NOT by Django migrations — every one is managed = False, so Django will
# never try to create/alter/drop these tables. They mirror what
# api.sysmac.in/api/... used to return over HTTP, now read straight from
# Postgres instead.
#
# NAMING NOTE: the sync tool's own model file calls the product table
# "Product" — renamed to SysmacProduct here because a class named Product
# already exists above (a different, unused, Django-managed table). Do not
# rename it back without also renaming/removing the old Product model,
# or Python will silently let one class overwrite the other.
# ══════════════════════════════════════════════════════════════════════════

class SysmacProductType(models.Model):
    """
    Source: acc_productproduct
    WHERE condition (applied by the sync tool, not here): settings LIKE
    '%##EC##%' AND settings LIKE '%##EU##%'
    Was: https://api.sysmac.in/api/productproduct/
    """
    name = models.CharField(max_length=30, primary_key=True)
    
    url = models.CharField(max_length=300, null=True, blank=True)

    class Meta:
        db_table = "acc_productproduct"
        managed = False  # table already exists in postgres, created outside Django migrations

    def __str__(self):
        return self.name


class SysmacProductBrand(models.Model):
    """
    Source: acc_productbrand
    WHERE condition (applied by the sync tool, not here): settings LIKE
    '%##EC##%' AND settings LIKE '%##EU##%'
    Was: https://api.sysmac.in/api/productbrand/
    """
    name = models.CharField(max_length=30, primary_key=True)
   
    url = models.CharField(max_length=300, null=True, blank=True)

    class Meta:
        db_table = "acc_productbrand"
        managed = False  # table already exists in postgres, created outside Django migrations

    def __str__(self):
        return self.name


class Master(models.Model):
    """
    Source: acc_master
    WHERE condition (applied by the sync tool, not here): super_code = 'debto'
    """
    code = models.CharField(max_length=30, primary_key=True)
    name = models.CharField(max_length=250)
    super_code = models.CharField(max_length=5, null=True, blank=True)
    address = models.CharField(max_length=100, null=True, blank=True)
    place = models.CharField(max_length=60, null=True, blank=True)
    city = models.CharField(max_length=80, null=True, blank=True)
    state = models.CharField(max_length=40, null=True, blank=True)
    phone = models.CharField(max_length=60, null=True, blank=True)
    phone2 = models.CharField(max_length=60, null=True, blank=True)
    fax = models.CharField(max_length=30, null=True, blank=True)
    remarkcolumntitle = models.CharField(max_length=20, null=True, blank=True)
    area = models.CharField(max_length=30, null=True, blank=True)
    gstin = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "acc_master"
        managed = False  # table already exists in postgres, created outside Django migrations

    def __str__(self):
        return f"{self.code} - {self.name}"


class SysmacProduct(models.Model):
    """
    Source: acc_product  (renamed from the sync tool's "Product" to avoid
    clashing with the existing, unused Product model above)
    WHERE condition (applied by the sync tool, not here): settings LIKE
    '%##EC##%'
    text3 = size, text5 = sub category
    Was: https://api.sysmac.in/api/product/
    """
    code = models.CharField(max_length=30, primary_key=True)
    name = models.CharField(max_length=200, null=True, blank=True)
    size = models.CharField(max_length=60, null=True, blank=True, db_column="text3")
    sub_category = models.CharField(max_length=60, null=True, blank=True, db_column="text5")
    unit = models.CharField(max_length=10, null=True, blank=True)
    taxcode = models.CharField(max_length=5, null=True, blank=True)
    company = models.CharField(max_length=30, null=True, blank=True)
    product = models.CharField(max_length=30, null=True, blank=True)
    brand = models.CharField(max_length=30, null=True, blank=True)
    text6 = models.CharField(max_length=40, null=True, blank=True)
    nameinsl = models.CharField(max_length=350, null=True, blank=True)
  
    properties = models.CharField(max_length=900, null=True, blank=True)

    class Meta:
        db_table = "acc_product"
        managed = False  # table already exists in postgres, created outside Django migrations

    def __str__(self):
        return f"{self.code} - {self.name}"


class SysmacProductPhoto(models.Model):
    """
    Source: acc_productphoto — no WHERE condition, all rows sync.
    Was: https://api.sysmac.in/api/productphoto/
    """
    slno = models.AutoField(primary_key=True)
    code = models.CharField(max_length=30, null=True, blank=True)
    url2 = models.CharField(max_length=300, null=True, blank=True)

    class Meta:
        db_table = "acc_productphoto"
        managed = False  # table already exists in postgres, created outside Django migrations

    def __str__(self):
        return f"{self.code} - photo {self.slno}"


class ProductBatch(models.Model):
    """
    Source: acc_productbatch
    WHERE condition (applied by the sync tool, not here): settings LIKE
    '%##EC##%'
    This is where pricing lives — joined to SysmacProduct via productcode.
    salesprice is the confirmed customer-facing selling price.

    NOTE: unlike the other synced tables, the real acc_productbatch table
    in Postgres has NO `settings` column — it was removed here after a
    ProgrammingError (column acc_productbatch.settings does not exist)
    confirmed the model was out of sync with the actual table. Do not add
    it back unless the column is actually added to the DB.
    """
    slno = models.AutoField(primary_key=True)
    productcode = models.CharField(max_length=30)
    salesprice = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)
    secondprice = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)
    thirdprice = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)
    fourthprice = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    nlc1 = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)
    barcode = models.CharField(max_length=35, null=True, blank=True)
    bmrp = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)

    class Meta:
        db_table = "acc_productbatch"
        managed = False  # table already exists in postgres, created outside Django migrations

    def __str__(self):
        return f"{self.productcode} batch {self.slno}"


class ServiceMaster(models.Model):
    """
    Source: acc_tt_servicemaster
    WHERE condition (applied by the sync tool, not here): type = section and area
    """
    slno = models.AutoField(primary_key=True)
    type = models.CharField(max_length=20, null=True, blank=True)
    name = models.CharField(max_length=200, null=True, blank=True)
    code = models.CharField(max_length=30, null=True, blank=True)
    url = models.CharField(max_length=300, null=True, blank=True)

    class Meta:
        db_table = "acc_tt_servicemaster"
        managed = False  # table already exists in postgres, created outside Django migrations

    def __str__(self):
        return f"{self.type} - {self.name}"


class SysmacUserAccount(models.Model):
    """
    Source: acc_users
    WHERE condition (applied by the sync tool, not here): role IN
    ('level1', 'level2', 'level3')

    Source PK is composite (id, pass). Django models need a single pk,
    so "id" is used as the pk here - update if id alone isn't actually
    unique in the source data. Renamed from "UserAccount" purely to keep
    "Sysmac*" naming consistent with the other synced tables above; no
    clash with your existing CustomUser.
    """
    id = models.CharField(max_length=30, primary_key=True, db_column="id")
    password = models.CharField(max_length=100, db_column="pass")
    role = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "acc_users"
        managed = False  # table already exists in postgres, created outside Django migrations

    def __str__(self):
        return f"{self.id} ({self.role})"