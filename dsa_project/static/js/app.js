// Opens and closes the navigation menu on small screens.
(function () {
  var button = document.getElementById("menu-button");
  var menu = document.getElementById("menu");
  if (!button || !menu) { return; }

  button.addEventListener("click", function () {
    var isOpen = menu.classList.toggle("hidden") === false;
    // On small screens the menu becomes a vertical list when open.
    menu.classList.toggle("flex", isOpen);
    button.setAttribute("aria-expanded", String(isOpen));
  });
})();
