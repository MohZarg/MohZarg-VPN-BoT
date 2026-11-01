import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi, Service } from '@/hooks/useApi';
import { useToast } from '@/components/ToastContainer';
import { useAuth } from '@/hooks/useAuthStore';

export function HomePage() {
  const { get } = useApi();
  const { user } = useAuth();
  const { success, error } = useToast();
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [balance, setBalance] = useState(0);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      setLoading(true);
      const [servicesRes, walletRes] = await Promise.all([
        get<Service[]>('/services', { active: true }),
        get<{ balance_minor: number }>('/wallet/balance'),
      ]);
      setServices(servicesRes);
      setBalance(walletRes.balance_minor / 10); // Convert to display units
    } catch (e) {
      error('خطا در بارگذاری داده‌ها');
    } finally {
      setLoading(false);
    }
  }

  function formatPrice(minor: number): string {
    return new Intl.NumberFormat('fa-IR').format(minor / 10) + ' تومان';
  }

  if (loading) {
    return (
      <div className="container py-8 flex items-center justify-center h-64">
        <div className="loading-spinner" />
      </div>
    );
  }

  return (
    <div className="container py-4 pb-24">
      {/* Welcome Section */}
      <div className="card mb-4 overflow-hidden">
        <div className="p-4 bg-primary text-white rounded-t-lg">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold">سلام، {user?.first_name || 'کاربر'}! 👋</h2>
              <p className="text-sm opacity-90 mt-1">به GhYiAb V2 خوش آمدید</p>
            </div>
            <div className="bg-white/20 px-4 py-2 rounded-lg text-center">
              <p className="text-sm opacity-90">موجودی کیف پول</p>
              <p className="text-xl font-bold">{formatPrice(balance)}</p>
            </div>
          </div>
        </div>
        <div className="p-4">
          <Link to="/services" className="btn btn-primary w-full">
            مشاهده همه سرویس‌ها
          </Link>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-2 gap-3 mb-6">
        <Link to="/services" className="card p-4 text-center">
          <ServerIcon className="mx-auto mb-2 text-accent" size={32} />
          <p className="font-medium">خرید سرویس</p>
        </Link>
        <Link to="/recharge" className="card p-4 text-center">
          <WalletIcon className="mx-auto mb-2 text-success" size={32} />
          <p className="font-medium">شارژ کیف پول</p>
        </Link>
      </div>

      {/* Services */}
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold">سرویس‌های پیشنهادی</h3>
        <Link to="/services" className="text-sm text-accent">مشاهده همه</Link>
      </div>

      {services.length === 0 ? (
        <div className="card p-8 text-center">
          <ServerIcon className="mx-auto mb-3 text-muted" size={48} />
          <p className="text-secondary">هیچ سرویس فعالی موجود نیست</p>
        </div>
      ) : (
        <div className="space-y-3">
          {services.slice(0, 5).map((service) => (
            <Link key={service.id} to={`/buy/${service.id}`} className="card block">
              <div className="p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <h4 className="font-semibold text-primary truncate">{service.name}</h4>
                    <p className="text-sm text-secondary mt-1 line-clamp-2">{service.description}</p>
                    <div className="flex flex-wrap gap-2 mt-2">
                      <span className="badge badge-info">{service.traffic_gb} گیگابایت</span>
                      <span className="badge badge-primary">{service.duration_days} روز</span>
                      <span className="badge badge-success">{service.provider_name}</span>
                    </div>
                  </div>
                  <div className="text-left">
                    <p className="text-xl font-bold text-primary">{formatPrice(service.price_minor)}</p>
                    <p className="text-xs text-muted">هر {service.duration_days} روز</p>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function ServerIcon({ className = '', size = 24 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className}>
      <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
      <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
      <line x1="6" y1="6" x2="6.01" y2="6" />
      <line x1="6" y1="18" x2="6.01" y2="18" />
    </svg>
  );
}

function WalletIcon({ className = '', size = 24 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M21 12V7H5V7a2 2 0 0 1 0-4h14a2 2 0 0 1 0 4v5" />
      <path d="M3 5v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5" />
    </svg>
  );
}