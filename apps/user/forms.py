from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(required=False)
    password = forms.CharField(required=False, min_length=5)


class RegisterForm(forms.Form):
    username = forms.CharField(required=False)
    password = forms.CharField(required=False, min_length=5)
