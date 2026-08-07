document.addEventListener("submit", function (event) {
    const submitter = event.submitter;
    if (!submitter || !submitter.dataset.loadingText) {
        return;
    }
    window.setTimeout(function () {
        submitter.dataset.originalText = submitter.textContent.trim();
        submitter.disabled = true;
        submitter.classList.add("is-loading");
        submitter.textContent = submitter.dataset.loadingText || "Processing...";
    }, 0);
});

document.addEventListener("click", function (event) {
    const link = event.target.closest("a[data-loading-text]");
    if (!link) {
        return;
    }
    link.classList.add("disabled", "is-loading");
    link.setAttribute("aria-disabled", "true");
    link.textContent = link.dataset.loadingText || "Processing...";
});

(function () {
    const logoutForm = document.getElementById("backLogoutForm");
    if (!logoutForm || !window.history || !window.history.pushState) {
        return;
    }

    window.history.pushState({ protectedPage: true }, "", window.location.href);
    window.addEventListener("popstate", function () {
        const confirmLogout = window.confirm("Are you sure you want to logout?");
        if (confirmLogout) {
            logoutForm.submit();
            return;
        }
        window.history.pushState({ protectedPage: true }, "", window.location.href);
    });
})();
