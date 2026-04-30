// Configuration - Update these to match your Python server
const API_ENDPOINT = "/chat"; // Change endpoint if needed
const LOGIN_ENDPOINT = "/auth/login";
const ADMIN_PASSWORD = "admin123"; // Default admin password - change in production
const ADMIN_LOGIN = "bebra";

// DOM elements
const loginScreen = document.getElementById("loginScreen");
const appContainer = document.getElementById("appContainer");
const loginMode = document.getElementById("loginMode");
const adminPasswordGroup = document.getElementById("adminPasswordGroup");
const userPasswordGroup = document.getElementById("userPasswordGroup");
const usernameInput = document.getElementById("usernameInput");
const adminPassword = document.getElementById("adminPassword");
const userPassword = document.getElementById("userPassword");
const loginButton = document.getElementById("loginButton");
const logoutButton = document.getElementById("logoutButton");
const userAvatar = document.getElementById("userAvatar");
const headerUser = document.getElementById("headerUser");
const headerRole = document.getElementById("headerRole");
const adminPanelButton = document.getElementById("adminPanelButton");
const adminPanel = document.getElementById("adminPanel");
const adminOverlay = document.getElementById("adminOverlay");
const closeAdminPanel = document.getElementById("closeAdminPanel");
const adminLogout = document.getElementById("adminLogout");
const adminServerUrl = document.getElementById("adminServerUrl");
const adminSystemPrompt = document.getElementById("adminSystemPrompt");
const saveServerSettings = document.getElementById("saveServerSettings");
const userList = document.getElementById("userList");
const addUserBtn = document.getElementById("addUserBtn");
const totalUsers = document.getElementById("totalUsers");
const activeUsers = document.getElementById("activeUsers");
const menuToggle = document.getElementById("menuToggle");
const sidebar = document.getElementById("sidebar");
const settingsBtn = document.getElementById("settingsBtn");
const serverStatusIndicator = document.getElementById("serverStatusIndicator");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const chatList = document.getElementById("chatList");

const chatMessages = document.getElementById("chatMessages");
const chatInput = document.getElementById("chatInput");
const sendButton = document.getElementById("sendButton");
const typingIndicator = document.getElementById("typingIndicator");

// Image upload elements
const imageUploadContainer = document.getElementById("imageUploadContainer");
const imageUploadInput = document.getElementById("imageUploadInput");
const imagePreviewContainer = document.getElementById("imagePreviewContainer");
const imageToggleButton = document.getElementById("imageToggleButton");

// Settings elements
const settingsButton = document.getElementById("settingsBtn");
const settingsPanel = document.getElementById("settingsPanel");
const settingsOverlay = document.getElementById("settingsOverlay");
const closeSettings = document.getElementById("closeSettings");
const SERVER_URL = document.getElementById("settingServer");
const serverButton = document.getElementById("serverButton");
const systemPrompt = document.getElementById("systemPrompt");
const temperatureSlider = document.getElementById("temperatureSlider");
const temperatureValue = document.getElementById("temperatureValue");
const topPSlider = document.getElementById("topPSlider");
const topPValue = document.getElementById("topPValue");
const resetSettings = document.getElementById("resetSettings");

// Image state
let uploadedImages = []; // Array of {base64, preview}

// Settings state
let currentSettings = {
  serverUrl: "",
  systemPrompt: "",
  temperature: 0.7,
  topP: 0.9,
};

// User state
let currentUser = {
  username: "Пользователь",
  role: "user", // 'user' or 'admin'
};

// Current chat session id (used for DB history on backend)
let currentSessionId = `chat_${Date.now()}`;

// Sidebar sessions loaded from backend
let chatSessions = [];

// Users database (stored on backend server)
let usersDatabase = [];

// Load settings from localStorage
function loadSettings() {
  const saved = localStorage.getItem("aiChatSettings");
  if (saved) {
    try {
      currentSettings = JSON.parse(saved);
      SERVER_URL.value = currentSettings.serverUrl || "";
      systemPrompt.value = currentSettings.systemPrompt || "";
      temperatureSlider.value = currentSettings.temperature || 0.7;
      topPSlider.value = currentSettings.topP || 0.9;
      updateSliderValues();
    } catch (e) {
      console.error("Error loading settings:", e);
    }
  }
}

async function loadUsersDatabase() {
  const serverUrl = getServerBaseUrl();
  if (!serverUrl) {
    usersDatabase = [];
    renderUserList();
    totalUsers.textContent = "0";
    return;
  }
  try {
    const response = await fetch(`${serverUrl}/users`);
    if (!response.ok) {
      throw new Error(`Ошибка загрузки пользователей: ${response.status}`);
    }
    const data = await response.json();
    usersDatabase = Array.isArray(data.items) ? data.items : [];
    renderUserList();
    totalUsers.textContent = String(usersDatabase.length);
  } catch (error) {
    console.error("Error loading users:", error);
    usersDatabase = [];
    renderUserList();
    totalUsers.textContent = "0";
  }
}

async function saveUsersDatabase() {
  // Users are persisted through backend API calls.
  await loadUsersDatabase();
}

// Load user from localStorage
function loadUser() {
  const saved = localStorage.getItem("aiChatUser");
  if (saved) {
    try {
      currentUser = JSON.parse(saved);
      return true;
    } catch (e) {
      console.error("Error loading user:", e);
      return false;
    }
  }
  return false;
}

// Clear all user data
function clearAllUserData() {
  localStorage.removeItem("aiChatUser");
  localStorage.removeItem("aiChatUsersDB");
  currentUser = { username: "Пользователь", role: "user" };
  usersDatabase = [];
}

// Toggle login mode (user/admin)
function toggleLoginMode() {
  const mode = loginMode.value;
  if (mode === "admin") {
    userPasswordGroup.style.display = "none";
    adminPasswordGroup.style.display = "flex";
    adminPassword.focus();
  } else {
    userPasswordGroup.style.display = "flex";
    adminPasswordGroup.style.display = "none";
    usernameInput.focus();
  }
}

// Initialize app
function initializeApp() {
  // Always clear user data on load
  clearAllUserData();
  loadSettings();
  showLoginScreen();
}

// Show login screen
function showLoginScreen() {
  loginScreen.style.display = "flex";
  appContainer.style.display = "none";
  loginMode.value = "user";
  toggleLoginMode();
  // Clear current user data when showing login
  currentUser = { username: "Пользователь", role: "user" };
}

// Show chat interface
function showChatInterface() {
  loginScreen.style.display = "none";
  appContainer.style.display = "flex";
  headerUser.textContent = currentUser.username;
  userAvatar.textContent = currentUser.username.charAt(0).toUpperCase();

  // Set role badge
  if (currentUser.role === "admin") {
    headerRole.textContent = "Администратор";
    headerRole.className = "user-role admin";
    document.getElementById("adminSection").style.display = "block";
  } else {
    headerRole.textContent = "Пользователь";
    headerRole.className = "user-role user";
    document.getElementById("adminSection").style.display = "none";
  }

  // Update settings based on role
  updateSettingsByRole();

  testConnection();
  loadChatSessions();
  chatInput.focus();
}

// Update settings visibility based on role
function updateSettingsByRole() {
  const adminElements = document.querySelectorAll(".admin-only");
  adminElements.forEach((el) => {
    if (currentUser.role === "admin") {
      el.classList.add("visible");
    } else {
      el.classList.remove("visible");
    }
  });
}

// Login function
async function login() {
  const mode = loginMode.value;
  const username = usernameInput.value.trim();
  const password =
    mode === "admin" ? adminPassword.value.trim() : userPassword.value.trim();

  if (username == "") {
    window.alert("Пожалуйста, введите логин");
    return;
  }
  if (!password) {
    window.alert("Пожалуйста, введите пароль");
    return;
  }

  if (
    mode === "admin" &&
    username === ADMIN_LOGIN &&
    password === ADMIN_PASSWORD
  ) {
    currentUser = {
      username: ADMIN_LOGIN,
      role: "admin",
    };
    showChatInterface();
  }

  const serverUrl = getServerBaseUrl();
  if (!serverUrl) {
    window.alert("Сначала укажите URL сервера в настройках");
    return;
  }

  loginButton.disabled = true;
  try {
    const response = await fetch(`${serverUrl}${LOGIN_ENDPOINT}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        password,
        mode,
      }),
    });

    if (!response.ok) {
      let detail = `Ошибка входа: ${response.status}`;
      try {
        const errorData = await response.json();
        detail = errorData.detail || detail;
      } catch {
        // keep fallback detail
      }
      throw new Error(detail);
    }

    const data = await response.json();
    const user = data?.item;
    if (!user?.username || !user?.role) {
      throw new Error("Сервер вернул некорректный ответ");
    }

    currentUser = {
      username: user.username,
      role: user.role,
    };
    showChatInterface();
  } catch (error) {
    console.error("Login error:", error);
    window.alert(error.message || "Не удалось выполнить вход");
  } finally {
    loginButton.disabled = false;
  }
}

// Logout function
function logout() {
  if (confirm("Вы уверены, что хотите выйти?")) {
    clearAllUserData();
    usernameInput.value = "";
    adminPassword.value = "";
    showLoginScreen();
  }
}

// Clear saved user (for testing)
function clearSavedUser() {
  localStorage.removeItem("aiChatUser");
  currentUser = { username: "Пользователь", role: "user" };
  location.reload();
}

// Force logout - call from console if needed
window.forceLogout = function () {
  localStorage.removeItem("aiChatUser");
  console.log("Пользователь вышел. Обновите страницу.");
};

// Force logout - call from console if needed
window.forceLogout = function () {
  localStorage.removeItem("aiChatUser");
  console.log("Пользователь вышел. Обновите страницу.");
};

// Admin panel functions
function showAdminPanel() {
  adminPanel.classList.add("open");
  adminOverlay.classList.add("active");
  loadAdminData();
}

function closeAdminPanelFunc() {
  adminPanel.classList.remove("open");
  adminOverlay.classList.remove("active");
}

async function loadAdminData() {
  // Load server settings
  adminServerUrl.value = currentSettings.serverUrl || "";
  adminSystemPrompt.value = currentSettings.systemPrompt || "";

  // Load users list
  await loadUsersDatabase();

  // Update stats
  totalUsers.textContent = usersDatabase.length;
  activeUsers.textContent = 1; // Current user
}

function renderUserList() {
  userList.innerHTML = "";
  usersDatabase.forEach((user, index) => {
    const userItem = document.createElement("div");
    userItem.className = "user-item";
    userItem.innerHTML = `
                    <div class="user-item-info">
                        <span class="user-item-name">${user.username}</span>
                        <span class="user-item-role ${user.role}">${user.role === "admin" ? "Админ" : "👤 Пользователь"}</span>
                    </div>
                    <div class="user-item-actions">
                        <button class="user-item-btn edit" onclick="editUser(${user.id})">✏️</button>
                        ${user.role !== "admin" ? `<button class="user-item-btn delete" onclick="deleteUser(${user.id})">🗑️</button>` : ""}
                    </div>
                `;
    userList.appendChild(userItem);
  });
}

async function addUser() {
  const username = prompt("Введите имя пользователя:");
  if (!username) return;

  const userPassword = prompt("Введите пароль пользователя:");
  if (!userPassword) return;

  const role = confirm(
    "Сделать администратором? (OK = админ, Отмена = пользователь)",
  );

  const serverUrl = getServerBaseUrl();
  if (!serverUrl) {
    alert("URL сервера не настроен");
    return;
  }

  try {
    const response = await fetch(`${serverUrl}/users`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: username.trim(),
        role: role ? "admin" : "user",
        user_role: currentUser.role,
        user_password: userPassword.trim(),
      }),
    });
    if (!response.ok) {
      const message = await response.text();
      throw new Error(message || `Ошибка сервера: ${response.status}`);
    }
    await saveUsersDatabase();
  } catch (error) {
    console.error("Error adding user:", error);
    alert(`Не удалось добавить пользователя: ${error.message}`);
  }
}

async function editUser(userId) {
  const user = usersDatabase.find((item) => item.id === userId);
  if (!user) return;
  const newUsername = prompt("Изменить имя пользователя:", user.username);
  if (newUsername) {
    const serverUrl = getServerBaseUrl();
    if (!serverUrl) {
      alert("URL сервера не настроен");
      return;
    }

    try {
      const response = await fetch(
        `${serverUrl}/users/${encodeURIComponent(userId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: newUsername.trim(),
            user_role: currentUser.role,
          }),
        },
      );
      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || `Ошибка сервера: ${response.status}`);
      }
      await saveUsersDatabase();
    } catch (error) {
      console.error("Error editing user:", error);
      alert(`Не удалось обновить пользователя: ${error.message}`);
    }
  }
}

async function deleteUser(userId) {
  if (confirm("Удалить этого пользователя?")) {
    const serverUrl = getServerBaseUrl();
    if (!serverUrl) {
      alert("URL сервера не настроен");
      return;
    }

    try {
      const response = await fetch(
        `${serverUrl}/users/${encodeURIComponent(userId)}?user_role=${encodeURIComponent(currentUser.role)}`,
        {
          method: "DELETE",
        },
      );
      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || `Ошибка сервера: ${response.status}`);
      }
      await saveUsersDatabase();
    } catch (error) {
      console.error("Error deleting user:", error);
      alert(`Не удалось удалить пользователя: ${error.message}`);
    }
  }
}

async function saveAdminServerSettings() {
  const newGlobalPrompt = adminSystemPrompt.value.trim();

  try {
    const requestBody = {
      new_prompt: newGlobalPrompt,
      user_role: currentUser.role,
    };

    // Save on server
    const serverUrl = getServerBaseUrl();
    if (!serverUrl) {
      throw new Error("URL сервера не настроен");
    }

    const response = await fetch(`${serverUrl}/admin/update-prompt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      throw new Error(`Ошибка сервера: ${response.status}`);
    }

    // Sync regular settings panel with admin values, then persist.
    SERVER_URL.value = adminServerUrl.value.trim();
    systemPrompt.value = adminSystemPrompt.value.trim();
    saveSettings();

    alert("Настройки сервера сохранены!");
  } catch (error) {
    console.error("Шайтан машина не делать:", error);
    alert(
      "Не удалось сохранить настройки, зайдите в консоль для подробной информации",
    );
  }
}

function adminLogoutFunc() {
  if (confirm("Выйти из админ-панели?")) {
    closeAdminPanelFunc();
    logout();
  }
}

// Save settings to localStorage
function saveSettings() {
  currentSettings = {
    serverUrl: SERVER_URL.value,
    systemPrompt: systemPrompt.value,
    temperature: parseFloat(temperatureSlider.value),
    topP: parseFloat(topPSlider.value),
  };
  localStorage.setItem("aiChatSettings", JSON.stringify(currentSettings));
}

// Update slider value displays
function updateSliderValues() {
  temperatureValue.textContent = temperatureSlider.value;
  topPValue.textContent = topPSlider.value;
}

// Auto-resize textarea
chatInput.addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = this.scrollHeight + "px";
});

// Send message on Enter (Shift+Enter for new line)
chatInput.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// Send button click
sendButton.addEventListener("click", sendMessage);

// Function to convert image file to base64
function imageToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const base64 = reader.result;
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// Function to add image preview
function addImagePreview(file, base64) {
  const previewDiv = document.createElement("div");
  previewDiv.className = "image-preview";

  const img = document.createElement("img");
  img.src = base64;
  img.alt = "Preview";

  const removeButton = document.createElement("button");
  removeButton.className = "image-preview-remove";
  removeButton.textContent = "×";
  removeButton.onclick = () => {
    const index = uploadedImages.findIndex((img) => img.base64 === base64);
    if (index > -1) {
      uploadedImages.splice(index, 1);
    }
    previewDiv.remove();
    if (uploadedImages.length === 0) {
      imageUploadContainer.classList.remove("active");
    }
  };

  previewDiv.appendChild(img);
  previewDiv.appendChild(removeButton);
  imagePreviewContainer.appendChild(previewDiv);

  uploadedImages.push({ base64, preview: previewDiv });
}

// Handle image upload
imageUploadInput.addEventListener("change", async (e) => {
  const files = Array.from(e.target.files);
  for (const file of files) {
    if (file.type.startsWith("image/")) {
      try {
        const base64 = await imageToBase64(file);
        addImagePreview(file, base64);
        imageUploadContainer.classList.add("active");
      } catch (error) {
        console.error("Error processing image:", error);
        alert("Error processing image: " + error.message);
      }
    }
  }
  e.target.value = "";
});

// Toggle image upload container
imageToggleButton.addEventListener("click", () => {
  imageUploadContainer.classList.toggle("active");
});

// Function to add message to chat
function addMessage(content, isUser, images = null) {
  const messageDiv = document.createElement("div");
  messageDiv.className = `message ${isUser ? "user" : "ai"}`;

  const contentDiv = document.createElement("div");
  contentDiv.className = "message-content";

  if (content) {
    const textNode = document.createTextNode(content);
    contentDiv.appendChild(textNode);
  }

  if (images && images.length > 0) {
    images.forEach((imgBase64) => {
      const img = document.createElement("img");
      img.src = imgBase64;
      img.className = "message-image";
      img.alt = "Attached image";
      contentDiv.appendChild(img);
    });
  }

  const timeDiv = document.createElement("div");
  timeDiv.className = "message-time";
  timeDiv.textContent = isUser ? "Вы" : "Ваш Архимед";

  messageDiv.appendChild(contentDiv);
  messageDiv.appendChild(timeDiv);
  chatMessages.appendChild(messageDiv);

  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function getServerBaseUrl() {
  return (currentSettings.serverUrl || "").trim().replace(/\/+$/, "");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

function truncateText(text, maxLen = 40) {
  const clean = (text || "").trim();
  if (clean.length <= maxLen) return clean || "Новый чат";
  return `${clean.slice(0, maxLen)}...`;
}

function formatSessionTime(isoDate) {
  if (!isoDate) return "";
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderChatList() {
  if (!chatList) return;
  if (!chatSessions.length) {
    chatList.innerHTML =
      '<div class="chat-item-empty">История пока пуста</div>';
    return;
  }

  chatList.innerHTML = chatSessions
    .map((session) => {
      const title = truncateText(session.first_message || "Новый чат");
      const safeTitle = escapeHtml(title);
      const safeTime = escapeHtml(formatSessionTime(session.last_timestamp));
      const isActive = session.session_id === currentSessionId ? "active" : "";
      const count = Number(session.messages_count || 0);

      return `
                    <div class="chat-item ${isActive}" data-session-id="${session.session_id}">
                        <div class="chat-item-title">${safeTitle}</div>
                        <div class="chat-item-time">${safeTime} • ${count}</div>
                    </div>
                `;
    })
    .join("");

  const items = chatList.querySelectorAll(".chat-item");
  items.forEach((item) => {
    item.addEventListener("click", () => {
      const sessionId = item.dataset.sessionId;
      if (sessionId) {
        loadSessionIntoChat(sessionId);
      }
    });
  });
}

function renderWelcomeMessage() {
  chatMessages.innerHTML = `
                <div class="message ai">
                    <div class="message-content">Привет! Чем я могу вам помочь?</div>
                    <div class="message-time">Ваш Архимед</div>
                </div>
            `;
}

async function loadChatSessions() {
  const serverUrl = getServerBaseUrl();
  if (!serverUrl) {
    chatSessions = [];
    renderChatList();
    return;
  }

  try {
    const username = encodeURIComponent(currentUser.username || "Пользователь");
    const response = await fetch(
      `${serverUrl}/chat/sessions?username=${username}&limit=100`,
    );
    if (!response.ok) {
      throw new Error(`Ошибка загрузки сессий: ${response.status}`);
    }
    const data = await response.json();
    chatSessions = Array.isArray(data.items) ? data.items : [];
    renderChatList();
  } catch (error) {
    console.error("Error loading chat sessions:", error);
    chatSessions = [];
    renderChatList();
  }
}

async function loadSessionIntoChat(sessionId) {
  const serverUrl = getServerBaseUrl();
  if (!serverUrl || !sessionId) return;

  try {
    const response = await fetch(
      `${serverUrl}/chat/history/${encodeURIComponent(sessionId)}?limit=300`,
    );
    if (!response.ok) {
      throw new Error(`Ошибка загрузки истории: ${response.status}`);
    }
    const data = await response.json();
    const items = Array.isArray(data.items) ? data.items.slice().reverse() : [];

    currentSessionId = sessionId;
    chatMessages.innerHTML = "";
    if (!items.length) {
      renderWelcomeMessage();
    } else {
      items.forEach((row) => {
        addMessage(row.user_message || "", true);
        addMessage(row.ai_response || "", false);
      });
    }
    renderChatList();
  } catch (error) {
    console.error("Error loading session history:", error);
    addMessage(`Ошибка загрузки истории: ${error.message}`, false);
  }
}

// Function to show/hide typing indicator
function showTypingIndicator(show) {
  if (show) {
    typingIndicator.classList.add("active");
    chatMessages.scrollTop = chatMessages.scrollHeight;
  } else {
    typingIndicator.classList.remove("active");
  }
}

// Function to update server status
function updateServerStatus(connected) {
  if (connected) {
    statusDot.className = "status-dot connected";
    statusText.textContent = "Подключено";
  } else {
    statusDot.className = "status-dot disconnected";
    statusText.textContent = "Нет подключения";
  }
}

// Function to send message to server
async function sendMessage() {
  const message = chatInput.value.trim();
  const imagesToSend = uploadedImages.map((img) => img.base64);

  // Allow sending even if message is empty if there are images
  if (!message && imagesToSend.length === 0) {
    return;
  }

  // Add user message to chat with images
  addMessage(
    message || "(image only)",
    true,
    imagesToSend.length > 0 ? imagesToSend : null,
  );

  // Clear input and images
  chatInput.value = "";
  chatInput.style.height = "auto";
  uploadedImages = [];
  imagePreviewContainer.innerHTML = "";
  imageUploadContainer.classList.remove("active");

  // Disable input and send button
  chatInput.disabled = true;
  sendButton.disabled = true;
  imageToggleButton.disabled = true;

  // Show typing indicator
  showTypingIndicator(true);

  try {
    // Prepare request body
    const requestBody = {
      message: message || "",
      temperature: parseFloat(temperatureSlider.value),
      top_p: parseFloat(topPSlider.value),
      system_prompt: systemPrompt.value.trim() || null,
      do_sample: true,
      username: currentUser.username || "Пользователь",
      session_id: currentSessionId,
    };

    // Add images if any
    if (imagesToSend.length > 0) {
      requestBody.images = imagesToSend;
    }

    // Send request to server with current settings
    const serverUrl = getServerBaseUrl();
    if (!serverUrl) {
      throw new Error("URL сервера не настроен");
    }

    const response = await fetch(`${serverUrl}${API_ENDPOINT}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      throw new Error(`Server error: ${response.status}`);
    }

    const data = await response.json();

    // Hide typing indicator
    showTypingIndicator(false);

    // Add AI response to chat
    const aiResponse = data.response || "No response received";
    addMessage(aiResponse, false);
    await loadChatSessions();

    updateServerStatus(true);
  } catch (error) {
    console.error("Error:", error);

    // Hide typing indicator
    showTypingIndicator(false);

    // Show error message
    addMessage(`Ошибка: ${error.message}`, false);
    updateServerStatus(false);
  } finally {
    // Re-enable input and send button
    chatInput.disabled = false;
    sendButton.disabled = false;
    imageToggleButton.disabled = false;
    chatInput.focus();
  }
}

// Test server connection on page load
async function testConnection() {
  const serverUrl = getServerBaseUrl();
  if (!serverUrl) {
    updateServerStatus(false);
    return;
  }

  try {
    const response = await fetch(serverUrl);
    if (response.ok) {
      updateServerStatus(true);
    } else {
      updateServerStatus(false);
    }
  } catch (error) {
    console.log(error);
    updateServerStatus(false);
  }
}

// Event listeners
loginMode.addEventListener("change", toggleLoginMode);
loginButton.addEventListener("click", login);
logoutButton.addEventListener("click", logout);
adminPanelButton.addEventListener("click", showAdminPanel);
closeAdminPanel.addEventListener("click", closeAdminPanelFunc);
adminOverlay.addEventListener("click", closeAdminPanelFunc);
adminLogout.addEventListener("click", adminLogoutFunc);
saveServerSettings.addEventListener("click", saveAdminServerSettings);
addUserBtn.addEventListener("click", addUser);
menuToggle.addEventListener("click", () => {
  sidebar.classList.toggle("collapsed");
});
settingsBtn.addEventListener("click", () => {
  settingsPanel.classList.add("open");
  settingsOverlay.classList.add("active");
});

// Settings panel controls
closeSettings.addEventListener("click", closeSettingsPanel);
settingsOverlay.addEventListener("click", closeSettingsPanel);

function closeSettingsPanel() {
  settingsPanel.classList.remove("open");
  settingsOverlay.classList.remove("active");
  saveSettings();
}

// Update slider displays on change
temperatureSlider.addEventListener("input", () => {
  updateSliderValues();
  saveSettings();
});

topPSlider.addEventListener("input", () => {
  updateSliderValues();
  saveSettings();
});

// Save settings when system prompt and URL changes
systemPrompt.addEventListener("input", saveSettings);
SERVER_URL.addEventListener("input", saveSettings);
serverButton.addEventListener("click", testConnection);

// Reset settings
resetSettings.addEventListener("click", () => {
  if (confirm("Сбросить все настройки?")) {
    currentSettings = {
      serverUrl: "",
      systemPrompt: "",
      temperature: 0.7,
      topP: 0.9,
    };
    SERVER_URL.value = "";
    systemPrompt.value = "";
    temperatureSlider.value = 0.7;
    topPSlider.value = 0.9;
    updateSliderValues();
    saveSettings();
  }
});

// Allow Enter key to login
userPassword.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    login();
  }
});

adminPassword.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    login();
  }
});

// New chat button
document.getElementById("newChatBtn").addEventListener("click", () => {
  currentSessionId = `chat_${Date.now()}`;
  renderWelcomeMessage();
  renderChatList();
});

// Make functions global for onclick handlers
window.editUser = editUser;
window.deleteUser = deleteUser;
window.clearSavedUser = clearSavedUser;

// Initialize
initializeApp();

// Add logout button to console for easy access
console.log("Чтобы выйти, выполните: clearSavedUser()");
