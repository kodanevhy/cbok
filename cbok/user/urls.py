from django import urls

from cbok.user import forms
from cbok.user import views

urlpatterns = [
    urls.re_path(
        r'^create/$',
        views.UserView.as_view(),
        kwargs={'form_class': forms.RegisterForm},
    ),
    urls.re_path(r'^show/$', views.UserView.as_view()),
    urls.re_path(
        r'^login/$',
        views.LoginView.as_view(),
        kwargs={'form_class': forms.LoginForm},
    ),
]
