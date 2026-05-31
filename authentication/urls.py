from django.urls import path,include    
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('',views.home,name='home'),
    path('login/',views.login_view,name='login'),
    path('logout/',views.logout_view,name='logout'),
    path('signup/',views.signup_view,name='signup'),
    # path('password-reset/', include([
    #     path('', auth_views.PasswordResetView.as_view(), name='password_reset'),
    #     path('done/', auth_views.PasswordResetView.as_view(), name='password_reset_done'),
    # ])),
]
