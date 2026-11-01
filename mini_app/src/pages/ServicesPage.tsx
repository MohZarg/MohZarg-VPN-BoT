import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi, Service } from '@/hooks/useApi';
import { useToast } from '@/components/ToastContainer';

export function ServicesPage() {
  const { get } = useApi();
  const { error } = useToast();
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'active' | 'expired'>('all');

  useEffect(() => {
    loadServices();
  }, []);

  async function loadServices() {
    try {
      setLoading(true);
      const res = await get<Service[]>('/services', { active: filter === 'active' });
      setServices(res);
    } catch (e) {
      error('خطا در بارگذاری سرویس‌ها');
    } finally {
      setLoading(false);
    }
  }

  function formatPrice(minor: number): string {
    return new Intl.NumberFormat('fa-IR').format(minor / 10) + ' تومان';
  }

  function formatTraffic(gb: number): string {
    if (gb >= 1024) return `${(gb / 1024).toFixed(1)} ترابایت`;
    return `${gb} گیگابایت`;
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
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">سرویس‌ها</h1>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 mb-4 overflow-x-auto pb-2">
        {['all', 'active'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f as any)}
            className={`btn px-4 py-2 whitespace-nowrap ${filter === f ? 'btn-primary' : 'btn-outline'}`}
          >
            {f === 'all' ? 'همه' : 'فعال'}
          </button>
        ))}
      </div>

      {services.length === 0 ? (
        <div className="card p-8 text-center">
          <ServerIcon className="mx-auto mb-3 text-muted" size={48} />
          <p className="text-secondary">هیچ سرویسی یافت نشد</p>
        </div>
      ) : (
        <div className="space-y-3">
          {services.map((service) => (
            <Link key={service.id} to={`/buy/${service.id}`} className="card block">
              <div className="p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h4 className="font-semibold text-primary truncate">{service.name}</h4>
                      {service.is_active && <span className="badge badge-success">فعال</span>}
                      {!service.is_active && <span className="badge badge-danger">غیرفعال</span>}
                    </div>
                    <p className="text-sm text-secondary mb-2 line-clamp-2">{service.description}</p>
                    <div className="flex flex-wrap gap-2">
                      <span className="badge badge-info">{formatTraffic(service.traffic_gb)}</span>
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