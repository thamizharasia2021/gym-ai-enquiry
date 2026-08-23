/**
 * Gym AI Assistant — Universal Theme, Typography & Logo Synchronizer
 * Automatically synchronizes color themes, Google Fonts, and logo images across all pages:
 * /setup, /site, /chat, /leads, /config, and /admin.
 */
(function(window) {
  const PRESET_PALETTES = {
    emerald: {
      name: "Emerald Green",
      primary: "#16a34a",
      secondary: "#0f172a",
      accent: "#16a34a",
      accentDark: "#15803d",
      bgSoft: "#f8fafc",
      headerBg: "#0f172a",
      chatHeaderBg: "#075e54",
      userMsgBg: "#dcf8c6",
      userMsgText: "#111827",
      botMsgBg: "#ffffff",
      botMsgText: "#111827",
      font: "Inter"
    },
    cyberpunk: {
      name: "Cyberpunk Lime & Neon",
      primary: "#84cc16",
      secondary: "#0a0e17",
      accent: "#a3e635",
      accentDark: "#65a30d",
      bgSoft: "#0f172a",
      headerBg: "#0a0e17",
      chatHeaderBg: "#111827",
      userMsgBg: "#84cc16",
      userMsgText: "#000000",
      botMsgBg: "#1e293b",
      botMsgText: "#f8fafc",
      font: "Outfit"
    },
    sapphire: {
      name: "Midnight Sapphire",
      primary: "#2563eb",
      secondary: "#0b132b",
      accent: "#3b82f6",
      accentDark: "#1d4ed8",
      bgSoft: "#f8fafc",
      headerBg: "#0f172a",
      chatHeaderBg: "#1e3a8a",
      userMsgBg: "#dbeafe",
      userMsgText: "#1e3a8a",
      botMsgBg: "#ffffff",
      botMsgText: "#0f172a",
      font: "Montserrat"
    },
    crimson: {
      name: "Crimson Power",
      primary: "#dc2626",
      secondary: "#18181b",
      accent: "#ef4444",
      accentDark: "#b91c1c",
      bgSoft: "#fcfcfc",
      headerBg: "#18181b",
      chatHeaderBg: "#991b1b",
      userMsgBg: "#fee2e2",
      userMsgText: "#7f1d1d",
      botMsgBg: "#ffffff",
      botMsgText: "#18181b",
      font: "Outfit"
    },
    amber: {
      name: "Sunset Amber",
      primary: "#d97706",
      secondary: "#1c1917",
      accent: "#f59e0b",
      accentDark: "#b45309",
      bgSoft: "#fffbeb",
      headerBg: "#1c1917",
      chatHeaderBg: "#78350f",
      userMsgBg: "#fef3c7",
      userMsgText: "#78350f",
      botMsgBg: "#ffffff",
      botMsgText: "#1c1917",
      font: "Poppins"
    },
    purple: {
      name: "Royal Purple",
      primary: "#7c3aed",
      secondary: "#110b29",
      accent: "#8b5cf6",
      accentDark: "#6d28d9",
      bgSoft: "#faf5ff",
      headerBg: "#110b29",
      chatHeaderBg: "#5b21b6",
      userMsgBg: "#ede9fe",
      userMsgText: "#4c1d95",
      botMsgBg: "#ffffff",
      botMsgText: "#110b29",
      font: "Plus Jakarta Sans"
    },
    obsidian: {
      name: "Stealth Obsidian",
      primary: "#64748b",
      secondary: "#020617",
      accent: "#94a3b8",
      accentDark: "#475569",
      bgSoft: "#090d16",
      headerBg: "#020617",
      chatHeaderBg: "#0f172a",
      userMsgBg: "#334155",
      userMsgText: "#ffffff",
      botMsgBg: "#1e293b",
      botMsgText: "#f8fafc",
      font: "Space Grotesk"
    },
    teal: {
      name: "Aqua Teal",
      primary: "#0d9488",
      secondary: "#042f2e",
      accent: "#14b8a6",
      accentDark: "#0f766e",
      bgSoft: "#f0fdfa",
      headerBg: "#042f2e",
      chatHeaderBg: "#115e59",
      userMsgBg: "#ccfbf1",
      userMsgText: "#134e4a",
      botMsgBg: "#ffffff",
      botMsgText: "#042f2e",
      font: "DM Sans"
    }
  };

  const GOOGLE_FONTS = [
    "Inter",
    "Outfit",
    "Montserrat",
    "Roboto",
    "Poppins",
    "Plus Jakarta Sans",
    "DM Sans",
    "Space Grotesk",
    "Raleway"
  ];

  function getApiBase() {
    return window.GYM_AI_API_BASE || (
      window.location.origin && !window.location.origin.includes("null") && !window.location.origin.includes("file:")
        ? window.location.origin
        : "http://localhost:8000"
    );
  }

  function getGymId() {
    const params = new URLSearchParams(window.location.search);
    return params.get("gym") || localStorage.getItem("gym_id") || "tarvos-fit";
  }

  function loadGoogleFont(fontName) {
    if (!fontName) return;
    const cleanFont = fontName.replace(/['"]/g, "").trim();
    const id = "gf-" + cleanFont.toLowerCase().replace(/\s+/g, "-");
    if (document.getElementById(id)) return;

    const link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(cleanFont)}:wght@300;400;500;600;700;800&display=swap`;
    document.head.appendChild(link);
  }

  function applyTheme(themeData, fontName, logoUrl, gymName) {
    const root = document.documentElement;
    const style = root.style;

    if (themeData) {
      if (themeData.primary_color || themeData.primary) {
        const p = themeData.primary_color || themeData.primary;
        style.setProperty("--primary", p);
        style.setProperty("--accent", p);
        style.setProperty("--accent-primary", p);
      }
      if (themeData.secondary_color || themeData.secondary) {
        const s = themeData.secondary_color || themeData.secondary;
        style.setProperty("--secondary", s);
        style.setProperty("--bg-dark", s);
        style.setProperty("--header-bg", s);
      }
      if (themeData.chatbot_header_color || themeData.chatHeaderBg) {
        style.setProperty("--header-bg", themeData.chatbot_header_color || themeData.chatHeaderBg);
      }
      if (themeData.user_msg_color || themeData.userMsgBg) {
        style.setProperty("--user-msg-bg", themeData.user_msg_color || themeData.userMsgBg);
      }
      if (themeData.user_msg_text || themeData.userMsgText) {
        style.setProperty("--user-msg-text", themeData.user_msg_text || themeData.userMsgText);
      }
      if (themeData.bot_msg_color || themeData.botMsgBg) {
        style.setProperty("--bot-msg-bg", themeData.bot_msg_color || themeData.botMsgBg);
      }
      if (themeData.bot_msg_text || themeData.botMsgText) {
        style.setProperty("--bot-msg-text", themeData.bot_msg_text || themeData.botMsgText);
      }
      if (themeData.background_color || themeData.bgSoft) {
        style.setProperty("--bg-soft", themeData.background_color || themeData.bgSoft);
      }
    }

    const finalFont = fontName || (themeData && (themeData.font_family || themeData.font));
    if (finalFont) {
      loadGoogleFont(finalFont);
      style.setProperty("--font-family", `'${finalFont}', -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif`);
      document.body.style.fontFamily = `var(--font-family)`;
    }

    const finalLogo = logoUrl || localStorage.getItem("gym_logo") || "/static/1000920458.png";
    if (finalLogo) {
      document.querySelectorAll("[data-gym-logo], .gym-logo-img, #headerAvatar img, .gymchat-head img").forEach(img => {
        if (img.tagName === "IMG") {
          img.src = finalLogo;
          img.style.display = "inline-block";
        }
      });
      const brandLogo = document.getElementById("brandLogo");
      if (brandLogo) {
        brandLogo.innerHTML = `<img src="${finalLogo}" alt="${gymName || 'Gym Logo'}" style="width:100%;height:100%;object-fit:contain;border-radius:10px;" onerror="this.parentElement.innerHTML='🏋️'" />`;
      }
      // For chat avatar container
      const chatAvatar = document.getElementById("headerAvatar");
      if (chatAvatar) {
        chatAvatar.innerHTML = `<img src="${finalLogo}" alt="Logo" style="width:100%;height:100%;object-fit:cover;border-radius:50%;" /><span class="online-indicator"></span>`;
      }
      // For embedded chat widget header logo on public site
      const chatHeadLogo = document.querySelector(".gymchat-head div span:first-child");
      if (chatHeadLogo && !chatHeadLogo.querySelector("img")) {
        chatHeadLogo.innerHTML = `<img src="${finalLogo}" style="width:24px;height:24px;object-fit:contain;background:#fff;border-radius:4px;padding:2px;" alt="Logo" />`;
      }
      // Update favicon
      let favicon = document.querySelector("link[rel~='icon']");
      if (!favicon) {
        favicon = document.createElement("link");
        favicon.rel = "icon";
        document.head.appendChild(favicon);
      }
      favicon.href = finalLogo;
    }

    const cleanGymName = (gymName || localStorage.getItem("gym_name") || "").replace(/\s+Elite$/i, "");
    if (cleanGymName) {
      document.querySelectorAll("[data-gym-name], #gymNameDisplay, #welcomeGymName").forEach(el => {
        el.textContent = cleanGymName;
      });
    }

    window.dispatchEvent(new CustomEvent("gym-theme-updated", {
      detail: { theme: themeData, font: finalFont, logo: finalLogo, gymName: gymName }
    }));
  }

  function getLocalTheme() {
    try {
      const raw = localStorage.getItem("gym_theme_config");
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  async function sync() {
    const gymId = getGymId();
    const local = getLocalTheme();
    const localFont = localStorage.getItem("gym_font") || (local && local.font_family);
    const localLogo = localStorage.getItem("gym_logo");
    const localName = localStorage.getItem("gym_name");

    // Immediately apply local cache
    if (local || localFont || localLogo) {
      applyTheme(local, localFont, localLogo, localName);
    }

    // Then asynchronously pull from server to ensure fresh state
    try {
      const res = await fetch(`${getApiBase()}/api/gym/${gymId}/info`);
      if (res.ok) {
        const data = await res.json();
        const serverTheme = data.theme || {};
        const serverFont = serverTheme.font_family || localFont || "Inter";
        const serverLogo = data.logo_url || localLogo;
        const serverName = data.gym_name || localName;

        localStorage.setItem("gym_theme_config", JSON.stringify(serverTheme));
        if (serverFont) localStorage.setItem("gym_font", serverFont);
        if (serverLogo) localStorage.setItem("gym_logo", serverLogo);
        if (serverName) localStorage.setItem("gym_name", serverName);

        applyTheme(serverTheme, serverFont, serverLogo, serverName);
      }
    } catch (err) {
      console.warn("Theme-sync server fetch fallback:", err);
    }
  }

  // Hamburger Menu Component Initialization
  function initHamburgerMenu() {
    const hamburgerBtn = document.getElementById("hamburgerBtn") || document.querySelector(".hamburger-btn");
    const mobileDrawer = document.getElementById("mobileNavDrawer") || document.querySelector(".mobile-nav-drawer");
    const mobileOverlay = document.getElementById("mobileNavOverlay") || document.querySelector(".mobile-nav-overlay");

    if (hamburgerBtn && mobileDrawer) {
      function toggleMenu() {
        const isOpen = mobileDrawer.classList.toggle("open");
        hamburgerBtn.classList.toggle("active", isOpen);
        if (mobileOverlay) mobileOverlay.classList.toggle("open", isOpen);
        hamburgerBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
        document.body.style.overflow = isOpen ? "hidden" : "";
      }

      hamburgerBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleMenu();
      });

      if (mobileOverlay) {
        mobileOverlay.addEventListener("click", () => {
          if (mobileDrawer.classList.contains("open")) toggleMenu();
        });
      }

      document.querySelectorAll(".mobile-nav-drawer a").forEach(link => {
        link.addEventListener("click", () => {
          if (mobileDrawer.classList.contains("open")) toggleMenu();
        });
      });
    }
  }

  // Auto-init on DOMContentLoaded
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      sync();
      initHamburgerMenu();
    });
  } else {
    sync();
    initHamburgerMenu();
  }

  // Expose global API
  window.GymTheme = {
    PRESETS: PRESET_PALETTES,
    FONTS: GOOGLE_FONTS,
    apply: applyTheme,
    sync: sync,
    getApiBase: getApiBase,
    getGymId: getGymId,
    loadFont: loadGoogleFont,
    initHamburgerMenu: initHamburgerMenu
  };
})(window);
