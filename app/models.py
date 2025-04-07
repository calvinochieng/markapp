from django.db import models
from django.db.models import Sum, Count, Q
from django.utils import timezone
import calendar
from decimal import Decimal
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

# ===================================================
# Staff Model
# ===================================================
class Staff(models.Model):
    """Staff model to represent drivers, turnboys, and loaders"""
    ROLE_CHOICES = [
        ('driver', 'Driver'),
        ('turnboy', 'Turnboy'),
        ('loader', 'Loader'),
    ]
    
    name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, db_index=True)
    is_loader = models.BooleanField(default=False, help_text="Check if this person also works as a loader")
    date_joined = models.DateField(default=timezone.now)
    is_active = models.BooleanField(default=True, db_index=True)
    
    def __str__(self):
        return f"{self.name} ({self.get_role_display()})"
      
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
            total_turnboy=Sum('turnboy_pay'),
            total_loader=Sum('loader_pay'),
            total=Sum('total_pay')
        )
        
        turnboy_payment = payments['total_turnboy'] or Decimal('0.00')
        loader_payment = payments['total_loader'] or Decimal('0.00')
        total_payment = payments['total'] or Decimal('0.00')
        
        return {
            'turnboy_payment': turnboy_payment,
            'loader_payment': loader_payment,
            'total_payment': total_payment
        }
# ===================================================
# Vehicle Model
# ===================================================
class Vehicle(models.Model):
    """Vehicle model to represent lorries used for deliveries"""    
    VEHICLE_TYPE_CHOICES = [
        ('truck', 'Truck'),
        ('van', 'Van'),
        ('bus', 'Bus'),
        ('other', 'Other'),
    ]
    
    plate_number = models.CharField(max_length=20, unique=True)
    vehicle_type = models.CharField(max_length=50, choices=VEHICLE_TYPE_CHOICES, blank=True)
    capacity = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)  # Added index for performance
    
    def __str__(self):
        return f"{self.plate_number} ({self.get_vehicle_type_display()}) - {self.capacity}"


# ===================================================
# Delivery Model
# ===================================================
class Delivery(models.Model):
    """Delivery model to track individual delivery trips"""

    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
    ]
    
    date = models.DateField(db_index=True)
    delivery_note_image = models.ImageField(upload_to='delivery_notes/', blank=True, null=True)
    time = models.TimeField()
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, db_index=True)
    driver = models.ForeignKey(
        Staff, related_name='driver_deliveries', on_delete=models.CASCADE,
        limit_choices_to={'role': 'driver'}, db_index=True
    )
    turnboy = models.ForeignKey(
        Staff, related_name='turnboy_deliveries', on_delete=models.CASCADE,
        limit_choices_to={'role': 'turnboy'}, db_index=True
    )
    turnboy_payment = models.DecimalField(
        max_digits=10, decimal_places=2, default=200.00,
        help_text="Payment for the turnboy for this delivery; can be adjusted based on distance"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='completed',
        help_text="Status of the delivery"
    )    
    destination = models.CharField(max_length=100)
    items_carried = models.TextField()
    loading_amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Total amount paid for loading"
    )
    notes = models.TextField(blank=True)
    turnboy_loaded = models.BooleanField(
        default=False,
        help_text="Set to True if the turnboy also helped with loading"
    )

    class Meta:
        verbose_name_plural = "Deliveries"
        ordering = ['-date']

    def __str__(self):
        return f"Delivery to {self.destination} on {self.date} - {self.vehicle.plate_number} (Driver: {self.driver.name}, Turnboy: {self.turnboy.name})"

    def get_loaders(self):
        """Return a list of all loaders for this delivery"""
        return [assignment.loader for assignment in self.loaderassignment_set.all()]

    def total_loader_count(self):
        """
        Count the total number of people loading, including the turnboy if they helped
        """
        # Count regular loaders from LoaderAssignment
        count = self.loaderassignment_set.count()
        
        # Add turnboy if they helped with loading
        if self.turnboy_loaded:
            count += 1
        
        return count

    def per_loader_amount(self):
        """
        Calculate payment per loader, splitting loading money across all loaders
        (including turnboy if they helped)
        """
        num_loaders = self.total_loader_count()
        
        if num_loaders == 0:
            return Decimal('0.00')
            
        # Split loading amount evenly among all loaders
        return self.loading_amount / Decimal(num_loaders)

# ===================================================
# LoaderAssignment Model
# ===================================================
class LoaderAssignment(models.Model):
    """Model to track which loaders worked on which deliveries"""
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE)
    loader = models.ForeignKey(
        Staff, on_delete=models.CASCADE, 
        limit_choices_to={'is_loader': True}
    )
    
    class Meta:
        unique_together = ('delivery', 'loader')  # Ensures a loader can only be assigned once per delivery

    def __str__(self):
        return f"{self.loader.name} - {self.delivery}"

# ===================================================
# MonthlyPayment Model
# ===================================================
class MonthlyPayment(models.Model):
    """Model to store calculated monthly payments"""
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    year = models.IntegerField()
    month = models.IntegerField()
    turnboy_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    loader_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_payment = models.DecimalField(max_digits=10, decimal_places=2)
    is_paid = models.BooleanField(default=False)
    payment_date = models.DateField(null=True, blank=True)
    
    class Meta:
        unique_together = ('staff', 'year', 'month')
    
    def __str__(self):
        month_name = calendar.month_name[self.month]
        return f"{self.staff.name} - {month_name} {self.year}"


# # ===================================================
# # PayrollManager Model
# # ===================================================
class PayrollManager(models.Model):
    """Stores payments per delivery per staff member"""
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE)
    turnboy_pay = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    loader_pay = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_pay = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    date_recorded = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('staff', 'delivery')
        
    def save(self, *args, **kwargs):
        # Always calculate total_pay as the sum of turnboy_pay and loader_pay
        self.total_pay = self.turnboy_pay + self.loader_pay
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"{self.staff.name} - {self.delivery} - ₦{self.total_pay}"
# # ===================================================
# # Signal Handler(s)
# # ===================================================
@receiver(post_save, sender=Delivery)
@receiver(post_delete, sender=Delivery)
def update_payroll_manager(sender, instance, **kwargs):
    """
    Update payroll records when a delivery is saved or deleted.
    This handles both turnboy payments and recalculates loader payments.
    """
    # If a Delivery is deleted, clean up related records
    if kwargs.get('signal') == post_delete:
        PayrollManager.objects.filter(delivery=instance).delete()
        return

    # 1. Update turnboy's payroll record
    turnboy = instance.turnboy
    turnboy_pay = instance.turnboy_payment
    
    # Calculate per-loader payment amount
    per_loader_amount = instance.per_loader_amount()
    
    # Handle turnboy's loader payment if they helped with loading
    if instance.turnboy_loaded:
        PayrollManager.objects.update_or_create(
            staff=turnboy,
            delivery=instance,
            defaults={
                'turnboy_pay': turnboy_pay,
                'loader_pay': per_loader_amount,
                'total_pay': turnboy_pay + per_loader_amount,
            }
        )
    else:
        # Turnboy didn't help with loading - only gets turnboy payment
        PayrollManager.objects.update_or_create(
            staff=turnboy,
            delivery=instance,
            defaults={
                'turnboy_pay': turnboy_pay,
                'loader_pay': Decimal('0.00'),
                'total_pay': turnboy_pay,
            }
        )
    
    # 2. Update all other loaders' payroll records
    loaders = instance.get_loaders()
    for loader in loaders:
        # Skip if this loader is also the turnboy (already handled above)
        if loader == turnboy:
            continue
            
        PayrollManager.objects.update_or_create(
            staff=loader,
            delivery=instance,
            defaults={
                'turnboy_pay': Decimal('0.00'),  # Not a turnboy payment
                'loader_pay': per_loader_amount,
                'total_pay': per_loader_amount,
            }
        )


@receiver(post_save, sender=LoaderAssignment)
@receiver(post_delete, sender=LoaderAssignment)
def update_payroll_on_loader_assignment_change(sender, instance, **kwargs):
    """
    When loader assignments change (add/remove), recalculate all payroll records
    for this delivery to ensure per_loader amounts are correct.
    """
    delivery = instance.delivery
    
    # We'll use the delivery signal handler to recalculate everything
    # This ensures all payroll records are updated when the number of loaders changes
    update_payroll_manager(Delivery, delivery, raw=False)