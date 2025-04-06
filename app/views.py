from django.shortcuts import render, redirect
from django.http import JsonResponse
from .models import *
import calendar
from django.db.models import Sum, Count
from django.utils import timezone

from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import logging
from django.contrib.auth.views import LoginView

logger = logging.getLogger(__name__)

from .forms import RegistrationForm

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


def index(request):
    return render(request, 'index.html')


class CustomLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True  # Redirects logged-in users away from login page
    
    def form_invalid(self, form):
        messages.error(self.request, 'Invalid username or password')
        return super().form_invalid(form)


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def dashboard(request):
    """Dashboard view showing staff payment information"""
    # Get current year and month
    current_year = timezone.now().year
    current_month = timezone.now().month
        
    # Total Deliveries
    deliveries = Delivery.objects.filter(date__year=current_year, date__month=current_month).order_by('-time')

    #  Active Staff members
    active_staff = Staff.objects.filter(is_active=True).count()

    # Active Vehicles
    active_vehicles = Vehicle.objects.filter(is_active=True).count()

    # Loaders Available
    loaders_available = Staff.objects.filter(is_loader=True, is_active=True).count()

    # Total Deliveries Amount
    total_loading_amount = deliveries.aggregate(Sum('loading_amount'))['loading_amount__sum'] or 0
    # Turnboy Payments
    total_turnboy_payments = deliveries.aggregate(Sum('turnboy_payment'))['turnboy_payment__sum'] or 0

    # Loader Payments + Turnboy Payments
    total_deliveries_amount =  total_loading_amount + total_turnboy_payments

        
    context = {
        'deliveries': deliveries,
        'total_deliveries': deliveries.count(),
        'active_staff': active_staff, 'loaders_available': loaders_available,
        'active_vehicles': active_vehicles,
        # Deliveries Payments
        'total_deliveries_amount': total_deliveries_amount,
          'total_loading_amount': total_loading_amount,
          'total_turnboy_payments': total_turnboy_payments,
        # Extra Details
        'current_month': calendar.month_name[current_month],
        'current_year': current_year,
    }
    
    return render(request, 'dashboard/dashboard.html', context)
