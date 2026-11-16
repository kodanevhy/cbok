from django import urls
from django.views.decorators import csrf

from cbok.alert import forms
from cbok.alert import views


urlpatterns = [
    urls.re_path(
        r'^topic/$',
        csrf.csrf_exempt(views.TopicView.as_view()),
        kwargs={'form_class': forms.CreateTopicForm},
    ),
]
