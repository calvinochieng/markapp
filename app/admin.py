# admin.py
from django.contrib import admin
from django.urls import path
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django import forms
from django.contrib import messages
from django.db.models import Sum, Count
from .models import Staff, Vehicle, Delivery, LoaderAssignment, MonthlyPayment, PayrollManager
import csv
from io import StringIO
import calendar
from decimal import Decimal

admin.site.site_header = "Delivery Management System"
admin.site.site_title = "Delivery Management"
admin.site.index_title = "Administration"

class LoaderAssignmentInline(admin.TabularInline):
    model = LoaderAssignment
    extra = 1
    autocomplete_fields = ['loader']

@admin.register(PayrollManager)
class PayrollManagerAdmin(admin.ModelAdmin):
    list_display = ('staff', 'delivery', 'turnboy_pay', 'loader_pay', 'total_pay', 'date_recorded')

@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ('date', 'vehicle', 'driver', 'turnboy', 'destination', 'loading_amount', 'loader_count')
    list_filter = ('date', 'vehicle', 'driver', 'turnboy', 'destination')
    search_fields = ('destination', 'items_carried', 'driver__name', 'turnboy__name')
    date_hierarchy = 'date'
    inlines = [LoaderAssignmentInline]
    autocomplete_fields = ['driver', 'turnboy', 'vehicle']
    
    def loader_count(self, obj):
        return obj.loaderassignment_set.count()
    loader_count.short_description = 'Number of Loaders'
    
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Additional validation could be added here if needed

@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'is_loader', 'is_active', 'date_joined')
    list_filter = ('role', 'is_loader', 'is_active')
    search_fields = ('name', 'phone_number')
    actions = ['calculate_monthly_payment']
    
    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        return queryset, use_distinct
    
    def calculate_monthly_payment(self, request, queryset):
        """Admin action to calculate monthly payments for selected staff"""
        class MonthYearForm(forms.Form):
            year = forms.IntegerField(min_value=2000, max_value=2100)
            month = forms.ChoiceField(choices=[(i, calendar.month_name[i]) for i in range(1, 13)])
        
        if 'apply' in request.POST:
            form = MonthYearForm(request.POST)
            if form.is_valid():
                year = form.cleaned_data['year']
                month = int(form.cleaned_data['month'])
                
                for staff in queryset:
                    # Calculate payment
                    payment = staff.get_monthly_payment(year, month)
                    
                    # Save as MonthlyPayment record
                    MonthlyPayment.objects.update_or_create(
                        staff=staff,
                        year=year,
                        month=month,
                        defaults={
                            'total_payment': payment,
                            'turnboy_payment': Decimal('200.00') * Delivery.objects.filter(
                                turnboy=staff,
                                date__year=year,
                                date__month=month
                            ).count() if staff.role == 'turnboy' else Decimal('0.00'),
                            'loader_payment': payment - (Decimal('200.00') * Delivery.objects.filter(
                                turnboy=staff,
                                date__year=year,
                                date__month=month
                            ).count() if staff.role == 'turnboy' else Decimal('0.00')),
                        }
                    )
                
                messages.success(request, f"Successfully calculated payments for {queryset.count()} staff members")
                return redirect('..')
        else:
            form = MonthYearForm()
        
        return render(
            request,
            "admin/calculate_monthly_payment.html",
            context={"staff": queryset, "form": form, "title": "Calculate Monthly Payment"}
        )
    calculate_monthly_payment.short_description = "Calculate monthly payment for selected staff"

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'vehicle_type', 'capacity', 'is_active')
    list_filter = ('vehicle_type', 'is_active')
    search_fields = ('plate_number',)

@admin.register(MonthlyPayment)
class MonthlyPaymentAdmin(admin.ModelAdmin):
    list_display = ('staff', 'get_month_year', 'turnboy_payment', 'loader_payment', 'total_payment', 'is_paid')
    list_filter = ('year', 'month', 'is_paid', 'staff__role')
    search_fields = ('staff__name',)
    actions = ['export_csv', 'mark_as_paid']
    date_hierarchy = 'payment_date'
    
    def get_month_year(self, obj):
        return f"{calendar.month_name[obj.month]} {obj.year}"
    get_month_year.short_description = "Month/Year"
    
    def export_csv(self, request, queryset):
        """Export selected payments as CSV"""
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Staff Name', 'Role', 'Month', 'Year', 'Turnboy Payment', 'Loader Payment', 'Total Payment', 'Is Paid'])
        
        for payment in queryset:
            writer.writerow([
                payment.staff.name,
                payment.staff.get_role_display(),
                calendar.month_name[payment.month],
                payment.year,
                payment.turnboy_payment,
                payment.loader_payment,
                payment.total_payment,
                'Yes' if payment.is_paid else 'No'
            ])
        
        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=monthly_payments.csv'
        return response
    export_csv.short_description = "Export selected payments to CSV"
    
    def mark_as_paid(self, request, queryset):
        """Mark selected payments as paid"""
        queryset.update(is_paid=True, payment_date=timezone.now().date())
        messages.success(request, f"{queryset.count()} payments marked as paid")
    mark_as_paid.short_description = "Mark selected payments as paid"
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('payment-summary/', self.admin_site.admin_view(self.payment_summary_view), name='payment-summary'),
        ]
        return custom_urls + urls
    
    def payment_summary_view(self, request):
        """View to display payment summary by month"""
        class YearMonthForm(forms.Form):
            year = forms.IntegerField(min_value=2000, max_value=2100, initial=timezone.now().year)
            month = forms.ChoiceField(choices=[(i, calendar.month_name[i]) for i in range(1, 13)], 
                                     initial=timezone.now().month)
        
        if request.method == 'POST':
            form = YearMonthForm(request.POST)
            if form.is_valid():
                year = form.cleaned_data['year']
                month = int(form.cleaned_data['month'])
            else:
                year = timezone.now().year
                month = timezone.now().month
        else:
            form = YearMonthForm()
            year = timezone.now().year
            month = timezone.now().month
        
        # Get payments for the selected month
        payments = MonthlyPayment.objects.filter(year=year, month=month)
        
        # Get summary statistics
        total_paid = payments.filter(is_paid=True).aggregate(Sum('total_payment'))['total_payment__sum'] or 0
        total_unpaid = payments.filter(is_paid=False).aggregate(Sum('total_payment'))['total_payment__sum'] or 0
        total_turnboy = payments.aggregate(Sum('turnboy_payment'))['turnboy_payment__sum'] or 0
        total_loader = payments.aggregate(Sum('loader_payment'))['loader_payment__sum'] or 0
        
        context = {
            'title': f"Payment Summary for {calendar.month_name[month]} {year}",
            'form': form,
            'payments': payments,
            'stats': {
                'total_paid': total_paid,
                'total_unpaid': total_unpaid,
                'total_turnboy': total_turnboy,
                'total_loader': total_loader,
                'total': total_paid + total_unpaid,
            },
            'month_name': calendar.month_name[month],
            'year': year,
        }
        
        return render(request, 'admin/payment_summary.html', context)
