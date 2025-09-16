import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { ClientThemeWrapper } from '../components/ClientThemeWrapper';
import { I18nProvider } from '../components/I18nProvider';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Bitzylabs NMV2 Flasher',
  description: 'Flash your Bitzylabs devices directly from the web',
  icons: {
    icon: [
      {
        url: '/pictures/favicon.svg',
        sizes: 'any',
        type: 'image/svg+xml',
      },
    ],
    shortcut: '/pictures/favicon.ico',
    apple: '/pictures/favicon.ico',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={inter.className}>
        <ClientThemeWrapper>
          <I18nProvider>
            <div className="min-h-screen text-foreground">
              <main className="w-full p-4">{children}</main>
            </div>
          </I18nProvider>
        </ClientThemeWrapper>
      </body>
    </html>
  );
}
