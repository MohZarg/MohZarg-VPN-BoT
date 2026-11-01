import React, { useState } from 'react';
import { useTelegram } from '@telegram-apps/sdk-react';
import { useAuth } from '@/hooks/useAuthStore';
import { useToast } from '@/components/ToastContainer';

export function SettingsPage() {
  const { themeParams, setThemeParams } = useTelegram();
  const { logout } = useAuth();
  const { success, info } = useToast();

  const [notifications, setNotifications] = useState(true);
  const [darkMode, setDarkMode] = useState(false);
  const [language, setLanguage] = useState<'fa' | 'en'>('fa');

  const handleLogout = () => {
    if (window.confirm('آیا از خروج از حساب کاربری مطمئن هستید؟')) {
      logout();
      window.location.reload();
    }
  };

  return (
    <div className="container py-4 pb-24">
      {/* Appearance */}
      <div className="card mb-4">
        <div className="p-4">
          <h3 className="font-semibold mb-4">نمایش</h3>

          <div className="space-y-4">
            <label className="flex items-center justify-between cursor-pointer">
              <div>
                <p className="font-medium">حالت تاریک</p>
                <p className="text-sm text-muted">استفاده از تم تیره</p>
              </div>
              <button
                role="switch"
                aria-checked={darkMode}
                onClick={() => {
                  setDarkMode(!darkMode);
                  setThemeParams({ bg_color: darkMode ? '#ffffff' : '#1a1a1a' });
                }}
                className={`relative w-12 h-7 rounded-full transition-colors ${
                  darkMode ? 'bg-accent' : 'bg-border-color'
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-6 h-6 rounded-full bg-white shadow-md transition-transform ${
                    darkMode ? 'translate-x-full' : 'translate-x-0'
                  }`}
                />
              </button>
            </label>

            <label className="flex items-center justify-between cursor-pointer">
              <div>
                <p className="font-medium">اعلان‌ها</p>
                <p className="text-sm text-muted">دریافت اعلان‌های مهم</p>
              </div>
              <button
                role="switch"
                aria-checked={notifications}
                onClick={() => setNotifications(!notifications)}
                className={`relative w-12 h-7 rounded-full transition-colors ${
                  notifications ? 'bg-accent' : 'bg-border-color'
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-6 h-6 rounded-full bg-white shadow-md transition-transform ${
                    notifications ? 'translate-x-full' : 'translate-x-0'
                  }`}
                />
              </button>
            </label>

            <div>
              <p className="font-medium mb-2">زبان</p>
              <div className="flex gap-2">
                {['fa', 'en'].map((lang) => (
                  <button
                    key={lang}
                    onClick={() => setLanguage(lang as 'fa' | 'en')}
                    className={`flex-1 py-2 px-4 rounded-lg font-medium transition-colors ${
                      language === lang
                        ? 'bg-accent text-white'
                        : 'bg-secondary text-primary'
                    }`}
                  >
                    {lang === 'fa' ? 'فارسی' : 'English'}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Data & Privacy */}
      <div className="card mb-4">
        <div className="p-4">
          <h3 className="font-semibold mb-4">داده‌ها و حریم خصوصی</h3>

          <div className="space-y-3">
            <button className="btn btn-outline w-full justify-start">
              <DownloadIcon className="ml-2" size={20} />
              دانلود داده‌های من
            </button>
            <button className="btn btn-outline w-full justify-start text-danger">
              <TrashIcon className="ml-2" size={20} />
              حذف حساب کاربری
            </button>
          </div>
        </div>
      </div>

      {/* About */}
      <div className="card mb-4">
        <div className="p-4">
          <h3 className="font-semibold mb-4">درباره برنامه</h3>

          <div className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted">نسخه برنامه</span>
              <span className="font-medium">2.0.0</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted">پلتفرم</span>
              <span className="font-medium">Telegram Mini App</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted">تاریخ ساخت</span>
              <span className="font-medium">2026</span>
            </div>
          </div>

          <div className="mt-4 pt-4 border-t border-border-color space-y-2">
            <button className="btn btn-ghost w-full justify-start text-sm" onClick={() => info('باز شد: قوانین و مقررات')}>
              قوانین و مقررات
            </button>
            <button className="btn btn-ghost w-full justify-start text-sm" onClick={() => info('باز شد: حریم خصوصی')}>
              حریم خصوصی
            </button>
            <button className="btn btn-ghost w-full justify-start text-sm" onClick={() => info('باز شد: تماس با پشتیبانی')}>
              تماس با پشتیبانی
            </button>
          </div>
        </div>
      </div>

      {/* Logout */}
      <div className="card">
        <div className="p-4">
          <button onClick={handleLogout} className="btn btn-danger w-full">
            <LogoutIcon className="ml-2" size={20} />
            خروج از حساب کاربری
          </button>
        </div>
      </div>
    </div>
  );
}

function DownloadIcon({ className = '', size = 24 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  );
}

function TrashIcon({ className = '', size = 24 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className}>
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

function LogoutIcon({ className = '', size = 24 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  );
}