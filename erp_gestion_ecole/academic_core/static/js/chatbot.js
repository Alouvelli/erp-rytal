(function () {
  'use strict';

  var bubble = document.getElementById('rytal-bubble');
  var panel = document.getElementById('rytal-panel');
  var closeBtn = document.getElementById('rytal-close');
  var clearBtn = document.getElementById('rytal-clear');
  var messagesEl = document.getElementById('rytal-messages');
  var typingEl = document.getElementById('rytal-typing');
  var form = document.getElementById('rytal-form');
  var input = document.getElementById('rytal-input');
  var sendBtn = document.getElementById('rytal-send');

  if (!bubble || !panel) return;

  var historyLoaded = false;

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  var LINK_MARKER = '\n[RYTAL_LINK]';

  function appendMessage(role, content) {
    var div = document.createElement('div');
    div.className = 'rytal-msg ' + (role === 'user' ? 'rytal-msg-user' : 'rytal-msg-assistant');

    var text = content;
    var linkUrl = null;
    var linkLabel = null;
    var markerIdx = content.indexOf(LINK_MARKER);
    if (markerIdx !== -1) {
      text = content.slice(0, markerIdx);
      var linkPart = content.slice(markerIdx + LINK_MARKER.length);
      var sepIdx = linkPart.indexOf('|');
      if (sepIdx !== -1) {
        linkUrl = linkPart.slice(0, sepIdx);
        linkLabel = linkPart.slice(sepIdx + 1);
      }
    }

    div.appendChild(document.createTextNode(text));

    // Le lien n'est jamais construit depuis du HTML : uniquement une URL et
    // un libellé fournis par le backend, insérés via createElement/textContent.
    if (linkUrl && linkLabel) {
      var link = document.createElement('a');
      link.href = linkUrl;
      link.className = 'rytal-msg-link';
      link.appendChild(document.createTextNode(linkLabel));
      div.appendChild(document.createElement('br'));
      div.appendChild(link);
    }

    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function setTyping(active) {
    typingEl.classList.toggle('d-none', !active);
    if (active) scrollToBottom();
  }

  function loadHistory() {
    if (historyLoaded) return;
    historyLoaded = true;
    fetch(CHATBOT_HISTORY_URL, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        messagesEl.innerHTML = '';
        (data.messages || []).forEach(function (m) {
          appendMessage(m.role, m.content);
        });
      })
      .catch(function () {
        appendMessage('assistant', "Impossible de charger la conversation pour le moment.");
      });
  }

  function openPanel() {
    panel.classList.remove('d-none');
    loadHistory();
    input.focus();
  }

  function resetConversation() {
    return fetch(CHATBOT_RESET_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': CHATBOT_CSRF_TOKEN },
    }).catch(function () {});
  }

  function closePanel() {
    panel.classList.add('d-none');
    resetConversation();
    messagesEl.innerHTML = '';
    historyLoaded = false;
  }

  bubble.addEventListener('click', function () {
    if (panel.classList.contains('d-none')) openPanel();
    else closePanel();
  });

  closeBtn.addEventListener('click', closePanel);

  // Fermeture automatique : tout clic en dehors du widget (y compris un
  // onglet/lien de la sidebar) referme le panneau s'il est ouvert.
  var widget = document.getElementById('rytal-widget');
  document.addEventListener('click', function (e) {
    if (panel.classList.contains('d-none')) return;
    if (widget && widget.contains(e.target)) return;
    closePanel();
  });

  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      if (!window.confirm('Effacer toute la conversation ?')) return;
      resetConversation().then(function () {
        messagesEl.innerHTML = '';
        historyLoaded = false;
        loadHistory();
      });
    });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) return;

    appendMessage('user', text);
    input.value = '';
    input.disabled = true;
    sendBtn.disabled = true;
    setTyping(true);

    fetch(CHATBOT_SEND_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': CHATBOT_CSRF_TOKEN,
      },
      body: JSON.stringify({ message: text }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          appendMessage('assistant', data.error);
        } else if (data.reply) {
          appendMessage('assistant', data.reply.content);
        }
      })
      .catch(function () {
        appendMessage('assistant', "RYTAL rencontre un problème technique. Merci de réessayer.");
      })
      .finally(function () {
        input.disabled = false;
        sendBtn.disabled = false;
        setTyping(false);
        input.focus();
      });
  });
})();
