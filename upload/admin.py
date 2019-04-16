# --------------------------------------------------------------------
from django.contrib import admin
from .models import Assignment, Resource, HandIn, HandInFile

# --------------------------------------------------------------------
class ResourceAdmin(admin.ModelAdmin):
    model  = Resource

    list_display = [
        'name'   ,
        'ctype'  ,
        'code'   ,
        'subcode',
        'promo'  ,
    ]

    list_filter = [
        'assignment__code'   ,
        'assignment__subcode',
        'assignment__promo'  ,
    ]

    search_fields = ['name']

    ordering = [
        'assignment__code'   ,
        'assignment__subcode',
        'assignment__promo'  ,
        'name'               ,
    ]

    def code(self, the):
        return the.assignment.code
    code.admin_order_field = 'code'
    code.short_description = 'Code'

    def subcode(self, the):
        return the.assignment.subcode
    subcode.admin_order_field = 'subcode'
    subcode.short_description = 'Subcode'

    def promo(self, the):
        return the.assignment.promo
    promo.admin_order_field = 'promo'
    promo.short_description = 'Promo'

    def has_add_permission(self, request, obj = None):
        return False

    def has_change_permission(self, request, obj = None):
        return False

# --------------------------------------------------------------------
admin.site.register(Assignment)
admin.site.register(Resource, ResourceAdmin)
