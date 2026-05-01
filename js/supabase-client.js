/* ============================================================
   FORMA — Supabase Client
   Forma Constructor OS™ · Sprint 5
   ============================================================
   Initializes the global Supabase JS client used by all
   frontend modules (auth.js, tier-guard.js, calc pages…).

   SECURITY (CLAUDE.md §Security Rules):
     - This file MUST contain the anon key only.
     - service_role key NEVER appears in frontend — it lives in
       Vercel environment variables and is used only by serverless
       functions. RLS is the real gate.

   USAGE (in HTML):
     <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
     <script src="/js/supabase-client.js"></script>
     // window.supabase is now ready
   ============================================================ */

(function () {
  "use strict";

  // ⚠️ PLACEHOLDER VALUES — replace before production deploy.
  // Source: Supabase Dashboard → Project Settings → API
  const SUPABASE_URL      = "https://YOUR-PROJECT-REF.supabase.co";
  const SUPABASE_ANON_KEY = "YOUR-PUBLIC-ANON-KEY";

  // Sanity check: bail loudly if @supabase/supabase-js wasn't loaded first.
  if (typeof window === "undefined") return;
  if (!window.supabase || typeof window.supabase.createClient !== "function") {
    console.error(
      "[Forma] supabase-js not found. Include the CDN script BEFORE supabase-client.js:\n" +
      '  <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>'
    );
    return;
  }

  // Warn (don't crash) when running with placeholders so dev preview still loads.
  if (
    SUPABASE_URL.includes("YOUR-PROJECT-REF") ||
    SUPABASE_ANON_KEY.includes("YOUR-PUBLIC-ANON-KEY")
  ) {
    console.warn(
      "[Forma] Supabase placeholder credentials in use. Update SUPABASE_URL " +
      "and SUPABASE_ANON_KEY in /js/supabase-client.js before going live."
    );
  }

  // Replace the namespace with the live client instance so callers can do
  //   window.supabase.auth.signInWithPassword(...)
  // exactly as in the official docs.
  const client = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true, // needed for Google OAuth redirect
    },
  });

  window.supabase = client;
  window.FormaSupabase = {
    client,
    url: SUPABASE_URL,
    isConfigured:
      !SUPABASE_URL.includes("YOUR-PROJECT-REF") &&
      !SUPABASE_ANON_KEY.includes("YOUR-PUBLIC-ANON-KEY"),
  };
})();
