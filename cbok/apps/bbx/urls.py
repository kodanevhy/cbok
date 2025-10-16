from django.conf.urls import url
from django.views.decorators.csrf import csrf_exempt

from cbok.apps.bbx import forms
from cbok.apps.bbx import views

urlpatterns = [
    url(r'^chrome_login_record_create/$',
        csrf_exempt(views.ChromePluginsView.as_view()),
        kwargs={'form_class': forms.ChromePluginRecordCreateForm}),
    url(r'^chrome_passphrase/$',
        views.ChromePluginsView.as_view()),
]
