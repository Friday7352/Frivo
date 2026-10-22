'use strict';
/*
  The app's own screens. The app sends which one to show (frivoShell.onView)
  and this draws it; buttons go back through frivoShell. Built from DOM
  nodes, never HTML strings: addresses and certificate names come from the
  network.
*/

(function () {
  const shellApi = window.frivoShell;
  const viewEl = document.getElementById('view');
  const footEl = document.getElementById('foot');

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    }
    return node;
  }

  function button(label, onClick, kind) {
    return el('button', { type: 'button', class: `btn${kind ? ` btn-${kind}` : ''}`, onclick: onClick }, label);
  }

  function actionButtons(actions) {
    return el('div', { class: 'actions' },
      (actions || []).map((a) => button(a.label, (e) => {
        const btn = e.currentTarget;   // gone from the event once it's handled
        btn.disabled = true;
        shellApi.action(a.id).catch(() => {}).finally(() => { btn.disabled = false; });
      }, a.primary ? 'primary' : null)));
  }

  // ---------------------------------------------------------------- views

  function welcome(v) {
    const parts = [];
    if (v.canGoBack) {
      parts.push(el('div', { class: 'back' }, button('← Back', () => shellApi.action('back'), 'link')));
    }
    parts.push(el('h1', { text: 'Where does Frivo run?' }));
    parts.push(el('p', { class: 'lead', text: 'Frivo can run on this PC, or on another PC on your network that you connect to. You can change this later from the tray icon.' }));
    if (v.notice) parts.push(el('p', { class: 'notice', text: v.notice }));

    if (v.local && v.local.supported) {
      const installed = v.local.installed;
      parts.push(el('div', { class: `option${v.current === 'local' ? ' is-current' : ''}` },
        el('p', { class: 'option-title' }, 'On this PC', v.current === 'local' ? el('span', { class: 'option-tag', text: 'Current' }) : null),
        el('p', {
          class: 'option-sub',
          text: installed
            ? `Frivo${v.local.version ? ` ${v.local.version}` : ''} is installed here. It runs in the background and this window is Frivo, so there's nothing else to open.`
            : "Frivo isn't installed on this PC yet. The app downloads Frivo's setup from GitHub, checks it, and runs it.",
        }),
        installed
          ? button('Use this PC', (e) => { e.currentTarget.disabled = true; shellApi.chooseLocal(); }, 'primary')
          : button('Install Frivo', (e) => { e.currentTarget.disabled = true; shellApi.action('install'); }, 'primary'),
      ));
    }

    const input = el('input', {
      type: 'text', id: 'address', placeholder: '192.168.1.50', spellcheck: 'false', autocomplete: 'off',
      'aria-label': "The other PC's address", value: v.remoteUrl || '',
    });
    const error = el('p', { class: 'field-error', role: 'alert' });
    const connect = async (e) => {
      const btn = e && e.currentTarget && e.currentTarget.tagName === 'BUTTON' ? e.currentTarget : null;
      if (btn) btn.disabled = true;
      error.textContent = '';
      const result = await shellApi.chooseRemote(input.value).catch((err) => ({ ok: false, error: String(err.message || err) }));
      if (!result || !result.ok) {
        error.textContent = (result && result.error) || "That address didn't work.";
        if (btn) btn.disabled = false;
      }
    };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') connect(e); });
    parts.push(el('div', { class: `option${v.current === 'remote' ? ' is-current' : ''}` },
      el('p', { class: 'option-title' }, 'On another PC', v.current === 'remote' ? el('span', { class: 'option-tag', text: 'Current' }) : null),
      el('p', { class: 'option-sub', text: "Type the address shown in Frivo's launcher on that PC, under Other devices on your network." }),
      el('div', { class: 'row' }, input, button('Connect', connect, v.local && v.local.supported ? null : 'primary')),
      error,
    ));
    viewEl.replaceChildren(...parts);
    if (!v.local || !v.local.supported || v.current === 'remote') input.focus();
  }

  function status(v) {
    viewEl.replaceChildren(el('div', { class: 'status' },
      v.spinner ? el('div', { class: 'spinner', 'aria-hidden': 'true' })
                : el('div', { class: `badge${v.tone === 'error' ? ' is-error' : ''}`, 'aria-hidden': 'true', text: v.tone === 'error' ? '!' : '■' }),
      el('h1', { text: v.title || '' }),
      v.detail ? el('p', { class: 'lead', text: v.detail }) : null,
      actionButtons(v.actions),
    ));
  }

  function trust(v) {
    const fact = (label, value, mono) => el('div', { class: 'fact' },
      el('dt', { text: label }), el('dd', { class: mono ? 'mono' : null, text: value || '—' }));
    viewEl.replaceChildren(
      el('h1', { text: v.changed ? `Frivo at ${v.host} has a different certificate` : `Trust Frivo at ${v.host}?` }),
      el('p', { class: `lead${v.changed ? ' warning' : ''}`, text: v.changed
        ? "This isn't the certificate this app trusted for this address before. That's expected if Frivo was reinstalled on that PC. If it wasn't, don't connect: something else may be answering at this address."
        : "Frivo makes its own certificate when it's installed, so Windows doesn't know it yet. Trust it if this is your Frivo. The app remembers it, and only ever accepts this one at this address." }),
      el('dl', { class: 'facts' },
        fact('Address', v.host),
        fact('Made by', v.authority),
        fact('For', (v.names || []).join(', ') || v.server),
        fact('Fingerprint', v.fingerprint, true)),
      el('div', { class: 'actions' },
        button(v.changed ? 'Trust the new one' : 'Trust and connect', (e) => {
          e.currentTarget.disabled = true;
          shellApi.trust(true, v.fullFingerprint);
        }, 'primary'),
        button('Cancel', () => shellApi.trust(false))),
    );
  }

  // Set through the style property: the page's security policy doesn't
  // allow style="" in markup.
  function progressBar(percent) {
    const fill = el('span');
    fill.style.width = `${Math.max(2, Math.min(100, percent))}%`;
    return el('div', { class: 'progress', role: 'progressbar', 'aria-valuenow': String(percent), 'aria-valuemin': '0', 'aria-valuemax': '100' }, fill);
  }

  function install(v) {
    if (v.stage === 'download') {
      viewEl.replaceChildren(el('div', { class: 'status' },
        el('div', { class: 'spinner', 'aria-hidden': 'true' }),
        el('h1', { text: `Downloading Frivo${v.version ? ` ${v.version}` : ''}…` }),
        el('p', { class: 'lead', text: "From Frivo's releases on GitHub. It's checked against the fingerprint GitHub publishes before it runs." }),
        progressBar(v.percent || 0)));
    } else {
      viewEl.replaceChildren(el('div', { class: 'status' },
        el('div', { class: 'spinner', 'aria-hidden': 'true' }),
        el('h1', { text: "Finish Frivo's setup" }),
        el('p', { class: 'lead', text: "Setup is open in its own window. Approve the administrator prompt, then follow its steps. This window carries on by itself when setup is done." })));
    }
  }

  function render(v) {
    if (!v) return;
    if (v.appVersion) footEl.textContent = `Frivo App ${v.appVersion}`;
    if (v.name === 'welcome') welcome(v);
    else if (v.name === 'trust') trust(v);
    else if (v.name === 'install') install(v);
    else status(v);
  }

  shellApi.onView(render);
  shellApi.ready().then(render);
}());
