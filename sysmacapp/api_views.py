import threading
from decimal import Decimal

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import (
    CustomUser, CustomProduct, Category, Banner, Brand,
    EditedAPIProduct, Wishlist, CartItem, DealOfTheDay, Order, OrderItem,
    SysmacProduct, ProductBatch, SysmacProductType, SysmacProductBrand,
    SysmacProductPhoto,
)
from .serializers import (
    MyTokenObtainPairSerializer, SignupSerializer, UserSerializer,
    CategorySerializer, BannerSerializer, BrandSerializer, OrderSerializer,
)

# ── Product listing comes straight from the DB (acc_product /
# acc_productbatch, synced by the external sync tool) instead of
# https://api.sysmac.in/api/product/. See _fetch_api_products() and
# _fetch_api_products_page() below.
#
# NOTE: NO FILTERING is applied here anymore — every row in acc_product /
# acc_productbatch is returned as-is, regardless of its `settings` value
# or its `product`/category field. Whatever is in the table is what shows
# up on the storefront.
#
# NOTE 2: Bestseller badges and discount ("% OFF") badges are intentionally
# disabled at this layer. `is_bestseller` is always sent as False, and
# `original_price` is always mirrored to equal `price` (rather than the
# synced `bmrp` value), so the frontend's own discount-comparison logic
# (`original_price > price`) never evaluates true. This keeps the
# storefront showing exactly what's coming from the sync tool with no
# manual/computed merchandising flags layered on top.

FULL_CATALOGUE_CACHE_KEY = "sysmac_full_catalogue"
FULL_CATALOGUE_CACHE_TTL = 600  # 10 minutes — DB catalogue doesn't change every second


class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer


@api_view(['POST'])
@permission_classes([AllowAny])
def signup(request):
    serializer = SignupSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(UserSerializer(request.user).data)


def _build_price_map(codes=None):
    """
    Returns {code: {'price': Decimal, 'original_price': Decimal}} sourced
    from acc_productbatch (ProductBatch.salesprice / .bmrp). No settings
    filter applied — every batch row is considered.

    If a product has multiple batch rows, the highest-slno (most recently
    synced) row wins.
    """
    qs = ProductBatch.objects.all()
    if codes is not None:
        qs = qs.filter(productcode__in=codes)

    price_map = {}
    for batch in qs.order_by('productcode', 'slno'):
        price_map[batch.productcode] = {
            'price': batch.salesprice or Decimal('0'),
            'original_price': batch.bmrp or Decimal('0'),
        }
    return price_map


def _sysmac_product_to_dict(p, price_map):
    """
    Shapes one SysmacProduct row (+ its matching ProductBatch pricing) into
    the same dict shape the old https://api.sysmac.in/api/product/ response
    used to return.
    """
    pricing = price_map.get(p.code, {})
    return {
        'code': p.code,
        'name': p.name or 'Unknown Product',
        'price': float(pricing.get('price') or 0),
        'original_price': float(pricing.get('original_price') or 0),
        'product': p.product or '',
        'category': p.sub_category or '',
        'brand': p.brand or '',
        'company': p.company or '',
        'unit': p.unit or '',
        'image': '',
    }


def _fetch_api_products(force_refresh=False):
    """
    Returns the FULL product catalogue read straight from acc_product
    (joined with acc_productbatch for pricing). No settings filter
    applied — every row in the table is included.
    """
    if not force_refresh:
        cached = cache.get(FULL_CATALOGUE_CACHE_KEY)
        if cached is not None:
            return cached

    products_qs = SysmacProduct.objects.all()
    codes = list(products_qs.values_list('code', flat=True))
    price_map = _build_price_map(codes)

    all_results = [_sysmac_product_to_dict(p, price_map) for p in products_qs]

    cache.set(FULL_CATALOGUE_CACHE_KEY, all_results, FULL_CATALOGUE_CACHE_TTL)
    return all_results


def _fetch_api_products_page(page=1, page_size=50):
    """
    Paginated version, DB-backed, no filtering. Mirrors the old HTTP call's
    ?page=N contract: returns (results, count, num_pages).
    """
    products_qs = SysmacProduct.objects.all().order_by('code')

    paginator = Paginator(products_qs, page_size)
    if page < 1:
        page = 1
    if paginator.num_pages and page > paginator.num_pages:
        page = paginator.num_pages
    page_obj = paginator.get_page(page) if paginator.num_pages else paginator.get_page(1)

    codes = [p.code for p in page_obj.object_list]
    price_map = _build_price_map(codes)

    results = [_sysmac_product_to_dict(p, price_map) for p in page_obj.object_list]
    return results, paginator.count, paginator.num_pages


SYSMAC_BRANDS_CACHE_KEY = "sysmac_brands_list"
SYSMAC_PRODUCT_TYPES_CACHE_KEY = "sysmac_product_types_list"
SYSMAC_LOOKUP_CACHE_TTL = 600  # 10 minutes, same as the full product catalogue


def _fetch_sysmac_brands(force_refresh=False):
    """
    Brand list, DB-backed from acc_productbrand (SysmacProductBrand,
    synced by the external sync tool) instead of
    https://api.sysmac.in/api/productbrand/.

    No filter applied — every row currently in acc_productbrand is
    returned as-is.
    """
    if not force_refresh:
        cached = cache.get(SYSMAC_BRANDS_CACHE_KEY)
        if cached is not None:
            return cached

    qs = SysmacProductBrand.objects.all()

    result = [
        {'name': b.name, 'url': b.url}
        for b in qs
    ]

    cache.set(SYSMAC_BRANDS_CACHE_KEY, result, SYSMAC_LOOKUP_CACHE_TTL)
    return result


def _fetch_sysmac_product_types(force_refresh=False):
    """
    Product-type / category list, DB-backed from acc_productproduct
    (SysmacProductType, synced by the external sync tool) instead of
    https://api.sysmac.in/api/productproduct/.

    No filter applied — every row currently in acc_productproduct is
    returned as-is.
    """
    if not force_refresh:
        cached = cache.get(SYSMAC_PRODUCT_TYPES_CACHE_KEY)
        if cached is not None:
            return cached

    qs = SysmacProductType.objects.all()

    result = [
        {'name': pt.name, 'url': pt.url}
        for pt in qs
    ]

    cache.set(SYSMAC_PRODUCT_TYPES_CACHE_KEY, result, SYSMAC_LOOKUP_CACHE_TTL)
    return result


def _valid_category_codes(force_refresh=False):
    """
    Set of category codes that exist in acc_productproduct
    (SysmacProductType). A product's `category` is only ever taken from
    this table now — never straight from acc_product.product and never
    from the old https://api.sysmac.in/api/productproduct/ HTTP call.
    """
    return {
        item.get('name')
        for item in _fetch_sysmac_product_types(force_refresh)
        if item.get('name')
    }


def _resolve_category(raw_code, valid_categories):
    """
    Resolve a product's category against acc_productproduct: only treat
    the code on the product row as a category if it's actually a known
    row in that table, otherwise leave it blank (caller falls back to
    'General').
    """
    code = (raw_code or '').strip()
    return code if code in valid_categories else ''


def _valid_brand_codes(force_refresh=False):
    """
    Set of brand codes that exist in acc_productbrand (SysmacProductBrand).
    A product's `brand` is only ever taken from this table now — never
    straight from acc_product.brand and never from the old
    https://api.sysmac.in/api/productbrand/ HTTP call.
    """
    return {
        item.get('name')
        for item in _fetch_sysmac_brands(force_refresh)
        if item.get('name')
    }


def _resolve_brand(raw_code, valid_brands):
    """
    Resolve a product's brand against acc_productbrand: only treat the
    code on the product row as a brand if it's actually a known row in
    that table, otherwise leave it blank (caller falls back to 'SYSMAC').
    """
    code = (raw_code or '').strip()
    return code if code in valid_brands else ''


SYSMAC_PHOTOS_RAW_CACHE_KEY = "sysmac_photos_raw"
SYSMAC_PHOTOS_BY_CODE_CACHE_KEY = "sysmac_photos_by_code"


def _fetch_sysmac_photos(force_refresh=False):
    """
    Photo rows, DB-backed from acc_productphoto (SysmacProductPhoto,
    synced by the external sync tool) instead of
    https://api.sysmac.in/api/productphoto/.

    No filter applied — every row currently in acc_productphoto is
    returned as-is (matches the sync tool's own note that this table has
    no WHERE condition).
    """
    if not force_refresh:
        cached = cache.get(SYSMAC_PHOTOS_RAW_CACHE_KEY)
        if cached is not None:
            return cached

    qs = SysmacProductPhoto.objects.all()

    result = [
        {'code': row.code, 'url2': row.url2}
        for row in qs
    ]

    cache.set(SYSMAC_PHOTOS_RAW_CACHE_KEY, result, SYSMAC_LOOKUP_CACHE_TTL)
    return result


def _sysmac_photo_url(url2):
    """
    url2 (from SysmacProductPhoto, synced from acc_productphoto) is
    already a complete, ready-to-use image URL, e.g.
    https://cloud.sysmac.in/images/<uuid>.jpg — sourced straight from
    your own SysmacProductPhoto model, not any external API.
    Just return it as-is — no reconstruction needed.
    """
    if not url2:
        return ''
    return url2.strip()


def _rebuild_photos_by_code(force_refresh=False):
    raw = _fetch_sysmac_photos(force_refresh)
    grouped = {}
    for row in raw:
        code = str(row.get('code', '')).strip()
        if not code:
            continue
        url = _sysmac_photo_url(row.get('url2', ''))
        if not url:
            continue
        grouped.setdefault(code, []).append(url)

    result = {}
    for code, urls in grouped.items():
        thumb_idx = next((i for i, u in enumerate(urls) if 'thumb' in u.lower()), 0)
        result[code] = {
            'thumbnail': urls[thumb_idx],
            'details': [u for i, u in enumerate(urls) if i != thumb_idx],
            'all': urls,
        }

    cache.set(SYSMAC_PHOTOS_BY_CODE_CACHE_KEY, result, SYSMAC_LOOKUP_CACHE_TTL)
    return result


_photos_warming_lock = threading.Lock()
_photos_warming = False


def _warm_photos_cache_async():
    global _photos_warming
    with _photos_warming_lock:
        if _photos_warming:
            return
        _photos_warming = True

    def _worker():
        global _photos_warming
        try:
            _rebuild_photos_by_code(force_refresh=False)
        except Exception:
            pass
        finally:
            with _photos_warming_lock:
                _photos_warming = False

    threading.Thread(target=_worker, daemon=True).start()


def _photos_by_code(force_refresh=False, block=False):
    if not force_refresh:
        cached = cache.get(SYSMAC_PHOTOS_BY_CODE_CACHE_KEY)
        if cached is not None:
            return cached

    if not block:
        _warm_photos_cache_async()
        return {}

    return _rebuild_photos_by_code(force_refresh)


def _abs(request, url):
    if url and url.startswith('/'):
        return request.build_absolute_uri(url)
    return url


def _to_decimal(v, default='0'):
    try:
        s = str(v).strip()
        return Decimal(s) if s != '' else Decimal(default)
    except Exception:
        return Decimal(default)


def _to_int(v, default=0):
    try:
        s = str(v).strip()
        return int(float(s)) if s != '' else default
    except Exception:
        return default


def _to_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    return str(v).lower() in ('true', '1', 'on', 'yes')


def build_product_list(request):
    """
    No category filtering — every active Sysmac product and active custom
    product is included, regardless of whether its category/product type
    matches any Category row.

    `category` and `brand` are resolved against acc_productproduct
    (SysmacProductType) and acc_productbrand (SysmacProductBrand) via
    _resolve_category() / _resolve_brand() — neither is taken as-is from
    acc_product.product / acc_product.brand anymore.

    Bestseller and discount badges are disabled here: `is_bestseller` is
    always False and `original_price` always mirrors `price`, regardless
    of any EditedAPIProduct override or synced bmrp value.
    """
    api_products = _fetch_api_products()
    edited_map = {p.original_code: p for p in EditedAPIProduct.objects.all()}
    photos_map = _photos_by_code()
    valid_categories = _valid_category_codes()
    valid_brands = _valid_brand_codes()
    out = []

    for p in api_products:
        code = str(p.get('code', ''))
        edited = edited_map.get(code)
        is_active = edited.is_active if edited else True
        if not is_active:
            continue

        photos = photos_map.get(code)
        image = ''
        if edited and edited.image:
            image = _abs(request, edited.image.url)
        elif photos:
            image = photos['thumbnail']
        elif p.get('image'):
            image = p.get('image')

        item_price = float(edited.price) if (edited and edited.price) else float(p.get('price') or 0)

        out.append({
            'id': code, 'code': code,
            'name': (edited.name if edited else None) or p.get('name', 'Unknown Product'),
            'price': item_price,
            'original_price': item_price,
            'category': (edited.product if edited else None)
                        or _resolve_category(p.get('product', ''), valid_categories)
                        or 'General',
            'brand': (edited.brand if edited else None)
                     or _resolve_brand(p.get('brand', ''), valid_brands)
                     or 'SYSMAC',
            'company': (edited.company if edited else None) or p.get('company', '') or 'SYSMAC',
            'image': image, 'type': 'sysmac',
            'is_bestseller': False,
        })

    for cp in CustomProduct.objects.filter(is_active=True):
        out.append({
            'id': str(cp.id), 'code': str(cp.id),
            'name': cp.name, 'price': float(cp.price),
            'original_price': float(cp.price),
            'category': cp.category or 'General',
            'brand': cp.brand or 'SYSMAC',
            'company': cp.company or 'SYSMAC',
            'image': _abs(request, cp.main_image.url) if cp.main_image else '',
            'type': 'custom', 'is_bestseller': False,
        })
    return out


def _build_product_dict(request, p, edited, photos_map=None, valid_categories=None, valid_brands=None):
    """
    Bestseller and discount badges are disabled here too: `is_bestseller`
    is always False and `original_price` always mirrors `price`.
    """
    code = str(p.get('code', ''))
    photos = (photos_map or {}).get(code)
    image = ''
    if edited and edited.image:
        image = _abs(request, edited.image.url)
    elif photos:
        image = photos['thumbnail']
    elif p.get('image'):
        image = p.get('image')

    if valid_categories is None:
        valid_categories = _valid_category_codes()
    if valid_brands is None:
        valid_brands = _valid_brand_codes()

    item_price = float(edited.price) if (edited and edited.price) else float(p.get('price') or 0)

    return {
        'id': code, 'code': code,
        'name': (edited.name if edited else None) or p.get('name', 'Unknown Product'),
        'price': item_price,
        'original_price': item_price,
        'category': (edited.product if edited else None)
                    or _resolve_category(p.get('product', ''), valid_categories)
                    or 'General',
        'brand': (edited.brand if edited else None)
                 or _resolve_brand(p.get('brand', ''), valid_brands)
                 or 'SYSMAC',
        'company': (edited.company if edited else None) or p.get('company', '') or 'SYSMAC',
        'image': image, 'type': 'sysmac',
        'is_bestseller': False,
    }


@api_view(['GET'])
@permission_classes([AllowAny])
def products(request):
    """
    Storefront product listing. No category or settings filtering — every
    row in acc_product (joined with acc_productbatch for pricing) is
    included, subject only to explicit search/category/brand/sort query
    params and per-item is_active from EditedAPIProduct (if set).

    Bestseller and discount badges are disabled — see _build_product_dict
    and build_product_list.
    """
    page_param = request.GET.get('page')

    # ── Legacy mode: full catalogue in one go ──
    if page_param is None:
        data = build_product_list(request)

        search = request.GET.get('search', '').lower()
        if search:
            data = [p for p in data if search in p['name'].lower()
                    or search in p['brand'].lower() or search in p['category'].lower()]

        category = request.GET.get('category', 'all')
        if category != 'all':
            data = [p for p in data if p['category'].lower() == category.lower()]

        brand = request.GET.get('brand', 'all')
        if brand != 'all':
            data = [p for p in data if p['brand'].lower() == brand.lower()]

        sort = request.GET.get('sort', 'all')
        if sort == 'price_low_high':
            data.sort(key=lambda x: x['price'])
        elif sort == 'price_high_low':
            data.sort(key=lambda x: x['price'], reverse=True)

        return Response({'count': len(data), 'results': data})

    # ── Paginated mode: one page (~50 items) per request ──
    page = _to_int(page_param, default=1)
    if page < 1:
        page = 1

    raw_results, count, num_pages = _fetch_api_products_page(page)

    codes = [str(p.get('code', '')) for p in raw_results]
    edited_map = {
        e.original_code: e
        for e in EditedAPIProduct.objects.filter(original_code__in=codes)
    }
    photos_map = _photos_by_code()
    valid_categories = _valid_category_codes()
    valid_brands = _valid_brand_codes()

    data = []
    for p in raw_results:
        code = str(p.get('code', ''))
        edited = edited_map.get(code)
        is_active = edited.is_active if edited else True
        if not is_active:
            continue

        data.append(_build_product_dict(request, p, edited, photos_map, valid_categories, valid_brands))

    # Custom (manually added) products only need to ride along on page 1
    if page == 1:
        for cp in CustomProduct.objects.filter(is_active=True):
            data.append({
                'id': str(cp.id), 'code': str(cp.id),
                'name': cp.name, 'price': float(cp.price),
                'original_price': float(cp.price),
                'category': cp.category or 'General',
                'brand': cp.brand or 'SYSMAC',
                'company': cp.company or 'SYSMAC',
                'image': _abs(request, cp.main_image.url) if cp.main_image else '',
                'type': 'custom', 'is_bestseller': False,
            })

    # Optional filters still work in paginated mode, applied to the
    # single page's worth of data
    search = request.GET.get('search', '').lower()
    if search:
        data = [p for p in data if search in p['name'].lower()
                or search in p['brand'].lower() or search in p['category'].lower()]

    category = request.GET.get('category', 'all')
    if category != 'all':
        data = [p for p in data if p['category'].lower() == category.lower()]

    brand = request.GET.get('brand', 'all')
    if brand != 'all':
        data = [p for p in data if p['brand'].lower() == brand.lower()]

    sort = request.GET.get('sort', 'all')
    if sort == 'price_low_high':
        data.sort(key=lambda x: x['price'])
    elif sort == 'price_high_low':
        data.sort(key=lambda x: x['price'], reverse=True)

    return Response({
        'count': count,
        'num_pages': num_pages,
        'page': page,
        'results': data,
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def product_detail(request, product_identifier):
    if str(product_identifier).isdigit():
        try:
            cp = CustomProduct.objects.get(id=int(product_identifier))
            return Response({
                'id': str(cp.id), 'code': str(cp.id), 'name': cp.name,
                'description': cp.description or '', 'price': float(cp.price),
                'category': cp.category or '', 'brand': cp.brand or '',
                'company': cp.company or '', 'unit': cp.unit or '',
                'image': _abs(request, cp.main_image.url) if cp.main_image else '',
                'images': [_abs(request, i.image.url) for i in cp.additional_images.all()],
                'type': 'custom',
            })
        except CustomProduct.DoesNotExist:
            pass

    ap = next((p for p in _fetch_api_products() if str(p.get('code')) == str(product_identifier)), None)
    if not ap:
        return Response({'detail': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        edited = EditedAPIProduct.objects.get(original_code=str(product_identifier))
    except EditedAPIProduct.DoesNotExist:
        edited = None

    code = str(ap.get('code'))
    photos = _photos_by_code().get(code)
    valid_categories = _valid_category_codes()
    valid_brands = _valid_brand_codes()

    image = ''
    if edited and edited.image:
        image = _abs(request, edited.image.url)
    elif photos:
        image = photos['thumbnail']
    elif ap.get('image'):
        image = ap.get('image')

    if edited and edited.additional_images.exists():
        images = [_abs(request, i.image.url) for i in edited.additional_images.all()]
    elif photos:
        images = photos['details']
    else:
        images = []

    return Response({
        'id': str(ap.get('code')), 'code': str(ap.get('code')),
        'name': (edited.name if edited else None) or ap.get('name', 'Unknown Product'),
        'description': '', 'unit': ap.get('unit', ''),
        'price': float(edited.price) if (edited and edited.price) else float(ap.get('price') or 0),
        'original_price': float(ap.get('original_price') or 0),
        'category': (edited.product if edited else None)
                    or _resolve_category(ap.get('product', ''), valid_categories),
        'brand': (edited.brand if edited else None)
                 or _resolve_brand(ap.get('brand', ''), valid_brands),
        'company': (edited.company if edited else None) or ap.get('company', ''),
        'image': image,
        'images': images,
        'type': 'sysmac',
    })


def _product_dict_by_code(request, code):
    ap = next((p for p in _fetch_api_products() if str(p.get('code')) == str(code)), None)
    if not ap:
        return None
    try:
        edited = EditedAPIProduct.objects.get(original_code=str(code))
    except EditedAPIProduct.DoesNotExist:
        edited = None
    return _build_product_dict(request, ap, edited, _photos_by_code())


@api_view(['GET'])
@permission_classes([AllowAny])
def product_photos(request, code):
    photos = _photos_by_code().get(str(code))
    if not photos:
        return Response({'code': str(code), 'thumbnail': '', 'images': []})
    return Response({'code': str(code), 'thumbnail': photos['thumbnail'], 'images': photos['details']})


@api_view(['GET'])
@permission_classes([AllowAny])
def categories(request):
    qs = Category.objects.filter(is_active=True).order_by('order', 'name')
    return Response(CategorySerializer(qs, many=True, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def banners(request):
    qs = Banner.objects.filter(is_active=True).order_by('order')
    return Response(BannerSerializer(qs, many=True, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def brands(request):
    qs = Brand.objects.filter(is_active=True).order_by('order', 'name')
    return Response(BrandSerializer(qs, many=True, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def sysmac_brands(request):
    raw = _fetch_sysmac_brands()
    result = []
    for b in raw:
        name = (b.get('name') or '').strip()
        if not name:
            continue
        result.append({
            'name': name,
            'website': b.get('url'),
        })
    return Response({'count': len(result), 'results': result})


@api_view(['GET'])
@permission_classes([AllowAny])
def sysmac_product_types(request):
    raw = _fetch_sysmac_product_types()
    result = []
    for item in raw:
        name = (item.get('name') or '').strip()
        if not name:
            continue
        result.append({
            'name': name,
            'website': item.get('url'),
        })
    return Response({'count': len(result), 'results': result})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def cart(request):
    items = request.user.cart_items.select_related('product').all()
    result = []
    total = Decimal('0.00')

    api_products = {str(p.get('code')): p for p in _fetch_api_products()}
    edited_map = {p.original_code: p for p in EditedAPIProduct.objects.all()}
    photos_map = _photos_by_code()

    for it in items:
        price = it.get_price
        total += price * it.quantity

        image = ''
        if it.product:
            if it.product.main_image:
                image = _abs(request, it.product.main_image.url)
        else:
            code = str(it.api_product_code)
            edited = edited_map.get(code)
            photos = photos_map.get(code)
            if edited and edited.image:
                image = _abs(request, edited.image.url)
            elif photos:
                image = photos['thumbnail']
            else:
                ap = api_products.get(code)
                if ap and ap.get('image'):
                    image = ap.get('image')

        result.append({
            'id': it.id,
            'name': it.get_name,
            'price': float(price),
            'quantity': it.quantity,
            'line_total': float(price * it.quantity),
            'image': image,
            'is_custom': bool(it.product),
            'product_id': it.product.id if it.product else None,
            'api_product_code': it.api_product_code,
        })

    delivery = Decimal('0.00') if total >= Decimal('500.00') else Decimal('40.00')
    return Response({
        'items': result,
        'count': items.count(),
        'total_price': float(total),
        'delivery_charge': float(delivery),
        'grand_total': float(total + delivery),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_to_cart(request):
    is_custom = request.data.get('is_custom', False)
    if is_custom:
        try:
            product = CustomProduct.objects.get(id=request.data.get('product_id'))
        except CustomProduct.DoesNotExist:
            return Response({'detail': 'Product not found'}, status=404)
        item, created = CartItem.objects.get_or_create(
            user=request.user, product=product, defaults={'quantity': 1})
    else:
        code = str(request.data.get('api_product_code'))
        ap = next((p for p in _fetch_api_products() if str(p.get('code')) == code), None)
        if not ap:
            return Response({'detail': 'Product not found'}, status=404)
        item, created = CartItem.objects.get_or_create(
            user=request.user, api_product_code=code,
            defaults={'api_product_name': ap.get('name', ''),
                      'api_product_price': Decimal(str(ap.get('price', 0))), 'quantity': 1})
    if not created:
        item.quantity += 1
        item.save()
    return Response({'success': True, 'cart_count': request.user.cart_items.count(),
                     'quantity': item.quantity})


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_cart_item(request, item_id):
    try:
        item = CartItem.objects.get(user=request.user, id=item_id)
    except CartItem.DoesNotExist:
        return Response({'detail': 'Item not found'}, status=404)

    qty = _to_int(request.data.get('quantity', item.quantity), default=item.quantity)
    if qty < 1:
        return Response({'detail': 'Quantity must be at least 1'}, status=400)

    item.quantity = qty
    item.save()
    return Response({'success': True, 'quantity': item.quantity})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_from_cart(request, item_id):
    CartItem.objects.filter(user=request.user, id=item_id).delete()
    return Response({'success': True, 'cart_count': request.user.cart_items.count()})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def wishlist(request):
    items = Wishlist.objects.filter(user=request.user)
    result = []

    api_products = {str(p.get('code')): p for p in _fetch_api_products()}
    edited_map = {p.original_code: p for p in EditedAPIProduct.objects.all()}
    photos_map = _photos_by_code()

    for it in items:
        if it.product:
            cp = it.product
            result.append({
                'id': it.id, 'name': cp.name, 'price': float(cp.price),
                'image': _abs(request, cp.main_image.url) if cp.main_image else '',
                'is_custom': True, 'product_id': cp.id, 'api_product_code': None,
            })
        else:
            code = str(it.api_product_code)
            edited = edited_map.get(code)
            ap = api_products.get(code)
            photos = photos_map.get(code)

            name = (edited.name if edited else None) or (ap.get('name') if ap else None) or f'Product {code}'
            price = (
                float(edited.price) if (edited and edited.price)
                else float(ap.get('price') or 0) if ap else None
            )
            if edited and edited.image:
                image = _abs(request, edited.image.url)
            elif photos:
                image = photos['thumbnail']
            elif ap and ap.get('image'):
                image = ap.get('image')
            else:
                image = ''

            result.append({
                'id': it.id, 'name': name, 'price': price, 'image': image,
                'is_custom': False, 'product_id': None, 'api_product_code': code,
            })
    return Response({'items': result, 'count': items.count()})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_wishlist(request):
    is_custom = request.data.get('is_custom', False)
    if is_custom:
        try:
            product = CustomProduct.objects.get(id=request.data.get('product_id'))
        except CustomProduct.DoesNotExist:
            return Response({'detail': 'Product not found'}, status=404)
        qs = Wishlist.objects.filter(user=request.user, product=product)
        if qs.exists():
            qs.delete()
            return Response({'success': True, 'added': False})
        Wishlist.objects.create(user=request.user, product=product)
        return Response({'success': True, 'added': True})
    else:
        code = str(request.data.get('api_product_code'))
        qs = Wishlist.objects.filter(user=request.user, api_product_code=code)
        if qs.exists():
            qs.delete()
            return Response({'success': True, 'added': False})
        Wishlist.objects.create(user=request.user, api_product_code=code)
        return Response({'success': True, 'added': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def wishlist_count(request):
    return Response({'count': Wishlist.objects.filter(user=request.user).count()})


def _is_admin(user):
    return user.is_authenticated and (user.is_superuser or user.user_type == 'admin')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_users(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    users = CustomUser.objects.all().order_by('-date_joined')
    return Response(UserSerializer(users, many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_toggle_user(request, user_id):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    try:
        u = CustomUser.objects.get(id=user_id)
        u.is_active = not u.is_active
        u.save()
        return Response({'success': True, 'is_active': u.is_active})
    except CustomUser.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_stats(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    api_prods = _fetch_api_products()

    total_sales = Decimal('0.00')
    for ci in CartItem.objects.all():
        total_sales += ci.get_price * ci.quantity

    return Response({
        'api_product_count': len(api_prods),
        'custom_product_count': CustomProduct.objects.filter(is_active=True).count(),
        'edited_api_product_count': EditedAPIProduct.objects.count(),
        'total_product_count': len(api_prods) + CustomProduct.objects.filter(is_active=True).count(),
        'total_users': CustomUser.objects.count(),
        'active_users': CustomUser.objects.filter(is_active=True).count(),
        'total_sales': float(total_sales),
        'total_purchase': 0.00,
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def admin_banners(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)

    if request.method == 'GET':
        qs = Banner.objects.all().order_by('order')
        return Response(BannerSerializer(qs, many=True, context={'request': request}).data)

    b = Banner(
        title=request.data.get('title', ''),
        subtitle=request.data.get('subtitle', ''),
        link=request.data.get('link', '') or None,
        is_active=_to_bool(request.data.get('is_active', True), default=True),
        order=_to_int(request.data.get('order', 0)),
    )
    if 'image' in request.FILES:
        b.image = request.FILES['image']
    b.save()
    return Response(BannerSerializer(b, context={'request': request}).data, status=201)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def admin_banner_update(request, pk):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    try:
        b = Banner.objects.get(pk=pk)
    except Banner.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)
    b.title = request.data.get('title', b.title)
    b.subtitle = request.data.get('subtitle', b.subtitle)
    b.link = request.data.get('link', b.link) or None
    if 'is_active' in request.data:
        b.is_active = _to_bool(request.data['is_active'], default=True)
    if 'order' in request.data:
        b.order = _to_int(request.data['order'])
    if 'image' in request.FILES:
        b.image = request.FILES['image']
    b.save()
    return Response(BannerSerializer(b, context={'request': request}).data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def admin_banner_delete(request, pk):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    Banner.objects.filter(pk=pk).delete()
    return Response({'success': True})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def admin_brands(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)

    if request.method == 'GET':
        qs = Brand.objects.all().order_by('order', 'name')
        return Response(BrandSerializer(qs, many=True, context={'request': request}).data)

    name = request.data.get('name', '').strip()
    if not name:
        return Response({'detail': 'Brand name is required'}, status=400)

    b = Brand(
        name=name,
        website=request.data.get('website', '') or None,
        description=request.data.get('description', ''),
        is_active=_to_bool(request.data.get('is_active', '1'), default=True),
        order=_to_int(request.data.get('order', 0)),
        image_url=request.data.get('image_url', '') or None,
    )
    if 'logo' in request.FILES:
        b.logo = request.FILES['logo']
    try:
        b.save()
    except Exception as e:
        return Response({'detail': str(e)}, status=400)
    return Response(BrandSerializer(b, context={'request': request}).data, status=201)


@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def admin_brand_update(request, pk):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    try:
        b = Brand.objects.get(pk=pk)
    except Brand.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    if request.method == 'GET':
        return Response(BrandSerializer(b, context={'request': request}).data)

    if 'name' in request.data:
        name = request.data['name'].strip()
        if not name:
            return Response({'detail': 'Brand name is required'}, status=400)
        b.name = name
    if 'website' in request.data:
        b.website = request.data['website'] or None
    if 'description' in request.data:
        b.description = request.data['description']
    if 'is_active' in request.data:
        b.is_active = _to_bool(request.data['is_active'], default=True)
    if 'order' in request.data:
        b.order = _to_int(request.data['order'])

    logo = request.FILES.get('logo')
    image_url = request.data.get('image_url', '')

    if logo:
        if b.logo:
            try:
                from django.core.files.storage import default_storage
                default_storage.delete(b.logo.path)
            except Exception:
                pass
        b.logo = logo
        b.image_url = None
    elif image_url:
        if b.logo:
            try:
                from django.core.files.storage import default_storage
                default_storage.delete(b.logo.path)
            except Exception:
                pass
            b.logo = None
        b.image_url = image_url or None

    try:
        b.save()
    except Exception as e:
        return Response({'detail': str(e)}, status=400)
    return Response(BrandSerializer(b, context={'request': request}).data)


@api_view(['DELETE', 'POST'])
@permission_classes([IsAuthenticated])
def admin_brand_delete(request, pk):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    try:
        b = Brand.objects.get(pk=pk)
    except Brand.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)
    if b.logo:
        try:
            from django.core.files.storage import default_storage
            default_storage.delete(b.logo.path)
        except Exception:
            pass
    b.delete()
    return Response({'success': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_category_create(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    c = Category(
        name=request.data.get('name', ''),
        online_name=request.data.get('online_name', '') or None,
        description=request.data.get('description', ''),
        is_active=_to_bool(request.data.get('is_active', True), default=True),
        order=_to_int(request.data.get('order', 0)),
        image_url=request.data.get('image_url', '') or None,
    )
    if 'image' in request.FILES:
        c.image = request.FILES['image']
    c.save()
    return Response(CategorySerializer(c, context={'request': request}).data, status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_categories_all(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    qs = Category.objects.all().order_by('order', 'name')
    return Response(CategorySerializer(qs, many=True, context={'request': request}).data)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def admin_category_update(request, pk):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    try:
        c = Category.objects.get(pk=pk)
    except Category.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)
    c.online_name = request.data.get('online_name', c.online_name) or None
    c.description = request.data.get('description', c.description)
    if 'is_active' in request.data:
        c.is_active = _to_bool(request.data['is_active'], default=True)
    if 'order' in request.data:
        c.order = _to_int(request.data['order'])
    if 'image_url' in request.data:
        c.image_url = request.data['image_url'] or None
    if 'image' in request.FILES:
        c.image = request.FILES['image']
    c.save()
    return Response(CategorySerializer(c, context={'request': request}).data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def admin_category_delete(request, pk):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    Category.objects.filter(pk=pk).delete()
    return Response({'success': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_custom_products(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    qs = CustomProduct.objects.all().order_by('-created_at')
    data = []
    for p in qs:
        data.append({
            'id': p.id, 'name': p.name, 'price': float(p.price),
            'category': p.category or '', 'brand': p.brand or '',
            'company': p.company or '', 'unit': p.unit or '',
            'product': p.product or '', 'description': p.description or '',
            'stock_quantity': p.stock_quantity, 'is_active': p.is_active,
            'is_bestseller': p.is_bestseller, 'bestseller_order': p.bestseller_order,
            'image': _abs(request, p.main_image.url) if p.main_image else '',
        })
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_custom_product_create(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    try:
        p = CustomProduct(
            name=request.data.get('name', ''),
            price=_to_decimal(request.data.get('price', 0)),
            category=request.data.get('category', '') or '',
            brand=request.data.get('brand', '') or '',
            company=request.data.get('company', '') or '',
            unit=request.data.get('unit', '') or '',
            product=request.data.get('product', '') or '',
            description=request.data.get('description', '') or '',
            stock_quantity=_to_int(request.data.get('stock_quantity', 0)),
            is_active=_to_bool(request.data.get('is_active', True), True),
            is_bestseller=_to_bool(request.data.get('is_bestseller', False)),
            bestseller_order=_to_int(request.data.get('bestseller_order', 0)),
        )
        if 'main_image' in request.FILES:
            p.main_image = request.FILES['main_image']
        p.save()
        return Response({'id': p.id, 'name': p.name}, status=201)
    except Exception as e:
        return Response({'detail': str(e)}, status=400)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def admin_custom_product_update(request, pk):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    try:
        p = CustomProduct.objects.get(pk=pk)
    except CustomProduct.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)
    try:
        for field in ['name', 'category', 'brand', 'company', 'unit', 'product', 'description']:
            if field in request.data:
                setattr(p, field, request.data[field] or '')
        if 'price' in request.data:
            p.price = _to_decimal(request.data['price'])
        if 'stock_quantity' in request.data:
            p.stock_quantity = _to_int(request.data['stock_quantity'])
        if 'bestseller_order' in request.data:
            p.bestseller_order = _to_int(request.data['bestseller_order'])
        if 'is_active' in request.data:
            p.is_active = _to_bool(request.data['is_active'], True)
        if 'is_bestseller' in request.data:
            p.is_bestseller = _to_bool(request.data['is_bestseller'])
        if 'main_image' in request.FILES:
            p.main_image = request.FILES['main_image']
        p.save()
        return Response({'success': True, 'id': p.id})
    except Exception as e:
        return Response({'detail': str(e)}, status=400)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def admin_custom_product_delete(request, pk):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    CustomProduct.objects.filter(pk=pk).delete()
    return Response({'success': True})


# ══════════════════════════════════════════════════════════════════════════
# ── Admin Sysmac products (per-variant / per-barcode rows) ──────────────
#
# ProductBatch (acc_productbatch) can have MULTIPLE rows for the same
# productcode — each row is a distinct variant/barcode with its own
# salesprice/bmrp. The admin table needs to show every one of those rows
# individually (one table row per barcode), not collapse them down to a
# single "last batch wins" price like the storefront does.
#
# _fetch_all_product_batches() and _build_admin_sysmac_variant_rows() are
# ADDITIVE — they don't replace _build_price_map()/_fetch_api_products(),
# which are still used everywhere else (storefront products(), cart,
# wishlist, deals, orders, etc.) exactly as before.
# ══════════════════════════════════════════════════════════════════════════

ADMIN_SYSMAC_ROWS_CACHE_KEY = "admin_sysmac_variant_rows"
ADMIN_SYSMAC_ROWS_CACHE_TTL = 600  # 10 minutes, same as the rest of the sync-tool cache


def _fetch_all_product_batches():
    """
    Unlike _build_price_map (which keeps only the last/most-recent batch
    row per productcode), this keeps EVERY batch row — each one is a
    distinct variant/barcode with its own salesprice.

    Returns: {productcode: [ {slno, barcode, price, original_price}, ... ]}
    """
    qs = ProductBatch.objects.all().order_by('productcode', 'slno')
    grouped = {}
    for b in qs:
        grouped.setdefault(b.productcode, []).append({
            'slno': b.slno,
            'barcode': (b.barcode or '').strip(),
            'price': b.salesprice or Decimal('0'),
            'original_price': b.bmrp or Decimal('0'),
        })
    return grouped


def _build_admin_sysmac_variant_rows(request, force_refresh=False):
    """
    Admin Sysmac Products table data: one row per ProductBatch (i.e. per
    barcode/variant), not one row per product code. A product code with
    3 batch rows (3 barcodes) produces 3 rows here, each with its own
    price looked up against that specific barcode.

    Products with no batch rows at all still get a single placeholder row
    (price 0, blank barcode) so they aren't silently dropped from the
    admin list.

    EditedAPIProduct overrides are keyed by product code (original_code),
    so a manual edit (name/brand/price override/active/bestseller) still
    applies to ALL variant rows of that code — same as before.
    """
    if not force_refresh:
        cached = cache.get(ADMIN_SYSMAC_ROWS_CACHE_KEY)
        if cached is not None:
            return cached

    products_qs = SysmacProduct.objects.all().order_by('code')
    batches_map = _fetch_all_product_batches()
    edited_map = {e.original_code: e for e in EditedAPIProduct.objects.all()}
    photos_map = _photos_by_code()

    rows = []
    for p in products_qs:
        code = p.code
        edited = edited_map.get(code)
        photos = photos_map.get(code)

        if edited and edited.image:
            image = _abs(request, edited.image.url)
        elif photos:
            image = photos['thumbnail']
        else:
            image = ''

        variants = batches_map.get(code) or [
            {'slno': None, 'barcode': '', 'price': Decimal('0'), 'original_price': Decimal('0')}
        ]

        for v in variants:
            rows.append({
                'row_id': f"{code}::{v['barcode'] or v['slno'] or '0'}",
                'code': code,
                'barcode': v['barcode'],
                'name': p.name or 'Unknown Product',
                'edited_name': edited.name if edited else None,
                'product': p.product or '',
                'edited_product': edited.product if edited else None,
                'category': p.sub_category or '',
                'edited_category': edited.category if edited else None,
                'brand': p.brand or '',
                'edited_brand': edited.brand if edited else None,
                'company': p.company or '',
                'edited_company': edited.company if edited else None,
                'price': float(v['price']),
                'edited_price': float(edited.price) if (edited and edited.price) else None,
                'original_price': float(v['original_price']),
                'image': image,
                'is_active': edited.is_active if edited else True,
                'is_bestseller': edited.is_bestseller if edited else False,
                'is_edited': edited is not None,
            })

    cache.set(ADMIN_SYSMAC_ROWS_CACHE_KEY, rows, ADMIN_SYSMAC_ROWS_CACHE_TTL)
    return rows


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_sysmac_products(request):
    """
    Returns one row PER BARCODE/VARIANT (via _build_admin_sysmac_variant_rows),
    paginated 50 rows per page. A product code with multiple ProductBatch
    rows now appears multiple times here — once per barcode — each with
    its own price, instead of collapsing to a single "last batch wins" row.
    """
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)

    page = _to_int(request.GET.get('page', 1), default=1)
    if page < 1:
        page = 1

    all_rows = _build_admin_sysmac_variant_rows(request)

    paginator = Paginator(all_rows, 50)
    page_obj = paginator.get_page(page) if paginator.num_pages else paginator.get_page(1)

    return Response({
        'results': list(page_obj.object_list),
        'count': paginator.count,
        'num_pages': paginator.num_pages,
        'page': page,
    })


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def admin_sysmac_product_update(request, code):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    edited, _ = EditedAPIProduct.objects.get_or_create(
        original_code=str(code),
        defaults={'name': request.data.get('name', code)}
    )
    for field in ['name', 'product', 'brand', 'company', 'category', 'unit']:
        if field in request.data:
            setattr(edited, field, request.data[field])
    if 'price' in request.data:
        edited.price = _to_decimal(request.data['price'])
    if 'bestseller_order' in request.data:
        edited.bestseller_order = _to_int(request.data['bestseller_order'])
    if 'is_active' in request.data:
        edited.is_active = _to_bool(request.data['is_active'], default=True)
    if 'is_bestseller' in request.data:
        edited.is_bestseller = _to_bool(request.data['is_bestseller'])
    if 'image' in request.FILES:
        edited.image = request.FILES['image']
    edited.save()
    # Bust the admin variant-rows cache so the edit (name/price/brand/
    # active/bestseller override) shows up immediately instead of waiting
    # up to ADMIN_SYSMAC_ROWS_CACHE_TTL seconds for it to expire on its own.
    cache.delete(ADMIN_SYSMAC_ROWS_CACHE_KEY)
    return Response({'success': True})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def admin_sysmac_product_delete(request, code):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    EditedAPIProduct.objects.filter(original_code=str(code)).delete()
    # Same cache-busting reasoning as admin_sysmac_product_update above.
    cache.delete(ADMIN_SYSMAC_ROWS_CACHE_KEY)
    return Response({'success': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_sysmac_brands(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)

    raw = _fetch_sysmac_brands()
    result = []
    for b in raw:
        name = (b.get('name') or '').strip()
        if not name:
            continue
        result.append({
            'name': name,
            'website': b.get('url'),
        })

    return Response({'count': len(result), 'results': result})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_sysmac_categories(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)

    raw = _fetch_sysmac_product_types()
    result = []
    for item in raw:
        name = (item.get('name') or '').strip()
        if not name:
            continue
        result.append({
            'name': name,
            'website': item.get('url'),
        })

    return Response({'count': len(result), 'results': result})


def _parse_deal_datetime(raw):
    if not raw:
        return None
    dt = parse_datetime(raw)
    if not dt:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def admin_deals(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)

    if request.method == 'POST':
        code = str(request.data.get('product_code', '')).strip()
        start_at = _parse_deal_datetime(request.data.get('start_at'))
        end_at = _parse_deal_datetime(request.data.get('end_at'))

        if not code:
            return Response({'detail': 'product_code is required'}, status=400)
        if not start_at or not end_at:
            return Response({'detail': 'start_at and end_at must be valid datetimes'}, status=400)
        if end_at <= start_at:
            return Response({'detail': 'End time must be after start time'}, status=400)
        if not _product_dict_by_code(request, code):
            return Response({'detail': 'Product not found'}, status=404)

        deal = DealOfTheDay.objects.create(
            product_code=code, start_at=start_at, end_at=end_at,
            created_by=request.user,
        )
        return Response({'success': True, 'id': deal.id}, status=status.HTTP_201_CREATED)

    result = []
    for d in DealOfTheDay.objects.all():
        result.append({
            'id': d.id,
            'product_code': d.product_code,
            'product': _product_dict_by_code(request, d.product_code),
            'start_at': d.start_at,
            'end_at': d.end_at,
            'is_active': d.is_active,
            'status': d.status,
        })
    return Response({'results': result})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def admin_deal_delete(request, pk):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    DealOfTheDay.objects.filter(pk=pk).delete()
    return Response({'success': True})


@api_view(['GET'])
@permission_classes([AllowAny])
def deals(request):
    now = timezone.now()
    live = DealOfTheDay.objects.filter(is_active=True, start_at__lte=now, end_at__gt=now)

    result = []
    for d in live:
        product = _product_dict_by_code(request, d.product_code)
        if not product:
            continue
        result.append({'id': d.id, 'end_at': d.end_at, **product})

    return Response({'results': result})


def _resolve_order_product(request, item):
    quantity = _to_int(item.get('quantity', 1), default=1)
    if quantity < 1:
        quantity = 1

    if item.get('is_custom'):
        try:
            product = CustomProduct.objects.get(id=item.get('product_id'))
        except CustomProduct.DoesNotExist:
            return None
        return {
            'product': product, 'api_product_code': None,
            'name': product.name, 'price': product.price, 'quantity': quantity,
        }

    code = str(item.get('api_product_code', ''))
    pd = _product_dict_by_code(request, code)
    if not pd:
        return None
    return {
        'product': None, 'api_product_code': code,
        'name': pd['name'], 'price': Decimal(str(pd['price'])), 'quantity': quantity,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_customer_search(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    q = (request.GET.get('q') or '').strip()
    if not q:
        return Response({'results': []})
    users = CustomUser.objects.filter(
        Q(email__icontains=q) | Q(phone__icontains=q), is_superuser=False
    )[:10]
    return Response({'results': UserSerializer(users, many=True).data})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def admin_orders(request):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)

    if request.method == 'POST':
        try:
            customer = CustomUser.objects.get(id=request.data.get('user_id'), is_superuser=False)
        except CustomUser.DoesNotExist:
            return Response(
                {'detail': 'Customer account not found — they need to sign up before an order can be created'},
                status=404,
            )

        contact_phone = str(request.data.get('contact_phone', '')).strip() or customer.phone
        if not contact_phone:
            return Response({'detail': 'contact_phone is required'}, status=400)

        raw_items = request.data.get('items') or []
        if not raw_items:
            return Response({'detail': 'At least one item is required'}, status=400)

        resolved = []
        for raw in raw_items:
            r = _resolve_order_product(request, raw)
            if not r:
                return Response({'detail': f'Product not found: {raw}'}, status=404)
            resolved.append(r)

        order = Order.objects.create(
            user=customer, contact_phone=contact_phone,
            notes=request.data.get('notes', ''), created_by=request.user,
        )
        for r in resolved:
            OrderItem.objects.create(order=order, **r)

        return Response(
            OrderSerializer(order, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    qs = Order.objects.select_related('user').prefetch_related('items').all()
    status_filter = request.GET.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)
    return Response({'results': OrderSerializer(qs, many=True, context={'request': request}).data})


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def admin_order_status_update(request, pk):
    if not _is_admin(request.user):
        return Response({'detail': 'Forbidden'}, status=403)
    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    new_status = request.data.get('status')
    if new_status not in ('confirmed', 'delivered'):
        return Response({'detail': "status must be 'confirmed' or 'delivered'"}, status=400)
    if new_status == 'delivered' and order.status not in ('confirmed', 'delivered'):
        return Response({'detail': 'Order must be confirmed before it can be marked delivered'}, status=400)

    order.status = new_status
    if new_status == 'confirmed' and not order.confirmed_at:
        order.confirmed_at = timezone.now()
    if new_status == 'delivered' and not order.delivered_at:
        order.delivered_at = timezone.now()
    order.save()
    return Response(OrderSerializer(order, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_orders(request):
    qs = request.user.orders.prefetch_related('items').all()
    return Response({'results': OrderSerializer(qs, many=True, context={'request': request}).data})