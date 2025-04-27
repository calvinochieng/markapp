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

@login_required
def dashboard(request):
    """
    Enhanced dashboard view showing comprehensive staff payment information
    with filtering options for custom date ranges rather than just month/year
    """
    # Get today's date
    today = timezone.now().date()
    
    # Default date range: last 30 days if no dates are specified
    default_end_date = today
    default_start_date = today - timezone.timedelta(days=30)
    
    # Get selected date range from request parameters
    try:
        start_date = request.GET.get('start_date')
        start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else default_start_date
        
        end_date = request.GET.get('end_date')
        end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else default_end_date
        
        # Ensure end_date is not before start_date
        if end_date < start_date:
            end_date = start_date
    except (ValueError, TypeError):
        # If any errors in parsing dates, use defaults
        start_date = default_start_date
        end_date = default_end_date
    
    # Create date range tuple
    date_range = (start_date, end_date)
    
    # Deliveries for the selected period - using select_related for optimization
    deliveries = (Delivery.objects
                 .filter(date__range=date_range)
                 .select_related('vehicle', 'driver')
                 .prefetch_related(
                     'staffassignment_set__staff'
                 )
                 .order_by('-date', '-time'))
    
    # Aggregate delivery statistics in a single query
    delivery_stats = deliveries.aggregate(
        total_loading=Sum('loading_amount'),
        delivery_count=Count('id'),
        completed_count=Count('id', filter=Q(status='completed')),
        in_progress_count=Count('id', filter=Q(status='in_progress')),
        pending_count=Count('id', filter=Q(status='pending'))
    )
    
    # Staff statistics
    staff_stats = {
        'active_total': Staff.objects.filter(is_active=True).count(),
        'drivers': Staff.objects.filter(role='driver', is_active=True).count(),
        'turnboys': Staff.objects.filter(role='turnboy', is_active=True).count(),
        'loaders': Staff.objects.filter(Q(role='loader') | Q(is_loader=True), is_active=True).count(),
    }
    
    # Vehicle statistics
    vehicle_stats = {
        'active_total': Vehicle.objects.filter(is_active=True).count(),
        'trucks': Vehicle.objects.filter(vehicle_type='truck', is_active=True).count(),
        'vans': Vehicle.objects.filter(vehicle_type='van', is_active=True).count(),
        'buses': Vehicle.objects.filter(vehicle_type='bus', is_active=True).count(),
    }
    
    # Top destinations
    top_destinations = (Delivery.objects
                       .filter(date__range=date_range)
                       .values('destination')
                       .annotate(count=Count('id'))
                       .order_by('-count')[:5])
    
    # Top performing staff members - now includes all drivers using the driver field
    top_drivers = (Staff.objects
                   .filter(role='driver')
                   .annotate(
                       delivery_count=Count(
                           'driver_deliveries',
                           filter=Q(driver_deliveries__date__range=date_range)
                       )
                   )
                   .order_by('-delivery_count')[:5])
    
    # Top performing turnboys - using StaffAssignment model
    top_turnboys = (Staff.objects
                    .filter(role='turnboy')
                    .annotate(
                        delivery_count=Count(
                            'staffassignment',
                            filter=Q(
                                staffassignment__role='turnboy',
                                staffassignment__delivery__date__range=date_range
                            )
                        )
                    )
                    .order_by('-delivery_count')[:5])
    
    # Calculate payment statistics from PayrollManager for non-driver roles
    payroll_stats = PayrollManager.objects.filter(
        delivery__date__range=date_range,
        staff__role__in=['turnboy', 'loader']  # Only include non-driver roles
    ).aggregate(
        total_role_pay=Sum('role_pay'),
        total_loader_pay=Sum('loader_pay'),
        total_pay=Sum('total_pay')
    )
    
    # Payment statistics by role (excluding drivers)
    turnboy_payments = PayrollManager.objects.filter(
        delivery__date__range=date_range,
        staff__role='turnboy'
    ).aggregate(
        role_pay=Sum('role_pay'),
        loader_pay=Sum('loader_pay'),
        total=Sum('total_pay')
    )
    
    loader_payments = PayrollManager.objects.filter(
        delivery__date__range=date_range,
        staff__role='loader'
    ).aggregate(
        role_pay=Sum('role_pay'),
        loader_pay=Sum('loader_pay'),
        total=Sum('total_pay')
    )
    
    # Calculate total loading amount
    total_loading_amount = delivery_stats['total_loading'] or 0
    
    # Calculate total payments by role
    total_role_payments = payroll_stats['total_role_pay'] or 0
    total_loader_payments = payroll_stats['total_loader_pay'] or 0
    total_turnboy_payments = turnboy_payments['total'] or 0
    
    # Calculate total deliveries amount
    total_deliveries_amount = total_loading_amount
    
    # Recently completed deliveries
    recent_deliveries = deliveries.filter(status='completed')[:5]
    
    # Payments from PaymentPeriod model that overlap with the selected date range
    period_payments = PaymentPeriod.objects.filter(
        Q(period_start__range=date_range) | 
        Q(period_end__range=date_range) |
        Q(period_start__lte=start_date, period_end__gte=end_date),
        staff__role__in=['turnboy', 'loader']  # Only non-driver roles
    ).aggregate(
        paid_amount=Sum('total_payment', filter=Q(is_paid=True)),
        unpaid_amount=Sum('total_payment', filter=Q(is_paid=False)),
        total_amount=Sum('total_payment')
    )
    
    # /////


    # ... inside your dashboard view ...

    # 1. Fetch relevant Staff Assignments (instead of aggregating directly)
    helper_assignments = StaffAssignment.objects.filter(
        delivery__date__range=date_range,
        helped_loading=True
    ).select_related('staff', 'delivery') # Crucial to fetch related data efficiently

    # 2. Process in Python to calculate earnings per staff member
    loading_earnings_by_staff = defaultdict(lambda: {'loading_count': 0, 'loading_earnings': Decimal(0)})

    for assignment in helper_assignments:
        staff_name = assignment.staff.name
        # Call the model method here in Python
        earnings = assignment.delivery.per_loader_amount()

        loading_earnings_by_staff[staff_name]['loading_count'] += 1
        loading_earnings_by_staff[staff_name]['loading_earnings'] += earnings

    # 3. Convert to list and sort to get top helpers
    loading_helpers_list = [
        {'staff__name': name, **data}
        for name, data in loading_earnings_by_staff.items()
    ]

    # Sort by count first (desc), then maybe earnings (desc) as a tie-breaker
    loading_helpers_list.sort(key=lambda x: (x['loading_count'], x['loading_earnings']), reverse=True)

    # 4. Get the top 5 for the context
    loading_helpers = loading_helpers_list[:5]

    # ... rest of your view, update context with this 'loading_helpers' ...
    # Make sure the template ('dashboard/dashboard.html') is updated to expect
    # 'staff__name', 'loading_count', and 'loading_earnings' keys for each item
    # in the 'loading_helpers' list.

    # Example context update:
    context = {
        # ... other context variables ...
        'loading_helpers': loading_helpers,
        # ...
    }


    # /////
    
    context = {
        # Date range information
        'start_date': start_date,
        'end_date': end_date,
        'date_range': f"{start_date.strftime('%d %b %Y')} - {end_date.strftime('%d %b %Y')}",
        
        # Deliveries information
        'deliveries': deliveries[:10],  # Limit to 10 most recent for dashboard
        'total_deliveries': delivery_stats['delivery_count'] or 0,
        'completed_deliveries': delivery_stats['completed_count'] or 0,
        'in_progress_deliveries': delivery_stats['in_progress_count'] or 0,
        'pending_deliveries': delivery_stats['pending_count'] or 0,
        'recent_deliveries': recent_deliveries,
        
        # Staff information
        'active_staff': staff_stats['active_total'],
        'active_drivers': staff_stats['drivers'],
        'active_turnboys': staff_stats['turnboys'],
        'loaders_available': staff_stats['loaders'],
        'top_drivers': top_drivers,
        'top_turnboys': top_turnboys,
        'loading_helpers': loading_helpers,
        
        # Vehicle information
        'active_vehicles': vehicle_stats['active_total'],
        'active_trucks': vehicle_stats['trucks'],
        'active_vans': vehicle_stats['vans'],
        'active_buses': vehicle_stats['buses'],
        
        # Delivery destinations
        'top_destinations': top_destinations,
        
        # Payment information (excluding drivers)
        'total_deliveries_amount': total_deliveries_amount,
        'total_loading_amount': total_loading_amount,
        'total_role_payments': total_role_payments,
        'total_loader_payments': total_loader_payments,
        'total_turnboy_payments': total_turnboy_payments,
        'turnboy_payments': {
            'role': turnboy_payments['role_pay'] or 0,
            'loader': turnboy_payments['loader_pay'] or 0,
            'total': turnboy_payments['total'] or 0
        },
        'loader_payments': {
            'role': loader_payments['role_pay'] or 0,
            'loader': loader_payments['loader_pay'] or 0,
            'total': loader_payments['total'] or 0
        },
        'total_pay': payroll_stats['total_pay'] or 0,
        
        # Period payment stats (excluding drivers)
        'period_paid': period_payments['paid_amount'] or 0,
        'period_unpaid': period_payments['unpaid_amount'] or 0,
        'period_total': period_payments['total_amount'] or 0,
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
        writer.writerow(['Delivery Date', 'Vehicle', 'Role Payment', 'Loader Payment', 'Total Payment'])
        
        for delivery in staff_data['deliveries']:
            writer.writerow([
                delivery.delivery.date.strftime('%Y-%m-%d'),
                delivery.delivery.vehicle.name if delivery.delivery.vehicle else 'N/A',
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
