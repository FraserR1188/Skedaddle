"""
URL configuration for rota_core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from rota import views as rota_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Django's built-in auth URLs: /accounts/login/, /accounts/logout/, etc.
    path('accounts/', include('django.contrib.auth.urls')),

    # Home / landing page
    path('', rota_views.home, name='home'),

    # Calendar + day views
    path('calendar/', rota_views.current_month_redirect, name='current_month'),
    path('calendar/<int:year>/<int:month>/', rota_views.monthly_calendar, name='monthly_calendar'),
    path('day/<int:year>/<int:month>/<int:day>/', rota_views.daily_rota, name='daily_rota'),
]
