// Vladimir Messenger - Frontend Application
class VladimirApp {
    constructor() {
        this.currentContact = null;
        this.broadcastMode = false;
        this.nodeId = '';
        this.contacts = [];
        this.messages = {};
        this.peers = [];
        this.init();
    }

    init() {
        document.addEventListener('DOMContentLoaded', () => {
            this.setupEventListeners();
            this.loadInitialData();
            this.startAutoRefresh();
        });
    }

    setupEventListeners() {
        // Кнопки модальных окон
        document.getElementById('addContactBtn')?.addEventListener('click', () => this.showModal('addContactModal'));
        document.getElementById('closeAddContactModal')?.addEventListener('click', () => this.hideModal('addContactModal'));
        document.getElementById('settingsBtn')?.addEventListener('click', () => this.showModal('settingsModal'));
        document.getElementById('closeSettingsModal')?.addEventListener('click', () => this.hideModal('settingsModal'));
        document.getElementById('closeInfoPanel')?.addEventListener('click', () => this.hideInfoPanel());

        // Вкладки настроек
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchTab(e.target.dataset.tab));
        });

        // Отправка сообщения
        document.getElementById('sendBtn')?.addEventListener('click', () => this.sendMessage());
        document.getElementById('messageInput')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Прикрепление файла
        document.getElementById('attachBtn')?.addEventListener('click', () => {
            document.getElementById('fileInput').click();
        });
        document.getElementById('fileInput')?.addEventListener('change', (e) => this.handleFileSelect(e));

        // Добавление контакта
        document.getElementById('confirmAddContact')?.addEventListener('click', () => this.addContact());

        // Групповой чат
        document.getElementById('groupChatBtn')?.addEventListener('click', () => this.toggleBroadcastMode());
    }

    async loadInitialData() {
        try {
            const [statusRes, contactsRes] = await Promise.all([
                fetch('/api/status'),
                fetch('/api/contacts')
            ]);
            
            const status = await statusRes.json();
            this.contacts = await contactsRes.json();
            this.nodeId = status.node_id || 'unknown';
            
            this.updateStatusUI(status);
            this.renderContacts();
            this.updatePeerCount(status.peer_count || 0);
        } catch (error) {
            console.error('Error loading initial data:', error);
            this.showNotification('Ошибка загрузки данных', 'error');
        }
    }

    startAutoRefresh() {
        setInterval(() => this.updateStatus(), 5000);
        setInterval(() => this.loadPeers(), 10000);
    }

    async updateStatus() {
        try {
            const response = await fetch('/api/status');
            const status = await response.json();
            this.updateStatusUI(status);
        } catch (error) {
            console.error('Error updating status:', error);
        }
    }

    updateStatusUI(status) {
        const modeIndicator = document.getElementById('modeIndicator');
        const connectionStatus = document.getElementById('connectionStatus');
        const statusText = connectionStatus?.querySelector('.status-text');
        
        const modeConfig = {
            'internet': { icon: '🌐', text: 'Интернет', color: '#4CAF50' },
            'lan': { icon: '📶', text: 'Локальная сеть', color: '#2196F3' },
            'ble': { icon: '📱', text: 'BLE Mesh', color: '#FF9800' },
            'offline': { icon: '❌', text: 'Оффлайн', color: '#9E9E9E' }
        };
        
        const config = modeConfig[status.mode_raw] || modeConfig.offline;
        
        if (modeIndicator) {
            modeIndicator.innerHTML = `
                <div class="mode-icon">${config.icon}</div>
                <span>Режим: ${config.text}</span>
            `;
            modeIndicator.style.borderColor = status.mode_raw === 'internet' ? '#4CAF50' : 
                                              status.mode_raw === 'lan' ? '#2196F3' : 
                                              status.mode_raw === 'ble' ? '#FF9800' : '#9E9E9E';
        }
        
        if (statusText) {
            statusText.textContent = status.mode || 'Неизвестно';
        }
        
        this.updatePeerCount(status.peer_count || 0);
    }

    updatePeerCount(count) {
        const peerCountEl = document.getElementById('peerCount');
        if (peerCountEl) {
            peerCountEl.textContent = count;
        }
    }

    renderContacts() {
        const list = document.getElementById('contactsList');
        if (!list) return;
        
        list.innerHTML = '';
        
        if (this.contacts.length === 0) {
            list.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-secondary);">Нет контактов</div>';
            return;
        }
        
        this.contacts.forEach(contact => {
            const item = document.createElement('div');
            item.className = `contact-item${this.currentContact === contact.id ? ' active' : ''}`;
            item.innerHTML = `
                <span class="contact-name" onclick="app.selectContact('${contact.id}', '${contact.name}')">
                    ${contact.name}
                </span>
            `;
            list.appendChild(item);
        });
    }

    async loadPeers() {
        try {
            const response = await fetch('/api/peers');
            this.peers = await response.json();
        } catch (error) {
            console.error('Error loading peers:', error);
        }
    }

    selectContact(contactId, contactName) {
        this.currentContact = contactId;
        this.broadcastMode = false;
        
        document.getElementById('currentChatName').textContent = contactName;
        document.getElementById('currentChatStatus').textContent = 'Онлайн';
        document.getElementById('inputArea').style.display = 'block';
        document.getElementById('welcomeMessage').style.display = 'none';
        
        this.renderContacts();
        this.loadMessages(contactId);
    }

    toggleBroadcastMode() {
        this.broadcastMode = !this.broadcastMode;
        this.currentContact = null;
        
        if (this.broadcastMode) {
            document.getElementById('currentChatName').textContent = '📢 Групповой чат';
            document.getElementById('currentChatStatus').textContent = 'Все узлы в сети';
            document.getElementById('inputArea').style.display = 'block';
            document.getElementById('welcomeMessage').style.display = 'none';
            this.loadBroadcastMessages();
        } else {
            document.getElementById('currentChatName').textContent = 'Выберите контакт';
            document.getElementById('currentChatStatus').textContent = 'Оффлайн';
            document.getElementById('inputArea').style.display = 'none';
            document.getElementById('welcomeMessage').style.display = 'flex';
        }
        
        this.renderContacts();
    }

    async loadMessages(contactId) {
        try {
            const response = await fetch(`/api/messages?contact_id=${contactId}`);
            const messages = await response.json();
            this.displayMessages(messages);
        } catch (error) {
            console.error('Error loading messages:', error);
        }
    }

    loadBroadcastMessages() {
        const messages = window.broadcastMessages || [];
        this.displayMessages(messages);
    }

    displayMessages(messages) {
        const container = document.getElementById('messagesContainer');
        if (!container) return;
        
        container.innerHTML = '';
        
        if (messages.length === 0) {
            container.innerHTML = '<div style="text-align: center; color: var(--text-secondary); padding: 40px;">Нет сообщений</div>';
            return;
        }
        
        messages.forEach(msg => {
            const div = document.createElement('div');
            div.className = `message ${msg.direction}`;
            div.style.cssText = `
                padding: 12px 16px;
                border-radius: 12px;
                max-width: 70%;
                margin-bottom: 8px;
                background: ${msg.direction === 'outgoing' ? 'var(--accent-blue)' : 'var(--bg-tertiary)'};
                align-self: ${msg.direction === 'outgoing' ? 'flex-end' : 'flex-start'};
            `;
            
            const time = new Date(msg.timestamp * 1000).toLocaleTimeString();
            div.innerHTML = `
                <div style="font-size: 13px; margin-bottom: 4px;">${this.escapeHtml(msg.content)}</div>
                <div style="font-size: 11px; opacity: 0.7; text-align: right;">${time}</div>
            `;
            
            container.appendChild(div);
        });
        
        container.scrollTop = container.scrollHeight;
    }

    async sendMessage() {
        const input = document.getElementById('messageInput');
        const content = input?.value.trim();
        
        if (!content) return;
        
        try {
            let response;
            
            if (this.broadcastMode) {
                response = await fetch('/api/messages/broadcast', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content })
                });
            } else if (this.currentContact) {
                response = await fetch('/api/messages', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        recipient_id: this.currentContact,
                        content: content
                    })
                });
            }
            
            if (response?.ok) {
                input.value = '';
                if (this.broadcastMode) {
                    this.loadBroadcastMessages();
                } else {
                    this.loadMessages(this.currentContact);
                }
                this.showNotification('Сообщение отправлено', 'success');
            } else {
                const data = await response?.json();
                this.showNotification(data?.error || 'Ошибка отправки', 'error');
            }
        } catch (error) {
            console.error('Error sending message:', error);
            this.showNotification('Ошибка отправки сообщения', 'error');
        }
    }

    async handleFileSelect(event) {
        const file = event.target.files[0];
        if (!file) return;
        
        if (file.size > 10 * 1024 * 1024) {
            this.showNotification('Файл слишком большой (макс. 10 МБ)', 'error');
            event.target.value = '';
            return;
        }
        
        const formData = new FormData();
        formData.append('file', file);
        
        if (this.currentContact) {
            formData.append('recipient_id', this.currentContact);
        }
        
        try {
            const response = await fetch('/api/files', {
                method: 'POST',
                body: formData
            });
            
            if (response.ok) {
                this.showNotification('Файл отправлен', 'success');
                event.target.value = '';
                if (this.currentContact) {
                    this.loadMessages(this.currentContact);
                }
            } else {
                const data = await response.json();
                this.showNotification(data.error || 'Ошибка отправки файла', 'error');
            }
        } catch (error) {
            console.error('Error sending file:', error);
            this.showNotification('Ошибка отправки файла', 'error');
        }
    }

    async addContact() {
        const name = document.getElementById('contactName')?.value.trim();
        const publicKey = document.getElementById('contactKey')?.value.trim();
        
        if (!name || !publicKey) {
            this.showNotification('Заполните все поля', 'error');
            return;
        }
        
        try {
            const response = await fetch('/api/contacts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, public_key: publicKey })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.hideModal('addContactModal');
                this.contacts.push(data);
                this.renderContacts();
                this.showNotification('Контакт добавлен', 'success');
                
                document.getElementById('contactName').value = '';
                document.getElementById('contactKey').value = '';
            } else {
                this.showNotification(data.error || 'Ошибка добавления контакта', 'error');
            }
        } catch (error) {
            console.error('Error adding contact:', error);
            this.showNotification('Ошибка добавления контакта', 'error');
        }
    }

    showModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('active');
            modal.style.display = 'flex';
        }
    }

    hideModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('active');
            modal.style.display = 'none';
        }
    }

    hideInfoPanel() {
        const panel = document.getElementById('infoPanel');
        if (panel) {
            panel.style.transform = 'translateX(100%)';
        }
    }

    switchTab(tabName) {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });
        
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.toggle('active', content.id === `${tabName}Tab`);
        });
    }

    showNotification(message, type = 'info') {
        const container = document.getElementById('notificationsContainer');
        if (!container) return;
        
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;
        
        container.appendChild(notification);
        
        setTimeout(() => {
            notification.style.opacity = '0';
            notification.style.transform = 'translateX(100%)';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Инициализация приложения
const app = new VladimirApp();
