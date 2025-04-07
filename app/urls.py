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
]