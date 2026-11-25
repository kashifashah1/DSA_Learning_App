// Stops a double click on Submit from sending the solution twice, and tells the student the code is running.
(function () {
  var form = document.getElementById("submit-form");
  var button = document.getElementById("submit-button");
  if (!form || !button) { return; }

  form.addEventListener("submit", function () {
    button.disabled = true;
    button.textContent = "Running your code...";
  });

  // If the student comes back with the Back button, make the button usable again.
  window.addEventListener("pageshow", function () {
    button.disabled = false;
    button.textContent = "Submit";
  });
})();
