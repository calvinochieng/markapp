from decimal import Decimal
from datetime import datetime
import calendar
from django.db.models import Sum, Count
from django.utils import timezone

from app.models import *



def generate_monthly_payroll(year, month):
    """Generate a complete payroll report for all staff members for a specific month"""
    # Get start and end dates for the month
    start_date = datetime(year, month, 1)
    _, last_day = calendar.monthrange(year, month)
    end_date = datetime(year, month, last_day, 23, 59, 59)
    
    # Get all active staff
    all_staff = Staff.objects.filter(is_active=True)
    
    # Get all deliveries in this month
    deliveries = Delivery.objects.filter(date__range=(start_date, end_date))
    
    payroll_data = []
    
    for staff in all_staff:
        payment_details = {
            'staff_id': staff.id,
            'name': staff.name,
            'role': staff.get_role_display(),
            'phone': staff.phone_number or 'N/A',
            'payments': [],
            'total_payment': Decimal('0.00')
        }
        # Calculate turnboy payments
        if staff.role == 'turnboy':
            turnboy_deliveries = deliveries.filter(turnboy=staff)
            turnboy_payment = turnboy_deliveries.aggregate(total=Sum('turnboy_payment'))['total'] or Decimal('0.00')
            
            if turnboy_payment > 0:
                payment_details['payments'].append({
                    'type': 'Turnboy Payment',
                    'trips': turnboy_deliveries.count(),
                    'amount': turnboy_payment
                })
                payment_details['total_payment'] += turnboy_payment
        
        # Calculate loader payments
        if staff.role == 'loader' or staff.is_loader:
            loader_assignments = LoaderAssignment.objects.filter(
                loader=staff,
                delivery__date__range=(start_date, end_date)
            )
            
            loader_payment = Decimal('0.00')
            delivery_count = 0
            
            for assignment in loader_assignments:
                num_loaders = assignment.delivery.loaderassignment_set.count()
                if num_loaders > 0:
                    per_loader = assignment.delivery.loading_amount / Decimal(num_loaders)
                    loader_payment += per_loader
                    delivery_count += 1
            
            if loader_payment > 0:
                payment_details['payments'].append({
                    'type': 'Loader Payment',
                    'trips': delivery_count,
                    'amount': loader_payment
                })
                payment_details['total_payment'] += loader_payment
        
        payroll_data.append(payment_details)
    
    return payroll_data


def generate_payroll_summary(year, month):
    """Generate a summary of payroll expenses for the month"""
    payroll = generate_monthly_payroll(year, month)
    
    total_paid = sum(staff['total_payment'] for staff in payroll)
    role_totals = {}
    
    for staff in payroll:
        role = staff['role']
        if role not in role_totals:
            role_totals[role] = {
                'count': 0,
                'total': Decimal('0.00')
            }
        
        role_totals[role]['count'] += 1
        role_totals[role]['total'] += staff['total_payment']
    
    return {
        'month': datetime(year, month, 1).strftime('%B %Y'),
        'total_staff': len(payroll),
        'total_payment': total_paid,
        'role_breakdown': role_totals
    }


# Create a view to generate and display payroll
from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
import csv


@login_required
def view_monthly_payroll(request):
    """View to display monthly payroll data with filtering options"""
    current_date = timezone.now()
    year = int(request.GET.get('year', current_date.year))
    month = int(request.GET.get('month', current_date.month))
    
    payroll_data = generate_monthly_payroll(year, month)
    summary = generate_payroll_summary(year, month)
    
    # Generate a list of months for the dropdown
    months = []
    for i in range(1, 13):
        months.append({
            'value': i,
            'name': datetime(2000, i, 1).strftime('%B')
        })
    
    # Generate a list of years (current year and 5 previous years)
    years = range(current_date.year - 5, current_date.year + 1)
    
    context = {
        'payroll': payroll_data,
        'summary': summary,
        'months': months,
        'years': years,
        'selected_month': month,
        'selected_year': year
    }
    
    return render(request, 'payroll/monthly_payroll.html', context)


@login_required
def export_payroll_csv(request):
    """Export payroll data as CSV"""
    current_date = timezone.now()
    year = int(request.GET.get('year', current_date.year))
    month = int(request.GET.get('month', current_date.month))
    
    payroll_data = generate_monthly_payroll(year, month)
    month_name = datetime(year, month, 1).strftime('%B_%Y')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="payroll_{month_name}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Staff ID', 'Name', 'Role', 'Phone', 'Total Payment'])
    
    for staff in payroll_data:
        writer.writerow([
            staff['staff_id'],
            staff['name'],
            staff['role'],
            staff['phone'],
            staff['total_payment']
        ])
    
    return response


# Create a detailed payroll slip for individual staff
@login_required
def view_staff_payslip(request, staff_id, year, month):
    """View to display a detailed payslip for a specific staff member"""
    staff = Staff.objects.get(pk=staff_id)
    
    # Get start and end dates for the month
    start_date = datetime(year, month, 1)
    _, last_day = calendar.monthrange(year, month)
    end_date = datetime(year, month, last_day, 23, 59, 59)
    
    # Calculate payment details
    payment_details = {
        'staff': staff,
        'month': datetime(year, month, 1).strftime('%B %Y'),
        'payments': [],
        'total_payment': Decimal('0.00')
    }
    
    # Get all deliveries in this month
    deliveries = Delivery.objects.filter(date__range=(start_date, end_date))
    
    # Driver payments
    if staff.role == 'driver':
        driver_deliveries = deliveries.filter(driver=staff)
        # You can customize driver payment calculation here
        driver_payment = Decimal('500.00') * driver_deliveries.count()
        
        payment_details['payments'].append({
            'type': 'Driver Payment',
            'description': f'{driver_deliveries.count()} deliveries @ KSh 500.00 each',
            'amount': driver_payment
        })
        payment_details['total_payment'] += driver_payment
        
        # Add list of deliveries for reference
        payment_details['deliveries'] = driver_deliveries
    
    # Turnboy payments
    if staff.role == 'turnboy':
        turnboy_deliveries = deliveries.filter(turnboy=staff)
        turnboy_payment = turnboy_deliveries.aggregate(total=Sum('turnboy_payment'))['total'] or Decimal('0.00')
        
        payment_details['payments'].append({
            'type': 'Turnboy Payment',
            'description': f'{turnboy_deliveries.count()} deliveries @ standard turnboy rate',
            'amount': turnboy_payment
        })
        payment_details['total_payment'] += turnboy_payment
        
        # Add list of deliveries for reference
        payment_details['deliveries'] = turnboy_deliveries
    
    # Loader payments
    if staff.role == 'loader' or staff.is_loader:
        loader_assignments = LoaderAssignment.objects.filter(
            loader=staff,
            delivery__date__range=(start_date, end_date)
        )
        
        loader_deliveries = [assignment.delivery for assignment in loader_assignments]
        loader_payment = Decimal('0.00')
        
        for assignment in loader_assignments:
            num_loaders = assignment.delivery.loaderassignment_set.count()
            if num_loaders > 0:
                per_loader = assignment.delivery.loading_amount / Decimal(num_loaders)
                loader_payment += per_loader
        
        payment_details['payments'].append({
            'type': 'Loader Payment',
            'description': f'{len(loader_deliveries)} loading assignments',
            'amount': loader_payment
        })
        payment_details['total_payment'] += loader_payment
        
        # Add list of deliveries for reference
        payment_details['deliveries'] = loader_deliveries
    
    return render(request, 'payroll/staff_payslip.html', payment_details)


# Model for payroll records (optional but recommended)
class PayrollRecord(models.Model):
    """Model to store historical payroll records"""
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    year = models.IntegerField()
    month = models.IntegerField()
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField(auto_now_add=True)
    payment_method = models.CharField(max_length=50, blank=True)
    reference_number = models.CharField(max_length=100, blank=True)
    is_paid = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('staff', 'year', 'month')
    
    def __str__(self):
        month_name = datetime(self.year, self.month, 1).strftime('%B')
        return f"Payroll for {self.staff.name} - {month_name} {self.year}"


# Function to generate or update payroll records
def generate_payroll_records(year, month, commit=False):
    """Generate or update payroll records for all staff for a specific month"""
    payroll_data = generate_monthly_payroll(year, month)
    records = []
    
    for staff_payment in payroll_data:
        staff = Staff.objects.get(pk=staff_payment['staff_id'])
        
        # Try to get existing record or create new one
        try:
            record = PayrollRecord.objects.get(staff=staff, year=year, month=month)
            record.amount_paid = staff_payment['total_payment']
        except PayrollRecord.DoesNotExist:
            record = PayrollRecord(
                staff=staff,
                year=year,
                month=month,
                amount_paid=staff_payment['total_payment']
            )
        
        if commit:
            record.save()
        
        records.append(record)
    
    return records


# Mark payroll as paid
@login_required
def mark_payroll_paid(request):

    if request.method == 'POST':
        staff_id = request.POST.get('staff_id')
        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))
        payment_method = request.POST.get('payment_method')
        reference = request.POST.get('reference')
        
        try:
            record = PayrollRecord.objects.get(staff_id=staff_id, year=year, month=month)
            record.is_paid = True
            record.payment_method = payment_method
            record.reference_number = reference
            record.payment_date = timezone.now().date()
            record.save()
            return HttpResponse(status=200)
        except PayrollRecord.DoesNotExist:
            return HttpResponse(status=404)
    
    return HttpResponse(status=405)  # Method not allowed



@receiver(post_save, sender=Delivery)
@receiver(post_delete, sender=Delivery)
def update_turnboy_payroll(sender, instance, **kwargs):
    if instance.turnboy:
        PayrollManager.objects.update_or_create(
            staff=instance.turnboy,
            delivery=instance,
            defaults={
                'turnboy_pay': instance.turnboy_payment,
                'loader_pay': 0,
                'total_pay': instance.turnboy_payment,
            }
        )


@receiver(post_save, sender=Delivery)
@receiver(post_delete, sender=Delivery)
def update_payroll(sender, instance, **kwargs):    
    turnboy = instance.turnboy
    turnboy_pay = instance.turnboy_payment
    loaders = instance.get_loaders()
    loader_count = len(loaders)
    per_loader_pay = instance.per_loader_amount()    
    if loader_count == 0:
        # makes sure that turnboy is assigned as the loader as well. and paid the loading money
        LoaderAssignment.objects.update_or_create(
            delivery=instance,
            loader=turnboy,
        )
        PayrollManager.objects.get_or_create(
            staff=loader,
            delivery=delivery,
            defaults={
                'turnboy_pay': turnboy_payment,  # will be updated separately if loader is also a turnboy.
                'loader_pay': per_loader_pay,
                'total_pay': per_loader_pay,
            }
        )

    '''
    Update or create payroll record for the turnboy, loaders

    '''

@receiver(post_save, sender=LoaderAssignment)
@receiver(post_delete, sender=LoaderAssignment)
def update_loader_payroll(sender, instance, **kwargs):
    """Update payroll records for loaders when a LoaderAssignment is added, updated, or deleted."""
    delivery = instance.delivery
    loaders = delivery.get_loaders()
    loader_count = len(loaders)
    
    if loader_count == 0:
        # Optionally: Delete any stale PayrollManager records for loaders.
        return

    per_loader_pay = delivery.per_loader_amount()

    for loader in loaders:
        # Get existing payroll record if it exists.
        payroll, created = PayrollManager.objects.get_or_create(
            staff=loader,
            delivery=delivery,
            defaults={
                'turnboy_pay': 0,  # will be updated separately if loader is also a turnboy.
                'loader_pay': per_loader_pay,
                'total_pay': per_loader_pay,
            }
        )
        if not created:
            # Preserve turnboy_pay if it exists.
            payroll.loader_pay = per_loader_pay
            payroll.total_pay = payroll.turnboy_pay + payroll.loader_pay
            payroll.save()


# ///////// End of the code /////////////








