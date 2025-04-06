from django.db import models
from django.db.models import Sum, Count, Q
from django.utils import timezone
import calendar
from decimal import Decimal
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import models

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
        """Calculate total payment for this staff member for a specific month"""
        # Create timezone-aware start and end datetimes for the month.
        start_date = timezone.localtime(timezone.datetime(year, month, 1))
        _, last_day = calendar.monthrange(year, month)
        end_date = timezone.localtime(timezone.datetime(year, month, last_day, 23, 59, 59))

        total_payment = Decimal('0.00')

        # Efficient turnboy payment: Aggregate turnboy payments for deliveries in the month.
        if self.role == 'turnboy':
            turnboy_payment = Delivery.objects.filter(
                turnboy=self,
                date__range=(start_date, end_date)
            ).aggregate(
                total_payment=Sum('turnboy_payment')
            )['total_payment'] or Decimal('0.00')
            total_payment += turnboy_payment

        # Efficient loader payment: Use annotated loader assignments.
        if self.is_loader:
            loader_assignments = (
                LoaderAssignment.objects
                .select_related('delivery')
                .filter(
                    loader=self,
                    delivery__date__range=(start_date, end_date)
                )
                .annotate(num_loaders=Count('delivery__loaderassignment'))
            )
            for assignment in loader_assignments:
                num_loaders = assignment.num_loaders
                if num_loaders > 0:
                    loader_payment = assignment.delivery.loading_amount / Decimal(num_loaders)
                    total_payment += loader_payment

        return total_payment

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
        max_length=20, choices=STATUS_CHOICES, default='pending',
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
        """Include turnboy if they helped with loading"""
        count = self.loaderassignment_set.count()
        if self.turnboy_loaded:
            count += 1
        return count

    def per_loader_amount(self):
        """Split loading money across actual loaders + turnboy if they helped"""
        num = self.total_loader_count()
        return self.loading_amount / Decimal(num) if num > 0 else Decimal('0.00')

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
    # Automatically calculate total pay when saving or updating the record.
    def clean(self):
        self.total_pay = self.turnboy_pay + self.loader_pay

    def save(self, *args, **kwargs):
        self.full_clean()  # ensures clean() is always called
        super().save(*args, **kwargs)


# # ===================================================
# # Signal Handler(s)
# # ===================================================
# Signal to update or create PayrollManager records when a LoaderAssignment is created or updated.
# This ensures that the payroll is always in sync with the loader assignments.
@receiver(post_save, sender=LoaderAssignment)
def update_payroll_on_loader_assignment(sender, instance, **kwargs):
    delivery = instance.delivery
    loader = instance.loader
    per_loader_pay = delivery.per_loader_amount()

    # Check if loader is also turnboy
    is_turnboy = loader == delivery.turnboy
    turnboy_pay = delivery.turnboy_payment if is_turnboy else Decimal('0.00')

    PayrollManager.objects.update_or_create(
        staff=loader,
        delivery=delivery,
        defaults={
            'turnboy_pay': turnboy_pay,
            'loader_pay': per_loader_pay,
        }
    )
# Signal to delete PayrollManager records when a LoaderAssignment is deleted.
@receiver(post_delete, sender=LoaderAssignment)
def delete_payroll_on_loader_remove(sender, instance, **kwargs):
    # Clean up PayrollManager if loader is removed from delivery
    PayrollManager.objects.filter(
        staff=instance.loader,
        delivery=instance.delivery
    ).delete()

# Signal to assign turnboy as loader if no loaders are assigned to the delivery.
# This ensures that the turnboy is always included in the loader assignments if they are also a loader.

@receiver(post_save, sender=Delivery)
def assign_turnboy_as_loader_if_needed(sender, instance, created, **kwargs):
    loaders = instance.get_loaders()

    # If no loaders and turnboy is also a loader, assign them
    if not loaders and instance.turnboy.is_loader:
        LoaderAssignment.objects.get_or_create(
            delivery=instance,
            loader=instance.turnboy
        )

@receiver(post_delete, sender=Delivery)
def cleanup_on_delivery_delete(sender, instance, **kwargs):
    # Clean up all loader assignments and payroll records on delivery deletion
    LoaderAssignment.objects.filter(delivery=instance).delete()
    PayrollManager.objects.filter(delivery=instance).delete()




