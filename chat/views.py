from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.utils import timezone
from django.utils.timezone import localtime
from pymongo import MongoClient
import base64
from bson import ObjectId
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import pytz
import hashlib
import json
from django.views.decorators.http import require_http_methods
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import os
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI")

client = MongoClient(MONGO_URI)
db = client['chat_new']

users_collection = db['users']
messages_collection = db['messages_websocket']
groups_collection = db['groups']
group_messages_collection = db['messages_group']
group_seeds_collection = db['group_encrypted_seeds'] 

# Password hashing
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ====================================================
# ENCRYPTION VIEWS - STORED IN USERS COLLECTION
# ====================================================

@csrf_exempt
@require_http_methods(["GET"])
def check_user_keys(request):
    """Check if user has existing encryption keys in users collection"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({'error': 'User ID not found'}, status=400)
        
        print(f"🔐 CHECK_KEYS - User: {user_id}")
        
        # Check if user has keys in users collection
        user = users_collection.find_one({'_id': ObjectId(user_id)})
        
        if not user:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        # Check if encryption keys exist
        has_keys = 'encryption_keys' in user and \
                  user['encryption_keys'] is not None and \
                  'encrypted_private_key' in user['encryption_keys'] and \
                  'public_key' in user['encryption_keys']
        
        print(f"🔐 KEYS STATUS - User {user_id}: {'Has keys' if has_keys else 'No keys'}")
        
        return JsonResponse({
            'has_keys': has_keys,
            'user_id': user_id
        })
        
    except Exception as e:
        print(f"❌ Error checking user keys: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def get_user_keys(request):
    """Get user's encrypted keys from users collection"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({'error': 'User ID not found'}, status=400)
        
        print(f"🔐 GET_KEYS - User: {user_id}")
        
        # Get user from database
        user = users_collection.find_one({'_id': ObjectId(user_id)})
        
        if not user:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        if 'encryption_keys' not in user or not user['encryption_keys']:
            print(f"❌ No encryption keys found for user: {user_id}")
            return JsonResponse({'error': 'No encryption keys found'}, status=404)
        
        encryption_keys = user['encryption_keys']
        
        response_data = {
            'encrypted_private_key': encryption_keys['encrypted_private_key'],
            'public_key': encryption_keys['public_key'],
            'iv': encryption_keys['iv'],
            'salt': encryption_keys['salt'],
            'iterations': encryption_keys['iterations'],
            'user_id': user_id,
            'created_at': encryption_keys.get('created_at', timezone.now()).isoformat()
        }
        
        print(f"✅ Successfully retrieved keys for user: {user_id}")
        return JsonResponse(response_data)
        
    except Exception as e:
        print(f"❌ Error getting user keys: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def store_user_keys(request):
    """Store user's encrypted keys in users collection"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({'error': 'User ID not found'}, status=400)
        
        data = json.loads(request.body)
        
        required_fields = ['encrypted_private_key', 'iv', 'salt', 'iterations', 'public_key']
        for field in required_fields:
            if field not in data:
                return JsonResponse({'error': f'Missing required field: {field}'}, status=400)
        
        print(f"🔐 STORE_KEYS - User: {user_id}")
        
        # Prepare encryption keys data
        encryption_data = {
            'encrypted_private_key': data['encrypted_private_key'],
            'public_key': data['public_key'],
            'iv': data['iv'],
            'salt': data['salt'],
            'iterations': data['iterations'],
            'created_at': timezone.now(),
            'updated_at': timezone.now()
        }
        
        # Update user document with encryption keys
        result = users_collection.update_one(
            {'_id': ObjectId(user_id)},
            {
                '$set': {
                    'encryption_keys': encryption_data,
                    'encryption_enabled': True,
                    'encryption_setup_at': timezone.now()
                }
            }
        )
        
        if result.modified_count > 0:
            print(f"✅ Successfully stored encryption keys for user: {user_id}")
            return JsonResponse({
                'success': True,
                'message': 'Encryption keys stored successfully',
                'user_id': user_id
            })
        else:
            print(f"❌ Failed to store keys for user: {user_id}")
            return JsonResponse({'error': 'Failed to store encryption keys'}, status=500)
        
    except Exception as e:
        print(f"❌ Error storing user keys: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def get_contact_public_key(request):
    """Get a contact's public key for encryption"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        contact_id = request.GET.get('user_id')
        if not contact_id:
            return JsonResponse({'error': 'Contact ID required'}, status=400)
        
        print(f"🔐 GET_PUBLIC_KEY - Contact: {contact_id}")
        
        # Get contact from database
        contact = users_collection.find_one({'_id': ObjectId(contact_id)})
        
        if not contact:
            return JsonResponse({'error': 'Contact not found'}, status=404)
        
        if 'encryption_keys' not in contact or not contact['encryption_keys']:
            return JsonResponse({'error': 'Contact does not have encryption setup'}, status=404)
        
        public_key = contact['encryption_keys']['public_key']
        
        return JsonResponse({
            'public_key': public_key,
            'user_id': contact_id,
            'user_name': contact.get('full_name', 'User')
        })
        
    except Exception as e:
        print(f"❌ Error getting contact public key: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def reset_encryption_keys(request):
    """Reset user's encryption keys (for testing or re-setup)"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        user_id = request.session.get('user_id')
        
        print(f"🔐 RESET_KEYS - User: {user_id}")
        
        # Remove encryption keys from user document
        result = users_collection.update_one(
            {'_id': ObjectId(user_id)},
            {
                '$unset': {
                    'encryption_keys': "",
                    'encryption_enabled': "",
                    'encryption_setup_at': ""
                }
            }
        )
        
        if result.modified_count > 0:
            print(f"✅ Successfully reset encryption keys for user: {user_id}")
            return JsonResponse({
                'success': True,
                'message': 'Encryption keys reset successfully',
                'user_id': user_id
            })
        else:
            print(f"❌ No keys to reset for user: {user_id}")
            return JsonResponse({'error': 'No encryption keys found to reset'}, status=404)
        
    except Exception as e:
        print(f"❌ Error resetting encryption keys: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def get_encryption_status(request):
    """Get comprehensive encryption status for the user"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        user_id = request.session.get('user_id')
        
        user = users_collection.find_one({'_id': ObjectId(user_id)})
        if not user:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        has_keys = 'encryption_keys' in user and user['encryption_keys'] is not None
        encryption_enabled = user.get('encryption_enabled', False)
        setup_at = user.get('encryption_setup_at')
        
        status_data = {
            'has_keys': has_keys,
            'encryption_enabled': encryption_enabled,
            'user_id': user_id,
            'setup_completed': has_keys and encryption_enabled
        }
        
        if setup_at:
            status_data['setup_at'] = setup_at.isoformat()
        
        if has_keys:
            keys = user['encryption_keys']
            status_data['keys_created'] = keys.get('created_at', timezone.now()).isoformat()
            status_data['keys_updated'] = keys.get('updated_at', timezone.now()).isoformat()
        
        return JsonResponse(status_data)
        
    except Exception as e:
        print(f"❌ Error getting encryption status: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

# ====================================================
# GROUP ENCRYPTION ENDPOINTS
# ====================================================

@csrf_exempt
@require_POST
def create_group_with_encryption(request):
    """Create group with encrypted seeds for each member - USING ObjectId"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({"error": "Authentication required"}, status=401)
        
        data = json.loads(request.body)
        group_name = data.get('name')
        member_ids = data.get('member_ids', [])
        encrypted_seeds = data.get('encrypted_seeds', [])
        
        if not group_name:
            return JsonResponse({"error": "Group name required"}, status=400)
        
        user_id = request.session.get('user_id')
        
        print(f"🔐 CREATE_GROUP_WITH_ENCRYPTION - Name: {group_name}, Members: {len(member_ids)}")
        
        # Convert all IDs to ObjectId
        user_object_id = ObjectId(user_id)
        member_object_ids = [ObjectId(mid) for mid in member_ids]
        
        # Create group document with ObjectId
        group_data = {
            "name": group_name,
            "created_by": user_object_id,
            "admin_ids": [user_object_id],
            "members": list(set([user_object_id] + member_object_ids)),
            "encryption_enabled": True,
            "created_at": timezone.now(),
            "updated_at": timezone.now(),
            "is_active": True
        }
        
        # Insert group to get group_id
        result = groups_collection.insert_one(group_data)
        group_id = str(result.inserted_id)
        
        print(f"✅ Group created: {group_id}")
        
        # Store encrypted seeds with ObjectId
        if encrypted_seeds:
            seed_documents = []
            for seed_data in encrypted_seeds:
                seed_doc = {
                    "group_id": ObjectId(group_id),
                    "member_id": ObjectId(seed_data['member_id']),
                    "encrypted_seed": seed_data['encrypted_seed'],
                    "iv": seed_data['iv'],
                    "encrypted_by": ObjectId(seed_data.get('encrypted_by', user_id)),
                    "timestamp": seed_data.get('timestamp', timezone.now().isoformat()),
                    "created_at": timezone.now()
                }
                seed_documents.append(seed_doc)
            
            if seed_documents:
                try:
                    group_seeds_collection.insert_many(seed_documents)
                    print(f"✅ Stored {len(seed_documents)} encrypted seeds for group {group_id}")
                except Exception as e:
                    print(f"❌ Error storing encrypted seeds: {e}")
        
        return JsonResponse({
            "success": True,
            "group_id": group_id,
            "message": "Encrypted group created successfully",
            "seeds_stored": len(encrypted_seeds) if encrypted_seeds else 0
        })
        
    except Exception as e:
        print(f"❌ Error creating encrypted group: {e}")
        return JsonResponse({"error": "Failed to create group"}, status=500)

@csrf_exempt
@require_POST
def get_my_encrypted_group_seed(request):
    """Get encrypted group seed specifically for the current user - USING ObjectId"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({"error": "Authentication required"}, status=401)
        
        data = json.loads(request.body)
        group_id = data.get('group_id')
        
        if not group_id:
            return JsonResponse({"error": "Group ID required"}, status=400)
        
        user_id = request.session.get('user_id')
        
        print(f"🔐 GET_MY_GROUP_SEED - Group: {group_id}, User: {user_id}")
        
        # Verify group exists and user is member
        group = groups_collection.find_one({
            "_id": ObjectId(group_id),
            "members": ObjectId(user_id),
            "is_active": True
        })
        
        if not group:
            return JsonResponse({"error": "Group not found or access denied"}, status=404)
        
        # Check if group has encryption enabled
        if not group.get('encryption_enabled', False):
            return JsonResponse({
                "error": "Group encryption not enabled",
                "encryption_enabled": False
            }, status=400)
        
        # Get the encrypted seed for THIS specific user
        encrypted_seed = group_seeds_collection.find_one({
            "group_id": ObjectId(group_id),
            "member_id": ObjectId(user_id)
        })
        
        if not encrypted_seed:
            print(f"❌ No encrypted seed found for user {user_id} in group {group_id}")
            return JsonResponse({
                "error": "No encrypted seed found for user",
                "encryption_enabled": True
            }, status=404)
        
        print(f"✅ Found encrypted seed for user {user_id} in group {group_id}")
        
        response_data = {
            "success": True,
            "encrypted_seed": {
                "encrypted_seed": encrypted_seed['encrypted_seed'],
                "encrypted_by": str(encrypted_seed['encrypted_by']),
                "timestamp": encrypted_seed['timestamp'],
                "iv": encrypted_seed['iv']
            },
            "encryption_enabled": True,
            "group_id": group_id
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        print(f"❌ Error getting encrypted group seed: {e}")
        return JsonResponse({"error": "Failed to get group seed"}, status=500)

@csrf_exempt
@require_POST
def add_members_with_encryption(request):
    """Add members to encrypted group - USING ObjectId"""
    try:
        if 'user_id' not in request.session:
            return JsonResponse({"error": "Authentication required"}, status=401)
        
        data = json.loads(request.body)
        group_id = data.get('group_id')
        new_member_ids = data.get('new_member_ids', [])
        encrypted_seeds = data.get('encrypted_seeds', [])
        
        if not group_id or not new_member_ids:
            return JsonResponse({"error": "Group ID and members required"}, status=400)
        
        user_id = request.session['user_id']
        user_object_id = ObjectId(user_id)

        # Query groups with ObjectId
        group = groups_collection.find_one({
            "_id": ObjectId(group_id),
            "admin_ids": user_object_id,
            "is_active": True
        })
        
        if not group:
            print("❌ Group not found or user is not admin")
            return JsonResponse({"error": "Group not found or no permission"}, status=404)
        
        print("✅ Group found and user is admin")
        
        if not group.get('encryption_enabled', False):
            return JsonResponse({"error": "Group encryption not enabled"}, status=400)
        
        # Filter out existing members
        current_members = [str(member) for member in group.get('members', [])]
        new_members = set(new_member_ids) - set(current_members)
        
        if not new_members:
            return JsonResponse({"error": "All members already in group"}, status=400)
        
        print(f"✅ Adding {len(new_members)} new members: {list(new_members)}")
        
        # Convert new members to ObjectId and add to group
        new_member_object_ids = [ObjectId(mid) for mid in new_members]
        update_result = groups_collection.update_one(
            {"_id": ObjectId(group_id)},
            {"$addToSet": {"members": {"$each": new_member_object_ids}}}
        )
        
        print(f"✅ Database update: {update_result.modified_count} documents modified")
        
        # Store encrypted seeds with ObjectId
        seeds_stored = 0
        if encrypted_seeds:
            seed_docs = []
            for seed_data in encrypted_seeds:
                member_id = seed_data.get('member_id')
                if member_id in new_members:
                    seed_docs.append({
                        "group_id": ObjectId(group_id),
                        "member_id": ObjectId(member_id),
                        "encrypted_seed": seed_data['encrypted_seed'],
                        "iv": seed_data['iv'],
                        "encrypted_by": user_object_id,
                        "timestamp": seed_data.get('timestamp', timezone.now().isoformat()),
                        "created_at": timezone.now()
                    })
                    print(f"✅ Prepared seed for member: {member_id}")
            
            if seed_docs:
                try:
                    group_seeds_collection.insert_many(seed_docs)
                    seeds_stored = len(seed_docs)
                    print(f"✅ Stored {seeds_stored} encrypted seeds as ObjectId")
                except Exception as e:
                    print(f"❌ Error storing seeds: {e}")
        
        # Get updated member count
        updated_group = groups_collection.find_one({"_id": ObjectId(group_id)})
        total_members = len(updated_group.get('members', []))
        
        response_data = {
            "success": True,
            "message": f"Successfully added {len(new_members)} member(s)",
            "added_members": list(new_members),
            "total_members": total_members,
            "seeds_stored": seeds_stored,
            "group_id": group_id
        }
        
        print(f"🎉 SUCCESS: {response_data}")
        return JsonResponse(response_data)
        
    except Exception as e:
        print(f"❌ Error in add_members_with_encryption: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": "Internal server error"}, status=500)

# ---------------- AUTHENTICATION & PROFILE ----------------

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
            avatar_file = request.FILES['avatar']
            avatar_data = base64.b64encode(avatar_file.read()).decode('utf-8')
            update_data['avatar_base64'] = avatar_data
        if request.POST.get('remove_avatar') == "true":
            update_data['avatar_base64'] = ""

        users_collection.update_one({'email': email}, {'$set': update_data})
        if new_email != email:
            request.session['email'] = new_email
        messages.success(request, 'Profile updated!')
        return redirect('profile')

    return redirect('profile')

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
    request.session.flush()
    return redirect('login')

def index(request):
    if 'email' not in request.session:
        return redirect('login')
    email = request.session['email']
    user = users_collection.find_one({"email": email})
    if not user:
        return redirect('login')
    request.session['user_id'] = str(user['_id'])
    request.session['user_full_name'] = user.get('full_name', 'User')
    return render(request, 'index.html', {
        'user_email': email,
        'user_id': str(user['_id']),
        'user_full_name': user.get('full_name', 'User'),
        'user_avatar_base64': user.get('avatar_base64', '')
    })

# ---------------- INDIVIDUAL CHAT FUNCTIONS WITH ENCRYPTION ----------------

def get_contacts(request):
    """Get all contacts for individual chat - USING ObjectId"""
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
        last_msg = messages_collection.find_one(
            {"room": room_name},
            sort=[("timestamp", -1)]
        )

        last_seen = contact.get('last_seen')
        if last_seen:
            last_seen = localtime(last_seen.replace(tzinfo=pytz.UTC))

        contact_data = {
            "id": contact_id,
            "full_name": contact.get('full_name', ''),
            "avatar_base64": contact.get('avatar_base64', ''),
            "status": contact.get('status', 'offline'),
            "last_seen": last_seen.isoformat() if last_seen else '',
            "last_message": None,
            "has_encryption": 'encryption_keys' in contact and contact['encryption_keys'] is not None
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
                "sender_id": str(last_msg.get('sender_id', '')),
                "timestamp": msg_timestamp.isoformat() if msg_timestamp else ''
            }

        serialized_contacts.append(contact_data)

    serialized_contacts.sort(
        key=lambda c: (c["last_message"]["timestamp"] if c["last_message"] else ""),
        reverse=True
    )

    return JsonResponse({"contacts": serialized_contacts})

def individual_chat_history(request):
    """Get chat history for individual conversation with encryption support - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    current_user_id = request.session['user_id']
    other_user_id = request.GET.get('user_id')
    
    if not other_user_id:
        return JsonResponse({"error": "User ID required"}, status=400)

    try:
        room_name = '_'.join(sorted([current_user_id, other_user_id]))
        
        messages = list(messages_collection.find(
            {
                "room": room_name,
                "$or": [
                    {"deleted": False},
                    {"sender_id": ObjectId(other_user_id)}
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
                "encrypted_content": msg.get('encrypted_content'),
                "iv": msg.get('iv'),
                "sender_id": str(msg['sender_id']),
                "receiver_id": str(msg['receiver_id']),
                "timestamp": timestamp.isoformat(),
                "read": msg.get('read', False),
                "edited": msg.get('edited', False),
                "deleted": msg.get('deleted', False),
                "message_type": "individual",
                "is_encrypted": 'encrypted_content' in msg and msg['encrypted_content'] is not None
            }
            
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
                "receiver_id": ObjectId(current_user_id),
                "read": False
            },
            {"$set": {"read": True}}
        )

        return JsonResponse({"messages": serialized_messages})

    except Exception as e:
        print(f"Error fetching individual chat history: {str(e)}")
        return JsonResponse({"error": "Failed to load chat history"}, status=500)

@csrf_exempt
@require_POST
def send_individual_message(request):
    """Send individual message via HTTP (WebSocket fallback) with encryption support - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        message_content = data.get('message', '').strip()
        encrypted_content = data.get('encrypted_content')
        iv = data.get('iv')
        receiver_id = data.get('receiver_id')
        temp_id = data.get('temp_id')
        
        if not receiver_id:
            return JsonResponse({"error": "Missing receiver"}, status=400)
        
        # Require either plaintext or encrypted content
        if not message_content and not encrypted_content:
            return JsonResponse({"error": "Missing message content"}, status=400)
        
        user_id = request.session['user_id']
        room_name = '_'.join(sorted([user_id, receiver_id]))
        timestamp = timezone.now()
        
        # Create message document with encryption support
        message_doc = {
            "room": room_name,
            "sender_id": ObjectId(user_id),
            "receiver_id": ObjectId(receiver_id),
            "message": message_content,
            "encrypted_content": encrypted_content,
            "iv": iv,
            "timestamp": timestamp,
            "read": False,
            "edited": False,
            "deleted": False,
            "message_type": "individual",
            "is_encrypted": encrypted_content is not None
        }
        
        result = messages_collection.insert_one(message_doc)
        message_id = str(result.inserted_id)
        
        return JsonResponse({
            "success": True,
            "message_id": message_id,
            "temp_id": temp_id,
            "timestamp": timestamp.isoformat(),
            "is_encrypted": encrypted_content is not None
        })
        
    except Exception as e:
        print(f"Error sending individual message: {e}")
        return JsonResponse({"error": "Failed to send message"}, status=500)

@csrf_exempt
@require_POST
def edit_individual_message(request):
    """Edit an individual chat message with encryption support - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        message_id = data.get('message_id')
        new_content = data.get('new_content')
        encrypted_content = data.get('encrypted_content')
        iv = data.get('iv')
        receiver_id = data.get('receiver_id')
        
        if not all([message_id, new_content or encrypted_content]):
            return JsonResponse({"error": "Missing parameters"}, status=400)
        
        user_id = request.session['user_id']
        
        update_data = {
            'edited': True,
            'edit_timestamp': timezone.now()
        }
        
        # Update both plaintext and encrypted content
        if new_content:
            update_data['message'] = new_content
        if encrypted_content:
            update_data['encrypted_content'] = encrypted_content
        if iv:
            update_data['iv'] = iv
        
        result = messages_collection.update_one(
            {
                '_id': ObjectId(message_id),
                'sender_id': ObjectId(user_id),
                'deleted': False
            },
            {
                '$set': update_data
            }
        )
        
        if result.modified_count > 0:
            return JsonResponse({"success": True})
        else:
            return JsonResponse({"error": "Message not found or not authorized"}, status=404)
            
    except Exception as e:
        print(f"Error editing individual message: {str(e)}")
        return JsonResponse({"error": "Failed to edit message"}, status=500)

@csrf_exempt
@require_POST
def delete_individual_message(request):
    """Delete an individual chat message - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        message_id = data.get('message_id')
        receiver_id = data.get('receiver_id')
        
        if not message_id:
            return JsonResponse({"error": "Message ID required"}, status=400)
        
        user_id = request.session['user_id']
        
        # Handle temp IDs
        if isinstance(message_id, str) and message_id.startswith('temp_'):
            return JsonResponse({"success": True, "message": "Temp message deleted"})
        
        result = messages_collection.update_one(
            {
                '_id': ObjectId(message_id),
                'sender_id': ObjectId(user_id)
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
            return JsonResponse({
                "success": True,
                "message": "Message deleted successfully"
            })
        else:
            return JsonResponse({
                "error": "Message not found or not authorized"
            }, status=404)
            
    except Exception as e:
        print(f"Error deleting individual message: {str(e)}")
        return JsonResponse({"error": "Failed to delete message"}, status=500)

@csrf_exempt
@require_POST
def clear_individual_chat(request):
    """Clear entire individual chat history - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        other_user_id = data.get('user_id')
        user_id = request.session['user_id']
        
        if not other_user_id:
            return JsonResponse({"error": "User ID required"}, status=400)
        
        room_name = '_'.join(sorted([user_id, other_user_id]))
        
        result = messages_collection.delete_many({
            "room": room_name,
            "message_type": "individual"
        })
        
        return JsonResponse({
            "success": True, 
            "deleted_count": result.deleted_count,
            "message": f"Cleared {result.deleted_count} messages"
        })
            
    except Exception as e:
        print(f"Error clearing individual chat: {str(e)}")
        return JsonResponse({"error": "Failed to clear chat"}, status=500)

@csrf_exempt
@require_POST
def mark_individual_as_read(request):
    """Mark individual messages as read - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        data = json.loads(request.body)
        message_ids = data.get("message_ids", [])
        if not message_ids:
            return JsonResponse({"error": "No message IDs provided"}, status=400)

        user_id = request.session['user_id']

        obj_ids = []
        for mid in message_ids:
            try:
                if isinstance(mid, str) and not mid.startswith("temp_"):
                    obj_ids.append(ObjectId(mid))
            except Exception:
                continue

        if obj_ids:
            result = messages_collection.update_many(
                {
                    "_id": {"$in": obj_ids}, 
                    "receiver_id": ObjectId(user_id)
                },
                {"$set": {"read": True, "read_timestamp": timezone.now()}}
            )
            print(f"Marked {result.modified_count} individual messages as read")

        return JsonResponse({"success": True, "message_ids": message_ids})
    except Exception as e:
        print(f"Error marking individual messages as read: {e}")
        return JsonResponse({"error": "Failed to mark messages as read"}, status=500)

# ---------------- GROUP CHAT FUNCTIONS WITH ENCRYPTION ----------------

def get_groups(request):
    """Get all groups where user is a member - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        user_id = request.session['user_id']
        groups = list(groups_collection.find({"members": ObjectId(user_id), "is_active": True}))

        serialized_groups = []
        for group in groups:
            last_msg = group.get("last_message")
            member_count = len(group.get("members", []))
            
            admin_ids = [str(admin_id) for admin_id in group.get('admin_ids', [])]
            is_admin = ObjectId(user_id) in group.get('admin_ids', [])
            
            unread_count = group_messages_collection.count_documents({
                "group_id": str(group["_id"]),
                "sender_id": {"$ne": ObjectId(user_id)},
                "read_by": {"$ne": ObjectId(user_id)}
            })
            
            serialized_groups.append({
                "id": str(group["_id"]),
                "name": group.get("name", "Unnamed Group"),
                "avatar_base64": group.get("avatar_base64", ""),
                "admin_ids": admin_ids,
                "members": [str(member) for member in group.get("members", [])],
                "member_count": member_count,
                "last_message": last_msg,
                "created_at": group.get("created_at", timezone.now()).isoformat(),
                "is_admin": is_admin,
                "unread_count": unread_count,
                "encryption_enabled": group.get("encryption_enabled", False)
            })
        
        return JsonResponse({"groups": serialized_groups})
    
    except Exception as e:
        print("Get groups error:", e)
        return JsonResponse({"error": "Failed to fetch groups"}, status=500)

def group_chat_history(request):
    """Get chat history for group with encryption support - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    group_id = request.GET.get('group_id')
    if not group_id:
        return JsonResponse({"error": "Group ID required"}, status=400)

    try:
        user_id = request.session['user_id']
        group = groups_collection.find_one({
            "_id": ObjectId(group_id), 
            "members": ObjectId(user_id),
            "is_active": True
        })
        
        if not group:
            return JsonResponse({"error": "Group not found or access denied"}, status=404)

        # FIX: Use ObjectId for group_id in query
        messages = list(group_messages_collection.find(
            {"group_id": ObjectId(group_id)},  # Convert to ObjectId
            sort=[("timestamp", 1)]
        ))

        serialized_messages = []
        for msg in messages:
            timestamp = msg["timestamp"]
            if timestamp and timestamp.tzinfo is None:
                timestamp = timezone.make_aware(timestamp)
                
            serialized_messages.append({
                "id": str(msg["_id"]),
                "sender_id": str(msg["sender_id"]),
                "sender_name": msg.get("sender_name", "Unknown"),
                "message": msg["message"],
                "encrypted_content": msg.get("encrypted_content"),
                "iv": msg.get("iv"),
                "timestamp": timestamp.isoformat(),
                "message_type": "group",
                "group_id": str(msg["group_id"]),  # Convert back to string for response
                "edited": msg.get("edited", False),
                "deleted": msg.get("deleted", False),
                "read_by": [str(user_id) for user_id in msg.get("read_by", [])],
                "is_encrypted": 'encrypted_content' in msg and msg['encrypted_content'] is not None
            })

        # FIX: Also update the mark as read query to use ObjectId
        group_messages_collection.update_many(
            {
                "group_id": ObjectId(group_id),  # Convert to ObjectId
                "sender_id": {"$ne": ObjectId(user_id)},
                "read_by": {"$ne": ObjectId(user_id)}
            },
            {"$addToSet": {"read_by": ObjectId(user_id)}}
        )

        return JsonResponse({
            "messages": serialized_messages,
            "group_info": {
                "name": group.get("name", "Unnamed Group"),
                "member_count": len(group.get("members", [])),
                "is_admin": ObjectId(user_id) in group.get('admin_ids', []),
                "encryption_enabled": group.get("encryption_enabled", False)
            }
        })
        
    except Exception as e:
        print(f"Error fetching group chat history: {str(e)}")
        return JsonResponse({"error": "Failed to load group chat history"}, status=500)

# def group_chat_history(request):
    # """Get chat history for group with encryption support - USING ObjectId"""
    # if 'user_id' not in request.session:
    #     return JsonResponse({"error": "Unauthorized"}, status=401)

    # group_id = request.GET.get('group_id')
    # if not group_id:
    #     return JsonResponse({"error": "Group ID required"}, status=400)

    # try:
    #     user_id = request.session['user_id']
    #     group = groups_collection.find_one({
    #         "_id": ObjectId(group_id), 
    #         "members": ObjectId(user_id),
    #         "is_active": True
    #     })
        
    #     if not group:
    #         return JsonResponse({"error": "Group not found or access denied"}, status=404)

    #     messages = list(group_messages_collection.find(
    #         {"group_id": group_id},
    #         sort=[("timestamp", 1)]
    #     ))

    #     serialized_messages = []
    #     for msg in messages:
    #         timestamp = msg["timestamp"]
    #         if timestamp and timestamp.tzinfo is None:
    #             timestamp = timezone.make_aware(timestamp)
                
    #         serialized_messages.append({
    #             "id": str(msg["_id"]),
    #             "sender_id": str(msg["sender_id"]),
    #             "sender_name": msg.get("sender_name", "Unknown"),
    #             "message": msg["message"],
    #             "encrypted_content": msg.get("encrypted_content"),
    #             "iv": msg.get("iv"),
    #             "timestamp": timestamp.isoformat(),
    #             "message_type": "group",
    #             "group_id": group_id,
    #             "edited": msg.get("edited", False),
    #             "deleted": msg.get("deleted", False),
    #             "read_by": [str(user_id) for user_id in msg.get("read_by", [])],
    #             "is_encrypted": 'encrypted_content' in msg and msg['encrypted_content'] is not None
    #         })

    #     # Mark messages as read for this user
    #     group_messages_collection.update_many(
    #         {
    #             "group_id": group_id,
    #             "sender_id": {"$ne": ObjectId(user_id)},
    #             "read_by": {"$ne": ObjectId(user_id)}
    #         },
    #         {"$addToSet": {"read_by": ObjectId(user_id)}}
    #     )

    #     return JsonResponse({
    #         "messages": serialized_messages,
    #         "group_info": {
    #             "name": group.get("name", "Unnamed Group"),
    #             "member_count": len(group.get("members", [])),
    #             "is_admin": ObjectId(user_id) in group.get('admin_ids', []),
    #             "encryption_enabled": group.get("encryption_enabled", False)
    #         }
    #     })
        
    # except Exception as e:
    #     print(f"Error fetching group chat history: {str(e)}")
    #     return JsonResponse({"error": "Failed to load group chat history"}, status=500)

@csrf_exempt
@require_POST
def send_group_message(request):
    """Send group message via HTTP (WebSocket fallback) with encryption support - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        message_content = data.get('message', '').strip()
        encrypted_content = data.get('encrypted_content')
        iv = data.get('iv')
        group_id = data.get('group_id')
        temp_id = data.get('temp_id')
        
        if not group_id:
            return JsonResponse({"error": "Missing group ID"}, status=400)
        
        if not message_content and not encrypted_content:
            return JsonResponse({"error": "Missing message content"}, status=400)
        
        user_id = request.session['user_id']
        
        user = users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            return JsonResponse({"error": "User not found"}, status=404)
            
        sender_name = user.get('full_name', 'Unknown User')
        
        timestamp = timezone.now()
        
        group = groups_collection.find_one({
            "_id": ObjectId(group_id),
            "members": ObjectId(user_id),
            "is_active": True
        })
        
        if not group:
            return JsonResponse({"error": "Not a member of this group"}, status=403)
        
        # Create group message document with encryption support
        message_doc = {
            "group_id": group_id,
            "sender_id": ObjectId(user_id),
            "sender_name": sender_name,
            "message": message_content,
            "encrypted_content": encrypted_content,
            "iv": iv,
            "timestamp": timestamp,
            "message_type": "group",
            "read_by": [ObjectId(user_id)],
            "edited": False,
            "deleted": False,
            "is_encrypted": encrypted_content is not None
        }
        
        result = group_messages_collection.insert_one(message_doc)
        message_id = str(result.inserted_id)
        
        # Update group's last message
        groups_collection.update_one(
            {"_id": ObjectId(group_id)},
            {"$set": {
                "last_message": {
                    "sender_id": user_id,
                    "sender_name": sender_name,
                    "content": message_content,
                    "timestamp": timestamp
                },
                "last_activity": timestamp,
                "updated_at": timestamp
            }}
        )
        
        return JsonResponse({
            "success": True,
            "message_id": message_id,
            "temp_id": temp_id,
            "timestamp": timestamp.isoformat(),
            "sender_name": sender_name,
            "is_encrypted": encrypted_content is not None
        })
        
    except Exception as e:
        print(f"Error sending group message: {e}")
        return JsonResponse({"error": "Failed to send message"}, status=500)

@csrf_exempt
@require_POST
def edit_group_message(request):
    """Edit a group chat message with encryption support - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        message_id = data.get('message_id')
        new_content = data.get('new_content')
        encrypted_content = data.get('encrypted_content')
        iv = data.get('iv')
        group_id = data.get('group_id')
        user_id = request.session['user_id']
        
        if not all([message_id, group_id, new_content or encrypted_content]):
            return JsonResponse({"error": "Missing parameters"}, status=400)
        
        update_data = {
            'edited': True,
            'edit_timestamp': timezone.now()
        }
        
        # Update both plaintext and encrypted content
        if new_content:
            update_data['message'] = new_content
        if encrypted_content:
            update_data['encrypted_content'] = encrypted_content
        if iv:
            update_data['iv'] = iv
        
        result = group_messages_collection.update_one(
            {
                '_id': ObjectId(message_id),
                'sender_id': ObjectId(user_id),
                'group_id': group_id,
                'deleted': False
            },
            {
                '$set': update_data
            }
        )
        
        if result.modified_count > 0:
            return JsonResponse({"success": True})
        else:
            return JsonResponse({"error": "Message not found or not authorized"}, status=404)
            
    except Exception as e:
        print(f"Error editing group message: {str(e)}")
        return JsonResponse({"error": "Failed to edit message"}, status=500)

@csrf_exempt
@require_POST
def delete_group_message(request):
    """Delete a group chat message - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        message_id = data.get('message_id')
        group_id = data.get('group_id')
        user_id = request.session['user_id']
        
        if not all([message_id, group_id]):
            return JsonResponse({"error": "Missing parameters"}, status=400)
        
        # Handle temp IDs
        if isinstance(message_id, str) and message_id.startswith('temp_'):
            return JsonResponse({"success": True, "message": "Temp message deleted"})
        
        result = group_messages_collection.update_one(
            {
                '_id': ObjectId(message_id),
                'sender_id': ObjectId(user_id),
                'group_id': group_id
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
            return JsonResponse({
                "success": True,
                "message": "Message deleted successfully"
            })
        else:
            return JsonResponse({
                "error": "Message not found or not authorized"
            }, status=404)
            
    except Exception as e:
        print(f"Error deleting group message: {str(e)}")
        return JsonResponse({"error": "Failed to delete message"}, status=500)

@csrf_exempt
@require_POST
def clear_group_chat(request):
    """Clear entire group chat history - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')
        user_id = request.session['user_id']
        
        if not group_id:
            return JsonResponse({"error": "Group ID required"}, status=400)
        
        # Check if user is admin
        group = groups_collection.find_one({
            "_id": ObjectId(group_id),
            "admin_ids": ObjectId(user_id),
            "is_active": True
        })
        
        if not group:
            return JsonResponse({"error": "Only admin can clear group chat"}, status=403)
        
        result = group_messages_collection.delete_many({"group_id": group_id})
        
        # Clear last message
        groups_collection.update_one(
            {"_id": ObjectId(group_id)},
            {"$set": {"last_message": None}}
        )
        
        return JsonResponse({
            "success": True, 
            "deleted_count": result.deleted_count,
            "message": f"Cleared {result.deleted_count} messages from group"
        })
            
    except Exception as e:
        print(f"Error clearing group chat: {str(e)}")
        return JsonResponse({"error": "Failed to clear group chat"}, status=500)

@csrf_exempt
@require_POST
def mark_group_as_read(request):
    """Mark group messages as read - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        data = json.loads(request.body)
        message_ids = data.get("message_ids", [])
        group_id = data.get("group_id")
        
        if not message_ids or not group_id:
            return JsonResponse({"error": "No message IDs or group ID provided"}, status=400)

        user_id = request.session['user_id']

        obj_ids = []
        for mid in message_ids:
            try:
                if isinstance(mid, str) and not mid.startswith("temp_"):
                    obj_ids.append(ObjectId(mid))
            except Exception:
                continue

        if obj_ids:
            # Add user to read_by array for each message
            for msg_id in obj_ids:
                group_messages_collection.update_one(
                    {
                        "_id": msg_id, 
                        "group_id": group_id
                    },
                    {"$addToSet": {"read_by": ObjectId(user_id)}}
                )

        return JsonResponse({"success": True, "message_ids": message_ids})
    except Exception as e:
        print(f"Error marking group messages as read: {e}")
        return JsonResponse({"error": "Failed to mark messages as read"}, status=500)

# ---------------- GROUP MANAGEMENT FUNCTIONS ----------------

@csrf_exempt
@require_POST
def get_group_members(request):
    """Get all members of a specific group - All members can access - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')
        
        if not group_id:
            return JsonResponse({"error": "Group ID required"}, status=400)
        
        user_id = request.session['user_id']
        
        print(f"🔧 GET_GROUP_MEMBERS - Group: {group_id}, User: {user_id}")
        
        # Verify group exists and user is a member
        group = groups_collection.find_one({
            "_id": ObjectId(group_id),
            "is_active": True
        })
        
        if not group:
            print(f"❌ Group not found: {group_id}")
            return JsonResponse({"error": "Group not found"}, status=404)
        
        # Check if user is a member of the group
        if ObjectId(user_id) not in group.get('members', []):
            print(f"❌ User {user_id} is not a member of group {group_id}")
            return JsonResponse({"error": "You are not a member of this group"}, status=403)
        
        print(f"✅ User is member of group. Fetching member details...")
        
        # Get all admin IDs
        admin_ids = group.get('admin_ids', [])
        
        print(f"🔧 Admin IDs for group: {[str(admin_id) for admin_id in admin_ids]}")
        
        # Get all group members with their user details
        members_data = []
        member_ids = group.get('members', [])
        
        print(f"🔧 Fetching details for {len(member_ids)} members...")
        
        for member_id in member_ids:
            try:
                user = users_collection.find_one({"_id": member_id})
                if user:
                    is_admin = member_id in admin_ids
                    is_online = user.get('status') == 'online'
                    
                    member_data = {
                        'id': str(member_id),
                        'full_name': user.get('full_name', 'User'),
                        'avatar_base64': user.get('avatar_base64', ''),
                        'is_admin': is_admin,
                        'is_online': is_online,
                        'email': user.get('email', ''),
                        'status': user.get('status', 'offline')
                    }
                    
                    # Add last_seen if available and user is offline
                    if not is_online and user.get('last_seen'):
                        last_seen = user['last_seen']
                        if last_seen and last_seen.tzinfo is None:
                            last_seen = timezone.make_aware(last_seen)
                        member_data['last_seen'] = last_seen.isoformat()
                    
                    members_data.append(member_data)
                    print(f"✅ Added member: {member_data['full_name']} (Admin: {is_admin})")
                else:
                    print(f"❌ User not found for ID: {member_id}")
                    
            except Exception as e:
                print(f"❌ Error processing member {member_id}: {str(e)}")
                continue
        
        # Sort members: admins first, then online users, then by name
        members_data.sort(key=lambda x: (
            not x['is_admin'],  # Admins first (True > False)
            not x['is_online'], # Online users next
            x['full_name'].lower()  # Then alphabetically
        ))
        
        print(f"✅ Successfully fetched {len(members_data)} members")
        
        response_data = {
            'success': True,
            'members': members_data,
            'total_members': len(members_data),
            'group_name': group.get('name', 'Group'),
            'admin_ids': [str(admin_id) for admin_id in admin_ids],
            'current_user_is_admin': ObjectId(user_id) in admin_ids
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        print(f"❌ Error getting group members: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': 'Failed to fetch group members'}, status=500)

@csrf_exempt
@require_POST
def remove_group_member(request):
    """Remove members from the group - Admin only (supports multiple member removal) - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')
        member_ids = data.get('member_ids', [])
        
        print(f"🔧 REMOVE_GROUP_MEMBER - Group: {group_id}, Members to remove: {member_ids}")
        
        if not group_id or not member_ids:
            return JsonResponse({'error': 'Group ID and Member IDs required'}, status=400)
        
        # Ensure member_ids is a list (handle both single and multiple)
        if not isinstance(member_ids, list):
            member_ids = [member_ids]
        
        user_id = request.session['user_id']
        user_object_id = ObjectId(user_id)
        
        # Get group
        group = groups_collection.find_one({
            "_id": ObjectId(group_id),
            "is_active": True
        })
        
        if not group:
            return JsonResponse({'error': 'Group not found'}, status=404)
        
        # Get all admins
        admin_ids = group.get('admin_ids', [])
        
        # Check if current user is admin
        if user_object_id not in admin_ids:
            return JsonResponse({'error': 'Only admins can remove members'}, status=403)
        
        print(f"🔧 User {user_id} is admin. Current admins: {[str(admin_id) for admin_id in admin_ids]}")
        
        # Get current members
        current_members = group.get('members', [])
        removed_members_info = []
        members_to_remove = []
        admins_to_remove = []
        errors = []
        
        for member_id in member_ids:
            member_object_id = ObjectId(member_id)
            
            # Prevent self-removal (unless it's the last admin leaving)
            if member_object_id == user_object_id:
                # Check if this is the only admin trying to remove themselves
                if len(admin_ids) == 1:
                    errors.append('You are the only admin. You cannot remove yourself. Transfer admin rights first or delete the group.')
                    continue
                else:
                    # Admin can remove themselves if there are other admins
                    print(f"⚠️ Admin {member_id} is removing themselves from the group")
            
            # Check if member exists in group
            if member_object_id not in current_members:
                errors.append(f'Member {member_id} not found in group')
                continue
            
            # Get member info before removal
            member_user = users_collection.find_one({"_id": member_object_id})
            if not member_user:
                errors.append(f'Member {member_id} not found in database')
                continue
            
            # Track if this member is an admin
            is_admin = member_object_id in admin_ids
            
            members_to_remove.append(member_object_id)
            if is_admin:
                admins_to_remove.append(member_object_id)
            
            removed_members_info.append({
                'id': member_id,
                'full_name': member_user.get('full_name', 'User'),
                'was_admin': is_admin
            })
        
        if not members_to_remove:
            if errors:
                return JsonResponse({'error': '; '.join(errors)}, status=400)
            else:
                return JsonResponse({'error': 'No valid members to remove'}, status=400)
        
        # ✅ Delete encrypted seeds for removed members
        seeds_deleted = 0
        try:
            # Delete all encrypted seeds for the removed members in this group
            delete_result = group_seeds_collection.delete_many({
                "group_id": ObjectId(group_id),
                "member_id": {"$in": members_to_remove}
            })
            seeds_deleted = delete_result.deleted_count
            print(f"✅ Deleted {seeds_deleted} encrypted seeds for removed members")
        except Exception as seed_error:
            print(f"⚠️ Error deleting encrypted seeds: {seed_error}")
        
        # Remove members from group members list
        updated_members = [m for m in current_members if m not in members_to_remove]
        
        # Update admin_ids (remove admins that are being removed)
        updated_admin_ids = [admin_id for admin_id in admin_ids if admin_id not in admins_to_remove]
        
        # Ensure we don't end up with no admins
        if len(updated_admin_ids) == 0:
            # If we're removing all admins, we need to assign a new admin
            if updated_members:
                # Assign the first remaining member as admin
                new_admin = updated_members[0]
                updated_admin_ids = [new_admin]
                print(f"⚠️ All admins removed. Assigning {new_admin} as new admin")
            else:
                # No members left - this shouldn't happen normally
                return JsonResponse({'error': 'Cannot remove all members from group'}, status=400)
        
        # Prepare update data
        update_data = {
            "members": updated_members,
            "updated_at": timezone.now(),
            "member_count": len(updated_members)
        }
        
        # Always update admin_ids to the new structure
        update_data["admin_ids"] = updated_admin_ids
        
        result = groups_collection.update_one(
            {"_id": ObjectId(group_id)},
            {"$set": update_data}
        )
        
        if result.modified_count > 0:
            # Send WebSocket notifications for removed members
            for member_id in members_to_remove:
                try:
                    # Notify the removed user
                    channel_layer = get_channel_layer()
                    user_channel_name = f"user_{str(member_id)}"
                    
                    async_to_sync(channel_layer.group_send)(
                        user_channel_name,
                        {
                            'type': 'group_user_removed',
                            'group_id': group_id,
                            'group_name': group.get('name', 'Group'),
                            'removed_by': user_id,
                            'removed_by_name': request.session.get('full_name', 'User'),
                            'timestamp': timezone.now().isoformat()
                        }
                    )
                    
                    # Remove user from group channel
                    group_channel_name = f"group_{group_id}"
                    async_to_sync(channel_layer.group_discard)(
                        group_channel_name,
                        user_channel_name
                    )
                    
                except Exception as ws_error:
                    print(f"⚠️ WebSocket error for user {member_id}: {ws_error}")
            
            # Notify remaining group members about the changes
            try:
                channel_layer = get_channel_layer()
                group_channel_name = f"group_{group_id}"
                
                async_to_sync(channel_layer.group_send)(
                    group_channel_name,
                    {
                        'type': 'group_members_updated',
                        'group_id': group_id,
                        'action': 'removed',
                        'removed_members': removed_members_info,
                        'removed_by': user_id,
                        'removed_by_name': request.session.get('full_name', 'User'),
                        'total_members': len(updated_members),
                        'timestamp': timezone.now().isoformat()
                    }
                )
                
            except Exception as ws_error:
                print(f"⚠️ Group WebSocket error: {ws_error}")
            
            response_data = {
                'success': True,
                'message': f'Removed {len(removed_members_info)} member{"" if len(removed_members_info) == 1 else "s"} from group',
                'removed_members': removed_members_info,
                'total_members': len(updated_members),
                'admins_updated': len(admins_to_remove) > 0,
                'new_admin_count': len(updated_admin_ids),
                'seeds_deleted': seeds_deleted
            }
            
            # Add errors if any (for partial successes)
            if errors:
                response_data['warnings'] = errors
            
            print(f"✅ Successfully removed {len(removed_members_info)} members from group")
            print(f"✅ Deleted {seeds_deleted} encrypted seeds")
            print(f"✅ Updated admin list: {[str(admin_id) for admin_id in updated_admin_ids]}")
            return JsonResponse(response_data)
        else:
            print("❌ Failed to update group in database")
            return JsonResponse({'error': 'Failed to remove members'}, status=500)
        
    except Exception as e:
        print(f"❌ Error removing group members: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': 'Failed to remove members'}, status=500)

@csrf_exempt
@require_POST
def make_group_admin(request):
    """Promote a regular member to admin status - Admin only - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')
        new_admin_id = data.get('member_id')
        
        print(f"🔧 MAKE ADMIN REQUEST - Group: {group_id}, New Admin: {new_admin_id}")
        
        if not group_id or not new_admin_id:
            return JsonResponse({'error': 'Group ID and Member ID required'}, status=400)
        
        user_id = request.session['user_id']
        user_object_id = ObjectId(user_id)
        new_admin_object_id = ObjectId(new_admin_id)
        
        # Get group
        group = groups_collection.find_one({
            "_id": ObjectId(group_id),
            "is_active": True
        })
        
        if not group:
            return JsonResponse({'error': 'Group not found'}, status=404)
        
        # Check if user is admin of this group
        admin_ids = group.get('admin_ids', [])
        if user_object_id not in admin_ids:
            return JsonResponse({'error': 'Only admins can promote members'}, status=403)
        
        # Check if member is already admin
        if new_admin_object_id in admin_ids:
            return JsonResponse({'error': 'Member is already an admin'}, status=400)
        
        # Verify new admin is a member of the group
        if new_admin_object_id not in group.get('members', []):
            return JsonResponse({'error': 'User is not a member of this group'}, status=400)
        
        # Get member info
        new_admin_user = users_collection.find_one({"_id": new_admin_object_id})
        if not new_admin_user:
            return JsonResponse({'error': 'Member not found'}, status=404)
        
        promoted_member_info = {
            'id': new_admin_id,
            'full_name': new_admin_user.get('full_name', 'User')
        }
        
        # Add to admin_ids array
        updated_admin_ids = admin_ids + [new_admin_object_id]
        
        result = groups_collection.update_one(
            {"_id": ObjectId(group_id)},
            {
                "$set": {
                    "admin_ids": updated_admin_ids,
                    "updated_at": timezone.now()
                }
            }
        )
        
        if result.modified_count > 0:
            return JsonResponse({
                'success': True,
                'message': f'Promoted {promoted_member_info["full_name"]} to admin',
                'promoted_member': promoted_member_info,
                'new_admin_id': new_admin_id
            })
        else:
            return JsonResponse({'error': 'Failed to promote member'}, status=500)
        
    except Exception as e:
        print(f"Error making group admin: {str(e)}")
        return JsonResponse({'error': 'Failed to promote member'}, status=500)

@csrf_exempt
@require_POST
def delete_group(request):
    """Permanently delete the entire group - Admin only (multi-admin support) - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')
        
        if not group_id:
            return JsonResponse({'error': 'Group ID required'}, status=400)
        
        user_id = request.session['user_id']
        user_object_id = ObjectId(user_id)
        
        # Get group
        group = groups_collection.find_one({
            "_id": ObjectId(group_id)
        })
        
        if not group:
            return JsonResponse({'error': 'Group not found'}, status=404)
        
        # Get all admins
        admin_ids = group.get('admin_ids', [])
        
        # Check if user is admin of this group
        if user_object_id not in admin_ids:
            return JsonResponse({'error': 'Only admins can delete the group'}, status=403)
        
        print(f"🔧 DELETE_GROUP - User {user_id} deleting group {group_id}")
        print(f"🔧 Current admins: {[str(admin_id) for admin_id in admin_ids]}")
        
        # Store group info for response
        group_info = {
            'id': group_id,
            'name': group.get('name', 'Group'),
            'total_members': len(group.get('members', [])),
            'total_admins': len(admin_ids),
            'deleted_by_admin': user_id
        }
        
        # SOFT DELETE: Mark group as inactive
        result = groups_collection.update_one(
            {"_id": ObjectId(group_id)},
            {
                "$set": {
                    "is_active": False,
                    "deleted_at": timezone.now(),
                    "deleted_by": user_object_id,
                    "deleted_by_name": request.session.get('full_name', 'User')
                }
            }
        )
        
        if result.modified_count > 0:
            # Send WebSocket notifications to all group members
            try:
                channel_layer = get_channel_layer()
                group_channel_name = f"group_{group_id}"
                
                # Notify all group members
                async_to_sync(channel_layer.group_send)(
                    group_channel_name,
                    {
                        'type': 'group_deleted',
                        'group_id': group_id,
                        'group_name': group.get('name', 'Group'),
                        'deleted_by': user_id,
                        'deleted_by_name': request.session.get('full_name', 'User'),
                        'timestamp': timezone.now().isoformat(),
                        'total_members_affected': len(group.get('members', []))
                    }
                )
                
                # Also notify each member individually
                for member_id in group.get('members', []):
                    try:
                        user_channel_name = f"user_{str(member_id)}"
                        async_to_sync(channel_layer.group_send)(
                            user_channel_name,
                            {
                                'type': 'group_deleted_notification',
                                'group_id': group_id,
                                'group_name': group.get('name', 'Group'),
                                'deleted_by': user_id,
                                'deleted_by_name': request.session.get('full_name', 'User'),
                                'timestamp': timezone.now().isoformat()
                            }
                        )
                    except Exception as user_ws_error:
                        print(f"⚠️ User WebSocket error for {member_id}: {user_ws_error}")
                
            except Exception as ws_error:
                print(f"⚠️ Group WebSocket error: {ws_error}")
            
            return JsonResponse({
                'success': True,
                'message': f'Group "{group_info["name"]}" has been deleted',
                'deleted_group': group_info
            })
        else:
            return JsonResponse({'error': 'Failed to delete group'}, status=500)
        
    except Exception as e:
        print(f"❌ Error deleting group: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': 'Failed to delete group'}, status=500)

@csrf_exempt
@require_POST
def leave_group(request):
    """Allow a member to leave the group voluntarily - Any member (multi-admin support) - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')
        
        if not group_id:
            return JsonResponse({'error': 'Group ID required'}, status=400)
        
        user_id = request.session['user_id']
        user_object_id = ObjectId(user_id)
        
        # Get group
        group = groups_collection.find_one({
            "_id": ObjectId(group_id),
            "is_active": True
        })
        
        if not group:
            return JsonResponse({'error': 'Group not found'}, status=404)
        
        # Check if user is a member
        if user_object_id not in group.get('members', []):
            return JsonResponse({'error': 'You are not a member of this group'}, status=400)
        
        # Get all admins
        admin_ids = group.get('admin_ids', [])
        
        print(f"🔧 LEAVE_GROUP - User {user_id} leaving group {group_id}")
        print(f"🔧 Current admins: {[str(admin_id) for admin_id in admin_ids]}")
        print(f"🔧 Current members: {[str(member_id) for member_id in group.get('members', [])]}")
        
        # Check if user is an admin
        is_admin = user_object_id in admin_ids
        
        # If user is admin, handle admin-specific logic
        if is_admin:
            print(f"⚠️ User {user_id} is an admin, checking admin conditions...")
            
            # Count remaining admins after this user leaves
            remaining_admins = [admin_id for admin_id in admin_ids if admin_id != user_object_id]
            remaining_members = [member for member in group.get('members', []) if member != user_object_id]
            
            print(f"🔧 Remaining admins after leave: {[str(admin_id) for admin_id in remaining_admins]}")
            print(f"🔧 Remaining members after leave: {[str(member_id) for member_id in remaining_members]}")
            
            # Check if this is the last admin
            if len(remaining_admins) == 0:
                print("⚠️ Last admin is leaving the group")
                
                # If no members left, delete the group
                if not remaining_members:
                    print("🗑️ No members left, deleting group...")
                    # SOFT DELETE: Mark group as inactive
                    groups_collection.update_one(
                        {"_id": ObjectId(group_id)},
                        {
                            "$set": {
                                "is_active": False,
                                "deleted_at": timezone.now(),
                                "deleted_by": user_object_id,
                                "deleted_by_name": request.session.get('full_name', 'User')
                            }
                        }
                    )
                    
                    # Send WebSocket notifications
                    try:
                        channel_layer = get_channel_layer()
                        group_channel_name = f"group_{group_id}"
                        
                        async_to_sync(channel_layer.group_send)(
                            group_channel_name,
                            {
                                'type': 'group_deleted',
                                'group_id': group_id,
                                'group_name': group.get('name', 'Group'),
                                'deleted_by': user_id,
                                'deleted_by_name': request.session.get('full_name', 'User'),
                                'timestamp': timezone.now().isoformat(),
                                'reason': 'last_admin_left_no_members'
                            }
                        )
                    except Exception as ws_error:
                        print(f"⚠️ WebSocket error: {ws_error}")
                    
                    return JsonResponse({
                        'success': True,
                        'message': 'You have left the group. Since you were the last member, the group has been deleted.',
                        'group_deleted': True,
                        'was_admin': True,
                        'was_last_admin': True
                    })
                else:
                    # There are members but no admins - assign a new admin
                    print(f"👑 Assigning new admin from remaining members: {[str(member_id) for member_id in remaining_members]}")
                    new_admin = remaining_members[0]  # Assign first remaining member as admin
                    
                    # Update group - remove user and assign new admin
                    update_data = {
                        "members": remaining_members,
                        "updated_at": timezone.now(),
                        "member_count": len(remaining_members),
                        "admin_ids": [new_admin]
                    }
                    
                    result = groups_collection.update_one(
                        {"_id": ObjectId(group_id)},
                        {"$set": update_data}
                    )
                    
                    if result.modified_count > 0:
                        # Send WebSocket notifications
                        try:
                            channel_layer = get_channel_layer()
                            group_channel_name = f"group_{group_id}"
                            
                            # Get new admin info
                            new_admin_user = users_collection.find_one({"_id": new_admin})
                            new_admin_name = new_admin_user.get('full_name', 'User') if new_admin_user else 'User'
                            
                            async_to_sync(channel_layer.group_send)(
                                group_channel_name,
                                {
                                    'type': 'group_admin_transferred',
                                    'group_id': group_id,
                                    'old_admin_id': user_id,
                                    'old_admin_name': request.session.get('full_name', 'User'),
                                    'new_admin_id': str(new_admin),
                                    'new_admin_name': new_admin_name,
                                    'timestamp': timezone.now().isoformat(),
                                    'reason': 'admin_left_group'
                                }
                            )
                            
                            # Also send member left notification
                            async_to_sync(channel_layer.group_send)(
                                group_channel_name,
                                {
                                    'type': 'group_member_left',
                                    'group_id': group_id,
                                    'member_id': user_id,
                                    'member_name': request.session.get('full_name', 'User'),
                                    'was_admin': True,
                                    'timestamp': timezone.now().isoformat(),
                                    'new_admin_assigned': str(new_admin)
                                }
                            )
                            
                        except Exception as ws_error:
                            print(f"⚠️ WebSocket error: {ws_error}")
                        
                        return JsonResponse({
                            'success': True,
                            'message': f'You have left the group. {new_admin_name} has been assigned as the new admin.',
                            'group_deleted': False,
                            'was_admin': True,
                            'was_last_admin': True,
                            'new_admin_assigned': str(new_admin),
                            'new_admin_name': new_admin_name,
                            'total_members': len(remaining_members)
                        })
                    else:
                        return JsonResponse({'error': 'Failed to leave group and assign new admin'}, status=500)
            else:
                # There are other admins, just remove this admin from the group
                print(f"🔧 Removing admin {user_id} from group, other admins remain")
                remaining_members = [member for member in group.get('members', []) if member != user_object_id]
                updated_admin_ids = [admin_id for admin_id in admin_ids if admin_id != user_object_id]
                
                update_data = {
                    "members": remaining_members,
                    "updated_at": timezone.now(),
                    "member_count": len(remaining_members),
                    "admin_ids": updated_admin_ids
                }
                
                result = groups_collection.update_one(
                    {"_id": ObjectId(group_id)},
                    {"$set": update_data}
                )
                
                if result.modified_count > 0:
                    # Send WebSocket notifications
                    try:
                        channel_layer = get_channel_layer()
                        group_channel_name = f"group_{group_id}"
                        
                        async_to_sync(channel_layer.group_send)(
                            group_channel_name,
                            {
                                'type': 'group_member_left',
                                'group_id': group_id,
                                'member_id': user_id,
                                'member_name': request.session.get('full_name', 'User'),
                                'was_admin': True,
                                'timestamp': timezone.now().isoformat(),
                                'remaining_admins': [str(admin_id) for admin_id in updated_admin_ids]
                            }
                        )
                    except Exception as ws_error:
                        print(f"⚠️ WebSocket error: {ws_error}")
                    
                    return JsonResponse({
                        'success': True,
                        'message': f'You have left the group "{group.get("name", "Group")}"',
                        'total_members': len(remaining_members),
                        'group_deleted': False,
                        'was_admin': True,
                        'was_last_admin': False,
                        'remaining_admins': [str(admin_id) for admin_id in updated_admin_ids]
                    })
                else:
                    return JsonResponse({'error': 'Failed to leave group'}, status=500)
        else:
            # Regular member leaving (not an admin)
            print(f"🔧 Removing regular member {user_id} from group")
            remaining_members = [member for member in group.get('members', []) if member != user_object_id]
            
            result = groups_collection.update_one(
                {"_id": ObjectId(group_id)},
                {
                    "$set": {
                        "members": remaining_members,
                        "updated_at": timezone.now(),
                        "member_count": len(remaining_members)
                    }
                }
            )
            
            if result.modified_count > 0:
                # Send WebSocket notifications
                try:
                    channel_layer = get_channel_layer()
                    group_channel_name = f"group_{group_id}"
                    
                    async_to_sync(channel_layer.group_send)(
                        group_channel_name,
                        {
                            'type': 'group_member_left',
                            'group_id': group_id,
                            'member_id': user_id,
                            'member_name': request.session.get('full_name', 'User'),
                            'was_admin': False,
                            'timestamp': timezone.now().isoformat(),
                            'total_members': len(remaining_members)
                        }
                    )
                except Exception as ws_error:
                    print(f"⚠️ WebSocket error: {ws_error}")
                
                return JsonResponse({
                    'success': True,
                    'message': f'You have left the group "{group.get("name", "Group")}"',
                    'total_members': len(remaining_members),
                    'group_deleted': False,
                    'was_admin': False
                })
            else:
                return JsonResponse({'error': 'Failed to leave group'}, status=500)
        
    except Exception as e:
        print(f"❌ Error leaving group: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': 'Failed to leave group'}, status=500)

@csrf_exempt
@require_POST
def get_available_contacts_for_group(request):
    """Get contacts that are not already in the group - For adding members or creating new groups - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')
        
        user_id = request.session['user_id']
        user_object_id = ObjectId(user_id)
        
        if group_id:
            # For existing group - get contacts not in this group
            group = groups_collection.find_one({
                "_id": ObjectId(group_id),
                "is_active": True
            })
            
            if not group:
                return JsonResponse({'error': 'Group not found'}, status=404)
            
            # Check if user is a member
            if user_object_id not in group.get('members', []):
                return JsonResponse({'error': 'You are not a member of this group'}, status=403)
            
            group_member_ids = set(group.get('members', []))
            
            # Get all users except current user and existing group members
            available_contacts = list(users_collection.find(
                {
                    "_id": {"$ne": user_object_id},
                    "_id": {"$nin": list(group_member_ids)}
                },
                {'full_name': 1, 'avatar_base64': 1, 'email': 1}
            ))
        else:
            # For new group creation - get all contacts except current user
            available_contacts = list(users_collection.find(
                {
                    "_id": {"$ne": user_object_id}
                },
                {'full_name': 1, 'avatar_base64': 1, 'email': 1}
            ))
        
        serialized_contacts = []
        for contact in available_contacts:
            serialized_contacts.append({
                'id': str(contact['_id']),
                'full_name': contact.get('full_name', 'User'),
                'avatar_base64': contact.get('avatar_base64', ''),
                'email': contact.get('email', '')
            })
        
        return JsonResponse({
            'success': True,
            'available_contacts': serialized_contacts,
            'total_available': len(serialized_contacts)
        })
        
    except Exception as e:
        print(f"Error getting available contacts: {str(e)}")
        return JsonResponse({'error': 'Failed to fetch available contacts'}, status=500)

@csrf_exempt
@require_POST
def bulk_remove_group_admins(request):
    """Remove admin privileges from multiple members - Admin only - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')
        remove_admin_ids = data.get('member_ids', [])
        
        print(f"🔧 BULK REMOVE ADMINS REQUEST - Group: {group_id}, Remove Admins: {remove_admin_ids}")
        
        if not group_id:
            return JsonResponse({'error': 'Group ID required'}, status=400)
        
        if not remove_admin_ids:
            return JsonResponse({'error': 'At least one Member ID required'}, status=400)
        
        user_id = request.session['user_id']
        user_object_id = ObjectId(user_id)
        
        # Get group
        group = groups_collection.find_one({
            "_id": ObjectId(group_id),
            "is_active": True
        })
        
        if not group:
            return JsonResponse({'error': 'Group not found'}, status=404)
        
        # Check if user is admin of this group
        admin_ids = group.get('admin_ids', [])
        if user_object_id not in admin_ids:
            return JsonResponse({'error': 'Only admins can remove admin privileges'}, status=403)
        
        # Check if trying to remove self
        if user_object_id in [ObjectId(admin_id) for admin_id in remove_admin_ids]:
            return JsonResponse({'error': 'You cannot remove your own admin privileges'}, status=400)
        
        # Convert remove_admin_ids to ObjectId
        remove_admin_object_ids = [ObjectId(admin_id) for admin_id in remove_admin_ids]
        
        # Filter only existing admins from the list
        existing_admin_ids_to_remove = [admin_id for admin_id in remove_admin_object_ids if admin_id in admin_ids]
        
        if not existing_admin_ids_to_remove:
            return JsonResponse({'error': 'None of the specified members are admins'}, status=400)
        
        # Count current admins and check if we're removing too many
        current_admin_count = len(admin_ids)
        remaining_admins = current_admin_count - len(existing_admin_ids_to_remove)
        
        # Prevent removing all admins
        if remaining_admins < 1:
            return JsonResponse({'error': 'Cannot remove all admins from the group'}, status=400)
        
        # Get member info for removed admins
        removed_members_info = []
        for admin_id in existing_admin_ids_to_remove:
            admin_user = users_collection.find_one({"_id": admin_id})
            if admin_user:
                removed_members_info.append({
                    'id': str(admin_id),
                    'full_name': admin_user.get('full_name', 'User')
                })
        
        # Remove from admin_ids array
        updated_admin_ids = [admin_id for admin_id in admin_ids if admin_id not in existing_admin_ids_to_remove]
        
        result = groups_collection.update_one(
            {"_id": ObjectId(group_id)},
            {
                "$set": {
                    "admin_ids": updated_admin_ids,
                    "updated_at": timezone.now()
                }
            }
        )
        
        if result.modified_count > 0:
            # Send WebSocket notifications
            try:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f"group_{group_id}",
                    {
                        'type': 'group_admins_removed',
                        'group_id': group_id,
                        'removed_member_ids': [str(admin_id) for admin_id in existing_admin_ids_to_remove],
                        'removed_member_names': [m['full_name'] for m in removed_members_info],
                        'removed_by_id': user_id,
                        'removed_by_name': request.session.get('full_name', 'Admin'),
                        'timestamp': str(timezone.now())
                    }
                )
                print("✅ WebSocket notification sent for bulk admin removal")
            except Exception as ws_error:
                print(f"⚠️ WebSocket notification failed: {str(ws_error)}")
            
            return JsonResponse({
                'success': True,
                'message': f'Removed admin privileges from {len(removed_members_info)} member(s)',
                'removed_members': removed_members_info,
                'removed_admin_ids': [str(admin_id) for admin_id in existing_admin_ids_to_remove],
                'admins_remaining': len(updated_admin_ids),
                'total_removed': len(removed_members_info)
            })
        else:
            return JsonResponse({'error': 'Failed to remove admin privileges'}, status=500)
        
    except Exception as e:
        print(f"❌ Error in bulk remove group admins: {str(e)}")
        return JsonResponse({'error': 'Failed to remove admin privileges'}, status=500)