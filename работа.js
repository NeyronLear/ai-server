// Configuration - Update these to match your Python server
        const API_ENDPOINT = '/chat'; // Change endpoint if needed

        // DOM elements
        const chatMessages = document.getElementById('chatMessages');
        const chatInput = document.getElementById('chatInput');
        const sendButton = document.getElementById('sendButton');
        const typingIndicator = document.getElementById('typingIndicator');
        const serverStatus = document.getElementById('serverStatus');
        const serverStatusSetting = document.getElementById('serverStatusSetting')
        
        // Image upload elements
        const imageUploadContainer = document.getElementById('imageUploadContainer');
        const imageUploadInput = document.getElementById('imageUploadInput');
        const imagePreviewContainer = document.getElementById('imagePreviewContainer');
        const imageToggleButton = document.getElementById('imageToggleButton');
        
        // Settings elements
        const settingsButton = document.getElementById('settingsButton');
        const settingsPanel = document.getElementById('settingsPanel');
        const settingsOverlay = document.getElementById('settingsOverlay');
        const closeSettings = document.getElementById('closeSettings');
        const SERVER_URL = document.getElementById('settingServer');
        const serverButton = document.getElementById('serverButton');
        const systemPrompt = document.getElementById('systemPrompt');
        const temperatureSlider = document.getElementById('temperatureSlider');
        const temperatureValue = document.getElementById('temperatureValue');
        const topPSlider = document.getElementById('topPSlider');
        const topPValue = document.getElementById('topPValue');
        const resetSettings = document.getElementById('resetSettings');

        // Image state
        let uploadedImages = []; // Array of {base64, preview}

        // Settings state
        let currentSettings = {
            serverUrl: '',
            systemPrompt: '',
            temperature: 0.7,
            topP: 0.9
        };

        // Load settings from localStorage
        function loadSettings() {
            const saved = localStorage.getItem('aiChatSettings');
            if (saved) {
                try {
                    currentSettings = JSON.parse(saved);
                    SERVER_URL.value = currentSettings.serverUrl || '';
                    systemPrompt.value = currentSettings.systemPrompt || '';
                    temperatureSlider.value = currentSettings.temperature || 0.7;
                    topPSlider.value = currentSettings.topP || 0.9;
                    updateSliderValues();
                } catch (e) {
                    console.error('Error loading settings:', e);
                }
            }
        }

        // Save settings to localStorage
        function saveSettings() {
            currentSettings = {
                serverUrl: SERVER_URL.value,
                systemPrompt: systemPrompt.value,
                temperature: parseFloat(temperatureSlider.value),
                topP: parseFloat(topPSlider.value)
            };
            localStorage.setItem('aiChatSettings', JSON.stringify(currentSettings));
        }

        // Update slider value displays
        function updateSliderValues() {
            temperatureValue.textContent = temperatureSlider.value;
            topPValue.textContent = topPSlider.value;
        }

        // Settings panel controls
        settingsButton.addEventListener('click', () => {
            settingsPanel.classList.add('open');
            settingsOverlay.classList.add('active');
        });

        closeSettings.addEventListener('click', closeSettingsPanel);
        settingsOverlay.addEventListener('click', closeSettingsPanel);

        function closeSettingsPanel() {
            settingsPanel.classList.remove('open');
            settingsOverlay.classList.remove('active');
            saveSettings();
        }

        // Update slider displays on change
        temperatureSlider.addEventListener('input', () => {
            updateSliderValues();
            saveSettings();
        });

        topPSlider.addEventListener('input', () => {
            updateSliderValues();
            saveSettings();
        });

        // Save settings when system prompt and URL changes
        systemPrompt.addEventListener('input', saveSettings);
        SERVER_URL.addEventListener('input', saveSettings);
        serverButton.addEventListener('click', testConnection);

        // Reset settings
        resetSettings.addEventListener('click', () => {
            if (confirm('Reset all settings to defaults?')) {
                currentSettings = {
                    serverUrl: '',
                    systemPrompt: '',
                    temperature: 0.7,
                    topP: 0.9
                };
                SERVER_URL.value = '';
                systemPrompt.value = '';
                temperatureSlider.value = 0.7;
                topPSlider.value = 0.9;
                updateSliderValues();
                saveSettings();
            }
        });

        // Auto-resize textarea
        chatInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });

        // Send message on Enter (Shift+Enter for new line)
        chatInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // Send button click
        sendButton.addEventListener('click', sendMessage);

        // Function to convert image file to base64
        function imageToBase64(file) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => {
                    // Remove data:image/...;base64, prefix if present, or keep it
                    const base64 = reader.result;
                    resolve(base64);
                };
                reader.onerror = reject;
                reader.readAsDataURL(file);
            });
        }

        // Function to add image preview
        function addImagePreview(file, base64) {
            const previewDiv = document.createElement('div');
            previewDiv.className = 'image-preview';
            
            const img = document.createElement('img');
            img.src = base64;
            img.alt = 'Preview';
            
            const removeButton = document.createElement('button');
            removeButton.className = 'image-preview-remove';
            removeButton.textContent = '×';
            removeButton.onclick = () => {
                const index = uploadedImages.findIndex(img => img.base64 === base64);
                if (index > -1) {
                    uploadedImages.splice(index, 1);
                }
                previewDiv.remove();
                if (uploadedImages.length === 0) {
                    imageUploadContainer.classList.remove('active');
                }
            };
            
            previewDiv.appendChild(img);
            previewDiv.appendChild(removeButton);
            imagePreviewContainer.appendChild(previewDiv);
            
            uploadedImages.push({ base64, preview: previewDiv });
        }

        // Handle image upload
        imageUploadInput.addEventListener('change', async (e) => {
            const files = Array.from(e.target.files);
            for (const file of files) {
                if (file.type.startsWith('image/')) {
                    try {
                        const base64 = await imageToBase64(file);
                        addImagePreview(file, base64);
                        imageUploadContainer.classList.add('active');
                    } catch (error) {
                        console.error('Error processing image:', error);
                        alert('Error processing image: ' + error.message);
                    }
                }
            }
            // Reset input to allow selecting the same file again
            e.target.value = '';
        });

        // Toggle image upload container
        imageToggleButton.addEventListener('click', () => {
            imageUploadContainer.classList.toggle('active');
        });

        // Function to add message to chat
        function addMessage(content, isUser, images = null) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${isUser ? 'user' : 'ai'}`;
            
            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content';
            
            // Add text content
            if (content) {
                const textNode = document.createTextNode(content);
                contentDiv.appendChild(textNode);
            }
            
            // Add images if present
            if (images && images.length > 0) { 
                images.forEach(imgBase64 => {
                    const img = document.createElement('img');
                    img.src = imgBase64;
                    img.className = 'message-image';
                    img.alt = 'Attached image';
                    contentDiv.appendChild(img);
                });
            }
            
            const timeDiv = document.createElement('div');
            timeDiv.className = 'message-time';
            timeDiv.textContent = isUser ? 'Вы' : 'Ваш Архимед';
            
            messageDiv.appendChild(contentDiv);
            messageDiv.appendChild(timeDiv);
            chatMessages.appendChild(messageDiv);
            
            // Scroll to bottom
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        // Function to show/hide typing indicator
        function showTypingIndicator(show) {
            if (show) {
                typingIndicator.classList.add('active');
                chatMessages.scrollTop = chatMessages.scrollHeight;
            } else {
                typingIndicator.classList.remove('active');
            }
        }

        // Function to update server status
        function updateServerStatus(connected) {
            if (connected) {
                serverStatus.textContent = '✓ Connected to server';
                serverStatus.className = 'server-status connected';
                serverStatusSetting.textContent = '✓ Connected to server';
                serverStatusSetting.className = 'server-status-setting connected';
            } else {
                serverStatus.textContent = '✗ Disconnected from server';
                serverStatus.className = 'server-status disconnected';
                serverStatusSetting.textContent = '✗ Disconnected from server';
                serverStatusSetting.className = 'server-status-setting disconnected';
            }
        }

        // Function to send message to server
        async function sendMessage() {
            const message = chatInput.value.trim();
            const imagesToSend = uploadedImages.map(img => img.base64);
            
            // Allow sending even if message is empty if there are images
            if (!message && imagesToSend.length === 0) {
                return;
            }

            // Add user message to chat with images
            addMessage(message || '(image only)', true, imagesToSend.length > 0 ? imagesToSend : null);
            
            // Clear input and images
            chatInput.value = '';
            chatInput.style.height = 'auto';
            uploadedImages = [];
            imagePreviewContainer.innerHTML = '';
            imageUploadContainer.classList.remove('active');
            
            // Disable input and send button
            chatInput.disabled = true;
            sendButton.disabled = true;
            imageToggleButton.disabled = true;
            
            // Show typing indicator
            showTypingIndicator(true);

            try {
                // Prepare request body
                const requestBody = {
                    message: message || '',
                    temperature: parseFloat(temperatureSlider.value),
                    top_p: parseFloat(topPSlider.value),
                    system_prompt: systemPrompt.value.trim() || null,
                    do_sample: true
                };
                
                // Add images if any
                if (imagesToSend.length > 0) {
                    requestBody.images = imagesToSend;
                }
                
                // Send request to server with current settings
                const response = await fetch(`${serverUrl}${API_ENDPOINT}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(requestBody)
                });

                if (!response.ok) {
                    throw new Error(`Server error: ${response.status}`);
                }

                const data = await response.json();
                
                // Hide typing indicator
                showTypingIndicator(false);
                
                // Add AI response to chat
                // Adjust based on your server's response format
                const aiResponse = data.response || 'No response received';
                addMessage(aiResponse, false);
                
                updateServerStatus(true);

            } catch (error) {
                console.error('Error:', error);
                
                // Hide typing indicator
                showTypingIndicator(false);
                
                // Show error message
                addMessage(`Error: ${error.message}. Please check if the server is running on ${serverUrl}`, false);
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
            try {
                console.log(currentSettings.serverUrl);
                const response = await fetch(`${currentSettings.serverUrl}`);
                if (response.ok) {
                    updateServerStatus(true);
                    showBanner();
                } else {
                    updateServerStatus(false);
                    showBanner();
                }
            } catch (error) {
                console.log(error);
                console.clear();
                updateServerStatus(false);
                showBanner();
            }
        }

        async function showBanner() {
            const banner = document.getElementById("banner");
            if (serverStatus.textContent == '✗ Disconnected from server' || serverStatus.textContent == 'Waiting for connection') {
                banner.className = "banner show";
            } else {
                banner.className = "banner";
            }
        }

        // Initialize
        loadSettings();
        testConnection();
        showBanner();
        chatInput.focus();