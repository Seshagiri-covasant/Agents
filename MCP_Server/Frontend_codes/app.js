// File: src/App.js
// Corrected and Enhanced

import React, { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';
import Sidebar from './Sidebar';
import * as api from './api';
import ChatMessage from './ChatMessage';

const MCP_SERVER_PLOT_URL = process.env.REACT_APP_MCP_SERVER_URL || 'http://localhost:8000'; // Ensure this is correct

function uuidv4() {
  return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
  );
}

const NEW_CHAT_PLACEHOLDER_PREFIX = "new_chat_placeholder_"; // Matches backend if used, or frontend specific

function App() {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [clientSessionId, setClientSessionId] = useState('');
  const [dailyConversationId, setDailyConversationId] = useState(''); // This is the active conversation ID
  const [isStreaming, setIsStreaming] = useState(false);
  const chatWindowRef = useRef(null);
  const fileInputRef = useRef(null);
  const [selectedFile, setSelectedFile] = useState(null); // <-- UNCOMMENTED
  const [uploadStatus, setUploadStatus] = useState('');
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [chatHistoryList, setChatHistoryList] = useState([]); // <-- NEW: For flat history list
  const [activeChatTitle, setActiveChatTitle] = useState('New Chat');
  const abortControllerRef = useRef(null);
  const [isFileContextActive, setIsFileContextActive] = useState(false);

  const startNewChatFlow = useCallback(() => {
    if (isStreaming) {
      abortControllerRef.current?.abort();
      setIsStreaming(false); // Ensure streaming is reset
    }
    setIsFileContextActive(false);
    setMessages([]);
    // Use a placeholder ID that indicates it's a new chat, backend will assign final ID
    const placeholderId = `${NEW_CHAT_PLACEHOLDER_PREFIX}${uuidv4()}`;
    setDailyConversationId(placeholderId);
    setActiveChatTitle("New Chat");
    setInputValue('');
    setUploadStatus('');
    setSelectedFile(null); // Clear selected file
    if (fileInputRef.current) fileInputRef.current.value = ""; // Reset file input
    localStorage.removeItem('activeChatInfo');
  }, [isStreaming]); // Added isStreaming to dependency array for abort logic

  const fetchHistory = useCallback(async (currentClientId) => {
    if (!currentClientId) return;
    setIsLoadingHistory(true);
    try {
      // API returns a flat list: [{id: "...", title: "...", timestamp: "..."}]
      const data = await api.fetchHistorySummary(currentClientId);
      setChatHistoryList(data || []); // <-- Store flat list directly
    } catch (error) {
      console.error("Failed to fetch history:", error);
      setChatHistoryList([]); // Set to empty array on error
    } finally {
      setIsLoadingHistory(false);
    }
  }, []);

  const processDbMessages = useCallback((dbMessages) => {
    return dbMessages
      .map(doc => {
        let text = '';
        let sender = doc.role;
        let htmlContent = null; // For plots or other rich content from history

        if (sender === 'user') {
          if (Array.isArray(doc.content) && doc.content[0]?.type === 'text') {
            text = doc.content[0].text;
          } else if (typeof doc.content === 'string') {
            text = doc.content;
          } else {
            return null;
          }
        } else if (sender === 'assistant') {
          if (typeof doc.content === 'string') {
            text = doc.content;
          } else if (Array.isArray(doc.content) && doc.content[0]?.type === 'text') {
            text = doc.content[0].text;
          } else if (doc.tool_calls && !doc.content) {
            text = `[Assistant used tools: ${doc.tool_calls.map(tc => tc.function.name).join(', ')}]`;
          } else if (doc.content === null || doc.content === undefined) {
             text = ""; // Or a placeholder like "[Thinking...]" if appropriate
          } else {
            // Potentially handle other structured content for assistant if necessary
            // For now, if it's not string or known list structure, treat as empty or stringify
            text = typeof doc.content === 'object' ? JSON.stringify(doc.content) : String(doc.content);
          }
          // Placeholder: If history items were to store plot info directly:
          // if (doc.plot_thumbnail_base64) {
          //   htmlContent = `<img src="data:image/png;base64,${doc.plot_thumbnail_base64}" alt="Plot thumbnail" />`;
          //   if (doc.plot_full_path) {
          //      htmlContent += `<br/><a href="${MCP_SERVER_PLOT_URL}/${doc.plot_full_path}" target="_blank">View full plot</a>`;
          //   }
          // }

        } else if (sender === 'tool') {
          // You might want to display tool results in a summarized way or not at all
          // For now, let's filter them out from direct display in chat window
           console.log("Tool message from history:", doc);
          // text = `[Tool execution: ${doc.name}] Output: ${JSON.stringify(doc.content).substring(0,100)}...`;
          // sender = 'system'; // Or render with a specific style for 'tool'
          return null; // Filter out direct display of raw tool messages for now
        } else {
          return null;
        }
        return { id: doc._id || uuidv4(), sender: sender, text: text, htmlContent: htmlContent, isStreamingDone: true };
      })
      .filter(Boolean);
  }, []);

  const loadConversationFromHistory = useCallback(async (convId, title) => {
    if (!convId || convId.startsWith(NEW_CHAT_PLACEHOLDER_PREFIX)) {
        console.warn("Attempted to load a placeholder chat or invalid ID:", convId);
        // Optionally, start a new chat if user clicks a "New Chat" placeholder from a stale list
        // startNewChatFlow(); 
        return;
    }
    if (isStreaming) {
        abortControllerRef.current?.abort();
        setIsStreaming(false);
    }
    setIsLoadingHistory(true);
    setMessages([]); // Clear current messages before loading new ones
    try {
      const data = await api.fetchConversation(convId); // Expects { messages: [] }
      const processedMessages = processDbMessages(data.messages);
      setMessages(processedMessages);
      setDailyConversationId(convId);
      setActiveChatTitle(title || "Chat History"); // Use provided title
      localStorage.setItem('activeChatInfo', JSON.stringify({ id: convId, title: title || "Chat History" }));
    } catch (error) {
      console.error("Error loading conversation:", error);
      setMessages([{ id: uuidv4(), sender: 'error', text: `Error loading conversation: ${error.message}`, isStreamingDone: true }]);
      setActiveChatTitle("Error");
    } finally {
      setIsLoadingHistory(false);
    }
  }, [processDbMessages, isStreaming]); // Added isStreaming

   useEffect(() => {
    let storedClientId = localStorage.getItem('chatClientSessionId');
    if (!storedClientId) {
      storedClientId = `client-${uuidv4()}`; // Make sure uuidv4() is robust
      localStorage.setItem('chatClientSessionId', storedClientId);
    }
    setClientSessionId(storedClientId);

    const lastChatInfo = localStorage.getItem('activeChatInfo');
    let loadedConversation = false;
    if (lastChatInfo) {
      try {
        const { id, title } = JSON.parse(lastChatInfo);
        if (id && !id.startsWith(NEW_CHAT_PLACEHOLDER_PREFIX)) {
          loadConversationFromHistory(id, title);
          loadedConversation = true;
        }
      } catch (e) {
        console.error("Error parsing lastChatInfo from localStorage", e);
        // Fall through to startNewChatFlow if parsing fails or ID is invalid
      }
    }

    if (!loadedConversation) {
      startNewChatFlow();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // <--- THE IMPORTANT CHANGE IS HERE: EMPTY DEPENDENCY ARRAY
  useEffect(() => {
    if (clientSessionId) fetchHistory(clientSessionId);
  }, [clientSessionId, fetchHistory]);

  useEffect(() => {
    if (chatWindowRef.current) {
      chatWindowRef.current.scrollTo(0, chatWindowRef.current.scrollHeight);
    }
  }, [messages]);

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
      setUploadStatus(''); // Clear previous status
    } else {
      setSelectedFile(null);
    }
  };

  const handleFileUpload = async () => {
    if (!selectedFile || !clientSessionId || isStreaming) return;
    setUploadStatus('Uploading & Processing...');
    setIsFileContextActive(false);
    try {
      // Pass clientSessionId and the file to the API
      const response = await api.uploadFile(clientSessionId, selectedFile);
      setUploadStatus(`Success: ${response.message || 'File processed.'} ${response.mcp_file_path ? '('+response.mcp_file_path+')' : ''}`);
      setIsFileContextActive(true);
      // Add a message to the chat indicating file upload, if desired
      // setMessages(prev => [...prev, {id: uuidv4(), sender: 'system', text: `File "${selectedFile.name}" uploaded. Path: ${response.mcp_file_path}`, isStreamingDone: true}]);
      // setSelectedFile(null); // Optionally clear after upload
      // if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (error) {
      setUploadStatus(`Upload Failed: ${error.message}`);
      setIsFileContextActive(false);
      console.error("File upload error:", error);
    }
  };
  const handleDeleteFileContext = async () => {
    if (!clientSessionId || isStreaming) return;
    setUploadStatus("Clearing file context...");
    try {
        // This new api function needs to be created in api.js
        const response = await api.clearFileContext(clientSessionId); 
        setUploadStatus(response.message || "File context cleared.");
        setSelectedFile(null);
        if (fileInputRef.current) fileInputRef.current.value = "";
        setIsFileContextActive(false); // <--- CLEAR FILE CONTEXT
    } catch (error) {
        setUploadStatus(`Failed to clear file context: ${error.message}`);
        console.error("Clear file context error:", error);
    }
};
  const handleSendMessage = async () => {
    if (inputValue.trim() === '' || isStreaming || !clientSessionId) return;

    // Determine if it's truly a new chat that needs ID assignment from backend
    const isNewChatSession = dailyConversationId.startsWith(NEW_CHAT_PLACEHOLDER_PREFIX);
    const userMessageText = inputValue;

    const userMsgObj = { id: uuidv4(), sender: 'user', text: userMessageText, isStreamingDone: true };
    setMessages(prev => [...prev, userMsgObj]);
    setInputValue('');
    setIsStreaming(true);

    const assistantMsgId = uuidv4();
    const assistantPlaceholder = { id: assistantMsgId, sender: 'assistant', text: '', htmlContent: null, isStreamingDone: false };
    setMessages(prev => [...prev, assistantPlaceholder]);

    abortControllerRef.current = new AbortController();

    const currentDailyConversationId = isNewChatSession ? null : dailyConversationId;

    const payload = {
      client_session_id: clientSessionId,
      message: userMessageText,
      // Send null if it's a new chat session, backend will create and return ID
      // Otherwise, send the existing dailyConversationId
      conversation_id: currentDailyConversationId
    };
    
    let tempNewChatId = dailyConversationId; // Keep placeholder if new, until confirmed

    const handleStreamData = (data) => {
      // Check for conversation_id (for new chats)
      if (isNewChatSession && data.conversation_id) { // Backend sends 'conversation_id'
        const confirmedId = data.conversation_id;
        const newTitle = userMessageText.substring(0, 40) + (userMessageText.length > 40 ? "..." : "");
        setDailyConversationId(confirmedId); // Update to the real ID from backend
        tempNewChatId = confirmedId; // Update for localStorage saving
        setActiveChatTitle(newTitle);
        localStorage.setItem('activeChatInfo', JSON.stringify({ id: confirmedId, title: newTitle }));
        // Refresh history as a new chat has been created
        fetchHistory(clientSessionId);
      }

      if (data.type === 'llm_token') {
        setMessages(prev =>
          prev.map(msg =>
            msg.id === assistantMsgId
              ? { ...msg, text: msg.text + data.content }
              : msg
          )
        );
      } else if (data.type === 'error') {
        setMessages(prev =>
          prev.map(msg =>
            msg.id === assistantMsgId
              ? { ...msg, text: `Stream Error: ${data.content}`, type: 'error', isStreamingDone: true } // Mark done on error
              : msg
          )
        );
      } else if (data.status === 'completed' && data.data && data.data.thumbnail_base64) {
        // This is a tool output, likely a plot
        const plotHtml = `<img src="data:image/png;base64,${data.data.thumbnail_base64}" alt="Plot thumbnail" style="max-width: 200px; max-height: 150px; border: 1px solid #ccc;" />
                          <br/><a href="${MCP_SERVER_PLOT_URL}/${data.data.plot_file_path}" target="_blank" rel="noopener noreferrer">View full plot</a>`;
        setMessages(prev =>
          prev.map(msg =>
            msg.id === assistantMsgId
              ? { ...msg, 
                  htmlContent: (msg.htmlContent || "") + plotHtml + "<br/>", // Append if multiple plots/tool outputs
                  // text: msg.text + (data.message ? `\n${data.message}` : "\n[Plot ready]") // Optional: add text from tool
                }
              : msg
          )
        );
      } else if (data.status === 'started' && data.message) {
         // Optionally show tool "started" messages
         console.log("Tool started:", data.message);
         // Could update assistant message: e.g., msg.text + `\n[Tool working: ${data.message}]`
      }
      // Handle other stream data types if necessary
    };

    try {
      await api.chatStream(payload, handleStreamData, abortControllerRef.current.signal);
    } catch (error) {
      if (error.name !== 'AbortError') {
        console.error("Chat stream error:", error);
        setMessages(prev =>
          prev.map(msg =>
            msg.id === assistantMsgId
              ? { ...msg, text: `Error: ${error.message}`, type: 'error', isStreamingDone: true }
              : msg
          )
        );
      }
    } finally {
      setIsStreaming(false);
      setMessages(prev =>
        prev.map(msg =>
          msg.id === assistantMsgId ? { ...msg, isStreamingDone: true } : msg
        )
      );
      // If it was a new chat and ID was confirmed, or if it was an existing chat,
      // refresh history to reflect new messages.
      // tempNewChatId will be the confirmed ID or the original dailyConversationId
      if (tempNewChatId && !tempNewChatId.startsWith(NEW_CHAT_PLACEHOLDER_PREFIX)) {
         fetchHistory(clientSessionId); // Refresh history after message send completion
      }
    }
  };

  return (
    <div className="App-container">
      <Sidebar
        history={chatHistoryList} // <-- Pass flat list
        loadConversation={loadConversationFromHistory}
        isLoadingHistory={isLoadingHistory} // Pass this for potential UI cues
        startNewChat={startNewChatFlow}
        activeConversationId={dailyConversationId} // <-- Pass current active ID for highlighting
        // File Upload Props
        handleFileChange={handleFileChange}
        isStreaming={isStreaming}
        fileInputRef={fileInputRef}
        selectedFile={selectedFile} // Pass selected file state
        handleFileUpload={handleFileUpload}
        uploadStatus={uploadStatus}
         handleDeleteFileContext={handleDeleteFileContext} // Pass the handler
    isFileContextActive={isFileContextActive} 
      />
      <div className="main-content-area">
        <header className="chat-header">{activeChatTitle}</header>
        <div className="chat-view-container">
          <div className="chat-window" ref={chatWindowRef}>
            {messages.map((msg) => (
              <ChatMessage key={msg.id} msg={msg} />
            ))}
{/*             
             {isStreaming && messages[messages.length-1]?.sender === 'assistant' && !messages[messages.length-1]?.isStreamingDone && (
              <div className="message assistant typing-indicator">
                <span className="cursor" />
              </div>
            )} */}
            
          </div>
          <div className="input-area-wrapper">
            <div className="input-area">
              <input type="text" value={inputValue} onChange={(e) => setInputValue(e.target.value)} onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()} placeholder="Send a message..." disabled={isStreaming} />
              <button onClick={handleSendMessage} disabled={isStreaming || !inputValue.trim()}>Send</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
