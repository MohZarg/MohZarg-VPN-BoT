import React, { useEffect, useState } from 'react';
import { useApi } from '@/hooks/useApi';
import { useToast } from '@/components/ToastContainer';
import { useAuth } from '@/hooks/useAuthStore';

const RECHARGE_AMOUNTS = [10000, 20000, 50000, 100000, 200000, 500000];

const GATEWAYS = [
  { id: 'zarinpal', name: 'زرین‌پال', icon: '🏦' },
  { id: 'zarinpey', name: 'زرین‌پی', icon: '💳' },
  { id: 'aqayepardakht', name: 'آقای پرداخت', icon: '🏪' },
  { id: 'plisio', name: 'پلیسیو (کریپتو)', icon: '₿' },
  { id: 'nowpayments', name: 'ناو پیمنتس (کریپتو)', icon: '💎' },
  { id: 'telegram_stars', name: 'استارز تلگرام', icon: '⭐' },
];

export function RechargePage() {
  const { get, post } = useApi();
  const { success, error } = useToast();
  const { user, initData } = useAuth();

  const [balance, setBalance] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selectedAmount, setSelectedAmount] = useState<number | null>(50000);
  const [customAmount, setCustomAmount] = useState('');
  const [selectedGateway, setSelectedGateway] = useState<string>('zarinpal');
  const [processing, setProcessing] = useState(false);

  useEffect(() => {
    loadBalance();
  }, []);

  async function loadBalance() {
    try {
      const res = await get<{ balance_minor: number }>('/wallet/balance');
      setBalance(res.balance_minor / 10);
    } catch (e) {
      error('خطا در بارگذاری موجودی');
    } finally {
      setLoading(false);
    }
  }

  async function handleRecharge() {
    if (!user) return;
    const amount = selectedAmount || parseInt(customAmount) * 10 || 0;
    if (amount < 1000) {
      error('مبلغ باید حداقل ۱۰۰ تومان باشد');
      return;
    }

    setProcessing(true);
    try {
      // Create deposit order
      const orderRes = await post<{ id: number }>('/wallet/deposit', {
        amount_minor: amount * 10, // Convert to minor units
        gateway: selectedGateway,
      });

      // Initiate payment
      const paymentRes = await post<{ payment_url: string; authority: string }>(
        `/payment/initiate`,
        {
          gateway: selectedGateway,
          amount_minor: amount * 10,
          order_id: orderRes.id,
          description: `شارژ کیف پول ${amount.toLocaleString('fa-IR')} تومان`,
          callback_url: `${window.location.origin}/payment/callback/${selectedGateway}`,
        }
      );

      if (paymentRes.payment_url) {
        window.location.href = paymentRes.payment_url;
      } else {
        error('خطا در ایجاد لینک پرداخت');
      }
    } catch (e) {
      error('خطا در پردازش شارژ');
    } finally {
      setProcessing(false);
    }
  }

  function formatPrice(minor: number): string {
    return new Intl.NumberFormat('fa-IR').format(minor) + ' تومان';
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
      {/* Balance Card */}
      <div className="card mb-4">
        <div className="p-6 text-center">
          <p className="text-sm text-muted mb-1">موجودی فعلی</p>
          <p className="text-4xl font-bold text-primary">{formatPrice(balance)}</p>
        </div>
      </div>

      {/* Amount Selection */}
      <div className="card mb-4">
        <div className="p-4">
          <h3 className="font-semibold mb-3">مبلغ شارژ</h3>

          {/* Quick amounts */}
          <div className="grid grid-cols-3 gap-2 mb-4">
            {RECHARGE_AMOUNTS.map((amt) => (
              <button
                key={amt}
                onClick={() => {
                  setSelectedAmount(amt);
                  setCustomAmount('');
                }}
                className={`p-3 rounded-lg border-2 font-semibold transition-all ${
                  selectedAmount === amt
                    ? 'border-accent bg-accent/5 text-accent'
                    : 'border-border-color text-primary'
                }`}
              >
                {formatPrice(amt)}
              </button>
            ))}
          </div>

          {/* Custom amount */}
          <div className="relative">
            <input
              type="tel"
              value={customAmount}
              onChange={(e) => {
                setCustomAmount(e.target.value.replace(/[^\d]/g, ''));
                setSelectedAmount(null);
              }}
              placeholder="مبلغ دلخواه (تومان)"
              className={`form-input ${selectedAmount ? 'border-border-color' : 'border-accent'}`}
              inputMode="numeric"
            />
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted">تومان</span>
          </div>
        </div>
      </div>

      {/* Gateway Selection */}
      <div className="card mb-4">
        <div className="p-4">
          <h3 className="font-semibold mb-3">روش پرداخت</h3>
          <div className="grid grid-cols-3 gap-2">
            {GATEWAYS.map((gateway) => (
              <button
                key={gateway.id}
                onClick={() => setSelectedGateway(gateway.id)}
                className={`p-3 rounded-lg border-2 transition-all text-center ${
                  selectedGateway === gateway.id
                    ? 'border-accent bg-accent/5'
                    : 'border-border-color'
                }`}
              >
                <span style={{ fontSize: '24px' }}>{gateway.icon}</span>
                <p className="text-xs font-medium mt-1">{gateway.name}</p>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Recharge Button */}
      <button
        onClick={handleRecharge}
        disabled={processing}
        className="btn btn-primary w-full btn-lg"
      >
        {processing ? (
          <>
            <div className="spinner" style={{ width: 20, height: 20 }} />
            در حال پردازش...
          </>
        ) : (
          `شارژ ${formatPrice((selectedAmount || parseInt(customAmount) * 10 || 0))}`
        )}
      </button>

      {/* Transaction History */}
      <div className="card mt-6">
        <div className="p-4">
          <h3 className="font-semibold mb-3">تراکنش‌های اخیر</h3>
          <TransactionHistory />
        </div>
      </div>
    </div>
  );
}

function TransactionHistory() {
  const { get } = useApi();
  const [transactions, setTransactions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadTransactions();
  }, []);

  async function loadTransactions() {
    try {
      const res = await get<any[]>('/wallet/transactions', { limit: 10 });
      setTransactions(res);
    } catch (e) {
      console.error('Failed to load transactions');
    } finally {
      setLoading(false);
    }
  }

  function formatPrice(minor: number): string {
    const sign = minor >= 0 ? '+' : '';
    return `${sign}${new Intl.NumberFormat('fa-IR').format(Math.abs(minor) / 10)} تومان`;
  }

  function getTypeColor(type: string): string {
    switch (type) {
      case 'deposit': return 'text-success';
      case 'withdrawal': return 'text-danger';
      case 'purchase': return 'text-primary';
      case 'refund': return 'text-warning';
      case 'referral': return 'text-accent';
      default: return 'text-secondary';
    }
  }

  if (loading) {
    return <div className="py-4 text-center"><div className="loading-spinner mx-auto" style={{ width: 24, height: 24 }} /></div>;
  }

  if (transactions.length === 0) {
    return <p className="text-center text-muted py-4">هیچ تراکنشی یافت نشد</p>;
  }

  return (
    <div className="space-y-3">
      {transactions.map((tx) => (
        <div key={tx.id} className="flex items-center justify-between p-3 bg-secondary rounded-lg">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-full flex items-center justify-center ${getTypeColor(tx.type)}/10`}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={getTypeColor(tx.type)}>
                {tx.type === 'deposit' && <path d="M21 12V7H5V7a2 2 0 0 1 0-4h14a2 2 0 0 1 0 4v5" />}
                {tx.type === 'purchase' && <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />}
                {tx.type === 'refund' && <path d="M21 12H7M7 12l5 5 5-5" />}
                {tx.type === 'referral' && <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />}
              </svg>
            </div>
            <div>
              <p className="font-medium text-sm">{tx.description}</p>
              <p className="text-xs text-muted">{new Date(tx.created_at).toLocaleDateString('fa-IR')}</p>
            </div>
          </div>
          <div className="text-left">
            <p className={`font-semibold text-sm ${getTypeColor(tx.type)}`}>{formatPrice(tx.amount_minor)}</p>
            <p className="text-xs text-muted">موجودی: {new Intl.NumberFormat('fa-IR').format(tx.balance_after_minor / 10)} تومان</p>
          </div>
        </div>
      ))}
    </div>
  );
}