// ====================================================
// PASSCODE & ENCRYPTION MANAGEMENT (11-50)
// ====================================================

// 11) Initialize Passcode System
async function initializePasscodeSystem() {
    try {
        const hasKeys = await checkUserKeys();
        isNewUser = !hasKeys;

        showPasscodeModal();

        if (isNewUser) {
            switchToTab('create');
            showInfo('Welcome! Set up your encryption passcode to secure your messages.');
        } else {
            switchToTab('verify');
            showInfo('Enter your passcode to unlock your encrypted messages.');
        }
    } catch (error) {
        console.error('Error initializing passcode system:', error);
        showError('Failed to initialize encryption system');
    }
}

// 12) Check User Keys
async function checkUserKeys() {
    try {
        const response = await fetch('/encryption/check_keys/');
        if (!response.ok) throw new Error('Failed to check keys');
        const data = await response.json();

        // Optimization: Store the bundled keys so we don't need to call get_keys later
        if (data.has_keys && data.keys) {
            cachedUserKeyBundle = data.keys;
        }

        return data.has_keys;
    } catch (error) {
        console.error('Error checking user keys:', error);
        return false;
    }
}

// 13) Generate and Store Keys
async function generateAndStoreKeys(passcode) {
    try {
        const keyPair = await crypto.subtle.generateKey(
            { name: 'ECDH', namedCurve: 'P-256' },
            true,
            ['deriveKey', 'deriveBits']
        );

        const salt = crypto.getRandomValues(new Uint8Array(16));
        const iterations = 100000;

        const masterKey = await crypto.subtle.deriveKey(
            { name: 'PBKDF2', salt, iterations, hash: 'SHA-256' },
            await crypto.subtle.importKey('raw', new TextEncoder().encode(passcode), 'PBKDF2', false, ['deriveKey']),
            { name: 'AES-GCM', length: 256 },
            false,
            ['encrypt', 'decrypt']
        );

        const exportedPrivateKey = await crypto.subtle.exportKey('pkcs8', keyPair.privateKey);
        const iv = crypto.getRandomValues(new Uint8Array(12));

        const encryptedPrivateKey = await crypto.subtle.encrypt(
            { name: 'AES-GCM', iv },
            masterKey,
            exportedPrivateKey
        );

        const exportedPublicKey = await crypto.subtle.exportKey('spki', keyPair.publicKey);

        await storeKeysOnServer(
            arrayBufferToBase64(encryptedPrivateKey),
            arrayBufferToBase64(iv),
            arrayBufferToBase64(salt),
            iterations,
            arrayBufferToBase64(exportedPublicKey)
        );

        userPrivateKey = keyPair.privateKey;
        userPublicKey = keyPair.publicKey;
        window.masterKey = masterKey;
    } catch (error) {
        console.error('Error generating keys:', error);
        throw error;
    }
}

// 14) Store Keys on Server
async function storeKeysOnServer(encryptedPrivateKey, iv, salt, iterations, publicKey) {
    try {
        const response = await fetch('/encryption/store_keys/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
            body: JSON.stringify({ encrypted_private_key: encryptedPrivateKey, iv, salt, iterations, public_key: publicKey })
        });

        if (!response.ok) throw new Error('Failed to store keys');
        return await response.json();
    } catch (error) {
        console.error('Error storing keys:', error);
        throw error;
    }
}

// 15) Decrypt User Keys
async function decryptUserKeys(passcode) {
    try {
        let data = cachedUserKeyBundle;

        if (!data) {
            console.log('🔄 Fetching user keys (no bundled data)...');
            const response = await fetch('/encryption/get_keys/');
            if (!response.ok) throw new Error('Failed to fetch keys');
            data = await response.json();
        } else {
            console.log('✅ Using bundled user keys');
        }

        const salt = base64ToArrayBuffer(data.salt);
        const iterations = data.iterations;

        const masterKey = await crypto.subtle.deriveKey(
            { name: 'PBKDF2', salt, iterations, hash: 'SHA-256' },
            await crypto.subtle.importKey('raw', new TextEncoder().encode(passcode), 'PBKDF2', false, ['deriveKey']),
            { name: 'AES-GCM', length: 256 },
            false,
            ['encrypt', 'decrypt']
        );

        const encryptedPrivateKey = base64ToArrayBuffer(data.encrypted_private_key);
        const iv = base64ToArrayBuffer(data.iv);

        const decryptedPrivateKey = await crypto.subtle.decrypt(
            { name: 'AES-GCM', iv },
            masterKey,
            encryptedPrivateKey
        );

        userPrivateKey = await crypto.subtle.importKey('pkcs8', decryptedPrivateKey, KEY_ALGORITHM, false, ['deriveKey', 'deriveBits']);
        userPublicKey = await crypto.subtle.importKey('spki', base64ToArrayBuffer(data.public_key), KEY_ALGORITHM, false, []);
        window.masterKey = masterKey;
    } catch (error) {
        console.error('Error decrypting keys:', error);
        throw error;
    }
}

// 16) Show Passcode Modal
function showPasscodeModal() {
    const modal = document.getElementById('passcodeModal');
    if (modal) {
        modal.classList.add('show');
        setupPasscodeInputs();
        setTimeout(() => {
            const activeTab = modal.querySelector('.tab-content.active');
            const firstInput = activeTab?.querySelector('.passcode-input');
            if (firstInput) firstInput.focus();
        }, 100);
    }
}

// 17) Close Passcode Modal
function closePasscodeModal() {
    const modal = document.getElementById('passcodeModal');
    if (modal) {
        modal.classList.remove('show');
        document.querySelectorAll('.passcode-input').forEach(input => {
            input.value = '';
            input.classList.remove('filled', 'error');
        });
        updateStrengthMeter(0);
        hideMessages();
    }
}

// 18) Switch To Tab
function switchToTab(tabName) {
    const modal = document.getElementById('passcodeModal');
    if (!modal) return;

    modal.querySelectorAll('.tab-header').forEach(header => {
        header.classList.toggle('active', header.dataset.tab === tabName);
    });

    modal.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `${tabName}-tab`);
    });

    currentPasscodeTab = tabName;
    document.querySelectorAll('.passcode-input').forEach(input => {
        input.value = '';
        input.classList.remove('filled', 'error');
    });

    hideMessages();

    setTimeout(() => {
        const activeTab = document.querySelector('.tab-content.active');
        const firstInput = activeTab?.querySelector('.passcode-input');
        if (firstInput) firstInput.focus();
    }, 50);

    if (tabName === 'create') updateCreateButtonState();
}

// 19) Setup Passcode Inputs
function setupPasscodeInputs() {
    const inputs = document.querySelectorAll('.passcode-input');

    inputs.forEach((input, index) => {
        input.addEventListener('input', (e) => {
            const value = e.target.value;

            if (value.length === 1 && /[0-9]/.test(value)) {
                input.classList.add('filled');
                input.classList.remove('error');

                if (index < inputs.length - 1) inputs[index + 1].focus();
                checkPasscodeCompletion();
            } else if (value.length === 0) {
                input.classList.remove('filled', 'error');
            } else {
                input.value = '';
                input.classList.add('error');
            }
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && !e.target.value && index > 0) {
                inputs[index - 1].focus();
                inputs[index - 1].value = '';
                inputs[index - 1].classList.remove('filled', 'error');
            }
        });

        input.addEventListener('paste', (e) => {
            e.preventDefault();
            const pastedData = e.clipboardData.getData('text').slice(0, 6);

            if (/^\d{6}$/.test(pastedData)) {
                const digits = pastedData.split('');
                inputs.forEach((input, i) => {
                    if (digits[i]) {
                        input.value = digits[i];
                        input.classList.add('filled');
                        input.classList.remove('error');
                    }
                });

                if (digits[5]) inputs[5].focus();
                checkPasscodeCompletion();
            }
        });
    });

    setupFormSubmissions();
}

// 20) Setup Form Submissions
function setupFormSubmissions() {
    const verifyForm = document.getElementById('verifyPasscodeForm');
    const createForm = document.getElementById('createPasscodeForm');

    if (verifyForm) verifyForm.addEventListener('submit', handleVerifyPasscode);
    if (createForm) createForm.addEventListener('submit', handleCreatePasscode);

    document.querySelectorAll('.tab-header').forEach(header => {
        header.addEventListener('click', () => switchToTab(header.dataset.tab));
    });
}

// 21) Check Passcode Completion
function checkPasscodeCompletion() {
    if (currentPasscodeTab === 'verify') {
        const inputs = document.querySelectorAll('#verify-tab .passcode-input');
        const isComplete = Array.from(inputs).every(input => input.value.length === 1);

        if (isComplete) {
            setTimeout(() => document.getElementById('verifyPasscodeForm').dispatchEvent(new Event('submit')), 300);
        }
    } else if (currentPasscodeTab === 'create') {
        updateCreateButtonState();
        updateStrengthMeter(calculatePasscodeStrength());
    }
}

// 22) Update Create Button State
function updateCreateButtonState() {
    const createInputs = document.querySelectorAll('.create-input');
    const confirmInputs = document.querySelectorAll('.confirm-input');
    const submitButton = document.querySelector('#createPasscodeForm .btn');

    const createComplete = Array.from(createInputs).every(input => input.value.length === 1);
    const confirmComplete = Array.from(confirmInputs).every(input => input.value.length === 1);

    if (createComplete && confirmComplete) {
        const createPasscode = Array.from(createInputs).map(input => input.value).join('');
        const confirmPasscode = Array.from(confirmInputs).map(input => input.value).join('');

        if (createPasscode === confirmPasscode) {
            submitButton.disabled = false;
            document.querySelectorAll('.passcode-input').forEach(input => input.classList.remove('error'));
        } else {
            submitButton.disabled = true;
            document.querySelectorAll('.confirm-input').forEach(input => input.classList.add('error'));
            showError('Passcodes do not match');
        }
    } else {
        submitButton.disabled = true;
        hideMessages();
    }
}

// 23) Calculate Passcode Strength
function calculatePasscodeStrength() {
    const inputs = document.querySelectorAll('.create-input');
    const passcode = Array.from(inputs).map(input => input.value).join('');

    if (passcode.length < 6) return 0;

    let strength = 0;
    const hasRepeats = /(\d)\1{2,}/.test(passcode);
    if (hasRepeats) strength -= 20;

    const isSequence = '012345 123456 234567 345678 456789 567890 678901 789012 890123 901234 098765 987654 876543 765432 654321 543210 432109 321098 210987 109876'.split(' ').includes(passcode);
    if (isSequence) strength -= 30;

    const uniqueDigits = new Set(passcode.split('')).size;
    strength += Math.min(uniqueDigits * 20, 100);

    return Math.max(0, Math.min(100, strength));
}

// 24) Update Strength Meter
function updateStrengthMeter(strength) {
    const strengthLevel = document.querySelector('.strength-level');
    const strengthText = document.querySelector('.strength-text');

    if (strengthLevel && strengthText) {
        strengthLevel.style.width = `${strength}%`;

        if (strength < 30) {
            strengthLevel.style.background = '#ef4444';
            strengthText.textContent = 'Weak passcode';
            strengthText.style.color = '#ef4444';
        } else if (strength < 70) {
            strengthLevel.style.background = '#f59e0b';
            strengthText.textContent = 'Moderate passcode';
            strengthText.style.color = '#f59e0b';
        } else {
            strengthLevel.style.background = '#10b981';
            strengthText.textContent = 'Strong passcode';
            strengthText.style.color = '#10b981';
        }
    }
}

// 25) Handle Verify Passcode
async function handleVerifyPasscode(e) {
    e.preventDefault();

    const inputs = document.querySelectorAll('#verify-tab .passcode-input');
    const passcode = Array.from(inputs).map(input => input.value).join('');

    if (passcode.length !== 6) {
        showError('Please enter a complete 6-digit passcode');
        inputs.forEach(input => input.classList.add('error'));
        return;
    }

    try {
        setFormLoading('verify', true);
        await decryptUserKeys(passcode);
        showSuccess('Encryption unlocked successfully!');

        setTimeout(() => {
            closePasscodeModal();
            showSystemMessage('Encryption enabled - Your messages are secure');
        }, 1000);
    } catch (error) {
        console.error('Error verifying passcode:', error);
        showError('Invalid passcode. Please try again.');
        inputs.forEach(input => input.classList.add('error'));

        setTimeout(() => {
            inputs.forEach(input => {
                input.value = '';
                input.classList.remove('filled', 'error');
            });
            inputs[0].focus();
        }, 1000);
    } finally {
        setFormLoading('verify', false);
    }
}

// 26) Handle Create Passcode
async function handleCreatePasscode(e) {
    e.preventDefault();

    const createInputs = document.querySelectorAll('.create-input');
    const confirmInputs = document.querySelectorAll('.confirm-input');

    const passcode = Array.from(createInputs).map(input => input.value).join('');
    const confirmPasscode = Array.from(confirmInputs).map(input => input.value).join('');

    if (passcode.length !== 6) {
        showError('Please enter a complete 6-digit passcode');
        return;
    }

    if (passcode !== confirmPasscode) {
        showError('Passcodes do not match');
        confirmInputs.forEach(input => input.classList.add('error'));
        return;
    }

    const strength = calculatePasscodeStrength();
    if (strength < 30) {
        showError('Please choose a stronger passcode. Avoid simple sequences or repeated numbers.');
        return;
    }

    try {
        setFormLoading('create', true);
        await generateAndStoreKeys(passcode);
        showSuccess('Encryption setup completed! Your messages are now secure.');

        setTimeout(() => {
            closePasscodeModal();
            showSystemMessage('End-to-end encryption enabled');
        }, 1500);
    } catch (error) {
        console.error('Error creating passcode:', error);
        showError('Failed to setup encryption. Please try again.');
    } finally {
        setFormLoading('create', false);
    }
}

// 27) Set Form Loading
function setFormLoading(formType, loading) {
    const form = document.getElementById(`${formType}PasscodeForm`);
    const button = form?.querySelector('.btn');

    if (form && button) {
        if (loading) {
            form.classList.add('loading');
            button.disabled = true;
        } else {
            form.classList.remove('loading');
            if (formType === 'verify') button.disabled = false;
        }
    }
}

// 28) Show Error Message
function showError(message) {
    hideMessages();
    const modal = document.getElementById('passcodeModal');
    const activeTab = modal?.querySelector('.tab-content.active');
    if (!activeTab) return;

    let errorDiv = activeTab.querySelector('.error-message');

    if (!errorDiv) {
        errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        activeTab.querySelector('.form-footer').prepend(errorDiv);
    }

    errorDiv.textContent = message;
    errorDiv.classList.add('show');
}

// 29) Show Success Message
function showSuccess(message) {
    hideMessages();
    const modal = document.getElementById('passcodeModal');
    const activeTab = modal?.querySelector('.tab-content.active');
    if (!activeTab) return;

    let successDiv = activeTab.querySelector('.success-message');

    if (!successDiv) {
        successDiv = document.createElement('div');
        successDiv.className = 'success-message';
        activeTab.querySelector('.form-footer').prepend(successDiv);
    }

    successDiv.textContent = message;
    successDiv.classList.add('show');
}

// 30) Hide Messages
function hideMessages() {
    document.querySelectorAll('.error-message, .success-message').forEach(msg => {
        msg.classList.remove('show');
    });
}

// ====================================================
// CORE ENCRYPTION FUNCTIONS (31-60)
// ====================================================

// 31) Get Contact Public Key
async function getContactPublicKey(contactId) {
    // CHECK PRE-FETCHED CACHE FIRST
    if (preFetchedPublicKeys.has(contactId)) {
        console.log(`✅ Using pre-fetched public key for contact: ${contactId}`);
        const base64Key = preFetchedPublicKeys.get(contactId);
        return await crypto.subtle.importKey(
            'spki',
            base64ToArrayBuffer(base64Key),
            KEY_ALGORITHM,
            false,
            []
        );
    }

    console.log(`🔄 Fetching public key (no pre-fetch)... ${contactId}`);
    try {
        const response = await fetch(`/encryption/get_public_key/?user_id=${contactId}`);
        if (!response.ok) throw new Error('Failed to fetch public key');

        const data = await response.json();
        if (!data.public_key) throw new Error('No public key found');

        return await crypto.subtle.importKey('spki', base64ToArrayBuffer(data.public_key), KEY_ALGORITHM, false, []);
    } catch (error) {
        console.error('Error getting contact public key:', error);
        throw error;
    }
}

// 32) Derive Room Key
async function deriveRoomKey(contactPublicKey, roomId) {
    try {
        const sharedSecret = await crypto.subtle.deriveBits({ name: 'ECDH', public: contactPublicKey }, userPrivateKey, 256);

        const roomKey = await crypto.subtle.deriveKey(
            { name: 'HKDF', salt: new TextEncoder().encode(roomId), info: new TextEncoder().encode('room_key'), hash: 'SHA-256' },
            await crypto.subtle.importKey('raw', sharedSecret, 'HKDF', false, ['deriveKey']),
            { name: 'AES-GCM', length: 256 },
            false,
            ['encrypt', 'decrypt']
        );

        return roomKey;
    } catch (error) {
        console.error('Error deriving room key:', error);
        throw error;
    }
}

// 33) Get or Create Room Key
async function getOrCreateRoomKey(contactId) {
    const cacheKey = `room_${contactId}`;

    if (keyCache.has(cacheKey)) return keyCache.get(cacheKey);

    // If an operation is already pending, wait for it
    if (pendingKeyOperations.has(cacheKey)) {
        console.log(`⏳ Waiting for pending room key operation: ${contactId}`);
        return pendingKeyOperations.get(cacheKey);
    }

    const promise = (async () => {
        try {
            const contactPublicKey = await getContactPublicKey(contactId);
            const roomId = [userId, contactId].sort().join('_');
            const roomKey = await deriveRoomKey(contactPublicKey, roomId);

            keyCache.set(cacheKey, roomKey);
            return roomKey;
        } catch (error) {
            console.error('Error getting room key:', error);
            throw error;
        } finally {
            pendingKeyOperations.delete(cacheKey);
        }
    })();

    pendingKeyOperations.set(cacheKey, promise);
    return promise;
}

// 34) Encrypt Message
async function encryptMessage(message, key) {
    try {
        const encoder = new TextEncoder();
        const encodedMessage = encoder.encode(message);
        const iv = crypto.getRandomValues(new Uint8Array(12));

        const encryptedData = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encodedMessage);

        return { ciphertext: arrayBufferToBase64(encryptedData), iv: arrayBufferToBase64(iv) };
    } catch (error) {
        console.error('Error encrypting message:', error);
        throw error;
    }
}

// 35) Decrypt Message
async function decryptMessage(encryptedData, key) {
    try {
        const ciphertext = base64ToArrayBuffer(encryptedData.ciphertext);
        const iv = base64ToArrayBuffer(encryptedData.iv);

        const decryptedData = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
        const decoder = new TextDecoder();
        return decoder.decode(decryptedData);
    } catch (error) {
        console.error('Error decrypting message:', error);
        throw error;
    }
}

// 35.1) Encrypt binary file (No TextEncoder)
async function encryptFile(fileBuffer, key) {
    try {
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const encryptedData = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, fileBuffer);
        return { ciphertext: arrayBufferToBase64(encryptedData), iv: arrayBufferToBase64(iv) };
    } catch (error) {
        console.error('Error encrypting file:', error);
        throw error;
    }
}

// 35.2) Decrypt binary file (No TextDecoder)
async function decryptFile(encryptedData, key) {
    try {
        const ciphertext = base64ToArrayBuffer(encryptedData.ciphertext);
        const iv = base64ToArrayBuffer(encryptedData.iv);
        return await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
    } catch (error) {
        console.error('Error decrypting file:', error);
        throw error;
    }
}

// 36) Encrypt Message for Contact
async function encryptMessageForContact(message, contactId) {
    try {
        const roomKey = await getOrCreateRoomKey(contactId);
        return await encryptMessage(message, roomKey);
    } catch (error) {
        console.error('Error encrypting message for contact:', error);
        throw error;
    }
}

// 37) Decrypt Message from Contact
async function decryptMessageFromContact(encryptedData, contactId) {
    try {
        const roomKey = await getOrCreateRoomKey(contactId);
        return await decryptMessage(encryptedData, roomKey);
    } catch (error) {
        console.error('Error decrypting message from contact:', error);
        throw error;
    }
}

// 38) Generate Group Seed
async function generateGroupSeed() {
    return crypto.getRandomValues(new Uint8Array(32));
}

// 39) Derive Group Key
async function deriveGroupKey(groupSeed, groupId) {
    try {
        return await crypto.subtle.deriveKey(
            { name: 'HKDF', salt: new TextEncoder().encode(groupId), info: new TextEncoder().encode('group_key'), hash: 'SHA-256' },
            await crypto.subtle.importKey('raw', groupSeed, 'HKDF', false, ['deriveKey']),
            { name: 'AES-GCM', length: 256 },
            false,
            ['encrypt', 'decrypt']
        );
    } catch (error) {
        console.error('Error deriving group key:', error);
        throw error;
    }
}

// 40) Encrypt Group Seed for Member - USE THIS VERSION
async function encryptGroupSeedForMember(groupSeedBase64, memberId, memberPublicKey) {
    try {
        console.log(`🔐 Encrypting group seed for member: ${memberId}`);

        // Convert string to ArrayBuffer
        const encoder = new TextEncoder();
        const seedBuffer = encoder.encode(groupSeedBase64);

        // Use the same room key derivation as individual messages
        const roomId = [userId, memberId].sort().join('_');
        const roomKey = await getOrCreateRoomKey(memberId);

        // Encrypt the group seed
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const encryptedSeed = await crypto.subtle.encrypt(
            { name: 'AES-GCM', iv: iv },
            roomKey,
            seedBuffer
        );

        console.log(`✅ Group seed encrypted for member: ${memberId}`);

        return {
            encrypted_seed: arrayBufferToBase64(encryptedSeed),
            iv: arrayBufferToBase64(iv)
        };

    } catch (error) {
        console.error(`Error encrypting group seed for ${memberId}:`, error);
        throw error;
    }
}

// 41) Decrypt Group Seed - USE THIS VERSION  
async function decryptGroupSeed(encryptedGroupSeed) {
    try {
        console.log('🔓 Decrypting group seed...');

        if (!encryptedGroupSeed.iv) {
            throw new Error('Missing IV for group seed decryption');
        }

        // Get the sender ID from the encrypted_by field
        const senderId = encryptedGroupSeed.encrypted_by;

        // Use room key with the sender
        const roomKey = await getOrCreateRoomKey(senderId);

        // Decrypt the group seed
        const decryptedData = await crypto.subtle.decrypt(
            {
                name: 'AES-GCM',
                iv: base64ToArrayBuffer(encryptedGroupSeed.iv)
            },
            roomKey,
            base64ToArrayBuffer(encryptedGroupSeed.encrypted_seed)
        );

        const decoder = new TextDecoder();
        const decryptedSeedBase64 = decoder.decode(decryptedData);

        console.log('✅ Group seed decrypted successfully');
        return base64ToArrayBuffer(decryptedSeedBase64);

    } catch (error) {
        console.error('Error decrypting group seed:', error);
        throw error;
    }
}

// 42) Get or Create Group Key
async function getOrCreateGroupKey(groupId) {
    const cacheKey = `group_${groupId}`;

    if (keyCache.has(cacheKey)) return keyCache.get(cacheKey);

    // If an operation is already pending, wait for it
    if (pendingKeyOperations.has(cacheKey)) {
        return pendingKeyOperations.get(cacheKey);
    }

    const promise = (async () => {
        try {
            let data;
            // CHECK PRE-FETCHED CACHE FIRST
            if (preFetchedGroupSeeds.has(groupId)) {
                console.log(`✅ Using pre-fetched seed for group: ${groupId}`);
                data = { success: true, encrypted_seed: preFetchedGroupSeeds.get(groupId) };
            } else {
                console.log(`🔄 Fetching group seed (no pre-fetch)... ${groupId}`);
                const response = await fetch('/encryption/get_my_encrypted_group_seed/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
                    body: JSON.stringify({ group_id: groupId })
                });

                if (!response.ok) throw new Error('Failed to fetch encrypted seed');
                data = await response.json();
            }

            if (data.success && data.encrypted_seed) {
                const groupSeed = await decryptGroupSeed(data.encrypted_seed);
                const groupKey = await deriveGroupKey(groupSeed, groupId);

                keyCache.set(cacheKey, groupKey);
                return groupKey;
            } else {
                throw new Error('No encrypted seed found for user');
            }
        } catch (error) {
            console.error('Error creating group key:', error);
            return await getOrCreateGroupKeyFallback(groupId);
        } finally {
            pendingKeyOperations.delete(cacheKey);
        }
    })();

    pendingKeyOperations.set(cacheKey, promise);
    return promise;
}

// 44) Encrypt Message for Group
async function encryptMessageForGroup(message, groupId) {
    try {
        const groupKey = await getOrCreateGroupKey(groupId);
        return await encryptMessage(message, groupKey);
    } catch (error) {
        console.error('Error encrypting message for group:', error);
        throw error;
    }
}

// 45) Decrypt Message from Group
async function decryptMessageFromGroup(encryptedData, groupId) {
    try {
        const groupKey = await getOrCreateGroupKey(groupId);
        return await decryptMessage(encryptedData, groupKey);
    } catch (error) {
        console.error('Error decrypting message from group:', error);
        throw error;
    }
}

// 46) Array Buffer to Base64
function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
}

// 47) Base64 to Array Buffer
function base64ToArrayBuffer(base64) {
    try {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    } catch (error) {
        console.error('Base64 conversion error:', error);
        throw error;
    }
}

// 48) Clear Key Cache
function clearKeyCache() {
    keyCache.clear();
    userPrivateKey = null;
    userPublicKey = null;
    window.masterKey = null;
}

// 49) Get Contact Public Key Cached
async function getContactPublicKeyCached(contactId) {
    const cacheKey = `pubkey_${contactId}`;

    if (publicKeyCache.has(cacheKey)) return publicKeyCache.get(cacheKey);

    // If an operation is already pending, wait for it
    if (pendingKeyOperations.has(cacheKey)) {
        return pendingKeyOperations.get(cacheKey);
    }

    const promise = (async () => {
        try {
            const publicKey = await getContactPublicKey(contactId);
            publicKeyCache.set(cacheKey, publicKey);
            return publicKey;
        } finally {
            pendingKeyOperations.delete(cacheKey);
        }
    })();

    pendingKeyOperations.set(cacheKey, promise);
    return promise;
}


// 50) Create Group with Member Encryption - UPDATED
async function createGroupWithMemberEncryption(groupName, selectedMembers) {
    try {
        const groupSeed = await generateGroupSeed();
        const groupSeedBase64 = arrayBufferToBase64(groupSeed);

        console.log(`🔐 Encrypting group seed for ${selectedMembers.length + 1} members...`);

        const encryptedSeeds = [];
        const allMembers = [...selectedMembers, userId];

        for (const memberId of allMembers) {
            try {
                const memberPublicKey = await getContactPublicKeyCached(memberId);

                // ✅ PASS memberId as second parameter
                const encryptedSeed = await encryptGroupSeedForMember(groupSeedBase64, memberId, memberPublicKey);

                encryptedSeeds.push({
                    member_id: memberId,
                    encrypted_seed: encryptedSeed.encrypted_seed,
                    iv: encryptedSeed.iv,  // ✅ Include IV
                    encrypted_by: userId,
                    timestamp: new Date().toISOString()
                });

                console.log(`✅ Encrypted for member: ${memberId}`);
            } catch (error) {
                console.error(`❌ Failed to encrypt for ${memberId}:`, error);
            }
        }

        // Send to server
        const response = await fetch('/groups/create_with_encryption/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
            body: JSON.stringify({
                name: groupName,
                member_ids: selectedMembers,
                encrypted_seeds: encryptedSeeds,
                encryption_enabled: true
            })
        });

        if (!response.ok) throw new Error('Failed to create group');

        const data = await response.json();
        const groupId = data.group_id;

        // Store group key locally
        const groupKey = await deriveGroupKey(groupSeed, groupId);
        keyCache.set(`group_${groupId}`, groupKey);

        console.log('✅ Encrypted group created and key cached successfully');
        return groupId;

    } catch (error) {
        console.error('Error creating encrypted group:', error);
        throw error;
    }
}
