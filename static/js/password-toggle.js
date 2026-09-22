/*
 * Show or hide the characters of every password field on the page.
 *
 * Progressive enhancement: without JavaScript the fields stay ordinary
 * password inputs and nothing else changes. Passwords start hidden, and are
 * hidden again the moment their form is submitted, so a revealed password
 * never lingers on screen after you press the button, and password managers
 * still see a password field when they decide what to save.
 */
(function () {
  "use strict";

  var EYE =
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
    '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" fill="none" ' +
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="2"/></svg>';

  var EYE_OFF =
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
    '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 19c-7 0-11-7-11-7a18.45 18.45 0 0 1 ' +
    '5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 7 11 7a18.5 18.5 0 0 1-2.16 3.19" ' +
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<path d="M1 1l22 22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

  function show(input, button, visible) {
    input.type = visible ? "text" : "password";
    button.innerHTML = visible ? EYE_OFF : EYE;
    button.setAttribute("aria-pressed", visible ? "true" : "false");
    button.setAttribute("aria-label", visible ? "Hide password" : "Show password");
    button.title = visible ? "Hide password" : "Show password";
  }

  function enhance(input) {
    if (input.getAttribute("data-pw-toggle")) { return; }
    input.setAttribute("data-pw-toggle", "1");

    var wrap = document.createElement("span");
    wrap.className = "pw-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var button = document.createElement("button");
    button.type = "button";                       // never submits the form
    button.className = "pw-toggle";
    if (input.id) { button.setAttribute("aria-controls", input.id); }
    wrap.appendChild(button);
    show(input, button, false);

    button.addEventListener("click", function () {
      show(input, button, input.type === "password");
    });

    if (input.form) {
      input.form.addEventListener("submit", function () {
        show(input, button, false);
      });
    }
  }

  function init() {
    var fields = document.querySelectorAll('input[type="password"]');
    for (var i = 0; i < fields.length; i++) { enhance(fields[i]); }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
