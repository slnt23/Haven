const USER_ID = '00000000-0000-0000-0000-000000000001';
const API_BASE = '';

let chatStarted = false;

// 自动调整输入框高度
function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

// 键盘事件
function handleKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function handleChatKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
  }
}

// 显示聊天界面
function showChatScreen() {
  document.getElementById('welcome-screen').classList.add('hidden');
  document.getElementById('chat-screen').classList.remove('hidden');
  chatStarted = true;
}

// 添加消息
function addMessage(role, content) {
  const container = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'flex gap-2.5 message-enter';

  if (role === 'user') {
    div.innerHTML =
      '<div class="flex-1"></div>' +
      '<div class="msg-bubble-user rounded-2xl rounded-tr-md px-4 py-3 max-w-xl text-sm text-gray-700 leading-relaxed">' +
      escapeHtml(content) +
      '</div>';
  } else {
    div.innerHTML =
      '<div class="w-7 h-7 rounded-lg bg-primary-500 flex items-center justify-center flex-shrink-0">' +
      '<svg class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">' +
      '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />' +
      '</svg>' +
      '</div>' +
      '<div class="msg-bubble-assistant rounded-2xl rounded-tl-md px-4 py-3 max-w-xl text-sm text-gray-600 leading-relaxed">' +
      formatContent(content) +
      '</div>';
  }

  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

// 打字指示器
function addTyping() {
  const container = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.id = 'typing-indicator';
  div.className = 'flex gap-2.5';
  div.innerHTML =
    '<div class="w-7 h-7 rounded-lg bg-primary-500 flex items-center justify-center flex-shrink-0">' +
    '<svg class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">' +
    '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />' +
    '</svg>' +
    '</div>' +
    '<div class="msg-bubble-assistant rounded-2xl rounded-tl-md px-4 py-3 flex items-center gap-1.5">' +
    '<span class="typing-dot w-1.5 h-1.5 bg-gray-400 rounded-full inline-block"></span>' +
    '<span class="typing-dot w-1.5 h-1.5 bg-gray-400 rounded-full inline-block"></span>' +
    '<span class="typing-dot w-1.5 h-1.5 bg-gray-400 rounded-full inline-block"></span>' +
    '</div>';
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById('typing-indicator');
  if (el) el.remove();
}

// 工具函数
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function formatContent(text) {
  return escapeHtml(text)
    .replace(/\n/g, '<br>')
    .replace(/(\d{2,3}\/\d{2,3})\s*mmHg/g, '<span class="text-primary-600 font-semibold">$1 mmHg</span>');
}

function setLoading(loading) {
  const btn = document.getElementById('chat-send-btn');
  const input = document.getElementById('chat-input');
  btn.disabled = loading;
  input.disabled = loading;
  if (loading) {
    addTyping();
  }
}

// 发送消息
async function sendMessage() {
  const input = document.getElementById('user-input');
  const text = input.value.trim();
  if (!text) return;

  showChatScreen();
  addMessage('user', text);
  input.value = '';
  input.style.height = 'auto';
  setLoading(true);

  try {
    const resp = await fetch(API_BASE + '/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': USER_ID,
      },
      body: JSON.stringify({ message: text }),
    });

    if (!resp.ok && resp.status !== 200) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || '请求失败');
    }

    const data = await resp.json();
    removeTyping();

    if (data.is_emergency) {
      addMessage('assistant', '<span class="text-red-500 font-medium">⚠ 紧急提醒</span><br><br>' + data.reply);
    } else {
      addMessage('assistant', data.reply);
    }
  } catch (e) {
    removeTyping();
    addMessage('assistant', '抱歉，请求失败，请稍后再试。如有紧急情况，请立即拨打 120。');
    console.error(e);
  } finally {
    setLoading(false);
  }
}

async function sendChatMessage() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;

  addMessage('user', text);
  input.value = '';
  input.style.height = 'auto';
  setLoading(true);

  try {
    const resp = await fetch(API_BASE + '/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': USER_ID,
      },
      body: JSON.stringify({ message: text }),
    });

    if (!resp.ok && resp.status !== 200) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || '请求失败');
    }

    const data = await resp.json();
    removeTyping();

    if (data.is_emergency) {
      addMessage('assistant', '<span class="text-red-500 font-medium">⚠ 紧急提醒</span><br><br>' + data.reply);
    } else {
      addMessage('assistant', data.reply);
    }
  } catch (e) {
    removeTyping();
    addMessage('assistant', '抱歉，请求失败，请稍后再试。如有紧急情况，请立即拨打 120。');
    console.error(e);
  } finally {
    setLoading(false);
  }
}

function sendQuick(text) {
  if (!chatStarted) {
    document.getElementById('user-input').value = text;
    sendMessage();
  } else {
    document.getElementById('chat-input').value = text;
    sendChatMessage();
  }
}

// 隐私政策弹窗
async function showConsentModal() {
  const modal = document.getElementById('consent-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');

  const policyText = document.getElementById('consent-policy-text');
  policyText.textContent = '加载中...';

  try {
    const resp = await fetch(API_BASE + '/api/consent/policy', {
      headers: { 'X-User-ID': USER_ID },
    });
    const data = await resp.json();
    policyText.textContent = data.policy;
  } catch (e) {
    policyText.textContent = '加载失败，请稍后重试。';
    console.error(e);
  }
}

function closeConsentModal() {
  const modal = document.getElementById('consent-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

async function agreeConsent() {
  const btn = document.getElementById('consent-agree-btn');
  btn.disabled = true;
  btn.textContent = '提交中...';

  try {
    const resp = await fetch(API_BASE + '/api/consent/agree', {
      method: 'POST',
      headers: { 'X-User-ID': USER_ID },
    });
    const data = await resp.json();

    if (data.success) {
      closeConsentModal();
      addMessage('assistant', '感谢您的确认！隐私政策已生效。如果您有任何问题，随时可以问我。');
    } else {
      alert('提交失败，请重试。');
    }
  } catch (e) {
    alert('请求失败，请重试。');
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.textContent = '同意并继续';
  }
}

// 血压记录弹窗
function showBpModal() {
  const modal = document.getElementById('bp-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.getElementById('bp-systolic').value = '';
  document.getElementById('bp-diastolic').value = '';
  document.getElementById('bp-level-hint').textContent = '';
  setTimeout(() => document.getElementById('bp-systolic').focus(), 100);
}

function closeBpModal() {
  const modal = document.getElementById('bp-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function updateBpLevel() {
  const systolic = parseInt(document.getElementById('bp-systolic').value);
  const diastolic = parseInt(document.getElementById('bp-diastolic').value);
  const hint = document.getElementById('bp-level-hint');

  if (!systolic || !diastolic) {
    hint.textContent = '';
    return;
  }

  let level = '';
  let colorClass = '';

  if (systolic >= 180 || diastolic >= 120) {
    level = '⚠ 严重偏高，请立即就医';
    colorClass = 'bp-severe';
  } else if (systolic >= 160 || diastolic >= 100) {
    level = '3级高血压（重度）';
    colorClass = 'bp-grade-3';
  } else if (systolic >= 140 || diastolic >= 90) {
    level = '2级高血压（中度）';
    colorClass = 'bp-grade-2';
  } else if (systolic >= 130 || diastolic >= 85) {
    level = '1级高血压（轻度）';
    colorClass = 'bp-grade-1';
  } else if (systolic >= 120 || diastolic >= 80) {
    level = '正常高值';
    colorClass = 'bp-high-normal';
  } else {
    level = '正常范围';
    colorClass = 'bp-normal';
  }

  hint.textContent = level;
  hint.className = 'text-xs text-center mb-4 ' + colorClass;
}

async function submitBp() {
  const systolic = document.getElementById('bp-systolic').value;
  const diastolic = document.getElementById('bp-diastolic').value;

  if (!systolic || !diastolic) {
    alert('请输入完整的血压数值');
    return;
  }

  if (systolic < 60 || systolic > 300 || diastolic < 30 || diastolic > 200) {
    alert('血压数值超出合理范围');
    return;
  }

  closeBpModal();
  showChatScreen();
  addMessage('user', `记录血压：${systolic}/${diastolic} mmHg`);
  setLoading(true);

  try {
    const resp = await fetch(API_BASE + '/api/blood-pressure', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': USER_ID,
      },
      body: JSON.stringify({ systolic, diastolic }),
    });

    const data = await resp.json();
    removeTyping();

    if (data.success) {
      const levelMap = {
        normal: '正常',
        high_normal: '正常高值',
        grade_1: '1级高血压',
        grade_2: '2级高血压',
        grade_3: '3级高血压',
        severe: '严重异常',
      };
      const level = levelMap[data.level] || data.level;
      addMessage('assistant', `已记录：${data.systolic}/${data.diastolic} mmHg\n血压等级：${level}\n\n如需查看趋势，可以问我"最近一周的血压情况"。`);
    } else {
      addMessage('assistant', '记录失败，请重试。');
    }
  } catch (e) {
    removeTyping();
    addMessage('assistant', '记录失败，请重试。如有紧急情况，请立即拨打 120。');
    console.error(e);
  } finally {
    setLoading(false);
  }
}

// 新对话
function newChat() {
  const container = document.getElementById('chat-messages');
  container.innerHTML = '';
  chatStarted = false;
  document.getElementById('welcome-screen').classList.remove('hidden');
  document.getElementById('chat-screen').classList.add('hidden');
  document.getElementById('user-input').value = '';
  document.getElementById('chat-input').value = '';
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function () {
  document.getElementById('user-input').focus();

  // 绑定血压输入事件
  document.getElementById('bp-systolic').addEventListener('input', updateBpLevel);
  document.getElementById('bp-diastolic').addEventListener('input', updateBpLevel);

  // 检查隐私政策同意状态
  checkConsentStatus();
});

// 检查同意状态
async function checkConsentStatus() {
  try {
    const resp = await fetch(API_BASE + '/api/consent/status', {
      headers: { 'X-User-ID': USER_ID },
    });
    const data = await resp.json();

    if (!data.consented) {
      setTimeout(showConsentModal, 500);
    }
  } catch (e) {
    console.error('检查同意状态失败:', e);
    // 如果检查失败，默认弹出（安全起见）
    setTimeout(showConsentModal, 500);
  }
}

// 健康档案弹窗
function showProfileModal() {
  const modal = document.getElementById('profile-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');

  // 清空表单
  document.getElementById('profile-gender').value = '';
  document.getElementById('profile-birth-date').value = '';
  document.getElementById('profile-height').value = '';
  document.getElementById('profile-weight').value = '';
  document.getElementById('profile-disease').value = '';
  document.getElementById('profile-diagnosed-date').value = '';
  document.getElementById('profile-notes').value = '';

  setTimeout(() => document.getElementById('profile-gender').focus(), 100);
}

function closeProfileModal() {
  const modal = document.getElementById('profile-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

async function submitProfile() {
  const gender = document.getElementById('profile-gender').value;
  const birthDate = document.getElementById('profile-birth-date').value;
  const height = document.getElementById('profile-height').value;
  const weight = document.getElementById('profile-weight').value;
  const disease = document.getElementById('profile-disease').value;
  const diagnosedDate = document.getElementById('profile-diagnosed-date').value;
  const notes = document.getElementById('profile-notes').value;

  if (!gender || !birthDate || !disease) {
    alert('请至少填写性别、出生日期和确诊慢病名称');
    return;
  }

  closeProfileModal();
  showChatScreen();

  // 构建消息文本
  let profileText = `健康档案信息：性别${gender}，出生日期${birthDate}`;
  if (height) profileText += `，身高${height}cm`;
  if (weight) profileText += `，体重${weight}kg`;
  profileText += `，确诊${disease}`;
  if (diagnosedDate) profileText += `，确诊时间${diagnosedDate}`;
  if (notes) profileText += `，补充信息：${notes}`;
  profileText += '。请分析我的健康档案并给出建议。';

  addMessage('user', profileText);
  setLoading(true);

  try {
    const resp = await fetch(API_BASE + '/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': USER_ID,
      },
      body: JSON.stringify({ message: profileText }),
    });

    if (!resp.ok && resp.status !== 200) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || '请求失败');
    }

    const data = await resp.json();
    removeTyping();

    if (data.is_emergency) {
      addMessage('assistant', '<span class="text-red-500 font-medium">⚠ 紧急提醒</span><br><br>' + data.reply);
    } else {
      addMessage('assistant', data.reply);
    }
  } catch (e) {
    removeTyping();
    addMessage('assistant', '抱歉，分析失败，请稍后再试。');
    console.error(e);
  } finally {
    setLoading(false);
  }
}
