'use client';

import { ThemeProvider } from 'next-themes';

import MobileGate from './bitzy/MobileGate';

/**
 * Light, dark, and the system setting between them.
 *
 * Light is the default: the store's scheme -- warm ground, white panels,
 * ink text -- which is what the reader lands on with no stored choice.
 * Dark is the same house one step down: a warm near-black ground, panels
 * lifted off it, crimson unchanged, and the terminal keeping its black
 * either way. It is applied only through the class this provider puts on
 * <html>, so every token in globals.css decides for itself which half it
 * is serving.
 *
 * "Auto" is the literal word `system`, resolved against
 * prefers-color-scheme and re-resolved when the OS changes its mind.
 * The choice persists under its storageKey, so whatever the reader picks
 * is what they get on the next load -- the default only ever applies
 * once, to a browser that has never chosen.
 *
 * Under the provider sits the phone's poster: below the md breakpoint
 * the flasher cannot flash, so MobileGate says so over the whole
 * screen and offers the store instead. It rides here rather than in
 * layout.tsx because it is ours, not upstream's -- nothing a merge
 * can take back out.
 */
export function ClientThemeWrapper({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="light"
      enableSystem
      storageKey="bitzy-theme"
      disableTransitionOnChange
    >
      {children}
      <MobileGate />
    </ThemeProvider>
  );
}
