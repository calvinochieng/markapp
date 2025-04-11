from django.urls import path   
from django.contrib.auth import views as auth_views
from .views import * 

urlpatterns = [
    path('',index, name='index'), 
    path('register/', register_view, name='register'),
    path('login/', LoginView.as_view(template_name='registration/login.html'), name='login'),    
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', dashboard, name='dashboard'),
    path('payroll/', staff_payroll, name='staff_payroll'), 
    path('payroll/period/', period_payroll, name='period_payroll'),
    path('payroll/individual/', individual_payroll, name='individual_payroll'),
    path('payroll/period/mark-paid/<int:period_id>/', mark_period_paid, name='mark_period_paid'),
    path('payroll/period/create/', create_payment_period_form, name='create_payment_period'),

]