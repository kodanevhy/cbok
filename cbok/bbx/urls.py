from django import urls
from django.views.decorators import csrf

from cbok.bbx import forms
from cbok.bbx import views

urlpatterns = [
    urls.re_path(
        r'^chrome_login_record_create/$',
        csrf.csrf_exempt(views.ChromePluginsView.as_view()),
        kwargs={'form_class': forms.ChromePluginRecordCreateForm},
    ),
    urls.re_path(r'^chrome_passphrase/$', views.ChromePluginsView.as_view()),
]
