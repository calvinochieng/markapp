from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
# /////Django Query Imports////
from .models import *
from django.db.models import Sum, Count, Q, F
from .forms import PaymentPeriodForm  # You'll need to create this form

# ////Utils Imports////
import csv
from decimal import Decimal
from django.contrib import messages
from django.utils import timezone
import calendar
from collections import defaultdict

from datetime import datetime, timedelta
from django.core.paginator import Paginator

# ////Auth Imports////
import logging
logger = logging.getLogger(__name__)
from django.contrib.auth.views import LoginView
from .forms import RegistrationForm
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required


def index(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'index.html')

# //////Auth Views///////
def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}!')
            return redirect('login')
    else:
        form = RegistrationForm()
    
    return render(request, 'registration/register.html', {'form': form})

class CustomLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True  # Redirects logged-in users away from login page
    
    def form_invalid(self, form):
        messages.error(self.request, 'Invalid username or password')
        return super().form_invalid(form)

def logout_view(request):
    logout(request)
    return redirect('login')
# //////End of Auth Views///////

# /////Dashboard View//////
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Count, Sum, F, Q
from django.db.models.functions import TruncMonth, TruncWeek
import calendar
from decimal import Decimal
from datetime import datetime, timedelta
import json

from .models import (
    Staff, 
    Vehicle, 
    Delivery, 
    StaffAssignment, 
    MonthlyPayment, 
    PaymentPeriod,
    PayrollManager
)

@login_required
def dashboard(request):
    """Main dashboard view displaying summary of operations"""
    # Get current date and time info
    today = timezone.now().date()
    current_month = today.month
    current_year = today.year
    
    # Calculate dates for filtering
    start_of_month = timezone.datetime(current_year, current_month, 1).date()
    _, last_day = calendar.monthrange(current_year, current_month)
    end_of_month = timezone.datetime(current_year, current_month, last_day).date()
    
    # Last 30 days
    thirty_days_ago = today - timedelta(days=30)
    
    # Get counts of active staff and vehicles
    active_staff_count = Staff.objects.filter(is_active=True).count()
    active_vehicles_count = Vehicle.objects.filter(is_active=True).count()
    
    # Get delivery stats
    total_deliveries = Delivery.objects.count()
    month_deliveries = Delivery.objects.filter(date__range=(start_of_month, end_of_month)).count()
    recent_deliveries = Delivery.objects.filter(date__range=(thirty_days_ago, today)).count()
    
    # Get pending deliveries
    pending_deliveries = Delivery.objects.filter(status='pending').count()
    in_progress_deliveries = Delivery.objects.filter(status='in_progress').count()
    
    # Calculate payroll stats
    total_payroll = PayrollManager.objects.all().aggregate(
        total=Sum('total_pay')
    )['total'] or Decimal('0.00')
    
    month_payroll = PayrollManager.objects.filter(
        delivery__date__range=(start_of_month, end_of_month)
    ).aggregate(
        total=Sum('total_pay')
    )['total'] or Decimal('0.00')
    
    # Get monthly delivery trends - last 6 months
    six_months_ago = today - timedelta(days=180)
    monthly_delivery_data = Delivery.objects.filter(
        date__gte=six_months_ago
    ).annotate(
        month=TruncMonth('date')
    ).values('month').annotate(
        count=Count('id')
    ).order_by('month')
    
    # Format the data for charts
    monthly_labels = []
    monthly_counts = []
    
    for item in monthly_delivery_data:
        # Format as 'Jan', 'Feb', etc.
        month_str = item['month'].strftime('%b')
        monthly_labels.append(month_str)
        monthly_counts.append(item['count'])
    
    # Get recent deliveries for display
    recent_delivery_list = Delivery.objects.all().order_by('-date')[:5]
    
    # Top staff by deliveries in the current month
    top_staff = StaffAssignment.objects.filter(
        delivery__date__range=(start_of_month, end_of_month)
    ).values(
        'staff__name', 'staff__role'
    ).annotate(
        delivery_count=Count('delivery')
    ).order_by('-delivery_count')[:5]
    
    # Top destinations
    top_destinations = Delivery.objects.values(
        'destination'
    ).annotate(
        count=Count('id')
    ).order_by('-count')[:5]
    
    # Status of monthly payments
    payment_stats = MonthlyPayment.objects.filter(
        year=current_year,
        month=current_month
    ).aggregate(
        total=Sum('total_payment'),
        paid_count=Count('id', filter=Q(is_paid=True)),
        unpaid_count=Count('id', filter=Q(is_paid=False))
    )
    
    # Vehicle usage stats
    vehicle_usage = Delivery.objects.filter(
        date__range=(thirty_days_ago, today)
    ).values(
        'vehicle__plate_number'
    ).annotate(
        trip_count=Count('id')
    ).order_by('-trip_count')
    
    # Prepare data for passing to the template
    context = {
        # Basic counts
        'active_staff_count': active_staff_count,
        'active_vehicles_count': active_vehicles_count,
        'total_deliveries': total_deliveries,
        'month_deliveries': month_deliveries,
        'recent_deliveries': recent_deliveries,
        
        # Delivery status
        'pending_deliveries': pending_deliveries,
        'in_progress_deliveries': in_progress_deliveries,
        
        # Financial stats
        'total_payroll': total_payroll,
        'month_payroll': month_payroll,
        
        # Chart data (converted to JSON for JavaScript)
        'monthly_labels': json.dumps(monthly_labels),
        'monthly_counts': json.dumps(monthly_counts),
        
        # Lists for tables
        'recent_delivery_list': recent_delivery_list,
        'top_staff': top_staff,
        'top_destinations': top_destinations,
        'vehicle_usage': vehicle_usage,
        
        # Payment status
        'payment_stats': payment_stats,
        
        # Time context
        'current_month': calendar.month_name[current_month],
        'current_year': current_year,
    }
    
    return render(request, 'dashboard/dashboard.html', context)

@login_required
def staff_dashboard(request):
    """Dashboard focused on staff performance and payments"""
    # Get current date and time info
    today = timezone.now().date()
    current_month = today.month
    current_year = today.year
    
    # Calculate date ranges
    start_of_month = timezone.datetime(current_year, current_month, 1).date()
    _, last_day = calendar.monthrange(current_year, current_month)
    end_of_month = timezone.datetime(current_year, current_month, last_day).date()
    
    # Get active staff with role counts
    turnboy_count = Staff.objects.filter(is_active=True, role='turnboy').count()
    loader_count = Staff.objects.filter(is_active=True, role='loader').count()
    
    # Staff with most deliveries this month
    top_staff_deliveries = StaffAssignment.objects.filter(
        delivery__date__range=(start_of_month, end_of_month)
    ).values(
        'staff__id', 'staff__name', 'staff__role'
    ).annotate(
        delivery_count=Count('delivery')
    ).order_by('-delivery_count')[:10]
    
    # Staff with highest earnings this month
    top_staff_earnings = PayrollManager.objects.filter(
        delivery__date__range=(start_of_month, end_of_month)
    ).values(
        'staff__id', 'staff__name', 'staff__role'
    ).annotate(
        total_earned=Sum('total_pay')
    ).order_by('-total_earned')[:10]
    
    # Payment status overview
    payment_status = MonthlyPayment.objects.filter(
        year=current_year,
        month=current_month
    ).aggregate(
        total_due=Sum('total_payment'),
        paid_amount=Sum('total_payment', filter=Q(is_paid=True)),
        unpaid_amount=Sum('total_payment', filter=Q(is_paid=False)),
        staff_paid=Count('id', filter=Q(is_paid=True)),
        staff_unpaid=Count('id', filter=Q(is_paid=False))
    )
    
    # Staff who helped loading the most
    top_loaders = StaffAssignment.objects.filter(
        helped_loading=True,
        delivery__date__range=(start_of_month, end_of_month)
    ).values(
        'staff__id', 'staff__name'
    ).annotate(
        loading_count=Count('delivery')
    ).order_by('-loading_count')[:5]
    
    # Recent payments made
    recent_payments = MonthlyPayment.objects.filter(
        is_paid=True
    ).order_by('-payment_date')[:5]
    
    # Context data for template
    context = {
        'turnboy_count': turnboy_count,
        'loader_count': loader_count,
        'top_staff_deliveries': top_staff_deliveries,
        'top_staff_earnings': top_staff_earnings,
        'payment_status': payment_status,
        'top_loaders': top_loaders,
        'recent_payments': recent_payments,
        'current_month': calendar.month_name[current_month],
        'current_year': current_year,
    }
    
    return render(request, 'dashboard/staff_dashboard.html', context)

@login_required
def delivery_dashboard(request):
    """Dashboard focused on delivery statistics and performance"""
    # Get current date and time info
    today = timezone.now().date()
    current_month = today.month
    current_year = today.year
    
    # Calculate date ranges
    start_of_month = timezone.datetime(current_year, current_month, 1).date()
    _, last_day = calendar.monthrange(current_year, current_month)
    end_of_month = timezone.datetime(current_year, current_month, last_day).date()
    
    # Last 30 days for recent stats
    thirty_days_ago = today - timedelta(days=30)
    
    # Get weekly delivery trends
    weekly_delivery_data = Delivery.objects.filter(
        date__gte=thirty_days_ago
    ).annotate(
        week=TruncWeek('date')
    ).values('week').annotate(
        count=Count('id')
    ).order_by('week')
    
    # Format for charts
    weekly_labels = []
    weekly_counts = []
    
    for item in weekly_delivery_data:
        # Format as 'Week of Mon, DD'
        week_str = item['week'].strftime('Week of %b %d')
        weekly_labels.append(week_str)
        weekly_counts.append(item['count'])
    
    # Delivery status breakdown
    status_counts = Delivery.objects.values(
        'status'
    ).annotate(
        count=Count('id')
    )
    
    # Delivery destinations analysis
    destination_data = Delivery.objects.filter(
        date__range=(start_of_month, end_of_month)
    ).values(
        'destination'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Vehicle performance
    vehicle_performance = Delivery.objects.filter(
        date__range=(start_of_month, end_of_month)
    ).values(
        'vehicle__plate_number', 'vehicle__vehicle_type'
    ).annotate(
        delivery_count=Count('id')
    ).order_by('-delivery_count')
    
    # Average loaders per delivery
    avg_loaders = Delivery.objects.filter(
        date__range=(start_of_month, end_of_month)
    ).annotate(
        loader_count=Count('staffassignment', filter=Q(staffassignment__helped_loading=True))
    ).aggregate(
        avg=Avg('loader_count')
    )['avg'] or 0
    
    # Recent deliveries with details
    recent_deliveries = Delivery.objects.select_related('vehicle').prefetch_related(
        'staffassignment_set__staff'
    ).order_by('-date')[:10]
    
    # Context data for template
    context = {
        'weekly_labels': json.dumps(weekly_labels),
        'weekly_counts': json.dumps(weekly_counts),
        'status_counts': status_counts,
        'destination_data': destination_data,
        'vehicle_performance': vehicle_performance,
        'avg_loaders': avg_loaders,
        'recent_deliveries': recent_deliveries,
        'current_month': calendar.month_name[current_month],
        'current_year': current_year,
    }
    
    # Fix for the missing Avg import
    try:
        from django.db.models import Avg
        avg_loaders = Delivery.objects.filter(
            date__range=(start_of_month, end_of_month)
        ).annotate(
            loader_count=Count('staffassignment', filter=Q(staffassignment__helped_loading=True))
        ).aggregate(
            avg=Avg('loader_count')
        )['avg'] or 0
        context['avg_loaders'] = avg_loaders
    except ImportError:
        context['avg_loaders'] = 0
    
    return render(request, 'dashboard/delivery_dashboard.html', context)

@login_required
def payroll_dashboard(request):
    """Dashboard focused on payroll and financial metrics"""
    # Get current date and time info
    today = timezone.now().date()
    current_month = today.month
    current_year = today.year
    
    # Calculate date ranges
    start_of_month = timezone.datetime(current_year, current_month, 1).date()
    _, last_day = calendar.monthrange(current_year, current_month)
    end_of_month = timezone.datetime(current_year, current_month, last_day).date()
    
    # Last 6 months for trends
    six_months_ago = today - timedelta(days=180)
    
    # Monthly payroll trends
    monthly_payroll_data = PayrollManager.objects.filter(
        delivery__date__gte=six_months_ago
    ).annotate(
        month=TruncMonth('delivery__date')
    ).values('month').annotate(
        total=Sum('total_pay'),
        role_pay=Sum('role_pay'),
        loader_pay=Sum('loader_pay')
    ).order_by('month')
    
    # Format for charts
    monthly_labels = []
    monthly_totals = []
    monthly_role_pay = []
    monthly_loader_pay = []
    
    for item in monthly_payroll_data:
        month_str = item['month'].strftime('%b %Y')
        monthly_labels.append(month_str)
        monthly_totals.append(float(item['total']))
        monthly_role_pay.append(float(item['role_pay']))
        monthly_loader_pay.append(float(item['loader_pay']))
    
    # Current month payment status
    payment_status = MonthlyPayment.objects.filter(
        year=current_year,
        month=current_month
    ).aggregate(
        total_amount=Sum('total_payment'),
        paid_amount=Sum('total_payment', filter=Q(is_paid=True)),
        unpaid_amount=Sum('total_payment', filter=Q(is_paid=False)),
        paid_count=Count('id', filter=Q(is_paid=True)),
        unpaid_count=Count('id', filter=Q(is_paid=False))
    )
    
    # Staff payment breakdown by role
    role_breakdown = MonthlyPayment.objects.filter(
        year=current_year,
        month=current_month
    ).values(
        'staff__role'
    ).annotate(
        total=Sum('total_payment'),
        role_pay=Sum('role_payment'),
        loader_pay=Sum('loader_payment')
    )
    
    # Pending payments list
    pending_payments = MonthlyPayment.objects.filter(
        is_paid=False
    ).select_related('staff').order_by('year', 'month')[:15]
    
    # Recent payments
    recent_payments = MonthlyPayment.objects.filter(
        is_paid=True
    ).select_related('staff').order_by('-payment_date')[:10]
    
    # Custom period payments
    custom_period_payments = PaymentPeriod.objects.filter(
        is_paid=False
    ).select_related('staff').order_by('period_end')[:10]
    
    # Context data for template
    context = {
        'monthly_labels': json.dumps(monthly_labels),
        'monthly_totals': json.dumps(monthly_totals),
        'monthly_role_pay': json.dumps(monthly_role_pay),
        'monthly_loader_pay': json.dumps(monthly_loader_pay),
        'payment_status': payment_status,
        'role_breakdown': role_breakdown,
        'pending_payments': pending_payments,
        'recent_payments': recent_payments,
        'custom_period_payments': custom_period_payments,
        'current_month': calendar.month_name[current_month],
        'current_year': current_year,
    }
    
    return render(request, 'dashboard/dashboard.html', context)
# //////End of Dashboard View//////


# /////MonthlyPayroll View//////

@login_required
def staff_payroll(request):
    """
    View for generating and viewing staff payroll information with date filtering
    """
    # Get current year and month as defaults
    current_year = timezone.now().year
    current_month = timezone.now().month
    
    # Get filter parameters from request
    selected_year = int(request.GET.get('year', current_year))
    selected_month = int(request.GET.get('month', current_month))
    staff_id = request.GET.get('staff_id', None)
    role_filter = request.GET.get('role', None)
    
    # Create date range for the selected month
    start_date = timezone.datetime(selected_year, selected_month, 1).date()
    _, last_day = calendar.monthrange(selected_year, selected_month)
    end_date = timezone.datetime(selected_year, selected_month, last_day).date()
    date_range = (start_date, end_date)
    
    # Get all active staff members, excluding drivers
    staff_query = Staff.objects.filter(is_active=True).exclude(role='driver')
    
    # Apply role filter if provided
    if role_filter:
        if role_filter == 'loader':
            staff_query = staff_query.filter(is_loader=True)
        else:
            staff_query = staff_query.filter(role=role_filter)
    
    # Get staff member details if specific staff selected
    selected_staff = None
    if staff_id:
        selected_staff = get_object_or_404(Staff, id=staff_id)
        # Filter to just this staff member
        staff_query = staff_query.filter(id=staff_id)
    
    # Prepare payroll data for each staff member
    payroll_data = []
    for staff in staff_query:
        # Get all payroll records for this staff member in the date range
        payroll_records = PayrollManager.objects.filter(
            staff=staff,
            delivery__date__range=date_range
        )
        
        # Calculate payment totals
        payment_totals = payroll_records.aggregate(
            turnboy_total=Sum('turnboy_pay') or Decimal('0.00'),
            loader_total=Sum('loader_pay') or Decimal('0.00'),
            grand_total=Sum('total_pay') or Decimal('0.00')
        )
        
        # Get delivery count for this staff member
        delivery_count = 0
        if staff.role == 'turnboy':
            delivery_count = Delivery.objects.filter(
                turnboy=staff,
                date__range=date_range
            ).count()
        
        # Get loader assignment count
        loader_count = 0
        if staff.is_loader:
            loader_count = payroll_records.filter(loader_pay__gt=0).count()
        
        # Check if a MonthlyPayment record exists for this staff member
        monthly_payment, created = MonthlyPayment.objects.get_or_create(
            staff=staff,
            year=selected_year,
            month=selected_month,
            defaults={
                'turnboy_payment': payment_totals['turnboy_total'] or Decimal('0.00'),
                'loader_payment': payment_totals['loader_total'] or Decimal('0.00'),
                'total_payment': payment_totals['grand_total'] or Decimal('0.00'),
            }
        )
        
        # If record exists but needs updating, update it
        if not created:
            monthly_payment.turnboy_payment = payment_totals['turnboy_total'] or Decimal('0.00')
            monthly_payment.loader_payment = payment_totals['loader_total'] or Decimal('0.00')
            monthly_payment.total_payment = payment_totals['grand_total'] or Decimal('0.00')
            monthly_payment.save()
        
        # Get delivery details for this staff member
        staff_deliveries = []
        if selected_staff and staff.id == selected_staff.id:
            staff_deliveries = payroll_records.select_related('delivery', 'delivery__vehicle')
        
        # Add staff data to the payroll data list
        payroll_data.append({
            'staff': staff,
            'turnboy_total': payment_totals['turnboy_total'] or Decimal('0.00'),
            'loader_total': payment_totals['loader_total'] or Decimal('0.00'),
            'grand_total': payment_totals['grand_total'] or Decimal('0.00'),
            'delivery_count': delivery_count,
            'loader_count': loader_count,
            'is_paid': monthly_payment.is_paid,
            'payment_date': monthly_payment.payment_date,
            'deliveries': staff_deliveries
        })
    
    # Prepare data for year/month filter dropdowns
    years = range(current_year - 2, current_year + 1)  # Current year and 2 years back
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]
    
    # Process payroll action
    if request.method == 'POST' and 'mark_paid' in request.POST:
        staff_ids = request.POST.getlist('staff_id')
        for staff_id in staff_ids:
            payment = MonthlyPayment.objects.get(
                staff_id=staff_id,
                year=selected_year,
                month=selected_month
            )
            payment.is_paid = True
            payment.payment_date = timezone.now().date()
            payment.save()
        messages.success(request, f"Marked {len(staff_ids)} staff payments as paid")
        return redirect(request.get_full_path())
    
    # Handle CSV export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="payroll_{selected_month}_{selected_year}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Staff Name', 'Role', 'Turnboy Payment', 'Loader Payment', 'Total Payment', 'Status'])
        
        for data in payroll_data:
            staff = data['staff']
            writer.writerow([
                staff.name,
                staff.get_role_display(),
                data['turnboy_total'],
                data['loader_total'],
                data['grand_total'],
                'Paid' if data['is_paid'] else 'Unpaid'
            ])
        
        return response
    
    context = {
        'payroll_data': payroll_data,
        'selected_year': selected_year,
        'selected_month': selected_month,
        'selected_month_name': calendar.month_name[selected_month],
        'selected_staff': selected_staff,
        'role_filter': role_filter,
        'years': years,
        'months': months,
        'date_range': f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}",
        'total_payroll': sum(data['grand_total'] for data in payroll_data),
        'total_turnboy_pay': sum(data['turnboy_total'] for data in payroll_data),
        'total_loader_pay': sum(data['loader_total'] for data in payroll_data),
        'total_staff': len(payroll_data),
    }
    
    return render(request, 'payroll/staff_payroll.html', context)

# //////End of Payroll View//////

# ////// Period Payroll View //////

@login_required
def period_payroll(request):
    """
    View for managing period-based payroll calculations
    Allows selecting a custom date range and calculating staff payments
    """
    # Get default dates for date range (current month if not specified)
    today = timezone.now().date()
    default_end = today
    default_start = today.replace(day=1)  # First day of current month
    
    # Get date range from request or use defaults
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else default_start
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else default_end
    except ValueError:
        # Handle invalid date format
        messages.error(request, 'Invalid date format. Using default date range.')
        start_date = default_start
        end_date = default_end
    
    # Make sure start_date is before end_date
    if start_date > end_date:
        messages.warning(request, 'Start date cannot be after end date. Dates have been swapped.')
        start_date, end_date = end_date, start_date
    
    date_range = (start_date, end_date)
    
    # Get filters from request
    staff_id = request.GET.get('staff_id')
    role_filter = request.GET.get('role')
    
    # Get all active staff, excluding drivers (similar to staff_payroll)
    staff_query = Staff.objects.filter(is_active=True).exclude(role='driver')
    
    # Apply role filter if provided
    if role_filter:
        if role_filter == 'loader':
            staff_query = staff_query.filter(is_loader=True)
        else:
            staff_query = staff_query.filter(role=role_filter)
    
    # Get specific staff member if requested
    selected_staff = None
    if staff_id:
        try:
            selected_staff = Staff.objects.get(id=staff_id)
            staff_query = staff_query.filter(id=staff_id)
        except Staff.DoesNotExist:
            messages.error(request, f'Staff with ID {staff_id} not found.')
    
    # Process form submission for marking payments as paid
    if request.method == 'POST' and 'mark_paid' in request.POST:
        selected_staff_ids = request.POST.getlist('staff_ids')
        
        if not selected_staff_ids:
            messages.warning(request, 'No staff members were selected.')
            return redirect(f"{request.path}?start_date={start_date}&end_date={end_date}")
        
        # Update payment periods for each selected staff member
        update_count = 0
        for staff_id in selected_staff_ids:
            try:
                payment_period = PaymentPeriod.objects.get(
                    staff_id=staff_id,
                    period_start=start_date,
                    period_end=end_date
                )
                payment_period.is_paid = True
                payment_period.payment_date = timezone.now().date()
                payment_period.save()
                update_count += 1
            except PaymentPeriod.DoesNotExist:
                # If payment period doesn't exist, create it first
                try:
                    staff = Staff.objects.get(id=staff_id)
                    
                    # Calculate payments for this staff and period
                    payments = PayrollManager.objects.filter(
                        staff=staff,
                        delivery__date__range=date_range
                    ).aggregate(
                        role_payment=Sum('role_pay'),
                        loader_payment=Sum('loader_pay'),
                        total_payment=Sum('total_pay')
                    )
                    
                    role_payment = payments['role_payment'] or 0
                    loader_payment = payments['loader_payment'] or 0
                    total_payment = payments['total_payment'] or 0
                    
                    # Create payment period
                    PaymentPeriod.objects.create(
                        staff=staff,
                        period_start=start_date,
                        period_end=end_date,
                        role_payment=role_payment,
                        loader_payment=loader_payment,
                        total_payment=total_payment,
                        is_paid=True,
                        payment_date=timezone.now().date(),
                        admin=request.user
                    )
                    update_count += 1
                except Staff.DoesNotExist:
                    messages.error(request, f'Staff with ID {staff_id} not found.')
                    continue
        
        if update_count > 0:
            messages.success(request, f'Successfully marked {update_count} staff payments as paid.')
        
        return redirect(f"{request.path}?start_date={start_date}&end_date={end_date}")
    
    # Process form submission for creating payment periods
    if request.method == 'POST' and 'create_payment_period' in request.POST:
        selected_staff_ids = request.POST.getlist('staff_ids')
        
        if not selected_staff_ids:
            messages.warning(request, 'No staff members were selected.')
            return redirect(f"{request.path}?start_date={start_date}&end_date={end_date}")
        
        # Create payment periods for each selected staff member
        created_count = 0
        for staff_id in selected_staff_ids:
            try:
                staff = Staff.objects.get(id=staff_id)
                
                # Calculate payments for this staff and period
                payments = PayrollManager.objects.filter(
                    staff=staff,
                    delivery__date__range=date_range
                ).aggregate(
                    role_payment=Sum('role_pay'),
                    loader_payment=Sum('loader_pay'),
                    total_payment=Sum('total_pay')
                )
                
                role_payment = payments['role_payment'] or 0
                loader_payment = payments['loader_payment'] or 0
                total_payment = payments['total_payment'] or 0
                
                # Create or update payment period
                payment_period, created = PaymentPeriod.objects.update_or_create(
                    staff=staff,
                    period_start=start_date,
                    period_end=end_date,
                    defaults={
                        'role_payment': role_payment,
                        'loader_payment': loader_payment,
                        'total_payment': total_payment,
                        'admin': request.user
                    }
                )
                
                created_count += 1
            except Staff.DoesNotExist:
                messages.error(request, f'Staff with ID {staff_id} not found.')
                continue
        
        if created_count > 0:
            messages.success(request, f'Successfully created payment periods for {created_count} staff members.')
        
        return redirect(f"{request.path}?start_date={start_date}&end_date={end_date}")
    
    # Prepare payroll data for each staff member
    staff_payments = []
    total_role_pay = Decimal('0.00')
    total_loader_pay = Decimal('0.00')
    total_pay = Decimal('0.00')
    
    for staff in staff_query:
        # Get all payroll records for this staff member in the date range
        payroll_records = PayrollManager.objects.filter(
            staff=staff,
            delivery__date__range=date_range
        )
        
        # Calculate payment totals
        payment_data = payroll_records.aggregate(
            role_payment=Sum('role_pay'),
            loader_payment=Sum('loader_pay'),
            total_payment=Sum('total_pay'),
            delivery_count=Count('delivery', distinct=True)
        )
        
        role_payment = payment_data['role_payment'] or Decimal('0.00')
        loader_payment = payment_data['loader_payment'] or Decimal('0.00')
        total_payment = payment_data['total_payment'] or Decimal('0.00')
        delivery_count = payment_data['delivery_count'] or 0
        
        # Add to running totals
        total_role_pay += role_payment
        total_loader_pay += loader_payment
        total_pay += total_payment
        
        # Check if a PaymentPeriod already exists for this staff and date range
        existing_period = PaymentPeriod.objects.filter(
            staff=staff,
            period_start=start_date,
            period_end=end_date
        ).first()
        
        # Get delivery details for this staff
        staff_deliveries = []
        if selected_staff and staff.id == selected_staff.id:
            staff_deliveries = payroll_records.select_related('delivery', 'delivery__vehicle').order_by('-delivery__date')
        
        # Add to staff_payments list
        staff_payments.append({
            'staff': staff,
            'role_payment': role_payment,
            'loader_payment': loader_payment,
            'total_payment': total_payment,
            'delivery_count': delivery_count,
            'existing_period': existing_period,
            'is_paid': existing_period.is_paid if existing_period else False,
            'payment_date': existing_period.payment_date if existing_period else None,
            'deliveries': staff_deliveries
        })
    
    # Sort by total payment (highest first)
    staff_payments.sort(key=lambda x: x['total_payment'], reverse=True)
    
    # Handle CSV export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="period_payroll_{start_date.strftime("%Y%m%d")}_{end_date.strftime("%Y%m%d")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Staff Name', 'Role', 'Deliveries', 'Role Payment', 'Loader Payment', 'Total Payment', 'Status'])
        
        for data in staff_payments:
            staff = data['staff']
            writer.writerow([
                staff.name,
                staff.get_role_display(),
                data['delivery_count'],
                data['role_payment'],
                data['loader_payment'],
                data['total_payment'],
                'Paid' if data['is_paid'] else 'Unpaid'
            ])
        
        return response
    
    context = {
        'staff_payments': staff_payments,
        'start_date': start_date,
        'end_date': end_date,
        'selected_staff': selected_staff,
        'role_filter': role_filter,
        'date_range': f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}",
        'total_payroll': total_pay,
        'total_role_pay': total_role_pay,
        'total_loader_pay': total_loader_pay,
        'total_staff': len(staff_payments),
    }
    
    return render(request, 'payroll/period_payroll.html', context)

@login_required
def individual_payroll(request):
    """
    View for managing individual staff payroll calculations
    Allows selecting a staff member and date range to calculate payments
    """
    # Get default dates for date range (current month if not specified)
    today = timezone.now().date()
    default_end = today
    default_start = today.replace(day=1)  # First day of current month
    
    # Get date range from request or use defaults
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else default_start
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else default_end
    except ValueError:
        # Handle invalid date format
        messages.error(request, 'Invalid date format. Using default date range.')
        start_date = default_start
        end_date = default_end
    
    # Make sure start_date is before end_date
    if start_date > end_date:
        messages.warning(request, 'Start date cannot be after end date. Dates have been swapped.')
        start_date, end_date = end_date, start_date
    
    date_range = (start_date, end_date)
    date_range_str = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"
    
    # Get staff ID from request
    staff_id = request.GET.get('staff_id')
    
    # Get all active staff, excluding drivers
    all_staff = Staff.objects.filter(is_active=True).exclude(role='driver')
    
    # Get specific staff member if requested
    selected_staff = None
    staff_data = None
    
    if staff_id:
        try:
            selected_staff = Staff.objects.get(id=staff_id)
            
            # Get all payroll records for this staff member in the date range
            payroll_records = PayrollManager.objects.filter(
                staff=selected_staff,
                delivery__date__range=date_range
            ).select_related('delivery', 'delivery__vehicle')
            
            # Calculate payment totals
            payment_data = payroll_records.aggregate(
                role_payment=Sum('role_pay'),
                loader_payment=Sum('loader_pay'),
                total_payment=Sum('total_pay'),
                delivery_count=Count('delivery', distinct=True)
            )
            
            role_payment = payment_data['role_payment'] or Decimal('0.00')
            loader_payment = payment_data['loader_payment'] or Decimal('0.00')
            total_payment = payment_data['total_payment'] or Decimal('0.00')
            delivery_count = payment_data['delivery_count'] or 0
            
            # Check if a PaymentPeriod already exists for this staff and date range
            existing_period = PaymentPeriod.objects.filter(
                staff=selected_staff,
                period_start=start_date,
                period_end=end_date
            ).first()
            
            # Get delivery details for this staff
            deliveries = payroll_records.order_by('-delivery__date')
            
            staff_data = {
                'staff': selected_staff,
                'role_payment': role_payment,
                'loader_payment': loader_payment,
                'total_payment': total_payment,
                'delivery_count': delivery_count,
                'existing_period': existing_period,
                'is_paid': existing_period.is_paid if existing_period else False,
                'payment_date': existing_period.payment_date if existing_period else None,
                'deliveries': deliveries
            }
            
        except Staff.DoesNotExist:
            messages.error(request, f'Staff with ID {staff_id} not found.')
    
    # Process form submission for creating payment period
    if request.method == 'POST' and 'create_payment_period' in request.POST and selected_staff:
        # Calculate payments for this staff and period
        payments = PayrollManager.objects.filter(
            staff=selected_staff,
            delivery__date__range=date_range
        ).aggregate(
            role_payment=Sum('role_pay'),
            loader_payment=Sum('loader_pay'),
            total_payment=Sum('total_pay')
        )
        
        role_payment = payments['role_payment'] or 0
        loader_payment = payments['loader_payment'] or 0
        total_payment = payments['total_payment'] or 0
        
        # Create or update payment period
        payment_period, created = PaymentPeriod.objects.update_or_create(
            staff=selected_staff,
            period_start=start_date,
            period_end=end_date,
            defaults={
                'role_payment': role_payment,
                'loader_payment': loader_payment,
                'total_payment': total_payment,
                'admin': request.user
            }
        )
        
        if created:
            messages.success(request, f'Successfully created payment period for {selected_staff.name}.')
        else:
            messages.success(request, f'Successfully updated payment period for {selected_staff.name}.')
        
        return redirect(f"{request.path}?staff_id={staff_id}&start_date={start_date}&end_date={end_date}")
    
    # Process form submission for marking payment as paid
    if request.method == 'POST' and 'mark_paid' in request.POST and selected_staff:
        try:
            payment_period = PaymentPeriod.objects.get(
                staff=selected_staff,
                period_start=start_date,
                period_end=end_date
            )
            payment_period.is_paid = True
            payment_period.payment_date = timezone.now().date()
            payment_period.save()
            
            messages.success(request, f'Payment for {selected_staff.name} marked as paid.')
        except PaymentPeriod.DoesNotExist:
            # If payment period doesn't exist, create it first and mark as paid
            payments = PayrollManager.objects.filter(
                staff=selected_staff,
                delivery__date__range=date_range
            ).aggregate(
                role_payment=Sum('role_pay'),
                loader_payment=Sum('loader_pay'),
                total_payment=Sum('total_pay')
            )
            
            role_payment = payments['role_payment'] or 0
            loader_payment = payments['loader_payment'] or 0
            total_payment = payments['total_payment'] or 0
            
            PaymentPeriod.objects.create(
                staff=selected_staff,
                period_start=start_date,
                period_end=end_date,
                role_payment=role_payment,
                loader_payment=loader_payment,
                total_payment=total_payment,
                is_paid=True,
                payment_date=timezone.now().date(),
                admin=request.user
            )
            
            messages.success(request, f'Payment period created and marked as paid for {selected_staff.name}.')
        
        return redirect(f"{request.path}?staff_id={staff_id}&start_date={start_date}&end_date={end_date}")
    
    # Handle CSV export
    if request.GET.get('export') == 'csv' and selected_staff and staff_data:
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{selected_staff.name}_payroll_{start_date.strftime("%Y%m%d")}_{end_date.strftime("%Y%m%d")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Delivery Date', 'Vehicle', 'Turnboy Payment', 'Loader Payment', 'Total Payment'])
        
        for delivery in staff_data['deliveries']:
            writer.writerow([
                delivery.delivery.date.strftime('%Y-%m-%d'),
                delivery.delivery.vehicle.plate_number if delivery.delivery.vehicle else 'N/A',
                delivery.role_pay,
                delivery.loader_pay,
                delivery.total_pay
            ])
        
        # Add summary row
        writer.writerow(['', '', '', '', ''])
        writer.writerow(['SUMMARY', '', staff_data['role_payment'], staff_data['loader_payment'], staff_data['total_payment']])
        
        return response
    
    context = {
        'page_title': 'Individual Staff Payroll',
        'all_staff': all_staff,
        'selected_staff': selected_staff,
        'staff_data': staff_data,
        'start_date': start_date,
        'end_date': end_date,
        'date_range_str': date_range_str,
    }
    
    return render(request, 'payroll/individual_payroll.html', context)


@login_required
def mark_period_paid(request, period_id):
    """Mark a payment period as paid"""
    if request.method == 'POST':
        try:
            period = PaymentPeriod.objects.get(id=period_id)
            period.is_paid = True
            period.payment_date = timezone.now().date()
            period.save()
            messages.success(request, f'Payment for {period.staff.name} marked as paid.')
        except PaymentPeriod.DoesNotExist:
            messages.error(request, 'Payment period not found.')
    
    # Return to the referring page or the period payroll page
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('period_payroll')

# View to create a form for the payment period
@login_required
def create_payment_period_form(request):
    """Create a new payment period form"""
    if request.method == 'POST':
        form = PaymentPeriodForm(request.POST)
        if form.is_valid():
            payment_period = form.save(commit=False)
            payment_period.admin = request.user
            
            # Calculate payments for this staff and period
            staff = payment_period.staff
            date_range = (payment_period.period_start, payment_period.period_end)
            
            payments = PayrollManager.objects.filter(
                staff=staff,
                delivery__date__range=date_range
            ).aggregate(
                role_payment=Sum('role_pay'),
                loader_payment=Sum('loader_pay'),
                total_payment=Sum('total_pay')
            )
            
            payment_period.role_payment = payments['role_payment'] or 0
            payment_period.loader_payment = payments['loader_payment'] or 0
            payment_period.total_payment = payments['total_payment'] or 0
            payment_period.save()
            
            messages.success(request, f'Payment period created for {staff.name}.')
            return redirect('period_payroll')
    else:
        form = PaymentPeriodForm()
    
    context = {
        'form': form,
        'page_title': 'Create Payment Period'
    }
    
    return render(request, 'payroll/payment_period_form.html', context)

# ////// End of Period Payroll View //////
