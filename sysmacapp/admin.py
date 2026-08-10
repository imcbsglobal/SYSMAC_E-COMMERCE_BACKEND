# admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.urls import path
from django.shortcuts import render
from .models import CustomUser
from .models import Banner
from django.utils.html import format_html


# --- NEW: forms bound to CustomUser (email-based) instead of the default
# UserCreationForm/UserChangeForm, which are hard-wired to auth.User.
# Without these, UserAdmin's default forms don't match this model, so the
# 'password' field in fieldsets below renders as a plain text box, and
# Admin saves whatever you type there as PLAIN TEXT instead of hashing it.
# This is why accounts created/edited via /admin can fail login with
# "invalid password" even when the password looks correct.
class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('email',)


class CustomUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = CustomUser
        fields = '__all__'
# --- end new ---


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    # --- NEW: use the CustomUser-bound forms above so add/edit hash passwords correctly ---
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm
    # --- end new ---
    list_display = ('email', 'user_type', 'is_staff', 'date_joined')
    list_filter = ('user_type', 'is_staff', 'is_superuser')
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'profile_picture')}),
        ('Permissions', {
            'fields': ('user_type', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'user_type', 'is_staff', 'is_superuser'),
        }),
    )
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('-date_joined',)
    
    # Add custom URL for user detail view
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:user_id>/details/', self.admin_site.admin_view(self.user_detail_view), 
            name='user-details'),
        ]
        return custom_urls + urls
    
    def user_detail_view(self, request, user_id):
        user = CustomUser.objects.get(id=user_id)
        context = {
            'user': user,
            'opts': self.model._meta,
            'title': f'User Details - {user.email}',
        }
        return render(request, 'admin/user_detail.html', context)

admin.site.register(CustomUser, CustomUserAdmin)


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("image_preview", "title", "is_active", "order", "created_at")
    list_display_links = ("image_preview", "title")
    list_editable = ("is_active", "order")
    list_filter = ("is_active", "created_at")
    search_fields = ("title", "subtitle")
    ordering = ("order",)
    actions = ["make_active", "make_inactive"]
    
    fieldsets = (
        (None, {
            'fields': ('title', 'subtitle', 'link')
        }),
        ('Image', {
            'fields': ('image', 'image_preview')
        }),
        ('Settings', {
            'fields': ('is_active', 'order')
        }),
    )
    
    readonly_fields = ('image_preview',)
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 100px; max-width: 200px;" />', obj.image.url)
        return "No Image"
    image_preview.short_description = 'Preview'
    
    def make_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} banners activated successfully.', messages.SUCCESS)
    make_active.short_description = "Activate selected banners"
    
    def make_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} banners deactivated successfully.', messages.SUCCESS)
    make_inactive.short_description = "Deactivate selected banners"
    
    # Add custom URL for banner management
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('banner-management/', self.admin_site.admin_view(self.banner_management_view), 
                 name='banner-management'),
        ]
        return custom_urls + urls
    
    def banner_management_view(self, request):
        # Get all banners
        banners = Banner.objects.all().order_by('order')
        
        # Handle form submission for reordering
        if request.method == 'POST' and 'reorder' in request.POST:
            try:
                new_order = request.POST.getlist('banner_order[]')
                for i, banner_id in enumerate(new_order):
                    Banner.objects.filter(id=banner_id).update(order=i)
                messages.success(request, 'Banner order updated successfully!')
                return redirect('admin:banner-management')
            except Exception as e:
                messages.error(request, f'Error updating order: {str(e)}')
        
        context = {
            'title': 'Banner Management',
            'banners': banners,
            'opts': self.model._meta,
            **self.admin_site.each_context(request),
        }
        return render(request, 'banner_management.html', context)
    
# Add this to your existing admin.py file (after the Banner admin section)

from django.contrib import messages
from .models import Brand

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("logo_preview", "name", "is_active", "order", "created_at")
    list_display_links = ("logo_preview", "name")
    list_editable = ("is_active", "order")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "description")
    ordering = ("order", "name")
    actions = ["make_active", "make_inactive"]
    
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'website')
        }),
        ('Logo', {
            'fields': ('logo', 'logo_preview')
        }),
        ('Settings', {
            'fields': ('is_active', 'order')
        }),
    )
    
    readonly_fields = ('logo_preview',)
    
    def logo_preview(self, obj):
        if obj.logo:
            return format_html('<img src="{}" style="max-height: 100px; max-width: 200px;" />', obj.logo.url)
        return "No Logo"
    logo_preview.short_description = 'Preview'
    
    def make_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} brands activated successfully.', messages.SUCCESS)
    make_active.short_description = "Activate selected brands"
    
    def make_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} brands deactivated successfully.', messages.SUCCESS)
    make_inactive.short_description = "Deactivate selected brands"   



    from django.contrib import admin
from .models import CustomProduct, EditedAPIProduct

@admin.register(CustomProduct)
class CustomProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'is_active', 'is_bestseller', 'bestseller_order', 'created_at')
    list_editable = ('is_active', 'is_bestseller', 'bestseller_order')
    list_filter = ('is_active', 'is_bestseller', 'category', 'brand')
    search_fields = ('name', 'brand', 'company')
    ordering = ('bestseller_order', 'name')
    
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'price', 'main_image')
        }),
        ('Product Details', {
            'fields': ('company', 'brand', 'category', 'unit', 'product', 'stock_quantity')
        }),
        ('Bestseller Settings', {
            'fields': ('is_bestseller', 'bestseller_order'),
            'description': 'Set bestseller status and order in slider'
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )

@admin.register(EditedAPIProduct)  
class EditedAPIProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'original_code', 'price', 'is_active', 'is_bestseller', 'bestseller_order')
    list_editable = ('is_active', 'is_bestseller', 'bestseller_order')
    list_filter = ('is_active', 'is_bestseller', 'category', 'brand')
    search_fields = ('name', 'original_code', 'brand', 'company')
    ordering = ('bestseller_order', 'name')
    
    fieldsets = (
        (None, {
            'fields': ('original_code', 'name', 'price', 'original_price', 'image')
        }),
        ('Product Details', {
            'fields': ('product', 'category', 'unit', 'tax_code', 'company', 'brand', 'text6')
        }),
        ('Bestseller Settings', {
            'fields': ('is_bestseller', 'bestseller_order'),
            'description': 'Set bestseller status and order in slider'
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    ) 

    # Add these imports to your existing admin.py
from .models import Category

# Add this admin class to your existing admin.py
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("image_preview", "name","online_name", "product_count", "is_active", "order", "created_at")
    list_display_links = ("image_preview", "name")
    list_editable = ("is_active", "order")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "description")
    ordering = ("order", "name")
    actions = ["make_active", "make_inactive"]
    
    fieldsets = (
        (None, {
            'fields': ('name', 'online_name','description')
        }),
        ('Image', {
            'fields': ('image', 'image_url', 'image_preview')
        }),
        ('Settings', {
            'fields': ('is_active', 'order')
        }),
    )
    
    readonly_fields = ('image_preview',)
    
    def product_count(self, obj):
        """Display product count for this category"""
        count = obj.product_count()
        if count > 0:
            return format_html('<span style="color: #059669; font-weight: 600;">{}</span>', count)
        return format_html('<span style="color: #64748b;">0</span>')
    product_count.short_description = 'Products'
    
    def image_preview(self, obj):
        image_url = obj.get_image_url()
        if image_url:
            return format_html('<img src="{}" style="max-height: 60px; max-width: 120px;" />', image_url)
        return "No Image"
    image_preview.short_description = 'Image Preview'
    
    def make_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} categories activated successfully.', messages.SUCCESS)
    make_active.short_description = "Activate selected categories"
    
    def make_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} categories deactivated successfully.', messages.SUCCESS)
    make_inactive.short_description = "Deactivate selected categories"