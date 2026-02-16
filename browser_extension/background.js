// Decision Engine Recorder - Background Service Worker
// Handles extension lifecycle and storage

chrome.runtime.onInstalled.addListener(() => {
  console.log('[Decision Engine] Extension installed');
});

// Optional: Handle messages from content script if needed
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'getSessionId') {
    chrome.storage.session.get(['sessionId'], (result) => {
      sendResponse({ sessionId: result.sessionId });
    });
    return true; // Keep channel open for async response
  }
});
