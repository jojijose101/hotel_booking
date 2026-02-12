from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from datetime import date
from .models import Hotel, Room, Booking
from django.utils.dateparse import parse_date
import razorpay
import hmac
import hashlib
from django.conf import settings
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt



def hotel_list(request):
    q = (request.GET.get("q") or "").strip()
    city = (request.GET.get("city") or "").strip()

    hotels = Hotel.objects.all().order_by("name")

    if q:
        hotels = hotels.filter(name__icontains=q)
    if city:
        hotels = hotels.filter(city__icontains=city)

    return render(request, "bookings/hotel_list.html", {
        "hotels": hotels,
        "q": q,
        "city": city,
    })


def hotel_detail(request, hotel_id):
    hotel = get_object_or_404(Hotel, id=hotel_id)
    rooms = hotel.rooms.filter(is_active=True).order_by("price_per_night")

    check_in_raw = (request.GET.get("check_in") or "").strip()
    check_out_raw = (request.GET.get("check_out") or "").strip()

    check_in = parse_date(check_in_raw) if check_in_raw else None
    check_out = parse_date(check_out_raw) if check_out_raw else None

    availability = {}  # room_id -> available count

    if check_in and check_out and check_in < check_out:
        for r in rooms:
            availability[r.id] = r.available_rooms(check_in, check_out)

    return render(request, "bookings/hotel_details.html", {
        "hotel": hotel,
        "rooms": rooms,
        "check_in": check_in_raw,
        "check_out": check_out_raw,
        "availability": availability,
    })



@login_required
def book_room(request, room_id):
    room = get_object_or_404(Room, id=room_id, is_active=True)

    errors = {}
    preview_available = None

    # ✅ read query params first (works for GET opening the page)
    check_in_q = (request.GET.get("check_in") or "").strip()
    check_out_q = (request.GET.get("check_out") or "").strip()

    # ✅ values for form refill (GET uses query params, POST uses submitted values)
    if request.method == "POST":
        values = {
            "check_in": (request.POST.get("check_in") or "").strip(),
            "check_out": (request.POST.get("check_out") or "").strip(),
            "rooms_count": (request.POST.get("rooms_count") or "1").strip(),
        }
    else:
        values = {
            "check_in": check_in_q,
            "check_out": check_out_q,
            "rooms_count": "1",
        }

    if request.method == "POST":
        # 1) Read raw inputs
        check_in_raw = values["check_in"]
        check_out_raw = values["check_out"]
        rooms_count_raw = values["rooms_count"]

        # 2) Validate & convert
        check_in = None
        check_out = None

        if not check_in_raw:
            errors["check_in"] = "Check-in date is required."
        else:
            try:
                check_in = date.fromisoformat(check_in_raw)
            except ValueError:
                errors["check_in"] = "Invalid check-in date format."

        if not check_out_raw:
            errors["check_out"] = "Check-out date is required."
        else:
            try:
                check_out = date.fromisoformat(check_out_raw)
            except ValueError:
                errors["check_out"] = "Invalid check-out date format."

        try:
            rooms_count = int(rooms_count_raw)
            if rooms_count < 1:
                errors["rooms_count"] = "Rooms must be at least 1."
        except ValueError:
            errors["rooms_count"] = "Rooms must be a number."
            rooms_count = None

        # 3) Date rules
        today = date.today()
        if check_in and check_out:
            if check_in >= check_out:
                errors["check_out"] = "Check-out must be after check-in."
            if check_in < today:
                errors["check_in"] = "Check-in cannot be in the past."

        # 4) Availability + create booking
        if not errors and check_in and check_out and rooms_count is not None:
            preview_available = room.available_rooms(check_in, check_out)

            if rooms_count > preview_available:
                errors["rooms_count"] = f"Only {preview_available} room(s) available for these dates."
            else:
                # total calculation: nights * rooms_count * price_per_nightnights = (check_out - check_in).days
                nights = (check_out - check_in).days
                amount = int(nights * rooms_count * float(room.price_per_night) * 100)  # paise
                booking = Booking.objects.create(
                    user=request.user,
                    room=room,
                    check_in=check_in,
                    check_out=check_out,
                    rooms_count=rooms_count,
                    status="confirmed",
                    is_paid=False,
                    amount_paise=amount,
                    )
# create booking first (pending payment)


                client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

                raz_order = client.order.create({
                    "amount": amount,
                    "currency": "INR",
                    "payment_capture": 1,  # auto capture
                    "receipt": f"booking_{booking.id}",
                    })

                booking.razorpay_order_id = raz_order["id"]
                booking.save()

# show payment page with Razorpay popup
                return render(request, "bookings/pay_now.html", {
                    "booking": booking,
                    "room": room,
                    "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                    "razorpay_order_id": booking.razorpay_order_id,
                    "amount": amount,
                    "callback_url": request.build_absolute_uri(reverse("booking:payment_verify")),
                    })


    return render(request, "bookings/book_room.html", {
        "room": room,
        "errors": errors,
        "values": values,
        "preview_available": preview_available,
    })


@login_required
@csrf_exempt
def payment_verify(request):
    if request.method != "POST":
        return redirect("booking:hotel_list")

    razorpay_order_id = request.POST.get("razorpay_order_id")
    razorpay_payment_id = request.POST.get("razorpay_payment_id")
    razorpay_signature = request.POST.get("razorpay_signature")

    booking = get_object_or_404(Booking, razorpay_order_id=razorpay_order_id)

    # Generate signature: HMAC_SHA256(order_id + "|" + payment_id, secret)
    payload = f"{razorpay_order_id}|{razorpay_payment_id}".encode()
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    if expected == razorpay_signature:
        booking.razorpay_payment_id = razorpay_payment_id
        booking.razorpay_signature = razorpay_signature
        booking.is_paid = True
        booking.save()
        messages.success(request, "✅ Payment successful! Booking confirmed.")
        return redirect("booking:my_bookings")

    booking.status = "cancelled"
    booking.save()
    messages.error(request, "❌ Payment verification failed.")
    return redirect("booking:my_bookings")


@login_required
def my_bookings(request):
    bookings = (
        Booking.objects
        .filter(user=request.user)
        .select_related("room", "room__hotel")
        .order_by("-created_at")
    )
    return render(request, "bookings/my_bookings.html", {"bookings": bookings})


@login_required
def cancel_booking(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related("room", "room__hotel"),
        id=booking_id,
        user=request.user
    )

    if request.method == "POST":
        booking.status = "cancelled"
        booking.save()
        messages.success(request, "Booking cancelled.")
        return redirect("booking:my_bookings")

    return render(request, "bookings/cancel_booking.html", {"booking": booking})


def signup_view(request):
    errors = {}
    values = {"username": "", "email": ""}

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""

        values["username"] = username
        values["email"] = email

        # validations
        if not username:
            errors["username"] = "Username is required."
        elif User.objects.filter(username=username).exists():
            errors["username"] = "Username already taken."

        if not email:
            errors["email"] = "Email is required."
        elif User.objects.filter(email=email).exists():
            errors["email"] = "Email already registered."

        if not password1:
            errors["password1"] = "Password is required."
        elif len(password1) < 6:
            errors["password1"] = "Password must be at least 6 characters."

        if password1 != password2:
            errors["password2"] = "Passwords do not match."

        if not errors:
            user = User.objects.create_user(username=username, email=email, password=password1)
            login(request, user)
            messages.success(request, "✅ Account created successfully!")
            return redirect("booking:hotel_list")

    return render(request, "bookings/signup.html", {"errors": errors, "values": values})


def login_view(request):
    errors = {}
    values = {"username": ""}

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        values["username"] = username

        if not username:
            errors["username"] = "Username is required."
        if not password:
            errors["password"] = "Password is required."

        if not errors:
            user = authenticate(request, username=username, password=password)
            if user is None:
                errors["general"] = "Invalid username or password."
            else:
                login(request, user)
                messages.success(request, "✅ Logged in successfully!")
                next_url = request.GET.get("next")
                return redirect(next_url or "booking:hotel_list")

    return render(request, "bookings/login.html", {"errors": errors, "values": values})


def logout_view(request):
    logout(request)
    messages.success(request, "Logged out.")
    return redirect("booking:login")