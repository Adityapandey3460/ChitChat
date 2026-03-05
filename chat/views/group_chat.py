from django.http import JsonResponse
from django.utils import timezone
from bson import ObjectId
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json

# Import DB collections
from .common import groups_collection, group_messages_collection, group_seeds_collection

def get_groups(request):
    """Get groups where user is a member - Optimized with pagination"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        user_id = request.session['user_id']
        
        # Pagination parameters
        try:
            offset = int(request.GET.get('offset', 0))
            limit = int(request.GET.get('limit', 20))
        except (ValueError, TypeError):
            offset = 0
            limit = 20

        # Optimization: Use aggregation to fetch groups, unread counts, and seeds in one go
        pipeline = [
            # 1. Match active groups where user is a member
            {"$match": {
                "members": ObjectId(user_id), 
                "is_active": True
            }},
            
            # 2. Lookup unread counts from group_messages_collection
            # We handle both string and ObjectId group_id for backward compatibility
            {"$lookup": {
                "from": "messages_group",
                "let": {"gid_str": {"$toString": "$_id"}, "gid_obj": "$_id", "uid": ObjectId(user_id)},
                "pipeline": [
                    {"$match": {
                        "$expr": {
                            "$and": [
                                {"$or": [
                                    {"$eq": ["$group_id", "$$gid_str"]},
                                    {"$eq": ["$group_id", "$$gid_obj"]}
                                ]},
                                {"$ne": ["$sender_id", "$$uid"]},
                                {"$not": {"$in": ["$$uid", {"$ifNull": ["$read_by", []]}]}}
                            ]
                        }
                    }},
                    {"$count": "count"}
                ],
                "as": "unread_info"
            }},
            
            # 3. Lookup user's encrypted seed
            {"$lookup": {
                "from": "group_encrypted_seeds",
                "let": {"gid": "$_id", "uid": ObjectId(user_id)},
                "pipeline": [
                    {"$match": {
                        "$expr": {
                            "$and": [
                                {"$eq": ["$group_id", "$$gid"]},
                                {"$eq": ["$member_id", "$$uid"]}
                             ]
                        }
                    }},
                    {"$limit": 1}
                ],
                "as": "seed_info"
            }},
            
            {"$unwind": {"path": "$unread_info", "preserveNullAndEmptyArrays": True}},
            {"$unwind": {"path": "$seed_info", "preserveNullAndEmptyArrays": True}},
            
            # 4. Filter/Project fields
            {"$project": {
                "name": 1,
                "admin_ids": 1,
                "members": 1,
                "last_message": 1,
                "created_at": 1,
                "encryption_enabled": 1,
                "unread_count": {"$ifNull": ["$unread_info.count", 0]},
                "seed_info": 1
            }},
            
            # 5. Sort by last message timestamp
            {"$sort": {
                "last_message.timestamp": -1,
                "name": 1
            }},
            
            # 6. Pagination
            {"$facet": {
                "metadata": [{"$count": "total"}],
                "data": [{"$skip": offset}, {"$limit": limit}]
            }}
        ]

        results = list(groups_collection.aggregate(pipeline))
        
        total = results[0]['metadata'][0]['total'] if results and results[0]['metadata'] else 0
        groups_data = results[0]['data'] if results else []

        serialized_groups = []
        for group in groups_data:
            last_msg = group.get("last_message")
            member_ids = group.get("members", [])
            member_count = len(member_ids)
            
            admin_ids = [str(admin_id) for admin_id in group.get('admin_ids', [])]
            is_admin = ObjectId(user_id) in group.get('admin_ids', [])
            
            # Properly serialize last_message if it exists
            if last_msg:
                if not isinstance(last_msg, dict):
                    last_msg = {}
                else:
                    last_msg = last_msg.copy()
                    
                if "timestamp" in last_msg and last_msg["timestamp"]:
                    ts = last_msg["timestamp"]
                    if hasattr(ts, 'isoformat'):
                        last_msg["timestamp"] = ts.isoformat()
                if "sender_id" in last_msg:
                    last_msg["sender_id"] = str(last_msg["sender_id"])
                
                # Check for image and set display content
                if last_msg.get('is_image', False):
                    last_msg["content"] = '📷 Image'
            
            my_encrypted_seed = None
            seed_info = group.get('seed_info')
            if seed_info:
                my_encrypted_seed = {
                    "encrypted_seed": seed_info['encrypted_seed'],
                    "encrypted_by": str(seed_info['encrypted_by']),
                    "timestamp": seed_info['timestamp'],
                    "iv": seed_info['iv']
                }

            serialized_groups.append({
                "id": str(group["_id"]),
                "name": group.get("name", "Unnamed Group"),
                "admin_ids": admin_ids,
                "members": [str(member) for member in member_ids],
                "member_count": member_count,
                "last_message": last_msg,
                "created_at": group.get("created_at", timezone.now()).isoformat(),
                "is_admin": is_admin,
                "unread_count": group.get("unread_count", 0),
                "encryption_enabled": group.get("encryption_enabled", False),
                "my_encrypted_seed": my_encrypted_seed
            })
        
        has_more = (offset + limit) < total
        
        return JsonResponse({
            "groups": serialized_groups,
            "has_more": has_more,
            "total": total
        })
    
    except Exception as e:
        print("Get groups error:", e)
        return JsonResponse({"error": "Failed to fetch groups"}, status=500)

def get_group_avatar(request, group_id):
    """Serve group avatar separately"""
    try:
        from .common import groups_collection
        group = groups_collection.find_one({"_id": ObjectId(group_id)}, {"avatar_base64": 1})
        if group and group.get("avatar_base64"):
            return JsonResponse({"avatar_base64": group["avatar_base64"]})
        return JsonResponse({"avatar_base64": ""})
    except:
        return JsonResponse({"avatar_base64": ""})

def group_chat_history(request):
    """Get chat history for group with encryption support - USING ObjectId"""
    if 'user_id' not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    group_id = request.GET.get('group_id')
    if not group_id:
        return JsonResponse({"error": "Group ID required"}, status=400)

    try:
        user_id = request.session['user_id']
        
        # Pagination params
        before = request.GET.get('before')
        limit = 50
        
        group = groups_collection.find_one({
            "_id": ObjectId(group_id), 
            "members": ObjectId(user_id),
            "is_active": True
        })
        
        if not group:
            return JsonResponse({"error": "Group not found or access denied"}, status=404)

        query = {"group_id": ObjectId(group_id)}
        if before:
            try:
                before_dt = timezone.datetime.fromisoformat(before.replace('Z', '+00:00'))
                query["timestamp"] = {"$lt": before_dt}
            except Exception as e:
                print(f"Error parsing before timestamp: {e}")

        # Fetch newest first for pagination, then reverse
        messages = list(group_messages_collection.find(
            query,
            sort=[("timestamp", -1)],
            limit=limit
        ))
        
        has_more = len(messages) == limit
        messages.reverse()

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
                "group_id": str(msg["group_id"]),
                "edited": msg.get("edited", False),
                "deleted": msg.get("deleted", False),
                "read_by": [str(user_id) for user_id in msg.get("read_by", [])],
                "is_encrypted": 'encrypted_content' in msg and msg['encrypted_content'] is not None,
                "is_image": msg.get("is_image", False),
                "image_size": msg.get("image_size"),
                "media_id": msg.get("media_id")
            })
            
            # Optimization: If it's a link-based image, don't send the heavy encrypted content in history
            last_msg = serialized_messages[-1]
            if last_msg["is_image"] and last_msg["media_id"]:
                last_msg["encrypted_content"] = None

        # Mark as read
        group_messages_collection.update_many(
            {
                "group_id": ObjectId(group_id),
                "sender_id": {"$ne": ObjectId(user_id)},
                "read_by": {"$ne": ObjectId(user_id)}
            },
            {"$addToSet": {"read_by": ObjectId(user_id)}}
        )

        return JsonResponse({
            "messages": serialized_messages,
            "has_more": has_more,
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
        is_image = data.get('is_image', False)
        image_size = data.get('image_size')
        media_id = data.get('media_id')
        
        if not group_id:
            return JsonResponse({"error": "Missing group ID"}, status=400)
        
        # Require either plaintext, encrypted content, image, or media_id
        if not any([message_content, encrypted_content, is_image, media_id]):
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
            "group_id": ObjectId(group_id),
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
            "is_encrypted": encrypted_content is not None or media_id is not None,
            "is_image": is_image,
            "image_size": image_size,
            "media_id": media_id
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
            "is_encrypted": encrypted_content is not None or media_id is not None,
            "is_image": is_image,
            "image_size": image_size,
            "media_id": media_id
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
                'group_id': ObjectId(group_id)
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
