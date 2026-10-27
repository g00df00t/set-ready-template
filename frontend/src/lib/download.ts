// Save a fetched blob as a file. Same helper the day's Deal Memos page
// defined locally first; pulled out here so the job's version doesn't carry
// a second copy. The day page keeps its own — not touched, to keep Phase 1
// from changing anything about the current version's code paths.
export function triggerDownload(blob: Blob, fallbackName: string, filename: string | null) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename ?? fallbackName;
  link.click();
  URL.revokeObjectURL(url);
}
