from django.urls import re_path

from cbok.user import forms
from cbok.user import views

urlpatterns = [
    re_path(r'^create/$',
            views.UserView.as_view(),
            kwargs={'form_class': forms.RegisterForm}),
    re_path(r'^show/$',
            views.UserView.as_view()),
    re_path(r'^login/$',
            views.LoginView.as_view(),
            kwargs={'form_class': forms.LoginForm}),
]