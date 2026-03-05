# consumers_group.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
import motor.motor_asyncio
from bson import ObjectId
from django.utils.timezone import now
from datetime import timedelta
import os
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env

from .views.common import async_users_collection as users_collection, async_groups_collection as groups_collection, async_group_messages_collection as group_messages_collection

class GroupChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            # Get string IDs from frontend
            self.user_id = self.scope['session'].get('user_id')  # String
            self.group_id = self.scope['url_route']['kwargs']['group_id']  # String
            
            if not self.user_id:
                await self.close(1000)  # Normal closure
                return

            print(f"🔗 WebSocket connection attempt - User: {self.user_id}, Group: {self.group_id}")

            # Convert to ObjectIds for database operations
            self.user_object_id = ObjectId(self.user_id)
            self.group_object_id = ObjectId(self.group_id)

            # Validate group membership and get user data
            user_data = await self.validate_group_membership_and_get_user()
            if not user_data:
                await self.close(1000)  # Normal closure
                return

            self.user_name = user_data['full_name']
            self.user_has_encryption = user_data.get('has_encryption', False)
            self.room_group_name = f'group_{self.group_id}'  # Keep group_id as string for room name

            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()

            print(f"✅ WebSocket connected successfully - User: {self.user_name}, Group: {self.group_id}")

            # Send join notification with encryption status
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "group_user_joined",
                    "user_id": self.user_id,  # Send string to frontend
                    "username": self.user_name,
                    "has_encryption": self.user_has_encryption,
                    "timestamp": now().isoformat()
                }
            )

        except Exception as e:
            print(f"❌ Connection error: {e}")
            await self.close(1000)  # Normal closure
            return

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            try:
                await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
            except Exception as e:
                print(f"Error discarding channel: {e}")

        if hasattr(self, 'user_object_id'):
            pass # Mark offline handled by GlobalConsumer

        if hasattr(self, 'room_group_name') and hasattr(self, 'user_id') and hasattr(self, 'user_name'):
            try:
                # Send leave notification
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "group_user_left",
                        "user_id": self.user_id,  # Send string to frontend
                        "username": self.user_name,
                        "timestamp": now().isoformat()
                    }
                )
            except Exception as e:
                print(f"Error sending leave notification: {e}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get("type")
            
            print(f"🔍 WebSocket message received: {message_type} from user {self.user_id}")

            # Map message types to handler methods
            handler_map = {
                "group_message": self.group_message_handler,
                "edit_group_message": self.edit_group_message_handler,
                "delete_group_message": self.delete_group_message_handler,
                "group_typing": self.group_typing_handler,
                "group_read_receipt": self.group_read_receipt_handler,
                "clear_group_chat": self.clear_group_chat_handler,
                "request_group_seed": self.request_group_seed_handler,
                "share_group_seed": self.share_group_seed_handler,
                "encryption_status": self.encryption_status_handler,
            }

            handler = handler_map.get(message_type)
            
            if handler:
                await handler(data)
            else:
                print(f"⚠️ Unknown message type: {message_type}")
                # Send error back to client instead of disconnecting
                await self.send(text_data=json.dumps({
                    "type": "error",
                    "message": f"Unknown message type: {message_type}"
                }))
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error: {e}")
            await self.send(text_data=json.dumps({
                "type": "error", 
                "message": "Invalid JSON format"
            }))
        except Exception as e:
            print(f"❌ General receive error: {e}")
            # DON'T disconnect on general errors
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": "Internal server error"
            }))

    async def validate_group_membership_and_get_user(self):
        """Check if user is a member of this group and get user data with encryption status"""
        try:
            # Get user data using ObjectId
            user = await users_collection.find_one({"_id": self.user_object_id})
            if not user:
                print(f"❌ User {self.user_id} not found in database")
                return None
            
            # Check group membership using ObjectIds
            group = await groups_collection.find_one({
                "_id": self.group_object_id,
                "members": self.user_object_id  # ObjectId comparison
            })
            
            if not group:
                print(f"❌ User {self.user_id} is not a member of group {self.group_id}")
                # Debug info
                debug_group = await groups_collection.find_one({"_id": self.group_object_id})
                if debug_group:
                    member_ids = [str(member) for member in debug_group.get('members', [])]
                    print(f"🔍 Group members: {member_ids}")
                    print(f"🔍 Looking for user: {self.user_id} (as ObjectId: {self.user_object_id})")
                return None
            
            print(f"✅ User {self.user_id} validated as member of group {self.group_id}")
            
            # Check if user has encryption setup
            has_encryption = 'encryption_keys' in user and user['encryption_keys'] is not None
            
            return {
                'full_name': user.get('full_name', 'Unknown User'),
                'email': user.get('email', ''),
                'has_encryption': has_encryption
            }
        except Exception as e:
            print(f"❌ Group membership validation error: {e}")
            return None

    async def validate_current_membership(self):
        """Revalidate if current user is still a group member"""
        try:
            group = await groups_collection.find_one({
                "_id": self.group_object_id,
                "members": self.user_object_id,
                "is_active": True
            })
            return group is not None
        except Exception as e:
            print(f"Membership validation error: {e}")
            return False

    async def validate_admin_permissions(self):
        """Revalidate if current user is still an admin"""
        try:
            group = await groups_collection.find_one({
                "_id": self.group_object_id,
                "admin_ids": self.user_object_id
            })
            return group is not None
        except Exception as e:
            print(f"Admin validation error: {e}")
            return False

    async def get_group_member_count(self):
        """Get current member count for the group"""
        try:
            group = await groups_collection.find_one({"_id": self.group_object_id})
            if group:
                return len(group.get('members', []))
            return 0
        except Exception as e:
            print(f"Error getting member count: {e}")
            return 0

    async def group_message_handler(self, data):
        """Handle group messages with encryption support and membership validation"""
        # REVALIDATE MEMBERSHIP FIRST
        if not await self.validate_current_membership():
            await self.send(text_data=json.dumps({
                "type": "error", 
                "message": "You are no longer a member of this group",
                "should_disconnect": True
            }))
            await self.close(1000)  # Normal closure
            return

        message_content = (data.get("message") or "").strip()
        encrypted_content = data.get("encrypted_content")
        iv = data.get("iv")
        temp_id = data.get("temp_id")
        is_image = data.get("is_image", False)
        image_size = data.get("image_size")
        media_id = data.get("media_id")

        # Require either plaintext, encrypted content, or image
        if not message_content and not encrypted_content and not is_image:
            return

        timestamp = now()

        # Check if group has encryption enabled using ObjectId
        group = await groups_collection.find_one({"_id": self.group_object_id})
        group_encryption_enabled = group.get('encryption_enabled', False) if group else False
        
        # Determine if this message is encrypted
        is_encrypted = encrypted_content is not None and group_encryption_enabled

        # Create group message document with ObjectIds
        message_doc = {
            "group_id": self.group_object_id,  # ObjectId
            "sender_id": self.user_object_id,  # ObjectId
            "sender_name": self.user_name,
            "message": message_content,
            "encrypted_content": encrypted_content,
            "iv": iv,
            "timestamp": timestamp,
            "message_type": "group",
            "is_image": is_image,
            "image_size": image_size,
            "media_id": media_id,
            "read_by": [self.user_object_id],  # ObjectId in array
            "is_encrypted": is_encrypted,
            "encryption_enabled": group_encryption_enabled
        }
        
        result = await group_messages_collection.insert_one(message_doc)
        message_id = str(result.inserted_id)  # Convert to string for frontend

        # Update group's last message using ObjectId
        last_message_content = message_content
        if is_encrypted and not message_content:
            last_message_content = "🔒 Encrypted message"
            
        await groups_collection.update_one(
            {"_id": self.group_object_id},
            {"$set": {
                "last_message": {
                    "sender_id": self.user_id,  # String for consistency
                    "sender_name": self.user_name,
                    "content": last_message_content,
                    "timestamp": timestamp,
                    "is_encrypted": is_encrypted
                },
                "last_activity": timestamp
            }}
        )

        # Prepare event for broadcasting (send strings to frontend)
        event = {
            "type": "group_message_broadcast",
            "message_id": message_id,
            "message": message_content,
            "encrypted_content": encrypted_content,
            "iv": iv,
            "sender_id": self.user_id,  # String
            "sender_name": self.user_name,
            "group_id": self.group_id,  # String
            "timestamp": timestamp.isoformat(),
            "temp_id": temp_id,
            "message_type": "group",
            "is_encrypted": is_encrypted,
            "is_image": is_image,
            "image_size": image_size,
            "media_id": media_id,
            "read_by_me": True,
            "encryption_enabled": group_encryption_enabled
        }

        await self.channel_layer.group_send(self.room_group_name, event)

    async def edit_group_message_handler(self, data):
        """Edit group message with encryption support and membership validation"""
        # REVALIDATE MEMBERSHIP FIRST
        if not await self.validate_current_membership():
            await self.send(text_data=json.dumps({
                "type": "error", 
                "message": "You are no longer a member of this group",
                "should_disconnect": True
            }))
            await self.close(1000)  # Normal closure
            return

        message_id = data.get("message_id")
        new_content = data.get("new_content", "").strip()
        encrypted_content = data.get("encrypted_content")
        iv = data.get("iv")
        
        if not message_id or (not new_content and not encrypted_content):
            return

        try:
            update_data = {
                "edited": True, 
                "edit_timestamp": now()
            }
            
            # Update both plaintext and encrypted content
            if new_content:
                update_data["message"] = new_content
            if encrypted_content:
                update_data["encrypted_content"] = encrypted_content
            if iv:
                update_data["iv"] = iv
            
            # Limit edit to 5 minutes
            five_minutes_ago = now() - timedelta(minutes=5)

            result = await group_messages_collection.update_one(
                {
                    "_id": ObjectId(message_id), 
                    "sender_id": self.user_object_id,  # ObjectId
                    "group_id": self.group_object_id,   # ObjectId
                    "timestamp": {"$gte": five_minutes_ago}
                },
                {"$set": update_data}
            )
            
            if result.modified_count == 0:
                print("Group message not found or not authorized to edit")
                return
                
        except Exception as e:
            print(f"Error editing group message: {e}")
            return

        await self.channel_layer.group_send(self.room_group_name, {
            "type": "group_message_edited",
            "message_id": message_id,
            "new_content": new_content,
            "encrypted_content": encrypted_content,
            "iv": iv,
            "group_id": self.group_id,  # String
            "timestamp": now().isoformat(),
            "editor_id": self.user_id,  # String
            "is_encrypted": encrypted_content is not None
        })

    async def delete_group_message_handler(self, data):
        """Delete group message with membership validation"""
        # REVALIDATE MEMBERSHIP FIRST
        if not await self.validate_current_membership():
            await self.send(text_data=json.dumps({
                "type": "error", 
                "message": "You are no longer a member of this group",
                "should_disconnect": True
            }))
            await self.close(1000)  # Normal closure
            return

        message_id = data.get("message_id")
        if not message_id:
            return

        try:
            # Handle temp IDs
            if isinstance(message_id, str) and message_id.startswith('temp_'):
                return
                
            result = await group_messages_collection.update_one(
                {
                    "_id": ObjectId(message_id), 
                    "sender_id": self.user_object_id,  # ObjectId
                    "group_id": self.group_object_id   # ObjectId
                },
                {"$set": {
                    "message": "This message was deleted", 
                    "encrypted_content": None,
                    "deleted": True,
                    "delete_timestamp": now()
                }}
            )
            
            if result.modified_count == 0:
                print(f"Group message {message_id} not found or not authorized")
                return
                
        except Exception as e:
            print(f"Error deleting group message: {e}")
            return

        await self.channel_layer.group_send(self.room_group_name, {
            "type": "group_message_deleted",
            "message_id": message_id,
            "group_id": self.group_id,  # String
            "deleter_id": self.user_id  # String
        })

    async def group_typing_handler(self, data):
        """Handle group typing indicators with membership validation"""
        try:
            # REVALIDATE MEMBERSHIP FIRST
            if not await self.validate_current_membership():
                return  # Silently ignore if user is no longer member
                
            is_typing = bool(data.get("is_typing", False))
            group_id = data.get("group_id", self.group_id)

            await self.channel_layer.group_send(self.room_group_name, {
                "type": "group_typing_indicator",
                "sender_id": self.user_id,
                "sender_name": self.user_name,
                "group_id": group_id,
                "is_typing": is_typing,
                "timestamp": now().isoformat()
            })
            
        except Exception as e:
            print(f"Typing handler error: {e}")

    async def group_read_receipt_handler(self, data):
        """Handle group message read receipts with membership validation"""
        # REVALIDATE MEMBERSHIP FIRST
        if not await self.validate_current_membership():
            await self.send(text_data=json.dumps({
                "type": "error", 
                "message": "You are no longer a member of this group",
                "should_disconnect": True
            }))
            await self.close(1000)  # Normal closure
            return

        message_ids = data.get("message_ids", [])
        if not message_ids:
            return

        # Update read status in database
        object_ids = []
        valid_message_ids = []
        
        for msg_id in message_ids:
            try:
                if isinstance(msg_id, str) and msg_id.startswith('temp_'):
                    continue
                object_ids.append(ObjectId(msg_id))
                valid_message_ids.append(msg_id)
            except Exception:
                continue

        if object_ids:
            # Use bulk write for better performance
            bulk_operations = []
            from pymongo import UpdateOne
            for msg_id in object_ids:
                bulk_operations.append(
                    UpdateOne(
                        {"_id": msg_id, "group_id": self.group_object_id},  # ObjectId
                        {"$addToSet": {"read_by": self.user_object_id}}  # ObjectId
                    )
                )
            
            if bulk_operations:
                await group_messages_collection.bulk_write(bulk_operations)

        await self.channel_layer.group_send(self.room_group_name, {
            "type": "group_read_receipt",
            "message_ids": valid_message_ids,
            "reader_id": self.user_id,  # String
            "group_id": self.group_id,  # String
            "timestamp": now().isoformat()
        })

    # async def clear_group_chat_handler(self, data):
    #     """Handle clear group chat - Admin only with permission validation"""
    #     try:
    #         # REVALIDATE ADMIN PERMISSIONS FIRST
    #         if not await self.validate_admin_permissions():
    #             await self.send(text_data=json.dumps({
    #                 "type": "error",
    #                 "message": "You are no longer an admin of this group"
    #             }))
    #             return  # JUST RETURN, DON'T DISCONNECT - USER IS STILL MEMBER

    #         group_id = data.get("group_id")
            
    #         print(f"🗑️ CLEAR GROUP CHAT WebSocket - Group: {group_id}, User: {self.user_id}")
            
    #         if not group_id:
    #             return

    #         # Verify user is admin of this group using ObjectIds (double check)
    #         group = groups_collection.find_one({
    #             "_id": ObjectId(group_id),
    #             "admin_ids": self.user_object_id  # ObjectId comparison
    #         })
            
    #         if not group:
    #             print(f"❌ User {self.user_id} is not admin of group {group_id}")
    #             return

    #         print(f"✅ User IS admin, clearing group chat...")
            
    #         # Clear all messages for this group
    #         result = group_messages_collection.delete_many({
    #             "group_id": group_id  # Keep as string if that's how it's stored
    #         })
            
    #         deleted_count = result.deleted_count
    #         print(f"✅ Cleared {deleted_count} messages from group {group_id}")

    #         # Update group's last message using ObjectId
    #         groups_collection.update_one(
    #             {"_id": ObjectId(group_id)},
    #             {"$set": {
    #                 "last_message": None,
    #                 "last_activity": now()
    #             }}
    #         )

    #         # Broadcast clear chat event to all group members
    #         await self.channel_layer.group_send(self.room_group_name, {
    #             "type": "group_chat_cleared",
    #             "group_id": group_id,  # String
    #             "cleared_by": self.user_id,  # String
    #             "cleared_by_name": self.user_name,
    #             "deleted_count": deleted_count,
    #             "timestamp": now().isoformat()
    #         })

    #     except Exception as e:
    #         print(f"❌ Error in clear_group_chat_handler: {e}")
    async def clear_group_chat_handler(self, data):
        """Handle clear group chat - Admin only with permission validation"""
        try:
            if not await self.validate_admin_permissions():
                await self.send(text_data=json.dumps({
                    "type": "error",
                    "message": "You are no longer an admin of this group"
                }))
                return

            group_id = data.get("group_id")
            if not group_id:
                return

            print(f"🗑️ CLEAR GROUP CHAT WebSocket - Group: {group_id}, User: {self.user_id}")

            # Convert to ObjectId for database operations only
            group_object_id = ObjectId(group_id)

            # Verify admin
            group = await groups_collection.find_one({
                "_id": group_object_id,  # Use ObjectId for DB
                "admin_ids": self.user_object_id
            })

            if not group:
                print(f"❌ User {self.user_id} is not admin of group {group_id}")
                await self.send(text_data=json.dumps({
                    "type": "error", 
                    "message": "You are not an admin of this group"
                }))
                return

            print(f"✅ User IS admin, clearing group chat...")

            # Delete all messages - use ObjectId for DB
            result = await group_messages_collection.delete_many({
                "group_id": group_object_id  # ObjectId for DB
            })
            deleted_count = result.deleted_count
            print(f"✅ Cleared {deleted_count} messages from group {group_id}")

            # Update last message - use ObjectId for DB
            await groups_collection.update_one(
                {"_id": group_object_id},  # ObjectId for DB
                {"$set": {
                    "last_message": None,
                    "last_activity": now()
                }}
            )

            # Notify everyone - use STRING for WebSocket
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "group_chat_cleared",
                    "group_id": group_id,  # Keep as string for frontend
                    "cleared_by": self.user_id,
                    "cleared_by_name": self.user_name,
                    "deleted_count": deleted_count,
                    "timestamp": now().isoformat()
                }
            )

            # Send success confirmation
            await self.send(text_data=json.dumps({
                "type": "clear_chat_success",
                "message": f"Cleared {deleted_count} messages",
                "deleted_count": deleted_count
            }))

        except Exception as e:
            print(f"❌ Error in clear_group_chat_handler: {e}")
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": "Failed to clear chat"
            }))

    async def request_group_seed_handler(self, data):
        """Handle requests for group encryption seed with membership validation"""
        try:
            # REVALIDATE MEMBERSHIP FIRST
            if not await self.validate_current_membership():
                await self.send(text_data=json.dumps({
                    "type": "error", 
                    "message": "You are no longer a member of this group",
                    "should_disconnect": True
                }))
                await self.close(1000)  # Normal closure
                return

            group_id = data.get("group_id")
            requester_id = self.user_id
            
            if not group_id:
                return

            print(f"🔐 GROUP SEED REQUEST - Group: {group_id}, Requester: {requester_id}")
            
            # Get group info using ObjectId
            group = await groups_collection.find_one({"_id": ObjectId(group_id)})
            if not group:
                return

            # Get admin IDs
            admin_ids = group.get('admin_ids', [])
            if not admin_ids and group.get('admin_id'):
                admin_ids = [group.get('admin_id')]

            # Find online admins with encryption
            online_admins = []
            async for admin_doc in users_collection.find({"_id": {"$in": admin_ids}}):
                if admin_doc and admin_doc.get('status') == 'online' and 'encryption_keys' in admin_doc:
                    online_admins.append({
                        'admin_id': str(admin_doc['_id']),  # Convert to string for WebSocket
                        'admin_name': admin_doc.get('full_name', 'Admin'),
                        'public_key': admin_doc['encryption_keys'].get('public_key')
                    })

            if online_admins:
                # Notify admins about the seed request
                for admin in online_admins:
                    await self.channel_layer.group_send(
                        f"user_{admin['admin_id']}",  # Send to admin's personal channel
                        {
                            "type": "group_seed_request",
                            "group_id": group_id,
                            "group_name": group.get('name', 'Group'),
                            "requester_id": requester_id,
                            "requester_name": self.user_name,
                            "admin_id": admin['admin_id'],
                            "timestamp": now().isoformat()
                        }
                    )

                # Notify requester that admins have been notified
                await self.send(text_data=json.dumps({
                    "type": "group_seed_request_sent",
                    "group_id": group_id,
                    "admin_count": len(online_admins),
                    "timestamp": now().isoformat()
                }))
            else:
                # No online admins with encryption
                await self.send(text_data=json.dumps({
                    "type": "group_seed_request_failed",
                    "group_id": group_id,
                    "reason": "No online admins with encryption available",
                    "timestamp": now().isoformat()
                }))

        except Exception as e:
            print(f"❌ Error in request_group_seed_handler: {e}")

    async def share_group_seed_handler(self, data):
        """Handle sharing encrypted group seed with members with admin validation"""
        try:
            # REVALIDATE ADMIN PERMISSIONS FIRST
            if not await self.validate_admin_permissions():
                await self.send(text_data=json.dumps({
                    "type": "error",
                    "message": "You are no longer an admin of this group"
                }))
                return  # JUST RETURN, DON'T DISCONNECT - USER IS STILL MEMBER

            group_id = data.get("group_id")
            encrypted_seed = data.get("encrypted_seed")
            member_id = data.get("member_id")
            
            if not all([group_id, encrypted_seed, member_id]):
                return

            print(f"🔐 SHARE GROUP SEED - Group: {group_id}, Member: {member_id}, Admin: {self.user_id}")
            
            # Verify admin permissions using ObjectIds (double check)
            group = await groups_collection.find_one({
                "_id": ObjectId(group_id),
                "admin_ids": self.user_object_id  # ObjectId comparison
            })
            
            if not group:
                print(f"❌ User {self.user_id} is not admin of group {group_id}")
                return
            
            # Verify target member is in group using ObjectIds
            member_in_group = await groups_collection.find_one({
                "_id": ObjectId(group_id),
                "members": ObjectId(member_id)  # ObjectId comparison
            })
            
            if not member_in_group:
                print(f"❌ Member {member_id} is not in group {group_id}")
                return

            # Send encrypted seed to the member
            await self.channel_layer.group_send(
                f"user_{member_id}",  # Send to member's personal channel
                {
                    "type": "group_seed_shared",
                    "group_id": group_id,
                    "group_name": group.get('name', 'Group'),
                    "encrypted_seed": encrypted_seed,
                    "shared_by": self.user_id,  # String
                    "shared_by_name": self.user_name,
                    "timestamp": now().isoformat()
                }
            )

            # Confirm to admin
            await self.send(text_data=json.dumps({
                "type": "group_seed_shared_confirmation",
                "group_id": group_id,
                "member_id": member_id,
                "timestamp": now().isoformat()
            }))

        except Exception as e:
            print(f"❌ Error in share_group_seed_handler: {e}")

    async def encryption_status_handler(self, data):
        """Handle encryption status updates with membership validation"""
        try:
            # REVALIDATE MEMBERSHIP FIRST
            if not await self.validate_current_membership():
                await self.send(text_data=json.dumps({
                    "type": "error", 
                    "message": "You are no longer a member of this group",
                    "should_disconnect": True
                }))
                await self.close(1000)  # Normal closure
                return

            group_id = data.get("group_id")
            status = data.get("status")  # 'enabled', 'disabled', 'error'
            message = data.get("message", "")
            
            if not group_id:
                return

            # Broadcast encryption status to all group members
            await self.channel_layer.group_send(self.room_group_name, {
                "type": "group_encryption_status",
                "group_id": group_id,  # String
                "status": status,
                "message": message,
                "updated_by": self.user_id,  # String
                "updated_by_name": self.user_name,
                "timestamp": now().isoformat()
            })

        except Exception as e:
            print(f"❌ Error in encryption_status_handler: {e}")

    # =============================================
    # EVENT HANDLERS - Send messages to WebSocket
    # =============================================

    async def group_message_broadcast(self, event):
        await self.send(text_data=json.dumps(event))

    async def group_message_edited(self, event):
        await self.send(text_data=json.dumps(event))

    async def group_message_deleted(self, event):
        await self.send(text_data=json.dumps(event))

    async def group_typing_indicator(self, event):
        """Handle and broadcast typing indicators to group"""
        await self.send(text_data=json.dumps({
            "type": "group_typing",
            "sender_id": event["sender_id"],
            "sender_name": event["sender_name"],
            "group_id": event["group_id"],
            "is_typing": event["is_typing"],
            "timestamp": event.get("timestamp", now().isoformat())
        }))

    async def group_read_receipt(self, event):
        await self.send(text_data=json.dumps(event))

    async def group_user_joined(self, event):
        await self.send(text_data=json.dumps(event))

    async def group_user_left(self, event):
        await self.send(text_data=json.dumps(event))

    async def group_chat_cleared(self, event):
        await self.send(text_data=json.dumps(event))

    async def group_seed_request(self, event):
        """Receive seed request (for admins)"""
        await self.send(text_data=json.dumps(event))

    async def group_seed_shared(self, event):
        """Receive shared group seed (for members)"""
        await self.send(text_data=json.dumps(event))

    async def group_encryption_status(self, event):
        """Receive encryption status updates"""
        await self.send(text_data=json.dumps(event))

    async def group_seed_request_sent(self, event):
        """Confirmation that seed request was sent"""
        await self.send(text_data=json.dumps(event))

    async def group_seed_request_failed(self, event):
        """Notification that seed request failed"""
        await self.send(text_data=json.dumps(event))

    async def group_seed_shared_confirmation(self, event):
        """Confirmation that seed was shared"""
        await self.send(text_data=json.dumps(event))

    async def group_members_updated(self, event):
        """Handle group membership update events with member count"""
        # Get current member count
        member_count = await self.get_group_member_count()
        
        # Add member count to the event
        event_with_count = dict(event)
        event_with_count['member_count'] = member_count
        
        await self.send(text_data=json.dumps(event_with_count))

    async def force_disconnect_user(self, event):
        """Force disconnect a specific user from group"""
        target_user_id = event.get("user_id")
        reason = event.get("reason")
        
        # Check if this message is for the current user
        if target_user_id == self.user_id:
            await self.send(text_data=json.dumps({
                "type": "force_disconnect",
                "reason": reason,
                "message": "You have been removed from this group"
            }))
            await self.close(1000)  # Normal closure

    async def error_handler(self, event):
        """Handle error messages"""
        await self.send(text_data=json.dumps(event))

    async def unhandled_message(self, event):
        """Handle unknown message types gracefully without disconnecting"""
        print(f"⚠️ Unhandled message type: {event.get('type')}")
        # Don't disconnect, just log and ignore

    async def group_member_left(self, event):
        """Broadcast when a member voluntarily leaves the group"""
        await self.send(text_data=json.dumps(event))

    async def group_admin_transferred(self, event):
        """Broadcast when admin rights are transferred (e.g. last admin left)"""
        await self.send(text_data=json.dumps(event))

    async def group_deleted(self, event):
        """Broadcast to all group members that the group was deleted"""
        await self.send(text_data=json.dumps(event))

    async def group_deleted_notification(self, event):
        """Personal notification for individual members that the group was deleted"""
        await self.send(text_data=json.dumps(event))

    async def group_user_removed(self, event):
        """Personal notification for a user who was removed from the group"""
        # Only forward to the targeted user
        target_user_id = event.get('user_id', '')
        if target_user_id == self.user_id:
            await self.send(text_data=json.dumps(event))
    # new
    async def group_admins_removed(self, event):
        """Handle bulk admin removal notifications"""
        try:
            # Get member count
            member_count = await self.get_group_member_count()
            
            # Check if current user lost admin
            if self.user_id in event.get('removed_member_ids', []):
                await self.send(text_data=json.dumps({
                    "type": "admin_status_updated",
                    "group_id": event['group_id'],
                    "is_admin": False,
                    "message": "You are no longer an admin"
                }))
            
            # Broadcast to all
            await self.send(text_data=json.dumps({
                "type": "group_admins_removed",
                "group_id": event['group_id'],
                "removed_member_ids": event.get('removed_member_ids', []),
                "member_count": member_count,
                "timestamp": event.get('timestamp', now().isoformat())
            }))
        except Exception as e:
            print(f"Error in group_admins_removed: {e}")