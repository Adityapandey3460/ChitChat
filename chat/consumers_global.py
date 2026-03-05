import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils.timezone import now
from bson import ObjectId
from .views.common import async_users_collection as users_collection

class GlobalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Authenticate via session
        self.user_id = self.scope["session"].get("user_id")
        
        if not self.user_id:
            await self.close(code=4001)
            return

        self.global_broadcast_group = "global_broadcast"
        self.personal_group = f"user_{self.user_id}"

        # Join the global broadcast group (for events like new user registration)
        await self.channel_layer.group_add(
            self.global_broadcast_group,
            self.channel_name
        )

        # Join the personal group (for events like being added to a new group)
        await self.channel_layer.group_add(
            self.personal_group,
            self.channel_name
        )

        # Mark user as online in database
        await users_collection.update_one(
            {"_id": ObjectId(self.user_id)},
            {"$set": {"status": "online", "last_seen": now()}}
        )

        # Broadcast status update globally
        await self.channel_layer.group_send(
            self.global_broadcast_group,
            {
                "type": "user_status_update",
                "user_id": self.user_id,
                "status": "online",
                "timestamp": now().isoformat()
            }
        )

        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'user_id') and self.user_id:
            # Leave the global broadcast group
            await self.channel_layer.group_discard(
                self.global_broadcast_group,
                self.channel_name
            )

            # Leave the personal group
            await self.channel_layer.group_discard(
                self.personal_group,
                self.channel_name
            )

            # Mark user as offline in database
            await users_collection.update_one(
                {"_id": ObjectId(self.user_id)},
                {"$set": {"status": "offline", "last_seen": now()}}
            )

            # Broadcast status update globally
            await self.channel_layer.group_send(
                self.global_broadcast_group,
                {
                    "type": "user_status_update",
                    "user_id": self.user_id,
                    "status": "offline",
                    "last_seen": now().isoformat()
                }
            )

    async def receive(self, text_data):
        # The global socket is generally read-only for the client,
        # but you can handle incoming pings or other global events here if needed.
        pass

    # --- Handlers for events sent via channel_layer.group_send ---

    async def global_new_user(self, event):
        """Broadcast when a new user registers on the platform."""
        await self.send(text_data=json.dumps({
            'type': 'global_new_user',
            'user_id': event.get('user_id'),
            'username': event.get('username')
        }))

    async def global_new_group(self, event):
        """Broadcast when a user is added to a brand new group."""
        await self.send(text_data=json.dumps({
            'type': 'global_new_group',
            'group_id': event.get('group_id'),
            'group_name': event.get('group_name')
        }))

    async def user_status_update(self, event):
        """Broadcast user status change to the client."""
        await self.send(text_data=json.dumps(event))
