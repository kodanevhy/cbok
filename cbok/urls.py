"""cbok URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the URL module: from django import urls
    2. Add a URL to urlpatterns: urls.path('blog/', urls.include('blog.urls'))
"""
from django import urls

from cbok import views


urlpatterns = [
    urls.re_path(r'^csrf/', views.CSRFView.as_view()),
    urls.re_path(r'^bbx/', urls.include('cbok.bbx.urls')),
    urls.re_path(r'^user/', urls.include('cbok.user.urls')),
    urls.re_path(r'^alert/', urls.include('cbok.alert.urls'))
]
