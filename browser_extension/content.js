// Decision Engine Recorder - Content Script
// Detects Claude chat messages and sends events to recorder

(function() {
  'use strict';

  const RECORDER_URL = 'http://localhost:8000/events/record';
  const ACTOR_ID = 'sam';
  const SOURCE_SYSTEM = 'claude-web';
  
  let sessionId = null;
  let messageBuffer = {
    userPrompt: null,
    assistantResponse: null,
    userPromptTimestamp: null,
    assistantResponseTimestamp: null
  };

  // Initialize session ID
  chrome.storage.session.get(['sessionId'], (result) => {
    if (!result.sessionId) {
      sessionId = generateUUID();
      chrome.storage.session.set({ sessionId });
    } else {
      sessionId = result.sessionId;
    }
  });

  function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      const r = Math.random() * 16 | 0;
      const v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }

  async function sha256(text) {
    const encoder = new TextEncoder();
    const data = encoder.encode(text);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  }

  function extractTextFromElement(element) {
    if (!element) return '';
    // Try to get text content, handling various Claude UI structures
    const textContent = element.textContent || element.innerText || '';
    return textContent.trim();
  }

  function findUserMessages() {
    // Claude uses various selectors - try multiple approaches
    const selectors = [
      '[data-testid*="user"]',
      '[class*="user"]',
      '[class*="User"]',
      'div[class*="message"]:has-text',
      'article[class*="user"]'
    ];
    
    const messages = [];
    for (const selector of selectors) {
      try {
        const elements = document.querySelectorAll(selector);
        elements.forEach(el => {
          const text = extractTextFromElement(el);
          if (text && text.length > 0) {
            messages.push({ element: el, text });
          }
        });
      } catch (e) {
        // Selector might not be supported
      }
    }
    return messages;
  }

  function findAssistantMessages() {
    const selectors = [
      '[data-testid*="assistant"]',
      '[class*="assistant"]',
      '[class*="Assistant"]',
      'div[class*="message"]:has-text',
      'article[class*="assistant"]'
    ];
    
    const messages = [];
    for (const selector of selectors) {
      try {
        const elements = document.querySelectorAll(selector);
        elements.forEach(el => {
          const text = extractTextFromElement(el);
          if (text && text.length > 0) {
            messages.push({ element: el, text });
          }
        });
      } catch (e) {
        // Selector might not be supported
      }
    }
    return messages;
  }

  function detectHumanSelection(text) {
    // Look for patterns like "I picked option 1", "I chose option 2", etc.
    const patterns = [
      /I\s+(?:picked|chose|selected)\s+option\s+(\d+)/i,
      /option\s+(\d+)\s+selected/i,
      /chose\s+(\d+)/i
    ];
    
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match) {
        return `option ${match[1]}`;
      }
    }
    return null;
  }

  async function sendEvent(userPrompt, assistantResponse, humanSelection) {
    if (!sessionId) {
      console.warn('[Decision Engine] Session ID not ready');
      return;
    }

    const payload = userPrompt + '\n---\n' + assistantResponse;
    const payloadHash = await sha256(payload);
    const occurredAtUtc = new Date().toISOString();

    const eventData = {
      event_type: 'AI_DECISION_TURN',
      actor_id: ACTOR_ID,
      session_id: sessionId,
      source_system: SOURCE_SYSTEM,
      payload_hash: payloadHash,
      system_suggestion: assistantResponse || null,
      options_presented: null,
      human_selection: humanSelection || null,
      occurred_at_utc: occurredAtUtc
    };

    try {
      const response = await fetch(RECORDER_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(eventData)
      });

      if (response.ok) {
        const result = await response.json();
        console.log('[Decision Engine] Event recorded:', result.event_id);
        
        // Store last event info for popup
        chrome.storage.local.set({
          lastEventId: result.event_id,
          lastEventTime: occurredAtUtc,
          lastError: null
        });
      } else {
        const errorText = await response.text();
        throw new Error(`HTTP ${response.status}: ${errorText}`);
      }
    } catch (error) {
      console.error('[Decision Engine] Failed to record event:', error);
      chrome.storage.local.set({
        lastError: error.message || String(error)
      });
    }
  }

  function processMessages() {
    const userMessages = findUserMessages();
    const assistantMessages = findAssistantMessages();

    // Simple approach: pair last user message with last assistant message
    if (userMessages.length > 0 && assistantMessages.length > 0) {
      const lastUser = userMessages[userMessages.length - 1];
      const lastAssistant = assistantMessages[assistantMessages.length - 1];
      
      // Check if we've already processed this pair
      const userKey = lastUser.text.substring(0, 50);
      const assistantKey = lastAssistant.text.substring(0, 50);
      
      if (messageBuffer.userPrompt !== userKey || messageBuffer.assistantResponse !== assistantKey) {
        messageBuffer.userPrompt = userKey;
        messageBuffer.assistantResponse = assistantKey;
        messageBuffer.userPromptTimestamp = Date.now();
        messageBuffer.assistantResponseTimestamp = Date.now();
        
        // Check for human selection in user message
        const humanSelection = detectHumanSelection(lastUser.text);
        
        sendEvent(lastUser.text, lastAssistant.text, humanSelection);
      }
    }
  }

  // Fallback: capture visible text from chat transcript
  function captureTranscriptFallback() {
    const chatContainer = document.querySelector('[class*="chat"], [class*="conversation"], main, [role="main"]');
    if (!chatContainer) return;

    const allText = chatContainer.innerText || chatContainer.textContent || '';
    const lines = allText.split('\n').filter(line => line.trim().length > 0);
    
    // Simple heuristic: look for alternating user/assistant patterns
    // This is a fallback if DOM selectors fail
    if (lines.length >= 2) {
      const lastUserLine = lines[lines.length - 2];
      const lastAssistantLine = lines[lines.length - 1];
      
      if (lastUserLine && lastAssistantLine && 
          lastUserLine.length > 10 && lastAssistantLine.length > 10) {
        const userKey = lastUserLine.substring(0, 50);
        const assistantKey = lastAssistantLine.substring(0, 50);
        
        if (messageBuffer.userPrompt !== userKey || messageBuffer.assistantResponse !== assistantKey) {
          messageBuffer.userPrompt = userKey;
          messageBuffer.assistantResponse = assistantKey;
          
          const humanSelection = detectHumanSelection(lastUserLine);
          sendEvent(lastUserLine, lastAssistantLine, humanSelection);
        }
      }
    }
  }

  // Watch for DOM changes
  const observer = new MutationObserver((mutations) => {
    let shouldProcess = false;
    
    mutations.forEach((mutation) => {
      if (mutation.addedNodes.length > 0 || mutation.type === 'childList') {
        shouldProcess = true;
      }
    });
    
    if (shouldProcess) {
      // Debounce processing
      setTimeout(() => {
        processMessages();
        // Fallback if processMessages doesn't find anything
        if (!messageBuffer.userPrompt || !messageBuffer.assistantResponse) {
          captureTranscriptFallback();
        }
      }, 1000);
    }
  });

  // Start observing when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      observer.observe(document.body, {
        childList: true,
        subtree: true
      });
      processMessages();
    });
  } else {
    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
    processMessages();
  }

  // Also process on page navigation (SPA)
  let lastUrl = location.href;
  new MutationObserver(() => {
    const url = location.href;
    if (url !== lastUrl) {
      lastUrl = url;
      setTimeout(processMessages, 2000);
    }
  }).observe(document, { subtree: true, childList: true });

  console.log('[Decision Engine] Content script loaded');
})();
