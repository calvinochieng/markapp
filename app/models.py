from django.db import models
from django.db.models import Sum, Count, Q
from django.utils import timezone
import calendar
# Import User
from django.contrib.auth.models import User
from decimal import Decimal
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.exceptions import ValidationError

# ===================================================
# Staff Model
# ===================================================
class Staff(models.Model):
    admin = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    """Staff model to represent turnboys and loaders"""
    ROLE_CHOICES = [
        ('turnboy', 'Turnboy'),
        ('loader', 'Loader'),
    ]
    
    name = models.CharField(max_length=100, unique=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, db_index=True, default='turnboy')
    is_loader = models.BooleanField(default=True, help_text="Check if this person can also work as a loader")
    
    date_joined = models.DateField(default=timezone.now)
    is_active = models.BooleanField(default=True, db_index=True)
    
    def __str__(self):
        return f"{self.name} ({self.get_role_display()})"
    
    def clean(self):
        # Ensure loader role always has is_loader=True
        if self.role == 'loader' and not self.is_loader:
            self.is_loader = True
        super().clean()
        
    def get_monthly_payment(self, year, month):
        """
        Calculate total payment for this staff member for a specific month
        based on completed PayrollManager records
        """
        # Create timezone-aware start and end dates for the month
        start_date = timezone.datetime(year, month, 1).date()
        _, last_day = calendar.monthrange(year, month)
        end_date = timezone.datetime(year, month, last_day).date()

        # Use PayrollManager records for more accurate payment calculation
        payments = PayrollManager.objects.filter(
            staff=self,
            delivery__date__range=(start_date, end_date)
        ).aggregate(
            total_role=Sum('role_pay'),
            total_loader=Sum('loader_pay'),
            total=Sum('total_pay')
        )
        
        role_payment = payments['total_role'] or Decimal('0.00')
        loader_payment = payments['total_loader'] or Decimal('0.00')
        total_payment = payments['total'] or Decimal('0.00')
        
        return {
            'role_payment': role_payment,
            'loader_payment': loader_payment,
            'total_payment': total_payment
        }   
        
        
# ===================================================
# Vehicle Model
# ===================================================
class Vehicle(models.Model):
    admin = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    """Vehicle model to represent lorries used for deliveries"""    
    VEHICLE_TYPE_CHOICES = [
        ('truck', 'Truck'),
        ('van', 'Van'),
        ('bus', 'Bus'),
        ('other', 'Other'),
    ]
    # Keep driver as a string field, not related to Staff model
    driver = models.CharField(max_length=100, blank=True, null=True)
    plate_number = models.CharField(max_length=20, unique=True)
    vehicle_type = models.CharField(max_length=50, choices=VEHICLE_TYPE_CHOICES, blank=True)
    capacity = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)  # Added index for performance
    
    def __str__(self):
        driver_display = f" - Driver: {self.driver}" if self.driver else ""
        return f"{self.plate_number} ({self.get_vehicle_type_display()}) - {self.capacity}{driver_display}"


# ===================================================
# Delivery Model
# ===================================================

class Delivery(models.Model):
    admin = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    """Delivery model to track individual delivery trips"""

    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
    ]
    
    date = models.DateField(db_index=True)
    delivery_note_image = models.ImageField(upload_to='delivery_notes/', blank=True, null=True)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, db_index=True)
    turnboy_payment_rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=200.00,
        help_text="Base payment rate for turnboys for this delivery; can be adjusted based on distance"
    )   
    destination = models.CharField(max_length=100)
    items_carried = models.TextField()
    loading_amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Total amount paid for loading"
    )
    notes = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='completed')

    class Meta:
        verbose_name_plural = "Deliveries"
        ordering = ['-date']

    def __str__(self):
        driver_name = self.vehicle.driver if self.vehicle and self.vehicle.driver else "No driver"
        turnboys = ", ".join([assign.staff.name for assign in self.staffassignment_set.filter(role='turnboy')])
        turnboys_str = f" (Turnboys: {turnboys})" if turnboys else ""
        
        return f"Delivery to {self.destination} on {self.date} - {self.vehicle.plate_number} (Driver: {driver_name}){turnboys_str}"

    def get_loaders(self):
        """Return a list of all staff who helped with loading for this delivery"""
        return Staff.objects.filter(
            staffassignment__delivery=self,
            staffassignment__helped_loading=True
        ).distinct()

    def total_loader_count(self):
        """Count the total number of people who helped with loading"""
        return self.staffassignment_set.filter(helped_loading=True).count()

    def per_loader_amount(self):
        """
        Calculate payment per loader, splitting loading money across all loaders
        """
        num_loaders = self.total_loader_count()
        
        if num_loaders == 0:
            return Decimal('0.00')
            
        # Split loading amount evenly among all loaders
        return self.loading_amount / Decimal(num_loaders)

# ===================================================
# LoaderAssignment Model and Staff Assignment
# ===================================================
class StaffAssignment(models.Model):
    """Model to track which staff worked on which deliveries and in what capacity"""
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE)
    staff = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        limit_choices_to={'role__in': ['turnboy', 'loader']},  # Only include these
    )
    role = models.CharField(max_length=20, choices=Staff.ROLE_CHOICES)  # Use Staff model choices
    helped_loading = models.BooleanField(
        default=False, 
        help_text="Set to True if this staff member helped with loading"
    )
    
    class Meta:
        unique_together = ('delivery', 'staff', 'role')  # Staff can have only one role per delivery
    
    def __str__(self):
        return f"{self.staff.name} as {self.get_role_display()} for {self.delivery}"
    
    def clean(self):
        # Ensure loaders always have helped_loading set to True
        if self.role == 'loader':
            self.helped_loading = True
        
        super().clean()
    
    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        self.clean()
        return super().save(force_insert, force_update, using, update_fields)


# ===================================================
# MonthlyPayment Model
# ===================================================
class MonthlyPayment(models.Model):
    admin = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    """Model to store calculated monthly payments"""
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    year = models.IntegerField()
    month = models.IntegerField()
    role_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0, 
                                       help_text="Payment for the staff's primary role (driver, turnboy, etc.)")
    loader_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_payment = models.DecimalField(max_digits=10, decimal_places=2)
    is_paid = models.BooleanField(default=False)
    payment_date = models.DateField(null=True, blank=True)
    
    class Meta:
        unique_together = ('staff', 'year', 'month')
    
    def __str__(self):
        month_name = calendar.month_name[self.month]
        return f"{self.staff.name} - {month_name} {self.year}"
    
    def save(self, *args, **kwargs):
        # Always ensure total_payment is the sum of role_payment and loader_payment
        self.total_payment = self.role_payment + self.loader_payment
        super().save(*args, **kwargs)

class PaymentPeriod(models.Model):
    admin = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    """Model to store calculated payments for custom periods"""
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    period_start = models.DateField()
    period_end = models.DateField()
    role_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    loader_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_payment = models.DecimalField(max_digits=10, decimal_places=2)
    is_paid = models.BooleanField(default=False)
    payment_date = models.DateField(null=True, blank=True)
    
    class Meta:
        # Ensure staff doesn't have overlapping payment periods
        constraints = [
            models.CheckConstraint(
                check=models.Q(period_end__gte=models.F('period_start')),
                name='period_end_gte_period_start'
            )
        ]
    
    def __str__(self):
        return f"{self.staff.name} - {self.period_start} to {self.period_end}"
    
    @property
    def period_name(self):
        """Generate a readable name for this period"""
        start_str = self.period_start.strftime("%d %b %Y")
        end_str = self.period_end.strftime("%d %b %Y")
        return f"{start_str} to {end_str}"
    
    def save(self, *args, **kwargs):
        # Always ensure total_payment is the sum of role_payment and loader_payment
        self.total_payment = self.role_payment + self.loader_payment
        super().save(*args, **kwargs)

# ===================================================
# PayrollManager Model
# ===================================================
class PayrollManager(models.Model):
    admin = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    """Stores payments per delivery per staff member"""
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE)
    role_pay = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Payment for the staff's primary role (turnboy, etc.)"
    )
    loader_pay = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Payment for loading activities if the staff helped with loading"
    )
    total_pay = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    date_recorded = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('staff', 'delivery')
        
    def save(self, *args, **kwargs):
        # Always calculate total_pay as the sum of role_pay and loader_pay
        self.total_pay = self.role_pay + self.loader_pay
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"{self.staff.name} - {self.delivery} - Ksh {self.total_pay}"

# ===================================================
# Signal Handler(s)
# ===================================================
@receiver(post_save, sender=Delivery)
@receiver(post_delete, sender=Delivery)
def update_payroll_manager(sender, instance, **kwargs):
    """
    Update payroll records when a delivery is saved or deleted.
    This handles all payroll scenarios according to business rules:
    
    1. Single turnboy, no helpers: Turnboy gets fixed rate + full loading amount
    2. Two turnboys, both loading: Each gets fixed rate + equal split of loading
    3. Two turnboys, only one loads: Loading turnboy gets fixed + full loading, other only fixed
    4. Turnboy + other loaders: Loading amount split equally among all loading helpers
    """
    # If a Delivery is deleted, clean up related records
    if kwargs.get('signal') == post_delete:
        PayrollManager.objects.filter(delivery=instance).delete()
        return

    # Get all staff who helped with loading
    loading_staff = instance.get_loaders()
    loading_count = len(loading_staff)
    
    # Get all turnboys for this delivery
    turnboy_assignments = instance.staffassignment_set.filter(role='turnboy')
    
    # Process all staff assignments based on the four scenarios
    for assignment in instance.staffassignment_set.all():
        # Base role pay (always paid)
        role_pay = instance.turnboy_payment_rate if assignment.role == 'turnboy' else Decimal('0.00')
        
        # Calculate loader pay based on whether they helped loading
        loader_pay = Decimal('0.00')
        
        if assignment.helped_loading and loading_count > 0:
            # Staff helped with loading, calculate their share
            per_loader = instance.loading_amount / Decimal(loading_count)
            loader_pay = per_loader
        
        # Update or create the payroll record
        PayrollManager.objects.update_or_create(
            staff=assignment.staff,
            delivery=instance,
            defaults={
                'role_pay': role_pay,
                'loader_pay': loader_pay,
                'total_pay': role_pay + loader_pay,
            }
        )


@receiver(post_save, sender=StaffAssignment)
@receiver(post_delete, sender=StaffAssignment)
def update_payroll_on_staff_assignment_change(sender, instance, **kwargs):
    """
    When staff assignments change (add/remove), recalculate all payroll records
    for this delivery to ensure per_loader amounts are correct.
    """
    if hasattr(instance, 'delivery'):
        delivery = instance.delivery
        
        # We'll use the delivery signal handler to recalculate everything
        update_payroll_manager(Delivery, delivery)