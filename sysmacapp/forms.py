from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, CustomProduct, EditedAPIProduct  # Added EditedAPIProduct import


# forms.py - Add this at the top of your file
from django.forms import ClearableFileInput, MultipleHiddenInput
from django.utils.translation import ngettext

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

    def __init__(self, attrs=None):
        default_attrs = {'multiple': True}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs)

    def value_from_datadict(self, data, files, name):
        if hasattr(files, 'getlist'):
            return files.getlist(name)
        return None


class CustomUserCreationForm(UserCreationForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(max_length=254, required=True, help_text='Required. Enter a valid email address.')

    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'email', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if CustomUser.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already in use.")
        return email

class CustomProductForm(forms.ModelForm):
    class Meta:
        model = CustomProduct
        fields = ['name', 'company', 'brand', 'category', 'price', 'unit', 'product', 'description', 'main_image', 'stock_quantity', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter product name',
                'required': True
            }),
            'company': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter company name'
            }),
            'brand': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter brand name'
            }),
            'category': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter category'
            }),
            'unit': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter unit (e.g., kg, pcs, ltr)'
            }),
            'product': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter product type'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Enter product description'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00',
                'required': True
            }),
            'stock_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'placeholder': '0'
            }),
            'main_image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = True
        self.fields['price'].required = True
        self.fields['price'].help_text = 'Enter price in decimal format (e.g., 99.99)'
        self.fields['stock_quantity'].help_text = 'Enter available quantity'


class EditedAPIProductForm(forms.ModelForm):
    class Meta:
        model = EditedAPIProduct
        fields = ['name', 'product', 'category', 'unit', 'tax_code', 'company', 
                 'brand', 'text6', 'price', 'original_price', 'image']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter product name',
                'required': True
            }),
            'product': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter product type'
            }),
            'category': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter category'
            }),
            'unit': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter unit (e.g., kg, pcs, ltr)'
            }),
            'tax_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter tax code'
            }),
            'company': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter company name'
            }),
            'brand': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter brand name'
            }),
            'text6': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter additional info'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00',
                'required': True
            }),
            'original_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            })
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = True
        self.fields['price'].required = True
        self.fields['price'].help_text = 'Enter price in decimal format (e.g., 99.99)'



from django import forms
from .models import Product

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'name', 'product_type', 'category', 'unit', 'tax_code',
            'company', 'brand', 'text6', 'price', 'original_price', 'is_active'
        ]






# forms.py - Modify your existing forms

from django import forms
from .models import ProductImage

# forms.py - Update your BaseProductForm
class BaseProductForm:
    additional_images = forms.FileField(
        widget=MultipleFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*'
        }),
        required=False,
        label='Additional Images'
    )

    def save_additional_images(self, product):
        """Handle saving additional images"""
        if 'additional_images' in self.files:
            for image in self.files.getlist('additional_images'):
                if image:  # Only save if there's actually a file
                    if isinstance(product, CustomProduct):
                        ProductImage.objects.create(custom_product=product, image=image)
                    else:
                        ProductImage.objects.create(api_product=product, image=image)

class  CustomProductForm(forms.ModelForm):
    class Meta:
        model = CustomProduct
        fields = ['name', 'company', 'brand', 'category', 'price', 
                 'unit', 'product', 'description', 'main_image', 
                 'stock_quantity', 'is_active']
        
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter product name',
                'required': True
            }),
            # ... keep your other widgets as they were ...
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = True
        self.fields['price'].required = True
        self.fields['price'].help_text = 'Enter price in decimal format (e.g., 99.99)'
        self.fields['stock_quantity'].help_text = 'Enter available quantity'

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            BaseProductForm.save_additional_images(self, instance)
        return instance

class EditedAPIProductForm(forms.ModelForm):
    class Meta:
        model = EditedAPIProduct
        fields = ['name', 'product', 'category', 'unit', 'tax_code', 
                 'company', 'brand', 'text6', 'price', 'original_price', 'image']
        
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter product name',
                'required': True
            }),
            # ... keep your other widgets as they were ...
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = True
        self.fields['price'].required = True
        self.fields['price'].help_text = 'Enter price in decimal format (e.g., 99.99)'

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            BaseProductForm.save_additional_images(self, instance)
        return instance
    

    # Update your existing CustomProductForm
class CustomProductForm(forms.ModelForm):
    class Meta:
        model = CustomProduct
        fields = [
            'name', 'description', 'price', 'main_image', 'company', 
            'brand', 'category', 'unit', 'product', 'stock_quantity',
            'is_bestseller', 'bestseller_order', 'is_active'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'is_bestseller': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'bestseller_order': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'help_text': 'Lower numbers appear first in slider'
            }),
        }

# Update your existing EditedAPIProductForm
class EditedAPIProductForm(forms.ModelForm):
    class Meta:
        model = EditedAPIProduct
        fields = [
            'name', 'product', 'category', 'unit', 'tax_code', 
            'company', 'brand', 'text6', 'price', 'original_price',
            'image', 'is_bestseller', 'bestseller_order', 'is_active'
        ]
        widgets = {
            'is_bestseller': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'bestseller_order': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'help_text': 'Lower numbers appear first in slider'
            }),
        }


        # Add these imports to your existing forms.py
from .models import Category

# Add this form class to your forms.py
class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'online_name', 'description', 'image', 'image_url', 'is_active', 'order']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter category name',
                'required': True
            }),
            'online_name': forms.TextInput(attrs={   # <-- new
                'class': 'form-control',
                'placeholder': 'Enter online display name (optional)'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Enter category description (optional)'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'image_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://example.com/image.jpg (optional)'
            }),
            'order': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'placeholder': '0'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = True
        self.fields['name'].help_text = 'Enter a unique category name'
        self.fields['order'].help_text = 'Lower numbers appear first (0 = top)'
        self.fields['image_url'].help_text = 'Use this if you prefer to use an image URL instead of uploading'

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if name:
            # Check for uniqueness (case-insensitive)
            existing = Category.objects.filter(name__iexact=name)
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise forms.ValidationError("A category with this name already exists.")
        return name
    
    def clean_online_name(self):
        """If supplied, must be unique (case-insensitive) unless we are editing the same row."""
        online = self.cleaned_data.get('online_name')
        if online:
            qs = Category.objects.filter(online_name__iexact=online)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("This online name is already in use.")
        return online

    def clean(self):
        cleaned_data = super().clean()
        image = cleaned_data.get('image')
        image_url = cleaned_data.get('image_url')
        
        # At least one image source should be provided
        if not image and not image_url:
            raise forms.ValidationError("Please provide either an image file or an image URL.")
        
        return cleaned_data