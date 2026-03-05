from django.http import JsonResponse
from django.utils import timezone
from django.utils.timezone import localtime
from bson import ObjectId
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import pytz
import json

# Import DB collections
from .common import users_collection, messages_collection

def get_contacts(request):
    """Get contacts for individual chat - Optimized with avatars excluded and pagination added"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    user_id = request.session['user_id']
    
    # Pagination parameters
    try:
        offset = int(request.GET.get('offset', 0))
        limit = int(request.GET.get('limit', 20))
    except (ValueError, TypeError):
        offset = 0
        limit = 20

    # Optimization: Using aggregation to fetch contacts and their last messages in one go
    pipeline = [
        # 1. Match all users except current user
        {"$match": {"_id": {"$ne": ObjectId(user_id)}}},
        
        # 2. Add room name for each contact to lookup last message
        {"$addFields": {
            "userIdStr": {"$toString": "$_id"},
            "myIdStr": user_id
        }},
        {"$addFields": {
            "roomName": {
                "$cond": [
                    {"$lt": ["$myIdStr", "$userIdStr"]},
                    {"$concat": ["$myIdStr", "_", "$userIdStr"]},
                    {"$concat": ["$userIdStr", "_", "$myIdStr"]}
                ]
            }
        }},
        
        # 3. Lookup last message from messages_collection for this room
        {"$lookup": {
            "from": "messages_websocket",
            "let": {"room": "$roomName"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$room", "$$room"]}}},
                {"$sort": {"timestamp": -1}},
                {"$limit": 1}
            ],
            "as": "last_msg"
        }},
        {"$unwind": {"path": "$last_msg", "preserveNullAndEmptyArrays": True}},
        
        # 4. Filter/Project fields for performance
        {"$project": {
            "full_name": 1,
            "status": 1,
            "last_seen": 1,
            "email": 1,
            "phone_number": 1,
            "encryption_keys": 1,
            "last_msg": 1
        }},
        
        # 5. Sort by last message timestamp (or empty for users with no messages)
        {"$sort": {
            "last_msg.timestamp": -1,
            "full_name": 1
        }},
        
        # 6. Pagination
        {"$facet": {
            "metadata": [{"$count": "total"}],
            "data": [{"$skip": offset}, {"$limit": limit}]
        }}
    ]

    results = list(users_collection.aggregate(pipeline))
    
    total = results[0]['metadata'][0]['total'] if results and results[0]['metadata'] else 0
    contacts_data = results[0]['data'] if results else []

    serialized_contacts = []
    for contact in contacts_data:
        contact_id = str(contact['_id'])
        last_msg = contact.get('last_msg')

        last_seen = contact.get('last_seen')
        if last_seen:
            if isinstance(last_seen, str):
                try:
                    from dateutil.parser import parse
                    last_seen = parse(last_seen)
                except:
                    pass
            if hasattr(last_seen, 'replace'):
                last_seen = localtime(last_seen.replace(tzinfo=pytz.UTC))

        contact_data = {
            "id": contact_id,
            "full_name": contact.get('full_name', ''),
            "email": contact.get('email', ''),
            "phone_number": contact.get('phone_number', ''),
            "status": contact.get('status', 'offline'),
            "last_seen": last_seen.isoformat() if hasattr(last_seen, 'isoformat') else str(last_seen) if last_seen else '',
            "last_message": None,
            "has_encryption": 'encryption_keys' in contact and contact['encryption_keys'] is not None,
            "public_key": contact.get('encryption_keys', {}).get('public_key') if contact.get('encryption_keys') else None
        }

        if last_msg:
            msg_timestamp = last_msg.get('timestamp')
            if msg_timestamp:
                if isinstance(msg_timestamp, str):
                    try:
                        from dateutil.parser import parse
                        msg_timestamp = parse(msg_timestamp)
                    except:
                        pass
                if hasattr(msg_timestamp, 'replace'):
                    msg_timestamp = localtime(msg_timestamp.replace(tzinfo=pytz.UTC))
            
            message_content = last_msg.get('message', '')
            if last_msg.get('is_image', False):
                message_content = '📷 Image'
            elif last_msg.get('deleted', False) and str(last_msg.get('sender_id')) != user_id:
                message_content = 'This message was deleted'
                
            contact_data["last_message"] = {
                "content": message_content,
                "sender_id": str(last_msg.get('sender_id', '')),
                "timestamp": msg_timestamp.isoformat() if hasattr(msg_timestamp, 'isoformat') else str(msg_timestamp) if msg_timestamp else ''
            }

        serialized_contacts.append(contact_data)

    has_more = (offset + limit) < total

    return JsonResponse({
        "contacts": serialized_contacts,
        "has_more": has_more,
        "total": total
    })

def get_user_avatar(request, user_id):
    """Serve user avatar separately for better caching and smaller list payload"""
    try:
        from .common import users_collection
        user = users_collection.find_one({"_id": ObjectId(user_id)}, {"avatar_base64": 1})
        if user and user.get("avatar_base64"):
            return JsonResponse({"avatar_base64": user["avatar_base64"]})
        return JsonResponse({"avatar_base64": ""})
    except:
        return JsonResponse({"avatar_base64": ""})

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
        
        # Pagination params
        before = request.GET.get('before')
        limit = 50
        
        query = {
            "room": room_name,
            "$or": [
                {"deleted": False},
                {"sender_id": ObjectId(other_user_id)}
            ]
        }
        
        if before:
            try:
                # Handle ISO format from frontend
                before_dt = timezone.datetime.fromisoformat(before.replace('Z', '+00:00'))
                query["timestamp"] = {"$lt": before_dt}
            except Exception as e:
                print(f"Error parsing before timestamp: {e}")

        # Fetch newest messages first for pagination, then reverse
        messages = list(messages_collection.find(
            query,
            sort=[("timestamp", -1)],
            limit=limit
        ))
        
        has_more = len(messages) == limit
        messages.reverse() # Restore chronological order

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
                "is_encrypted": 'encrypted_content' in msg and msg['encrypted_content'] is not None,
                "is_image": msg.get('is_image', False),
                "image_size": msg.get('image_size'),
                "media_id": msg.get('media_id')
            }
            
            # Optimization: If it's a link-based image, don't send the heavy encrypted content in history
            if message_data["is_image"] and message_data["media_id"]:
                message_data["encrypted_content"] = None
            
            if msg.get('edited') and msg.get('edit_timestamp'):
                edit_ts = msg['edit_timestamp']
                if edit_ts and edit_ts.tzinfo is None:
                    edit_ts = timezone.make_aware(edit_ts)
                message_data["edit_timestamp"] = edit_ts.isoformat()
            
            serialized_messages.append(message_data)

        # Mark messages as read (only for the last batch or all? usually all unread in room)
        messages_collection.update_many(
            {
                "room": room_name,
                "receiver_id": ObjectId(current_user_id),
                "read": False
            },
            {"$set": {"read": True}}
        )

        return JsonResponse({
            "messages": serialized_messages,
            "has_more": has_more
        })

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
        is_image = data.get('is_image', False)
        image_size = data.get('image_size')
        media_id = data.get('media_id')
        
        if not receiver_id:
            return JsonResponse({"error": "Missing receiver"}, status=400)
        
        # Require either plaintext, encrypted content, image, or media_id
        if not any([message_content, encrypted_content, is_image, media_id]):
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
            "is_encrypted": encrypted_content is not None or media_id is not None,
            "is_image": is_image,
            "image_size": image_size,
            "media_id": media_id
        }
        
        result = messages_collection.insert_one(message_doc)
        message_id = str(result.inserted_id)
        
        return JsonResponse({
            "success": True,
            "message_id": message_id,
            "temp_id": temp_id,
            "timestamp": timestamp.isoformat(),
            "is_encrypted": encrypted_content is not None or media_id is not None,
            "is_image": is_image,
            "image_size": image_size,
            "media_id": media_id
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
