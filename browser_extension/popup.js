// Decision Engine Recorder - Popup Script
// Displays last event status and errors

document.addEventListener('DOMContentLoaded', () => {
  // Load session ID
  chrome.storage.session.get(['sessionId'], (result) => {
    const sessionIdEl = document.getElementById('sessionId');
    if (result.sessionId) {
      sessionIdEl.textContent = result.sessionId.substring(0, 8) + '...';
      sessionIdEl.title = result.sessionId;
    } else {
      sessionIdEl.textContent = 'Not initialized';
    }
  });

  // Load last event info
  chrome.storage.local.get(['lastEventId', 'lastEventTime', 'lastError'], (result) => {
    const eventIdEl = document.getElementById('lastEventId');
    const eventTimeEl = document.getElementById('lastEventTime');
    const errorContainer = document.getElementById('errorContainer');
    const errorEl = document.getElementById('lastError');

    if (result.lastEventId) {
      eventIdEl.textContent = result.lastEventId.substring(0, 8) + '...';
      eventIdEl.title = result.lastEventId;
      eventIdEl.classList.add('success');
      
      if (result.lastEventTime) {
        const date = new Date(result.lastEventTime);
        eventTimeEl.textContent = date.toLocaleString();
      }
    } else {
      eventIdEl.textContent = 'No events recorded yet';
    }

    if (result.lastError) {
      errorContainer.style.display = 'block';
      errorEl.textContent = result.lastError;
    } else {
      errorContainer.style.display = 'none';
    }
  });
});
