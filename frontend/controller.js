/* Controller client.
 *
 * Two jobs:
 *   1. Maintain a low-latency WebSocket to the server (with heartbeat + auto-reconnect).
 *   2. Turn multi-touch into button_down / button_up deltas.
 *
 * Multi-touch model: we use Pointer Events (one event stream that covers both
 * iPhone touches and a desktop mouse for testing). Every active pointer that began
 * on a control is tracked in `pointers` -> the button currently under it. The set of
 * pressed buttons is the union of those, recomputed on every pointer change. That
 * naturally supports chords (Up+Right+A), finger-slides between buttons, and release.
 */
(function () {
  "use strict";

  var WS_URL = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws";
  var HEARTBEAT_MS = 2000;
  var MAX_RECONNECT_MS = 5000;

  var socket = null;
  var heartbeatTimer = null;
  var reconnectDelay = 500;

  var pressed = new Set();        // logical buttons currently reported as down
  var pointers = new Map();       // pointerId -> button name (or null when off a control)

  var statusEl = document.getElementById("status");

  function setStatus(state, text) {
    statusEl.className = "status status--" + state;
    statusEl.textContent = text;
  }

  function send(obj) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(obj));
    }
  }

  // ---- input ------------------------------------------------------------
  function buttonAt(x, y) {
    var el = document.elementFromPoint(x, y);
    var btn = el && el.closest("[data-button]");
    return btn ? btn.dataset.button : null;
  }

  function setVisual(button, isDown) {
    var el = document.querySelector('[data-button="' + button + '"]');
    if (el) el.classList.toggle("is-pressed", isDown);
  }

  function recompute() {
    var next = new Set();
    pointers.forEach(function (button) {
      if (button) next.add(button);
    });

    pressed.forEach(function (button) {
      if (!next.has(button)) {
        pressed.delete(button);
        setVisual(button, false);
        send({ type: "button_up", button: button, timestamp: Date.now() });
      }
    });

    next.forEach(function (button) {
      if (!pressed.has(button)) {
        pressed.add(button);
        setVisual(button, true);
        send({ type: "button_down", button: button, timestamp: Date.now() });
      }
    });
  }

  function onPointerDown(e) {
    var button = buttonAt(e.clientX, e.clientY);
    if (button === null) return;           // only track pointers that start on a control
    e.preventDefault();
    pointers.set(e.pointerId, button);
    recompute();
  }

  function onPointerMove(e) {
    if (!pointers.has(e.pointerId)) return; // ignore moves from untracked pointers (e.g. hovering mouse)
    e.preventDefault();
    pointers.set(e.pointerId, buttonAt(e.clientX, e.clientY)); // support sliding between buttons
    recompute();
  }

  function onPointerUp(e) {
    if (!pointers.has(e.pointerId)) return;
    e.preventDefault();
    pointers.delete(e.pointerId);
    recompute();
  }

  function clearAllPressed() {
    pointers.clear();
    pressed.forEach(function (button) {
      setVisual(button, false);
    });
    pressed.clear();
  }

  // ---- fullscreen -------------------------------------------------------
  // iPhone Safari has no Fullscreen API; its only chrome-free mode is launching
  // from the Home Screen (standalone). Everywhere else (Android/desktop/iPad) the
  // Fullscreen API works, so try it and otherwise show Add-to-Home instructions.
  var isStandalone =
    window.navigator.standalone === true ||
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches);

  var fsBtn = document.getElementById("fullscreen-btn");
  var fsHelp = document.getElementById("fs-help");
  var fsHelpClose = document.getElementById("fs-help-close");
  var docEl = document.documentElement;

  function canRequestFullscreen() {
    return !!(docEl.requestFullscreen || docEl.webkitRequestFullscreen);
  }

  function toggleFullscreen() {
    var isFs = document.fullscreenElement || document.webkitFullscreenElement;
    if (isFs) {
      (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    } else if (docEl.requestFullscreen) {
      docEl.requestFullscreen().catch(function () {});
    } else if (docEl.webkitRequestFullscreen) {
      docEl.webkitRequestFullscreen();
    }
  }

  if (fsBtn) {
    if (isStandalone) {
      fsBtn.hidden = true;                 // already chrome-free, nothing to do
    } else {
      fsBtn.addEventListener("click", function () {
        if (canRequestFullscreen()) {
          toggleFullscreen();
        } else if (fsHelp) {
          fsHelp.hidden = false;           // iPhone: show Add-to-Home-Screen steps
        }
      });
    }
  }
  if (fsHelpClose) {
    fsHelpClose.addEventListener("click", function () { fsHelp.hidden = true; });
  }
  if (fsHelp) {
    // Tapping the dimmed backdrop (but not the card) also dismisses.
    fsHelp.addEventListener("click", function (e) {
      if (e.target === fsHelp) fsHelp.hidden = true;
    });
  }

  // ---- stream mode (split video + controller) ---------------------------
  // A second layout: top half live MJPEG video, bottom half the pad. Completely
  // independent of the WebSocket input path — the <img> just points at
  // /video/stream.mjpeg, so if video is off or capture fails the controller below is
  // unaffected (we show a small placeholder and quietly retry).
  var STREAM_URL = "/video/stream.mjpeg";
  var STREAM_KEY = "rpc_stream_mode";
  var STREAM_RETRY_MS = 4000;

  var modeBtn = document.getElementById("mode-btn");
  var streamPanel = document.getElementById("stream-panel");
  var streamImg = document.getElementById("stream-img");
  var streamMsg = document.getElementById("stream-msg");
  var streamRetryTimer = null;
  var streamOn = false;

  function startStream() {
    if (streamMsg) streamMsg.hidden = true;
    // Cache-bust so a re-enable opens a fresh MJPEG connection rather than a stale one.
    if (streamImg) streamImg.src = STREAM_URL + "?t=" + Date.now();
  }

  function stopStream() {
    if (streamRetryTimer) { clearTimeout(streamRetryTimer); streamRetryTimer = null; }
    if (streamImg) streamImg.removeAttribute("src"); // closes the MJPEG connection
  }

  function setStreamMode(on, persist) {
    streamOn = on;
    document.body.classList.toggle("mode-stream", on);
    if (streamPanel) streamPanel.hidden = !on;
    if (modeBtn) modeBtn.setAttribute("aria-pressed", on ? "true" : "false");
    if (on) { startStream(); } else { stopStream(); }
    if (persist !== false) {
      try { localStorage.setItem(STREAM_KEY, on ? "1" : "0"); } catch (e) {}
    }
  }

  if (streamImg) {
    streamImg.addEventListener("error", function () {
      if (!streamOn) return;                  // ignore the error fired by clearing src
      if (streamMsg) streamMsg.hidden = false;
      // Capture may just be (re)starting on the Pi (ffmpeg backs off + relaunches);
      // retry so the video self-heals without the user toggling the mode.
      if (streamRetryTimer) clearTimeout(streamRetryTimer);
      streamRetryTimer = setTimeout(function () { if (streamOn) startStream(); }, STREAM_RETRY_MS);
    });
    streamImg.addEventListener("load", function () {
      if (streamMsg) streamMsg.hidden = true;
    });
  }

  if (modeBtn) {
    modeBtn.addEventListener("click", function () { setStreamMode(!streamOn); });
  }

  // Restore the preference on load: ?mode=stream wins, else the last saved choice.
  (function () {
    var wantStream = /[?&]mode=stream\b/.test(location.search);
    if (!wantStream) {
      try { wantStream = localStorage.getItem(STREAM_KEY) === "1"; } catch (e) {}
    }
    if (wantStream) setStreamMode(true, false);
  })();

  // ---- confirm dialogs (EXIT / REBOOT) ----------------------------------
  // Both buttons have no data-button, so the touch/pointer pipeline ignores them
  // (buttonAt returns null) and a click opens a two-tap confirm overlay. Only the
  // confirm action takes effect; tapping Cancel or the dimmed backdrop dismisses.
  var EXIT_HOLD_MS = 250;

  function wireConfirm(triggerId, overlayId, cancelId, confirmId, onConfirm) {
    var overlay = document.getElementById(overlayId);
    function show(visible) { if (overlay) overlay.hidden = !visible; }

    var trigger = document.getElementById(triggerId);
    if (trigger) trigger.addEventListener("click", function () { show(true); });

    var cancel = document.getElementById(cancelId);
    if (cancel) cancel.addEventListener("click", function () { show(false); });

    var confirm = document.getElementById(confirmId);
    if (confirm) confirm.addEventListener("click", function () {
      show(false);
      onConfirm();
    });

    if (overlay) overlay.addEventListener("click", function (e) {
      if (e.target === overlay) show(false);   // backdrop tap cancels
    });
  }

  // EXIT: send a momentary EXIT press (down, then up after a short hold) so RetroArch's
  // enable+exit hotkey — both BTN_MODE — registers the press across a poll frame.
  wireConfirm("exit-btn", "exit-confirm", "exit-cancel", "exit-confirm-btn", function () {
    send({ type: "button_down", button: "EXIT", timestamp: Date.now() });
    setTimeout(function () {
      send({ type: "button_up", button: "EXIT", timestamp: Date.now() });
    }, EXIT_HOLD_MS);
  });

  // REBOOT: send the system message; the server guards it so it only ever reboots a
  // real Pi (no-op on the Mac / mock / when RPC_ALLOW_REBOOT is off).
  wireConfirm("reboot-btn", "reboot-confirm", "reboot-cancel", "reboot-confirm-btn", function () {
    send({ type: "system", action: "reboot" });
    // The Pi is going down; the socket will drop and auto-reconnect once it's back.
    setStatus("disconnected", "Rebooting…");
  });

  // ---- connection -------------------------------------------------------
  function startHeartbeat() {
    stopHeartbeat();
    heartbeatTimer = setInterval(function () {
      send({ type: "heartbeat" });
    }, HEARTBEAT_MS);
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function connect() {
    setStatus("connecting", "Connecting…");
    socket = new WebSocket(WS_URL);

    socket.onopen = function () {
      reconnectDelay = 500;
      send({ type: "hello", protocol: "1.0", controller: "gameboy" });
    };

    socket.onmessage = function (event) {
      var msg;
      try {
        msg = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (msg.type === "accepted") {
        setStatus("connected", "Connected");
        startHeartbeat();
      }
    };

    socket.onclose = function () {
      // Drop everything locally; the server releases its side on disconnect too.
      setStatus("disconnected", "Reconnecting…");
      stopHeartbeat();
      clearAllPressed();
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_MS);
    };

    socket.onerror = function () {
      socket.close();
    };
  }

  // Pointer move/up/cancel listen on window so a finger that slides off a button
  // (or lifts anywhere) is still tracked.
  document.addEventListener("pointerdown", onPointerDown, { passive: false });
  window.addEventListener("pointermove", onPointerMove, { passive: false });
  window.addEventListener("pointerup", onPointerUp, { passive: false });
  window.addEventListener("pointercancel", onPointerUp, { passive: false });
  // Belt-and-suspenders: stop iOS context menu / selection on long-press.
  window.addEventListener("contextmenu", function (e) {
    e.preventDefault();
  });

  connect();
})();
