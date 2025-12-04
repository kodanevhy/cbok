from django.urls import re_path
from django.views.decorators.csrf import csrf_exempt

from cbok.apps.bbx import forms
from cbok.apps.bbx import views

urlpatterns = [
    re_path(r'^chrome_login_record_create/$',
            csrf_exempt(views.ChromePluginsView.as_view()),
            kwargs={'form_class': forms.ChromePluginRecordCreateForm}),
    re_path(r'^chrome_passphrase/$',
            views.ChromePluginsView.as_view()),
]
