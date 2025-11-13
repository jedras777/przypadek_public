from django.urls import path
from .views import home_view, login_view, register_view, logout_view, stage_view, reset_case_view, completed_grouped, completed_case, completed_detail


urlpatterns = [
    path("", home_view, name="home"),
    path("zaloguj/", login_view, name="login"),
    path("wyloguj/", logout_view, name="logout"),
    path("rejestracja/", register_view, name="register"),
    path("chat/<slug:case_slug>/reset/", reset_case_view, name="case-reset"),
    path("chat/<slug:case_slug>/<str:stage>/", stage_view, name="chat-stage"),
    path('ukonczone/', completed_grouped, name='completed-grouped'),
    path('ukonczone/<slug:case_slug>/', completed_case, name='completed-case'),
    path('ukonczone/p/<int:pk>/', completed_detail, name='completed-detail'),
]
