# urls.py
from django.urls import path
from . import views

urlpatterns = [
    # ---------------- AUTHENTICATION & PROFILE ----------------
    path('', views.index, name='index'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('create_account/', views.create_account, name='create_account'),
    path('profile/', views.profile, name='profile'),
    path('edit_profile/', views.edit_profile, name='edit_profile'),
    path('delete_account/', views.delete_account, name='delete_account'),
    
    # ---------------- ENCRYPTION CORE (ESSENTIAL) ----------------
    path('encryption/check_keys/', views.check_user_keys, name='check_user_keys'),
    path('encryption/get_keys/', views.get_user_keys, name='get_user_keys'),
    path('encryption/store_keys/', views.store_user_keys, name='store_user_keys'),
    path('encryption/get_public_key/', views.get_contact_public_key, name='get_contact_public_key'),
    path('encryption/status/', views.get_encryption_status, name='get_encryption_status'),
    
    # ---------------- INDIVIDUAL CHAT ----------------
    path('get_contacts/', views.get_contacts, name='get_contacts'),
    path('chat/history/', views.individual_chat_history, name='individual_chat_history'),
    path('chat/send_message/', views.send_individual_message, name='send_individual_message'),
    path('chat/edit_message/', views.edit_individual_message, name='edit_individual_message'),
    path('chat/delete_message/', views.delete_individual_message, name='delete_individual_message'),
    path('chat/clear_chat/', views.clear_individual_chat, name='clear_individual_chat'),
    path('chat/mark_read/', views.mark_individual_as_read, name='mark_individual_as_read'),
    
    # ---------------- GROUP CHAT ----------------
    path('groups/', views.get_groups, name='get_groups'),
    path('groups/history/', views.group_chat_history, name='group_chat_history'),
    path('groups/send_message/', views.send_group_message, name='send_group_message'),
    path('groups/edit_message/', views.edit_group_message, name='edit_group_message'),
    path('groups/delete_message/', views.delete_group_message, name='delete_group_message'),
    path('groups/clear_chat/', views.clear_group_chat, name='clear_group_chat'),
    path('groups/mark_read/', views.mark_group_as_read, name='mark_group_as_read'),
    
    # ---------------- GROUP MANAGEMENT ----------------
    path('groups/get_members/', views.get_group_members, name='get_group_members'),
    path('groups/remove_member/', views.remove_group_member, name='remove_group_member'),
    path('groups/make_admin/', views.make_group_admin, name='make_group_admin'),
    path('groups/delete_group/', views.delete_group, name='delete_group'),
    path('groups/leave/', views.leave_group, name='leave_group'),
    path('groups/available_contacts/', views.get_available_contacts_for_group, name='get_available_contacts_for_group'),
    path('groups/bulk_remove_admins/', views.bulk_remove_group_admins, name='bulk_remove_group_admins'),

    # Group Encryption URLs
    path('groups/create_with_encryption/', views.create_group_with_encryption, name='create_group_with_encryption'),
    path('groups/add_members_with_encryption/', views.add_members_with_encryption, name='add_members_with_encryption'),
    path('encryption/get_my_encrypted_group_seed/', views.get_my_encrypted_group_seed, name='get_my_encrypted_group_seed'),
]