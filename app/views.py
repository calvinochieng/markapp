from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
# /////Django Query Imports////
from .models import *
from django.db.models import Sum, Count, Q

# ////Utils Imports////
import csv
from decimal import Decimal
from django.contrib import messages
from django.utils import timezone
import calendar

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

@login_required
def dashboard(request):
    """
    Enhanced dashboard view showing comprehensive staff payment information
    with filtering options for year/month selection
    """
    # Get selected year and month (defaulting to current if not specified)
    selected_year = int(request.GET.get('year', timezone.now().year))
    selected_month = int(request.GET.get('month', timezone.now().month))
    
    # Create date range for the selected month
    start_date = timezone.datetime(selected_year, selected_month, 1).date()
    _, last_day = calendar.monthrange(selected_year, selected_month)
    end_date = timezone.datetime(selected_year, selected_month, last_day).date()
    date_range = (start_date, end_date)
    
    # Deliveries for the selected month - using select_related for optimization
    deliveries = (Delivery.objects
                 .filter(date__range=date_range)
                 .select_related('vehicle', 'driver', 'turnboy')
                 .prefetch_related('loaderassignment_set__loader')
                 .order_by('-date', '-time'))
    
    # Aggregate delivery statistics in a single query
    delivery_stats = deliveries.aggregate(
        total_loading=Sum('loading_amount'),
        total_turnboy=Sum('turnboy_payment'),
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
        'loaders': Staff.objects.filter(is_loader=True, is_active=True).count(),
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
    
    # Top performing staff members (based on number of deliveries)
    top_drivers = (Staff.objects
                   .filter(role='driver')
                   .annotate(delivery_count=Count('driver_deliveries', 
                                                filter=Q(driver_deliveries__date__range=date_range)))
                   .order_by('-delivery_count')[:5])
    
    # Calculate payment statistics from PayrollManager
    payroll_stats = PayrollManager.objects.filter(
        delivery__date__range=date_range
    ).aggregate(
        total_turnboy_pay=Sum('turnboy_pay'),
        total_loader_pay=Sum('loader_pay'),
        total_pay=Sum('total_pay')
    )
    
    # Calculate total delivery amount
    total_loading_amount = delivery_stats['total_loading'] or 0
    total_turnboy_payments = delivery_stats['total_turnboy'] or 0
    total_deliveries_amount = total_loading_amount + total_turnboy_payments
    
    # Recently completed deliveries
    recent_deliveries = deliveries.filter(status='completed')[:5]
    
    # Create list of years and months for filter dropdown
    current_year = timezone.now().year
    years = range(current_year - 2, current_year + 1)  # Current year and 2 years back
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]
    
    context = {
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
        
        # Vehicle information
        'active_vehicles': vehicle_stats['active_total'],
        'active_trucks': vehicle_stats['trucks'],
        'active_vans': vehicle_stats['vans'],
        'active_buses': vehicle_stats['buses'],
        
        # Delivery destinations
        'top_destinations': top_destinations,
        
        # Payment information
        'total_deliveries_amount': total_deliveries_amount,
        'total_loading_amount': total_loading_amount,
        'total_turnboy_payments': total_turnboy_payments,
        'total_turnboy_pay': payroll_stats['total_turnboy_pay'] or 0,
        'total_loader_pay': payroll_stats['total_loader_pay'] or 0,
        'total_pay': payroll_stats['total_pay'] or 0,
        
        # Date information for filtering
        'selected_month': selected_month,
        'selected_month_name': calendar.month_name[selected_month],
        'selected_year': selected_year,
        'years': years,
        'months': months,
        'date_range': f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"
    }
    
    return render(request, 'dashboard/dashboard.html', context)


# /////Payroll View//////
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
    
    # Get all active staff members
    staff_query = Staff.objects.filter(is_active=True)
    
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
        if staff.role == 'driver':
            delivery_count = Delivery.objects.filter(
                driver=staff,
                date__range=date_range
            ).count()
        elif staff.role == 'turnboy':
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

