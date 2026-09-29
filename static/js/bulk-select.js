/*
 * Tick several suggestions and act on them together.
 *
 * Each bar is a <form class="bulk-bar" id="...">; the tick boxes belong to it
 * through their form="..." attribute, so they can sit inside the cards, next
 * to each card's own buttons, without nesting forms. Hold Shift to tick or
 * untick a whole run between two boxes. Without JavaScript the boxes and the
 * buttons still work; only the counter and the helper buttons need it.
 */
(function () {
  "use strict";

  function toArray(list) { return Array.prototype.slice.call(list); }

  toArray(document.querySelectorAll("form.bulk-bar")).forEach(function (bar) {
    var boxes = function () {
      return toArray(document.querySelectorAll('input.bulk-check[form="' + bar.id + '"]'));
    };
    var counter = bar.querySelector(".bulk-count");
    var submits = toArray(bar.querySelectorAll('button[type="submit"]'));
    var last = null;

    function refresh() {
      var all = boxes();
      var ticked = all.filter(function (b) { return b.checked; }).length;
      if (counter) { counter.textContent = ticked + " selected"; }
      submits.forEach(function (b) { b.disabled = ticked === 0; });
      all.forEach(function (b) {
        var card = b.closest(".suggestion-card");
        if (card) { card.classList.toggle("is-selected", b.checked); }
      });
    }

    boxes().forEach(function (box) {
      box.addEventListener("click", function (event) {
        var all = boxes();
        if (event.shiftKey && last && all.indexOf(last) !== -1) {
          var from = all.indexOf(last), to = all.indexOf(box);
          var lo = Math.min(from, to), hi = Math.max(from, to);
          for (var i = lo; i <= hi; i++) { all[i].checked = box.checked; }
        }
        last = box;
        refresh();
      });
    });

    toArray(bar.querySelectorAll("[data-bulk-select]")).forEach(function (button) {
      button.addEventListener("click", function () {
        var how = button.getAttribute("data-bulk-select");
        boxes().forEach(function (b) {
          if (how === "all") { b.checked = true; }
          else if (how === "none") { b.checked = false; }
          else if (how === "dictionary" && b.getAttribute("data-in-dictionary") === "1") { b.checked = true; }
        });
        refresh();
      });
    });

    refresh();
  });
})();
