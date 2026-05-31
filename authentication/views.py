from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import User 

def home(request):
    return render(request, 'authentication/index.html')
def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        email = request.POST.get('username')
        password = request.POST.get('password')
        remember_me = request.POST.get('remember_me')
        user = authenticate(request, username=email, password=password)

        if user is not None:
            login(request, user)
            if not remember_me:
                request.session.set_expiry(0) 
            else:
                request.session.set_expiry(1209600)
            return redirect('home')
        else:
            messages.error(request, "Invalid email or password.")
            # Redirect instead of render to clear the POST state
            return redirect('login') 
    
    return render(request, 'authentication/login.html')

def signup_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        
        # 1. Check Passwords
        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect('signup') # CHANGED: redirect instead of render

        # 2. Check Email exists
        if User.objects.filter(email=email).exists():
            messages.error(request, "This email is already registered.")
            return redirect('signup') # CHANGED: redirect instead of render

        try:
            user = User.objects.create_user(
                username=email, 
                email=email, 
                password=password,
                first_name=first_name
            )
            login(request, user)
            messages.success(request, f"Welcome, {first_name}!")
            return redirect('home')

        except Exception as e:
            messages.error(request, "An error occurred during registration.")
            return redirect('signup')
            
    return render(request, 'authentication/signup.html')

def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('home')