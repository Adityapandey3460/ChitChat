from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.utils import timezone
from django.utils.timezone import localtime
from pymongo import MongoClient
import base64
from bson import ObjectId
from django.contrib import messages
from django.utils.timezone import localtime
import pytz
import hashlib  # For password hashing
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json

# MongoDB setup
MONGO_URI = "mongodb+srv://adityapandey:12345@chat-cluster.7qiiw2q.mongodb.net/?retryWrites=true&w=majority&appName=chat-cluster"
client = MongoClient(MONGO_URI)
db = client['chat']
users_collection = db['users']
messages_collection = db['messages_websocket']

def hash_password(password):
    """Simple password hashing function"""
    return hashlib.sha256(password.encode()).hexdigest()

def profile(request):
    if 'email' not in request.session:
        return redirect('login')

    email = request.session['email']
    user = users_collection.find_one({"email": email})
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
        # Handle profile updates
        full_name = request.POST.get('full_name')
        new_email = request.POST.get('email')
        update_data = {'full_name': full_name, 'email': new_email}

        # Handle password change if fields are provided
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if current_password or new_password or confirm_password:
            # Validate password change
            if not all([current_password, new_password, confirm_password]):
                messages.error(request, 'All password fields are required for changing password.')
            elif new_password != confirm_password:
                messages.error(request, 'New passwords do not match.')
            elif hash_password(current_password) != user['password']:
                messages.error(request, 'Current password is incorrect.')
            else:
                update_data['password'] = hash_password(new_password)
                messages.success(request, 'Password successfully changed!')

        # Handle avatar upload/removal
        if 'avatar' in request.FILES:
            avatar_file = request.FILES['avatar']
            avatar_data = base64.b64encode(avatar_file.read()).decode('utf-8')
            update_data['avatar_base64'] = avatar_data

        if request.POST.get('remove_avatar') == "true":
            update_data['avatar_base64'] = ""

        # Update user in database
        users_collection.update_one({'email': email}, {'$set': update_data})
        
        # Update session email if changed
        if new_email != email:
            request.session['email'] = new_email
            messages.success(request, 'Email updated successfully!')
        
        messages.success(request, 'Profile updated successfully!')
        return redirect('profile')

    return redirect('profile')

def index(request):
    if 'email' not in request.session:
        return redirect('login')

    email = request.session['email']
    user = users_collection.find_one({"email": email})
    if not user:
        return redirect('login')

    request.session['user_id'] = str(user['_id'])
    
    # Get avatar data if it exists in the user document
    avatar_base64 = user.get('avatar_base64')
    
    return render(request, 'index.html', {
        'user_email': email,
        'user_id': str(user['_id']),
        'user_full_name': user.get('full_name', 'User'),
        'user_avatar_base64': avatar_base64
    })

def get_contacts(request):
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    user_id = request.session['user_id']
    contacts = list(users_collection.find(
        {"_id": {"$ne": ObjectId(user_id)}},
        {'full_name': 1, 'avatar_base64': 1, 'status': 1, 'last_seen': 1}
    ))

    serialized_contacts = []
    for contact in contacts:
        contact_id = str(contact['_id'])
        room_name = '_'.join(sorted([user_id, contact_id]))

        # Get the last non-deleted message or the last message if all are deleted
        last_msg = messages_collection.find_one(
            {"room": room_name},
            sort=[("timestamp", -1)]
        )

        # Convert last_seen to localtime
        last_seen = contact.get('last_seen')
        if last_seen:
            last_seen = localtime(last_seen.replace(tzinfo=pytz.UTC))

        contact_data = {
            "id": contact_id,
            "full_name": contact.get('full_name', ''),
            "avatar_base64": contact.get('avatar_base64', ''),
            "status": contact.get('status', 'offline'),
            "last_seen": last_seen.isoformat() if last_seen else '',
            "last_message": None
        }

        if last_msg:
            msg_timestamp = last_msg.get('timestamp')
            if msg_timestamp:
                msg_timestamp = localtime(msg_timestamp.replace(tzinfo=pytz.UTC))

            message_content = last_msg.get('message', '')
            if last_msg.get('deleted', False) and last_msg.get('sender_id') != user_id:
                message_content = 'This message was deleted'

            contact_data["last_message"] = {
                "content": message_content,
                "sender_id": last_msg.get('sender_id', ''),
                "timestamp": msg_timestamp.isoformat() if msg_timestamp else '',
                "deleted": last_msg.get('deleted', False)
            }

        serialized_contacts.append(contact_data)

    # ✅ Sort contacts by last_message timestamp (most recent first)
    serialized_contacts.sort(
        key=lambda c: (
            c["last_message"]["timestamp"] if c["last_message"] else ""
        ),
        reverse=True
    )

    return JsonResponse({"contacts": serialized_contacts})


def chat_history(request):
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    current_user_id = request.session['user_id']
    other_user_id = request.GET.get('user_id')
    
    if not other_user_id:
        return JsonResponse({"error": "User ID required"}, status=400)

    try:
        room_name = '_'.join(sorted([current_user_id, other_user_id]))
        
        # Get messages that aren't deleted or are from the other user
        messages = list(messages_collection.find(
            {
                "room": room_name,
                "$or": [
                    {"deleted": False},
                    {"sender_id": other_user_id}  # Show deleted messages from other users
                ]
            },
            sort=[("timestamp", 1)]
        ))

        serialized_messages = []
        for msg in messages:
            timestamp = msg['timestamp']
            if timestamp and timestamp.tzinfo is None:
                timestamp = timezone.make_aware(timestamp)
            
            message_data = {
                "id": str(msg['_id']),
                "message": msg['message'],
                "sender_id": str(msg['sender_id']),
                "receiver_id": str(msg['receiver_id']),
                "timestamp": timestamp.isoformat(),
                "read": msg.get('read', False),
                "edited": msg.get('edited', False),
                "deleted": msg.get('deleted', False)
            }
            
            # Add edit timestamp if message was edited
            if msg.get('edited') and msg.get('edit_timestamp'):
                edit_ts = msg['edit_timestamp']
                if edit_ts and edit_ts.tzinfo is None:
                    edit_ts = timezone.make_aware(edit_ts)
                message_data["edit_timestamp"] = edit_ts.isoformat()
            
            serialized_messages.append(message_data)

        # Mark messages as read
        messages_collection.update_many(
            {
                "room": room_name,
                "receiver_id": current_user_id,
                "read": False
            },
            {"$set": {"read": True}}
        )

        return JsonResponse({"messages": serialized_messages})

    except Exception as e:
        print(f"Error fetching chat history: {str(e)}")
        return JsonResponse({"error": "Failed to load chat history"}, status=500)

@csrf_exempt
@require_POST
def edit_message(request):
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        message_id = data.get('message_id')
        new_content = data.get('new_content')
        receiver_id = data.get('receiver_id')
        user_id = request.session['user_id']
        
        if not all([message_id, new_content, receiver_id]):
            return JsonResponse({"error": "Missing parameters"}, status=400)
        
        # Update message in database
        result = messages_collection.update_one(
            {
                '_id': ObjectId(message_id),
                'sender_id': user_id,
                'deleted': False
            },
            {
                '$set': {
                    'message': new_content,
                    'edited': True,
                    'edit_timestamp': timezone.now()
                }
            }
        )
        
        if result.modified_count > 0:
            return JsonResponse({"success": True})
        else:
            return JsonResponse({"error": "Message not found or not authorized"}, status=404)
            
    except Exception as e:
        print(f"Error editing message: {str(e)}")
        return JsonResponse({"error": "Failed to edit message"}, status=500)

@csrf_exempt
@require_POST
def delete_message(request):
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        message_id = data.get('message_id')
        receiver_id = data.get('receiver_id')
        user_id = request.session['user_id']
        
        if not all([message_id, receiver_id]):
            return JsonResponse({"error": "Missing parameters"}, status=400)
        
        # Soft delete message in database
        result = messages_collection.update_one(
            {
                '_id': ObjectId(message_id),
                'sender_id': user_id
            },
            {
                '$set': {
                    'deleted': True,
                    'message': 'This message was deleted',
                    'delete_timestamp': timezone.now()
                }
            }
        )
        
        if result.modified_count > 0:
            return JsonResponse({"success": True})
        else:
            return JsonResponse({"error": "Message not found or not authorized"}, status=404)
            
    except Exception as e:
        print(f"Error deleting message: {str(e)}")
        return JsonResponse({"error": "Failed to delete message"}, status=500)


@csrf_exempt
@require_POST
def clear_chat(request):
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        other_user_id = data.get('user_id')
        user_id = request.session['user_id']
        
        if not other_user_id:
            return JsonResponse({"error": "User ID required"}, status=400)
        
        room_name = '_'.join(sorted([user_id, other_user_id]))
        
        # Permanently delete all messages from the database
        result = messages_collection.delete_many({"room": room_name})
        
        return JsonResponse({
            "success": True, 
            "deleted_count": result.deleted_count,
            "permanent_delete": True
        })
            
    except Exception as e:
        print(f"Error clearing chat: {str(e)}")
        return JsonResponse({"error": "Failed to clear chat"}, status=500)

def create_account(request):
    if request.method == 'POST':
        name = request.POST['name']
        email = request.POST['email']
        password = request.POST['password']

        if users_collection.find_one({"email": email}):
            return render(request, 'create_account.html', {"error": "Email already exists"})

        users_collection.insert_one({
            "email": email,
            "password": hash_password(password),
            "full_name": name,
            "avatar_base64": "",
            "joined_on": timezone.now(),
            "status": "offline",
            "is_active": True
        })
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
    user_id = str(user['_id'])

    users_collection.delete_one({"email": email})
    messages_collection.delete_many({
        "$or": [
            {"sender_id": user_id},
            {"receiver_id": user_id}
        ]
    })
    request.session.flush()
    return redirect('login')

@csrf_exempt
@require_POST
def mark_as_read(request):
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        data = json.loads(request.body)
        message_ids = data.get("message_ids", [])
        if not message_ids:
            return JsonResponse({"error": "No message IDs provided"}, status=400)

        user_id = request.session['user_id']

        # Convert to ObjectIds (skip temp IDs)
        obj_ids = []
        for mid in message_ids:
            try:
                if isinstance(mid, str) and not mid.startswith("temp_"):
                    obj_ids.append(ObjectId(mid))
            except Exception:
                continue

        if obj_ids:
            result = messages_collection.update_many(
                {"_id": {"$in": obj_ids}, "receiver_id": user_id},
                {"$set": {"read": True, "read_timestamp": timezone.now()}}
            )
            print(f"Marked {result.modified_count} messages as read")

        return JsonResponse({"success": True, "message_ids": message_ids})
    except Exception as e:
        print(f"Error marking messages as read: {e}")
        return JsonResponse({"error": "Failed to mark messages as read"}, status=500)
