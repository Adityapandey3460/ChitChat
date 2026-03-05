from django.http import JsonResponse
from django.utils import timezone
from bson import ObjectId
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# Import DB collections
from .common import users_collection, groups_collection, group_seeds_collection

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
        
        # Pagination parameters
        try:
            offset = int(data.get('offset', 0))
            limit = int(data.get('limit', 50))
        except (ValueError, TypeError):
            offset = 0
            limit = 50

        # Get all group members with their user details - Optimized to exclude base64 in list
        members_data = []
        member_ids = group.get('members', [])
        
        print(f"🔧 Fetching details for {len(member_ids)} members (Paginated)...")
        
        # Sort member IDs for consistent pagination if needed, or just slice the IDs first
        # For simplicity and to maintain "Admins first" logic, we might need to fetch all
        # unless groups are massive (>1000 members).
        
        for member_id in member_ids:
            try:
                user = users_collection.find_one({"_id": member_id}, {'full_name': 1, 'status': 1, 'last_seen': 1, 'email': 1})
                if user:
                    is_admin = member_id in admin_ids
                    is_online = user.get('status') == 'online'
                    
                    member_data = {
                        'id': str(member_id),
                        'full_name': user.get('full_name', 'User'),
                        'avatar_base64': None, # Excluded
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
                
            except Exception as e:
                print(f"❌ Error processing member {member_id}: {str(e)}")
                continue
        
        # Sort members: admins first, then online users, then by name
        members_data.sort(key=lambda x: (
            not x['is_admin'],  # Admins first (True > False)
            not x['is_online'], # Online users next
            x['full_name'].lower()  # Then alphabetically
        ))
        
        # Slice for pagination
        paginated_members = members_data[offset : offset + limit]
        has_more = (offset + limit) < len(members_data)
        
        print(f"✅ Successfully fetched {len(paginated_members)} members (has_more: {has_more})")
        
        response_data = {
            'success': True,
            'members': paginated_members,
            'has_more': has_more,
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
            # Notify all group members via WebSocket
            try:
                channel_layer = get_channel_layer()
                group_channel_name = f"group_{group_id}"

                async_to_sync(channel_layer.group_send)(
                    group_channel_name,
                    {
                        'type': 'group_members_updated',
                        'group_id': group_id,
                        'action': 'admin_added',
                        'new_admin_id': new_admin_id,
                        'new_admin_name': promoted_member_info['full_name'],
                        'promoted_by': user_id,
                        'promoted_by_name': request.session.get('full_name', 'Admin'),
                        'timestamp': timezone.now().isoformat()
                    }
                )
                print(f"✅ WebSocket notification sent for admin promotion of {new_admin_id}")
            except Exception as ws_error:
                print(f"⚠️ WebSocket error for admin promotion: {ws_error}")

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
        
        # Pagination parameters
        try:
            offset = int(data.get('offset', 0))
            limit = int(data.get('limit', 50))
        except (ValueError, TypeError):
            offset = 0
            limit = 50

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
            query = {
                "_id": {"$ne": user_object_id, "$nin": list(group_member_ids)}
            }
        else:
            # For new group creation - get all contacts except current user
            query = {
                "_id": {"$ne": user_object_id}
            }
        
        all_available = list(users_collection.find(
            query,
            {'full_name': 1, 'email': 1}
        ))
        
        serialized_contacts = []
        for contact in all_available:
            serialized_contacts.append({
                'id': str(contact['_id']),
                'full_name': contact.get('full_name', 'User'),
                'avatar_base64': None, # Excluded
                'email': contact.get('email', '')
            })
        
        # Sort alphabetically
        serialized_contacts.sort(key=lambda x: x['full_name'].lower())

        # Slice for pagination
        paginated_contacts = serialized_contacts[offset : offset + limit]
        has_more = (offset + limit) < len(serialized_contacts)

        return JsonResponse({
            'success': True,
            'available_contacts': paginated_contacts,
            'has_more': has_more,
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
