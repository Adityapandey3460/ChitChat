from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('profile/', views.profile, name='profile'),
    path('edit_profile/', views.edit_profile, name='edit_profile'),
    path('get_contacts/', views.get_contacts, name='get_contacts'),
    path('chat/history/', views.chat_history, name='chat_history'),
    path('chat/edit_message/', views.edit_message, name='edit_message'),
    path('chat/delete_message/', views.delete_message, name='delete_message'),
    path('chat/clear_chat/', views.clear_chat, name='clear_chat'),
    path('create_account/', views.create_account, name='create_account'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('delete_account/', views.delete_account, name='delete_account'),
    path("chat/mark_as_read/", views.mark_as_read, name="mark_as_read"),

]