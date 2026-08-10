from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import api_views

urlpatterns = [
    # Auth
    path('token/', api_views.MyTokenObtainPairView.as_view(), name='api_token'),
    path('token/refresh/', TokenRefreshView.as_view(), name='api_token_refresh'),
    path('signup/', api_views.signup, name='api_signup'),
    path('me/', api_views.me, name='api_me'),

    # Public
    path('products/', api_views.products, name='api_products'),
    path('products/<str:code>/photos/', api_views.product_photos, name='api_product_photos'),
    path('products/<str:product_identifier>/', api_views.product_detail, name='api_product_detail'),
    path('categories/', api_views.categories, name='api_categories'),
    path('banners/', api_views.banners, name='api_banners'),
    path('brands/', api_views.brands, name='api_brands'),
    path('sysmac-brands/', api_views.sysmac_brands, name='api_sysmac_brands'),
    path('sysmac-product-types/', api_views.sysmac_product_types, name='api_sysmac_product_types'),
    path('deals/', api_views.deals, name='api_deals'),

    # Cart
    path('cart/', api_views.cart, name='api_cart'),
    path('cart/add/', api_views.add_to_cart, name='api_cart_add'),
    path('cart/remove/<int:item_id>/', api_views.remove_from_cart, name='api_cart_remove'),
    path('cart/update/<int:item_id>/', api_views.update_cart_item, name='api_cart_update'),

    # Wishlist
    path('wishlist/', api_views.wishlist, name='api_wishlist'),
    path('wishlist/toggle/', api_views.toggle_wishlist, name='api_wishlist_toggle'),

    # Orders — customer's own
    path('orders/', api_views.my_orders, name='api_my_orders'),

    # Admin — stats & users
    path('admin/stats/', api_views.admin_stats, name='api_admin_stats'),
    path('admin/users/', api_views.admin_users, name='api_admin_users'),
    path('admin/users/<int:user_id>/toggle/', api_views.admin_toggle_user, name='api_admin_toggle_user'),

    # Admin — banners
    path('admin/banners/list/', api_views.admin_banners, name='api_admin_banner_list'),
    path('admin/banners/', api_views.admin_banners, name='api_admin_banners'),
    path('admin/banners/<int:pk>/', api_views.admin_banner_update, name='api_admin_banner_update'),
    path('admin/banners/<int:pk>/delete/', api_views.admin_banner_delete, name='api_admin_banner_delete'),

    # Admin — brands (legacy manual CRUD, kept for compatibility)
    path('admin/brands/list/', api_views.admin_brands, name='api_admin_brand_list'),
    path('admin/brands/', api_views.admin_brands, name='api_admin_brands'),
    path('admin/brands/<int:pk>/', api_views.admin_brand_update, name='api_admin_brand_update'),
    path('admin/brands/<int:pk>/delete/', api_views.admin_brand_delete, name='api_admin_brand_delete'),

    # Admin — categories (legacy manual CRUD, kept for compatibility)
    path('admin/categories/', api_views.admin_categories_all, name='api_admin_categories_all'),
    path('admin/categories/create/', api_views.admin_category_create, name='api_admin_category_create'),
    path('admin/categories/<int:pk>/', api_views.admin_category_update, name='api_admin_category_update'),
    path('admin/categories/<int:pk>/delete/', api_views.admin_category_delete, name='api_admin_category_delete'),

    # Admin — custom products
    path('admin/custom-products/', api_views.admin_custom_products, name='api_admin_custom_products'),
    path('admin/custom-products/create/', api_views.admin_custom_product_create, name='api_admin_custom_product_create'),
    path('admin/custom-products/<int:pk>/', api_views.admin_custom_product_update, name='api_admin_custom_product_update'),
    path('admin/custom-products/<int:pk>/delete/', api_views.admin_custom_product_delete, name='api_admin_custom_product_delete'),

    # Admin — sysmac products
    path('admin/sysmac-products/', api_views.admin_sysmac_products, name='api_admin_sysmac_products'),
    path('admin/sysmac-products/<str:code>/', api_views.admin_sysmac_product_update, name='api_admin_sysmac_product_update'),
    path('admin/sysmac-products/<str:code>/delete/', api_views.admin_sysmac_product_delete, name='api_admin_sysmac_product_delete'),

    # Admin — sysmac brands (live from Sysmac brand API)
    path('admin/sysmac-brands/', api_views.admin_sysmac_brands, name='api_admin_sysmac_brands'),

    # Admin — sysmac categories / product types (live from Sysmac product-type API)
    path('admin/sysmac-categories/', api_views.admin_sysmac_categories, name='api_admin_sysmac_categories'),

    # Admin — deal of the day
    path('admin/deals/', api_views.admin_deals, name='api_admin_deals'),
    path('admin/deals/<int:pk>/delete/', api_views.admin_deal_delete, name='api_admin_deal_delete'),

    # Admin — order management
    path('admin/customers/search/', api_views.admin_customer_search, name='api_admin_customer_search'),
    path('admin/orders/', api_views.admin_orders, name='api_admin_orders'),
    path('admin/orders/<int:pk>/status/', api_views.admin_order_status_update, name='api_admin_order_status_update'),
]