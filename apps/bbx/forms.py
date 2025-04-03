from django import forms


class ChromePluginRecordCreateForm(forms.Form):
    address = forms.GenericIPAddressField(required=True, protocol='ipv4')
    password = forms.CharField(required=True, min_length=5)
