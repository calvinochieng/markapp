from django.contrib import admin
from django.urls import path
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django import forms
from django.contrib import messages
from django.db.models import Sum, Count, Q, F, Value, DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from decimal import Decimal
import calendar
import csv
import json
from datetime import timedelta
from io import StringIO
from .models import (
    Staff, Vehicle, Delivery, 
    MonthlyPayment, PayrollManager, PaymentPeriod, StaffAssignment
)

admin.site.site_header = "Delivery Management System"
admin.site.site_title = "Delivery Management"
admin.site.index_title = "Administration"

# Inline for Staff Assignments (drivers, turnboys)
class StaffAssignmentInline(admin.TabularInline):
    model = StaffAssignment
    extra = 1
    autocomplete_fields = ['staff']
    fields = ['staff', 'role', 'helped_loading']

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Filter staff to only show turnboys and loaders for assignments
        if db_field.name == "staff":
            kwargs["queryset"] = Staff.objects.filter(
                Q(role__in=['turnboy', 'loader']) & Q(is_active=True)
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# PayrollManager Admin with enhanced features
@admin.register(PayrollManager)
class PayrollManagerAdmin(admin.ModelAdmin):
    list_display = ('staff', 'delivery', 'role_pay', 'loader_pay', 'total_pay', 'date_recorded')
    list_filter = ('staff__role', 'delivery__date', 'staff__is_active')
    search_fields = ('staff__name', 'delivery__destination', 'delivery__vehicle__plate_number')
    date_hierarchy = 'date_recorded'
    readonly_fields = ('total_pay', 'staff', 'delivery', 'date_recorded')
    list_select_related = ('staff', 'delivery', 'delivery__vehicle')
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('staff', 'delivery', 'role_pay', 'loader_pay', 'total_pay')
        }),
        ('Metadata', {
            'fields': ('date_recorded',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        # Prevent direct creation as these are generated automatically
        return False
    
    def get_queryset(self, request):
        # Order by most recent first
        return super().get_queryset(request).select_related(
            'staff', 'delivery', 'delivery__vehicle'
        ).order_by('-delivery__date', 'staff__name')
    
    def has_delete_permission(self, request, obj=None):
        # Allow deletion for testing but warn in the template
        return True
    
    def save_model(self, request, obj, form, change):
        obj.total_pay = obj.role_pay + obj.loader_pay
        super().save_model(request, obj, form, change)


# Delivery Admin with enhanced features
@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_filter = ('date', 'vehicle')
    date_hierarchy = 'date'
    inlines = [StaffAssignmentInline]
    autocomplete_fields = ['vehicle']
    list_per_page = 20
    
    fieldsets = (
        ('Delivery Information', {
            'fields': ('date', 'vehicle', 'destination')
        }),
        ('Financial Information', {
            'fields': ('loading_amount', 'turnboy_payment_rate', )
        }),
        ('Details', {
            'fields': ('items_carried',  'delivery_note_image')
        }),
    )
    



# Staff Admin with enhanced features
@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'is_loader', 'is_active', 'phone_number', 'date_joined')
    list_filter = ('role', 'is_loader', 'is_active', 'date_joined')
    search_fields = ('name', 'phone_number')
    actions = [ 
              'export_staff_payments_csv', 'mark_as_inactive', 'mark_as_active']
    
    fieldsets = (
        ('Staff Information', {
            'fields': ('name','is_active',)
        }),
    )
    
    

# Vehicle Admin with enhanced features
@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'driver', 'vehicle_type', 'capacity', 'is_active')
    list_filter = ('vehicle_type', 'is_active')
    search_fields = ('plate_number', 'driver')
    
    fieldsets = (
        ('Vehicle Information', {
            'fields': ('plate_number', 'driver', 'vehicle_type', 'capacity')
        }),
        ('Status', {
            'fields': ('is_active',),
        }),
    )

# Monthly Payment Admin
@admin.register(MonthlyPayment)
class MonthlyPaymentAdmin(admin.ModelAdmin):
    list_display = ('staff_name', 'month_year', 'role_payment', 'loader_payment', 
                'total_payment', 'payment_status', 'payment_date')
    list_filter = ('is_paid', 'month', 'year', 'staff__role')
    search_fields = ('staff__name',)
    date_hierarchy = 'payment_date'
    actions = ['mark_as_paid', 'mark_as_unpaid', 'export_to_csv']
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('staff', 'year', 'month', 'role_payment', 'loader_payment', 'total_payment')
        }),
        ('Payment Status', {
            'fields': ('is_paid', 'payment_date')
        }),
    )
    
    readonly_fields = ('total_payment',)
    
    def staff_name(self, obj):
        return obj.staff.name
    staff_name.admin_order_field = 'staff__name'
    staff_name.short_description = 'Staff'
    
    def month_year(self, obj):
        return format_html(
            '<span style="white-space:nowrap;">{} {}</span>',
            calendar.month_name[obj.month], obj.year
        )
    month_year.short_description = 'Month/Year'
    
    def payment_status(self, obj):
        if obj.is_paid:
            return format_html(
                '<span style="color:green;">✓ Paid</span> on {}'.format(
                    obj.payment_date.strftime('%d %b %Y') if obj.payment_date else 'Unknown date'
                )
            )
        else:
            return format_html('<span style="color:red;">Unpaid</span>')
    payment_status.short_description = 'Status'
    
    def mark_as_paid(self, request, queryset):
        """Mark selected payments as paid"""
        queryset.update(is_paid=True, payment_date=timezone.now().date())
        messages.success(request, f"Marked {queryset.count()} payments as paid")
    mark_as_paid.short_description = "Mark selected payments as paid"
    
    def mark_as_unpaid(self, request, queryset):
        """Mark selected payments as unpaid"""
        queryset.update(is_paid=False, payment_date=None)
        messages.success(request, f"Marked {queryset.count()} payments as unpaid")
    mark_as_unpaid.short_description = "Mark selected payments as unpaid"
    
    def export_to_csv(self, request, queryset):
        """Export selected payments to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="monthly_payments.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Staff Name', 'Role', 'Month', 'Year', 'Role Payment', 
            'Loader Payment', 'Total Payment', 'Payment Status', 'Payment Date'
        ])
        
        for payment in queryset:
            writer.writerow([
                payment.staff.name,
                payment.staff.get_role_display(),
                calendar.month_name[payment.month],
                payment.year,
                payment.role_payment,
                payment.loader_payment,
                payment.total_payment,
                'Paid' if payment.is_paid else 'Unpaid',
                payment.payment_date or 'N/A'
            ])
        
        return response
    export_to_csv.short_description = "Export selected payments to CSV"


# Payment Period Admin
@admin.register(PaymentPeriod)
class PaymentPeriodAdmin(admin.ModelAdmin):
    list_display = ('staff_name', 'period_display', 'role_payment', 'loader_payment', 
                'total_payment', 'payment_status', 'payment_date')
    list_filter = ('is_paid', 'period_start', 'staff__role')
    search_fields = ('staff__name',)
    date_hierarchy = 'period_start'
    actions = ['mark_as_paid', 'mark_as_unpaid', 'export_to_csv']
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('staff', 'period_start', 'period_end', 'role_payment', 'loader_payment', 'total_payment')
        }),
        ('Payment Status', {
            'fields': ('is_paid', 'payment_date')
        }),
    )
    
    readonly_fields = ('total_payment',)
    
    def staff_name(self, obj):
        return obj.staff.name
    staff_name.admin_order_field = 'staff__name'
    staff_name.short_description = 'Staff'
    
    def period_display(self, obj):
        return obj.period_name
    period_display.short_description = 'Period'
    
    def payment_status(self, obj):
        if obj.is_paid:
            return format_html(
                '<span style="color:green;">✓ Paid</span> on {}'.format(
                    obj.payment_date.strftime('%d %b %Y') if obj.payment_date else 'Unknown date'
                )
            )
        else:
            return format_html('<span style="color:red;">Unpaid</span>')
    payment_status.short_description = 'Status'
    
    def mark_as_paid(self, request, queryset):
        """Mark selected payments as paid"""
        queryset.update(is_paid=True, payment_date=timezone.now().date())
        messages.success(request, f"Marked {queryset.count()} payments as paid")
    mark_as_paid.short_description = "Mark selected payments as paid"
    
    def mark_as_unpaid(self, request, queryset):
        """Mark selected payments as unpaid"""
        queryset.update(is_paid=False, payment_date=None)
        messages.success(request, f"Marked {queryset.count()} payments as unpaid")
    mark_as_unpaid.short_description = "Mark selected payments as unpaid"
    
    def export_to_csv(self, request, queryset):
        """Export selected payments to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="custom_period_payments.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Staff Name', 'Role', 'Period Start', 'Period End', 'Role Payment', 
            'Loader Payment', 'Total Payment', 'Payment Status', 'Payment Date'
        ])
        
        for payment in queryset:
            writer.writerow([
                payment.staff.name,
                payment.staff.get_role_display(),
                payment.period_start,
                payment.period_end,
                payment.role_payment,
                payment.loader_payment,
                payment.total_payment,
                'Paid' if payment.is_paid else 'Unpaid',
                payment.payment_date or 'N/A'
            ])
        
        return response
    export_to_csv.short_description = "Export selected payments to CSV"


# Register the StaffAssignment model (for advanced filtering and reporting)
@admin.register(StaffAssignment)
class StaffAssignmentAdmin(admin.ModelAdmin):
    list_display = ('staff_name', 'role', 'delivery_info', 'delivery_date', 'helped_loading')
    list_filter = ('role', 'helped_loading', 'delivery__date', 'staff__role')
    search_fields = ('staff__name', 'delivery__destination')
    date_hierarchy = 'delivery__date'
    
    def staff_name(self, obj):
        return obj.staff.name
    staff_name.admin_order_field = 'staff__name'
    staff_name.short_description = 'Staff'
    
    def delivery_info(self, obj):
        return f"{obj.delivery.destination} ({obj.delivery.vehicle.plate_number})"
    delivery_info.short_description = 'Delivery'
    
    def delivery_date(self, obj):
        return obj.delivery.date
    delivery_date.admin_order_field = 'delivery__date'
    delivery_date.short_description = 'Date'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('staff', 'delivery', 'delivery__vehicle')
    
    def has_add_permission(self, request):
        # Discourage direct creation - these should be managed via Delivery
        return False