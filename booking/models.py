from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Sum
from django.db.models.functions import Coalesce


class Hotel(models.Model):
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=120)
    address = models.TextField(blank=True)
    description = models.TextField(blank=True)

    image = models.ImageField(
        upload_to="hotels/",
        blank=True,
        null=True
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hotels",
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"{self.name} ({self.city})"


class Room(models.Model):
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name="rooms")
    name = models.CharField(max_length=120)
    capacity = models.PositiveIntegerField(default=2)
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2)
    total_rooms = models.PositiveIntegerField(default=1)

    image = models.ImageField(
        upload_to="rooms/",
        blank=True,
        null=True
    )

    is_active = models.BooleanField(default=True)

    def available_rooms(self, check_in, check_out):
        # bookings that overlap with selected range
        booked = self.bookings.filter(
            status="confirmed",
            check_in__lt=check_out,
            check_out__gt=check_in
        ).aggregate(total=Coalesce(Sum("rooms_count"), 0))["total"]

        return max(self.total_rooms - booked, 0)


    def __str__(self):
        return f"{self.hotel.name} - {self.name}"


class Booking(models.Model):
    STATUS_CHOICES = (
        ("confirmed", "Confirmed"),
        ("cancelled", "Cancelled"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="bookings")
    check_in = models.DateField()
    check_out = models.DateField()
    rooms_count = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="confirmed")
    created_at = models.DateTimeField(auto_now_add=True)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)
    is_paid = models.BooleanField(default=False)
    amount_paise = models.PositiveIntegerField(default=0)  # total in paise


    def clean(self):
        if self.check_in >= self.check_out:
            raise ValidationError("Check-out must be after check-in.")
        if self.check_in < timezone.now().date():
            raise ValidationError("Check-in cannot be in the past.")
