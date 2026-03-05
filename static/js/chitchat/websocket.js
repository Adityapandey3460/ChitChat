// ====================================================
// WEBSOCKET AND MESSAGE HANDLING (71-90)
// ====================================================
// 71) Connect WebSocket - UPDATED VERSION
function connectWebSocket() {
    if (chatSocket && chatSocket.readyState === WebSocket.OPEN) {
        return; // Already connected
    }

    let wsUrl = null;
    if (currentFriend) {
        const roomName = [userId, currentFriend.id].sort().join('_');
        wsUrl = `/ws/chat/${roomName}/`;
    } else if (currentGroup) {
        wsUrl = `/ws/group/${currentGroup.id}/`;
    } else return;

    const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';

    try {
        chatSocket = new WebSocket(`${wsScheme}://${window.location.host}${wsUrl}`);

        chatSocket.onopen = () => {
            console.log('WebSocket connected successfully');
            // Reset any error states
            if (currentGroup) {
                updateGroupAdminStatus(currentGroup.isAdmin || false);
            }
        };

        chatSocket.onclose = (e) => {
            console.log('WebSocket disconnected:', e.code, e.reason);
            cleanupReadReceipts();

            // Only attempt reconnect if it wasn't a forced disconnect
            if (e.code !== 1000 && currentGroup) { // 1000 = normal closure
                setTimeout(() => {
                    console.log('Attempting to reconnect WebSocket...');
                    connectWebSocket();
                }, 3000);
            }
        };

        chatSocket.onerror = (err) => {
            console.error('WebSocket error:', err);
            // Don't automatically reconnect on error - let onclose handle it
        };

        chatSocket.onmessage = async (e) => {
            try {
                const data = JSON.parse(e.data);
                switch (data.type) {
                    case 'individual_message': await handleIndividualMessage(data); break;
                    case 'group_message_broadcast': await handleGroupMessage(data); break;
                    case 'individual_message_edited':
                    case 'group_message_edited': await handleMessageEdited(data); break;
                    case 'individual_message_deleted':
                    case 'group_message_deleted': handleMessageDeleted(data); break;
                    case 'individual_chat_cleared':
                    case 'group_chat_cleared': handleChatCleared(data); break;
                    case 'individual_typing_indicator':
                    case 'group_typing_indicator': handleTypingIndicator(data); break;
                    case 'individual_read_receipt':
                    case 'group_read_receipt': handleReadReceipt(data); break;
                    case 'group_user_joined': handleGroupUserJoined(data); break;
                    case 'group_user_left': handleGroupUserLeft(data); break;
                    case 'group_admins_removed': handleGroupAdminsRemoved(data); break;
                    case 'user_status_update': handleUserStatusUpdate(data); break;

                    // ── Group management live updates ──────────────────
                    case 'group_members_updated': handleGroupMembersUpdated(data); break;
                    case 'group_member_left': handleGroupMemberLeft(data); break;
                    case 'group_admin_transferred': handleGroupAdminTransferred(data); break;
                    case 'group_deleted': handleGroupDeleted(data); break;
                    case 'group_deleted_notification': handleGroupDeleted(data); break;
                    case 'group_user_removed': handleGroupUserRemoved(data); break;

                    case 'error': handleWebSocketError(data); break;
                    case 'force_disconnect': handleForceDisconnect(data); break;

                    default: console.log('Unknown WebSocket message type:', data.type);
                }
            } catch (error) {
                console.error('Error processing WebSocket message:', error);
            }
        };
    } catch (error) {
        console.error('Error creating WebSocket:', error);
    }
}

// 72) Connect Global WebSocket
function connectGlobalWebSocket() {
    if (globalSocket && globalSocket.readyState === WebSocket.OPEN) {
        return; // Already connected
    }

    const wsUrl = '/ws/global/';
    const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';

    try {
        globalSocket = new WebSocket(`${wsScheme}://${window.location.host}${wsUrl}`);

        globalSocket.onopen = () => {
            console.log('Global WebSocket connected successfully');
        };

        globalSocket.onclose = (e) => {
            console.log('Global WebSocket disconnected:', e.code, e.reason);
            // Attempt reconnect if it wasn't a forced disconnect
            if (e.code !== 1000) {
                setTimeout(() => {
                    console.log('Attempting to reconnect Global WebSocket...');
                    connectGlobalWebSocket();
                }, 5000);
            }
        };

        globalSocket.onerror = (err) => {
            console.error('Global WebSocket error:', err);
        };

        globalSocket.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data.type === 'global_new_user') {
                    console.log(`Global Event: New user registered -> ${data.username}`);
                    // Force refresh universally
                    loadContacts();
                } else if (data.type === 'global_new_group') {
                    console.log(`Global Event: You were added to new group -> ${data.group_name}`);
                    // Force refresh universally
                    loadGroups();
                } else if (data.type === 'user_status_update') {
                    handleUserStatusUpdate(data);
                }
            } catch (error) {
                console.error('Error processing Global WebSocket message:', error);
            }
        };
    } catch (error) {
        console.error('Error creating Global WebSocket:', error);
    }
}

// Add handler:
function handleGroupAdminsRemoved(data) {
    if (data.member_count && currentGroup) {
        currentGroup.memberCount = data.member_count;
        updateChatHeader(currentGroup.name, `Group • ${currentGroup.memberCount} members`);
    }
    if (data.removed_member_ids.includes(userId)) {
        showSystemMessage('You are no longer an admin');
        updateGroupAdminStatus(false);
    }
}

async function sendMessageViaHTTP(message, receiver_id, timestamp, tempMessageId, messageType, encryptedData, isImage = false) {
    try {
        const endpoint = messageType === 'group_message' ? '/groups/send_message/' : '/chat/send_message/';

        const payload = {
            message: isImage ? "[Image]" : message,
            encrypted_content: encryptedData.ciphertext,
            iv: encryptedData.iv,
            receiver_id: receiver_id,
            timestamp: timestamp.toISOString(),
            temp_id: tempMessageId,
            is_image: isImage
        };

        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Failed to send message via HTTP');
        }

        const data = await response.json();
        console.log('Message sent via HTTP:', data);
        return data;
    } catch (error) {
        console.error('Error sending message via HTTP:', error);
        throw error;
    }
}

// 72) Handle Individual Message
async function handleIndividualMessage(data) {
    if (data.sender_id !== userId) {
        try {
            const isImage = data.is_image || false;
            let content;

            if (isImage) {
                // Cache metadata for lazy decrypt
                encryptedImageCache.set(data.message_id, {
                    ciphertext: data.encrypted_content,
                    iv: data.iv,
                    sender_id: data.sender_id,
                    receiver_id: data.receiver_id,
                    media_id: data.media_id,
                    image_size: data.image_size,
                    is_group: false
                });
                content = ""; // Content will be loaded on demand
            } else {
                content = await decryptMessageFromContact({ ciphertext: data.encrypted_content, iv: data.iv }, data.sender_id);
            }

            const timeStr = formatTime(data.timestamp);
            addMessageToChat(content, false, timeStr, data.sender_id, data.message_id, false, false, data.read || false, null, data.timestamp, isImage, data.image_size);
            updateContactLastMessage(data.sender_id, isImage ? "📷 Image" : content, false, data.timestamp);
            playNotificationSound();
        } catch (error) {
            console.error('Error decrypting individual message:', error);
            addMessageToChat('🔒 Unable to decrypt message', false, formatTime(data.timestamp), data.sender_id, data.message_id, false, false, false);
        }
    } else if (data.temp_id) {
        tempToRealIdMap.set(data.temp_id, data.message_id);
        processPendingOperations(data.temp_id, data.message_id);
        updateTempMessageId(data.temp_id, data.message_id);
        if (data.read !== undefined) updateMessageStatus(data.message_id, data.read);
    }
}

// 73) Handle Group Message
async function handleGroupMessage(data) {
    const isSent = data.sender_id === userId;

    if (!isSent) {
        try {
            const isImage = data.is_image || false;
            let content;

            if (isImage) {
                // Cache metadata for lazy decrypt
                encryptedImageCache.set(data.message_id, {
                    ciphertext: data.encrypted_content,
                    iv: data.iv,
                    sender_id: data.sender_id,
                    group_id: data.group_id,
                    media_id: data.media_id,
                    image_size: data.image_size,
                    is_group: true
                });
                content = "";
            } else {
                const decryptedContent = await decryptMessageFromGroup({ ciphertext: data.encrypted_content, iv: data.iv }, data.group_id);
                content = decryptedContent;
            }

            const timeStr = formatTime(data.timestamp);
            addMessageToChat(content, false, timeStr, data.sender_id, data.message_id, false, false, false, data.sender_name, data.timestamp, isImage, data.image_size);
            updateGroupLastMessage(data.group_id, isImage ? "📷 Image" : content, data.sender_name, data.timestamp);
            playNotificationSound();
        } catch (error) {
            console.error('Error decrypting group message:', error);
            addMessageToChat('🔒 Unable to decrypt message', false, formatTime(data.timestamp), data.sender_id, data.message_id, false, false, false, data.sender_name);
        }
    } else if (data.temp_id) {
        tempToRealIdMap.set(data.temp_id, data.message_id);
        processPendingOperations(data.temp_id, data.message_id);
        updateTempMessageId(data.temp_id, data.message_id);
    }
}

// 74) Handle Message Edited
async function handleMessageEdited(data) {
    if (data.editor_id !== userId) {
        try {
            let decryptedContent;
            if (data.group_id) {
                decryptedContent = await decryptMessageFromGroup({ ciphertext: data.encrypted_content, iv: data.iv }, data.group_id);
            } else {
                decryptedContent = await decryptMessageFromContact({ ciphertext: data.encrypted_content, iv: data.iv }, data.editor_id);
            }
            updateMessageInUI(data.message_id, decryptedContent, data.timestamp);
        } catch (error) {
            console.error('Error decrypting edited message:', error);
            updateMessageInUI(data.message_id, '🔒 Unable to decrypt message', data.timestamp);
        }
    }
}

// 75) Handle Message Deleted
function handleMessageDeleted(data) {
    if (data.deleter_id !== userId) deleteMessageFromUI(data.message_id);
}

// 76) Handle Chat Cleared
function handleChatCleared(data) {
    if (data.cleared_by !== userId) loadMessages();
}

// 77) Handle Typing Indicator
function handleTypingIndicator(data) {
    if (currentFriend && data.sender_id === currentFriend.id) {
        if (data.is_typing) {
            chatStatus.textContent = data.sender_id === userId ? 'typing...' : 'typing...';
            // Note: we can use sender_name for group but for individual 'typing...' is standard
        } else {
            // Restore actual status
            const statusText = currentFriend.isOnline ? 'Online' : `Last seen ${formatLastSeen(currentFriend.lastSeen)}`;
            updateChatHeader(currentFriend.name, statusText);
        }
    } else if (currentGroup) {
        if (data.is_typing && data.sender_id !== userId) {
            chatStatus.textContent = `${data.sender_name} is typing...`;
        } else {
            chatStatus.textContent = `Group • ${currentGroup.memberCount} members`;
        }
    }
}

// 77.1) Handle User Status Update
function handleUserStatusUpdate(data) {
    if (currentFriend && data.user_id === currentFriend.id) {
        // IMPORTANT: Only update if the status is actually different or if this is an offline with new last_seen
        currentFriend.isOnline = (data.status === 'online');
        if (data.status === 'offline' && data.last_seen) {
            currentFriend.lastSeen = data.last_seen;
        }

        // Update Sidebar list status marker if it exists
        const contactItem = document.querySelector(`.contact-item[data-user-id="${data.user_id}"]`);
        if (contactItem) {
            const statusFull = contactItem.querySelector('.status-full');
            if (statusFull) {
                statusFull.textContent = currentFriend.isOnline ? 'online' : 'offline';
                statusFull.className = `status-full ${currentFriend.isOnline ? 'online' : 'offline'}`;
            }
        }

        // Only update Header if not currently showing typing indicator
        if (!chatStatus.textContent.includes('typing...')) {
            const statusText = currentFriend.isOnline ? 'Online' : `Last seen ${formatLastSeen(currentFriend.lastSeen)}`;
            updateChatHeader(currentFriend.name, statusText);
        }
    }
}

// 78) Handle Read Receipt
function handleReadReceipt(data) {
    if (data.message_ids && Array.isArray(data.message_ids)) {
        data.message_ids.forEach(messageId => updateMessageStatus(messageId, true));
    }
}

// 79) Handle Group User Joined
function handleGroupUserJoined(data) {
    if (currentGroup && currentGroup.id === data.group_id) {
        showSystemMessage(`${data.user_name} joined the group`);
        currentGroup.memberCount++;
        updateChatHeader(currentGroup.name, `Group • ${currentGroup.memberCount} members`);
    }
}

// 80) Handle Group User Left
function handleGroupUserLeft(data) {
    if (currentGroup && currentGroup.id === data.group_id) {
        showSystemMessage(`${data.user_name} left the group`);
        currentGroup.memberCount--;
        updateChatHeader(currentGroup.name, `Group • ${currentGroup.memberCount} members`);
    }
}


// 81) Handle WebSocket Error
function handleWebSocketError(data) {
    console.log('WebSocket error:', data.message);

    // Show user-friendly error message
    if (data.message.includes('no longer a member')) {
        showSystemMessage('You have been removed from this group');
        // Optionally redirect to groups list after a delay
        setTimeout(() => {
            if (currentGroup && currentGroup.id === data.group_id) {
                loadGroups(); // Go back to groups list
                currentGroup = null;
                updateChatUI();
            }
        }, 3000);
    } else if (data.message.includes('no longer an admin')) {
        showSystemMessage('You are no longer an admin of this group');
        // Update UI to remove admin privileges but stay in chat
        updateGroupAdminStatus(false);
    }

    // Only disconnect if explicitly told to
    if (data.should_disconnect && chatSocket) {
        chatSocket.close();
    }
}

// 82) Handle Force Disconnect
function handleForceDisconnect(data) {
    console.log('Force disconnect:', data.reason, data.message);
    showSystemMessage(data.message);

    // Redirect to groups list after a delay
    setTimeout(() => {
        if (currentGroup) {
            loadGroups();
            currentGroup = null;
            updateChatUI();
        }
    }, 2000);

    if (chatSocket) {
        chatSocket.close();
    }
}

// 83) Handle Group Members Updated  ─────────────────────────────────────────
// Handles both `action: 'removed'` (member/admin kicked out)
// and `action: 'admin_added'` (someone was promoted).
function handleGroupMembersUpdated(data) {
    if (!currentGroup || currentGroup.id !== data.group_id) return;

    if (data.action === 'removed') {
        const removedIds = (data.removed_members || []).map(m => m.id);
        const removedNames = (data.removed_members || []).map(m => m.full_name);

        if (removedIds.includes(userId)) {
            // ── The current user was removed ──────────────────────────────
            showSystemMessage('You have been removed from this group');
            setTimeout(() => {
                removeGroupFromSidebar(data.group_id);
                if (currentGroup && currentGroup.id === data.group_id) {
                    currentGroup = null;
                    resetChatView();
                    if (chatSocket) { chatSocket.close(); chatSocket = null; }
                }
            }, 2500);
        } else {
            // ── Another member was removed ────────────────────────────────
            const nameStr = removedNames.length ? removedNames.join(', ') : 'A member';
            showSystemMessage(`${nameStr} was removed from the group`);
            const newCount = data.total_members;
            if (newCount !== undefined) {
                currentGroup.memberCount = newCount;
                updateChatHeader(currentGroup.name, `Group • ${currentGroup.memberCount} members`);
                updateGroupMemberCountInSidebar(data.group_id, newCount);
            } else {
                currentGroup.memberCount = Math.max(0, currentGroup.memberCount - removedIds.length);
                updateChatHeader(currentGroup.name, `Group • ${currentGroup.memberCount} members`);
            }
        }
    } else if (data.action === 'admin_added') {
        // ── Admin promoted ────────────────────────────────────────────────
        if (data.new_admin_id === userId) {
            showSystemMessage('You are now an admin of this group');
            updateGroupAdminStatus(true);
        } else {
            showSystemMessage(`${data.new_admin_name || 'A member'} is now a group admin`);
        }
    }
}

// 84) Update Group Admin Status  ──────────────────────────────────────────────
function updateGroupAdminStatus(isAdmin) {
    if (currentGroup) {
        currentGroup.isAdmin = isAdmin;
        // Show/hide admin-only menu options
        const adminOnlyEls = document.querySelectorAll('.admin-only');
        adminOnlyEls.forEach(el => {
            el.style.display = isAdmin ? '' : 'none';
        });
        console.log(`Admin status updated: ${isAdmin ? 'Admin' : 'Member'}`);
    }
}

// 85) Show System Message  ─────────────────────────────────────────────────────
function showSystemMessage(message) {
    const chatBoxEl = document.getElementById('chatBox');
    if (chatBoxEl) {
        const systemMessage = document.createElement('div');
        systemMessage.className = 'system-message';
        systemMessage.textContent = message;
        systemMessage.style.cssText = 'text-align:center;color:#888;font-size:13px;font-style:italic;margin:10px 0;padding:5px 12px;';
        chatBoxEl.appendChild(systemMessage);
        chatBoxEl.scrollTop = chatBoxEl.scrollHeight;
    }
    console.log('System:', message);
}

// 86) Handle Group Member Left  ────────────────────────────────────────────────
// Fired when another member (not the current user) voluntarily leaves.
function handleGroupMemberLeft(data) {
    if (!currentGroup || currentGroup.id !== data.group_id) return;
    if (data.member_id === userId) return; // leaver handles their own UI

    showSystemMessage(`${data.member_name || 'A member'} left the group`);

    const newCount = data.total_members;
    if (newCount !== undefined) {
        currentGroup.memberCount = newCount;
    } else {
        currentGroup.memberCount = Math.max(0, currentGroup.memberCount - 1);
    }
    updateChatHeader(currentGroup.name, `Group • ${currentGroup.memberCount} members`);
    updateGroupMemberCountInSidebar(data.group_id, currentGroup.memberCount);

    // If admin was auto-transferred because leaver was last admin
    if (data.new_admin_assigned) {
        if (data.new_admin_assigned === userId) {
            updateGroupAdminStatus(true);
            showSystemMessage('You are now the group admin');
        }
    }
}

// 87) Handle Group Admin Transferred  ─────────────────────────────────────────
function handleGroupAdminTransferred(data) {
    if (!currentGroup || currentGroup.id !== data.group_id) return;

    const msg = `${data.old_admin_name || 'Admin'} left. ${data.new_admin_name || 'A member'} is now the group admin.`;
    showSystemMessage(msg);

    if (data.new_admin_id === userId) updateGroupAdminStatus(true);
    if (data.old_admin_id === userId) updateGroupAdminStatus(false);
}

// 88) Handle Group Deleted  ────────────────────────────────────────────────────
function handleGroupDeleted(data) {
    const isCurrentGroup = currentGroup && currentGroup.id === data.group_id;
    if (isCurrentGroup) {
        showSystemMessage(`Group "${data.group_name}" has been deleted`);
    }
    setTimeout(() => {
        removeGroupFromSidebar(data.group_id);
        if (isCurrentGroup) {
            currentGroup = null;
            resetChatView();
            if (chatSocket) { chatSocket.close(); chatSocket = null; }
        }
    }, 2000);
}

// 89) Handle Group User Removed (personal channel notification)  ───────────────
function handleGroupUserRemoved(data) {
    const isCurrentGroup = currentGroup && currentGroup.id === data.group_id;
    if (isCurrentGroup) {
        showSystemMessage(`You were removed from "${data.group_name || 'this group'}"`);
        setTimeout(() => {
            removeGroupFromSidebar(data.group_id);
            currentGroup = null;
            resetChatView();
            if (chatSocket) { chatSocket.close(); chatSocket = null; }
        }, 2500);
    } else {
        removeGroupFromSidebar(data.group_id);
    }
}

// ── Sidebar helpers  ──────────────────────────────────────────────────────────

/** Remove a group list item from the sidebar. */
function removeGroupFromSidebar(groupId) {
    const el = document.querySelector(`[data-group-id="${groupId}"]`);
    if (el) el.remove();
}

/** Update the displayed member count in the sidebar group list item. */
function updateGroupMemberCountInSidebar(groupId, count) {
    const el = document.querySelector(`[data-group-id="${groupId}"] .group-members`);
    if (el) el.textContent = `${count} member${count !== 1 ? 's' : ''}`;
}
