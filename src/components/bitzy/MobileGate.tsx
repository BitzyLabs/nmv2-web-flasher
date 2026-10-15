'use client';

import { ArrowRight } from 'lucide-react';
import { useEffect, useState } from 'react';

const basePath = '';
const STORE_URL = 'https://www.bitzylabs.com';
const DISMISS_KEY = 'bitzy-gate-dismissed';

/**
 * The phone gets a poster instead of a flasher.
 *
 * WebUSB, Web Serial and the ST-Link path are all desktop-browser
 * territory, so below the md breakpoint -- the same rule the header's
 * hamburger lives by -- the reader meets this gate first: the store's
 * warm dark ground with the crimson radials, the dot face saying the
 * one thing that matters, and the store as the loud way out. "Browse
 * anyway" is the quiet one: it hides the gate for this tab
 * (sessionStorage), so a phone can still read the instructions if it
 * insists, and a fresh tab gets the poster again.
 *
 * The poster is fixed colours on purpose -- it is an art layer, not
 * app chrome, and it should look the same whether the site behind it
 * is standing in the light or the dark.
 */
export default function MobileGate() {
  const [mounted, setMounted] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    setMounted(true);
    setDismissed(sessionStorage.getItem(DISMISS_KEY) === '1');
    const query = window.matchMedia('(max-width: 767px)');
    const sync = () => setMobile(query.matches);
    sync();
    query.addEventListener('change', sync);
    return () => query.removeEventListener('change', sync);
  }, []);

  // The page behind the poster does not scroll.
  useEffect(() => {
    if (!(mounted && mobile && !dismissed)) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [mounted, mobile, dismissed]);

  if (!(mounted && mobile && !dismissed)) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="The flasher needs a PC"
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center overflow-hidden bg-[#1C1A16] px-6 text-center"
    >
      {/* The canvas the page paints, re-staged for the poster: the same
          tile as texture, the same two crimson radials as warmth. Both
          painted once, both behind everything, neither scrollable. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage: "url('/pictures/logo-tile.svg')",
          backgroundSize: '340px auto',
        }}
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            'radial-gradient(700px 380px at 85% -5%, rgba(220, 20, 60, 0.28), transparent 60%), radial-gradient(600px 460px at -10% 110%, rgba(220, 20, 60, 0.16), transparent 55%)',
        }}
      />

      <div className="relative flex flex-col items-center">
        <img
          src={`${basePath}/pictures/bitzylabs-logo-dark.png`}
          alt="Bitzy Labs"
          className="h-7 w-auto object-contain"
        />
        <p className="font-data mt-8 text-3xl font-bold leading-tight tracking-wider text-[#F1EEE7] sm:text-4xl">
          THIS FLASHER
          <br />
          NEEDS A PC<span className="animate-pulse text-[#DC143C]">_</span>
        </p>
        <p className="mt-4 max-w-sm text-sm leading-relaxed text-[#A6A093]">
          Your phone is a lovely camera and a terrible flasher. Open me on a desktop browser and we
          will have your boards blinking in seconds.
        </p>
        <a
          href={STORE_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="font-data mt-8 inline-flex items-center gap-2 rounded-full border border-[#DC143C] bg-[rgba(220,20,60,0.12)] px-5 py-2.5 text-sm font-bold tracking-wider text-[#DC143C] transition-colors hover:bg-[rgba(220,20,60,0.2)]"
        >
          <span>IN THE MEANTIME</span>
          <ArrowRight className="h-4 w-4" strokeWidth={2.5} aria-hidden="true" />
          <span>VISIT OUR STORE</span>
        </a>
        <button
          type="button"
          onClick={() => {
            sessionStorage.setItem(DISMISS_KEY, '1');
            setDismissed(true);
          }}
          className="mt-6 text-xs text-[#A6A093] underline underline-offset-4 transition-colors hover:text-[#F1EEE7]"
        >
          or browse anyway
        </button>
      </div>
    </div>
  );
}
