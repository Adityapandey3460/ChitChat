from django.http import JsonResponse
from django.utils import timezone
from bson import ObjectId
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json

# Import DB collections
from .common import groups_collection, group_seeds_collection

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
                    
        # Broadcast global_new_group to every member's personal global channel
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            
            all_members_str = [str(m) for m in group_data["members"]]
            for m_id in all_members_str:
                async_to_sync(channel_layer.group_send)(
                    f"user_{m_id}",
                    {
                        "type": "global_new_group",
                        "group_id": group_id,
                        "group_name": group_name
                    }
                )
        except Exception as e:
            print(f"Failed to broadcast global_new_group to members: {e}")
        
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
        
        # Broadcast global_new_group to every NEW member's personal global channel
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            
            group_name = updated_group.get('name', 'Unnamed Group')
            
            for m_id in new_members:
                async_to_sync(channel_layer.group_send)(
                    f"user_{m_id}",
                    {
                        "type": "global_new_group",
                        "group_id": group_id,
                        "group_name": group_name
                    }
                )
            print(f"✅ Broadcasted global_new_group to {len(new_members)} new members")
        except Exception as e:
            print(f"Failed to broadcast global_new_group to new members: {e}")

        print(f"🎉 SUCCESS: {response_data}")
        return JsonResponse(response_data)
        
    except Exception as e:
        print(f"❌ Error in add_members_with_encryption: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": "Internal server error"}, status=500)
