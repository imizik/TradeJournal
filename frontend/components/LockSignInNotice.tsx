/** Shown only while the owner lock is in report-only mode, on a device that is not signed in yet. */
export default function LockSignInNotice() {
  return (
    <div className="mb-3 flex items-center justify-between gap-3 rounded border border-primary/40 px-3 py-2 text-sm">
      <span>This device is not signed in yet. The journal will ask for the passphrase once the lock is on.</span>
      {/* A full page load, so the sign-in page renders on its own without this layout's state. */}
      <a href="/sign-in" className="shrink-0 rounded bg-primary px-3 py-1 font-medium text-primary-foreground">Sign in</a>
    </div>
  );
}
