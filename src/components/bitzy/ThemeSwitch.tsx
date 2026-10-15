'use client';

import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';

/**
 * Light, Dark, Auto: the three states the reader can put the site in.
 *
 * A segmented pill for the bar, icons carrying the meaning and words
 * beside them from sm up where there is room for them. "Auto" stores the
 * literal word `system` -- next-themes then follows prefers-color-scheme
 * from there and keeps following it as the OS changes -- and whatever is
 * picked lands in localStorage under the provider's storageKey, which is
 * what makes the choice survive a reload.
 *
 * The active pill waits for mount before it shows: next-themes reads the
 * stored choice on the client only, so the first server render cannot
 * know it, and painting an active state the server never saw is a
 * hydration mismatch waiting to happen.
 */
const MODES = [
  { value: 'light', label: 'Light', Icon: Sun },
  { value: 'dark', label: 'Dark', Icon: Moon },
  { value: 'system', label: 'Auto', Icon: Monitor },
] as const;

export default function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <div
      className="flex items-center rounded-full border border-[var(--color-hairline-light)] bg-[var(--color-panel)] p-0.5"
      role="group"
      aria-label="Theme"
    >
      {MODES.map(({ value, label, Icon }) => {
        const active = mounted && theme === value;
        return (
          <button
            key={value}
            type="button"
            onClick={() => setTheme(value)}
            aria-pressed={active}
            aria-label={`${label} theme`}
            title={`${label} theme`}
            className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
              active
                ? 'bg-[rgba(220,20,60,0.08)] text-[var(--color-bitzy)]'
                : 'text-[var(--color-muted-warm)] hover:text-[var(--color-ink)]'
            }`}
          >
            <Icon size={13} strokeWidth={2} aria-hidden="true" />
            <span className="hidden sm:inline">{label}</span>
          </button>
        );
      })}
    </div>
  );
}
