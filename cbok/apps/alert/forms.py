from django import forms


class CreateTopicForm(forms.Form):
    name = forms.CharField(required=False)
