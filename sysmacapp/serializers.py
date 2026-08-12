from django.db.models import Q
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import (
    CustomUser, CustomProduct, Category, Banner, Brand, Order, OrderItem,
    SysmacProduct, ProductBatch,
)


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    is_admin = serializers.ReadOnlyField()

    class Meta:
        model = CustomUser
        fields = ['id', 'email', 'phone', 'first_name', 'last_name', 'full_name',
                  'user_type', 'is_staff', 'is_superuser', 'is_active',
                  'is_admin', 'profile_picture', 'date_joined']


class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop(self.username_field, None)
        self.fields['identifier'] = serializers.CharField()
        self.fields['password'] = serializers.CharField(write_only=True)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['is_superuser'] = user.is_superuser
        return token

    def validate(self, attrs):
        identifier = attrs.get('identifier', '').strip()
        password = attrs.get('password', '')

        user = CustomUser.objects.filter(
            Q(email__iexact=identifier) | Q(phone=identifier)
        ).first()

        if user is None or not user.check_password(password) or not user.is_active:
            raise serializers.ValidationError(
                'No active account found with the given credentials'
            )

        refresh = self.get_token(user)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserSerializer(user).data,
        }


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    phone = serializers.CharField(required=True)

    class Meta:
        model = CustomUser
        fields = ['id', 'email', 'phone', 'first_name', 'last_name', 'password']

    def create(self, validated_data):
        password = validated_data.pop('password')
        return CustomUser.objects.create_user(password=password, **validated_data)


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ['id', 'name', 'price', 'quantity', 'line_total']

    def get_line_total(self, obj):
        return float(obj.line_total)


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    customer_name = serializers.SerializerMethodField()
    customer_email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = Order
        fields = ['id', 'order_number', 'status', 'status_display', 'contact_phone',
                  'notes', 'items', 'total', 'customer_name', 'customer_email',
                  'created_at', 'confirmed_at', 'delivered_at']

    def get_total(self, obj):
        return float(obj.total)

    def get_customer_name(self, obj):
        return obj.user.full_name or obj.user.email


class CategorySerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'online_name', 'display_name', 'image',
                  'description', 'is_active', 'order', 'product_count']

    def get_image(self, obj):
        return obj.get_image_url()

    def get_display_name(self, obj):
        return obj.online_name or obj.name

    def get_product_count(self, obj):
        return obj.product_count()


class BannerSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = Banner
        fields = ['id', 'title', 'subtitle', 'image', 'link', 'is_active', 'order']

    def get_image(self, obj):
        request = self.context.get('request')
        if obj.image:
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        return ''


class BrandSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = Brand
        fields = ['id', 'name', 'image', 'website', 'description', 'is_active', 'order']

    def get_image(self, obj):
        request = self.context.get('request')
        url = obj.get_image_url()
        if url and url.startswith('/') and request:
            return request.build_absolute_uri(url)
        return url


# ── acc_product / acc_productbatch (SysmacProduct) ──────────────────────
class ProductBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductBatch
        fields = ['slno', 'productcode', 'salesprice', 'secondprice',
                  'thirdprice', 'fourthprice', 'quantity', 'nlc1',
                  'barcode', 'bmrp']


class SysmacProductSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    category = serializers.CharField(source='sub_category')

    class Meta:
        model = SysmacProduct
        fields = ['code', 'name', 'size', 'category', 'unit', 'taxcode',
                  'company', 'product', 'brand', 'price', 'original_price']

    def get_price(self, obj):
        # NOTE: settings__icontains filter removed — acc_productbatch has
        # no `settings` column in the real table (confirmed via
        # ProgrammingError: column acc_productbatch.settings does not
        # exist). See ProductBatch model docstring in models.py.
        batch = ProductBatch.objects.filter(
            productcode=obj.code
        ).order_by('slno').last()
        return float(batch.salesprice) if batch and batch.salesprice else 0.0

    def get_original_price(self, obj):
        # NOTE: settings__icontains filter removed — see get_price() above.
        batch = ProductBatch.objects.filter(
            productcode=obj.code
        ).order_by('slno').last()
        return float(batch.bmrp) if batch and batch.bmrp else 0.0