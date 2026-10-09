// Progressive enhancement only. Every page works without this script.
(function () {
  "use strict";

  // Busy state: forms marked data-busy disable their submit button and say "Working...".
  document.querySelectorAll("form[data-busy]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (event.defaultPrevented) return;
      var button = event.submitter || form.querySelector("button[type=submit], button:not([type])");
      if (!button) return;
      // Keep the pressed button's name and value, which disabling would drop.
      if (button.name) {
        var hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = button.name;
        hidden.value = button.value;
        form.appendChild(hidden);
      }
      window.setTimeout(function () {
        button.disabled = true;
        button.textContent = "Working...";
      }, 0);
    });
  });

  // Character counter for any textarea or input with data-counter and maxlength.
  document.querySelectorAll("[data-counter]").forEach(function (field) {
    var out = document.getElementById(field.getAttribute("data-counter"));
    if (!out) return;
    var max = field.getAttribute("maxlength");
    function update() {
      out.textContent = field.value.length + (max ? " of " + max : "") + " characters";
    }
    field.addEventListener("input", update);
    update();
  });

  // Confirmation for forms marked data-confirm.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }, true);
  });
})();
