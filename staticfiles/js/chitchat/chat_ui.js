// ====================================================
// CHAT UI MANAGEMENT (61-80)
// ====================================================

const encryptedImageCache = new Map();


// 🖼 Dedicated avatar cache (DO NOT mix with crypto key cache)
const avatarCache = new Map();

// 61) Update Chat Header
function updateChatHeader(name, status) {
    chatName.textContent = name;
    chatStatus.textContent = status;
}

// 62) Update Chat Avatar
function updateChatAvatar(avatar, name, type) {
    const avatarClass = type === 'group'
        ? 'group-header-avatar'
        : 'chat-header-avatar';

    chatAvatar.className = avatarClass;

    if (avatar) {
        chatAvatar.innerHTML =
            `<img src="data:image/png;base64,${avatar}" alt="${name}">`;
    } else {
        chatAvatar.innerHTML =
            `<div class="avatar-initials">${getInitialsFromName(name)}</div>`;

        // Fetch avatar on-demand if available
        const targetId = type === 'group'
            ? currentGroup?.id
            : currentFriend?.id;

        if (targetId) {
            fetchAndSetHeaderAvatar(targetId, type, chatAvatar, name);
        }
    }
}

async function fetchAndSetHeaderAvatar(id, type, container, name) {
    const cacheKey = `${type}_${id}`;

    // ✅ Use avatarCache ONLY
    if (avatarCache.has(cacheKey)) {
        const base64 = avatarCache.get(cacheKey);

        if (base64) {
            container.innerHTML =
                `<img src="data:image/png;base64,${base64}" alt="${name}">`;
        } else {
            container.innerHTML =
                `<div class="avatar-initials">${getInitialsFromName(name)}</div>`;
        }
        return;
    }

    try {
        const response = await fetch(`/avatar/${type}/${id}/`);
        if (!response.ok) return;

        const data = await response.json();

        if (data.avatar_base64) {
            avatarCache.set(cacheKey, data.avatar_base64);

            container.innerHTML =
                `<img src="data:image/png;base64,${data.avatar_base64}" alt="${name}">`;
        } else {
            // ✅ Safe negative caching (does NOT affect crypto)
            avatarCache.set(cacheKey, null);

            container.innerHTML =
                `<div class="avatar-initials">${getInitialsFromName(name)}</div>`;
        }

    } catch (error) {
        console.error("Error fetching header avatar:", error);
    }
}

// 63) Show Group Management
function showGroupManagement(isAdmin) {
    const groupManagement = document.getElementById('groupManagement');
    const clearChatBtn = document.getElementById('clearChatBtn');
    const clearGroupChatOption = document.getElementById('clearGroupChatOption');

    if (groupManagement) {
        groupManagement.style.display = 'block';
        const adminOptions = document.querySelectorAll('.admin-only');
        adminOptions.forEach(option => option.style.display = isAdmin ? 'block' : 'none');
    }

    if (clearChatBtn) clearChatBtn.style.display = 'none';
    if (clearGroupChatOption) clearGroupChatOption.style.display = isAdmin ? 'block' : 'none';
}

// 64) Hide Group Management
function hideGroupManagement() {
    const groupManagement = document.getElementById('groupManagement');
    const clearChatBtn = document.getElementById('clearChatBtn');
    const clearGroupChatOption = document.getElementById('clearGroupChatOption');

    if (groupManagement) groupManagement.style.display = 'none';
    if (clearChatBtn) clearChatBtn.style.display = 'none'; // Only show via selectContact
    if (clearGroupChatOption) clearGroupChatOption.style.display = 'none';
}

// 64.1) Update Recipient Dropdown Content
function updateRecipientDropdownContent() {
    if (!currentFriend) return;

    const nameEl = document.getElementById('recipientDropdownName');
    const emailEl = document.getElementById('recipientDropdownEmail');
    const emailDetailEl = document.getElementById('recipientDropdownEmailDetail');
    const phoneEl = document.getElementById('recipientDropdownPhone');
    const avatarContainer = document.getElementById('recipientDropdownAvatar');

    if (nameEl) nameEl.textContent = currentFriend.name || 'Unknown';
    if (emailEl) emailEl.textContent = currentFriend.email || 'No email provided';
    if (emailDetailEl) emailDetailEl.textContent = currentFriend.email || 'No email provided';
    if (phoneEl) phoneEl.textContent = currentFriend.phone || 'Not provided';

    if (avatarContainer) {
        if (currentFriend.avatar) {
            avatarContainer.innerHTML = `<img src="data:image/png;base64,${currentFriend.avatar}" alt="${currentFriend.name}">`;
        } else {
            avatarContainer.innerHTML = `<div class="avatar-initials">${getInitialsFromName(currentFriend.name)}</div>`;
        }
    }
}

// 65) Handle Mobile View
// 65) Handle Mobile View (Switch from Contacts to Chat)
function handleMobileView() {
    if (window.innerWidth <= 768) {
        if (contactsPanel) contactsPanel.classList.remove('active');
        if (chatPanel) chatPanel.classList.remove('hidden');
    }
}

function goBackToContacts() {
    if (window.innerWidth <= 768) {
        if (contactsPanel) contactsPanel.classList.add('active');
        if (chatPanel) chatPanel.classList.add('hidden');
        resetCurrentSelections();
    }
}

// 66) Add Message to Chat
function addMessageToChat(content, isSent, timeStr, senderId, messageId, isEdited = false, isDeleted = false, isRead = false, senderName = null, timestamp = null, isImage = false, imageSize = null) {
    const isAtBottom = chatBox.scrollHeight - chatBox.scrollTop <= chatBox.clientHeight + 150;

    const msgDiv = createMessageElement(content, isSent, timeStr, senderId, messageId, isEdited, isDeleted, isRead, senderName, timestamp, isImage, imageSize);
    chatBox.appendChild(msgDiv);

    // Update oldest timestamp if it's the first message loaded
    if (!oldestMessageTimestamp && timestamp) {
        oldestMessageTimestamp = timestamp;
    }

    // Only autoscroll if user is sent the message OR is already at the bottom
    if (isSent || isAtBottom) {
        setTimeout(() => {
            chatBox.style.scrollBehavior = 'smooth';
            chatBox.scrollTop = chatBox.scrollHeight;
        }, 60);
    }
}

// 67) Show System Message
function showSystemMessage(message) {
    const isAtBottom = chatBox.scrollHeight - chatBox.scrollTop <= chatBox.clientHeight + 150;

    const systemMsgDiv = document.createElement('div');
    systemMsgDiv.className = 'system-message';
    systemMsgDiv.innerHTML = `
        <div class="system-message-content" style="text-align:center;color:#888;font-size:13px;font-style:italic;margin:10px 0;">
            <span>${escapeHtml(message)}</span>
        </div>
    `;
    chatBox.appendChild(systemMsgDiv);

    if (isAtBottom) {
        setTimeout(() => {
            chatBox.style.scrollBehavior = 'smooth';
            chatBox.scrollTop = chatBox.scrollHeight;
        }, 60);
    }
}


// Lazy loading states
let oldestMessageTimestamp = null;
let isLoadingOlder = false;
let hasMoreMessages = true;

async function loadMessages(isOlder = false) {
    if (!currentFriend && !currentGroup) return;
    if (isOlder && (!hasMoreMessages || isLoadingOlder)) return;

    try {
        if (isOlder) {
            isLoadingOlder = true;
            // Optionally show a small loader at the top
            const loader = document.createElement('div');
            loader.className = 'loading-older-spinner';
            loader.textContent = 'Loading older messages...';
            chatBox.prepend(loader);
        } else {
            // Remove smooth scroll and hide while loading to prevent "jump"
            chatBox.classList.add('history-loading');
            chatBox.innerHTML = '<div class="loading-spinner">Loading messages...</div>';
            oldestMessageTimestamp = null;
            hasMoreMessages = true;
        }

        let url;
        if (currentFriend) url = `/chat/history/?user_id=${currentFriend.id}`;
        else if (currentGroup) url = `/groups/history/?group_id=${currentGroup.id}`;

        if (isOlder && oldestMessageTimestamp) {
            url += `&before=${encodeURIComponent(oldestMessageTimestamp)}`;
        }

        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const data = await response.json();
        if (data.error) throw new Error(data.error);

        hasMoreMessages = data.has_more;

        // Remove older loader if present
        const oldLoader = chatBox.querySelector('.loading-older-spinner');
        if (oldLoader) oldLoader.remove();

        await renderMessages(data.messages, currentFriend, currentGroup, isOlder);

        if (isOlder) {
            isLoadingOlder = false;
        } else {
            // reveal is now handled inside renderMessages for non-older loads
        }
    } catch (error) {
        console.error('Error loading messages:', error);
        chatBox.classList.remove('history-loading');
        if (!isOlder) {
            chatBox.innerHTML = `
                <div class="error-message">
                    Failed to load messages. Please try again.
                    <button onclick="loadMessages()">Retry</button>
                </div>
            `;
        }
        isLoadingOlder = false;
    }
}

// 69) Render Messages - UPDATED FOR BOTH INDIVIDUAL AND GROUP + Lazy Loading
async function renderMessages(messages, currentFriend = null, currentGroup = null, isOlder = false) {
    if (!isOlder) {
        chatBox.innerHTML = '';
        // Lock scroll behavior during initial paint
        chatBox.style.scrollBehavior = 'auto';
    }

    if (!messages || messages.length === 0) {
        if (!isOlder) {
            chatBox.innerHTML = '<div class="no-messages">No messages yet. Start the conversation!</div>';
            chatBox.classList.remove('history-loading');
        }
        return;
    }

    // NEW: Handle duplicate date dividers at batch junction
    if (isOlder && messages.length > 0) {
        const lastNewMsgDate = new Date(messages[messages.length - 1].timestamp).toDateString();
        const firstExistingDivider = chatBox.querySelector('.date-divider');
        // If the first thing in chat is a divider for the same day as our new batch ends
        if (firstExistingDivider && (firstExistingDivider.dataset.date === lastNewMsgDate)) {
            firstExistingDivider.remove();
        }
    }

    const previousHeight = chatBox.scrollHeight;

    // Create a fragment or temporary container to avoid repeated DOM updates
    const fragment = document.createDocumentFragment();
    let lastDate = '';

    // If loading older, we might need to handle the date divider gap between batches
    // But for simplicity, we render batch by batch.
    // Optimization: check the last message of the older batch vs first message of the current top

    // Prepare all message content (decrypt in parallel + check cache)
    const processedMessages = await Promise.all(messages.map(async (msg) => {
        let content = msg.message || msg.content;
        const isSent = msg.sender_id === userId;
        const isImage = msg.is_image || false;

        if (isImage) {
            // Check IndexedDB cache for encrypted image
            const cachedData = await getFromCache(msg.id);
            if (cachedData && cachedData.ciphertext && cachedData.iv) {
                try {
                    let buffer;
                    if (currentGroup) {
                        buffer = await decryptGroupImage(cachedData.ciphertext, cachedData.iv, currentGroup.id);
                    } else {
                        if (isSent) {
                            buffer = await decryptImageWithReceiver({ ciphertext: cachedData.ciphertext, iv: cachedData.iv }, msg.receiver_id);
                        } else {
                            buffer = await decryptImageWithSender({ ciphertext: cachedData.ciphertext, iv: cachedData.iv }, msg.sender_id);
                        }
                    }
                    const b64 = arrayBufferToBase64(buffer);
                    const dataUrl = `data:image/webp;base64,${b64}`;
                    return { ...msg, decryptedContent: dataUrl, isCached: true, isSent, timeStr: formatTime(msg.timestamp), isImage, imageSize: msg.image_size };
                } catch (err) {
                    console.error('Failed to decrypt cached image:', err);
                    // Fall through to lazy load if decryption fails
                }
            }
        }

        if (msg.encrypted_content && msg.iv && !isImage) {
            try {
                if (currentFriend) {
                    if (isSent) {
                        content = await decryptMessageWithReceiver({ ciphertext: msg.encrypted_content, iv: msg.iv }, msg.receiver_id);
                    } else {
                        content = await decryptMessageWithSender({ ciphertext: msg.encrypted_content, iv: msg.iv }, msg.sender_id);
                    }
                } else if (currentGroup) {
                    content = await decryptGroupMessage(msg.encrypted_content, msg.iv, currentGroup.id);
                }
            } catch (error) {
                console.error('Error decrypting message:', error);
                content = '🔒 Unable to decrypt message';
            }
        }
        return { ...msg, decryptedContent: content, isSent, timeStr: formatTime(msg.timestamp), isImage, imageSize: msg.image_size };
    }));

    for (const msg of processedMessages) {
        const msgDate = new Date(msg.timestamp);
        const dateStr = msgDate.toDateString();

        if (dateStr !== lastDate) {
            lastDate = dateStr;
            const dateDiv = document.createElement('div');
            dateDiv.className = 'date-divider';
            dateDiv.dataset.date = dateStr;
            dateDiv.textContent = formatDateDivider(msgDate);
            fragment.appendChild(dateDiv);
        }

        const isRead = Boolean(msg.read);

        // Cache encrypted data/metadata for lazy loading
        if (msg.is_image && !msg.isCached) {
            encryptedImageCache.set(msg.id || msg.temp_id, {
                ciphertext: msg.encrypted_content,
                iv: msg.iv,
                sender_id: msg.sender_id,
                receiver_id: msg.receiver_id,
                image_size: msg.image_size,
                media_id: msg.media_id,
                is_group: !!currentGroup,
                group_id: currentGroup ? currentGroup.id : null
            });
        }

        const msgDiv = createMessageElement(msg.decryptedContent, msg.isSent, msg.timeStr, msg.sender_id, msg.id, msg.edited, msg.deleted, isRead, msg.sender_name, msg.timestamp, msg.isImage, msg.imageSize);
        fragment.appendChild(msgDiv);
    }

    // Update oldest timestamp
    if (messages.length > 0) {
        const batchOldest = messages[0].timestamp;
        if (!oldestMessageTimestamp || new Date(batchOldest) < new Date(oldestMessageTimestamp)) {
            oldestMessageTimestamp = batchOldest;
        }
    }

    if (isOlder) {
        // ENFORCE auto scroll behavior to prevent "smooth scroll jump" back to bottom
        const originalBehavior = chatBox.style.scrollBehavior;
        chatBox.style.scrollBehavior = 'auto';

        chatBox.prepend(fragment);
        // Maintain scroll position (instant)
        chatBox.scrollTop = chatBox.scrollHeight - previousHeight;

        // Restore behavior after a tiny delay
        setTimeout(() => {
            chatBox.style.scrollBehavior = originalBehavior;
        }, 50);
    } else {
        chatBox.appendChild(fragment);

        // Use a more robust triple-scroll to ensure it hits bottom before reveal
        const scrollToBottom = () => {
            chatBox.style.scrollBehavior = 'auto';
            chatBox.scrollTop = chatBox.scrollHeight;
        };

        scrollToBottom();

        // Short delay to allow layout engine to update heights
        setTimeout(() => {
            scrollToBottom();
            chatBox.classList.remove('history-loading');
            chatBox.style.scrollBehavior = ''; // Restore smooth scroll
            setupReadReceipts();
        }, 30);
    }
}

// Helper to create message element without appending (refactored from addMessageToChat)
function createMessageElement(content, isSent, timeStr, senderId, messageId, isEdited = false, isDeleted = false, isRead = false, senderName = null, rawTimestamp = null, isImage = false, imageSize = null) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${isSent ? 'sent' : 'received'}`;
    if (isImage) msgDiv.classList.add('image-message');
    msgDiv.dataset.messageId = messageId;
    msgDiv.dataset.read = isRead ? 'true' : 'false';

    if (isDeleted) content = 'This message was deleted';

    let label = isSent ? 'You' : (senderName || (currentFriend ? currentFriend.name : 'User'));

    let statusIndicator = '';
    if (isSent && !isDeleted) {
        statusIndicator = `
            <div class="message-status ${isRead ? 'read' : 'sent'}">
                ${isRead ? '<span class="tick">✓</span><span class="tick">✓</span>' : '<span class="tick">✓</span>'}
            </div>
        `;
    }

    let bodyContent;
    if (isImage && !isDeleted) {
        const sizeStr = formatFileSize(imageSize);
        // Check if content is a data URL (cached/decrypted) or a raw Base64 string
        if (content && (content.startsWith('data:image') || content.length > 50)) {
            const dataUrl = content.startsWith('data:image') ? content : `data:image/webp;base64,${content}`;
            bodyContent = `
                <div class="image-container">
                    <img src="${dataUrl}" class="chat-image" alt="Shared image" onclick="viewImage(this.src)">
                    <div class="image-overlay">
                        ${sizeStr ? `<span class="image-size">${sizeStr}</span>` : ''}
                        <button class="image-download-btn" onclick="downloadImage('${dataUrl}', 'image_${messageId}.webp')" title="Download Image">
                            <i class="fas fa-download"></i>
                        </button>
                    </div>
                </div>
            `;
        } else {
            // Placeholder state (WhatsApp Style)
            const hasKeys = !!window.masterKey;

            bodyContent = `
                <div class="image-container placeholder" id="img-container-${messageId}" onclick="${hasKeys ? `loadAndDecryptImage('${messageId}')` : `showError('Please enter your passcode to view images')`}">
                    <div class="image-placeholder-content">
                        <div class="download-icon-container">
                            <i class="fas ${hasKeys ? 'fa-download' : 'fa-lock'} center-download"></i>
                            <div class="spinner-small" style="display:none"></div>
                        </div>
                        <span class="placeholder-size">${hasKeys ? (sizeStr || 'Image') : '🔒 Encrypted Image'}</span>
                    </div>
                </div>
            `;
        }
    } else {
        bodyContent = escapeHtml(content);
    }

    msgDiv.innerHTML = `
        ${!isSent || currentGroup ? `<span class="sender-label">${label}</span>` : ''}
        <div class="body">${bodyContent}</div>
        <div class="message-footer">
            <small class="time">${timeStr}${isEdited ? ' (edited)' : ''}</small>
            ${statusIndicator}
        </div>
    `;

    const isTempId = typeof messageId === 'string' && messageId.startsWith('temp_');
    if (isSent && !isDeleted && !isTempId) {
        // Calculate message age for edit window (5 minutes = 300,000ms)
        const messageAge = rawTimestamp ? (new Date() - new Date(rawTimestamp)) : 0;
        const canEdit = messageAge < 300000;

        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'message-actions';

        let editBtnHtml = '';
        if (canEdit) {
            editBtnHtml = `
                <button class="message-action-btn edit" onclick="editMessage('${messageId}')">
                    <i class="fas fa-edit"></i>
                </button>
            `;
        }

        actionsDiv.innerHTML = `
            ${editBtnHtml}
            <button class="message-action-btn delete" onclick="openDeleteMessageModal('${messageId}')">
                <i class="fas fa-trash"></i>
            </button>
        `;
        msgDiv.appendChild(actionsDiv);
    }
    return msgDiv;
}

// Initialize scroll listener (Called from initializeApp via common.js)
function initializeChatScroll() {
    if (!chatBox) return;

    chatBox.addEventListener('scroll', () => {
        // Increased threshold to 50px for better reliability
        if (chatBox.scrollTop <= 50 && hasMoreMessages && !isLoadingOlder && oldestMessageTimestamp) {
            console.log('Fetching older messages...');
            loadMessages(true);
        }
    });
}

// 70) Decrypt with Receiver ID (INDIVIDUAL CHAT)
async function decryptMessageWithReceiver(encryptedData, receiverId) {
    try {
        const roomKey = await getOrCreateRoomKey(receiverId);
        return await decryptMessage(encryptedData, roomKey);
    } catch (error) {
        console.error(`Failed to decrypt message to ${receiverId}:`, error);
        throw error;
    }
}

async function decryptMessageWithSender(encryptedData, senderId) {
    try {
        const roomKey = await getOrCreateRoomKey(senderId);
        return await decryptMessage(encryptedData, roomKey);
    } catch (error) {
        console.error(`Failed to decrypt message from ${senderId}:`, error);
        throw error;
    }
}

// ✅ NEW: Group Message Decryption
async function decryptGroupMessage(encryptedContent, iv, groupId) {
    try {
        console.log(`🔐 Decrypting group message for group ${groupId}`);

        // Get the group key (same one used for WebSocket messages)
        const groupKey = await getOrCreateGroupKey(groupId);

        const encryptedData = {
            ciphertext: encryptedContent,
            iv: iv
        };

        return await decryptMessage(encryptedData, groupKey);
    } catch (error) {
        console.error(`Failed to decrypt group message for ${groupId}:`, error);
        throw error;
    }
}

// ✅ NEW: Image Decryption Helpers
async function decryptImageWithReceiver(encryptedData, receiverId) {
    const roomKey = await getOrCreateRoomKey(receiverId);
    return await decryptFile(encryptedData, roomKey);
}

async function decryptImageWithSender(encryptedData, senderId) {
    const roomKey = await getOrCreateRoomKey(senderId);
    return await decryptFile(encryptedData, roomKey);
}

async function decryptGroupImage(encryptedContent, iv, groupId) {
    const groupKey = await getOrCreateGroupKey(groupId);
    return await decryptFile({ ciphertext: encryptedContent, iv: iv }, groupKey);
}

// ✅ NEW: Image Compression (WhatsApp standard: 1600px max)
async function compressImage(file, maxWidth = 1600, maxHeight = 1600, quality = 0.8) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.readAsDataURL(file);
        reader.onload = (event) => {
            const img = new Image();
            img.src = event.target.result;
            img.onload = () => {
                const canvas = document.createElement('canvas');
                let width = img.width;
                let height = img.height;

                if (width > height) {
                    if (width > maxWidth) {
                        height *= maxWidth / width;
                        width = maxWidth;
                    }
                } else {
                    if (height > maxHeight) {
                        width *= maxHeight / height;
                        height = maxHeight;
                    }
                }

                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, width, height);

                canvas.toBlob((blob) => {
                    if (blob) {
                        blob.arrayBuffer().then(resolve).catch(reject);
                    } else {
                        reject(new Error('Canvas toBlob failed'));
                    }
                }, 'image/webp', quality);
            };
            img.onerror = reject;
        };
        reader.onerror = reject;
    });
}

// ✅ NEW: View Image (Light-box simple)
function viewImage(src) {
    const viewer = document.createElement('div');
    viewer.className = 'image-viewer-overlay';
    viewer.innerHTML = `
        <div class="image-viewer-content">
            <img src="${src}" alt="Full view">
            <div class="viewer-actions">
                <button class="viewer-close">&times;</button>
                <a href="${src}" download="image_download.webp" class="viewer-download">
                    <i class="fas fa-download"></i> Download
                </a>
            </div>
        </div>
    `;
    viewer.onclick = (e) => {
        if (e.target.className === 'image-viewer-overlay' || e.target.className === 'viewer-close') {
            viewer.remove();
        }
    };
    document.body.appendChild(viewer);
}

// ✅ NEW: Download Image Helper
function downloadImage(dataUrl, filename) {
    const link = document.createElement('a');
    link.href = dataUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ✅ NEW: WhatsApp Style Lazy Decrypt & Download
async function loadAndDecryptImage(messageId) {
    const container = document.getElementById(`img-container-${messageId}`);
    if (!container || !container.classList.contains('placeholder')) return;

    const data = encryptedImageCache.get(messageId);
    if (!data) return;

    // Show loading state
    const icon = container.querySelector('.center-download');
    const spinner = container.querySelector('.spinner-small');
    if (icon) icon.style.display = 'none';
    if (spinner) spinner.style.display = 'block';

    try {
        let ciphertext = data.ciphertext;
        let iv = data.iv;

        // If it's a link-based image and we don't have the ciphertext in memory
        if (data.media_id && !ciphertext) {
            console.log(`📥 Fetching encrypted media from server: ${data.media_id}`);
            const response = await fetch(`/media/download/${data.media_id}/`);
            if (!response.ok) throw new Error('Failed to download encrypted media');

            // The response is an application/octet-stream (binary ciphertext)
            const blob = await response.blob();
            const arrayBuffer = await blob.arrayBuffer();

            // We need it as Base64 for the existing decryption logic or modify decryption to take buffers
            // DecryptMessage currently takes {ciphertext, iv} where ciphertext is B64
            // Let's convert to B64 for consistency with current code
            ciphertext = arrayBufferToBase64(arrayBuffer);
        }

        if (!ciphertext || !iv) throw new Error('Missing encrypted data or IV');

        let buffer;
        if (data.is_group) {
            buffer = await decryptGroupImage(ciphertext, iv, data.group_id);
        } else {
            const isSent = data.sender_id === userId;
            if (isSent) {
                buffer = await decryptImageWithReceiver({ ciphertext: ciphertext, iv: iv }, data.receiver_id);
            } else {
                buffer = await decryptImageWithSender({ ciphertext: ciphertext, iv: iv }, data.sender_id);
            }
        }

        const b64 = arrayBufferToBase64(buffer);
        const dataUrl = `data:image/webp;base64,${b64}`;
        const sizeStr = formatFileSize(data.image_size);

        // Save to browser cache (IndexedDB) in ENCRYPTED form for next time
        if (messageId && !messageId.startsWith('temp_')) {
            saveToCache(messageId, ciphertext, iv).catch(err => console.error('Cache save error:', err));
        }

        // Update UI: Swap placeholder for image
        container.classList.remove('placeholder');
        container.removeAttribute('onclick');
        container.innerHTML = `
            <img src="${dataUrl}" class="chat-image" alt="Shared image" onclick="viewImage(this.src)">
            <div class="image-overlay">
                ${sizeStr ? `<span class="image-size">${sizeStr}</span>` : ''}
                <button class="image-download-btn" onclick="downloadImage('${dataUrl}', 'image_${messageId}.webp')" title="Download Image">
                    <i class="fas fa-download"></i>
                </button>
            </div>
        `;

        // Automatically trigger download as requested
        downloadImage(dataUrl, `image_${messageId}.webp`);
    } catch (error) {
        console.error('Lazy decryption failed:', error);
        if (icon) icon.style.display = 'block';
        if (spinner) spinner.style.display = 'none';
        showError('Failed to decrypt image.');
    }
}

// ✅ NEW: Format File Size
function formatFileSize(bytes) {
    if (!bytes || isNaN(bytes)) return '';
    if (bytes < 1024) return bytes + ' B';
    else if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    else return (bytes / 1048576).toFixed(1) + ' MB';
}

// ====================================================
// EVENT HANDLERS (121-130)
// ====================================================

// 121) Handle Modal Click
function handleModalClick(e) {
    if (e.target.classList.contains('confirmation-modal')) {
        if (e.target.id === 'deleteMessageModal') closeDeleteMessageModal();
        else if (e.target.id === 'clearChatModal') closeClearChatModal();
        else if (e.target.id === 'leaveGroupModal') closeLeaveGroupModal();
        else if (e.target.id === 'deleteGroupModal') closeDeleteGroupModal();
    }

    if (e.target.classList.contains('group-management-modal')) {
        if (e.target.id === 'viewMembersModal') closeViewMembersModal();
        else if (e.target.id === 'addMembersModal') closeAddMembersModal();
        else if (e.target.id === 'removeMembersModal') closeRemoveMembersModal();
        else if (e.target.id === 'makeAdminModal') closeMakeAdminModal();
        else if (e.target.id === 'removeAdminModal') closeRemoveAdminModal();
    }

    if (e.target.classList.contains('create-group-modal')) closeCreateGroupModal();
    if (e.target.classList.contains('passcode-modal')) closePasscodeModal();
}

// 122) Handle Escape Key
function handleEscapeKey(e) {
    if (e.key === 'Escape') {
        const modals = [
            'deleteMessageModal', 'clearChatModal', 'leaveGroupModal', 'deleteGroupModal',
            'viewMembersModal', 'addMembersModal', 'removeMembersModal', 'makeAdminModal',
            'removeAdminModal', 'createGroupModal', 'passcodeSetupModal', 'passcodeEntryModal'
        ];

        for (const modalId of modals) {
            const modal = document.getElementById(modalId);
            if (modal && modal.style.display === 'flex') {
                if (modalId === 'deleteMessageModal') closeDeleteMessageModal();
                else if (modalId === 'clearChatModal') closeClearChatModal();
                else if (modalId === 'createGroupModal') closeCreateGroupModal();
                else if (modalId.includes('passcode')) closePasscodeModal();
                return;
            }
        }

        if (editModal && editModal.style.display === 'flex') closeEditModal();
    }
}

// 123) Handle Resize
function handleResize() {
    if (window.innerWidth > 768) {
        contactsPanel.classList.remove('active');
        chatPanel.classList.remove('hidden');
    }
}

// 124) Handle Edit Modal Click
function handleEditModalClick(e) {
    if (e.target === editModal) closeEditModal();
}

// 125) Handle Edit Escape Key
function handleEditEscapeKey(e) {
    if (e.key === 'Escape' && editModal && editModal.style.display === 'flex') closeEditModal();
}

// 126) Handle Group Member Selection
function handleGroupMemberSelection(e) {
    if (e.target.matches('#groupMembers input[type="checkbox"]')) updateSelectedCount();
}

// 127) Refresh Contacts
async function refreshContacts() {
    await loadContacts();
    showSuccess('Contacts refreshed');
}

// 128) Refresh Groups
async function refreshGroups() {
    await loadGroups();
    showSuccess('Groups refreshed');
}

// 129) Logout
function logout() {
    clearKeyCache();
    window.location.href = '/logout/';
}

// 130) Get Encryption Status
function getEncryptionStatus() {
    return {
        keysLoaded: !!(userPrivateKey && userPublicKey),
        masterKeyLoaded: !!masterKey,
        cachedKeys: keyCache.size
    };
}

