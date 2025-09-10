from django.conf.urls import url

from user import forms
from user import views

urlpatterns = [
    url(r'^create/$',
        views.UserView.as_view(),
        kwargs={'form_class': forms.RegisterForm}),
    url(r'^show/$',
        views.UserView.as_view()),
    url(r'^login/$',
        views.LoginView.as_view(),
        kwargs={'form_class': forms.LoginForm}),
]
