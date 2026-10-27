"use client";

// /jobs/[id] alone has no content of its own — Pre-production is the job's
// front door.

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

export default function JobIndexRedirect() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  useEffect(() => { router.replace(`/jobs/${id}/pre-production`); }, [id, router]);
  return null;
}
