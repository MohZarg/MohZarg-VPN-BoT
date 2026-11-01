import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useApi } from '@/hooks/useApi';
import { useToast } from '@/components/ToastContainer';
import { useAuth } from '@/hooks/useAuthStore';

export function PaymentGatewayPage() {
  const { gateway } = useParams<{ gateway: string }>();
  const navigate = useNavigate();
  const { get } = useApi();
  const { error, success } = useToast();
  const { user, initData } = useAuth();

  const [loading, setLoading] = useState(true);
  const [paymentUrl, setPaymentUrl] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    checkPaymentStatus();
  }, [gateway]);

  async function checkPaymentStatus() {
    if (!gateway || !initData) {
      navigate('/recharge');
      return;
    }

    try {
      // Check if there's a pending payment for this gateway
      const res = await get<{ payment_url?: string; status: string }>(
        `/payment/status/${gateway}`,
        { init_data: initData }
      );

      if (res.payment_url) {
        setPaymentUrl(res.payment_url);
      } else if (res.status === 'completed') {
        success('پرداخت با موفقیت انجام شد');
        navigate('/profile');
      } else if (res.status === 'failed') {
        error('پرداخت ناموفق بود');
        navigate('/recharge');
      }
    } catch (e) {
      console.error('Payment status check failed:', e);
    } finally {
      setLoading(false);
    }
  }

  const handleReturn = () => {
    setChecking(true);
    checkPaymentStatus();
  };

  const gatewayInfo: Record<string, { name: string; icon: string; color: string }> = {
    zarinpal: { name: 'زرین‌پال', icon: '🏦', color: '#1e3a5f' },
    zarinpey: { name: 'زرین‌پی', icon: '💳', color: '#2c3e50' },
    aqayepardakht: { name: 'آقای پرداخت', icon: '🏪', color: '#e74c3c' },
    plisio: { name: 'پلیسیو', icon: '₿', color: '#f39c12' },
    nowpayments: { name: 'ناو پیمنتس', icon: '💎', color: '#9b59b6' },
    telegram_stars: { name: 'استارز تلگرام', icon: '⭐', color: '#f1c40f' },
  };

  const info = gatewayInfo[gateway || ''] || { name: gateway || 'درگاه', icon: '💳', color: '#2c3e50' };

  if (loading) {
    return (
      <div className="container py-8 flex items-center justify-center h-64">
        <div className="loading-spinner" />
      </div>
    );
  }

  return (
    <div className="container py-4 pb-24">
      <div className="text-center py-8">
        <div className="w-24 h-24 mx-auto mb-4 rounded-full flex items-center justify-center" style={{ backgroundColor: `${info.color}15` }}>
          <span style={{ fontSize: '48px' }}>{info.icon}</span>
        </div>
        <h1 className="text-2xl font-bold text-primary mb-2">{info.name}</h1>
        <p className="text-secondary">
          {paymentUrl ? 'در حال انتقال به درگاه پرداخت...' : 'بررسی وضعیت پرداخت...'}
        </p>
      </div>

      {paymentUrl && (
        <div className="card mb-4">
          <div className="p-4 text-center">
            <p className="text-sm text-muted mb-3">اگر به درگاه پرداخت منتقل نشدید، روی دکمه زیر کلیک کنید</p>
            <a
              href={paymentUrl}
              className="btn btn-primary w-full btn-lg"
              target="_blank"
              rel="noopener noreferrer"
            >
              انتقال به درگاه پرداخت
            </a>
          </div>
        </div>
      )}

      <div className="card mb-4">
        <div className="p-4">
          <button
            onClick={handleReturn}
            disabled={checking}
            className="btn btn-secondary w-full"
          >
            {checking ? (
              <>
                <div className="spinner" style={{ width: 20, height: 20 }} />
                بررسی وضعیت...
              </>
            ) : (
              'بررسی مجدد وضعیت پرداخت'
            )}
          </button>

          <button
            onClick={() => navigate('/recharge')}
            className="btn btn-outline w-full mt-3"
          >
            بازگشت به شارژ
          </button>
        </div>
      </div>

      <div className="card">
        <div className="p-4">
          <h3 className="font-semibold mb-3">راهنمای پرداخت</h3>
          <ul className="space-y-2 text-sm text-secondary">
            <li className="flex items-center gap-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="text-success flex-shrink-0">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              پس از پرداخت موفق، به برنامه برگردید
            </li>
            <li className="flex items-center gap-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="text-success flex-shrink-0">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              موجودی کیف پول شما به‌روزرسانی می‌شود
            </li>
            <li className="flex items-center gap-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="text-success flex-shrink-0">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              در صورت مشکل، با پشتیبانی تماس بگیرید
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}