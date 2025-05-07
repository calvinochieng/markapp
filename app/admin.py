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
    list_display = ('delivery_date', 'vehicle_info', 'display_driver', 'display_turnboys', 
                   'destination', 'loading_amount', 'loader_count', 'display_loading_payments')
    list_filter = ('date', 'vehicle')
    search_fields = ('destination', 'items_carried', 'vehicle__plate_number', 'vehicle__driver')
    date_hierarchy = 'date'
    inlines = [StaffAssignmentInline]
    autocomplete_fields = ['vehicle']
    readonly_fields = ('display_payment_details',)
    list_per_page = 20
    
    fieldsets = (
        ('Delivery Information', {
            'fields': ('date', 'vehicle', 'destination')
        }),
        ('Financial Information', {
            'fields': ('loading_amount', 'turnboy_payment_rate', 'display_payment_details')
        }),
        ('Details', {
            'fields': ('items_carried', 'notes', 'delivery_note_image')
        }),
    )
    
    def delivery_date(self, obj):
        """Format date in a more readable format"""
        return format_html(
            '<span style="white-space:nowrap;">{}</span>', 
            obj.date.strftime('%d %b %Y')
        )
    delivery_date.admin_order_field = 'date'
    delivery_date.short_description = 'Date'
    
    def vehicle_info(self, obj):
        return format_html(
            '<span style="font-weight:bold;">{}</span><br><span style="color:#666;">{} - {}</span>',
            obj.vehicle.plate_number,
            obj.vehicle.get_vehicle_type_display(),
            obj.vehicle.capacity
        )
    vehicle_info.short_description = 'Vehicle'
    vehicle_info.admin_order_field = 'vehicle__plate_number'
    
    def display_driver(self, obj):
        return obj.vehicle.driver or "No driver"
    display_driver.short_description = 'Driver'
    
    def display_turnboys(self, obj):
        turnboys = StaffAssignment.objects.filter(delivery=obj, role='turnboy')
        if not turnboys:
            return format_html('<span style="color:#999;">None</span>')
        
        # Show turnboy names and indicate if they're loading
        turnboy_info = []
        for t in turnboys:
            loading_status = ' <span style="color:green;">✓</span>' if t.helped_loading else ''
            turnboy_info.append(f"{t.staff.name}{loading_status}")
        
        return format_html(", ".join(turnboy_info))
    display_turnboys.short_description = 'Turnboys'
    
    def loader_count(self, obj):
        # Count staff who helped with loading
        return obj.staffassignment_set.filter(helped_loading=True).count()
    loader_count.short_description = 'Total Loaders'
    
    def display_loading_payments(self, obj):
        if not obj.id:
            return "N/A"
            
        loaders = obj.staffassignment_set.filter(helped_loading=True)
        if not loaders:
            return format_html('<span style="color:#999;">No loaders</span>')
            
        loader_count = loaders.count()
        per_loader = obj.loading_amount / loader_count if loader_count > 0 else 0
        
        return format_html(
            '<span style="white-space:nowrap;">Ksh {:.2f}</span> per loader ({})',
            per_loader, loader_count
        )
    display_loading_payments.short_description = 'Loading Payments'
    
    def display_payment_details(self, obj):
        """Display payment details for this delivery"""
        if not obj.id:
            return "Save delivery first to see payment details"
            
        html = "<h3>Payment Details</h3>"
        html += "<table style='width:100%; border-collapse:collapse;'>"
        html += "<tr style='background-color:#f0f0f0;'>"
        html += "<th style='border:1px solid #ddd; padding:8px; text-align:left;'>Staff</th>"
        html += "<th style='border:1px solid #ddd; padding:8px; text-align:left;'>Role</th>"
        html += "<th style='border:1px solid #ddd; padding:8px; text-align:left;'>Fixed Pay</th>"
        html += "<th style='border:1px solid #ddd; padding:8px; text-align:left;'>Loading Pay</th>"
        html += "<th style='border:1px solid #ddd; padding:8px; text-align:left;'>Total Pay</th>"
        html += "</tr>"
        
        # Get PayrollManager records
        payroll_records = PayrollManager.objects.filter(delivery=obj).select_related('staff')
        
        if not payroll_records:
            html += "<tr><td colspan='5' style='border:1px solid #ddd; padding:8px;'>No payment records found</td></tr>"
        else:
            for record in payroll_records:
                html += f"<tr style='border:1px solid #ddd;'>"
                html += f"<td style='border:1px solid #ddd; padding:8px;'>{record.staff.name}</td>"
                html += f"<td style='border:1px solid #ddd; padding:8px;'>{record.staff.get_role_display()}</td>"
                html += f"<td style='border:1px solid #ddd; padding:8px;'>Ksh {record.role_pay:.2f}</td>"
                html += f"<td style='border:1px solid #ddd; padding:8px;'>Ksh {record.loader_pay:.2f}</td>"
                html += f"<td style='border:1px solid #ddd; padding:8px;'><b>Ksh {record.total_pay:.2f}</b></td>"
                html += "</tr>"
        
        html += "</table>"
        
        # Add a section for loading breakdown
        html += "<h4 style='margin-top:15px;'>Loading Payment Breakdown</h4>"
        html += "<p>Total loading amount: Ksh {:.2f}</p>".format(obj.loading_amount)
        
        total_loaders = obj.staffassignment_set.filter(helped_loading=True).count()
        if total_loaders > 0:
            per_loader = obj.loading_amount / total_loaders
            html += "<p>Per-loader payment: Ksh {:.2f} ({} helpers)</p>".format(per_loader, total_loaders)
        else:
            html += "<p>No loading helpers assigned.</p>"
        
        # Add explanation based on scenario
        loaders = obj.staffassignment_set.filter(helped_loading=True)
        turnboys = obj.staffassignment_set.filter(role='turnboy')
        loading_turnboys = turnboys.filter(helped_loading=True)
        
        html += "<h4 style='margin-top:15px;'>Applied Scenario</h4>"
        
        if turnboys.count() == 1 and loading_turnboys.count() == 1 and loaders.count() == 1:
            # Scenario 1: Single turnboy who loads
            html += "<p><b>Scenario 1:</b> Single turnboy handling loading. The turnboy receives both the "
            html += "fixed turnboy payment (Ksh {:.2f}) and the full loading amount (Ksh {:.2f}).</p>".format(
                obj.turnboy_payment_rate, obj.loading_amount
            )
        elif turnboys.count() > 1 and loading_turnboys.count() > 1:
            # Scenario 2: Multiple turnboys all loading
            html += "<p><b>Scenario 2:</b> Multiple turnboys all helping with loading. Each turnboy receives their "
            html += "fixed payment (Ksh {:.2f}) plus an equal share of the loading money (Ksh {:.2f} each).</p>".format(
                obj.turnboy_payment_rate, obj.loading_amount / loaders.count()
            )
        elif turnboys.count() > 1 and loading_turnboys.count() == 1:
            # Scenario 3: Multiple turnboys, only one loading
            html += "<p><b>Scenario 3:</b> Multiple turnboys with only one handling loading. The loading turnboy "
            html += "receives both fixed payment (Ksh {:.2f}) and loading payment (Ksh {:.2f}), ".format(
                obj.turnboy_payment_rate, obj.loading_amount / loaders.count()
            )
            html += "while non-loading turnboys only receive their fixed payment.</p>"
        elif loaders.count() > turnboys.filter(helped_loading=True).count():
            # Scenario 4: Turnboys plus other loaders
            html += "<p><b>Scenario 4:</b> Turnboys plus additional loaders. The loading amount "
            html += "(Ksh {:.2f}) is divided equally among all {} loading helpers. ".format(
                obj.loading_amount, loaders.count()
            )
            html += "Each gets Ksh {:.2f} for loading. Turnboys also receive their fixed payment.</p>".format(
                obj.loading_amount / loaders.count()
            )
        else:
            html += "<p>Custom scenario - see the payment breakdown above for details.</p>"
        
        return mark_safe(html)
    display_payment_details.short_description = 'Payment Details'
    
    # Custom actions
    actions = ['export_to_csv', 'calculate_payments']
    
    def export_to_csv(self, request, queryset):
        """Export selected deliveries to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="deliveries.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Date', 'Destination', 'Vehicle', 'Driver', 'Turnboys', 
            'Loading Amount', 'Items Carried', 'Status'
        ])
        
        for delivery in queryset:
            turnboys = ", ".join([
                t.staff.name for t in StaffAssignment.objects.filter(delivery=delivery, role='turnboy')
            ])
            
            writer.writerow([
                delivery.date,
                delivery.destination,
                delivery.vehicle.plate_number,
                delivery.vehicle.driver or 'No driver',
                turnboys,
                delivery.loading_amount,
                delivery.items_carried,
                delivery.status
            ])
        
        return response
    export_to_csv.short_description = "Export selected deliveries to CSV"
    
    def calculate_payments(self, request, queryset):
        """Force recalculation of payments for selected deliveries"""
        from django.db.models.signals import post_save
        from .models import update_payroll_manager
        
        count = 0
        for delivery in queryset:
            update_payroll_manager(Delivery, delivery)
            count += 1
        
        messages.success(request, f"Recalculated payments for {count} deliveries")
    calculate_payments.short_description = "Recalculate payments for selected deliveries"
    
    # Override to optimize queries
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('vehicle')


# Staff Admin with enhanced features
@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'is_loader', 'is_active', 'phone_number', 'date_joined', 
                   'display_payments_month', 'display_deliveries_count')
    list_filter = ('role', 'is_loader', 'is_active', 'date_joined')
    search_fields = ('name', 'phone_number')
    actions = ['calculate_monthly_payment', 'calculate_custom_period_payment', 
              'export_staff_payments_csv', 'mark_as_inactive', 'mark_as_active']
    
    fieldsets = (
        ('Staff Information', {
            'fields': ('name', 'phone_number', 'role', 'is_loader')
        }),
        ('Status', {
            'fields': ('is_active', 'date_joined'),
        }),
    )
    
    def get_queryset(self, request):
        # Annotate with payment info for current month and delivery count
        today = timezone.now().date()
        start_date = today.replace(day=1)
        _, last_day = calendar.monthrange(today.year, today.month)
        end_date = today.replace(day=last_day)
        
        return super().get_queryset(request).annotate(
            current_month_pay=Coalesce(Sum(
                'payrollmanager__total_pay',
                filter=Q(payrollmanager__delivery__date__range=(start_date, end_date))
            ), Value(0), output_field=DecimalField()),
            deliveries_count=Count('staffassignment__delivery', distinct=True)
        )
    
    def display_payments_month(self, obj):
        # Display payments for current month
        if hasattr(obj, 'current_month_pay'):
            return format_html(
                '<span style="white-space:nowrap;">Ksh {:.2f}</span>',
                obj.current_month_pay
            )
        return "Ksh 0.00"
    display_payments_month.short_description = f"Earnings ({timezone.now().strftime('%b %Y')})"
    display_payments_month.admin_order_field = 'current_month_pay'
    
    def display_deliveries_count(self, obj):
        """Display number of deliveries for this staff member"""
        if hasattr(obj, 'deliveries_count'):
            url = f"/admin/your_app/delivery/?staff={obj.id}"  # Adjust the URL to your app name
            return format_html('<a href="{}">{}</a>', url, obj.deliveries_count)
        return "0"
    display_deliveries_count.short_description = "Deliveries"
    display_deliveries_count.admin_order_field = 'deliveries_count'
    
    def calculate_monthly_payment(self, request, queryset):
        """Admin action to calculate monthly payments for selected staff"""
        class MonthYearForm(forms.Form):
            year = forms.IntegerField(min_value=2000, max_value=2100, initial=timezone.now().year)
            month = forms.ChoiceField(
                choices=[(i, calendar.month_name[i]) for i in range(1, 13)],
                initial=timezone.now().month
            )
        
        if 'apply' in request.POST:
            form = MonthYearForm(request.POST)
            if form.is_valid():
                year = form.cleaned_data['year']
                month = int(form.cleaned_data['month'])
                
                for staff in queryset:
                    # Get calculated payment from staff model
                    payment_data = staff.get_monthly_payment(year, month)
                    
                    # Save as MonthlyPayment record
                    MonthlyPayment.objects.update_or_create(
                        staff=staff,
                        year=year,
                        month=month,
                        defaults={
                            'role_payment': payment_data['role_payment'],
                            'loader_payment': payment_data['loader_payment'],
                            'total_payment': payment_data['total_payment'],
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
    
    def calculate_custom_period_payment(self, request, queryset):
        """Calculate payments for a custom date range"""
        class DateRangeForm(forms.Form):
            start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
            end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
        
        if 'apply' in request.POST:
            form = DateRangeForm(request.POST)
            if form.is_valid():
                start_date = form.cleaned_data['start_date']
                end_date = form.cleaned_data['end_date']
                
                if start_date > end_date:
                    messages.error(request, "Start date must be before end date")
                    return redirect('.')
                
                for staff in queryset:
                    # Get all payroll entries for this staff in the date range
                    payroll_entries = PayrollManager.objects.filter(
                        staff=staff,
                        delivery__date__range=(start_date, end_date)
                    )
                    
                    # Calculate totals
                    role_payment = payroll_entries.aggregate(total=Coalesce(Sum('role_pay'), Value(0), output_field=DecimalField()))['total']
                    loader_payment = payroll_entries.aggregate(total=Coalesce(Sum('loader_pay'), Value(0), output_field=DecimalField()))['total']
                    total_payment = role_payment + loader_payment
                    
                    # Create or update PaymentPeriod record
                    PaymentPeriod.objects.update_or_create(
                        staff=staff,
                        period_start=start_date,
                        period_end=end_date,
                        defaults={
                            'role_payment': role_payment,
                            'loader_payment': loader_payment,
                            'total_payment': total_payment,
                        }
                    )
                
                messages.success(request, f"Successfully calculated custom period payments for {queryset.count()} staff members")
                return redirect('..')
        else:
            form = DateRangeForm(initial={
                'start_date': timezone.now().replace(day=1).date(),
                'end_date': timezone.now().date()
            })
        
        return render(
            request,
            "admin/calculate_custom_period_payment.html",
            context={"staff": queryset, "form": form, "title": "Calculate Custom Period Payment"}
        )
    calculate_custom_period_payment.short_description = "Calculate payment for custom period"
    
    def export_staff_payments_csv(self, request, queryset):
        """Export detailed payment history for selected staff"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="staff_payment_details.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Staff Name', 'Role', 'Delivery Date', 'Destination',
            'Fixed Pay', 'Loading Pay', 'Total Pay'
        ])
        
        for staff in queryset:
            # Get all payroll entries for this staff, ordered by date
            payroll_entries = PayrollManager.objects.filter(staff=staff).select_related(
                'delivery'
            ).order_by('-delivery__date')
            
            for entry in payroll_entries:
                writer.writerow([
                    staff.name,
                    staff.get_role_display(),
                    entry.delivery.date,
                    entry.delivery.destination,
                    entry.role_pay,
                    entry.loader_pay,
                    entry.total_pay
                ])
        
        return response
    export_staff_payments_csv.short_description = "Export detailed payment history (CSV)"
    
    def mark_as_inactive(self, request, queryset):
        """Mark selected staff as inactive"""
        updated = queryset.update(is_active=False)
        messages.success(request, f"Marked {updated} staff members as inactive")
    mark_as_inactive.short_description = "Mark selected staff as inactive"
    
    def mark_as_active(self, request, queryset):
        """Mark selected staff as active"""
        updated = queryset.update(is_active=True)
        messages.success(request, f"Marked {updated} staff members as active")
    mark_as_active.short_description = "Mark selected staff as active"
    
    # Add chart view for staff earnings
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('staff-earnings-chart/', self.admin_site.admin_view(self.staff_earnings_chart_view), 
                 name='staff-earnings-chart'),
            path('staff-earnings-data/', self.admin_site.admin_view(self.staff_earnings_data), 
                 name='staff-earnings-data'),
        ]
        return custom_urls + urls
    
    def staff_earnings_chart_view(self, request):
        """View to display staff earnings chart"""
        return render(request, 'admin/staff_earnings_chart.html', {'title': 'Staff Earnings Chart'})
    
    def staff_earnings_data(self, request):
        """API endpoint to provide staff earnings data for charts"""
        # Get the top 10 earning staff for the current month
        today = timezone.now().date()
        start_date = today.replace(day=1)
        _, last_day = calendar.monthrange(today.year, today.month)
        end_date = today.replace(day=last_day)
        
        top_staff = Staff.objects.filter(is_active=True).annotate(
            earnings=Coalesce(Sum(
                'payrollmanager__total_pay',
                filter=Q(payrollmanager__delivery__date__range=(start_date, end_date))
            ), Value(0), output_field=DecimalField())
        ).order_by('-earnings')[:10]
        
        data = {
            'labels': [staff.name for staff in top_staff],
            'datasets': [{
                'label': f'Earnings for {calendar.month_name[today.month]} {today.year}',
                'data': [float(staff.earnings) for staff in top_staff],
                'backgroundColor': 'rgba(54, 162, 235, 0.5)',
                'borderColor': 'rgba(54, 162, 235, 1)',
                'borderWidth': 1
            }]
        }
        
        return JsonResponse(data)

# Vehicle Admin with enhanced features
@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'driver', 'vehicle_type', 'capacity', 'is_active', 'display_deliveries_count')
    list_filter = ('vehicle_type', 'is_active')
    search_fields = ('plate_number', 'driver')
    actions = ['mark_as_inactive', 'mark_as_active', 'export_vehicle_deliveries']
    
    fieldsets = (
        ('Vehicle Information', {
            'fields': ('plate_number', 'driver', 'vehicle_type', 'capacity')
        }),
        ('Status', {
            'fields': ('is_active',),
        }),
    )
    
    def get_queryset(self, request):
        # Annotate with delivery count
        return super().get_queryset(request).annotate(
            deliveries_count=Count('delivery')
        )
    
    def display_deliveries_count(self, obj):
        """Display number of deliveries for this vehicle"""
        if hasattr(obj, 'deliveries_count'):
            url = f"/admin/your_app/delivery/?vehicle__id__exact={obj.id}"  # Adjust URL to your app name
            return format_html('<a href="{}">{}</a>', url, obj.deliveries_count)
        return "0"
    display_deliveries_count.short_description = "Deliveries"
    display_deliveries_count.admin_order_field = 'deliveries_count'
    
    def mark_as_active(self, request, queryset):
            """Mark selected vehicles as active"""
            updated = queryset.update(is_active=True)
            messages.success(request, f"Marked {updated} vehicles as active")
    mark_as_active.short_description = "Mark selected vehicles as active"
    
    def export_vehicle_deliveries(self, request, queryset):
        """Export all deliveries for selected vehicles to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="vehicle_deliveries.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Vehicle', 'Driver', 'Date', 'Destination', 
            'Turnboys', 'Loading Amount', 'Status'
        ])
        
        for vehicle in queryset:
            deliveries = Delivery.objects.filter(vehicle=vehicle).order_by('-date')
            
            for delivery in deliveries:
                turnboys = ", ".join([
                    t.staff.name for t in StaffAssignment.objects.filter(
                        delivery=delivery, role='turnboy'
                    )
                ])
                
                writer.writerow([
                    vehicle.plate_number,
                    vehicle.driver or 'No driver',
                    delivery.date,
                    delivery.destination,
                    turnboys,
                    delivery.loading_amount,
                    delivery.status
                ])
        
        return response
    export_vehicle_deliveries.short_description = "Export delivery history for selected vehicles"
    
    # Add vehicle statistics view
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('vehicle-stats/', self.admin_site.admin_view(self.vehicle_stats_view), 
                name='vehicle-stats'),
            path('vehicle-stats-data/', self.admin_site.admin_view(self.vehicle_stats_data), 
                name='vehicle-stats-data'),
        ]
        return custom_urls + urls
    
    def vehicle_stats_view(self, request):
        """View to display vehicle statistics"""
        return render(request, 'admin/vehicle_stats.html', {'title': 'Vehicle Statistics'})
    
    def vehicle_stats_data(self, request):
        """API endpoint to provide vehicle statistics data for charts"""
        # Get the top 10 vehicles by delivery count
        today = timezone.now().date()
        thirty_days_ago = today - timedelta(days=30)
        
        top_vehicles = Vehicle.objects.filter(is_active=True).annotate(
            total_deliveries=Count('delivery'),
            recent_deliveries=Count('delivery', filter=Q(delivery__date__gte=thirty_days_ago))
        ).order_by('-total_deliveries')[:10]
        
        data = {
            'labels': [vehicle.plate_number for vehicle in top_vehicles],
            'datasets': [
                {
                    'label': 'Total Deliveries',
                    'data': [vehicle.total_deliveries for vehicle in top_vehicles],
                    'backgroundColor': 'rgba(54, 162, 235, 0.5)',
                },
                {
                    'label': 'Last 30 Days',
                    'data': [vehicle.recent_deliveries for vehicle in top_vehicles],
                    'backgroundColor': 'rgba(255, 99, 132, 0.5)',
                }
            ]
        }
        
        return JsonResponse(data)


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