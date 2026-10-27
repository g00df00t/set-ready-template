"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase";
import { readBrand, type Brand } from "@/lib/brand";

/**
 * The signed-in producer's brand, for the surfaces that show it.
 *
 * An earlier version also repainted the app's own accent colour from here, so
 * the whole workspace wore the company's colour. That was reverted on purpose —
 * see docs/branding-plan.md. The brand now appears only where a crew member or
 * a client would see it: the call sheet on screen, and the confirm page.
 *
 * Public pages have no session and get their brand from the API instead, since
 * the person opening them has no account at all.
 */
export function useBrand(): Brand {
  const [brand, setBrand] = useState<Brand>({ name: null, accent: null, image: null, nameInImage: false, background: null });
  useEffect(() => {
    let live = true;
    createClient().auth.getSession().then(({ data: { session } }) => {
      if (live) setBrand(readBrand(session?.user?.user_metadata));
    });
    return () => { live = false; };
  }, []);
  return brand;
}
