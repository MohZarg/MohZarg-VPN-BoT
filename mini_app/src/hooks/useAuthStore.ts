import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { useTelegram } from '@telegram-apps/sdk-react';

interface User {
  id: number;
  username?: string;
  first_name: string;
  last_name?: string;
  language_code?: string;
  is_premium?: boolean;
  photo_url?: string;
}

interface AuthState {
  user: User | null;
  initData: string | null;
  isAuthenticated: boolean;
  initAuth: () => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      initData: null,
      isAuthenticated: false,

      initAuth: async () => {
        const { initData, user } = useTelegram.getState();

        if (initData) {
          // Parse user from initData
          try {
            const userData = user || JSON.parse(new URLSearchParams(initData).get('user') || '{}');
            set({
              user: userData,
              initData,
              isAuthenticated: true,
            });
          } catch (e) {
            console.error('Failed to parse user data:', e);
          }
        }
      },

      logout: () => set({ user: null, initData: null, isAuthenticated: false }),
    }),
    {
      name: 'auth-store',
      partialize: (state) => ({ user: state.user, initData: state.initData, isAuthenticated: state.isAuthenticated }),
    }
  )
);

export function useAuth() {
  const { user, isAuthenticated, initData, logout } = useAuthStore();
  return { user, isAuthenticated, initData, logout };
}