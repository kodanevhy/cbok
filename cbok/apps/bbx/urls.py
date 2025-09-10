from django.conf.urls import url
from django.views.decorators.csrf import csrf_exempt

from bbx import forms
from bbx import views

urlpatterns = [
    url(r'^chrome_login_record_create/$',
        csrf_exempt(views.ChromePluginsView.as_view()),
        kwargs={'form_class': forms.ChromePluginRecordCreateForm}),
]
