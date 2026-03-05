/**
 * storage.js - IndexedDB Management for ChitChat
 * Used for browser-side caching of encrypted images to ensure privacy at rest.
 */

const DB_NAME = 'ChitChatMediaCache';
const DB_VERSION = 2; // Incremented version for schema change
const STORE_NAME = 'media_cache';

let db;

/**
 * Initialize the IndexedDB
 */
function initDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);

        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            // Remove old store if it exists
            if (db.objectStoreNames.contains('decrypted_images')) {
                db.deleteObjectStore('decrypted_images');
            }
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME, { keyPath: 'messageId' });
            }
        };

        request.onsuccess = (event) => {
            db = event.target.result;
            console.log('IndexedDB initialized successfully');
            resolve(db);
        };

        request.onerror = (event) => {
            console.error('IndexedDB error:', event.target.error);
            reject(event.target.error);
        };
    });
}

/**
 * Save an encrypted image to the cache
 * @param {string} messageId 
 * @param {string} ciphertext (Base64)
 * @param {string} iv (Base64)
 */
async function saveToCache(messageId, ciphertext, iv) {
    if (!db) await initDB();

    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);

        const item = {
            messageId: messageId,
            ciphertext: ciphertext,
            iv: iv,
            timestamp: Date.now()
        };

        const request = store.put(item);

        request.onsuccess = () => resolve(true);
        request.onerror = (event) => {
            console.error('Save to cache failed:', event.target.error);
            reject(event.target.error);
        };
    });
}

/**
 * Get an encrypted image from the cache
 * @param {string} messageId 
 * @returns {Promise<object|null>} Object with ciphertext and iv, or null
 */
async function getFromCache(messageId) {
    if (!db) await initDB();

    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.get(messageId);

        request.onsuccess = () => {
            if (request.result) {
                resolve({
                    ciphertext: request.result.ciphertext,
                    iv: request.result.iv
                });
            } else {
                resolve(null);
            }
        };

        request.onerror = (event) => {
            console.error('Get from cache failed:', event.target.error);
            reject(event.target.error);
        };
    });
}

/**
 * Clear the entire media cache
 */
async function clearMediaCache() {
    if (!db) await initDB();

    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.clear();

        request.onsuccess = () => resolve(true);
        request.onerror = (event) => reject(event.target.error);
    });
}

// Auto-initialize on load
initDB().catch(err => console.error("Could not init IndexDB", err));
