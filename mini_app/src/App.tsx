import React, { useEffect, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useTelegram } from '@telegram-apps/sdk-react';
import { HomePage } from '@/pages/HomePage';
import { ServicesPage } from '@/pages/ServicesPage';
import { BuyPage } from '@/pages/BuyPage';
import { RechargePage } from '@/pages/RechargePage';
import { ProfilePage } from '@/pages/ProfilePage';
import { SettingsPage } from '@/pages/SettingsPage';
import { PaymentGatewayPage } from '@/pages/PaymentGatewayPage';
import { Header } from '@/components/Header';
import { BottomNav } from '@/components/BottomNav';
import { ToastContainer } from '@/components/ToastContainer';
import { useAuthStore } from '@/hooks/useAuthStore';
import { useApi } from '@/hooks/useApi';

export function App() {
  const { init, isFullscreen } = useTelegram();
  const { initAuth } = useAuthStore();
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    async function initialize() {
      try {
        await init();
        await initAuth();
        setInitialized(true);
      } catch (error) {
        console.error('Failed to initialize app:', error);
        setInitialized(true);
      }
    }
    initialize();
  }, [init, initAuth]);

  if (!initialized) {
    return (
      <div className="flex items-center justify-center h-full bg-primary">
        <div className="loading-spinner" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-primary safe-top safe-bottom">
      <Header />
      <main className="flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/services" element={<ServicesPage />} />
          <Route path="/buy/:serviceId" element={<BuyPage />} />
          <Route path="/recharge" element={<RechargePage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/payment/:gateway" element={<PaymentGatewayPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <BottomNav />
      <ToastContainer />
    </div>
  );
}