from django.contrib.auth import login, logout as auth_logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, redirect

# Login (klasowy widok Django)
login_view = LoginView.as_view(template_name="chat/login.html")

def register_view(request):
    next_url = request.GET.get("next") or request.POST.get("next")
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            if next_url:
                return redirect(next_url)
            return redirect("home")
    else:
        form = UserCreationForm()
    return render(request, "chat/register.html", {"form": form, "next": next_url})

@require_http_methods(["GET", "POST"])
def logout_view(request):
    auth_logout(request)
    return redirect("home")
