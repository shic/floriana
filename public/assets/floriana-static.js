(() => {
  const CONTACT_EMAIL = "celanifloriana@gmail.com";

  const fieldLabel = (field) => {
    const id = field.id ? document.querySelector(`label[for="${CSS.escape(field.id)}"]`) : null;
    if (id) return id.textContent.replace("*", "").trim();
    if (field.name) return field.name.replace(/_/g, " ");
    return "Field";
  };

  const collectFields = (form) => Array.from(form.querySelectorAll("input, textarea, select"))
    .filter((field) => field.name && !["hidden", "submit", "button"].includes(field.type))
    .map((field) => `${fieldLabel(field)}: ${field.value || ""}`)
    .join("\n");

    document.querySelectorAll("form[data-static-form='mailto'], form.fusion-form").forEach((form) => {
    form.setAttribute("novalidate", "novalidate");
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      const subject = form.closest(".page-id-154") ? "Newsletter request" : "Messaggio da florianacelani.com";
      const body = collectFields(form);
      const mailto = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
      window.location.href = mailto;
      const success = form.querySelector(".fusion-form-response-success");
      if (success) success.style.display = "block";
    }, true);
  });
})();
