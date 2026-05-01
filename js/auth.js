/* ============================================================
   FORMA — Auth helpers
   Forma Constructor OS™ · Sprint 5
   ============================================================
   Wraps Supabase Auth so UI code stays simple.
   Exposes window.FormaAuth with:
     login(email, password)
     signup(email, password, fullName, phone?)
     loginWithGoogle()
     logout()
     getUser()         → current auth user (or null)
     getProfile()      → row from public.profiles (or null)
     onAuthChange(cb)  → subscribe to login/logout

   Profile creation:
     A profile row (tier='free') is created on signup, and
     ensured on every login/OAuth callback in case the row
     is missing (e.g. first Google sign-in). RLS policy on
     `profiles` must permit the user to insert their own row
     (id = auth.uid()).
   ============================================================ */

(function () {
  "use strict";

  function client() {
    if (!window.supabase || !window.supabase.auth) {
      console.error("[Forma] Supabase client not ready. Load /js/supabase-client.js first.");
      return null;
    }
    return window.supabase;
  }

  /* ---------- Profile ensure ---------- */
  async function ensureProfile(user, extras) {
    const sb = client();
    if (!sb || !user) return null;

    const { data: existing, error: selErr } = await sb
      .from("profiles")
      .select("*")
      .eq("id", user.id)
      .maybeSingle();

    if (selErr) {
      console.warn("[Forma] profile lookup failed:", selErr.message);
      return null;
    }
    if (existing) return existing;

    const insertRow = {
      id: user.id,
      email: user.email,
      full_name:
        (extras && extras.fullName) ||
        user.user_metadata?.full_name ||
        user.user_metadata?.name ||
        null,
      phone: (extras && extras.phone) || user.phone || null,
      tier: "free",
    };

    const { data: created, error: insErr } = await sb
      .from("profiles")
      .insert(insertRow)
      .select()
      .single();

    if (insErr) {
      console.warn("[Forma] profile insert failed:", insErr.message);
      return null;
    }
    return created;
  }

  /* ---------- Public API ---------- */

  async function signup(email, password, fullName, phone) {
    const sb = client();
    if (!sb) return { ok: false, error: "supabase-not-ready" };

    const { data, error } = await sb.auth.signUp({
      email,
      password,
      options: {
        data: { full_name: fullName || null, phone: phone || null },
      },
    });
    if (error) return { ok: false, error: error.message };

    if (data.user) {
      await ensureProfile(data.user, { fullName, phone });
    }
    return { ok: true, user: data.user, session: data.session };
  }

  async function login(email, password) {
    const sb = client();
    if (!sb) return { ok: false, error: "supabase-not-ready" };

    const { data, error } = await sb.auth.signInWithPassword({ email, password });
    if (error) return { ok: false, error: error.message };

    if (data.user) await ensureProfile(data.user);
    return { ok: true, user: data.user, session: data.session };
  }

  async function loginWithGoogle(redirectTo) {
    const sb = client();
    if (!sb) return { ok: false, error: "supabase-not-ready" };

    const target =
      redirectTo ||
      `${window.location.origin}/auth/callback.html`;

    const { data, error } = await sb.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: target },
    });
    if (error) return { ok: false, error: error.message };
    return { ok: true, data };
  }

  async function logout() {
    const sb = client();
    if (!sb) return { ok: false, error: "supabase-not-ready" };
    const { error } = await sb.auth.signOut();
    if (error) return { ok: false, error: error.message };
    return { ok: true };
  }

  async function getUser() {
    const sb = client();
    if (!sb) return null;
    const { data } = await sb.auth.getUser();
    return data?.user || null;
  }

  async function getProfile() {
    const sb = client();
    if (!sb) return null;
    const user = await getUser();
    if (!user) return null;

    const { data, error } = await sb
      .from("profiles")
      .select("*")
      .eq("id", user.id)
      .maybeSingle();

    if (error) {
      console.warn("[Forma] getProfile failed:", error.message);
      return null;
    }
    if (!data) {
      // First-time OAuth: create the row now.
      return await ensureProfile(user);
    }
    return data;
  }

  function onAuthChange(callback) {
    const sb = client();
    if (!sb) return { unsubscribe: function () {} };
    const { data } = sb.auth.onAuthStateChange((event, session) => {
      if (session?.user && (event === "SIGNED_IN" || event === "TOKEN_REFRESHED")) {
        ensureProfile(session.user).catch(function () {});
      }
      try { callback(event, session); } catch (e) { console.error(e); }
    });
    return data?.subscription || { unsubscribe: function () {} };
  }

  /* ---------- Expose ---------- */
  window.FormaAuth = {
    signup,
    login,
    loginWithGoogle,
    logout,
    getUser,
    getProfile,
    onAuthChange,
    ensureProfile,
  };
})();
