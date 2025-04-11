from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import PaymentPeriod, Staff

class RegistrationForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'input'})
    )
    first_name = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={'class': 'input'})
    )
    last_name = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={'class': 'input'})
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={'class': 'input'}),
        help_text=UserCreationForm.base_fields['password1'].help_text
    )
    password2 = forms.CharField(
        label="Password confirmation",
        widget=forms.PasswordInput(attrs={'class': 'input'}),
        help_text=UserCreationForm.base_fields['password2'].help_text
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'input'}),
        }



class PaymentPeriodForm(forms.ModelForm):
    """Form for creating or updating payment periods"""
    
    class Meta:
        model = PaymentPeriod
        fields = ['staff', 'period_start', 'period_end', 'is_paid', 'payment_date']
        widgets = {
            'period_start': forms.DateInput(attrs={'type': 'date'}),
            'period_end': forms.DateInput(attrs={'type': 'date'}),
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter active staff only
        self.fields['staff'].queryset = Staff.objects.filter(is_active=True)
        
        # Add CSS classes
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'input'
            
        # Add placeholders
        self.fields['staff'].widget.attrs['placeholder'] = 'Select staff member'


        