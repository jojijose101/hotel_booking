 // UX: Make check-out min = check-in, and auto-calc total
  const checkIn = document.getElementById("check_in");
  const checkOut = document.getElementById("check_out");
  const roomsCount = document.getElementById("rooms_count");

  const nightsCountEl = document.getElementById("nightsCount");
  const roomsCountPreviewEl = document.getElementById("roomsCountPreview");
  const totalPriceEl = document.getElementById("totalPrice");
  const pricePerNightEl = document.getElementById("pricePerNight");

  // Convert "123.00" to number safely
  const pricePerNight = parseFloat((pricePerNightEl?.textContent || "0").replace(/,/g, "")) || 0;

  function dayDiff(a, b) {
    // a,b are yyyy-mm-dd
    const d1 = new Date(a + "T00:00:00");
    const d2 = new Date(b + "T00:00:00");
    const ms = d2 - d1;
    const days = Math.floor(ms / (1000 * 60 * 60 * 24));
    return isNaN(days) ? 0 : days;
  }

  function syncDates() {
    if (checkIn.value) {
      checkOut.min = checkIn.value;
      if (checkOut.value && checkOut.value <= checkIn.value) {
        checkOut.value = "";
      }
    }
  }

  function updateTotals() {
    const nights = (checkIn.value && checkOut.value) ? dayDiff(checkIn.value, checkOut.value) : 0;
    const rooms = parseInt(roomsCount.value || "1", 10) || 1;

    nightsCountEl.textContent = nights > 0 ? nights : 0;
    roomsCountPreviewEl.textContent = rooms;

    const total = Math.max(nights, 0) * Math.max(rooms, 0) * pricePerNight;
    totalPriceEl.textContent = total ? total.toFixed(2) : "0";
  }

  checkIn.addEventListener("change", () => { syncDates(); updateTotals(); });
  checkOut.addEventListener("change", updateTotals);
  roomsCount.addEventListener("input", updateTotals);

  // init
  syncDates();
  updateTotals();