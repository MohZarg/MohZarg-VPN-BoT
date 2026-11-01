import React from 'react';
import { useTelegram } from '@telegram-apps/sdk-react';

export function Header() {
  const { backButton } = useTelegram();

  React.useEffect(() => {
    backButton.show();
    backButton.onClick(() => {
      window.history.back();
    });
    return () => {
      backButton.offClick();
    };
  }, [backButton]);

  return (
    <header className="sticky top-0 z-10 bg-primary border-b border-border-color px-4 py-3 flex items-center justify-between">
      <h1 className="text-lg font-semibold text-primary">GhYiAb V2</h1>
      <div className="w-8" />
    </header>
  );
}