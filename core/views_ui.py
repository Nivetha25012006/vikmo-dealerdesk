from django.shortcuts import render


def dashboard_view(request):
    """Serve the single-page DealerDesk dashboard interface."""
    return render(request, "core/dashboard.html")
