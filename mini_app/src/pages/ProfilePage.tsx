import React, { useEffect, useState } from 'react';
import { useApi, UserProfile, Order } from '@/hooks/useApi';
import { useToast } from '@/components/ToastContainer';
import { useAuth } from '@/hooks/useAuthStore';
import { Link } from 'react-router-dom';

export function ProfilePage() {
  const { get } = useApi();
  const { error } = useToast();
  const { user, isAuthenticated } = useAuth();

  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'info' | 'orders' | 'referral'>('info');

  useEffect(() => {
    if (isAuthenticated) {
      loadProfile();
      loadOrders();
    }
  }, [isAuthenticated]);

  async function loadProfile() {
    try {
      const res = await get<UserProfile>('/user/profile');
      setProfile(res);
    } catch (e) {
      error('خطا در بارگذاری پروفایل');
    }
  }

  async function loadOrders() {
    try {
      const res = await get<Order[]>('/orders', { limit: 20 });
      setOrders(res);
    } catch (e) {
      console.error('Failed to load orders');
    } finally {
      setLoading(false);
    }
  }

  function formatPrice(minor: number): string {
    return new Intl.NumberFormat('fa-IR').format(minor / 10) + ' تومان';
  }

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString('fa-IR', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  }

  function getStatusBadge(status: string) {
    const badges: Record<string, { label: string; class: string }> = {
      pending: { label: 'در انتظار پرداخت', class: 'badge-warning' },
      paid: { label: 'پرداخت شده', class: 'badge-success' },
      provisioning: { label: 'در حال فعال‌سازی', class: 'badge-info' },
      active: { label: 'فعال', class: 'badge-success' },
      expired: { label: 'منقضی شده', class: 'badge-danger' },
      cancelled: { label: 'لغو شده', class: 'badge-danger' },
    };
    const b = badges[status] || { label: status, class: 'badge-primary' };
    return <span className={`badge ${b.class}`}>{b.label}</span>;
  }

  if (!isAuthenticated) {
    return (
      <div className="container py-12 text-center">
        <UserIcon className="mx-auto mb-4 text-muted" size={64} />
        <h2 className="text-xl font-semibold mb-2">ورود مورد نیاز</h2>
        <p className="text-secondary mb-6">برای مشاهده پروفایل خود، لطفاً وارد شوید</p>
        <button className="btn btn-primary" onClick={() => window.location.reload()}>
          تلاش مجدد
        </button>
      </div>
    );
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
      {/* Profile Header */}
      <div className="card mb-4">
        <div className="p-4">
          <div className="flex items-center gap-4">
            <div className="w-20 h-20 rounded-full bg-accent/10 flex items-center justify-center">
              {user?.photo_url ? (
                <img src={user.photo_url} alt="" className="w-full h-full rounded-full object-cover" />
              ) : (
                <UserIcon size={40} className="text-accent" />
              )}
            </div>
            <div className="flex-1">
              <h1 className="text-xl font-bold text-primary">
                {user?.first_name || ''} {user?.last_name || ''}
              </h1>
              {user?.username && (
                <p className="text-sm text-muted">@{user.username}</p>
              )}
              <div className="flex items-center gap-2 mt-2">
                {user?.is_premium && (
                  <span className="badge badge-warning">⭐ تلگرام پریمیم</span>
                )}
                {profile?.is_agent && (
                  <span className="badge badge-primary">نماینده</span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <Link to="/recharge" className="card p-4 text-center">
          <WalletIcon className="mx-auto mb-2 text-accent" size={28} />
          <p className="text-sm text-muted">موجودی کیف پول</p>
          <p className="font-bold text-primary">{formatPrice(profile?.wallet_balance_minor || 0)}</p>
        </Link>
        <Link to="/services" className="card p-4 text-center">
          <ServerIcon className="mx-auto mb-2 text-success" size={28} />
          <p className="text-sm text-muted">سفارش‌های فعال</p>
          <p className="font-bold text-primary">
            {orders.filter((o) => o.status === 'active').length}
          </p>
        </Link>
        <div className="card p-4 text-center">
          <GiftIcon className="mx-auto mb-2 text-warning" size={28} />
          <p className="text-sm text-muted">درآمد رفرال</p>
          <p className="font-bold text-primary">{formatPrice(profile?.referral_earnings_minor || 0)}</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="card mb-4">
        <div className="flex border-b border-border-color">
          {[
            { id: 'info', label: 'اطلاعات' },
            { id: 'orders', label: 'سفارش‌ها' },
            { id: 'referral', label: 'رفرال' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`flex-1 py-3 text-center text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? 'text-accent border-b-2 border-accent'
                  : 'text-muted'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="p-4">
          {activeTab === 'info' && profile && (
            <div className="space-y-4">
              <div>
                <p className="text-sm text-muted">کد رفرال</p>
                <div className="flex items-center gap-2 mt-1">
                  <code className="flex-1 bg-secondary px-3 py-2 rounded-lg font-mono text-lg">
                    {profile.referral_code}
                  </code>
                  <button className="btn btn-outline btn-sm" onClick={() => copyToClipboard(profile.referral_code)}>
                    کپی
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-muted">تلفن</p>
                  <p className="font-medium">{user?.phone_number || 'ثبت نشده'}</p>
                </div>
                <div>
                  <p className="text-sm text-muted">تاریخ عضویت</p>
                  <p className="font-medium">{profile.created_at ? formatDate(profile.created_at) : '-'}</p>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'orders' && (
            <div className="space-y-3">
              {orders.length === 0 ? (
                <p className="text-center text-muted py-8">هیچ سفارشی یافت نشد</p>
              ) : (
                orders.map((order) => (
                  <Link key={order.id} to={`/order/${order.id}`} className="card block">
                    <div className="p-3">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="font-medium">سفارش #{order.id}</p>
                          <p className="text-sm text-muted">{formatDate(order.created_at)}</p>
                        </div>
                        <div className="text-left">
                          <p className="font-semibold text-primary">{formatPrice(order.price_minor)}</p>
                          {getStatusBadge(order.status)}
                        </div>
                      </div>
                    </div>
                  </Link>
                ))
              )}
            </div>
          )}

          {activeTab === 'referral' && profile && (
            <div className="space-y-4">
              <div className="p-4 bg-accent/5 rounded-lg">
                <p className="text-sm text-secondary mb-2">
                  با اشتراک‌گذاری لینک رفرال خود، از هر خرید دوستانتان کسب درآمد کنید.
                </p>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={`https://t.me/ghyiab_bot?start=${profile.referral_code}`}
                    readOnly
                    className="form-input flex-1"
                  />
                  <button className="btn btn-primary btn-sm" onClick={() => copyToClipboard(`https://t.me/ghyiab_bot?start=${profile.referral_code}`)}>
                    کپی لینک
                  </button>
                </div>
              </div>
              <div>
                <p className="font-medium mb-2">امتیازات رفرال</p>
                <ul className="space-y-2 text-sm text-secondary">
                  <li className="flex items-center gap-2">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="text-success">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                    %{10} کمیسیون از خرید مستقیم (سطح ۱)
                  </li>
                  <li className="flex items-center gap-2">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="text-success">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                    %{5} کمیسیون از خرید زیرمجموعه‌ها (سطح ۲)
                  </li>
                </ul>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text);
}

function UserIcon({ className = '', size = 24 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
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

function GiftIcon({ className = '', size = 24 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className}>
      <polyline points="20 12 20 22 4 22 4 12" />
      <rect x="2" y="7" width="20" height="5" rx="1" ry="1" />
      <line x1="12" y1="22" x2="12" y2="7" />
      <path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z" />
      <path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z" />
    </svg>
  );
}