import { useState } from 'react';
import { X } from 'lucide-react';

const basePath = '';

const SITE_LINKS = [
  { label: 'Shop', href: 'https://www.bitzylabs.com' },
];

function Notice({ title, body, onClose }: { title: string; body: string; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="relative w-full max-w-md rounded-xl border border-[var(--color-hairline-light)] bg-white p-6 text-[var(--color-ink)]">
        <button
          onClick={onClose}
          aria-label="Close"
          className="absolute right-4 top-4 text-[var(--color-muted-warm)] transition-colors hover:text-[var(--color-bitzy)]"
        >
          <X size={20} />
        </button>
        <h2 className="font-display text-lg font-bold">{title}</h2>
        <p className="mt-2 text-sm text-[var(--color-muted-warm)]">{body}</p>
      </div>
    </div>
  );
}

export default function Footer() {
  const [notice, setNotice] = useState<'privacy' | 'terms' | null>(null);

  const linkClass = 'text-sm text-[var(--color-muted-warm)] transition-colors hover:text-[var(--color-bitzy)]';

  return (
    <>
      {notice === 'privacy' && (
        <Notice
          title="Privacy"
          body="We collect no data. Your ISP still does."
          onClose={() => setNotice(null)}
        />
      )}
      {notice === 'terms' && (
        <Notice
          title="Terms"
          body="The source code is provided under the GPL-3.0 licence."
          onClose={() => setNotice(null)}
        />
      )}

      <footer className="mt-8 w-full border-t border-[var(--color-hairline-light)] bg-white text-[var(--color-ink)]">
        <div className="mx-auto grid w-full max-w-screen-xl gap-10 px-4 py-12 md:grid-cols-2 lg:px-6">
          <div>
            <div className="flex items-center gap-2.5">
              <img
                src={`${basePath}/pictures/bitzylabs-logo-light.png`}
                alt="Bitzy Labs"
                className="h-7 w-auto object-contain"
              />
              <span className="brand-badge">Flasher</span>
            </div>
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-[var(--color-muted-warm)]">
              Open source firmware for open source hardware, flashed straight from the browser.
            </p>
          </div>

          <div>
            <h3 className="font-display text-sm font-bold tracking-tight">BitzyLabs</h3>
            <ul className="mt-4 space-y-2.5">
              {SITE_LINKS.map((link) => (
                <li key={link.label}>
                  <a
                    href={link.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={linkClass}
                  >
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="border-t border-[var(--color-hairline-light)]">
          <div className="mx-auto flex w-full max-w-screen-xl flex-col-reverse items-center gap-3 px-4 py-5 text-xs text-[var(--color-muted-warm)] sm:flex-row sm:justify-between lg:px-6">
            <div className="flex items-center gap-4">
              <span>© {new Date().getFullYear()} BitzyLabs</span>
              <button
                onClick={() => setNotice('terms')}
                className="transition-colors hover:text-[var(--color-bitzy)]"
              >
                Terms
              </button>
              <button
                onClick={() => setNotice('privacy')}
                className="transition-colors hover:text-[var(--color-bitzy)]"
              >
                Privacy
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-x-3">
              <span>Credits to</span>
              <a
                href="https://github.com/WantClue"
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-[var(--color-bitzy)]"
              >
                WantClue
              </a>
              <span aria-hidden="true">·</span>
              <a
                href="https://github.com/BitMaker-hub/bitronics-web-flasher"
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-[var(--color-bitzy)]"
              >
                BitMaker
              </a>
              <span aria-hidden="true">·</span>
              <a
                href="https://github.com/Hypothesis-Magic/stm32-web-flasher"
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-[var(--color-bitzy)]"
              >
                Hypothesis-Magic
              </a>
            </div>
          </div>
        </div>
      </footer>
    </>
  );
}
