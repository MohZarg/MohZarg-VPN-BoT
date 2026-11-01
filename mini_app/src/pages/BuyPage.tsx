import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useApi, Service } from '@/hooks/useApi';
import { useToast } from '@/components/ToastContainer';
import { useAuth } from '@/hooks/useAuthStore';

const GATEWAYS = [
  { id: 'zarinpal', name: 'زرین‌پال', icon: '🏦', color: '#1e3a5f' },
  { id: 'zarinpey', name: 'زرین‌پی', icon: '💳', color: '#2c3e50' },
  { id: 'aqayepardakht', name: 'آقای پرداخت', icon: '🏪', color: '#e74c3c' },
  { id: 'plisio', name: 'پلیسیو (کریپتو)', icon: '₿', color: '#f39c12' },
  { id: 'nowpayments', name: 'ناو پیمنتس (کریپتو)', icon: '💎', color: '#9b59b6' },
  { id: 'telegram_stars', name: 'استارز تلگرام', icon: '⭐', color: '#f1c40f' },
];

export function BuyPage() {
  const { serviceId } = useParams<{ serviceId: string }>();
  const navigate = useNavigate();
  const { get, post } = useApi();
  const { success, error } = useToast();
  const { user, initData } = useAuth();

  const [service, setService] = useState<Service | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedGateway, setSelectedGateway] = useState<string>('zarinpal');
  const [processing, setProcessing] = useState(false);

  useEffect(() => {
    loadService();
  }, [serviceId]);

  async function loadService() {
    if (!serviceId) return;
    try {
      setLoading(true);
      const res = await get<Service>(`/services/${serviceId}`);
      setService(res);
    } catch (e) {
      error('خطا در بارگذاری سرویس');
      navigate('/services');
    } finally {
      setLoading(false);
    }
  }

  async function handlePurchase() {
    if (!service || !user) return;

    setProcessing(true);
    try {
      // Create order
      const orderRes = await post<{ id: number }>('/orders', {
        service_id: service.id,
        gateway: selectedGateway,
      });

      // Initiate payment
      const paymentRes = await post<{ payment_url: string; authority: string }>(
        `/payment/initiate`,
        {
          gateway: selectedGateway,
          amount_minor: service.price_minor,
          order_id: orderRes.id,
          description: `خرید ${service.name}`,
          callback_url: `${window.location.origin}/payment/callback/${selectedGateway}`,
        }
      );

      if (paymentRes.payment_url) {
        // Redirect to payment gateway
        window.location.href = paymentRes.payment_url;
      } else {
        error('خطا در ایجاد لینک پرداخت');
      }
    } catch (e) {
      error('خطا در پردازش سفارش');
    } finally {
      setProcessing(false);
    }
  }

  function formatPrice(minor: number): string {
    return new Intl.NumberFormat('fa-IR').format(minor / 10) + ' تومان';
  }

  function formatTraffic(gb: number): string {
    if (gb >= 1024) return `${(gb / 1024).toFixed(1)} ترابایت`;
    return `${gb} گیگابایت`;
  }

  if (loading || !service) {
    return (
      <div className="container py-8 flex items-center justify-center h-64">
        <div className="loading-spinner" />
      </div>
    );
  }

  return (
    <div className="container py-4 pb-24">
      {/* Service Info */}
      <div className="card mb-4">
        <div className="p-4">
          <div className="flex items-start justify-between gap-4 mb-3">
            <div className="flex-1 min-w-0">
              <h1 className="text-lg font-bold text-primary">{service.name}</h1>
              <p className="text-sm text-secondary mt-1">{service.description}</p>
            </div>
            <div className="text-left">
              <p className="text-2xl font-bold text-primary">{formatPrice(service.price_minor)}</p>
              <p className="text-xs text-muted">قیمت نهایی</p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="p-3 bg-secondary/10 rounded-lg">
              <p className="text-sm text-muted">ترافیک</p>
              <p className="font-semibold text-accent">{formatTraffic(service.traffic_gb)}</p>
            </div>
            <div className="p-3 bg-primary/10 rounded-lg">
              <p className="text-sm text-muted">مدت زمان</p>
              <p className="font-semibold text-primary">{service.duration_days} روز</p>
            </div>
            <div className="p-3 bg-success/10 rounded-lg">
              <p className="text-sm text-muted">پنل</p>
              <p className="font-semibold text-success">{service.provider_name}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Gateway Selection */}
      <div className="card mb-4">
        <div className="p-4">
          <h3 className="font-semibold mb-3">روش پرداخت</h3>
          <div className="grid grid-cols-2 gap-2">
            {GATEWAYS.map((gateway) => (
              <button
                key={gateway.id}
                onClick={() => setSelectedGateway(gateway.id)}
                className={`p-3 rounded-lg border-2 transition-all text-right ${
                  selectedGateway === gateway.id
                    ? 'border-accent bg-accent/5'
                    : 'border-border-color'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span style={{ fontSize: '20px' }}>{gateway.icon}</span>
                  <span className="font-medium text-sm">{gateway.name}</span>
                </div>
                {gateway.id === 'telegram_stars' && user?.is_premium && (
                  <span className="badge badge-warning text-xs">پیشنیاز: تلگرام پریمیم</span>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Purchase Button */}
      <button
        onClick={handlePurchase}
        disabled={processing}
        className="btn btn-primary w-full btn-lg"
      >
        {processing ? (
          <>
            <div className="spinner" style={{ width: 20, height: 20 }} />
            در حال پردازش...
          </>
        ) : (
          `خرید و پرداخت ${formatPrice(service.price_minor)}`
        )}
      </button>

      {/* Features */}
      {service.features && service.features.length > 0 && (
        <div className="card mt-4">
          <div className="p-4">
            <h3 className="font-semibold mb-3">امکانات</h3>
            <ul className="space-y-2">
              {service.features.map((feature, i) => (
                <li key={i} className="flex items-center gap-2 text-sm text-secondary">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="text-success flex-shrink-0">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  {feature}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}