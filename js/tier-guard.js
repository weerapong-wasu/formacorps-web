/* ============================================================
   FORMA — Tier Guard (client-side UX gate)
   Forma Constructor OS™ · Sprint 5
   ============================================================
   ⚠️  IMPORTANT (CLAUDE.md §Security Rules #3):
       Server-side RLS is the REAL gate. This module only
       improves UX (redirects, hides locked controls). Anyone
       bypassing this code is still blocked by Postgres RLS.

   Tier hierarchy (lowest → highest):
       free → pro → engineer → enterprise

   Tier expiry:
       If profile.tier_expires_at exists and is in the past,
       the user is treated as 'free'.

   Public API — window.FormaTier:
       checkTier(required, options?) → Promise<{ allowed, profile, reason }>
         options.redirect = '/upgrade/' (default null = no redirect)
         options.silent   = true to suppress console output
       hasAccess(profile, required) → boolean (pure, no I/O)
       getEffectiveTier(profile)    → 'free' | 'pro' | 'engineer' | 'enterprise'
       guard(required, redirect?)   → Promise<boolean>
         convenience wrapper that redirects on deny

   Examples:
       // On a /tools/full-calc.html page:
       FormaTier.guard('pro', '/upgrade/');
       // On a /tools/fcip/ page:
       FormaTier.guard('engineer', '/upgrade/');
   ============================================================ */

(function () {
  "use strict";

  const TIER_RANK = Object.freeze({
    free: 0,
    pro: 1,
    engineer: 2,
    enterprise: 3,
  });

  function getEffectiveTier(profile) {
    if (!profile) return "free";

    const tier = profile.tier || "free";
    if (!(tier in TIER_RANK)) return "free";

    if (profile.tier_expires_at) {
      const expires = new Date(profile.tier_expires_at).getTime();
      if (Number.isFinite(expires) && expires < Date.now()) {
        return "free";
      }
    }
    return tier;
  }

  function hasAccess(profile, required) {
    if (!(required in TIER_RANK)) {
      console.warn("[Forma] Unknown required tier:", required);
      return false;
    }
    const effective = getEffectiveTier(profile);
    return TIER_RANK[effective] >= TIER_RANK[required];
  }

  async function checkTier(required, options) {
    options = options || {};
    if (!(required in TIER_RANK)) {
      throw new Error("Unknown tier: " + required);
    }

    if (!window.FormaAuth) {
      if (!options.silent) {
        console.error("[Forma] FormaAuth not loaded. Include /js/auth.js first.");
      }
      return { allowed: false, profile: null, reason: "auth-not-ready" };
    }

    const profile = await window.FormaAuth.getProfile();

    if (!profile) {
      if (options.redirect) {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = "/auth/login.html?next=" + next;
      }
      return { allowed: false, profile: null, reason: "not-authenticated" };
    }

    const allowed = hasAccess(profile, required);

    if (!allowed && options.redirect) {
      const target = options.redirect +
        (options.redirect.indexOf("?") === -1 ? "?" : "&") +
        "required=" + encodeURIComponent(required) +
        "&from=" + encodeURIComponent(window.location.pathname);
      window.location.href = target;
    }

    return {
      allowed,
      profile,
      reason: allowed ? "ok" : "tier-insufficient",
    };
  }

  async function guard(required, redirect) {
    const result = await checkTier(required, {
      redirect: redirect || "/upgrade/",
    });
    return result.allowed;
  }

  window.FormaTier = {
    TIER_RANK,
    checkTier,
    hasAccess,
    getEffectiveTier,
    guard,
  };
})();
