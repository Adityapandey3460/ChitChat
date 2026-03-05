// ====================================================
// MESSAGE SENDING AND MANAGEMENT (81-110)
// ====================================================

// 81) Send Message
async function sendMessage(imageBuffer = null, isImage = false, imageSize = null) {
    const message = isImage ? "" : messageInput.value.trim();
    if (!isImage && !message) return;
    if (!currentFriend && !currentGroup) return;

    let receiverId, messageType;
    if (currentFriend) {
        receiverId = currentFriend.id;
        messageType = 'chat_message';
    } else if (currentGroup) {
        receiverId = currentGroup.id;
        messageType = 'group_message';
    } else return;

    const timestamp = new Date();
    const timeStr = formatTime(timestamp);
    const tempMessageId = 'temp_' + Date.now();

    pendingMessageOperations.set(tempMessageId, {
        type: 'send',
        message: isImage ? "[Image]" : message,
        timestamp: timestamp,
        receiver_id: receiverId,
        message_type: currentGroup ? 'group' : 'individual'
    });

    const senderName = currentGroup ? userName : null;
    const displayContent = isImage ? arrayBufferToBase64(imageBuffer) : message;
    addMessageToChat(displayContent, true, timeStr, userId, tempMessageId, false, false, false, senderName, timestamp, isImage, imageSize);

    if (currentFriend) updateContactLastMessage(currentFriend.id, isImage ? "📷 Image" : message, true, timestamp);
    else if (currentGroup) updateGroupLastMessage(currentGroup.id, isImage ? "📷 Image" : message, 'You', timestamp);

    try {
        let encryptedData;
        let mediaId = null;

        if (currentFriend) {
            if (isImage) {
                encryptedData = await encryptFile(imageBuffer, await getOrCreateRoomKey(currentFriend.id));
                // 📤 Pre-upload encrypted blob to server
                mediaId = await uploadEncryptedMedia(encryptedData.ciphertext);
            } else {
                encryptedData = await encryptMessageForContact(message, currentFriend.id);
            }
        } else if (currentGroup) {
            if (isImage) {
                encryptedData = await encryptFile(imageBuffer, await getOrCreateGroupKey(currentGroup.id));
                // 📤 Pre-upload encrypted blob to server
                mediaId = await uploadEncryptedMedia(encryptedData.ciphertext);
            } else {
                encryptedData = await encryptMessageForGroup(message, currentGroup.id);
            }
        }

        const messageData = {
            type: messageType,
            encrypted_content: isImage ? null : encryptedData.ciphertext, // Omit ciphertext for images
            iv: encryptedData.iv,
            receiver_id: receiverId,
            timestamp: timestamp.toISOString(),
            temp_id: tempMessageId,
            read: false,
            is_image: isImage,
            image_size: imageSize,
            media_id: mediaId
        };

        if (currentGroup) {
            messageData.group_id = receiverId;
            messageData.sender_name = userName;
        }

        const success = safeWebSocketSend(messageData);
        if (!success) {
            // Updated sendMessageViaHTTP to handle isImage
            sendMessageViaHTTP(message, receiverId, timestamp, tempMessageId, messageType, encryptedData, isImage);
        }
    } catch (error) {
        console.error('Error encrypting/sending message:', error);
        showError('Failed to encrypt message. Please try again.');
        return;
    }

    if (!isImage) {
        messageInput.value = "";
        resetInputHeight();
    }
    setTimeout(() => chatBox.scrollTop = chatBox.scrollHeight, 50);
}

// 81.1) Handle Image Upload
async function handleImageUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    if (!file.type.startsWith('image/')) {
        showError('Please select an image file.');
        return;
    }

    try {
        // Show a "Compressing..." indicator if needed
        const compressedBuffer = await compressImage(file);
        const imageSize = compressedBuffer.byteLength;
        await sendMessage(compressedBuffer, true, imageSize);
    } catch (error) {
        console.error('Error handling image upload:', error);
        showError('Failed to process image.');
    } finally {
        event.target.value = ''; // Reset input
    }
}

// 82) Safe WebSocket Send
function safeWebSocketSend(data) {
    if (!chatSocket || chatSocket.readyState !== WebSocket.OPEN) {
        console.log('WebSocket not ready, cannot send message');
        return false;
    }

    try {
        chatSocket.send(JSON.stringify(data));
        return true;
    } catch (error) {
        console.error('Error sending WebSocket message:', error);
        return false;
    }
}

// 83) Send Message via HTTP
async function sendMessageViaHTTP(message, receiver_id, timestamp, tempMessageId, messageType, encryptedData, isImage = false, imageSize = null) {
    try {
        const endpoint = messageType === 'group_message' ? '/groups/send_message/' : '/chat/send_message/';

        const payload = {
            message: message,
            encrypted_content: isImage ? null : encryptedData.ciphertext,
            iv: encryptedData.iv,
            receiver_id: receiver_id,
            timestamp: timestamp.toISOString(),
            temp_id: tempMessageId,
            is_image: isImage,
            image_size: imageSize,
            media_id: encryptedData.media_id || null
        };

        if (messageType === 'group_message') payload.group_id = receiver_id;

        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
            body: JSON.stringify(payload)
        });

        if (!response.ok) throw new Error('HTTP send failed');

        const data = await response.json();
        if (data.message_id && tempMessageId) updateTempMessageId(tempMessageId, data.message_id);
    } catch (error) {
        console.error('Error sending message via HTTP:', error);
        showError('Failed to send message. Please try again.');
    }
}

/**
 * Helper to upload encrypted media blob to server
 * @param {string} base64Ciphertext 
 * @returns {Promise<string>} media_id
 */
async function uploadEncryptedMedia(base64Ciphertext) {
    const binary = base64ToArrayBuffer(base64Ciphertext);
    const blob = new Blob([binary], { type: 'application/octet-stream' });

    const formData = new FormData();
    formData.append('file', blob, 'encrypted_media');

    const response = await fetch('/media/upload/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCSRFToken() },
        body: formData
    });

    if (!response.ok) throw new Error('Media upload failed');

    const data = await response.json();
    return data.media_id;
}

// 84) Process Pending Operations
function processPendingOperations(tempId, realId) {
    const operation = pendingMessageOperations.get(tempId);
    if (operation) {
        switch (operation.type) {
            case 'edit':
                safeWebSocketSend({
                    type: operation.message_type === 'group' ? "edit_group_message" : "edit_message",
                    message_id: realId,
                    new_content: operation.new_content,
                    ...(operation.message_type === 'group' && { group_id: currentGroup.id })
                });
                break;
            case 'delete':
                safeWebSocketSend({
                    type: operation.message_type === 'group' ? "delete_group_message" : "delete_message",
                    message_id: realId,
                    ...(operation.message_type === 'group' && { group_id: currentGroup.id })
                });
                break;
        }
        pendingMessageOperations.delete(tempId);
    }
}

// 85) Update Temp Message ID
function updateTempMessageId(tempId, realId) {
    const messageElement = document.querySelector(`[data-message-id="${tempId}"]`);
    if (messageElement) {
        messageElement.dataset.messageId = realId;
        tempToRealIdMap.set(tempId, realId);

        const statusElement = messageElement.querySelector('.message-status');
        const isRead = statusElement && statusElement.classList.contains('read');

        if (messageElement.classList.contains('sent')) {
            const existingActions = messageElement.querySelector('.message-actions');
            if (!existingActions) {
                const actionsDiv = document.createElement('div');
                actionsDiv.className = 'message-actions';
                actionsDiv.innerHTML = `
                    <button class="message-action-btn edit" onclick="editMessage('${realId}')">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="message-action-btn delete" onclick="openDeleteMessageModal('${realId}')">
                        <i class="fas fa-trash"></i>
                    </button>
                `;
                messageElement.appendChild(actionsDiv);
            }
        }

        if (statusElement) {
            if (isRead) statusElement.classList.add('read');
            else statusElement.classList.remove('read');
        }
    }
}

// 86) Update Message Status
function updateMessageStatus(messageId, isRead) {
    if (messageId.startsWith && messageId.startsWith('temp_')) {
        if (tempToRealIdMap.has(messageId)) messageId = tempToRealIdMap.get(messageId);
    }

    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;

    const statusElement = messageElement.querySelector('.message-status');
    if (statusElement) {
        if (isRead) {
            statusElement.classList.remove('sent');
            statusElement.classList.add('read');
            statusElement.innerHTML = '<span class="tick">✓</span><span class="tick">✓</span>';
        } else {
            statusElement.classList.remove('read');
            statusElement.classList.add('sent');
            statusElement.innerHTML = '<span class="tick">✓</span>';
        }
    } else if (messageElement.classList.contains('sent')) {
        const footer = messageElement.querySelector('.message-footer') || messageElement;
        const newStatus = document.createElement('div');
        newStatus.className = 'message-status ' + (isRead ? 'read' : 'sent');
        newStatus.innerHTML = isRead ? '<span class="tick">✓</span><span class="tick">✓</span>' : '<span class="tick">✓</span>';
        footer.appendChild(newStatus);
    }

    messageElement.dataset.read = isRead ? 'true' : 'false';
}

// 87) Setup Read Receipts
function setupReadReceipts() {
    cleanupReadReceipts();

    let lastScrollTime = 0;
    const SCROLL_THROTTLE = 1000;

    function isElementVisibleInChat(el) {
        if (!el) return false;
        const containerRect = chatBox.getBoundingClientRect();
        const elRect = el.getBoundingClientRect();
        const elMid = elRect.top + (elRect.height / 2);
        return elMid >= containerRect.top && elMid <= containerRect.bottom;
    }

    function checkUnreadMessages() {
        const now = Date.now();
        if (now - readReceiptLastSentTime < READ_RECEIPT_COOLDOWN) return;
        if (!currentFriend && !currentGroup) return;

        const receivedMessages = document.querySelectorAll('.message.received');
        const unreadToSend = [];

        receivedMessages.forEach(message => {
            const messageId = message.dataset.messageId;
            const alreadyMarked = message.dataset.read === 'true';

            if (messageId && !alreadyMarked && isElementVisibleInChat(message)) {
                unreadToSend.push(messageId);
                message.dataset.read = 'true';
            }
        });

        if (unreadToSend.length > 0) {
            const receiptData = {
                type: currentGroup ? "group_read_receipt" : "read_receipt",
                message_ids: unreadToSend,
                reader_id: userId
            };

            if (currentGroup) receiptData.group_id = currentGroup.id;

            safeWebSocketSend(receiptData);
            markMessagesAsRead(unreadToSend);
            readReceiptLastSentTime = now;
        }
    }

    readReceiptScrollHandler = function () {
        const now = Date.now();
        if (now - lastScrollTime < SCROLL_THROTTLE) return;
        lastScrollTime = now;

        if (readReceiptCheckTimeout) clearTimeout(readReceiptCheckTimeout);
        readReceiptCheckTimeout = setTimeout(checkUnreadMessages, 500);
    };

    chatBox.addEventListener('scroll', readReceiptScrollHandler);
    setTimeout(checkUnreadMessages, 1000);
}

// 88) Cleanup Read Receipts
function cleanupReadReceipts() {
    if (readReceiptCheckTimeout) {
        clearTimeout(readReceiptCheckTimeout);
        readReceiptCheckTimeout = null;
    }

    if (readReceiptScrollHandler) {
        chatBox.removeEventListener('scroll', readReceiptScrollHandler);
        readReceiptScrollHandler = null;
    }
}

// 89) Mark Messages as Read
async function markMessagesAsRead(messageIds) {
    if (!messageIds.length || (!currentFriend && !currentGroup)) return;

    try {
        const endpoint = currentGroup ? '/groups/mark_read/' : '/chat/mark_read/';
        const payload = { message_ids: messageIds };
        if (currentGroup) payload.group_id = currentGroup.id;

        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
            body: JSON.stringify(payload)
        });

        if (response.ok) messageIds.forEach(messageId => updateMessageStatus(messageId, true));
    } catch (error) {
        console.error('Error marking messages as read:', error);
    }
}

// 90) Update Message in UI
function updateMessageInUI(messageId, newContent, timestamp) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;

    const messageBody = messageElement.querySelector('.body');
    const timeElement = messageElement.querySelector('.time');

    if (messageBody && timeElement) {
        messageBody.textContent = newContent;
        timeElement.textContent = formatTime(timestamp) + ' (edited)';
    }
}

// ====================================================
// MESSAGE EDITING AND DELETION (91-110)
// ====================================================

// 91) Edit Message
function editMessage(messageId) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;

    const messageBody = messageElement.querySelector('.body');
    const currentContent = messageBody.textContent;

    currentEditingMessageId = messageId;
    editMessageText.value = currentContent;
    if (editModal) editModal.style.display = 'flex';
    editMessageText.focus();
}

// 92) Close Edit Modal
function closeEditModal() {
    if (editModal) editModal.style.display = 'none';
    currentEditingMessageId = null;
    if (editMessageText) editMessageText.value = '';
}

// 93) Save Edited Message
async function saveEditedMessage() {
    if (!currentEditingMessageId) return;

    const newContent = editMessageText.value.trim();
    if (!newContent) return;

    const messageIdToEdit = currentEditingMessageId;
    closeEditModal(); // Close immediately for responsive UX before network block

    const messageElement = document.querySelector(`[data-message-id="${messageIdToEdit}"]`);
    if (messageElement) {
        const messageBody = messageElement.querySelector('.body');
        const timeElement = messageElement.querySelector('.time');

        if (messageBody && timeElement) {
            messageBody.textContent = newContent;
            timeElement.textContent = formatTime(new Date()) + ' (edited)';
        }
    }

    try {
        let encryptedData;
        if (currentGroup) encryptedData = await encryptMessageForGroup(newContent, currentGroup.id);
        else if (currentFriend) encryptedData = await encryptMessageForContact(newContent, currentFriend.id);

        let endpoint, payload;

        if (currentGroup) {
            endpoint = '/groups/edit_message/';
            payload = {
                message_id: messageIdToEdit,
                new_content: newContent,
                encrypted_content: encryptedData.ciphertext,
                iv: encryptedData.iv,
                group_id: currentGroup.id
            };
        } else if (currentFriend) {
            endpoint = '/chat/edit_message/';
            payload = {
                message_id: messageIdToEdit,
                new_content: newContent,
                encrypted_content: encryptedData.ciphertext,
                iv: encryptedData.iv,
                receiver_id: currentFriend.id
            };
        } else return;

        const wsData = {
            type: currentGroup ? "edit_group_message" : "edit_message",
            message_id: messageIdToEdit,
            new_content: newContent,
            encrypted_content: encryptedData.ciphertext,
            iv: encryptedData.iv
        };

        if (currentGroup) wsData.group_id = currentGroup.id;
        else if (currentFriend) wsData.receiver_id = currentFriend.id;

        const wsSuccess = safeWebSocketSend(wsData);

        if (!wsSuccess) {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
                body: JSON.stringify(payload)
            });

            if (!response.ok) throw new Error('Failed to edit message');
        }

        showSuccess('Message edited successfully!');
    } catch (error) {
        console.error('Error editing message:', error);
        showError(error.message || 'Failed to edit message');
    }
}

// 94) Open Delete Message Modal
let messageToDelete = null;
function openDeleteMessageModal(messageId) {
    messageToDelete = messageId;
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (messageElement) {
        const messageBody = messageElement.querySelector('.body');
        if (messageBody) messageBody.dataset.originalContent = messageBody.textContent;
    }

    const modal = document.getElementById('deleteMessageModal');
    if (modal) modal.style.display = 'flex';
}

// 95) Close Delete Message Modal
function closeDeleteMessageModal() {
    const modal = document.getElementById('deleteMessageModal');
    if (modal) modal.style.display = 'none';
    messageToDelete = null;
}

// 96) Confirm Delete Message
function confirmDeleteMessage() {
    if (messageToDelete) {
        deleteMessage(messageToDelete);
        closeDeleteMessageModal();
    }
}

// 97) Delete Message
async function deleteMessage(messageId) {
    if (!messageId) return;

    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;

    const messageBody = messageElement.querySelector('.body');
    const actionsDiv = messageElement.querySelector('.message-actions');

    if (messageBody) {
        messageBody.textContent = 'This message was deleted';
        messageBody.style.color = '#999';
        messageBody.style.fontStyle = 'italic';
    }

    if (actionsDiv) actionsDiv.remove();

    let endpoint, payload;

    if (currentGroup) {
        endpoint = '/groups/delete_message/';
        payload = { message_id: messageId, group_id: currentGroup.id };
    } else if (currentFriend) {
        endpoint = '/chat/delete_message/';
        payload = { message_id: messageId, receiver_id: currentFriend.id };
    } else return;

    try {
        const wsData = {
            type: currentGroup ? "delete_group_message" : "delete_message",
            message_id: messageId
        };

        if (currentGroup) wsData.group_id = currentGroup.id;
        else if (currentFriend) wsData.receiver_id = currentFriend.id;

        const wsSuccess = safeWebSocketSend(wsData);

        if (!wsSuccess) {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
                body: JSON.stringify(payload)
            });

            if (!response.ok) throw new Error('Failed to delete message');
        }

        showSuccess('Message deleted successfully!');
    } catch (error) {
        console.error('Error deleting message:', error);
        showError(error.message || 'Failed to delete message');

        if (messageElement && messageBody) {
            messageBody.textContent = messageBody.dataset.originalContent || 'Message content';
            messageBody.style.color = '';
            messageBody.style.fontStyle = '';
        }
    }
}

// 98) Delete Message from UI
function deleteMessageFromUI(messageId) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;

    const messageBody = messageElement.querySelector('.body');
    const actionsDiv = messageElement.querySelector('.message-actions');

    if (messageBody) messageBody.textContent = 'This message was deleted';
    if (actionsDiv) actionsDiv.remove();
}

// 99) Open Clear Chat Modal
function openClearChatModal() {
    if (!currentFriend && !currentGroup) {
        showError('Please select a chat to clear');
        return;
    }

    if (currentGroup && !currentGroup.isAdmin) {
        showError('Only group admins can clear group chat');
        return;
    }

    const modal = document.getElementById('clearChatModal');
    if (modal) {
        const chatName = currentFriend ? currentFriend.name : currentGroup.name;
        const chatType = currentFriend ? 'chat' : 'group chat';

        const modalTitle = modal.querySelector('.modal-header h3');
        const modalBody = modal.querySelector('.modal-body p');

        if (modalTitle) modalTitle.textContent = currentFriend ? 'Clear Chat' : 'Clear Group Chat';
        if (modalBody) modalBody.textContent = `Are you sure you want to clear all messages in this ${chatType}? This action cannot be undone.`;

        modal.style.display = 'flex';
    }
}

// 100) Close Clear Chat Modal
function closeClearChatModal() {
    const modal = document.getElementById('clearChatModal');
    if (modal) modal.style.display = 'none';
}

