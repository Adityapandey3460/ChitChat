// ====================================================
// Complete Chat Application with End-to-End Encryption
// ====================================================

// Global variables
let currentFriend = null;
let currentGroup = null;
let chatSocket = null;
let globalSocket = null; // New app-wide WebSocket connection
let typingTimer = null;
let currentEditingMessageId = null;
let currentPasscodeTab = 'verify';
let isNewUser = false;

// Contact Pagination
let contactOffset = 0;
const contactLimit = 20;
let hasMoreContacts = true;
let isContactLoading = false;

// Group Pagination
let groupOffset = 0;
const groupLimit = 20;
let hasMoreGroups = true;
let isGroupLoading = false;

// Encryption variables
let userPrivateKey = null;
let userPublicKey = null;
let masterKey = null;
let keyCache = new Map();
let pendingKeyOperations = new Map();
let publicKeyCache = new Map();

// Bundled data cache (for optimization)
let cachedUserKeyBundle = null;
let preFetchedPublicKeys = new Map();
let preFetchedGroupSeeds = new Map();

// Lazy loading for avatars
const avatarObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const el = entry.target;
            const id = el.dataset.avatarId;
            const type = el.dataset.avatarType;
            if (id && type) {
                fetchAndSetAvatar(id, type, el);
            }
            avatarObserver.unobserve(el);
        }
    });
}, { rootMargin: '50px' });


// Message tracking
const pendingMessageOperations = new Map();
const tempToRealIdMap = new Map();

// Group management variables
let currentGroupMembers = [];
let availableContacts = [];
let selectedMembersForRemoval = [];
let selectedMembersForAdmin = [];
let selectedAdminsForRemoval = [];

// DOM Elements (Initialized in initializeApp)
let chatPanel, contactsPanel, chatBox, messageInput, contactList, groupList, chatHeader, chatName, chatStatus, chatAvatar, clearChatBtn, editModal, editMessageText;

function initializeDOM() {
    chatPanel = document.getElementById("chatPanel");
    contactsPanel = document.getElementById("sidebar");
    chatBox = document.getElementById("chatBox");
    messageInput = document.getElementById("messageInput");
    contactList = document.getElementById("contactList");
    groupList = document.getElementById("groupList");
    chatHeader = document.getElementById("chatHeader");
    chatName = document.getElementById("chatName");
    chatStatus = document.getElementById("chatStatus");
    chatAvatar = document.getElementById("chatAvatar");
    clearChatBtn = document.getElementById("clearChatBtn");
    editModal = document.getElementById("editModal");
    editMessageText = document.getElementById("editMessageText");
}

// Tab management
let currentTab = 'contacts';

// Read receipt variables
let readReceiptLastSentTime = 0;
const READ_RECEIPT_COOLDOWN = 3000;
let readReceiptCheckTimeout = null;
let readReceiptScrollHandler = null;

// Encryption constants
const ENCRYPTION_ALGORITHM = 'AES-GCM';
const KEY_ALGORITHM = { name: 'ECDH', namedCurve: 'P-256' };
const KEY_DERIVATION_ALGORITHM = { name: 'PBKDF2' };
const KEY_USAGES = ['deriveKey', 'deriveBits'];

// ====================================================
// INITIALIZATION FUNCTIONS (1-10)
// ====================================================

// 1) Initialize Application
function initializeApp() {
    console.log('Initializing application...');
    initializeDOM();
    initializeChatScroll();
    initializeContactScroll();
    initializeGroupScroll();

    // Initial data load
    loadContacts();
    loadGroups();
    initializeProfileDropdown();
    initializeContactSearch();
    initializeGroupSearch();
    initializeTabNavigation();
    initializeGroupManagement();
    initializeEventListeners();
    setupMobileView();
    initializeMobileNavigation();
    initializeRecipientDropdown();
    connectGlobalWebSocket(); // Connect global listeners first

    setTimeout(() => {
        initializePasscodeSystem();
    }, 500);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeApp);
} else {
    initializeApp();
}

// 2) Initialize Event Listeners
function initializeEventListeners() {
    initializeMessageInput();
    initializeModalEvents();

    // Typing indicator handled in initializeMessageInput
}

// 3) Initialize Message Input
function initializeMessageInput() {
    if (messageInput) {
        messageInput.addEventListener('input', () => {
            handleTypingStart();
            adjustInputHeight();
        });
        messageInput.addEventListener('keydown', handleKeyPress);
    }
}

// 4) Initialize Modal Events
function initializeModalEvents() {
    document.addEventListener('click', handleModalClick);
    document.addEventListener('keydown', handleEscapeKey);
    window.addEventListener('resize', handleResize);
    window.addEventListener('click', handleEditModalClick);
    document.addEventListener('keydown', handleEditEscapeKey);
    document.addEventListener('change', handleGroupMemberSelection);
}

// 5) Initialize Tab Navigation
function initializeTabNavigation() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;

    const tabButtons = sidebar.querySelectorAll('.tab-btn');

    tabButtons.forEach(button => {
        button.addEventListener('click', function () {
            const tabId = this.dataset.tab;
            currentTab = tabId; // Keep currentTab updated

            // Remove active class from all buttons and content within sidebar ONLY
            sidebar.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            sidebar.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

            // Add active class to current selection
            this.classList.add('active');
            const targetContent = document.getElementById(`${tabId}-tab`);
            if (targetContent) targetContent.classList.add('active');

            // FETCH DATA ONLY IF EMPTY (Optimization: remove redundant loads)
            if (tabId === 'contacts') {
                if (contactList && contactList.children.length === 0) loadContacts();
            } else if (tabId === 'groups') {
                if (groupList && groupList.children.length === 0) loadGroups();
            }

            if (window.innerWidth <= 768) {
                if (contactsPanel) contactsPanel.classList.add('active');
                if (chatPanel) chatPanel.classList.add('hidden');
            }
            resetChatView();
        });
    });

    // Add delegation for contact and group clicks
    if (contactList) {
        contactList.addEventListener('click', function (e) {
            const contactEl = e.target.closest('.contact');
            if (contactEl && !contactEl.dataset.groupId) {
                selectContact(null, contactEl);
            }
        });
    }

    if (groupList) {
        groupList.addEventListener('click', function (e) {
            const groupEl = e.target.closest('.contact');
            if (groupEl && groupEl.dataset.groupId) {
                selectGroup(null, groupEl);
            }
        });
    }
}

// 6) Initialize Recipient Dropdown
function initializeRecipientDropdown() {
    const trigger = document.getElementById('recipientProfileTrigger');
    const dropdown = document.getElementById('recipientDropdown');

    if (trigger && dropdown) {
        trigger.addEventListener('click', (e) => {
            // Only toggle if we are in an individual chat
            if (currentFriend) {
                e.stopPropagation();

                // Hide user profile dropdown if it's open
                const userDropdown = document.getElementById('profileDropdown');
                if (userDropdown) userDropdown.classList.remove('show');

                dropdown.classList.toggle('show');
                if (dropdown.classList.contains('show')) {
                    updateRecipientDropdownContent();
                }
            }
        });

        document.addEventListener('click', (e) => {
            if (!trigger.contains(e.target)) {
                dropdown.classList.remove('show');
            }
        });
    }
}

// 6) Initialize Contact Search
function initializeContactSearch() {
    const contactSearch = document.getElementById('contactSearch');
    if (!contactSearch) return;

    contactSearch.addEventListener('input', function () {
        const searchTerm = this.value.toLowerCase().trim();
        const contacts = document.querySelectorAll('#contactList .contact');

        contacts.forEach(contact => {
            const contactName = (contact.dataset.contactName || '').toLowerCase();
            contact.style.display = contactName.includes(searchTerm) ? 'flex' : 'none';
        });
    });
}

// 7) Initialize Group Search
function initializeGroupSearch() {
    const groupSearch = document.getElementById('groupSearch');
    if (!groupSearch) return;

    groupSearch.addEventListener('input', function () {
        const searchTerm = this.value.toLowerCase().trim();
        const groups = document.querySelectorAll('#groupList .contact');

        groups.forEach(group => {
            const groupName = (group.dataset.groupName || '').toLowerCase();
            group.style.display = groupName.includes(searchTerm) ? 'flex' : 'none';
        });
    });
}

// 8) Initialize Profile Dropdown
function initializeProfileDropdown() {
    const profileDropdownTrigger = document.getElementById('profileDropdownTrigger');
    const profileDropdown = document.getElementById('profileDropdown');

    if (!profileDropdownTrigger || !profileDropdown) return;

    const headerAvatar = profileDropdownTrigger.querySelector('.profile-avatar');
    if (headerAvatar) {
        headerAvatar.innerHTML = userAvatar
            ? `<img src="data:image/png;base64,${userAvatar}" alt="${userName || 'User'}">`
            : `<div class="avatar-initials">${getInitialsFromName(userName || userEmail)}</div>`;
    }

    const dropdownAvatar = profileDropdown.querySelector('.dropdown-avatar');
    const dropdownName = profileDropdown.querySelector('.dropdown-user-name');
    const dropdownEmail = profileDropdown.querySelector('.dropdown-user-email');

    if (dropdownAvatar) {
        dropdownAvatar.innerHTML = userAvatar
            ? `<img src="data:image/png;base64,${userAvatar}" alt="${userName || 'User'}">`
            : `<div class="avatar-initials">${getInitialsFromName(userName || userEmail)}</div>`;
    }

    if (dropdownName) dropdownName.textContent = userName || 'User';
    if (dropdownEmail) dropdownEmail.textContent = userEmail || 'No email';

    profileDropdownTrigger.addEventListener('click', function (e) {
        e.stopPropagation();

        // Hide recipient dropdown if it's open
        const recipientDropdown = document.getElementById('recipientDropdown');
        if (recipientDropdown) recipientDropdown.classList.remove('show');

        profileDropdown.classList.toggle('show');
    });

    document.addEventListener('click', function (e) {
        if (!profileDropdown.contains(e.target) && !profileDropdownTrigger.contains(e.target)) {
            profileDropdown.classList.remove('show');
        }
    });
}

// 9) Initialize Group Management
function initializeGroupManagement() {
    const groupManagementBtn = document.getElementById('groupManagementBtn');
    if (groupManagementBtn) {
        groupManagementBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            const dropdown = document.getElementById('groupManagementDropdown');
            if (dropdown) dropdown.classList.toggle('show');
        });
    }

    document.addEventListener('click', function () {
        const dropdown = document.getElementById('groupManagementDropdown');
        if (dropdown) dropdown.classList.remove('show');
    });
}

// 10) Toggle Sidebar
function toggleSidebar() {
    if (window.innerWidth <= 768) {
        if (contactsPanel) contactsPanel.classList.toggle('active');
        if (chatPanel) chatPanel.classList.toggle('hidden');
    }
}

// 11) Setup Mobile View Initial State
function setupMobileView() {
    if (window.innerWidth <= 768) {
        if (!currentFriend && !currentGroup) {
            if (chatPanel) chatPanel.classList.add('hidden');
            if (contactsPanel) contactsPanel.classList.add('active');
        } else {
            handleMobileView();
        }
    }
}

function initializeMobileNavigation() {
    const backBtn = document.getElementById('mobileBackBtn');
    if (backBtn) {
        backBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            goBackToContacts();
        });
    }
}

// ====================================================
// CONTACT AND GROUP MANAGEMENT (51-70)
// ====================================================

// 51) Load Contacts
async function loadContacts(isAppend = false) {
    if (isContactLoading || (!hasMoreContacts && isAppend)) return;

    isContactLoading = true;
    if (!isAppend) contactOffset = 0;

    try {
        const url = `/get_contacts/?offset=${contactOffset}&limit=${contactLimit}`;
        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to load contacts');
        const data = await response.json();

        renderContacts(data.contacts, isAppend);

        hasMoreContacts = data.has_more;
        if (hasMoreContacts) {
            contactOffset += data.contacts.length;
        }
    } catch (error) {
        console.error('Error loading contacts:', error);
        if (!isAppend) showError('Failed to load contacts');
    } finally {
        isContactLoading = false;
    }
}

// 52) Load Groups
async function loadGroups(isAppend = false) {
    if (isGroupLoading || (!hasMoreGroups && isAppend)) return;

    isGroupLoading = true;
    if (!isAppend) groupOffset = 0;

    try {
        const url = `/groups/?offset=${groupOffset}&limit=${groupLimit}`;
        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to load groups');
        const data = await response.json();

        renderGroups(data.groups, isAppend);

        hasMoreGroups = data.has_more;
        if (hasMoreGroups) {
            groupOffset += data.groups.length;
        }
    } catch (error) {
        console.error('Error loading groups:', error);
        if (!isAppend) showError('Failed to load groups');
    } finally {
        isGroupLoading = false;
    }
}

// 53) Render Contacts
function renderContacts(contacts, isAppend = false) {
    if (!contactList) return;
    if (!isAppend) contactList.innerHTML = '';

    contacts.forEach(contact => {
        // Prevent duplicates
        if (document.querySelector(`[data-contact-id="${contact.id}"]`)) return;

        const contactEl = document.createElement('li');
        contactEl.className = 'contact';
        contactEl.dataset.contactId = contact.id;
        contactEl.dataset.contactName = contact.full_name;
        contactEl.dataset.contactEmail = contact.email || '';
        contactEl.dataset.contactPhone = contact.phone_number || '';
        contactEl.dataset.contactLastSeen = contact.last_seen || '';

        const lastMsg = contact.last_message;
        const isSent = lastMsg && lastMsg.sender_id === userId;
        const timeStr = lastMsg ? formatTime(lastMsg.timestamp) : '';

        // Optimized Avatar Rendering: Show initials first, fetch avatar in background
        contactEl.innerHTML = `
            <div class="contact-avatar" id="avatar-user-${contact.id}">
                <div class="avatar-initials">${getInitialsFromName(contact.full_name)}</div>
                ${contact.status === 'online' ? '<div class="online-indicator"></div>' : ''}
            </div>
            <div class="contact-info">
                <div class="contact-name">${contact.full_name}</div>
                <div class="contact-last-msg">
                    ${lastMsg ? (isSent ? 'You: ' : '') + truncateMessage(lastMsg.content, 20) : 'No messages yet'}
                </div>
            </div>
            <div class="contact-time">
                ${timeStr}
                ${contact.status !== 'online' ?
                `<span class="last-seen">last seen ${formatLastSeen(contact.last_seen)}</span>` : ''}
            </div>
        `;

        contactList.appendChild(contactEl);

        // Lazy load avatar
        const avatarDiv = contactEl.querySelector('.contact-avatar');
        avatarDiv.dataset.avatarId = contact.id;
        avatarDiv.dataset.avatarType = 'user';
        avatarObserver.observe(avatarDiv);

        // Pre-fetch/cache public key if bundled
        if (contact.public_key) {
            preFetchedPublicKeys.set(contact.id, contact.public_key);
        }
    });
}

// 54) Render Groups
function renderGroups(groups, isAppend = false) {
    if (!groupList) return;
    if (!isAppend) groupList.innerHTML = '';

    groups.forEach(group => {
        // Prevent duplicates
        if (document.querySelector(`[data-group-id="${group.id}"]`)) return;

        const groupEl = createGroupElement(group);
        groupList.appendChild(groupEl);

        // Setup lazy loading for group avatar
        const avatarDiv = groupEl.querySelector('.group-avatar');
        if (avatarDiv) avatarObserver.observe(avatarDiv);

        // Pre-fetch/cache group seed if bundled
        if (group.my_encrypted_seed) {
            preFetchedGroupSeeds.set(group.id, group.my_encrypted_seed);
        }
    });
}

// 55) Create Group Element
function createGroupElement(group) {
    const groupEl = document.createElement('li');
    groupEl.className = 'contact';
    groupEl.dataset.groupId = group.id;
    groupEl.dataset.groupName = group.name;
    groupEl.dataset.isAdmin = group.is_admin ? 'true' : 'false';

    const lastMsg = group.last_message;
    const isSent = lastMsg && lastMsg.sender_id === userId;
    const timeStr = lastMsg ? formatTime(lastMsg.timestamp) : '';
    const hasUnread = group.unread_count > 0;

    groupEl.innerHTML = `
        <div class="group-avatar ${hasUnread ? 'has-unread' : ''}" id="avatar-group-${group.id}" 
             data-avatar-id="${group.id}" data-avatar-type="group">
            <div class="avatar-initials">
                ${getInitialsFromName(group.name)}
            </div>
        </div>
        <div class="contact-info">
            <div class="contact-name-wrapper">
                <div class="contact-name">${escapeHtml(group.name)}</div>
                ${hasUnread ? `<div class="unread-badge">${group.unread_count}</div>` : ''}
            </div>
            <div class="contact-last-msg ${hasUnread ? 'unread' : ''}">
                ${lastMsg ?
            `<span class="sender-prefix">${isSent ? 'You: ' : `${escapeHtml(lastMsg.sender_name)}: `}</span>
                     <span class="message-content">${escapeHtml(truncateMessage(lastMsg.content, 20))}</span>` :
            '<span class="no-messages">No messages yet</span>'}
            </div>
            <div class="group-members">${group.member_count || 0} members</div>
        </div>
        <div class="contact-time">
            ${timeStr}
        </div>
    `;

    groupEl.setAttribute('tabindex', '0');

    // Fetch avatar asynchronously
    fetchAndSetAvatar(group.id, 'group', groupEl.querySelector('.group-avatar'));

    return groupEl;
}

// 56) Select Contact
function selectContact(contact, contactEl) {
    if (!contact && contactEl) {
        // Handle element-based selection (e.g., from server-rendered HTML or delegation)
        contact = {
            id: contactEl.dataset.contactId,
            full_name: contactEl.dataset.contactName,
            email: contactEl.dataset.contactEmail || '',
            phone_number: contactEl.dataset.contactPhone || '',
            avatar_base64: contactEl.querySelector('img')?.src.split(',')[1] || '',
            status: contactEl.querySelector('.online-indicator') ? 'online' : 'offline',
            last_seen: contactEl.dataset.contactLastSeen || '',
        };
    }

    resetCurrentSelections();

    currentFriend = {
        id: contact.id || contact._id,
        name: contact.full_name,
        email: contact.email,
        phone: contact.phone_number,
        avatar: contact.avatar_base64,
        isOnline: contact.status === 'online',
        lastSeen: contact.last_seen,
        type: 'contact'
    };

    updateChatHeader(currentFriend.name, currentFriend.isOnline ? 'Online' : `Last seen ${formatLastSeen(currentFriend.lastSeen)}`);
    updateChatAvatar(currentFriend.avatar, currentFriend.name, 'contact');

    if (contactEl) contactEl.classList.add('active');

    // Explicitly manage header visibility for contacts
    hideGroupManagement();
    if (clearChatBtn) clearChatBtn.style.display = 'flex';

    connectWebSocket();
    loadMessages();
    setTimeout(setupReadReceipts, 500);
    handleMobileView();
}

// 57) Select Group
function selectGroup(group, groupEl) {
    if (!group && groupEl) {
        // Handle element-based selection
        group = {
            id: groupEl.dataset.groupId,
            name: groupEl.dataset.groupName,
            avatar_base64: groupEl.querySelector('img')?.src.split(',')[1] || '',
            member_count: parseInt(groupEl.querySelector('.group-members')?.textContent) || 0,
            is_admin: groupEl.dataset.isAdmin === 'true',
        };
    }

    resetCurrentSelections();

    currentGroup = {
        id: group.id || group._id,
        name: group.name,
        avatar: group.avatar_base64,
        memberCount: group.member_count || 0,
        isAdmin: group.is_admin || false,
        type: 'group'
    };

    updateChatHeader(currentGroup.name, `Group • ${currentGroup.memberCount} members`);
    updateChatAvatar(currentGroup.avatar, currentGroup.name, 'group');

    // Explicitly manage header visibility for groups
    if (clearChatBtn) clearChatBtn.style.display = 'none';
    showGroupManagement(currentGroup.isAdmin);

    if (groupEl) groupEl.classList.add('active');
    connectWebSocket();
    loadMessages();
    setTimeout(setupReadReceipts, 500);
    handleMobileView();
}

// 58) Reset Current Selections
function resetCurrentSelections() {
    cleanupReadReceipts();
    if (chatSocket) {
        try { chatSocket.close(); } catch (e) { console.log('Error closing WebSocket:', e); }
    }

    currentFriend = null;
    currentGroup = null;
    hideGroupManagement();
    document.querySelectorAll('.contact').forEach(c => c.classList.remove('active'));
}

// 59) Reset Chat View
function resetChatView() {
    resetCurrentSelections();
    showWelcomeScreen();
    if (clearChatBtn) clearChatBtn.style.display = 'none';
}

// 60) Show Welcome Screen
function showWelcomeScreen() {
    chatBox.innerHTML = `
        <div class="welcome-container">
            <div class="welcome-illustration">
                <i class="fas fa-comments"></i>
            </div>
            <div class="welcome-title">Welcome to ChitChat!</div>
            <div class="welcome-subtitle">Select a contact or group from your list to start a conversation.</div>
        </div>
    `;

    chatName.textContent = 'Welcome to ChitChat!';
    chatStatus.textContent = 'Select a contact to start chatting';
    chatAvatar.innerHTML = '<div class="avatar-initials">CH</div>';
    chatAvatar.className = 'chat-header-avatar';
}

// ====================================================
// UTILITY AND HELPER FUNCTIONS (101-134)
// ====================================================

// ----------------------------------------------------
// 101) confirmDeleteGroup
// ----------------------------------------------------
async function confirmDeleteGroup() {
    if (!currentGroup) return;

    try {
        const response = await fetch('/groups/delete_group/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken(),
            },
            body: JSON.stringify({
                group_id: currentGroup.id
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Failed to delete group');
        }

        const data = await response.json();
        if (data.success) {
            // Remove group from UI
            const groupElement = document.querySelector(`[data-group-id="${currentGroup.id}"]`);
            if (groupElement) {
                groupElement.remove();
            }

            closeDeleteGroupModal();
            showSuccess(data.message || 'Group deleted successfully!');

            // Reset to welcome screen
            resetChatView();
        } else {
            throw new Error(data.error || 'Failed to delete group');
        }

    } catch (error) {
        console.error('Error deleting group:', error);
        showError(error.message || 'Failed to delete group');
    }
}

// ----------------------------------------------------
// 102) getMemberName
// ----------------------------------------------------
function getMemberName(memberId) {
    const member = currentGroupMembers.find(m => m.id === memberId);
    return member ? member.full_name : 'Unknown member';
}


// ----------------------------------------------------
// 111) showError
// ----------------------------------------------------
function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message';
    errorDiv.textContent = message;
    document.body.appendChild(errorDiv);
    setTimeout(() => errorDiv.remove(), 3000);
}

// ----------------------------------------------------
// 112) showSuccess
// ----------------------------------------------------
function showSuccess(message) {
    const successDiv = document.createElement('div');
    successDiv.className = 'success-message';
    successDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: var(--success);
        color: white;
        padding: 12px 20px;
        border-radius: 8px;
        z-index: 10000;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    `;
    successDiv.textContent = message;
    document.body.appendChild(successDiv);
    setTimeout(() => successDiv.remove(), 3000);
}

// Add these loading utility functions
function showLoading(message = 'Loading...') {
    // Create or get loading element
    let loadingEl = document.getElementById('loadingIndicator');
    if (!loadingEl) {
        loadingEl = document.createElement('div');
        loadingEl.id = 'loadingIndicator';
        loadingEl.style.cssText = `
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(0,0,0,0.8);
            color: white;
            padding: 20px;
            border-radius: 8px;
            z-index: 10000;
            display: none;
        `;
        document.body.appendChild(loadingEl);
    }
    loadingEl.textContent = message;
    loadingEl.style.display = 'block';
}

function hideLoading() {
    const loadingEl = document.getElementById('loadingIndicator');
    if (loadingEl) {
        loadingEl.style.display = 'none';
    }
}

// ====================================================
// UTILITY FUNCTIONS (111-130)
// ====================================================

// 111) Get CSRF Token
function getCSRFToken() {
    const cookieValue = document.cookie
        .split('; ')
        .find(row => row.startsWith('csrftoken='))
        ?.split('=')[1];
    return cookieValue || '';
}

// 112) Get Initials From Name
function getInitialsFromName(name) {
    if (!name) return "C";
    const parts = name.split(' ');
    let initials = parts[0].charAt(0).toUpperCase();
    if (parts.length > 1) initials += parts[parts.length - 1].charAt(0).toUpperCase();
    return initials || "C";
}

// 113) Format Time
function formatTime(timestamp) {
    try {
        const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
        return date.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true });
    } catch (e) {
        console.error('Error formatting time:', e);
        return '';
    }
}

// 114) Format Last Seen
function formatLastSeen(timestamp) {
    if (!timestamp) return 'a long time ago';
    try {
        const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
        const now = new Date();
        const diffMinutes = Math.floor((now - date) / (1000 * 60));

        if (diffMinutes < 1) return 'just now';
        if (diffMinutes < 60) return `${diffMinutes} min ago`;
        if (diffMinutes < 1440) return `${Math.floor(diffMinutes / 60)} hours ago`;

        return date.toLocaleDateString('en-IN', {
            day: 'numeric',
            month: 'short',
            year: (date.getFullYear() !== now.getFullYear()) ? 'numeric' : undefined
        });
    } catch (e) {
        console.error('Error formatting last seen:', e);
        return '';
    }
}

// 115) Format Date Divider
function formatDateDivider(date) {
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);

    if (date.toDateString() === today.toDateString()) return "Today";
    if (date.toDateString() === yesterday.toDateString()) return "Yesterday";

    return date.toLocaleDateString('en-IN', { month: 'short', day: 'numeric', year: 'numeric' });
}

// 116) Truncate Message
function truncateMessage(text, length) {
    if (!text) return '';
    return text.length > length ? text.substring(0, length) + '...' : text;
}

// 117) Escape HTML
function escapeHtml(unsafe) {
    if (!unsafe) return '';
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// 118) Play Notification Sound
function playNotificationSound() {
    const audio = new Audio('/static/notification.mp3');
    audio.play().catch(e => console.log('Audio play failed:', e));
}

// 119) Fetch and Set Avatar Asynchronously
async function fetchAndSetAvatar(id, type, container) {
    if (!id || !container) return;

    // Check cache first (Simple in-memory cache for the session)
    const cacheKey = `${type}_${id}`;
    if (keyCache.has(cacheKey)) {
        const base64 = keyCache.get(cacheKey);
        if (base64) renderAvatarToContainer(container, base64);
        return;
    }

    try {
        const url = `/avatar/${type}/${id}/`;
        const response = await fetch(url);
        if (response.ok) {
            const data = await response.json();
            if (data.avatar_base64) {
                keyCache.set(cacheKey, data.avatar_base64); // Reuse keyCache or use a new one
                renderAvatarToContainer(container, data.avatar_base64);
            }
        }
    } catch (error) {
        console.error(`Error fetching avatar for ${type} ${id}:`, error);
    }
}

function renderAvatarToContainer(container, base64) {
    if (!container || !base64) return;

    // Clear initials and add image
    const initials = container.querySelector('.avatar-initials, .avatar-initials-small');
    if (initials) initials.remove();

    // Remove existing img if any
    const existingImg = container.querySelector('img');
    if (existingImg) existingImg.remove();

    const img = document.createElement('img');
    img.src = `data:image/png;base64,${base64}`;
    img.style.opacity = '0';
    img.onload = () => { img.style.opacity = '1'; };
    img.style.transition = 'opacity 0.3s ease';

    container.prepend(img);
}

// 119) Handle Typing Start
function handleTypingStart() {
    if (!currentFriend && !currentGroup) return;

    clearTimeout(typingTimer);

    let typingData;
    if (currentFriend) {
        typingData = {
            type: "typing",
            sender_id: userId,
            receiver_id: currentFriend.id,
            is_typing: true
        };
    } else if (currentGroup) {
        typingData = {
            type: "group_typing",
            sender_id: userId,
            group_id: currentGroup.id,
            sender_name: userName,
            is_typing: true
        };
    }

    safeWebSocketSend(typingData);

    typingTimer = setTimeout(() => {
        typingData.is_typing = false;
        safeWebSocketSend(typingData);
    }, 2000);
}

// 120) Handle Key Press
function handleKeyPress(e) {
    if (e.key === 'Enter') {
        const isMobile = window.innerWidth <= 768;
        if (e.shiftKey || isMobile) {
            // Let the default behavior happen (new line)
            // But we still need to adjust height
            setTimeout(adjustInputHeight, 0);
        } else {
            e.preventDefault();
            sendMessage();
            resetInputHeight();
        }
    } else {
        handleTypingStart();
    }
}

// 121) Adjust Input Height (Auto-grow)
function adjustInputHeight() {
    if (!messageInput) return;

    // Reset height to get correct scrollHeight
    messageInput.style.height = '44px';

    // Set to scrollHeight
    const newHeight = Math.min(messageInput.scrollHeight, 150);
    messageInput.style.height = (newHeight) + 'px';

    // Show scrollbar only if max-height reached
    messageInput.style.overflowY = messageInput.scrollHeight > 150 ? 'auto' : 'hidden';

    // On mobile: sync chatBox padding-bottom with the actual input bar height
    if (window.innerWidth <= 768 && chatBox) {
        const inputBar = document.getElementById('chatInputBar');
        if (inputBar) {
            chatBox.style.paddingBottom = (inputBar.offsetHeight + 10) + 'px';
        }
    }
}

// 122) Reset Input Height
function resetInputHeight() {
    if (messageInput) {
        messageInput.style.height = '44px';
        messageInput.style.overflowY = 'hidden';
    }
}

// 123) Initialize Contact Scroll (Infinite Scroll for Sidebar)
function initializeContactScroll() {
    const contactsTab = document.getElementById('contacts-tab');
    if (!contactsTab) return;

    contactsTab.addEventListener('scroll', () => {
        const { scrollTop, scrollHeight, clientHeight } = contactsTab;
        if (scrollTop + clientHeight >= scrollHeight - 50) {
            if (hasMoreContacts && !isContactLoading) {
                console.log('Loading more contacts...');
                loadContacts(true);
            }
        }
    });
}

// 124) Initialize Group Scroll (Infinite Scroll for Sidebar)
function initializeGroupScroll() {
    const groupsTab = document.getElementById('groups-tab');
    if (!groupsTab) return;

    groupsTab.addEventListener('scroll', () => {
        const { scrollTop, scrollHeight, clientHeight } = groupsTab;
        if (scrollTop + clientHeight >= scrollHeight - 50) {
            if (hasMoreGroups && !isGroupLoading) {
                console.log('Loading more groups...');
                loadGroups(true);
            }
        }
    });
}

