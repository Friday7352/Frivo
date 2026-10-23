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
  let typedAddress = null;   // what's typed in the address box, kept across redraws

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

    // CHANGED: what's been typed survives the screen being redrawn (the
    // network list fills in while it's open).
    const prev = document.getElementById('address');
    const hadFocus = prev && document.activeElement === prev;
    const input = el('input', {
      type: 'text', id: 'address', placeholder: '192.168.1.50', spellcheck: 'false', autocomplete: 'off',
      'aria-label': "The other PC's address",
    });
    input.value = typedAddress !== null ? typedAddress : (v.remoteUrl || '');
    input.addEventListener('input', () => { typedAddress = input.value; });
    const error = el('p', { class: 'field-error', role: 'alert' });
    const connectTo = async (address, name, btn) => {
      if (btn) btn.disabled = true;
      error.textContent = '';
      const result = await shellApi.chooseRemote(address, name).catch((err) => ({ ok: false, error: String(err.message || err) }));
      if (!result || !result.ok) {
        error.textContent = (result && result.error) || "That address didn't work.";
        if (btn) btn.disabled = false;
      }
    };
    const connect = (e) => {
      const btn = e && e.currentTarget && e.currentTarget.tagName === 'BUTTON' ? e.currentTarget : null;
      return connectTo(input.value, '', btn);
    };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') connect(e); });

    // NEW: Frivo found on the network, to pick from.
    const found = (v.discovery && v.discovery.servers) || [];
    const hideThisPc = v.local && v.local.supported && v.local.installed;
    const listed = found.filter((s) => !(s.thisPc && hideThisPc));
    const searching = v.discovery && v.discovery.searching;
    const list = el('div', { class: 'found' },
      listed.map((server) => el('button', {
        type: 'button', class: 'found-item',
        onclick: (e) => connectTo(server.url, server.name, e.currentTarget),
      },
      el('span', { class: 'found-name', text: server.name }),
      el('span', { class: 'found-meta', text: `${server.address}${server.version ? ` · Frivo ${server.version}` : ''}${server.thisPc ? ' · this PC' : ''}` }))),
      el('div', { class: 'found-status' },
        searching ? el('span', { class: 'mini-spinner', 'aria-hidden': 'true' }) : null,
        el('span', { text: searching
          ? (listed.length ? 'Still looking…' : 'Looking for Frivo on your network…')
          : (listed.length ? '' : "No Frivo found on your network. Type its address instead.") }),
        searching ? null : button('Look again', () => shellApi.action('rescan'), 'link')));

    parts.push(el('div', { class: `option${v.current === 'remote' ? ' is-current' : ''}` },
      el('p', { class: 'option-title' }, 'On another PC', v.current === 'remote' ? el('span', { class: 'option-tag', text: 'Current' }) : null),
      el('p', { class: 'option-sub', text: "Pick it below, or type the address shown in Frivo's launcher on that PC." }),
      list,
      el('div', { class: 'row' }, input, button('Connect', connect, v.local && v.local.supported ? null : 'primary')),
      error,
    ));
    viewEl.replaceChildren(...parts);
    if (hadFocus) input.focus();
    else if (!prev && (!v.local || !v.local.supported || v.current === 'remote')) input.focus();
  }

  // NEW: connecting to another PC for the first time asks for the code
  // its launcher (or Settings › Other devices) shows.
  function pair(v) {
    const input = el('input', {
      type: 'text', id: 'pair-code', class: 'code-input', placeholder: 'XXXX-XXXX-XXXX', maxlength: '16',
      spellcheck: 'false', autocomplete: 'off', 'aria-label': 'Pairing code',
    });
    const error = el('p', { class: 'field-error', role: 'alert', text: v.error || '' });
    const submit = async (e) => {
      const btn = e && e.currentTarget && e.currentTarget.tagName === 'BUTTON' ? e.currentTarget : null;
      if (btn) btn.disabled = true;
      error.textContent = '';
      const result = await shellApi.pair(input.value).catch((err) => ({ ok: false, error: String(err.message || err) }));
      if (!result || !result.ok) {
        error.textContent = (result && result.error) || "That code didn't work.";
        if (btn) btn.disabled = false;
        input.focus();
        input.select();
      }
    };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(e); });
    const where = v.serverName ? `${v.serverName} (${v.host})` : v.host;
    viewEl.replaceChildren(el('div', null,
      el('h1', { text: v.changed ? `Pair with ${where} again` : `Pair with ${where}` }),
      v.changed ? el('p', { class: 'lead warning', text: "Frivo at this address isn't the one this app paired with before. That's expected if Frivo was reinstalled there. If it wasn't, don't pair: something else may be answering at this address." }) : null,
      el('p', { class: 'lead', text: "Type the pairing code shown on that PC: in Frivo's launcher, or in Frivo under Settings › Other devices. It proves this is your Frivo, so nothing else on the network can pretend to be it." }),
      el('div', { class: 'row' }, input, button('Pair', submit, 'primary')),
      error,
      el('div', { class: 'actions actions-left' },
        button('No code? Compare the certificate instead', () => shellApi.action('compare'), 'link'),
        button('Cancel', () => shellApi.action('change'), 'link')),
    ));
    input.focus();
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
      // CHANGED: say what each row is. "Made by" read as who made the app;
      // it's the certificate authority Frivo created on that PC, by the
      // name written in the certificate.
      el('dl', { class: 'facts' },
        fact('Address', v.host),
        fact('Certificate signed by', v.authority),
        fact('Valid for', (v.names || []).join(', ') || v.server),
        fact('Fingerprint', v.fingerprint, true)),
      el('div', { class: 'actions' },
        button(v.changed ? 'Trust the new one' : 'Trust and connect', (e) => {
          e.currentTarget.disabled = true;
          shellApi.trust(true, v.fullFingerprint);
        }, 'primary'),
        button('Cancel', () => shellApi.trust(false))),
      el('div', { class: 'actions' }, button('Use the pairing code instead', () => shellApi.action('pair'), 'link')),
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
    // CHANGED (2.0.0): it's just Frivo. The app's own version is in Settings › App.
    if (v.appVersion) footEl.textContent = 'Frivo · by Friday';
    if (v.name !== 'welcome') typedAddress = null;
    if (v.name === 'welcome') welcome(v);
    else if (v.name === 'trust') trust(v);
    else if (v.name === 'pair') pair(v);
    else if (v.name === 'install') install(v);
    else status(v);
  }

  shellApi.onView(render);
  shellApi.ready().then(render);
}());
