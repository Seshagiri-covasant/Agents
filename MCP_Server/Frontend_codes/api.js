// File: src/api.js
// Complete and updated

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8080';

/**
 * Handles API responses, parsing JSON and throwing errors for non-ok statuses.
 * @param {Response} response - The fetch Response object.
 * @returns {Promise<any>} - The parsed JSON data.
 * @throws {Error} - Throws an error with details if response is not ok.
 */
async function handleResponse(response) {
  if (response.ok) {
    // For 204 No Content, response.json() will fail. Return a success indicator or null.
    // Your current endpoints mostly return JSON, so this might only be for future-proofing.
    if (response.status === 204) {
      return { success: true, message: "Operation successful, no content." };
    }
    // Check if content-type is JSON before trying to parse
    const contentType = response.headers.get("content-type");
    if (contentType && contentType.includes("application/json")) {
        return response.json();
    }
    // If not JSON, but still OK, return text (or handle as needed)
    return response.text(); 
  }

  // Attempt to parse error detail from JSON, otherwise use status text
  let errorData;
  try {
    errorData = await response.json();
  } catch (e) {
    // If response is not JSON or JSON parsing fails
    const textError = await response.text();
    errorData = { detail: textError || response.statusText || `Server error: ${response.status}` };
  }
  throw new Error(errorData.detail || `HTTP ${response.status}`);
}

/**
 * Initiates a streaming chat session with the backend.
 * @param {object} payload - The data to send for the chat request.
 * @param {function} onData - Callback function to handle incoming data chunks.
 * @param {AbortSignal} signal - AbortSignal to allow aborting the fetch request.
 */
export async function chatStream(payload, onData, signal) {
  try {
    console.log("--- 1. [API.JS] Preparing to fetch /chat_stream with payload:", payload);

    const response = await fetch(`${API_BASE_URL}/chat_stream`, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream' 
      },
      body: JSON.stringify(payload),
      signal, // Pass the AbortSignal to the fetch request
    });
    
    console.log(`--- 2. [API.JS] Fetch response received for /chat_stream. Status: ${response.status}, OK: ${response.ok}`);

    if (!response.ok || !response.body) {
      const errorText = await response.text().catch(() => `Failed to get error text, status: ${response.status}`);
      console.error("--- X. [API.JS] ERROR in /chat_stream: Response not OK or body is missing. Status:", response.status, "Error Text:", errorText);
      throw new Error(`HTTP ${response.status}: ${errorText || 'Server error or no stream body'}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    console.log("--- 3. [API.JS] Starting to read from /chat_stream...");

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        console.log("--- 4. [API.JS] /chat_stream finished.");
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      // SSE messages are separated by double newlines ('\n\n')
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const messageString = buffer.substring(0, boundary);
        buffer = buffer.substring(boundary + 2); // Consume the message and the delimiter
        if (messageString.startsWith('data: ')) {
          try {
            const jsonData = JSON.parse(messageString.substring(6)); // Remove 'data: ' prefix
            onData(jsonData);
          } catch (e) { 
            console.error('--- X. [API.JS] SSE Parse Error in /chat_stream:', e, "Original string:", messageString); 
          }
        } else if (messageString.trim() !== '') {
            // Log other non-empty lines that are not data events (e.g., comments, id, event type)
            // console.log("--- [API.JS] SSE Non-data line:", messageString);
        }
      }
    }
  } catch (error) {
    // AbortError is expected if the user cancels the stream, don't log as critical
    if (error.name === 'AbortError') {
        console.log("--- [API.JS] /chat_stream fetch aborted by client.");
    } else {
        console.error("--- X. [API.JS] CRITICAL FETCH ERROR in chatStream:", error);
    }
    throw error; // Re-throw to be caught by App.js or calling function
  }
}

/**
 * Fetches the summary list of chat history for a client.
 * @param {string} clientSessionId - The client's session ID.
 * @returns {Promise<Array<object>>} - A promise that resolves to an array of history summary objects.
 */
export async function fetchHistorySummary(clientSessionId) {
  console.log(`--- [API.JS] Fetching history summary for client: ${clientSessionId}`);
  const response = await fetch(`${API_BASE_URL}/history/summary_list?client_session_id=${encodeURIComponent(clientSessionId)}`);
  return handleResponse(response);
}

/**
 * Fetches the full message history for a specific conversation.
 * @param {string} convId - The conversation ID.
 * @returns {Promise<object>} - A promise that resolves to an object containing messages.
 */
export async function fetchConversation(convId) {
  console.log(`--- [API.JS] Fetching conversation details for ID: ${convId}`);
  const response = await fetch(`${API_BASE_URL}/history/conversation_by_id?conversation_id=${encodeURIComponent(convId)}`);
  return handleResponse(response);
}

/**
 * Uploads a file to the agent for processing.
 * @param {string} clientSessionId - The client's session ID.
 * @param {File} file - The file object to upload.
 * @returns {Promise<object>} - A promise that resolves to the server's response.
 */
export async function uploadFile(clientSessionId, file) {
  console.log(`--- [API.JS] Uploading file: ${file.name} for client: ${clientSessionId}`);
  const formData = new FormData();
  // Backend endpoint /upload_for_agent expects 'session_id' as the form field name
  formData.append('session_id', clientSessionId); 
  formData.append('file', file); // 'file' is the standard field name for the file itself

  const response = await fetch(`${API_BASE_URL}/upload_for_agent`, { 
    method: 'POST', 
    body: formData 
    // IMPORTANT: Do NOT set 'Content-Type' header when using FormData with fetch.
    // The browser will set it correctly, including the multipart boundary.
  });
  return handleResponse(response);
}

/**
 * Sends a request to the backend to clear the currently active file context for a session.
 * @param {string} clientSessionId - The client's session ID.
 * @returns {Promise<object>} - A promise that resolves to the server's response.
 */
export async function clearFileContext(clientSessionId) {
  console.log(`--- [API.JS] Clearing file context for client: ${clientSessionId}`);
  const response = await fetch(`${API_BASE_URL}/clear_file_context`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_session_id: clientSessionId }), // Backend expects 'client_session_id' in JSON body
  });
  return handleResponse(response);
}
