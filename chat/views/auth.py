from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.timezone import localtime
import base64
import pytz
from bson import ObjectId
from django.contrib import messages

# Import from common
from .common import users_collection, messages_collection, group_messages_collection, groups_collection, hash_password

def profile(request):
    if 'email' not in request.session:
        return redirect('login')
    user = users_collection.find_one({"email": request.session['email']})
    if not user:
        return redirect('login')
    user['avatar_base64'] = user.get('avatar_base64', '')
    return render(request, 'profile.html', {"user": user})

def edit_profile(request):
    if 'email' not in request.session:
        return redirect('login')

    email = request.session['email']
    user = users_collection.find_one({'email': email})
    if not user:
        return redirect('login')

    if request.method == 'POST':
        full_name = request.POST.get('full_name')
        new_email = request.POST.get('email')
        update_data = {'full_name': full_name, 'email': new_email}

        # Handle password change
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if current_password or new_password or confirm_password:
            if not all([current_password, new_password, confirm_password]):
                messages.error(request, 'All password fields required.')
            elif new_password != confirm_password:
                messages.error(request, 'Passwords do not match.')
            elif hash_password(current_password) != user['password']:
                messages.error(request, 'Current password incorrect.')
            else:
                update_data['password'] = hash_password(new_password)
                messages.success(request, 'Password changed!')

        # Handle avatar
        if 'avatar' in request.FILES:
            from .common import compress_image
            avatar_file = request.FILES['avatar']
            update_data['avatar_base64'] = compress_image(avatar_file)
        if request.POST.get('remove_avatar') == "true":
            update_data['avatar_base64'] = ""

        users_collection.update_one({'email': email}, {'$set': update_data})
        if new_email != email:
            request.session['email'] = new_email
        messages.success(request, 'Profile updated!')
        return redirect('profile')

    return redirect('profile')

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

def create_account(request):
    if request.method == 'POST':
        name = request.POST['name']
        email = request.POST['email']
        password = request.POST['password']

        if users_collection.find_one({"email": email}):
            return render(request, 'create_account.html', {"error": "Email already exists"})

        result = users_collection.insert_one({
            "email": email,
            "password": hash_password(password),
            "full_name": name,
            "avatar_base64": "",
            "joined_on": timezone.now(),
            "status": "offline",
            "is_active": True
        })
        
        # Broadcast the new user to the global channel
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "global_broadcast",
                {
                    "type": "global_new_user",
                    "user_id": str(result.inserted_id),
                    "username": name
                }
            )
        except Exception as e:
            print(f"Failed to broadcast global_new_user: {e}")

        return redirect('login')

    return render(request, 'create_account.html')

def login_view(request):
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST['password']
        user = users_collection.find_one({"email": email, "password": hash_password(password)})

        if user:
            request.session['email'] = email
            request.session['user_id'] = str(user['_id'])
            request.session['user_full_name'] = user.get('full_name', 'User')
            users_collection.update_one({"email": email}, {"$set": {"status": "online"}})
            return redirect('index')
        else:
            return render(request, 'login.html', {'error': 'Invalid credentials'})

    return render(request, 'login.html')

def logout_view(request):
    email = request.session.get('email')
    if email:
        users_collection.update_one({"email": email}, {"$set": {"status": "offline"}})
    request.session.flush()
    return redirect('login')

def delete_account(request):
    if 'email' not in request.session:
        return redirect('login')

    email = request.session['email']
    user = users_collection.find_one({"email": email})
    user_id = ObjectId(user['_id'])

    users_collection.delete_one({"email": email})
    messages_collection.delete_many({
        "$or": [
            {"sender_id": user_id},
            {"receiver_id": user_id}
        ]
    })
    # Also delete group messages and remove from groups
    group_messages_collection.delete_many({"sender_id": user_id})
    groups_collection.update_many(
        {"members": user_id},
        {"$pull": {"members": user_id}}
    )
    # Also remove from admin_ids!
    groups_collection.update_many(
        {"admin_ids": user_id},
        {"$pull": {"admin_ids": user_id}}
    )
    request.session.flush()
    return redirect('login')

def index(request):
    if 'email' not in request.session:
        return redirect('login')
    email = request.session['email']
    user = users_collection.find_one({"email": email})
    if not user:
        return redirect('login')
    
    user_id = str(user['_id'])
    request.session['user_id'] = user_id
    request.session['user_full_name'] = user.get('full_name', 'User')

    # Contacts and Groups are fetched asynchronously by frontend JS
    serialized_contacts = []
    serialized_groups = []

    return render(request, 'index.html', {
        'user_email': email,
        'user_id': user_id,
        'user_full_name': user.get('full_name', 'User'),
        'user_avatar_base64': user.get('avatar_base64', ''),
        'contacts': serialized_contacts,
        'groups': serialized_groups
    })
