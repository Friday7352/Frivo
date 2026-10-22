'use strict';
/*
  What a page in the app's window can ask the app for. Two pages load here:

    the app's own screens (file://…/ui/shell.html)   window.frivoShell
    Frivo's own pages, from its server              window.frivoApp

  Frivo's Settings show an "App" section when window.frivoApp is there, and
  a browser simply doesn't have it. The main process checks every request
  again against the page it came from, so another site can't use these.
*/

const { contextBridge, ipcRenderer } = require('electron');

if (location.protocol === 'file:') {
  contextBridge.exposeInMainWorld('frivoShell', {
    ready: () => ipcRenderer.invoke('shell:ready'),
    chooseLocal: () => ipcRenderer.invoke('shell:choose-local'),
    chooseRemote: (address) => ipcRenderer.invoke('shell:choose-remote', String(address || '')),
    trust: (accept, fingerprint) => ipcRenderer.invoke('shell:trust', Boolean(accept), String(fingerprint || '')),
    action: (id) => ipcRenderer.invoke('shell:action', String(id || '')),
    onView: (callback) => {
      ipcRenderer.on('shell:view', (event, view) => callback(view));
    },
  });
} else {
  contextBridge.exposeInMainWorld('frivoApp', {
    getState: () => ipcRenderer.invoke('app:get-state'),
    setCloseAction: (action) => ipcRenderer.invoke('app:set-close-action', String(action || '')),
    setStartAtLogin: (on) => ipcRenderer.invoke('app:set-start-at-login', Boolean(on)),
    stopFrivo: () => ipcRenderer.invoke('app:stop-frivo'),
    copy: (text) => ipcRenderer.invoke('app:copy', String(text || '')),
    changeConnection: () => ipcRenderer.invoke('app:change-connection'),
    checkForUpdate: () => ipcRenderer.invoke('app:check-update'),
    installUpdate: () => ipcRenderer.invoke('app:install-update'),
    onState: (callback) => {
      ipcRenderer.on('app:state', (event, value) => callback(value));
    },
  });
}
