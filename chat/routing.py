# routing.py
from django.urls import re_path
from . import consumers_individual
from . import consumers_group

websocket_urlpatterns = [
    # Individual chat routes
    re_path(r'ws/chat/(?P<room_name>[^/]+)/$', 
            consumers_individual.IndividualChatConsumer.as_asgi()),
    
    # Group chat routes
    re_path(r'ws/group/(?P<group_id>[^/]+)/$',
            consumers_group.GroupChatConsumer.as_asgi()),
]