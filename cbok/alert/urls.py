from django.urls import re_path
from django.views.decorators.csrf import csrf_exempt

from cbok.alert import forms
from cbok.alert import views


urlpatterns = [
    re_path(r'^topic/$',
            csrf_exempt(views.TopicView.as_view()),
            kwargs={'form_class': forms.CreateTopicForm}),
]
