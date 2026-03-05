// ====================================================
// GROUP CREATION AND MANAGEMENT (101-120)
// ====================================================

// 100) Global variables for group management pagination
let createGroupOffset = 0;
const createGroupLimit = 20;
let hasMoreCreateGroup = true;
let isCreateGroupLoading = false;

let addMembersOffset = 0;
const addMembersLimit = 20;
let hasMoreAddMembers = true;
let isAddMembersLoading = false;

let viewMembersOffset = 0;
const viewMembersLimit = 20;
let hasMoreViewMembers = true;
let isViewMembersLoading = false;

// 101) Create Group
async function createGroup() {
  const groupName = document.getElementById('groupName').value.trim();
  const selectedMembers = Array.from(document.querySelectorAll('#groupMembers input:checked'))
    .map(checkbox => checkbox.value);

  if (!groupName || selectedMembers.length === 0) {
    showError('Please enter group name and select members.');
    return;
  }

  try {
    const groupId = await createGroupWithMemberEncryption(groupName, selectedMembers);

    const newGroup = {
      id: groupId,
      name: groupName,
      avatar_base64: null,
      member_count: selectedMembers.length + 1,
      last_message: null,
      is_admin: true,
      encryption_enabled: true
    };

    const groupEl = createGroupElement(newGroup);
    groupList.prepend(groupEl);

    closeCreateGroupModal();
    showSuccess('Encrypted group created successfully!');
    selectGroup(newGroup, groupEl);
  } catch (error) {
    console.error('Error creating group:', error);
    showError(error.message || 'Failed to create encrypted group');
  }
}

// 102) Open Create Group Modal
async function openCreateGroupModal(isAppend = false) {
  if (isCreateGroupLoading || (!hasMoreCreateGroup && isAppend)) return;

  if (!isAppend) {
    createGroupOffset = 0;
    hasMoreCreateGroup = true;
    const groupMembersContainer = document.getElementById('groupMembers');
    if (groupMembersContainer) groupMembersContainer.innerHTML = '';
  }

  isCreateGroupLoading = true;
  try {
    const response = await fetch(`/get_contacts/?offset=${createGroupOffset}&limit=${createGroupLimit}`);
    if (!response.ok) throw new Error('Failed to load contacts');

    const data = await response.json();
    hasMoreCreateGroup = data.has_more;
    if (hasMoreCreateGroup) {
      createGroupOffset += data.contacts.length;
    }

    populateGroupMembersList(data.contacts, isAppend);

    if (!isAppend) {
      const modal = document.getElementById('createGroupModal');
      if (modal) modal.style.display = 'flex';

      setTimeout(() => {
        const groupNameInput = document.getElementById('groupName');
        if (groupNameInput) groupNameInput.focus();

        // Initialize scroll listener once
        initializeModalScroll('groupMembers', () => openCreateGroupModal(true));
      }, 100);
    }
  } catch (error) {
    console.error('Error loading contacts for group creation:', error);
    if (!isAppend) showError('Failed to load contacts. Please try again.');
  } finally {
    isCreateGroupLoading = false;
  }
}

// 103) Close Create Group Modal
function closeCreateGroupModal() {
  const modal = document.getElementById('createGroupModal');
  if (modal) modal.style.display = 'none';

  document.getElementById('groupName').value = '';
  document.getElementById('groupMembersSearch').value = '';
  const groupMembersContainer = document.getElementById('groupMembers');
  if (groupMembersContainer) groupMembersContainer.innerHTML = '';
}

// 104) Populate Group Members List
function populateGroupMembersList(contacts, isAppend = false) {
  const groupMembersContainer = document.getElementById('groupMembers');
  if (!groupMembersContainer) return;

  if (!isAppend) groupMembersContainer.innerHTML = '';

  if ((!contacts || contacts.length === 0) && !isAppend) {
    groupMembersContainer.innerHTML = '<div class="no-contacts">No contacts available</div>';
    return;
  }

  contacts.forEach(contact => {
    // Prevent duplicates
    if (document.getElementById(`member-${contact.id}`)) return;

    const memberDiv = document.createElement('div');
    memberDiv.className = 'member-checkbox';

    memberDiv.innerHTML = `
            <div class="member-checkbox-content">
                <div class="member-info">
                    <div class="member-avatar-small" id="avatar-create-${contact.id}">
                        <div class="avatar-initials-small">${getInitialsFromName(contact.full_name)}</div>
                    </div>
                    <span class="member-name">${contact.full_name}</span>
                </div>
                <div class="member-checkbox-control">
                    <input type="checkbox" id="member-${contact.id}" value="${contact.id}">
                </div>
            </div>
        `;

    memberDiv.addEventListener('click', function (e) {
      if (e.target.type !== 'checkbox') {
        const checkbox = this.querySelector('input[type="checkbox"]');
        checkbox.checked = !checkbox.checked;
        updateSelectedCount();
      }
    });

    const checkbox = memberDiv.querySelector('input[type="checkbox"]');
    checkbox.addEventListener('change', updateSelectedCount);

    groupMembersContainer.appendChild(memberDiv);

    // Fetch avatar on-demand
    fetchAndSetAvatar(contact.id, 'user', document.getElementById(`avatar-create-${contact.id}`));
  });

  updateSelectedCount();
}

// 105) Filter Group Members
function filterGroupMembers() {
  const searchTerm = document.getElementById('groupMembersSearch').value.toLowerCase().trim();
  const memberCheckboxes = document.querySelectorAll('.member-checkbox');

  memberCheckboxes.forEach(member => {
    const memberName = member.querySelector('.member-name').textContent.toLowerCase();
    member.style.display = memberName.includes(searchTerm) ? 'flex' : 'none';
  });
}

// 106) Update Selected Count
function updateSelectedCount() {
  const selectedCount = document.querySelectorAll('#groupMembers input:checked').length;
  const countElement = document.getElementById('selectedCount');
  if (countElement) countElement.textContent = `${selectedCount} member${selectedCount !== 1 ? 's' : ''} selected`;
}

// 107) Update Contact Last Message
function updateContactLastMessage(contactId, message, isSent, timestamp) {
  const contacts = document.querySelectorAll('#contactList .contact');

  contacts.forEach(contact => {
    if (contact.dataset.contactId === contactId) {
      const lastMsgEl = contact.querySelector('.contact-last-msg');
      const timeEl = contact.querySelector('.contact-time');

      if (lastMsgEl && timeEl) {
        lastMsgEl.textContent = isSent ? `You: ${truncateMessage(message, 20)}` : truncateMessage(message, 20);
        timeEl.innerHTML = formatTime(timestamp);
        contactList.prepend(contact);
      }
    }
  });
}

// 108) Update Group Last Message
function updateGroupLastMessage(groupId, message, senderName, timestamp) {
  const groups = document.querySelectorAll('#groupList .contact');

  groups.forEach(group => {
    if (group.dataset.groupId === groupId) {
      const lastMsgEl = group.querySelector('.contact-last-msg');
      const timeEl = group.querySelector('.contact-time');

      if (lastMsgEl && timeEl) {
        const isYou = senderName === 'You';
        lastMsgEl.textContent = isYou ? `You: ${truncateMessage(message, 20)}` : `${senderName}: ${truncateMessage(message, 20)}`;
        timeEl.innerHTML = formatTime(timestamp);
        groupList.prepend(group);
      }
    }
  });
}

// 109) Confirm Clear Chat
function confirmClearChat() {
  clearChat();
  closeClearChatModal();
}

// 110) Clear Chat
async function clearChat() {
  if (!currentFriend && !currentGroup) {
    showError('Please select a chat to clear');
    return;
  }

  try {
    let endpoint, payload;

    if (currentGroup) {
      endpoint = '/groups/clear_chat/';
      payload = { group_id: currentGroup.id };
    } else if (currentFriend) {
      endpoint = '/chat/clear_chat/';
      payload = { user_id: currentFriend.id };
    }

    const wsData = { type: currentGroup ? "clear_group_chat" : "clear_chat" };
    if (currentGroup) wsData.group_id = currentGroup.id;
    else if (currentFriend) wsData.receiver_id = currentFriend.id;

    const wsSuccess = safeWebSocketSend(wsData);

    if (!wsSuccess) {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        if (response.status === 403) throw new Error('You do not have permission to clear this group chat');
        else if (response.status === 404) throw new Error('Chat not found');
        else throw new Error('Failed to clear chat');
      }
    }

    chatBox.innerHTML = '<div class="no-messages">No messages yet. Start the conversation!</div>';

    if (currentFriend) updateContactLastMessage(currentFriend.id, '', false, new Date());
    else if (currentGroup) updateGroupLastMessage(currentGroup.id, '', '', new Date());

    showSuccess('Chat cleared successfully!');
  } catch (error) {
    console.error('Error clearing chat:', error);
    if (error.message.includes('permission') || error.message.includes('admin')) {
      showError('Only group admins can clear group chat');
    } else {
      showError(error.message || 'Failed to clear chat');
    }
  }
}



// ----------------------------------------------------
// 64) switchToGroupsTab
// ----------------------------------------------------
function switchToGroupsTab() {
  // Switch to groups tab
  const groupsTabBtn = document.querySelector('.tab-btn[data-tab="groups"]');
  const groupsTabContent = document.getElementById('groups-tab');
  const contactsTabBtn = document.querySelector('.tab-btn[data-tab="contacts"]');
  const contactsTabContent = document.getElementById('contacts-tab');

  if (groupsTabBtn && groupsTabContent) {
    contactsTabBtn.classList.remove('active');
    contactsTabContent.classList.remove('active');
    groupsTabBtn.classList.add('active');
    groupsTabContent.classList.add('active');
    currentTab = 'groups';
  }
}

// ----------------------------------------------------

// ----------------------------------------------------
// 67) openViewMembersModal
// ----------------------------------------------------// 67) openViewMembersModal
async function openViewMembersModal(isAppend = false) {
  if (!currentGroup) return;

  if (isViewMembersLoading || (!hasMoreViewMembers && isAppend)) return;

  if (!isAppend) {
    viewMembersOffset = 0;
    hasMoreViewMembers = true;
    const container = document.getElementById('membersList');
    if (container) container.innerHTML = '';
  }

  isViewMembersLoading = true;
  try {
    const response = await fetch('/groups/get_members/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      },
      body: JSON.stringify({
        group_id: currentGroup.id,
        offset: viewMembersOffset,
        limit: viewMembersLimit
      })
    });

    if (!response.ok) throw new Error('Failed to load group members');

    const data = await response.json();
    if (data.success) {
      hasMoreViewMembers = data.has_more;
      if (hasMoreViewMembers) {
        viewMembersOffset += data.members.length;
      }

      currentGroupMembers = isAppend ? [...currentGroupMembers, ...data.members] : data.members;
      populateMembersList(data.members, 'membersList', isAppend);

      if (!isAppend) {
        const modal = document.getElementById('viewMembersModal');
        if (modal) modal.style.display = 'flex';

        setTimeout(() => {
          initializeModalScroll('membersList', () => openViewMembersModal(true));
        }, 100);
      }
    } else {
      throw new Error(data.error || 'Failed to load group members');
    }
  } catch (error) {
    console.error('Error loading group members:', error);
    if (!isAppend) showError('Failed to load group members');
  } finally {
    isViewMembersLoading = false;
  }
}

// ----------------------------------------------------
// 68) closeViewMembersModal
// ----------------------------------------------------
function closeViewMembersModal() {
  const modal = document.getElementById('viewMembersModal');
  if (modal) modal.style.display = 'none';
}

// ----------------------------------------------------
// 69) openAddMembersModal
// ----------------------------------------------------// 69) openAddMembersModal
async function openAddMembersModal(isAppend = false) {
  if (!currentGroup) return;

  if (isAddMembersLoading || (!hasMoreAddMembers && isAppend)) return;

  if (!isAppend) {
    addMembersOffset = 0;
    hasMoreAddMembers = true;
    const container = document.getElementById('availableMembersList');
    if (container) container.innerHTML = '';
  }

  isAddMembersLoading = true;
  try {
    const response = await fetch('/groups/available_contacts/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      },
      body: JSON.stringify({
        group_id: currentGroup.id,
        offset: addMembersOffset,
        limit: addMembersLimit
      })
    });

    if (!response.ok) throw new Error('Failed to load contacts');

    const data = await response.json();
    if (data.success) {
      hasMoreAddMembers = data.has_more;
      if (hasMoreAddMembers) {
        addMembersOffset += data.available_contacts.length;
      }

      availableContacts = isAppend ? [...availableContacts, ...data.available_contacts] : data.available_contacts;
      populateAvailableMembersList(data.available_contacts, isAppend);

      if (!isAppend) {
        const modal = document.getElementById('addMembersModal');
        if (modal) modal.style.display = 'flex';

        setTimeout(() => {
          initializeModalScroll('availableMembersList', () => openAddMembersModal(true));
        }, 100);
      }
    } else {
      throw new Error(data.error || 'Failed to load contacts');
    }
  } catch (error) {
    console.error('Error loading available contacts:', error);
    if (!isAppend) showError('Failed to load available contacts');
  } finally {
    isAddMembersLoading = false;
  }
}

// ----------------------------------------------------
// 70) closeAddMembersModal
// ----------------------------------------------------
function closeAddMembersModal() {
  const modal = document.getElementById('addMembersModal');
  if (modal) modal.style.display = 'none';

  // Reset search
  const searchInput = document.getElementById('addMembersSearch');
  if (searchInput) searchInput.value = '';
}

// ====================================================
// ADVANCED GROUP MANAGEMENT (71-100)
// ====================================================

// ----------------------------------------------------
// 71) openRemoveMembersModal
// ----------------------------------------------------
async function openRemoveMembersModal() {
  if (!currentGroup) return;

  try {
    // Reset selection
    selectedMembersForRemoval = [];

    // Get group members
    const response = await fetch('/groups/get_members/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      },
      body: JSON.stringify({
        group_id: currentGroup.id
      })
    });

    if (!response.ok) throw new Error('Failed to load members');

    const data = await response.json();
    if (data.success) {
      // Filter out current user and other admins
      const removableMembers = data.members.filter(member =>
        member.id !== userId && !member.is_admin
      );

      populateRemoveMembersList(removableMembers);
      updateRemoveMembersSelectedCount();

      const modal = document.getElementById('removeMembersModal');
      if (modal) modal.style.display = 'flex';
    } else {
      throw new Error(data.error || 'Failed to load members');
    }

  } catch (error) {
    console.error('Error loading members for removal:', error);
    showError('Failed to load members');
  }
}

// ----------------------------------------------------
// 72) closeRemoveMembersModal
// ----------------------------------------------------
function closeRemoveMembersModal() {
  const modal = document.getElementById('removeMembersModal');
  if (modal) modal.style.display = 'none';

  // Reset search and selection
  const searchInput = document.getElementById('removeMembersSearch');
  if (searchInput) searchInput.value = '';

  selectedMembersForRemoval = [];
}

// ----------------------------------------------------
// 73) openMakeAdminModal
// ----------------------------------------------------
async function openMakeAdminModal() {
  if (!currentGroup) return;

  try {
    // Reset selection
    selectedMembersForAdmin = [];

    // Get group members
    const response = await fetch('/groups/get_members/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      },
      body: JSON.stringify({
        group_id: currentGroup.id
      })
    });

    if (!response.ok) throw new Error('Failed to load members');

    const data = await response.json();
    if (data.success) {
      // Filter out current user and existing admins
      const eligibleMembers = data.members.filter(member =>
        member.id !== userId && !member.is_admin
      );

      populateMakeAdminList(eligibleMembers);
      updateMakeAdminSelectedCount();

      const modal = document.getElementById('makeAdminModal');
      if (modal) modal.style.display = 'flex';
    } else {
      throw new Error(data.error || 'Failed to load members');
    }

  } catch (error) {
    console.error('Error loading members for admin promotion:', error);
    showError('Failed to load members');
  }
}

// ----------------------------------------------------
// 74) closeMakeAdminModal
// ----------------------------------------------------
function closeMakeAdminModal() {
  const modal = document.getElementById('makeAdminModal');
  if (modal) modal.style.display = 'none';

  // Reset search and selection
  const searchInput = document.getElementById('makeAdminSearch');
  if (searchInput) searchInput.value = '';

  selectedMembersForAdmin = [];
}

// ----------------------------------------------------
// 75) openRemoveAdminModal
// ----------------------------------------------------
async function openRemoveAdminModal() {
  if (!currentGroup) return;

  try {
    // Reset selection
    selectedAdminsForRemoval = [];

    // Get group members
    const response = await fetch('/groups/get_members/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      },
      body: JSON.stringify({
        group_id: currentGroup.id
      })
    });

    if (!response.ok) throw new Error('Failed to load members');

    const data = await response.json();
    if (data.success) {
      // Filter to get only admins (excluding current user)
      const adminMembers = data.members.filter(member =>
        member.is_admin && member.id !== userId
      );

      populateRemoveAdminList(adminMembers);
      updateRemoveAdminSelectedCount();

      const modal = document.getElementById('removeAdminModal');
      if (modal) modal.style.display = 'flex';
    } else {
      throw new Error(data.error || 'Failed to load members');
    }

  } catch (error) {
    console.error('Error loading admins for removal:', error);
    showError('Failed to load admins');
  }
}

// ----------------------------------------------------
// 76) closeRemoveAdminModal
// ----------------------------------------------------
function closeRemoveAdminModal() {
  const modal = document.getElementById('removeAdminModal');
  if (modal) modal.style.display = 'none';

  // Reset search and selection
  const searchInput = document.getElementById('removeAdminSearch');
  if (searchInput) searchInput.value = '';

  selectedAdminsForRemoval = [];
}

// ----------------------------------------------------
// 77) openLeaveGroupModal
// ----------------------------------------------------
function openLeaveGroupModal() {
  if (!currentGroup) return;

  // Set warning message based on user role
  const warningElement = document.getElementById('leaveGroupWarning');
  if (warningElement) {
    if (currentGroup.isAdmin) {
      warningElement.textContent = 'You are the group admin. If you leave, the group will be deleted unless you transfer admin rights first.';
    } else {
      warningElement.textContent = 'You will no longer have access to this group or its messages.';
    }
  }

  const modal = document.getElementById('leaveGroupModal');
  if (modal) modal.style.display = 'flex';
}

// ----------------------------------------------------
// 78) closeLeaveGroupModal
// ----------------------------------------------------
function closeLeaveGroupModal() {
  const modal = document.getElementById('leaveGroupModal');
  if (modal) modal.style.display = 'none';
}

// ----------------------------------------------------
// 79) openDeleteGroupModal
// ----------------------------------------------------
function openDeleteGroupModal() {
  const modal = document.getElementById('deleteGroupModal');
  if (modal) modal.style.display = 'flex';
}

// ----------------------------------------------------
// 80) closeDeleteGroupModal
// ----------------------------------------------------
function closeDeleteGroupModal() {
  const modal = document.getElementById('deleteGroupModal');
  if (modal) modal.style.display = 'none';
}

// ----------------------------------------------------
// 81) populateMembersList
// ----------------------------------------------------// 81) populateMembersList
function populateMembersList(members, containerId, isAppend = false) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!isAppend) container.innerHTML = '';

  if ((!members || members.length === 0) && !isAppend) {
    container.innerHTML = '<div class="no-members">No members found</div>';
    return;
  }

  members.forEach(member => {
    // Prevent duplicates
    if (container.querySelector(`[data-member-id="${member.id}"]`)) return;

    const memberDiv = document.createElement('div');
    memberDiv.className = 'member-checkbox-item';
    memberDiv.dataset.memberId = member.id;

    let roleText = member.is_admin ? 'Admin' : 'Member';
    if (member.id === userId) roleText = 'You';

    memberDiv.innerHTML = `
      <div class="member-checkbox-content">
        <div class="member-info">
          <div class="member-avatar-small" id="avatar-member-${member.id}">
             <div class="avatar-initials-small">${getInitialsFromName(member.full_name)}</div>
          </div>
          <div class="member-details">
            <div class="member-name">${member.full_name}</div>
            <div class="member-role">${roleText}</div>
          </div>
        </div>
      </div>
    `;

    container.appendChild(memberDiv);

    // Fetch avatar on-demand
    fetchAndSetAvatar(member.id, 'user', document.getElementById(`avatar-member-${member.id}`));
  });
}

// 81b) Initialize Modal Scroll
function initializeModalScroll(containerId, callback) {
  const container = document.getElementById(containerId);
  if (!container) return;

  // Remove existing listener to prevent stacking
  container.onscroll = null;

  container.addEventListener('scroll', () => {
    const { scrollTop, scrollHeight, clientHeight } = container;
    if (scrollTop + clientHeight >= scrollHeight - 30) {
      callback();
    }
  });
}

// ----------------------------------------------------
// 82) populateAvailableMembersList
// ----------------------------------------------------// 82) populateAvailableMembersList
function populateAvailableMembersList(contacts, isAppend = false) {
  const container = document.getElementById('availableMembersList');
  if (!container) return;

  if (!isAppend) container.innerHTML = '';

  if ((!contacts || contacts.length === 0) && !isAppend) {
    container.innerHTML = '<div class="no-contacts">No contacts available to add</div>';
    return;
  }

  contacts.forEach(contact => {
    // Prevent duplicates
    if (container.querySelector(`[value="${contact.id}"]`)) return;

    const contactDiv = document.createElement('div');
    contactDiv.className = 'available-member-item';

    contactDiv.innerHTML = `
      <div class="member-info">
        <div class="member-avatar-small" id="avatar-available-${contact.id}">
           <div class="avatar-initials-small">${getInitialsFromName(contact.full_name)}</div>
        </div>
        <div class="member-details">
          <div class="member-name">${contact.full_name}</div>
        </div>
      </div>
      <input type="checkbox" class="available-member-checkbox" value="${contact.id}">
    `;

    container.appendChild(contactDiv);

    // Fetch avatar on-demand
    fetchAndSetAvatar(contact.id, 'user', document.getElementById(`avatar-available-${contact.id}`));
  });
}

// ----------------------------------------------------
// 83) populateRemoveMembersList
// ----------------------------------------------------
function populateRemoveMembersList(members, containerId = 'removeMembersList') {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = '';

  if (!members || members.length === 0) {
    container.innerHTML = '<div class="no-members">No eligible members found</div>';
    return;
  }

  members.forEach(member => {
    const memberDiv = document.createElement('div');
    memberDiv.className = 'member-checkbox-item';
    memberDiv.dataset.memberId = member.id;

    const isSelected = selectedMembersForRemoval.includes(member.id);

    memberDiv.innerHTML = `
      <div class="member-checkbox-content">
        <div class="member-info">
          <div class="member-avatar-small" id="avatar-remove-${member.id}">
            ${member.avatar_base64 ?
        `<img src="data:image/png;base64,${member.avatar_base64}" alt="${member.full_name}">` :
        `<div class="avatar-initials-small">${getInitialsFromName(member.full_name)}</div>`}
          </div>
          <div class="member-details">
            <div class="member-name">${member.full_name}</div>
            <div class="member-role">Member</div>
          </div>
        </div>
        <div class="member-checkbox-control">
          <input type="checkbox" class="remove-member-checkbox" value="${member.id}" 
                 ${isSelected ? 'checked' : ''} 
                 onchange="toggleMemberForRemoval('${member.id}')">
        </div>
      </div>
    `;

    // Add click event for the entire row
    memberDiv.addEventListener('click', function (e) {
      if (e.target.type !== 'checkbox') {
        const checkbox = this.querySelector('.remove-member-checkbox');
        checkbox.checked = !checkbox.checked;
        toggleMemberForRemoval(member.id);
      }
    });

    container.appendChild(memberDiv);

    // Fetch avatar on-demand
    fetchAndSetAvatar(member.id, 'user', document.getElementById(`avatar-remove-${member.id}`));
  });
}

// ----------------------------------------------------
// 84) populateMakeAdminList
// ----------------------------------------------------
function populateMakeAdminList(members, containerId = 'makeAdminList') {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = '';

  if (!members || members.length === 0) {
    container.innerHTML = '<div class="no-members">No eligible members found</div>';
    return;
  }

  members.forEach(member => {
    const memberDiv = document.createElement('div');
    memberDiv.className = 'member-checkbox-item';
    memberDiv.dataset.memberId = member.id;

    const isSelected = selectedMembersForAdmin.includes(member.id);

    memberDiv.innerHTML = `
      <div class="member-checkbox-content">
        <div class="member-info">
          <div class="member-avatar-small" id="avatar-make-admin-${member.id}">
            ${member.avatar_base64 ?
        `<img src="data:image/png;base64,${member.avatar_base64}" alt="${member.full_name}">` :
        `<div class="avatar-initials-small">${getInitialsFromName(member.full_name)}</div>`}
          </div>
          <div class="member-details">
            <div class="member-name">${member.full_name}</div>
            <div class="member-role">Member</div>
          </div>
        </div>
        <div class="member-checkbox-control">
          <input type="checkbox" class="make-admin-checkbox" value="${member.id}" 
                 ${isSelected ? 'checked' : ''} 
                 onchange="toggleMemberForAdmin('${member.id}')">
        </div>
      </div>
    `;

    // Add click event for the entire row
    memberDiv.addEventListener('click', function (e) {
      if (e.target.type !== 'checkbox') {
        const checkbox = this.querySelector('.make-admin-checkbox');
        checkbox.checked = !checkbox.checked;
        toggleMemberForAdmin(member.id);
      }
    });

    container.appendChild(memberDiv);

    // Fetch avatar on-demand
    fetchAndSetAvatar(member.id, 'user', document.getElementById(`avatar-make-admin-${member.id}`));
  });
}

// ----------------------------------------------------
// 85) populateRemoveAdminList
// ----------------------------------------------------
function populateRemoveAdminList(members, containerId = 'removeAdminList') {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = '';

  if (!members || members.length === 0) {
    container.innerHTML = '<div class="no-members">No other admins found</div>';
    return;
  }

  members.forEach(member => {
    const memberDiv = document.createElement('div');
    memberDiv.className = 'member-checkbox-item';
    memberDiv.dataset.memberId = member.id;

    const isSelected = selectedAdminsForRemoval.includes(member.id);

    memberDiv.innerHTML = `
      <div class="member-checkbox-content">
        <div class="member-info">
          <div class="member-avatar-small" id="avatar-remove-admin-${member.id}">
            ${member.avatar_base64 ?
        `<img src="data:image/png;base64,${member.avatar_base64}" alt="${member.full_name}">` :
        `<div class="avatar-initials-small">${getInitialsFromName(member.full_name)}</div>`}
          </div>
          <div class="member-details">
            <div class="member-name">${member.full_name}</div>
            <div class="member-role">Admin</div>
          </div>
        </div>
        <div class="member-checkbox-control">
          <input type="checkbox" class="remove-admin-checkbox" value="${member.id}" 
                 ${isSelected ? 'checked' : ''} 
                 onchange="toggleAdminForRemoval('${member.id}')">
        </div>
      </div>
    `;

    // Add click event for the entire row
    memberDiv.addEventListener('click', function (e) {
      if (e.target.type !== 'checkbox') {
        const checkbox = this.querySelector('.remove-admin-checkbox');
        checkbox.checked = !checkbox.checked;
        toggleAdminForRemoval(member.id);
      }
    });

    container.appendChild(memberDiv);

    // Fetch avatar on-demand
    fetchAndSetAvatar(member.id, 'user', document.getElementById(`avatar-remove-admin-${member.id}`));
  });
}

// ----------------------------------------------------
// 86) filterAvailableMembers
// ----------------------------------------------------
function filterAvailableMembers() {
  const searchTerm = document.getElementById('addMembersSearch').value.toLowerCase().trim();
  const availableMembers = document.querySelectorAll('.available-member-item');

  availableMembers.forEach(member => {
    const memberName = member.querySelector('.member-name').textContent.toLowerCase();
    if (memberName.includes(searchTerm)) {
      member.style.display = 'flex';
    } else {
      member.style.display = 'none';
    }
  });
}

// ----------------------------------------------------
// 87) filterRemoveMembers
// ----------------------------------------------------
function filterRemoveMembers() {
  const searchTerm = document.getElementById('removeMembersSearch').value.toLowerCase().trim();
  const memberCheckboxes = document.querySelectorAll('#removeMembersList .member-checkbox-item');

  memberCheckboxes.forEach(member => {
    const memberName = member.querySelector('.member-name').textContent.toLowerCase();
    if (memberName.includes(searchTerm)) {
      member.style.display = 'flex';
    } else {
      member.style.display = 'none';
    }
  });
}

// ----------------------------------------------------
// 88) filterMakeAdminMembers
// ----------------------------------------------------
function filterMakeAdminMembers() {
  const searchTerm = document.getElementById('makeAdminSearch').value.toLowerCase().trim();
  const memberCheckboxes = document.querySelectorAll('#makeAdminList .member-checkbox-item');

  memberCheckboxes.forEach(member => {
    const memberName = member.querySelector('.member-name').textContent.toLowerCase();
    if (memberName.includes(searchTerm)) {
      member.style.display = 'flex';
    } else {
      member.style.display = 'none';
    }
  });
}

// ----------------------------------------------------
// 89) filterRemoveAdminMembers
// ----------------------------------------------------
function filterRemoveAdminMembers() {
  const searchTerm = document.getElementById('removeAdminSearch').value.toLowerCase().trim();
  const memberCheckboxes = document.querySelectorAll('#removeAdminList .member-checkbox-item');

  memberCheckboxes.forEach(member => {
    const memberName = member.querySelector('.member-name').textContent.toLowerCase();
    if (memberName.includes(searchTerm)) {
      member.style.display = 'flex';
    } else {
      member.style.display = 'none';
    }
  });
}

// ----------------------------------------------------
// 90) toggleMemberForRemoval
// ----------------------------------------------------
function toggleMemberForRemoval(memberId) {
  const checkbox = document.querySelector(`.remove-member-checkbox[value="${memberId}"]`);

  if (checkbox.checked) {
    // Add to selection if not already there
    if (!selectedMembersForRemoval.includes(memberId)) {
      selectedMembersForRemoval.push(memberId);
    }
  } else {
    // Remove from selection
    selectedMembersForRemoval = selectedMembersForRemoval.filter(id => id !== memberId);
  }

  updateRemoveMembersSelectedCount();

  // Visual feedback
  const memberDiv = document.querySelector(`.member-checkbox-item[data-member-id="${memberId}"]`);
  if (memberDiv) {
    if (checkbox.checked) {
      memberDiv.style.background = '#e8f0fe';
      memberDiv.classList.add('selected');
    } else {
      memberDiv.style.background = '';
      memberDiv.classList.remove('selected');
    }
  }
}

// ====================================================
// GROUP ACTION FUNCTIONS (91-120)
// ====================================================

// ----------------------------------------------------
// 91) toggleMemberForAdmin
// ----------------------------------------------------
function toggleMemberForAdmin(memberId) {
  const checkbox = document.querySelector(`.make-admin-checkbox[value="${memberId}"]`);

  if (checkbox.checked) {
    // Add to selection if not already there
    if (!selectedMembersForAdmin.includes(memberId)) {
      selectedMembersForAdmin.push(memberId);
    }
  } else {
    // Remove from selection
    selectedMembersForAdmin = selectedMembersForAdmin.filter(id => id !== memberId);
  }

  updateMakeAdminSelectedCount();

  // Visual feedback
  const memberDiv = document.querySelector(`.member-checkbox-item[data-member-id="${memberId}"]`);
  if (memberDiv) {
    if (checkbox.checked) {
      memberDiv.style.background = '#e8f0fe';
      memberDiv.classList.add('selected');
    } else {
      memberDiv.style.background = '';
      memberDiv.classList.remove('selected');
    }
  }
}

// ----------------------------------------------------
// 92) toggleAdminForRemoval
// ----------------------------------------------------
function toggleAdminForRemoval(memberId) {
  const checkbox = document.querySelector(`.remove-admin-checkbox[value="${memberId}"]`);

  if (checkbox.checked) {
    // Add to selection if not already there
    if (!selectedAdminsForRemoval.includes(memberId)) {
      selectedAdminsForRemoval.push(memberId);
    }
  } else {
    // Remove from selection
    selectedAdminsForRemoval = selectedAdminsForRemoval.filter(id => id !== memberId);
  }

  updateRemoveAdminSelectedCount();

  // Visual feedback
  const memberDiv = document.querySelector(`.member-checkbox-item[data-member-id="${memberId}"]`);
  if (memberDiv) {
    if (checkbox.checked) {
      memberDiv.style.background = '#e8f0fe';
      memberDiv.classList.add('selected');
    } else {
      memberDiv.style.background = '';
      memberDiv.classList.remove('selected');
    }
  }
}

// ----------------------------------------------------
// 93) updateRemoveMembersSelectedCount
// ----------------------------------------------------
function updateRemoveMembersSelectedCount() {
  const countElement = document.getElementById('removeMembersSelectedCount');
  if (countElement) {
    const count = selectedMembersForRemoval.length;
    countElement.textContent = `${count} member${count !== 1 ? 's' : ''} selected for removal`;
  }
}

// ----------------------------------------------------
// 94) updateMakeAdminSelectedCount
// ----------------------------------------------------
function updateMakeAdminSelectedCount() {
  const countElement = document.getElementById('makeAdminSelectedCount');
  if (countElement) {
    const count = selectedMembersForAdmin.length;
    countElement.textContent = `${count} member${count !== 1 ? 's' : ''} selected for admin promotion`;

    // Update button text
    const confirmBtn = document.querySelector('#makeAdminModal .confirm');
    if (confirmBtn) {
      confirmBtn.textContent = count > 0 ? `Make ${count} Admin${count > 1 ? 's' : ''}` : 'Make Admins';
    }
  }
}

// ----------------------------------------------------
// 95) updateRemoveAdminSelectedCount
// ----------------------------------------------------
function updateRemoveAdminSelectedCount() {
  const countElement = document.getElementById('removeAdminSelectedCount');
  if (countElement) {
    const count = selectedAdminsForRemoval.length;
    countElement.textContent = `${count} admin${count !== 1 ? 's' : ''} selected for removal`;

    // Update button text
    const confirmBtn = document.querySelector('#removeAdminModal .confirm');
    if (confirmBtn) {
      confirmBtn.textContent = count > 0 ? `Remove ${count} Admin${count > 1 ? 's' : ''}` : 'Remove Admin';
    }
  }
}

// ----------------------------------------------------
// 96) addSelectedMembers
// ----------------------------------------------------

async function addSelectedMembers() {
  if (!currentGroup) {
    showError('No group selected');
    return;
  }

  const selectedCheckboxes = document.querySelectorAll('.available-member-checkbox:checked');
  const selectedMemberIds = Array.from(selectedCheckboxes).map(cb => cb.value);

  if (selectedMemberIds.length === 0) {
    showError('Please select at least one member to add.');
    return;
  }

  try {
    showLoading('Adding members...');

    // CORRECTION: Ensure encryption keys are loaded first
    if (!userPrivateKey || !userPublicKey) {
      throw new Error('Encryption keys not loaded. Please unlock encryption first.');
    }

    // Use the optimized encrypted member addition
    const result = await addMembersToEncryptedGroup(currentGroup.id, selectedMemberIds);

    // CORRECTION: Check if result has expected structure
    if (!result || !result.success) {
      throw new Error(result?.error || 'Failed to add members');
    }

    // CORRECTION: Safe UI updates
    if (result.added_members) {
      currentGroupMembers = [...currentGroupMembers, ...result.added_members];
    }

    if (result.total_members) {
      currentGroup.memberCount = result.total_members;
      updateChatHeader(currentGroup.name, `Group • ${currentGroup.memberCount} members`);
    }

    // CORRECTION: Fix modal ID reference
    const membersModal = document.getElementById('viewMembersModal');
    if (membersModal && membersModal.style.display === 'flex') {
      await loadGroupMembers(currentGroup.id);
    }

    closeAddMembersModal();
    showSuccess(`✅ Added ${selectedMemberIds.length} member(s) successfully!`);

  } catch (error) {
    console.error('Error adding members:', error);
    showError(error.message || 'Failed to add members. Please try again.');
  } finally {
    hideLoading();
  }
}

async function addMembersToEncryptedGroup(groupId, newMemberIds) {
  try {
    console.log(`🔐 Adding ${newMemberIds.length} member(s) to encrypted group ${groupId}`);

    // 1. Get admin's encrypted group seed
    const response = await fetch('/encryption/get_my_encrypted_group_seed/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body: JSON.stringify({ group_id: groupId })
    });

    if (!response.ok) throw new Error('Failed to fetch group seed');
    const data = await response.json();
    if (!data.success || !data.encrypted_seed) throw new Error('Admin group seed not found');

    // 2. Admin decrypts group seed using their private key
    console.log('🔓 Decrypting group seed...');
    const groupSeed = await decryptGroupSeed(data.encrypted_seed);
    const groupSeedBase64 = arrayBufferToBase64(groupSeed);

    // 3. Encrypt the same group seed for each new member
    console.log(`🔐 Encrypting for ${newMemberIds.length} new member(s)...`);
    const encryptedSeeds = [];

    for (const memberId of newMemberIds) {
      try {
        const memberPublicKey = await getContactPublicKeyCached(memberId);
        const encryptedSeed = await encryptGroupSeedForMember(groupSeedBase64, memberId, memberPublicKey);

        encryptedSeeds.push({
          member_id: memberId,
          encrypted_seed: encryptedSeed.encrypted_seed,
          iv: encryptedSeed.iv,
          encrypted_by: userId,
          timestamp: new Date().toISOString()
        });
      } catch (error) {
        console.error(`❌ Failed to encrypt for ${memberId}:`, error);
      }
    }

    if (encryptedSeeds.length === 0) throw new Error('Failed to encrypt for any new members');

    // 4. Send encrypted seeds to backend for storage
    const addResponse = await fetch('/groups/add_members_with_encryption/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body: JSON.stringify({
        group_id: groupId,
        new_member_ids: newMemberIds,
        encrypted_seeds: encryptedSeeds
      })
    });

    if (!addResponse.ok) throw new Error('Server failed to add members');
    const result = await addResponse.json();
    if (!result.success) throw new Error(result.error || 'Failed to add members');

    console.log(`✅ Successfully added ${result.added_members.length} member(s) with encryption`);
    return result;

  } catch (error) {
    console.error('❌ Error adding new members:', error);
    throw error;
  }
}

// ----------------------------------------------------
// 97) confirmRemoveMembers
// ----------------------------------------------------
async function confirmRemoveMembers() {
  if (!currentGroup || selectedMembersForRemoval.length === 0) {
    showError('Please select at least one member to remove.');
    return;
  }

  try {
    const response = await fetch('/groups/remove_member/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      },
      body: JSON.stringify({
        group_id: currentGroup.id,
        member_ids: selectedMembersForRemoval
      })
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.error || 'Failed to remove members');
    }

    const data = await response.json();
    if (data.success) {
      // Update local members list
      selectedMembersForRemoval.forEach(memberId => {
        currentGroupMembers = currentGroupMembers.filter(member => member.id !== memberId);
      });

      // Update member count in header
      currentGroup.memberCount = data.total_members;
      updateChatHeader(currentGroup.name, `Group • ${currentGroup.memberCount} members`);

      closeRemoveMembersModal();
      showSuccess(data.message || 'Members removed successfully!');
    } else {
      throw new Error(data.error || 'Failed to remove members');
    }

  } catch (error) {
    console.error('Error removing members:', error);
    showError(error.message || 'Failed to remove members');
  }
}

// ----------------------------------------------------
// 98) confirmMakeAdmin
// ----------------------------------------------------
async function confirmMakeAdmin() {
  if (!currentGroup || selectedMembersForAdmin.length === 0) {
    showError('Please select at least one member to make admin.');
    return;
  }

  try {
    // Show loading state
    const confirmBtn = document.querySelector('#makeAdminModal .confirm');
    const originalText = confirmBtn.textContent;
    confirmBtn.textContent = 'Making Admins...';
    confirmBtn.disabled = true;

    let successCount = 0;
    let errorMessages = [];

    // Process each selected member
    for (const memberId of selectedMembersForAdmin) {
      try {
        const response = await fetch('/groups/make_admin/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken(),
          },
          body: JSON.stringify({
            group_id: currentGroup.id,
            member_id: memberId
          })
        });

        if (response.ok) {
          const data = await response.json();
          if (data.success) {
            successCount++;

            // Update local members list
            const memberIndex = currentGroupMembers.findIndex(member => member.id === memberId);
            if (memberIndex !== -1) {
              currentGroupMembers[memberIndex].is_admin = true;
            }
          } else {
            errorMessages.push(`Failed to promote ${getMemberName(memberId)}: ${data.error}`);
          }
        } else {
          const errorData = await response.json();
          errorMessages.push(`Failed to promote ${getMemberName(memberId)}: ${errorData.error || 'Server error'}`);
        }
      } catch (error) {
        errorMessages.push(`Failed to promote ${getMemberName(memberId)}: ${error.message}`);
      }
    }

    // Reset button state
    confirmBtn.textContent = originalText;
    confirmBtn.disabled = false;

    // Show results
    if (successCount > 0) {
      let message = `Successfully promoted ${successCount} member${successCount !== 1 ? 's' : ''} to admin!`;
      if (errorMessages.length > 0) {
        message += ` But ${errorMessages.length} failed.`;
        console.error('Some promotions failed:', errorMessages);
      }
      showSuccess(message);
    }

    if (errorMessages.length > 0 && successCount === 0) {
      showError('Failed to promote members: ' + errorMessages[0]);
    }

    closeMakeAdminModal();

  } catch (error) {
    console.error('Error making members admin:', error);
    showError('Failed to promote members');

    // Reset button state
    const confirmBtn = document.querySelector('#makeAdminModal .confirm');
    confirmBtn.textContent = 'Make Admins';
    confirmBtn.disabled = false;
  }
}

// ----------------------------------------------------
// 99) confirmRemoveAdmin
// ----------------------------------------------------
async function confirmRemoveAdmin() {
  if (!currentGroup || selectedAdminsForRemoval.length === 0) {
    showError('Please select at least one admin to remove.');
    return;
  }

  try {
    // Safely update UI elements
    const confirmBtn = document.querySelector('#removeAdminModal .confirm');
    const selectedCountElement = document.getElementById('removeAdminSelectedCount');

    if (confirmBtn) {
      confirmBtn.textContent = 'Removing Admins...';
      confirmBtn.disabled = true;
    }

    // Use bulk remove endpoint for better performance
    const response = await fetch('/groups/bulk_remove_admins/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      },
      body: JSON.stringify({
        group_id: currentGroup.id,
        member_ids: selectedAdminsForRemoval
      })
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.error || 'Failed to remove admin privileges');
    }

    const data = await response.json();

    if (data.success) {
      // Update local members list
      selectedAdminsForRemoval.forEach(memberId => {
        const memberIndex = currentGroupMembers.findIndex(member => member.id === memberId);
        if (memberIndex !== -1) {
          currentGroupMembers[memberIndex].is_admin = false;
        }
      });

      showSuccess(data.message || `Admin privileges removed from ${selectedAdminsForRemoval.length} members!`);
    } else {
      throw new Error(data.error || 'Failed to remove admin privileges');
    }

    closeRemoveAdminModal();

  } catch (error) {
    console.error('Error removing admin privileges:', error);
    showError(error.message || 'Failed to remove admin privileges');
  } finally {
    // Always reset button state
    const confirmBtn = document.querySelector('#removeAdminModal .confirm');
    if (confirmBtn) {
      confirmBtn.textContent = 'Remove Admin';
      confirmBtn.disabled = false;
    }
  }
}
// ----------------------------------------------------
// 100) confirmLeaveGroup
// ----------------------------------------------------
async function confirmLeaveGroup() {
  if (!currentGroup) return;

  try {
    const response = await fetch('/groups/leave/', {
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
      throw new Error(errorData.error || 'Failed to leave group');
    }

    const data = await response.json();
    if (data.success) {
      showSuccess(data.message || 'You have left the group');

      // Remove group from sidebar
      const groupElement = document.querySelector(`[data-group-id="${currentGroup.id}"]`);
      if (groupElement) {
        groupElement.remove();
      }

      // Reset chat view
      resetChatView();

      closeLeaveGroupModal();
    } else {
      throw new Error(data.error || 'Failed to leave group');
    }

  } catch (error) {
    console.error('Error leaving group:', error);
    showError(error.message || 'Failed to leave group');
  }
}



// 135) Decrypt with Sender ID
async function decryptMessageWithSender(encryptedData, senderId) {
  try {
    const roomKey = await getOrCreateRoomKey(senderId);
    return await decryptMessage(encryptedData, roomKey);
  } catch (error) {
    console.error(`Failed to decrypt message from ${senderId}:`, error);
    throw error;
  }
}

// 136) Show Info
function showInfo(message) {
  console.info('Passcode Info:', message);
}



// 138) Add Member to Group with Encryption
async function addMemberToGroupWithEncryption(groupId, newMemberId) {
  try {
    const newGroupSeed = await generateGroupSeed();
    const groupSeedBase64 = arrayBufferToBase64(newGroupSeed);

    const newMemberPublicKey = await getContactPublicKeyCached(newMemberId);
    const encryptedSeed = await encryptGroupSeedForMember(groupSeedBase64, newMemberPublicKey);

    const response = await fetch('/groups/add_member_encryption/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body: JSON.stringify({
        group_id: groupId,
        encrypted_seed: {
          member_id: newMemberId,
          encrypted_seed: encryptedSeed.encrypted_seed,
          encrypted_by: userId,
          timestamp: new Date().toISOString()
        }
      })
    });

    if (response.ok) {
      const groupKey = await deriveGroupKey(newGroupSeed, groupId);
      keyCache.set(`group_${groupId}`, groupKey);
    }
  } catch (error) {
    console.error('Error adding member encryption:', error);
  }
}

// 139) Validate Encryption Setup
async function validateEncryptionSetup() {
  try {
    const status = getEncryptionStatus();
    if (!status.keysLoaded) throw new Error('Encryption keys not loaded');

    const testMessage = "Encryption test";
    const encrypted = await encryptMessageForContact(testMessage, userId);
    const decrypted = await decryptMessageFromContact(encrypted, userId);

    if (decrypted !== testMessage) throw new Error('Encryption self-test failed');
    return true;
  } catch (error) {
    console.error('Encryption validation failed:', error);
    return false;
  }
}

// 140) Reinitialize Encryption
async function reinitializeEncryption() {
  clearKeyCache();
  await initializePasscodeSystem();
}

// ====================================================
// END OF COMPLETE CHAT APPLICATION
// ====================================================


