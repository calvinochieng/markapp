from django.contrib import admin
from django.urls import path
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django import forms
from django.contrib import messages
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from decimal import Decimal
import calendar
import csv
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


# PayrollManager Admin
@admin.register(PayrollManager)
class PayrollManagerAdmin(admin.ModelAdmin):
    list_display = ('staff', 'delivery', 'role_pay', 'loader_pay', 'total_pay', 'date_recorded')
    list_filter = ('staff__role', 'delivery__date')
    search_fields = ('staff__name', 'delivery__destination')
    date_hierarchy = 'date_recorded'
    readonly_fields = ('total_pay', 'staff', 'delivery', 'date_recorded')
    
    def has_add_permission(self, request):
        # Prevent direct creation as these are generated automatically
        return False
    
    def get_queryset(self, request):
        # Order by most recent first
        return super().get_queryset(request).order_by('-delivery__date', 'staff__name')
    
    def has_delete_permission(self, request, obj=None):
        # Allow deletion for testing but warn in the template
        return True


# Delivery Admin
@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ('date', 'vehicle', 'display_driver', 'display_turnboys', 
                   'destination', 'loading_amount', 'loader_count', 'display_loading_payments', 'status')
    list_filter = ('date', 'vehicle', 'status', 'driver')
    search_fields = ('destination', 'items_carried')
    date_hierarchy = 'date'
    inlines = [StaffAssignmentInline]
    autocomplete_fields = ['vehicle', 'driver']
    readonly_fields = ('display_payment_details',)
    fieldsets = (
        ('Delivery Information', {
            'fields': ('date', 'time', 'vehicle', 'driver', 'destination', 'status')
        }),
        ('Financial Information', {
            'fields': ('loading_amount', 'turnboy_payment_rate', 'display_payment_details')
        }),
        ('Details', {
            'fields': ('items_carried', 'notes', 'delivery_note_image')
        }),
    )
    
    def display_driver(self, obj):
        return obj.driver.name if obj.driver else "No driver"
    display_driver.short_description = 'Driver'
    
    def display_turnboys(self, obj):
        turnboys = StaffAssignment.objects.filter(delivery=obj, role='turnboy')
        if not turnboys:
            return "None"
        
        # Show turnboy names and indicate if they're loading
        turnboy_info = []
        for t in turnboys:
            loading_status = " (loading)" if t.helped_loading else ""
            turnboy_info.append(f"{t.staff.name}{loading_status}")
        
        return ", ".join(turnboy_info)
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
            return "No loaders"
            
        loader_count = loaders.count()
        per_loader = obj.loading_amount / loader_count if loader_count > 0 else 0
        
        return f"Ksh {per_loader:.2f} per loader ({loader_count} loaders)"
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
    

# Staff Admin
@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'is_loader', 'is_active', 'phone_number', 'date_joined', 'display_payments_month')
    list_filter = ('role', 'is_loader', 'is_active')
    search_fields = ('name', 'phone_number')
    actions = ['calculate_monthly_payment', 'calculate_custom_period_payment', 'export_staff_payments_csv']
    
    def get_queryset(self, request):
        # Annotate with payment info for current month
        today = timezone.now().date()
        start_date = today.replace(day=1)
        _, last_day = calendar.monthrange(today.year, today.month)
        end_date = today.replace(day=last_day)
        
        return super().get_queryset(request).annotate(
            current_month_pay=Sum(
                'payrollmanager__total_pay',
                filter=Q(payrollmanager__delivery__date__range=(start_date, end_date))
            )
        )
    
    def display_payments_month(self, obj):
        # Display payments for current month
        if hasattr(obj, 'current_month_pay') and obj.current_month_pay:
            return f"Ksh {obj.current_month_pay:.2f}"
        return "Ksh 0.00"
    display_payments_month.short_description = f"Earnings ({timezone.now().strftime('%b %Y')})"
    
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
                    role_payment = payroll_entries.aggregate(total=Sum('role_pay'))['total'] or Decimal('0.00')
                    loader_payment = payroll_entries.aggregate(total=Sum('loader_pay'))['total'] or Decimal('0.00')
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

# Vehicle Admin
@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'vehicle_type', 'capacity', 'is_active')
    list_filter = ('vehicle_type', 'is_active')
    search_fields = ('plate_number',)

# Monthly Payment Admin
@admin.register(MonthlyPayment)
class MonthlyPaymentAdmin(admin.ModelAdmin):
    list_display = ('staff', 'get_month_year', 'role_payment', 'loader_payment', 'total_payment', 'is_paid', 'payment_date')
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
        writer.writerow(['Staff Name', 'Role', 'Month', 'Year', 'Role Payment', 'Loader Payment', 'Total Payment', 'Is Paid', 'Payment Date'])
        
        for payment in queryset:
            writer.writerow([
                payment.staff.name,
                payment.staff.get_role_display(),
                calendar.month_name[payment.month],
                payment.year,
                payment.role_payment,
                payment.loader_payment,
                payment.total_payment,
                'Yes' if payment.is_paid else 'No',
                payment.payment_date if payment.payment_date else ''
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
            month = forms.ChoiceField(
                choices=[(i, calendar.month_name[i]) for i in range(1, 13)], 
                initial=timezone.now().month
            )
        
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
        total_role = payments.aggregate(Sum('role_payment'))['role_payment__sum'] or 0
        total_loader = payments.aggregate(Sum('loader_payment'))['loader_payment__sum'] or 0
        
        context = {
            'title': f"Payment Summary for {calendar.month_name[month]} {year}",
            'form': form,
            'payments': payments,
            'stats': {
                'total_paid': total_paid,
                'total_unpaid': total_unpaid,
                'total_role': total_role,
                'total_loader': total_loader,
                'total': total_paid + total_unpaid,
            },
            'month_name': calendar.month_name[month],
            'year': year,
        }
        
        return render(request, 'admin/payment_summary.html', context)

# Payment Period Admin
@admin.register(PaymentPeriod)
class PaymentPeriodAdmin(admin.ModelAdmin):
    list_display = ('staff', 'period_name', 'role_payment', 'loader_payment', 'total_payment', 'is_paid', 'payment_date')
    list_filter = ('is_paid', 'staff__role', 'period_start', 'period_end')
    search_fields = ('staff__name',)
    actions = ['export_csv', 'mark_as_paid']
    date_hierarchy = 'period_start'
    
    def export_csv(self, request, queryset):
        """Export selected period payments as CSV"""
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Staff Name', 'Role', 'Period Start', 'Period End', 'Role Payment', 
                         'Loader Payment', 'Total Payment', 'Is Paid', 'Payment Date'])
        
        for payment in queryset:
            writer.writerow([
                payment.staff.name,
                payment.staff.get_role_display(),
                payment.period_start,
                payment.period_end,
                payment.role_payment,
                payment.loader_payment,
                payment.total_payment,
                'Yes' if payment.is_paid else 'No',
                payment.payment_date if payment.payment_date else ''
            ])
        
        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=period_payments.csv'
        return response
    export_csv.short_description = "Export selected period payments to CSV"
    
    def mark_as_paid(self, request, queryset):
        """Mark selected period payments as paid"""
        queryset.update(is_paid=True, payment_date=timezone.now().date())
        messages.success(request, f"{queryset.count()} period payments marked as paid")
    mark_as_paid.short_description = "Mark selected period payments as paid"
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('period-summary/', self.admin_site.admin_view(self.period_summary_view), name='period-summary'),
        ]
        return custom_urls + urls
    
    def period_summary_view(self, request):
        """View to display payment summary by custom period"""
        class DateRangeForm(forms.Form):
            start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
            end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
        
        if request.method == 'POST':
            form = DateRangeForm(request.POST)
            if form.is_valid():
                start_date = form.cleaned_data['start_date']
                end_date = form.cleaned_data['end_date']
            else:
                start_date = timezone.now().replace(day=1).date()
                end_date = timezone.now().date()
        else:
            form = DateRangeForm(initial={
                'start_date': timezone.now().replace(day=1).date(),
                'end_date': timezone.now().date()
            })
            start_date = timezone.now().replace(day=1).date()
            end_date = timezone.now().date()
        
        # Get payments for the selected period (exact match)
        payments = PaymentPeriod.objects.filter(period_start=start_date, period_end=end_date)
        
        # Get summary statistics
        total_paid = payments.filter(is_paid=True).aggregate(Sum('total_payment'))['total_payment__sum'] or 0
        total_unpaid = payments.filter(is_paid=False).aggregate(Sum('total_payment'))['total_payment__sum'] or 0
        total_role = payments.aggregate(Sum('role_payment'))['role_payment__sum'] or 0
        total_loader = payments.aggregate(Sum('loader_payment'))['loader_payment__sum'] or 0
        
        context = {
            'title': f"Payment Summary for Period {start_date} to {end_date}",
            'form': form,
            'payments': payments,
            'stats': {
                'total_paid': total_paid,
                'total_unpaid': total_unpaid,
                'total_role': total_role,
                'total_loader': total_loader,
                'total': total_paid + total_unpaid,
            },
            'start_date': start_date,
            'end_date': end_date,
        }
        
        return render(request, 'admin/period_payment_summary.html', context)

# Staff Assignment Admin
@admin.register(StaffAssignment)
class StaffAssignmentAdmin(admin.ModelAdmin):
    list_display = ('staff', 'delivery', 'role', 'helped_loading', 'display_payments')
    list_filter = ('role', 'helped_loading', 'delivery__date')
    search_fields = ('staff__name', 'delivery__destination')
    autocomplete_fields = ['staff', 'delivery']
    
    def display_payments(self, obj):
        """Display payment info for this staff assignment"""
        if not obj.id:
            return "N/A"
            
        try:
            payroll = PayrollManager.objects.get(staff=obj.staff, delivery=obj.delivery)
            if obj.helped_loading:
                return f"Role: Ksh {payroll.role_pay:.2f}, Loading: Ksh {payroll.loader_pay:.2f}"
            else:
                return f"Role: Ksh {payroll.role_pay:.2f}"
        except PayrollManager.DoesNotExist:
            return "No payment record"
    display_payments.short_description = "Payments"
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Filter staff to only show turnboys and loaders
        if db_field.name == "staff":
            kwargs["queryset"] = Staff.objects.filter(
                Q(role__in=['turnboy', 'loader']) & Q(is_active=True)
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

# Add missing import for mark_safe
from django.utils.safestring import mark_safe